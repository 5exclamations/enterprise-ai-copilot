"""Ollama provider/embedder (mocked HTTP - deterministic), Alembic migrations, and re-indexing."""
import json
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import select

from app.config import Settings
from app.db import Base, init_db, make_engine
from app.llm import LLMError, LLMMessage, ToolCall, ToolSpec, get_provider
from app.llm.ollama_provider import OllamaProvider
from app.llm.pricing import estimate_cost
from app.models import Chunk
from app.reindex import reindex
from app.retrieval.embeddings import OllamaEmbedder, get_embedder
from app.services.documents import update_document

BACKEND = Path(__file__).resolve().parent.parent
TOOLS = [ToolSpec(name="check_stock", description="d", parameters={"type": "object", "properties": {}})]


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ----------------------------------------------------------------------------- Ollama provider
def test_ollama_tool_call_roundtrip_and_usage():
    seen = {}

    def handler(req):
        seen["body"], seen["path"] = json.loads(req.content), req.url.path
        return httpx.Response(200, json={"model": "qwen2.5:3b", "done_reason": "stop", "prompt_eval_count": 140, "eval_count": 25,
                                         "message": {"role": "assistant", "content": "", "tool_calls": [
                                             {"function": {"name": "check_stock", "arguments": {"sku": "FS-1003"}}}]}})

    p = OllamaProvider(Settings(llm_model="qwen2.5:3b", ollama_num_ctx=2048), client=client(handler))
    r = p.chat([LLMMessage(role="user", content="stock?")], TOOLS)
    assert seen["path"] == "/api/chat" and seen["body"]["stream"] is False
    assert seen["body"]["options"]["num_ctx"] == 2048 and seen["body"]["tools"][0]["function"]["name"] == "check_stock"
    assert r.tool_calls[0].name == "check_stock" and r.tool_calls[0].arguments == {"sku": "FS-1003"}
    assert r.finish_reason == "tool_calls" and (r.usage.input_tokens, r.usage.output_tokens) == (140, 25) and not r.usage.estimated


def test_ollama_string_arguments_and_wire_format():
    def handler(req):
        return httpx.Response(200, json={"message": {"content": None, "tool_calls": [
            {"function": {"name": "t", "arguments": "{\"a\": 1}"}}, {"function": {"name": "u", "arguments": "not json"}}]}})

    r = OllamaProvider(Settings(), client=client(handler)).chat([LLMMessage(role="user", content="x")], TOOLS)
    assert r.tool_calls[0].arguments == {"a": 1} and "__invalid_json__" in r.tool_calls[1].arguments
    wire = OllamaProvider.to_wire([LLMMessage(role="assistant", tool_calls=[ToolCall(id="1", name="t", arguments={"a": 1})]),
                                   LLMMessage(role="tool", tool_call_id="1", name="t", content="res")])
    assert wire[0]["tool_calls"][0]["function"]["arguments"] == {"a": 1} and wire[1] == {"role": "tool", "content": "res", "tool_name": "t"}


def test_ollama_errors_are_clear():
    p = OllamaProvider(Settings(llm_model="nope"), client=client(lambda req: httpx.Response(404, json={"error": "x"})))
    with pytest.raises(LLMError, match="ollama pull nope"):
        p.chat([LLMMessage(role="user", content="x")])

    def boom(req):
        raise httpx.ConnectError("refused")

    import app.llm.ollama_provider as mod
    mod.time.sleep = lambda s: None
    with pytest.raises(LLMError, match="unavailable"):
        OllamaProvider(Settings(), client=client(boom), max_retries=2).chat([LLMMessage(role="user", content="x")])


def test_ollama_registered_and_free():
    assert get_provider(Settings(llm_provider="ollama")).name == "ollama"
    assert estimate_cost("ollama", "qwen2.5:3b", 1000, 1000, Settings()) == 0.0


# --------------------------------------------------------------------------- Ollama embedder
def test_ollama_embedder_prefixes_and_dim_check():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3] for _ in body["input"]]})

    s = Settings(embedding_provider="ollama", embedding_model="nomic-embed-text", embedding_dim=3,
                 embedding_query_prefix="search_query: ", embedding_document_prefix="search_document: ")
    e = OllamaEmbedder(s, client=client(handler))
    assert e.embed(["a", "b"]) == [[0.1, 0.2, 0.3]] * 2 and e.embed_query("q") == [0.1, 0.2, 0.3]
    assert calls[0]["input"] == ["search_document: a", "search_document: b"] and calls[1]["input"] == ["search_query: q"]
    with pytest.raises(ValueError, match="EMBEDDING_DIM"):
        OllamaEmbedder(Settings(embedding_dim=768), client=client(handler)).embed(["a"])


def test_embedder_factory_default_stays_offline_hashing():
    assert get_embedder().name == "hashing-v1"


# ----------------------------------------------------------------------------- migrations
def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'm.db').as_posix()}"


def test_migrations_upgrade_matches_models_and_roundtrips(tmp_path):
    url = _url(tmp_path)
    command.upgrade(_cfg(url), "head")
    eng = make_engine(url)
    insp = sa.inspect(eng)
    assert {"tenants", "chunks", "documents", "alembic_version"} <= set(insp.get_table_names())
    assert "embedding_model" in {c["name"] for c in insp.get_columns("chunks")}
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models drifted from migrations: {diff}"
    command.downgrade(_cfg(url), "base")
    assert set(sa.inspect(make_engine(url)).get_table_names()) == {"alembic_version"}
    command.upgrade(_cfg(url), "head")  # and up again


def test_migration_adopts_pre_alembic_database_without_losing_data(tmp_path):
    url = _url(tmp_path)
    eng = make_engine(url)
    init_db(eng)
    with eng.begin() as conn:  # simulate a DB built by the old init_db() (no embedding_model column)
        conn.execute(sa.text("ALTER TABLE chunks DROP COLUMN embedding_model"))
        conn.execute(sa.text("INSERT INTO tenants (id, slug, name) VALUES (1, 'a', 'A')"))
        conn.execute(sa.text("INSERT INTO documents (id, tenant_id, title, filename, content_type, category, content_hash, version, status, meta, created_at, updated_at)"
                             " VALUES (1, 1, 't', 'f', 'text/plain', 'other', 'h', 1, 'active', '{}', '2026-01-01', '2026-01-01')"))
        conn.execute(sa.text("INSERT INTO chunks (document_id, tenant_id, chunk_index, content, search_text, content_hash, token_count, embedding, flagged)"
                             " VALUES (1, 1, 0, 'c', 'c', 'h', 1, '[0.5, 0.5]', 0)"))
    command.upgrade(_cfg(url), "head")
    with make_engine(url).connect() as conn:
        row = conn.execute(sa.text("SELECT embedding_model, content FROM chunks")).one()
        assert tuple(row) == ("hashing-v1", "c")
        assert conn.execute(sa.text("SELECT count(*) FROM tenants")).scalar() == 1


# ------------------------------------------------------------------------------- reindexing
class FakeEmbedder:
    name, dim = "fake-neural", 4

    def embed(self, texts):
        return [[float(len(t) % 7), 1.0, 0.0, 0.0] for t in texts]

    def embed_query(self, text):
        return self.embed([text])[0]


def test_reindex_reembeds_only_stale_chunks(db):
    n = db.scalar(select(sa.func.count()).select_from(Chunk))
    assert n > 0 and {c.embedding_model for c in db.scalars(select(Chunk))} == {"hashing-v1"}
    out = reindex(db, FakeEmbedder())
    assert out["reembedded"] == n and out["model"] == "fake-neural"
    assert {c.embedding_model for c in db.scalars(select(Chunk))} == {"fake-neural"}
    assert all(len(c.embedding) == 4 for c in db.scalars(select(Chunk)))
    assert reindex(db, FakeEmbedder())["reembedded"] == 0  # idempotent
    assert reindex(db, FakeEmbedder(), force=True)["reembedded"] == n


def test_update_does_not_reuse_vectors_from_another_model(db):
    from app.models import Document
    doc = db.scalars(select(Document)).first()
    data = "\n\n".join(c.content for c in doc.chunks).encode()
    res = update_document(db, doc=doc, user_id=None, filename="x.md", data=data + b"\n\nNew trailing paragraph for hash change.",
                          embedder=FakeEmbedder())
    assert res.chunks_reused == 0 and res.chunks_embedded == res.chunks_total  # hashing-v1 vectors were not reused
    assert {c.embedding_model for c in doc.chunks} == {"fake-neural"}


