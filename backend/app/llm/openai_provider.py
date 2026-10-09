"""OpenAI-compatible Chat Completions provider (OpenAI, Azure-style gateways, Ollama, vLLM...)."""
from __future__ import annotations

import json
import time

import httpx

from ..config import Settings
from .base import LLMError, LLMMessage, LLMProvider, LLMResponse, ToolCall, ToolSpec, Usage

RETRYABLE = {408, 409, 429, 500, 502, 503, 504}


class OpenAICompatProvider(LLMProvider):
    name = "openai"

    def __init__(self, settings: Settings, client: httpx.Client | None = None, max_retries: int = 3):
        self.model = settings.llm_model or "gpt-4o-mini"
        self._base = settings.openai_base_url.rstrip("/")
        self._key = settings.openai_api_key
        self._client = client or httpx.Client(timeout=settings.llm_timeout_seconds)
        self._max_retries = max_retries

    @staticmethod
    def to_wire(messages: list[LLMMessage]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m.role == "assistant" and m.tool_calls:
                out.append({"role": "assistant", "content": m.content, "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}} for tc in m.tool_calls]})
            elif m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""})
            else:
                out.append({"role": m.role, "content": m.content or ""})
        return out

    def chat(self, messages, tools=None, temperature=0.0) -> LLMResponse:
        body: dict = {"model": self.model, "messages": self.to_wire(messages), "temperature": temperature}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                r = self._client.post(f"{self._base}/chat/completions", headers=headers, json=body)
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
        choice = data["choices"][0]
        msg = choice["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"__invalid_json__": tc["function"].get("arguments")}
            calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args))
        u = data.get("usage") or {}
        return LLMResponse(
            content=msg.get("content"), tool_calls=calls, model=data.get("model", self.model),
            finish_reason=choice.get("finish_reason") or "stop",
            usage=Usage(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0)))
