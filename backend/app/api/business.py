"""Read-only business data endpoints and the human confirmation endpoints for drafted actions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import Principal, current_principal
from ..db import get_db
from ..guardrails.pii import mask_email, mask_phone
from ..models import Order, PendingAction, Product
from ..services import actions as svc
from ..tools.business import _order_query, _order_total, _stock_row

router = APIRouter(prefix="/api", tags=["business"])


@router.get("/products")
def products(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(Product).where(Product.tenant_id == p.tenant_id)
                      .options(selectinload(Product.inventory)).order_by(Product.sku)).all()
    return [{**_stock_row(x), "category": x.category, "unit_price": str(x.unit_price), "hazmat": x.hazmat}
            for x in rows]


@router.get("/orders")
def orders(status: str | None = None, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = _order_query(p.tenant_id)
    if status:
        q = q.where(Order.status == status)
    out = []
    for o in db.scalars(q.order_by(Order.number)).all():
        t = _order_total(o)
        out.append({"order_number": o.number, "customer": o.customer.name, "status": o.status,
                    "items": len(o.items), "total": str(t.total), "created_on": o.created_on.date().isoformat()})
    return out


@router.get("/orders/{number}")
def order_detail(number: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    o = db.scalar(_order_query(p.tenant_id).where(Order.number == number))
    if o is None:
        raise HTTPException(404, "Order not found")
    c = o.customer
    manager = p.can("manager")
    return {"order_number": o.number, "status": o.status, "customer": c.name, "tier": c.tier,
            "email": c.email if manager else mask_email(c.email), "phone": c.phone if manager else mask_phone(c.phone),
            "totals": _order_total(o).as_dict()}


def _action_json(a: PendingAction) -> dict:
    return {"id": a.id, "action_type": a.action_type, "status": a.status, "preview": a.preview, "reason": a.reason,
            "result": a.result, "created_at": a.created_at, "resolved_at": a.resolved_at, "payload": a.payload}


@router.get("/actions")
def list_actions(status: str | None = Query(None), p: Principal = Depends(current_principal),
                 db: Session = Depends(get_db)):
    q = select(PendingAction).where(PendingAction.tenant_id == p.tenant_id)
    if status:
        q = q.where(PendingAction.status == status)
    return [_action_json(a) for a in db.scalars(q.order_by(PendingAction.created_at.desc()).limit(50)).all()]


@router.post("/actions/{action_id}/confirm")
def confirm_action(action_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    try:
        return _action_json(svc.confirm(db, p, action_id))
    except svc.ActionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    try:
        return _action_json(svc.reject(db, p, action_id))
    except svc.ActionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
