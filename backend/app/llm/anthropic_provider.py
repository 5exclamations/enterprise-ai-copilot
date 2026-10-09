"""Anthropic Messages API provider (tool use via content blocks)."""
from __future__ import annotations

import time

import httpx

from ..config import Settings
from .base import LLMError, LLMMessage, LLMProvider, LLMResponse, ToolCall, ToolSpec, Usage

RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings, client: httpx.Client | None = None, max_retries: int = 3):
        self.model = settings.llm_model or "claude-haiku-5-5"
        self._base = settings.anthropic_base_url.rstrip("/")
        self._key = settings.anthropic_api_key
        self._client = client or httpx.Client(timeout=settings.llm_timeout_seconds)
        self._max_retries = max_retries

    @staticmethod
    def to_wire(messages: list[LLMMessage]) -> tuple[str, list[dict]]:
        system = "\n\n".join(m.content or "" for m in messages if m.role == "system")
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "assistant":
                blocks: list[dict] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                blocks += [{"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                           for tc in m.tool_calls]
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            elif m.role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content or ""}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)  # parallel tool results share one user turn
                else:
                    out.append({"role": "user", "content": [block]})
            else:
                out.append({"role": "user", "content": m.content or ""})
        return system, out

    def chat(self, messages, tools=None, temperature=0.0) -> LLMResponse:
        system, wire = self.to_wire(messages)
        body: dict = {"model": self.model, "max_tokens": 1500, "temperature": temperature,
                      "messages": wire}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                             for t in tools]
        headers = {"x-api-key": self._key or "", "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                r = self._client.post(f"{self._base}/v1/messages", headers=headers, json=body)
                if r.status_code in RETRYABLE:
                    raise LLMError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return self._parse(r.json())
            except (httpx.TransportError, LLMError) as exc:
                last = exc
                time.sleep(min(2 ** attempt * 0.5, 4))
            except httpx.HTTPStatusError as exc:
                raise LLMError(f"Provider error {exc.response.status_code}: {exc.response.text[:300]}") from exc
        raise LLMError(f"Provider unavailable after {self._max_retries} attempts: {last}")

    def _parse(self, data: dict) -> LLMResponse:
        text_parts, calls = [], []
        for block in data.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block.get("input") or {}))
        u = data.get("usage") or {}
        return LLMResponse(
            content="".join(text_parts) or None, tool_calls=calls, model=data.get("model", self.model),
            finish_reason=data.get("stop_reason") or "stop",
            usage=Usage(input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0)))
