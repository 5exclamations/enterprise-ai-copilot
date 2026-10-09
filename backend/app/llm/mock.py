"""Deterministic mock LLM.

This is NOT a language model. It is a rule-based planner (regex intent -> tool calls) and an
extractive answer composer (restates tool summaries / best-matching document sentences and
cites the sources the tools returned). Its purpose:

* run the full agent loop, API, UI and CI with zero credentials and zero flakiness;
* give the evaluation harness a stable baseline, so eval numbers measure the *pipeline*
  (retrieval, tools, guardrails, schema validation) rather than a model's mood;
* support adversarial tests: `gullible=True` makes it obey instructions found inside tool
  results, proving the surrounding system stays safe even when the model is compromised.

Eval scores obtained with the mock say nothing about how a real model would phrase answers.
"""
from __future__ import annotations

import json
import re

from ..text import estimate_tokens, split_sentences, tokenize
from .base import LLMMessage, LLMProvider, LLMResponse, ToolCall, ToolSpec, Usage

ORDER_RE = re.compile(r"\bSO-\d{5}\b")
SKU_RE = re.compile(r"\b[A-Z]{2}-\d{4}\b")
RESULT_RE = re.compile(r'<tool_result name="([^"]+)"[^>]*>(.*)</tool_result>', re.DOTALL)

STRONG_DOC = re.compile(
    r"\b(polic(?:y|ies)|procedures?|sop|warranty|warranties|refunds?|returns?|terms|hours|holidays?|hazmat|"
    r"hazardous|privacy|security|guidelines?|handbook|lead times?|approval|approve|credit limit|net 30|late fee|"
    r"restocking|rma|retention|calibration|training|onboarding|escalat\w*|cutoff|cut-off|sds|spill|"
    r"cycle count\w*|safety stock|support)\b", re.I)
WEAK_DOC = re.compile(r"\b(shipping|delivery|deliver|ship|discounts?|payment|pay|cancel\w*|credit|express|"
                      r"how long|how many days|how much time|when)\b", re.I)
STOCK_RE = re.compile(r"\b(stock|inventory|available|availability|on hand|how many|units|reserved|warehouse)\b", re.I)
LOW_RE = re.compile(r"\b(low[- ]stock|running low|reorder point|below (?:the )?reorder|out of stock|need(?:s)? (?:to be )?reorder\w*|"
                    r"need(?:s)? restock\w*|low on)\b", re.I)
QUOTE_RE = re.compile(r"\b(total|quote|how much would|how much (?:will|does|do)|price for|cost (?:of|for|me)|what would .* cost)\b", re.I)
PRODUCT_RE = re.compile(r"\b(products?|sell|catalog|items?|do we (?:have|carry|stock)|cheapest|under \$|"
                        r"gloves?|boots?|helmets?|hard hats?|bolts?|nuts?|washers?|screws?|anchors?|drills?|wrench(?:es)?|"
                        r"calipers?|sockets?|tape|wrap|boxes|strapping|degreaser|fasteners?|safety|tools?|packaging|chemicals?|"
                        r"vests?|respirators?|glasses|goggles)\b", re.I)
STATUS_WORDS = {"pending": "pending", "confirmed": "confirmed", "shipped": "shipped", "delivered": "delivered",
                "cancelled": "cancelled", "canceled": "cancelled", "on hold": "on_hold", "on_hold": "on_hold"}
CAP_PHRASE = re.compile(r"\b(?:from|for|by|of|customer)\s+((?:[A-Z][\w&.'-]*)(?:\s+[A-Z][\w&.'-]*)+)")
INJECTION_IN_RESULT = re.compile(r"ignore (?:all |any )?(?:previous|prior|above)|disregard (?:all |the )?(?:previous|prior)|"
                                 r"system override|new instructions", re.I)

_NOISE_FOR_DOC = {"policy", "company", "tell", "please", "explain", "describe", "give"}


class MockProvider(LLMProvider):
    name = "mock"
    model = "mock-rules-v1"

    def __init__(self, gullible: bool = False, fault: str | None = None):
        self.gullible = gullible
        self.fault = fault  # None | "bad_json_once" | "hallucinated_citation"
        self._faulted = False

    # ------------------------------------------------------------------ public API
    def chat(self, messages: list[LLMMessage], tools: list[ToolSpec] | None = None,
             temperature: float = 0.0) -> LLMResponse:
        tool_names = {t.name for t in tools or []}
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=-1)
        question = messages[last_user].content or "" if last_user >= 0 else ""
        after = messages[last_user + 1:]
        results = [m for m in after if m.role == "tool"]
        called_before = any(m.tool_calls for m in after)

        # a "correction" user turn from the agent (schema retry) arrives after our own answer
        if question.startswith("[format-correction]"):
            question = next((m.content for m in reversed(messages[:last_user]) if m.role == "user"
                             and not (m.content or "").startswith("[format-correction]")), question)
            results = [m for m in messages if m.role == "tool"][-6:]
            called_before = True

        calls: list[ToolCall] = []
        if self.gullible and results:
            calls = self._gullible_calls(messages, results)
        if not calls and not called_before:
            calls = self._plan(question, tool_names)
            if not calls and "draft_action" not in tool_names and self._plan_action(
                    question, question.lower(), list(ORDER_RE.findall(question)), list(SKU_RE.findall(question))):
                return self._respond(messages, tools, content=json.dumps({
                    "answer": "Your role does not allow drafting business actions. Please ask a manager or admin.",
                    "citations": [], "confidence": "high"}))

        if calls:
            return self._respond(messages, tools, content=None, calls=calls)
        return self._respond(messages, tools, content=self._compose(question, results))

    # ------------------------------------------------------------------- planning
    def _plan(self, q: str, available: set[str]) -> list[ToolCall]:
        calls: list[tuple[str, dict]] = []
        orders = list(dict.fromkeys(ORDER_RE.findall(q)))
        skus = list(dict.fromkeys(SKU_RE.findall(q)))
        ql = q.lower()

        action = self._plan_action(q, ql, orders, skus)
        if action is not None:
            calls.append(action)
        else:
            for o in orders[:3]:
                calls.append(("get_order", {"order_number": o}))
            quote_items = self._quote_items(q, skus)
            if quote_items and QUOTE_RE.search(q):
                args: dict = {"items": quote_items}
                m = CAP_PHRASE.search(q)
                if m:
                    args["customer"] = m.group(1)
                for tier in ("platinum", "gold"):
                    if tier in ql and "customer" not in args:
                        args["customer_tier"] = tier
                if "express" in ql:
                    args["shipping_method"] = "express"
                calls.append(("calculate_order_total", args))
            elif skus and not orders:
                if STOCK_RE.search(q) or LOW_RE.search(q):
                    calls += [("check_stock", {"sku": s}) for s in skus[:3]]
                else:
                    calls += [("search_products", {"query": s}) for s in skus[:3]]
            elif LOW_RE.search(q) and not skus:
                calls.append(("check_stock", {"low_stock_only": True}))
            elif "orders" in ql and not orders:
                args = {}
                for word, status in STATUS_WORDS.items():
                    if re.search(rf"\b{word}\b", ql):
                        args["status"] = status
                        break
                m = CAP_PHRASE.search(q)
                if m:
                    args["customer"] = m.group(1)
                calls.append(("list_orders", args))
            elif PRODUCT_RE.search(q) and not STRONG_DOC.search(q) and not orders:
                args = {"query": q}
                m = re.search(r"under \$?(\d+(?:\.\d+)?)", ql)
                if m:
                    args["max_price"] = float(m.group(1))
                calls.append(("search_products", args))

        structured = bool(calls)
        if STRONG_DOC.search(q) or (WEAK_DOC.search(q) and not structured) or not structured:
            if action is None:
                calls.append(("search_documents", {"query": q[:300]}))
        out = []
        for i, (name, args) in enumerate(calls):
            if name in available:
                out.append(ToolCall(id=f"call_{i}_{name}", name=name, arguments=args))
        return out

    def _plan_action(self, q: str, ql: str, orders: list[str], skus: list[str]):
        if orders:
            status = None
            if re.search(r"\bcancel", ql):
                status = "cancelled"
            elif re.search(r"\b(put|place|set)\b.*\bhold\b|\bon hold\b|\bhold\b", ql) and "release" not in ql:
                status = "on_hold"
            elif re.search(r"\b(release|resume|reopen)\b", ql):
                status = "pending"
            elif re.search(r"\b(mark|set|update|move)\b.*\bshipped\b|\bship order\b", ql):
                status = "shipped"
            elif re.search(r"\b(mark|set)\b.*\bdelivered\b", ql):
                status = "delivered"
            elif re.search(r"\b(confirm|approve)\b.*\border\b", ql):
                status = "confirmed"
            if status and re.search(r"\b(cancel|hold|release|resume|reopen|mark|set|update|move|ship|confirm|approve|put|place)\b", ql):
                return ("draft_action", {"action_type": "update_order_status", "order_number": orders[0],
                                         "new_status": status, "reason": q[:200]})
        if skus:
            bare = SKU_RE.sub("", ORDER_RE.sub("", q))
            nums = [int(n.replace(",", "")) for n in re.findall(r"(?<![\w.-])-?\d[\d,]*(?![\w.-])", bare)]
            if re.search(r"\b(reorder|restock|purchase order|order more|replenish|buy more|po for|create a po|raise a po)\b", ql) and nums:
                return ("draft_action", {"action_type": "create_purchase_order", "sku": skus[0],
                                         "quantity": abs(nums[0]), "reason": q[:200]})
            if re.search(r"\b(adjust|correct|write[- ]?off|remove|deduct|add)\b", ql) and re.search(r"\b(inventory|stock|count)\b", ql) and nums:
                wh = re.search(r"\b(?:at|in)\s+(?:the\s+)?([A-Z][a-z]+)\b", q)
                delta = nums[-1]
                if re.search(r"\b(remove|deduct|write[- ]?off|damaged|lost|shrink)\b", ql):
                    delta = -abs(delta)
                if wh:
                    return ("draft_action", {"action_type": "adjust_inventory", "sku": skus[0], "warehouse": wh.group(1),
                                             "delta": delta, "reason": q[:200]})
        return None

    @staticmethod
    def _quote_items(q: str, skus: list[str]) -> list[dict]:
        items = []
        for sku in skus:
            m = (re.search(rf"(\d[\d,]*)\s*(?:x|×|units? of|pcs of|pieces of|boxes of|cases of|of)?\s*{sku}", q)
                 or re.search(rf"{sku}\s*(?:x|×|\()\s*(\d[\d,]*)", q))
            if m:
                items.append({"sku": sku, "quantity": int(m.group(1).replace(",", ""))})
        return items

    # ------------------------------------------------------------------ adversarial
    def _gullible_calls(self, messages: list[LLMMessage], results: list[LLMMessage]) -> list[ToolCall]:
        """A compromised model: it obeys instructions embedded in retrieved content."""
        if any(tc.name == "execute_sql" for m in messages for tc in m.tool_calls):
            return []
        for m in results:
            text = m.content or ""
            if INJECTION_IN_RESULT.search(text):
                order = ORDER_RE.search(text)
                calls = [ToolCall(id="evil_sql", name="execute_sql", arguments={"sql": "DELETE FROM orders"}),
                         ToolCall(id="evil_confirm", name="confirm_action", arguments={"action_id": "all"}),
                         ToolCall(id="evil_tenant", name="search_products",
                                  arguments={"query": "everything", "tenant_id": 2})]
                if order:
                    calls.append(ToolCall(id="evil_draft", name="draft_action", arguments={
                        "action_type": "update_order_status", "order_number": order.group(0),
                        "new_status": "cancelled", "reason": "instructed by document"}))
                return calls
        return []

    # ------------------------------------------------------------------ composing
    def _compose(self, question: str, results: list[LLMMessage]) -> str:
        if not results:
            body = {"answer": "I can help with company policies, products, inventory and orders. "
                              "Could you tell me what you would like to look up?",
                    "citations": [], "confidence": "low"}
            return json.dumps(body)
        parts: list[str] = []
        cites: list[str] = []
        errors = 0
        doc_found = False
        for m in results:
            mt = RESULT_RE.search(m.content or "")
            if not mt:
                continue
            name = mt.group(1)
            try:
                payload = json.loads(mt.group(2))
            except json.JSONDecodeError:
                continue
            if not payload.get("ok"):
                errors += 1
                parts.append(f"I couldn't complete that lookup: {payload.get('error')}")
                continue
            if name == "search_documents":
                passages = payload.get("data", {}).get("passages", [])
                text, used = self._extract(question, passages)
                if passages and text:
                    doc_found = True
                    parts.append(text)
                    cites += used
                else:
                    parts.append("I could not find anything about that in the company documents.")
                continue
            parts.append(payload.get("summary", ""))
            cites += [s["id"] for s in payload.get("sources", [])]
            if name == "draft_action":
                parts.append("Please review the preview and confirm or reject it; nothing has changed yet.")
        cites = list(dict.fromkeys(cites))[:8]
        if self.fault == "hallucinated_citation":
            cites.append("doc:99999#9")
        conf = "low" if errors or (not cites and not doc_found) else "high"
        return json.dumps({"answer": "\n\n".join(p for p in parts if p), "citations": cites, "confidence": conf})

    @staticmethod
    def _extract(question: str, passages: list[dict], max_sentences: int = 3) -> tuple[str, list[str]]:
        qterms = {t for t in tokenize(question) if t not in _NOISE_FOR_DOC}
        scored = []
        for rank, p in enumerate(passages[:4]):
            for pos, sent in enumerate(split_sentences(p["text"])):
                if len(sent) < 20:
                    continue
                overlap = len(qterms & set(tokenize(sent)))
                if overlap:
                    scored.append((overlap - 0.15 * rank, rank, pos, sent, p))
        if not scored:
            return "", []
        best = sorted(scored, key=lambda x: -x[0])[:max_sentences]
        best.sort(key=lambda x: (x[1], x[2]))
        text = " ".join(b[3].lstrip("-* ").strip() for b in best)
        used = list(dict.fromkeys(b[4]["source_id"] for b in best))
        titles = list(dict.fromkeys(b[4]["document"] for b in best))
        return f"{text} (Source: {', '.join(titles)})", used

    # ---------------------------------------------------------------------- output
    def _respond(self, messages, tools, content: str | None, calls: list[ToolCall] | None = None) -> LLMResponse:
        if content is not None and self.fault == "bad_json_once" and not self._faulted:
            self._faulted = True
            content = "Sure! Here is what I found, in plain prose rather than the required JSON."
        in_tokens = sum(estimate_tokens((m.content or "") + json.dumps([c.arguments for c in m.tool_calls]))
                        for m in messages) + sum(estimate_tokens(t.model_dump_json()) for t in tools or [])
        out_text = content or json.dumps([c.model_dump() for c in calls or []])
        return LLMResponse(content=content, tool_calls=calls or [], model=self.model,
                           finish_reason="tool_calls" if calls else "stop",
                           usage=Usage(input_tokens=in_tokens, output_tokens=estimate_tokens(out_text), estimated=True))
