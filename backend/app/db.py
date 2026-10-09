"""Engine/session setup and the dialect-aware embedding column type."""
from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from .config import get_settings


class Base(DeclarativeBase):
    pass


class EmbeddingType(TypeDecorator):
    """pgvector `vector(N)` on PostgreSQL, a JSON array everywhere else.

    The JSON fallback keeps tests and the zero-dependency demo working; the
    retrieval layer picks the matching search strategy per dialect.
    """

    impl = sa.JSON
    cache_ok = True

    def __init__(self, dim: int | None = None):
        super().__init__()
        self.dim = dim or get_settings().embedding_dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(sa.JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]


def make_engine(url: str | None = None) -> sa.Engine:
    url = url or get_settings().database_url
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool
        return sa.create_engine(url, **kwargs)
    return sa.create_engine(url, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(bind: sa.Engine | None = None) -> None:
    """Create extension, tables and search indexes (idempotent)."""
    from . import models  # noqa: F401  (register tables)

    bind = bind or engine
    if bind.dialect.name == "postgresql":
        with bind.begin() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        with bind.begin() as conn:
            conn.execute(
                sa.text(
                    "CREATE INDEX IF NOT EXISTS ix_chunks_fts ON chunks "
                    "USING GIN (to_tsvector('english', search_text))"
                )
            )
            conn.execute(
                sa.text(
                    "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw ON chunks "
                    "USING hnsw (embedding vector_cosine_ops)"
                )
            )
