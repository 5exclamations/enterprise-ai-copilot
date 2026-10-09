"""Embedding providers.

* `HashingEmbedder` - deterministic, dependency-free, offline. Signed feature hashing of
  unigrams / bigrams / char-trigrams plus a tiny synonym table. It is lexical-plus, NOT a
  neural model; it exists so the whole system runs and tests without credentials.
* `OpenAICompatEmbedder` - any OpenAI-compatible `/embeddings` endpoint (OpenAI, Ollama,
  vLLM, LM Studio...). Use this for genuinely semantic retrieval.
"""
from __future__ import annotations

import math
import zlib
from typing import Protocol

import httpx

from ..config import Settings, get_settings
from ..text import expand_synonyms


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


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


class OpenAICompatEmbedder:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.name = settings.embedding_model
        self.dim = settings.embedding_dim
        self._base = settings.openai_base_url.rstrip("/")
        self._key = settings.openai_api_key
        self._client = client or httpx.Client(timeout=settings.llm_timeout_seconds)

    def embed(self, texts: list[str]) -> list[list[float]]:
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
                "the vector column must be re-created to change dimensions."
            )
        return out


_cached: Embedder | None = None


def get_embedder(settings: Settings | None = None) -> Embedder:
    global _cached
    settings = settings or get_settings()
    if _cached is None:
        if settings.embedding_provider == "openai":
            _cached = OpenAICompatEmbedder(settings)
        else:
            _cached = HashingEmbedder(settings.embedding_dim)
    return _cached


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
