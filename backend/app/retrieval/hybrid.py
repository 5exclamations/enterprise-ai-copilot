"""Hybrid retrieval: semantic (vector) + keyword (BM25 / full-text) + metadata filters,
fused with Reciprocal Rank Fusion.

On PostgreSQL both channels run in the database (pgvector cosine distance with an HNSW
index; `ts_rank_cd` over a GIN-indexed tsvector). On other dialects (SQLite, used by tests
and the zero-dependency demo) the same logic runs in Python over the tenant's candidate set.
Tenant filtering is applied in the query itself, never after the fact.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Chunk, Document
from ..text import tokenize
from .embeddings import Embedder, get_embedder

RRF_K = 60
CANDIDATES = 30
MIN_SEMANTIC = 0.18  # cosine below this with no keyword support is treated as noise
MIN_KEYWORD_TERMS = 2  # a keyword-only hit must match at least this many distinct query terms


@dataclass
class Filters:
    category: str | None = None
    document_ids: list[int] | None = None
    effective_after: str | None = None  # ISO date, matched against extracted effective_date


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    document_title: str
    category: str
    section: str | None
    page: int | None
    chunk_index: int
    content: str
    score: float
    semantic_score: float | None = None
    keyword_score: float | None = None
    semantic_rank: int | None = None
    keyword_rank: int | None = None
    matched_terms: int = 0
    doc_version: int = 1
    extra: dict = field(default_factory=dict)

    @property
    def source_id(self) -> str:
        return f"doc:{self.document_id}#{self.chunk_index}"


def _base_query(tenant_id: int, f: Filters):
    q = (
        sa.select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.tenant_id == tenant_id, Document.tenant_id == tenant_id,
               Document.status == "active", Chunk.flagged.is_(False))
    )
    if f.category:
        q = q.where(Document.category == f.category)
    if f.document_ids:
        q = q.where(Document.id.in_(f.document_ids))
    return q


def _effective_ok(doc: Document, f: Filters) -> bool:
    if not f.effective_after:
        return True
    eff = (doc.meta or {}).get("effective_date")
    return bool(eff) and eff >= f.effective_after


class HybridRetriever:
    def __init__(self, db: Session, embedder: Embedder | None = None):
        self.db = db
        self.embedder = embedder or get_embedder()
        self._pg = db.get_bind().dialect.name == "postgresql"

    # ------------------------------------------------------------------ channels
    def _semantic(self, tenant_id: int, qvec: list[float], f: Filters):
        if self._pg:
            dist = Chunk.embedding.op("<=>", return_type=sa.Float)(sa.literal(qvec, type_=Vector(len(qvec))))
            rows = self.db.execute(
                _base_query(tenant_id, f).add_columns((1 - dist).label("sim")).order_by(dist).limit(CANDIDATES * 3)
            ).all()
            return [(c, d, float(s)) for c, d, s in rows if _effective_ok(d, f)][:CANDIDATES]
        rows = self.db.execute(_base_query(tenant_id, f)).all()
        rows = [(c, d) for c, d in rows if c.embedding is not None and _effective_ok(d, f)]
        if not rows:
            return []
        mat = np.array([c.embedding for c, _ in rows], dtype=np.float32)
        q = np.array(qvec, dtype=np.float32)
        sims = mat @ q / (np.linalg.norm(mat, axis=1) * np.linalg.norm(q) + 1e-9)
        order = np.argsort(-sims)[:CANDIDATES]
        return [(rows[i][0], rows[i][1], float(sims[i])) for i in order]

    def _keyword(self, tenant_id: int, query: str, f: Filters):
        terms = list(dict.fromkeys(tokenize(query)))
        if not terms:
            return [], terms
        if self._pg:
            safe = [re.sub(r"[^a-z0-9]", "", t) for t in terms]
            tsq = sa.func.to_tsquery("english", " | ".join(t for t in safe if t))
            tsv = sa.func.to_tsvector("english", Chunk.search_text)
            rank = sa.func.ts_rank_cd(tsv, tsq)
            rows = self.db.execute(
                _base_query(tenant_id, f).add_columns(rank.label("rank")).where(tsv.op("@@")(tsq))
                .order_by(sa.desc(rank)).limit(CANDIDATES * 3)
            ).all()
            return [(c, d, float(r)) for c, d, r in rows if _effective_ok(d, f)][:CANDIDATES], terms
        rows = [(c, d) for c, d in self.db.execute(_base_query(tenant_id, f)).all() if _effective_ok(d, f)]
        return _bm25(rows, terms)[:CANDIDATES], terms

    # --------------------------------------------------------------------- search
    def search(self, tenant_id: int, query: str, k: int | None = None, filters: Filters | None = None,
               w_semantic: float = 1.0, w_keyword: float = 1.0, mode: str = "hybrid") -> list[Hit]:
        k = k or get_settings().retrieval_top_k
        f = filters or Filters()
        qvec = self.embedder.embed([query])[0]
        sem = self._semantic(tenant_id, qvec, f) if mode in ("hybrid", "semantic") else []
        kw, terms = self._keyword(tenant_id, query, f) if mode in ("hybrid", "keyword") else ([], tokenize(query))

        fused: dict[int, Hit] = {}

        def hit_for(c: Chunk, d: Document) -> Hit:
            if c.id not in fused:
                fused[c.id] = Hit(
                    chunk_id=c.id, document_id=d.id, document_title=d.title, category=d.category,
                    section=c.section, page=c.page, chunk_index=c.chunk_index, content=c.content,
                    score=0.0, doc_version=d.version)
            return fused[c.id]

        for rank, (c, d, s) in enumerate(sem, 1):
            h = hit_for(c, d)
            h.semantic_score, h.semantic_rank = s, rank
            h.score += w_semantic / (RRF_K + rank)
        for rank, (c, d, s) in enumerate(kw, 1):
            h = hit_for(c, d)
            h.keyword_score, h.keyword_rank = s, rank
            h.score += w_keyword / (RRF_K + rank)
            h.matched_terms = len(set(tokenize(c.search_text)) & set(terms))

        def relevant(h: Hit) -> bool:
            sem_ok = h.semantic_score is not None and h.semantic_score >= MIN_SEMANTIC
            if h.keyword_rank and h.matched_terms == 0:  # e.g. PG stemming differences: compute locally
                h.matched_terms = len(set(tokenize(h.content)) & set(terms))
            kw_ok = h.keyword_rank is not None and h.matched_terms >= min(MIN_KEYWORD_TERMS, len(terms))
            return sem_ok or kw_ok

        hits = sorted((h for h in fused.values() if relevant(h)), key=lambda h: -h.score)
        return hits[:k]


def _bm25(rows: list[tuple[Chunk, Document]], terms: list[str], k1: float = 1.5, b: float = 0.75):
    if not rows:
        return []
    docs = [Counter(tokenize(c.search_text)) for c, _ in rows]
    lens = [sum(d.values()) for d in docs]
    avg = (sum(lens) / len(lens)) or 1.0
    n = len(rows)
    df = {t: sum(1 for d in docs if t in d) for t in terms}
    scored = []
    for (c, d), tf, ln in zip(rows, docs, lens):
        s = 0.0
        for t in terms:
            if df[t] == 0 or t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            f = tf[t]
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * ln / avg))
        if s > 0:
            scored.append((c, d, s))
    scored.sort(key=lambda x: -x[2])
    return scored
