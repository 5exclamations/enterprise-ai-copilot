"""Chat, identity, usage statistics and evaluation-results endpoints."""
from __future__ import annotations

import json
import math
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agent import run_agent
from ..auth import Principal, current_principal
from ..db import get_db
from ..guardrails.validation import InputRejected
from ..models import AuditLog, Chunk, Document, PendingAction, Tenant, UsageLog, utcnow

router = APIRouter(prefix="/api", tags=["core"])
EVAL_RESULTS = Path(__file__).resolve().parents[2] / "evals" / "results" / "latest.json"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)  # real limit enforced (and sanitised) in the agent
    conversation_id: str | None = Field(default=None, max_length=32)


@router.get("/demo/users")
def demo_users(db: Session = Depends(get_db)):
    """Seeded demo personas for the login screen. Disabled (404) unless DEMO_MODE=true."""
    from ..auth import hash_key
    from ..config import get_settings
    from ..models import User
    from ..seed import DEMO_KEYS, USERS

    if not get_settings().demo_mode:
        raise HTTPException(404, "Not found")
    hashes = {hash_key(k): k for k in DEMO_KEYS.values()}
    out = []
    for slug, label, name, email, role in USERS:
        u = db.scalar(select(User).where(User.email == email))
        if u and u.api_key_hash in hashes:
            out.append({"label": label, "name": name, "email": email, "role": role,
                        "tenant": db.get(Tenant, u.tenant_id).name, "api_key": DEMO_KEYS[label]})
    return out


@router.get("/me")
def me(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    t = db.get(Tenant, p.tenant_id)
    return {"user_id": p.user_id, "name": p.name, "email": p.email, "role": p.role, "tenant": t.name}


@router.post("/chat")
def chat(req: ChatRequest, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    try:
        r = run_agent(db, p, req.message, req.conversation_id)
    except InputRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"conversation_id": r.conversation_id, "answer": r.answer, "citations": r.citations,
            "consulted": r.consulted, "tool_calls": r.tool_calls, "pending_actions": r.pending_actions,
            "usage": r.usage, "latency_ms": r.latency_ms, "flags": r.flags, "blocked": r.blocked,
            "confidence": r.confidence}


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, math.ceil(q * len(s)) - 1)], 1)


@router.get("/usage/summary")
def usage_summary(days: int = 14, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    logs = db.scalars(select(UsageLog).where(UsageLog.tenant_id == p.tenant_id, UsageLog.kind == "chat",
                                             UsageLog.created_at >= since)).all()
    by_day: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    for l in logs:
        d = by_day.setdefault(l.created_at.date().isoformat(), {"calls": 0, "tokens": 0})
        d["calls"] += 1
        d["tokens"] += l.input_tokens + l.output_tokens
        m = by_model.setdefault(f"{l.provider}/{l.model}", {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        m["calls"] += 1
        m["input_tokens"] += l.input_tokens
        m["output_tokens"] += l.output_tokens
        m["cost_usd"] += l.cost_usd or 0.0
    events = dict(db.execute(select(AuditLog.event, func.count()).where(AuditLog.tenant_id == p.tenant_id,
                                                                        AuditLog.created_at >= since)
                             .group_by(AuditLog.event)).all())
    tools = {k.removeprefix("tool.call:"): v for k, v in events.items() if k.startswith("tool.call:")}
    guardrails = {k.removeprefix("guardrail."): v for k, v in events.items() if k.startswith("guardrail.")}
    actions = dict(db.execute(select(PendingAction.status, func.count()).where(PendingAction.tenant_id == p.tenant_id)
                              .group_by(PendingAction.status)).all())
    lat = [l.latency_ms for l in logs]
    return {
        "window_days": days,
        "llm_calls": len(logs),
        "input_tokens": sum(l.input_tokens for l in logs),
        "output_tokens": sum(l.output_tokens for l in logs),
        "cost_usd": round(sum(l.cost_usd or 0.0 for l in logs), 6),
        "cost_unknown_calls": sum(1 for l in logs if l.cost_usd is None),
        "llm_latency_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95)},
        "by_day": [{"day": k, **v} for k, v in sorted(by_day.items())],
        "by_model": by_model, "tool_calls": tools, "guardrail_events": guardrails, "actions": actions,
        "corpus": {"documents": db.scalar(select(func.count()).select_from(Document).where(Document.tenant_id == p.tenant_id)),
                   "chunks": db.scalar(select(func.count()).select_from(Chunk).where(Chunk.tenant_id == p.tenant_id))},
    }


@router.get("/eval/latest")
def eval_latest(_: Principal = Depends(current_principal)):
    if not EVAL_RESULTS.exists():
        raise HTTPException(404, "No evaluation results yet. Run `python -m evals.run`.")
    return json.loads(EVAL_RESULTS.read_text())
