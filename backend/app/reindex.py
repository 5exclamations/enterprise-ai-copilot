"""Re-embed every chunk with the currently configured embedding model.

    python -m app.reindex            # only chunks whose embedding is missing or from another model
    python -m app.reindex --all      # force re-embedding everything

Run it after changing EMBEDDING_PROVIDER / EMBEDDING_MODEL / EMBEDDING_DIM (and `alembic upgrade head`).
"""
from __future__ import annotations

import argparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Chunk
from .retrieval.embeddings import Embedder, get_embedder

BATCH = 16


def reindex(db: Session, embedder: Embedder | None = None, force: bool = False, progress=None) -> dict:
    embedder = embedder or get_embedder()
    stmt = select(Chunk).order_by(Chunk.id)
    chunks = [c for c in db.scalars(stmt) if force or c.embedding is None or c.embedding_model != embedder.name]
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i : i + BATCH]
        for c, vec in zip(batch, embedder.embed([c.search_text for c in batch])):
            c.embedding, c.embedding_model = vec, embedder.name
        db.commit()
        if progress:
            progress(min(i + BATCH, len(chunks)), len(chunks))
    total = db.scalar(select(func.count()).select_from(Chunk)) or 0
    return {"model": embedder.name, "dim": embedder.dim, "reembedded": len(chunks), "total_chunks": total}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="re-embed every chunk, not just stale ones")
    args = ap.parse_args()
    with SessionLocal() as db:
        print(reindex(db, force=args.all, progress=lambda done, n: print(f"  {done}/{n}", flush=True)))


if __name__ == "__main__":
    main()
