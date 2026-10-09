"""Document ingestion service: parse -> chunk -> metadata -> embed -> store (+ updates)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..guardrails import injection
from ..ingestion.chunking import chunk_document
from ..ingestion.metadata import extract_metadata
from ..ingestion.parsing import ParseError, parse_document
from ..models import AuditLog, Chunk, Document
from ..retrieval.embeddings import Embedder, get_embedder

__all__ = ["IngestResult", "ingest_document", "update_document", "delete_document", "ParseError"]


@dataclass
class IngestResult:
    document: Document
    chunks_total: int
    chunks_embedded: int  # new embeddings computed
    chunks_reused: int  # embeddings reused from identical chunks of the previous version
    chunks_quarantined: int
    unchanged: bool = False


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def _build_chunks(doc: Document, filename: str, data: bytes, embedder: Embedder,
                  reuse: dict[str, list[float]], title: str | None, category: str | None):
    parsed = parse_document(filename, data)
    meta = extract_metadata(filename, parsed, title=title, category=category)
    drafts = chunk_document(parsed)
    if not drafts:
        raise ParseError("Document contains no indexable text.")
    settings = get_settings()
    rows, to_embed = [], []
    quarantined = 0
    for d in drafts:
        search_text = " | ".join(p for p in (meta["title"], d.section, d.content) if p)
        scan = injection.scan(d.content)
        flagged = scan.suspicious and settings.quarantine_injected_chunks
        quarantined += int(flagged)
        row = Chunk(
            tenant_id=doc.tenant_id, chunk_index=d.index, content=d.content, search_text=search_text,
            content_hash=_sha(search_text), section=d.section, page=d.page, token_count=d.token_count,
            flagged=flagged, flag_reason=",".join(scan.matches) if flagged else None,
        )
        if row.content_hash in reuse:
            row.embedding, row.embedding_model = reuse[row.content_hash], embedder.name
        else:
            to_embed.append(row)
        rows.append(row)
    if to_embed:
        for row, vec in zip(to_embed, embedder.embed([r.search_text for r in to_embed])):
            row.embedding, row.embedding_model = vec, embedder.name
    return parsed, meta, rows, len(to_embed), len(rows) - len(to_embed), quarantined


def ingest_document(db: Session, *, tenant_id: int, user_id: int | None, filename: str, data: bytes,
                    content_type: str = "application/octet-stream", title: str | None = None,
                    category: str | None = None, embedder: Embedder | None = None) -> IngestResult:
    max_bytes = get_settings().max_upload_bytes
    if len(data) > max_bytes:
        raise ParseError(f"File too large (limit {max_bytes // (1024 * 1024)} MB).")
    embedder = embedder or get_embedder()
    doc = Document(tenant_id=tenant_id, title="", filename=filename[:300], content_type=content_type[:100],
                   category="other", content_hash=_sha(data), uploaded_by=user_id, meta={})
    _, meta, rows, n_emb, n_reuse, n_quar = _build_chunks(doc, filename, data, embedder, {}, title, category)
    doc.title, doc.category, doc.meta, doc.chunks = meta["title"], meta["category"], meta, rows
    db.add(doc)
    db.add(AuditLog(tenant_id=tenant_id, user_id=user_id, event="document.ingested",
                    detail={"filename": filename, "chunks": len(rows), "quarantined": n_quar}))
    db.commit()
    return IngestResult(doc, len(rows), n_emb, n_reuse, n_quar)


def update_document(db: Session, *, doc: Document, user_id: int | None, filename: str, data: bytes,
                    content_type: str = "application/octet-stream", title: str | None = None,
                    category: str | None = None, embedder: Embedder | None = None) -> IngestResult:
    """Replace a document's content in place. Identical chunks keep their embeddings."""
    embedder = embedder or get_embedder()
    new_hash = _sha(data)
    if new_hash == doc.content_hash and not title and not category:
        n = len(doc.chunks)
        return IngestResult(doc, n, 0, n, sum(c.flagged for c in doc.chunks), unchanged=True)
    # Only reuse vectors made by the same embedding model; vectors from different models are not comparable.
    old = {c.content_hash: c.embedding for c in doc.chunks if c.embedding is not None and c.embedding_model == embedder.name}
    _, meta, rows, n_emb, n_reuse, n_quar = _build_chunks(
        doc, filename, data, embedder, old, title or None, category or None)
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    db.expire(doc, ["chunks"])
    for r in rows:
        r.document_id = doc.id
    db.add_all(rows)
    doc.title, doc.category, doc.meta = meta["title"], meta["category"], meta
    doc.filename, doc.content_type, doc.content_hash = filename[:300], content_type[:100], new_hash
    doc.version += 1
    db.add(AuditLog(tenant_id=doc.tenant_id, user_id=user_id, event="document.updated",
                    detail={"document_id": doc.id, "version": doc.version, "reused": n_reuse, "embedded": n_emb}))
    db.commit()
    db.refresh(doc)
    return IngestResult(doc, len(rows), n_emb, n_reuse, n_quar)


def delete_document(db: Session, doc: Document, user_id: int | None) -> None:
    db.add(AuditLog(tenant_id=doc.tenant_id, user_id=user_id, event="document.deleted",
                    detail={"document_id": doc.id, "title": doc.title}))
    db.delete(doc)
    db.commit()


def get_tenant_document(db: Session, tenant_id: int, doc_id: int) -> Document | None:
    return db.scalar(select(Document).where(Document.id == doc_id, Document.tenant_id == tenant_id))
