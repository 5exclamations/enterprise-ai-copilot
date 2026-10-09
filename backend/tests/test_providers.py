import json

import httpx
import pytest

from app.config import Settings
from app.llm import LLMError, LLMMessage, ToolSpec, get_provider
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.openai_provider import OpenAICompatProvider
from app.llm.pricing import estimate_cost

TOOLS = [ToolSpec(name="check_stock", description="d", parameters={"type": "object", "properties": {}})]
MSGS = [LLMMessage(role="system", content="sys"), LLMMessage(role="user", content="hi")]


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_tool_call_roundtrip():
    seen = {}

    def handler(req):
        seen["body"], seen["auth"] = json.loads(req.content), req.headers["authorization"]
        return httpx.Response(200, json={"model": "m", "choices": [{"finish_reason": "tool_calls", "message": {
            "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "check_stock", "arguments": "{\"sku\": \"FS-1001\"}"}}]}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5}})

    p = OpenAICompatProvider(Settings(openai_api_key="k"), client=client(handler))
    r = p.chat(MSGS, TOOLS)
    assert r.tool_calls[0].arguments == {"sku": "FS-1001"} and r.usage.input_tokens == 11
    assert seen["auth"] == "Bearer k" and seen["body"]["tools"][0]["function"]["name"] == "check_stock"


def test_openai_wire_format_for_tool_results():
    from app.llm import ToolCall
    wire = OpenAICompatProvider.to_wire([LLMMessage(role="assistant", tool_calls=[ToolCall(id="1", name="t", arguments={"a": 1})]),
                                         LLMMessage(role="tool", tool_call_id="1", content="r")])
    assert wire[0]["tool_calls"][0]["function"]["arguments"] == '{"a": 1}' and wire[1]["tool_call_id"] == "1"


def test_anthropic_roundtrip_and_parallel_results_merge():
    from app.llm import ToolCall
    system, wire = AnthropicProvider.to_wire([
        LLMMessage(role="system", content="sys"), LLMMessage(role="user", content="q"),
        LLMMessage(role="assistant", tool_calls=[ToolCall(id="a", name="t", arguments={}), ToolCall(id="b", name="t", arguments={"x": 1})]),
        LLMMessage(role="tool", tool_call_id="a", content="ra"), LLMMessage(role="tool", tool_call_id="b", content="rb")])
    assert system == "sys" and len(wire) == 3 and len(wire[2]["content"]) == 2

    def handler(req):
        assert req.headers["x-api-key"] == "k" and json.loads(req.content)["system"] == "sys"
        return httpx.Response(200, json={"model": "m", "stop_reason": "tool_use", "usage": {"input_tokens": 7, "output_tokens": 3},
                                         "content": [{"type": "text", "text": "ok"}, {"type": "tool_use", "id": "t1", "name": "check_stock", "input": {"sku": "FS-1001"}}]})

    r = AnthropicProvider(Settings(anthropic_api_key="k"), client=client(handler)).chat(MSGS, TOOLS)
    assert r.content == "ok" and r.tool_calls[0].name == "check_stock" and r.usage.output_tokens == 3


def test_retries_then_succeeds_and_gives_up(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    assert OpenAICompatProvider(Settings(), client=client(flaky)).chat(MSGS).content == "hi" and calls["n"] == 3
    with pytest.raises(LLMError):
        OpenAICompatProvider(Settings(), client=client(lambda r: httpx.Response(500))).chat(MSGS)
    with pytest.raises(LLMError):
        OpenAICompatProvider(Settings(), client=client(lambda r: httpx.Response(401, text="bad key"))).chat(MSGS)


def test_factory_and_pricing():
    assert get_provider(Settings(llm_provider="mock")).name == "mock"
    with pytest.raises(LLMError):
        get_provider(Settings(llm_provider="anthropic"))
    with pytest.raises(LLMError):
        get_provider(Settings(llm_provider="nope"))
    assert estimate_cost("openai", "x", 1000, 1000, Settings()) is None  # unknown prices are never guessed
    assert estimate_cost("openai", "x", 1_000_000, 0, Settings(llm_price_input_per_mtok=2.0, llm_price_output_per_mtok=8.0)) == 2.0
