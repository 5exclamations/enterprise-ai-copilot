"""Opt-in integration tests against a REAL local Ollama server (never run in CI).

    RUN_OLLAMA_TESTS=1 pytest -m ollama -q

Needs `ollama pull qwen2.5:3b` and `ollama pull nomic-embed-text`. Override with OLLAMA_TEST_LLM /
OLLAMA_TEST_EMBED / OLLAMA_BASE_URL. Assertions are deliberately loose: real models are not deterministic.
"""
import os

import pytest
from sqlalchemy import select

from app.config import Settings
from app.llm import LLMMessage, ToolSpec, get_provider
from app.retrieval.embeddings import OllamaEmbedder, cosine
from app.retrieval.hybrid import HybridRetriever

pytestmark = [pytest.mark.ollama, pytest.mark.skipif(os.environ.get("RUN_OLLAMA_TESTS") != "1",
                                                     reason="opt-in: set RUN_OLLAMA_TESTS=1 with a local Ollama server")]

LLM = os.environ.get("OLLAMA_TEST_LLM", "qwen2.5:3b")
EMBED = os.environ.get("OLLAMA_TEST_EMBED", "nomic-embed-text")


def _settings(**kw) -> Settings:
    return Settings(llm_provider="ollama", llm_model=LLM, embedding_provider="ollama", embedding_model=EMBED, embedding_dim=768,
                    embedding_query_prefix="search_query: ", embedding_document_prefix="search_document: ", **kw)


def test_embedder_is_semantic():
    e = OllamaEmbedder(_settings())
    q = e.embed_query("how long do customers have to send products back?")
    returns, forklift = e.embed(["Returns are accepted within 30 days of delivery.", "Forklift batteries must be charged in ventilated areas."])
    assert len(q) == 768 and cosine(q, returns) > cosine(q, forklift) + 0.1


def test_chat_model_emits_a_valid_tool_call():
    tools = [ToolSpec(name="check_stock", description="Check stock levels for a SKU",
                      parameters={"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]})]
    r = get_provider(_settings()).chat([LLMMessage(role="system", content="Use tools to answer."),
                                        LLMMessage(role="user", content="Is FS-1003 in stock?")], tools)
    assert r.usage.input_tokens > 0 and r.tool_calls and r.tool_calls[0].name == "check_stock"
    assert "FS-1003" in str(r.tool_calls[0].arguments)


def test_retrieval_with_neural_embeddings_handles_paraphrase(db):
    """Re-embed the seeded corpus with the real model, then query with words the documents do not use."""
    from app.models import Chunk
    from app.reindex import reindex
    e = OllamaEmbedder(_settings())
    out = reindex(db, e)
    assert out["model"] == EMBED and all(len(c.embedding) == 768 for c in db.scalars(select(Chunk)))
    from app.models import Tenant
    tenant = db.scalars(select(Tenant)).first()
    hits = HybridRetriever(db, e).search(tenant.id, "how long can a customer wait before sending an item back", k=3)
    assert hits and any("return" in h.document_title.lower() or "return" in h.content.lower() for h in hits)
