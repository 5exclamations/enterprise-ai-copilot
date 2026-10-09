"""Native Ollama chat provider (`/api/chat`): local models, no credentials, no per-token cost.

The native API is used instead of Ollama's OpenAI-compat shim so we can set the context window
and keep-alive, and so token counts come straight from `prompt_eval_count` / `eval_count`.
"""
from __future__ import annotations

import json
import time

import httpx

from ..config import Settings
from .base import LLMError, LLMMessage, LLMProvider, LLMResponse, ToolCall, ToolSpec, Usage


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, settings: Settings, client: httpx.Client | None = None, max_retries: int = 2):
        self.model = settings.llm_model or "qwen2.5:3b"
        self._base = settings.ollama_base_url.rstrip("/")
        self._num_ctx = settings.ollama_num_ctx
        self._keep_alive = settings.ollama_keep_alive
        self._client = client or httpx.Client(timeout=settings.ollama_timeout_seconds)
        self._max_retries = max_retries

    @staticmethod
    def to_wire(messages: list[LLMMessage]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m.role == "assistant" and m.tool_calls:
                out.append({"role": "assistant", "content": m.content or "", "tool_calls": [
                    {"function": {"name": tc.name, "arguments": tc.arguments}} for tc in m.tool_calls]})
            elif m.role == "tool":
                out.append({"role": "tool", "content": m.content or "", "tool_name": m.name or ""})
            else:
                out.append({"role": m.role, "content": m.content or ""})
        return out

    def chat(self, messages: list[LLMMessage], tools: list[ToolSpec] | None = None,
             temperature: float = 0.0) -> LLMResponse:
        body: dict = {
            "model": self.model, "messages": self.to_wire(messages), "stream": False,
            "keep_alive": self._keep_alive,
            "options": {"temperature": temperature, "num_ctx": self._num_ctx, "seed": 7},
        }
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                r = self._client.post(f"{self._base}/api/chat", json=body)
                if r.status_code == 404:
                    raise LLMError(f"Ollama model '{self.model}' not found; run `ollama pull {self.model}`")
                if r.status_code >= 500:
                    last = LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                    time.sleep(1 + attempt)
                    continue
                r.raise_for_status()
                return self._parse(r.json())
            except httpx.TransportError as exc:
                last = exc
                time.sleep(1 + attempt)
            except httpx.HTTPStatusError as exc:
                raise LLMError(f"Ollama error {exc.response.status_code}: {exc.response.text[:300]}") from exc
        raise LLMError(f"Ollama unavailable at {self._base} after {self._max_retries} attempts: {last}")

    def _parse(self, data: dict) -> LLMResponse:
        msg = data.get("message") or {}
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):  # some models emit a JSON string
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"__invalid_json__": args}
            calls.append(ToolCall(id=f"call_{i}", name=fn.get("name", ""), arguments=args))
        return LLMResponse(
            content=msg.get("content") or None, tool_calls=calls, model=data.get("model", self.model),
            finish_reason="tool_calls" if calls else (data.get("done_reason") or "stop"),
            usage=Usage(input_tokens=data.get("prompt_eval_count", 0), output_tokens=data.get("eval_count", 0)))
