from __future__ import annotations

from ..config import Settings, get_settings
from .base import LLMError, LLMMessage, LLMProvider, LLMResponse, ToolCall, ToolSpec, Usage

__all__ = ["LLMError", "LLMMessage", "LLMProvider", "LLMResponse", "ToolCall", "ToolSpec", "Usage", "get_provider"]


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """Build the configured provider. `mock` needs no credentials."""
    s = settings or get_settings()
    name = s.llm_provider.lower()
    if name == "mock":
        from .mock import MockProvider

        return MockProvider()
    if name == "openai":
        from .openai_provider import OpenAICompatProvider

        return OpenAICompatProvider(s)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        if not s.anthropic_api_key:
            raise LLMError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicProvider(s)
    raise LLMError(f"Unknown LLM_PROVIDER '{s.llm_provider}' (expected mock, openai or anthropic)")
