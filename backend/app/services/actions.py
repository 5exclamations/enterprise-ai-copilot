"""State-changing business actions: draft -> human confirmation -> execute.

The assistant can only call `draft`, which writes a PendingAction row and touches no
business data. `confirm` is exposed solely as an authenticated HTTP endpoint (a human
clicking a button); it is deliberately not reachable from any LLM tool.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal
from ..config import get_settings
from ..guardrails.validation import ORDER_PATTERN, SKU_PATTERN
from ..models import AuditLog, Inventory, Order, PendingAction, Product, PurchaseOrder, utcnow

ORDER_TRANSITIONS = {
    "pending": {"confirmed", "cancelled", "on_hold"},
    "confirmed": {"shipped", "cancelled", "on_hold"},
    "on_hold": {"pending", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


class ActionError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpdateOrderStatus(_Strict):
    action_type: Literal["update_order_status"]
    order_number: str = Field(pattern=ORDER_PATTERN)
    new_status: Literal["pending", "confirmed", "shipped", "delivered", "cancelled", "on_hold"]


class CreatePurchaseOrder(_Strict):
    action_type: Literal["create_purchase_order"]
    sku: str = Field(pattern=SKU_PATTERN)
    quantity: int = Field(ge=1, le=100_000)
    supplier: str | None = Field(default=None, max_length=120)


class AdjustInventory(_Strict):
    action_type: Literal["adjust_inventory"]
    sku: str = Field(pattern=SKU_PATTERN)
    warehouse: str = Field(min_length=2, max_length=40)
    delta: int = Field(ge=-10_000, le=10_000)


ActionPayload = Annotated[Union[UpdateOrderStatus, CreatePurchaseOrder, AdjustInventory],
                          Field(discriminator="action_type")]


class _Wrapper(BaseModel):
    payload: ActionPayload


def parse_payload(raw: dict):
    try:
        return _Wrapper(payload=raw).payload
    except ValidationError as exc:
        msg = "; ".join(f"{'.'.join(map(str, e['loc'][1:]))}: {e['msg']}" for e in exc.errors())
        raise ActionError(f"Invalid action: {msg}") from exc


def _product(db: Session, tenant_id: int, sku: str) -> Product:
    p = db.scalar(select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku))
    if p is None:
        raise ActionError(f"Unknown SKU {sku}", 404)
    return p


def _order(db: Session, tenant_id: int, number: str) -> Order:
    o = db.scalar(select(Order).where(Order.tenant_id == tenant_id, Order.number == number))
    if o is None:
        raise ActionError(f"Order {number} not found", 404)
    return o


def _build_preview(db: Session, tenant_id: int, p) -> dict:
    if isinstance(p, UpdateOrderStatus):
        o = _order(db, tenant_id, p.order_number)
        if p.new_status not in ORDER_TRANSITIONS[o.status]:
            raise ActionError(f"Order {o.number} is '{o.status}'; cannot move it to '{p.new_status}'.", 409)
        return {"title": f"Change order {o.number} status", "expected": {"status": o.status},
                "changes": [{"field": "status", "from": o.status, "to": p.new_status}],
                "warnings": ["Customer will be notified."] if p.new_status in ("cancelled", "shipped") else []}
    if isinstance(p, CreatePurchaseOrder):
        prod = _product(db, tenant_id, p.sku)
        supplier = p.supplier or prod.supplier or "Unassigned supplier"
        est = prod.unit_price * p.quantity * Decimal("0.6")  # rough landed-cost heuristic for the preview only
        warnings = ["Purchase orders over $5,000 need director approval (Replenishment SOP)."] if est > 5000 else []
        if not prod.active:
            warnings.append("Product is discontinued.")
        return {"title": f"Create purchase order for {prod.sku}", "expected": {},
                "changes": [{"field": "product", "from": None, "to": f"{prod.sku} {prod.name}"},
                            {"field": "quantity", "from": None, "to": p.quantity},
                            {"field": "supplier", "from": None, "to": supplier}],
                "warnings": warnings}
    if isinstance(p, AdjustInventory):
        prod = _product(db, tenant_id, p.sku)
        inv = db.scalar(select(Inventory).where(Inventory.product_id == prod.id, Inventory.tenant_id == tenant_id,
                                                Inventory.warehouse == p.warehouse))
        if inv is None:
            raise ActionError(f"{p.sku} has no inventory record at warehouse '{p.warehouse}'.", 404)
        after = inv.on_hand + p.delta
        if after < max(0, inv.reserved):
            raise ActionError(f"Resulting on-hand ({after}) would drop below reserved units ({inv.reserved}).", 409)
        warnings = ["Adjustments over 100 units need manager sign-off with a reason."] if abs(p.delta) > 100 else []
        return {"title": f"Adjust {prod.sku} inventory at {inv.warehouse}", "expected": {"on_hand": inv.on_hand},
                "changes": [{"field": "on_hand", "from": inv.on_hand, "to": after}], "warnings": warnings}
    raise ActionError("Unsupported action")


def draft(db: Session, principal: Principal, raw_payload: dict, reason: str = "",
          conversation_id: str | None = None) -> PendingAction:
    if not principal.can("manager"):
        raise ActionError("Your role may not draft business actions.", 403)
    p = parse_payload(raw_payload)
    preview = _build_preview(db, principal.tenant_id, p)
    action = PendingAction(
        tenant_id=principal.tenant_id, user_id=principal.user_id, action_type=p.action_type,
        payload=p.model_dump(), preview=preview, reason=reason[:500], conversation_id=conversation_id)
    db.add(action)
    db.add(AuditLog(tenant_id=principal.tenant_id, user_id=principal.user_id, event="action.drafted",
                    detail={"type": p.action_type, "payload": p.model_dump()}))
    db.commit()
    return action


def _load(db: Session, principal: Principal, action_id: str) -> PendingAction:
    a = db.scalar(select(PendingAction).where(PendingAction.id == action_id,
                                              PendingAction.tenant_id == principal.tenant_id))
    if a is None:
        raise ActionError("Action not found", 404)
    return a


def confirm(db: Session, principal: Principal, action_id: str) -> PendingAction:
    if not principal.can("manager"):
        raise ActionError("Only managers or admins can confirm actions.", 403)
    a = _load(db, principal, action_id)
    if a.status != "pending":
        raise ActionError(f"Action already {a.status}.", 409)
    if utcnow() - _aware(a.created_at) > timedelta(minutes=get_settings().action_ttl_minutes):
        a.status, a.resolved_at, a.resolved_by = "expired", utcnow(), principal.user_id
        db.commit()
        raise ActionError("Action expired; ask the assistant to draft it again.", 410)
    p = parse_payload(a.payload)  # re-validate stored payload: never trust persisted data blindly
    try:
        fresh = _build_preview(db, principal.tenant_id, p)  # re-check state at execution time
        if fresh["expected"] != a.preview.get("expected"):
            raise ActionError("Data changed since this action was drafted; please review and redraft.", 409)
        result = _execute(db, principal.tenant_id, p)
    except ActionError as exc:
        db.rollback()
        a = _load(db, principal, action_id)
        a.status, a.result, a.resolved_at, a.resolved_by = "failed", {"error": str(exc)}, utcnow(), principal.user_id
        db.add(AuditLog(tenant_id=principal.tenant_id, user_id=principal.user_id, event="action.failed",
                        detail={"action_id": a.id, "error": str(exc)}))
        db.commit()
        raise
    a.status, a.result, a.resolved_at, a.resolved_by = "confirmed", result, utcnow(), principal.user_id
    db.add(AuditLog(tenant_id=principal.tenant_id, user_id=principal.user_id, event="action.executed",
                    detail={"action_id": a.id, "type": a.action_type, "result": result}))
    db.commit()
    return a


def reject(db: Session, principal: Principal, action_id: str) -> PendingAction:
    a = _load(db, principal, action_id)
    if a.status != "pending":
        raise ActionError(f"Action already {a.status}.", 409)
    if not principal.can("manager") and a.user_id != principal.user_id:
        raise ActionError("Not allowed", 403)
    a.status, a.resolved_at, a.resolved_by = "rejected", utcnow(), principal.user_id
    db.add(AuditLog(tenant_id=principal.tenant_id, user_id=principal.user_id, event="action.rejected",
                    detail={"action_id": a.id}))
    db.commit()
    return a


def _execute(db: Session, tenant_id: int, p) -> dict:
    if isinstance(p, UpdateOrderStatus):
        o = _order(db, tenant_id, p.order_number)
        old, o.status = o.status, p.new_status
        return {"order": o.number, "from": old, "to": o.status}
    if isinstance(p, CreatePurchaseOrder):
        prod = _product(db, tenant_id, p.sku)
        n = db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id)) or 0
        po = PurchaseOrder(tenant_id=tenant_id, number=f"PO-{70001 + n}", product_id=prod.id, quantity=p.quantity,
                           supplier=p.supplier or prod.supplier or "Unassigned supplier", status="draft")
        db.add(po)
        return {"purchase_order": po.number, "sku": prod.sku, "quantity": p.quantity, "supplier": po.supplier}
    if isinstance(p, AdjustInventory):
        prod = _product(db, tenant_id, p.sku)
        inv = db.scalar(select(Inventory).where(Inventory.product_id == prod.id, Inventory.tenant_id == tenant_id,
                                                Inventory.warehouse == p.warehouse))
        old, inv.on_hand = inv.on_hand, inv.on_hand + p.delta
        return {"sku": prod.sku, "warehouse": inv.warehouse, "from": old, "to": inv.on_hand}
    raise ActionError("Unsupported action")


def _aware(dt):
    from datetime import timezone

    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
