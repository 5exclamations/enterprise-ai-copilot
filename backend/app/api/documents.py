"""Document management endpoints (ingestion, update, search inspection)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal, current_principal, require_role
from ..config import get_settings
from ..db import get_db
from ..models import Chunk, Document
from ..retrieval.hybrid import Filters, HybridRetriever
from ..services import documents as svc

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _summary(db: Session, d: Document) -> dict:
    total, flagged = db.execute(
        select(func.count(Chunk.id), func.coalesce(func.sum(sa_int(Chunk.flagged)), 0)).where(Chunk.document_id == d.id)
    ).one()
    return {"id": d.id, "title": d.title, "filename": d.filename, "category": d.category, "version": d.version,
            "content_type": d.content_type, "status": d.status, "chunks": total, "quarantined_chunks": int(flagged),
            "metadata": d.meta, "created_at": d.created_at, "updated_at": d.updated_at}


def sa_int(col):
    import sqlalchemy as sa

    return sa.case((col.is_(True), 1), else_=0)


async def _read_upload(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File too large (limit {limit // (1024 * 1024)} MB)")
    return data


def _ingest_response(res: svc.IngestResult, db: Session) -> dict:
    return {**_summary(db, res.document), "ingestion": {
        "chunks_total": res.chunks_total, "embeddings_computed": res.chunks_embedded,
        "embeddings_reused": res.chunks_reused, "chunks_quarantined": res.chunks_quarantined,
        "unchanged": res.unchanged}}


@router.get("")
def list_documents(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).where(Document.tenant_id == p.tenant_id).order_by(Document.title)).all()
    return [_summary(db, d) for d in docs]


@router.post("", status_code=201)
async def upload_document(file: UploadFile = File(...), title: str | None = Form(None),
                          category: str | None = Form(None), p: Principal = Depends(require_role("manager")),
                          db: Session = Depends(get_db)):
    data = await _read_upload(file)
    try:
        res = svc.ingest_document(db, tenant_id=p.tenant_id, user_id=p.user_id, filename=file.filename or "upload",
                                  data=data, content_type=file.content_type or "application/octet-stream",
                                  title=title or None, category=category or None)
    except svc.ParseError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _ingest_response(res, db)


@router.put("/{doc_id}")
async def update_document(doc_id: int, file: UploadFile = File(...), title: str | None = Form(None),
                          category: str | None = Form(None), p: Principal = Depends(require_role("manager")),
                          db: Session = Depends(get_db)):
    doc = svc.get_tenant_document(db, p.tenant_id, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    data = await _read_upload(file)
    try:
        res = svc.update_document(db, doc=doc, user_id=p.user_id, filename=file.filename or doc.filename, data=data,
                                  content_type=file.content_type or doc.content_type, title=title or None,
                                  category=category or None)
    except svc.ParseError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _ingest_response(res, db)


@router.get("/{doc_id}")
def get_document(doc_id: int, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    doc = svc.get_tenant_document(db, p.tenant_id, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return {**_summary(db, doc), "chunk_list": [
        {"index": c.chunk_index, "section": c.section, "page": c.page, "tokens": c.token_count,
         "flagged": c.flagged, "flag_reason": c.flag_reason, "content": c.content} for c in doc.chunks]}


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, p: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    doc = svc.get_tenant_document(db, p.tenant_id, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    svc.delete_document(db, doc, p.user_id)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    category: str | None = None
    effective_after: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    k: int = Field(default=5, ge=1, le=20)


@router.post("/search")
def search_documents(req: SearchRequest, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    """Inspect retrieval directly: shows both channel scores and ranks for every hit."""
    hits = HybridRetriever(db).search(p.tenant_id, req.query, k=req.k,
                                      filters=Filters(category=req.category, effective_after=req.effective_after))
    return [{"source_id": h.source_id, "document_id": h.document_id, "document": h.document_title,
             "category": h.category, "section": h.section, "page": h.page, "content": h.content,
             "score": round(h.score, 5), "semantic_score": h.semantic_score and round(h.semantic_score, 3),
             "semantic_rank": h.semantic_rank, "keyword_rank": h.keyword_rank} for h in hits]
