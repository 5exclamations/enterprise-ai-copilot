"""The assistant's tool set. Every query is scoped by `ctx.principal.tenant_id`."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..guardrails.pii import mask_email, mask_phone, redact_secrets
from ..guardrails.validation import ORDER_PATTERN, SKU_PATTERN
from ..models import Customer, Order, OrderItem, Product
from ..retrieval.hybrid import Filters
from ..services import actions as action_service
from ..services import pricing
from ..text import tokenize
from .registry import Source, StrictArgs, Tool, ToolContext, ToolError, ToolOutput, ToolRegistry

OrderStatus = Literal["pending", "confirmed", "shipped", "delivered", "cancelled", "on_hold"]
_NOISE = {"product", "item", "sell", "catalog", "list", "show", "find", "search", "available", "stock",
          "have", "carry", "offer", "sold", "price", "cost", "much", "under", "below", "cheap", "need"}


# ----------------------------------------------------------------------------- helpers
def _find_product(db: Session, tenant_id: int, sku: str) -> Product:
    p = db.scalar(select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku)
                  .options(selectinload(Product.inventory)))
    if p is None:
        raise ToolError(f"No product with SKU {sku} in your catalog.")
    return p


def _stock_row(p: Product) -> dict:
    on_hand = sum(i.on_hand for i in p.inventory)
    reserved = sum(i.reserved for i in p.inventory)
    available = on_hand - reserved
    status = "OUT_OF_STOCK" if available <= 0 else "LOW" if available <= p.reorder_point else "OK"
    if not p.active:
        status = "DISCONTINUED"
    return {
        "sku": p.sku, "name": p.name, "on_hand": on_hand, "reserved": reserved, "available": available,
        "reorder_point": p.reorder_point, "status": status, "active": p.active,
        "warehouses": [{"warehouse": i.warehouse, "on_hand": i.on_hand, "reserved": i.reserved,
                        "available": i.on_hand - i.reserved} for i in sorted(p.inventory, key=lambda i: i.warehouse)],
    }


def _usd(x) -> str:
    return f"${Decimal(str(x)):,.2f}"


# ---------------------------------------------------------------------- search_products
class SearchProductsArgs(StrictArgs):
    query: str = Field(min_length=1, max_length=200, description="Free-text product search (name, category, SKU).")
    category: str | None = Field(default=None, max_length=60, description="Optional exact category filter.")
    max_price: float | None = Field(default=None, ge=0, description="Optional maximum unit price in USD.")
    include_discontinued: bool = False
    limit: int = Field(default=5, ge=1, le=10)


def search_products(ctx: ToolContext, a: SearchProductsArgs) -> ToolOutput:
    q = select(Product).where(Product.tenant_id == ctx.principal.tenant_id).options(selectinload(Product.inventory))
    if not a.include_discontinued:
        q = q.where(Product.active.is_(True))
    if a.category:
        q = q.where(func.lower(Product.category) == a.category.lower())
    if a.max_price is not None:
        q = q.where(Product.unit_price <= Decimal(str(a.max_price)))
    terms = [t for t in dict.fromkeys(tokenize(a.query)) if t not in _NOISE
             and not (a.max_price is not None and t.replace('.', '').isdigit())]
    scored = []
    for p in ctx.db.scalars(q):
        hay = set(tokenize(f"{p.sku} {p.name} {p.category} {p.description}"))
        score = sum(1 for t in terms if t in hay)
        if not terms or score:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1].sku))
    found = [p for _, p in scored[: a.limit]]
    rows = [{"sku": p.sku, "name": p.name, "category": p.category, "unit_price": str(p.unit_price),
             "available": _stock_row(p)["available"], "active": p.active} for p in found]
    if not rows:
        return ToolOutput(summary="No matching products found.", data={"products": []})
    lines = [f"{r['sku']} {r['name']} ({r['category']}) - {_usd(r['unit_price'])}, {r['available']} available"
             for r in rows]
    return ToolOutput(
        summary=f"Found {len(rows)} product(s): " + "; ".join(lines) + ".",
        data={"products": rows},
        sources=[Source(id=f"product:{p.sku}", type="product", title=f"{p.sku} {p.name}",
                        snippet=f"{p.category}, {_usd(p.unit_price)}") for p in found])


# ------------------------------------------------------------------------- check_stock
class CheckStockArgs(StrictArgs):
    sku: str | None = Field(default=None, pattern=SKU_PATTERN, description="SKU such as FS-1001.")
    low_stock_only: bool = Field(default=False, description="List every product at or below its reorder point.")


def check_stock(ctx: ToolContext, a: CheckStockArgs) -> ToolOutput:
    tid = ctx.principal.tenant_id
    if a.sku:
        row = _stock_row(_find_product(ctx.db, tid, a.sku))
        wh = ", ".join(f"{w['warehouse']}: {w['available']} available ({w['on_hand']} on hand, {w['reserved']} reserved)"
                       for w in row["warehouses"]) or "no warehouse records"
        return ToolOutput(
            summary=(f"{row['sku']} {row['name']}: {row['available']} units available "
                     f"({row['on_hand']} on hand, {row['reserved']} reserved); reorder point {row['reorder_point']}; "
                     f"status {row['status']}. By warehouse - {wh}."),
            data=row,
            sources=[Source(id=f"inventory:{row['sku']}", type="inventory", title=f"Inventory {row['sku']}",
                            snippet=f"{row['available']} available, status {row['status']}")])
    if not a.low_stock_only:
        raise ToolError("Provide a `sku`, or set `low_stock_only` to true.")
    products = ctx.db.scalars(select(Product).where(Product.tenant_id == tid, Product.active.is_(True))
                              .options(selectinload(Product.inventory)).order_by(Product.sku)).all()
    rows = [r for r in (_stock_row(p) for p in products) if r["status"] in ("LOW", "OUT_OF_STOCK")]
    if not rows:
        return ToolOutput(summary="No products are at or below their reorder point.", data={"items": []})
    txt = "; ".join(f"{r['sku']} {r['name']} ({r['available']} available, reorder at {r['reorder_point']})"
                    for r in rows)
    return ToolOutput(
        summary=f"{len(rows)} product(s) at or below reorder point: {txt}.", data={"items": rows},
        sources=[Source(id=f"inventory:{r['sku']}", type="inventory", title=f"Inventory {r['sku']}",
                        snippet=f"{r['available']} available, status {r['status']}") for r in rows])


# --------------------------------------------------------------------- order helpers
def _order_total(o: Order) -> pricing.Quote:
    lines = [pricing.Line(i.product.sku, i.product.name, i.quantity, i.unit_price, i.product.hazmat) for i in o.items]
    return pricing.quote(lines, o.customer.tier, o.shipping_method)


def _contact(ctx: ToolContext, c: Customer) -> dict:
    if ctx.principal.can("manager"):
        return {"contact": c.contact_name, "email": c.email, "phone": c.phone}
    return {"contact": c.contact_name, "email": mask_email(c.email), "phone": mask_phone(c.phone)}


def _order_query(tenant_id: int):
    return (select(Order).where(Order.tenant_id == tenant_id)
            .options(selectinload(Order.items).selectinload(OrderItem.product),
                     selectinload(Order.customer)))


# ----------------------------------------------------------------------------- get_order
class GetOrderArgs(StrictArgs):
    order_number: str = Field(pattern=ORDER_PATTERN, description="Order number such as SO-10004.")


def get_order(ctx: ToolContext, a: GetOrderArgs) -> ToolOutput:
    o = ctx.db.scalar(_order_query(ctx.principal.tenant_id).where(Order.number == a.order_number))
    if o is None:
        raise ToolError(f"Order {a.order_number} was not found.")
    q = _order_total(o)
    items = [f"{i.quantity} x {i.product.sku} {i.product.name}" for i in o.items]
    data = {
        "order_number": o.number, "status": o.status, "customer": o.customer.name, "tier": o.customer.tier,
        "created_on": o.created_on.date().isoformat(), "shipping_method": o.shipping_method,
        "items": [{"sku": i.product.sku, "name": i.product.name, "quantity": i.quantity,
                   "unit_price": str(i.unit_price)} for i in o.items],
        "totals": q.as_dict(), **_contact(ctx, o.customer),
    }
    return ToolOutput(
        summary=(f"Order {o.number} for {o.customer.name} ({o.customer.tier} tier) is {o.status}. "
                 f"Placed {data['created_on']}, {o.shipping_method} shipping. Items: {'; '.join(items)}. "
                 f"Total {_usd(q.total)} (subtotal {_usd(q.subtotal)}, shipping {_usd(q.shipping + q.hazmat_surcharge)}, "
                 f"tax {_usd(q.tax)})."),
        data=data,
        sources=[Source(id=f"order:{o.number}", type="order", title=f"Order {o.number}",
                        snippet=f"{o.customer.name}, {o.status}, {_usd(q.total)}")])


# --------------------------------------------------------------------------- list_orders
class ListOrdersArgs(StrictArgs):
    status: OrderStatus | None = None
    customer: str | None = Field(default=None, max_length=120, description="Customer name (partial match).")
    limit: int = Field(default=10, ge=1, le=25)


def list_orders(ctx: ToolContext, a: ListOrdersArgs) -> ToolOutput:
    q = _order_query(ctx.principal.tenant_id)
    if a.status:
        q = q.where(Order.status == a.status)
    if a.customer:
        q = q.join(Customer, Customer.id == Order.customer_id).where(
            Customer.tenant_id == ctx.principal.tenant_id,
            func.lower(Customer.name).like(f"%{a.customer.lower()}%"))
    orders = ctx.db.scalars(q.order_by(Order.number).limit(a.limit)).all()
    if not orders:
        return ToolOutput(summary="No matching orders found.", data={"orders": []})
    rows = []
    for o in orders:
        t = _order_total(o)
        rows.append({"order_number": o.number, "customer": o.customer.name, "status": o.status,
                     "total": str(t.total), "created_on": o.created_on.date().isoformat()})
    txt = "; ".join(f"{r['order_number']} {r['customer']} - {r['status']}, {_usd(r['total'])}" for r in rows)
    return ToolOutput(
        summary=f"{len(rows)} order(s): {txt}.", data={"orders": rows},
        sources=[Source(id=f"order:{r['order_number']}", type="order", title=f"Order {r['order_number']}",
                        snippet=f"{r['customer']}, {r['status']}") for r in rows])


# ------------------------------------------------------------------ calculate_order_total
class LineItem(StrictArgs):
    sku: str = Field(pattern=SKU_PATTERN)
    quantity: int = Field(ge=1, le=100_000)


class CalculateTotalArgs(StrictArgs):
    items: list[LineItem] = Field(min_length=1, max_length=50)
    customer: str | None = Field(default=None, max_length=120, description="Customer name, to apply their tier discount.")
    customer_tier: Literal["standard", "gold", "platinum"] | None = None
    shipping_method: Literal["standard", "express"] = "standard"


def calculate_order_total(ctx: ToolContext, a: CalculateTotalArgs) -> ToolOutput:
    tid = ctx.principal.tenant_id
    tier = a.customer_tier or "standard"
    cust_name = None
    if a.customer:
        c = ctx.db.scalar(select(Customer).where(Customer.tenant_id == tid,
                                                 func.lower(Customer.name).like(f"%{a.customer.lower()}%")))
        if c is None:
            raise ToolError(f"No customer matching '{a.customer}'.")
        tier, cust_name = c.tier, c.name
    lines = []
    for it in a.items:
        p = _find_product(ctx.db, tid, it.sku)
        if not p.active:
            raise ToolError(f"{p.sku} is discontinued and cannot be quoted.")
        lines.append(pricing.Line(p.sku, p.name, it.quantity, p.unit_price, p.hazmat))
    if a.shipping_method == "express" and any(l.hazmat for l in lines):
        raise ToolError("Hazmat items cannot ship express (ground only).")
    q = pricing.quote(lines, tier, a.shipping_method)
    d = q.as_dict()
    parts = ", ".join(f"{l.quantity} x {l.sku}" for l in lines)
    who = f" for {cust_name} ({tier})" if cust_name else f" ({tier} pricing)"
    return ToolOutput(
        summary=(f"Quote{who}: {parts}. Subtotal {_usd(q.subtotal)}, discount {_usd(q.discount)} ({q.discount_pct}%), "
                 f"shipping {_usd(q.shipping)}"
                 + (f", hazmat surcharge {_usd(q.hazmat_surcharge)}" if q.hazmat_surcharge else "")
                 + f", tax {_usd(q.tax)}. Total {_usd(q.total)}."),
        data=d,
        sources=[Source(id="calc:quote", type="calculation", title="Order total calculation",
                        snippet=f"Total {_usd(q.total)}; " + "; ".join(q.notes))])


# --------------------------------------------------------------------- search_documents
class SearchDocsArgs(StrictArgs):
    query: str = Field(min_length=2, max_length=300, description="Natural-language question or keywords.")
    category: Literal["policy", "sop", "catalog", "legal", "support", "other"] | None = None
    limit: int = Field(default=5, ge=1, le=8)


def search_documents(ctx: ToolContext, a: SearchDocsArgs) -> ToolOutput:
    hits = ctx.retriever.search(ctx.principal.tenant_id, a.query, k=a.limit,
                                filters=Filters(category=a.category))
    if not hits:
        return ToolOutput(summary="No relevant passages found in company documents.", data={"passages": []})
    passages = [{
        "source_id": h.source_id, "document": h.document_title, "section": h.section, "page": h.page,
        "text": redact_secrets(h.content[:1200]).text, "score": round(h.score, 4),
        "semantic_score": None if h.semantic_score is None else round(h.semantic_score, 3),
        "keyword_rank": h.keyword_rank, "semantic_rank": h.semantic_rank, "document_id": h.document_id,
        "category": h.category, "version": h.doc_version,
    } for h in hits]
    return ToolOutput(
        summary=f"Retrieved {len(hits)} passage(s) from: " + ", ".join(dict.fromkeys(h.document_title for h in hits)) + ".",
        data={"passages": passages},
        sources=[Source(id=h.source_id, type="document", title=h.document_title + (f" · {h.section.split(' > ')[-1]}" if h.section and h.section.split(" > ")[-1] != h.document_title else ""),
                        snippet=redact_secrets(h.content[:240]).text, meta={"page": h.page, "document_id": h.document_id,
                                                       "version": h.doc_version}) for h in hits])


# ------------------------------------------------------------------------- draft_action
class DraftActionArgs(StrictArgs):
    action_type: Literal["update_order_status", "create_purchase_order", "adjust_inventory"]
    order_number: str | None = Field(default=None, pattern=ORDER_PATTERN)
    new_status: OrderStatus | None = None
    sku: str | None = Field(default=None, pattern=SKU_PATTERN)
    quantity: int | None = Field(default=None, ge=1, le=100_000)
    supplier: str | None = Field(default=None, max_length=120)
    warehouse: str | None = Field(default=None, max_length=40)
    delta: int | None = Field(default=None, ge=-10_000, le=10_000)
    reason: str = Field(default="", max_length=500)


_ACTION_FIELDS = {
    "update_order_status": ("order_number", "new_status"),
    "create_purchase_order": ("sku", "quantity", "supplier"),
    "adjust_inventory": ("sku", "warehouse", "delta"),
}


def draft_action(ctx: ToolContext, a: DraftActionArgs) -> ToolOutput:
    allowed = _ACTION_FIELDS[a.action_type]
    given = {k: getattr(a, k) for k in ("order_number", "new_status", "sku", "quantity", "supplier", "warehouse", "delta")
             if getattr(a, k) is not None}
    stray = set(given) - set(allowed)
    if stray:
        raise ToolError(f"Fields not valid for {a.action_type}: {', '.join(sorted(stray))}.")
    try:
        action = action_service.draft(ctx.db, ctx.principal, {"action_type": a.action_type, **given},
                                      a.reason, ctx.conversation_id)
    except action_service.ActionError as exc:
        raise ToolError(str(exc)) from exc
    pv = action.preview
    change = "; ".join(f"{c['field']}: {c['from']} -> {c['to']}" if c["from"] is not None else f"{c['field']}: {c['to']}"
                       for c in pv["changes"])
    return ToolOutput(
        summary=(f"Drafted '{pv['title']}' ({change}). This is NOT executed: it is waiting for explicit confirmation "
                 f"by a manager (action {action.id})."),
        data={"action_id": action.id, "status": "pending_confirmation", "action_type": a.action_type,
              "preview": pv, "reason": a.reason},
        sources=[Source(id=f"action:{action.id}", type="action", title=pv["title"], snippet=change)])


# ------------------------------------------------------------------------ registration
def build_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(Tool("search_documents", "Search company policies, SOPs and catalog documents (hybrid semantic + keyword). "
                    "Use for any question about policies, procedures, terms or how the business operates.",
                    SearchDocsArgs, search_documents))
    r.register(Tool("search_products", "Search the product catalog by name, category or SKU.", SearchProductsArgs,
                    search_products))
    r.register(Tool("check_stock", "Check inventory for a SKU (per warehouse), or list all low-stock products.",
                    CheckStockArgs, check_stock))
    r.register(Tool("get_order", "Retrieve one order by order number, with items, status and totals.", GetOrderArgs,
                    get_order))
    r.register(Tool("list_orders", "List orders, optionally filtered by status or customer name.", ListOrdersArgs,
                    list_orders))
    r.register(Tool("calculate_order_total", "Deterministically price an order (discounts, shipping, tax). "
                    "Always use this instead of doing arithmetic yourself.", CalculateTotalArgs, calculate_order_total))
    r.register(Tool("draft_action", "Draft a state-changing business action (order status change, purchase order, "
                    "inventory adjustment). This only creates a PENDING draft; a human must confirm it separately.",
                    DraftActionArgs, draft_action, min_role="manager", mutating=True))
    return r


REGISTRY = build_registry()
