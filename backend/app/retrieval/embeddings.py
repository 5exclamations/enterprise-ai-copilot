"""Embedding providers.

* `HashingEmbedder` - deterministic, dependency-free, offline. Signed feature hashing of
  unigrams / bigrams / char-trigrams plus a tiny synonym table. It is lexical-plus, NOT a
  neural model; it exists so the whole system runs and tests without credentials.
* `OllamaEmbedder` - a real neural model served locally by Ollama (`/api/embed`), e.g.
  `nomic-embed-text` (768-d). Supports asymmetric query/document task prefixes.
* `OpenAICompatEmbedder` - any OpenAI-compatible `/embeddings` endpoint (OpenAI, vLLM,
  LM Studio...). Use this for genuinely semantic retrieval against a hosted service.
"""
from __future__ import annotations

import math
import time
import zlib
from typing import Protocol

import httpx

from ..config import Settings, get_settings
from ..text import expand_synonyms


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed documents/chunks."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query (some models use a different task prefix than for documents)."""
        ...


class HashingEmbedder:
    name = "hashing-v1"

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = zlib.crc32(feature.encode("utf-8"))
        return h % self.dim, 1.0 if (h >> 31) & 1 else -1.0

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        toks = expand_synonyms(text)
        feats: dict[str, float] = {}
        for t in toks:
            feats["u:" + t] = feats.get("u:" + t, 0.0) + 1.0
        for a, b in zip(toks, toks[1:]):
            feats["b:" + a + "_" + b] = feats.get("b:" + a + "_" + b, 0.0) + 0.5
        for t in toks:
            padded = f"^{t}$"
            for i in range(len(padded) - 2):
                key = "c:" + padded[i : i + 3]
                feats[key] = feats.get(key, 0.0) + 0.15
        for key, tf in feats.items():
            idx, sign = self._bucket(key)
            vec[idx] += sign * (1.0 + math.log(tf) if tf >= 1 else tf)
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


class OpenAICompatEmbedder:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.name = settings.embedding_model
        self.dim = settings.embedding_dim
        self._base = settings.openai_base_url.rstrip("/")
        self._key = settings.openai_api_key
        self._qp = settings.embedding_query_prefix
        self._dp = settings.embedding_document_prefix
        self._client = client or httpx.Client(timeout=settings.llm_timeout_seconds)

    def _call(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            r = self._client.post(
                f"{self._base}/embeddings",
                headers=headers,
                json={"model": self.name, "input": texts[i : i + 64]},
            )
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        if out and len(out[0]) != self.dim:
            raise ValueError(
                f"Embedding model returned {len(out[0])} dims but EMBEDDING_DIM={self.dim}; "
                "set EMBEDDING_DIM to match and run `alembic upgrade head` + `python -m app.reindex`."
            )
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._call([self._dp + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._call([self._qp + text])[0]


class OllamaEmbedder:
    """Neural embeddings from a local Ollama server."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.name = settings.embedding_model
        self.dim = settings.embedding_dim
        self._base = settings.ollama_base_url.rstrip("/")
        self._keep_alive = settings.ollama_keep_alive
        self._qp = settings.embedding_query_prefix
        self._dp = settings.embedding_document_prefix
        self._client = client or httpx.Client(timeout=settings.ollama_timeout_seconds)

    def _post_with_retry(self, body: dict, attempts: int = 4) -> httpx.Response:
        """Ollama can answer 5xx/drop the connection while it (re)loads a model; retry with backoff."""
        last: Exception | None = None
        for n in range(attempts):
            try:
                r = self._client.post(f"{self._base}/api/embed", json=body)
                if r.status_code < 500:
                    return r
                last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            except httpx.TransportError as exc:
                last = exc
            time.sleep(min(2 ** n, 8))
        raise RuntimeError(f"Ollama embedding unavailable at {self._base} after {attempts} attempts: {last}")

    def _call(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 16):
            r = self._post_with_retry({"model": self.name, "input": texts[i : i + 16], "keep_alive": self._keep_alive})
            if r.status_code == 404:
                raise RuntimeError(f"Ollama embedding model '{self.name}' not found; run `ollama pull {self.name}`")
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
        if out and len(out[0]) != self.dim:
            raise ValueError(
                f"Embedding model '{self.name}' returned {len(out[0])} dims but EMBEDDING_DIM={self.dim}; "
                "set EMBEDDING_DIM to match and run `alembic upgrade head` + `python -m app.reindex`."
            )
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._call([self._dp + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._call([self._qp + text])[0]


_cached: Embedder | None = None


def get_embedder(settings: Settings | None = None) -> Embedder:
    global _cached
    settings = settings or get_settings()
    if _cached is None:
        if settings.embedding_provider == "ollama":
            _cached = OllamaEmbedder(settings)
        elif settings.embedding_provider == "openai":
            _cached = OpenAICompatEmbedder(settings)
        else:
            _cached = HashingEmbedder(settings.embedding_dim)
    return _cached


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
