from decimal import Decimal

from sqlalchemy import select

from app.agent import run_agent
from app.models import AuditLog
from app.retrieval.hybrid import HybridRetriever
from app.tools.business import REGISTRY
from app.tools.registry import ToolContext


def ctx(db, p):
    return ToolContext(db=db, principal=p, retriever=HybridRetriever(db))


def run(db, p, name, **args):
    return REGISTRY.execute(ctx(db, p), name, args)


def test_stock_and_low_stock(db, manager):
    ex = run(db, manager, "check_stock", sku="FS-1003")
    assert ex.ok and ex.output.data["available"] == 50 and ex.output.data["status"] == "LOW"
    low = run(db, manager, "check_stock", low_stock_only=True).output.data["items"]
    assert {i["sku"] for i in low} == {"FS-1003", "FS-1005", "PK-4003", "SF-2005", "TL-3002", "TL-3005"}


def test_order_total_math(db, manager):
    # platinum: 20 x $23.75 = 475.00; -10% = 427.50; shipping 25 (under $500); tax 8% = 34.20
    q = run(db, manager, "calculate_order_total", items=[{"sku": "SF-2002", "quantity": 20}], customer_tier="platinum").output.data
    assert q["subtotal"] == "475.00" and q["total"] == "486.70"
    big = run(db, manager, "calculate_order_total", items=[{"sku": "TL-3001", "quantity": 15}], customer_tier="gold").output.data
    assert big["discount_pct"] == "7" and big["shipping"] == "0.00"
    haz = run(db, manager, "calculate_order_total", items=[{"sku": "CH-5001", "quantity": 1}], shipping_method="express")
    assert not haz.ok and "express" in haz.error


def test_tenant_isolation_in_tools(db, manager, verdant):
    assert run(db, manager, "get_order", order_number="SO-20002").ok is False
    assert run(db, verdant, "get_order", order_number="SO-10001").output.data["customer"] == "Trattoria Rossi"
    assert run(db, manager, "get_order", order_number="SO-10001").output.data["customer"] == "Northwind Fabrication"
    assert run(db, manager, "check_stock", sku="VF-1001").ok is False


def test_model_cannot_inject_tenant_or_sql(db, manager):
    for bad in ({"query": "x", "tenant_id": 2}, {"query": "x; DROP TABLE orders"}):
        ex = run(db, manager, "search_products", **bad)
        if "tenant_id" in bad:
            assert not ex.ok and "Extra inputs" in ex.error
    assert not run(db, manager, "execute_sql", sql="select 1").ok
    events = {e for (e,) in db.execute(select(AuditLog.event))}
    assert {"guardrail.unknown_tool", "guardrail.invalid_tool_args"} <= events


def test_viewer_masking_and_role_gating(db, viewer, manager):
    v = run(db, viewer, "get_order", order_number="SO-10003").output.data
    assert v["email"].startswith("p***@") and v["phone"].startswith("***")
    assert run(db, manager, "get_order", order_number="SO-10003").output.data["email"] == "priya@ironbridge.example"
    assert "draft_action" not in [s.name for s in REGISTRY.specs_for(viewer)]
    ex = run(db, viewer, "draft_action", action_type="update_order_status", order_number="SO-10004", new_status="cancelled")
    assert not ex.ok and "Permission denied" in ex.error


def test_agent_answers_with_valid_citations_and_usage(db, manager):
    r = run_agent(db, manager, "How long do customers have to return items?")
    assert "30 days" in r.answer and r.citations and r.citations[0]["type"] == "document"
    assert r.usage["llm_calls"] == 2 and r.usage["input_tokens"] > 0 and r.usage["cost_usd"] > 0


def test_agent_conversation_ownership(db, manager, viewer):
    import pytest
    r = run_agent(db, manager, "Is FS-1001 in stock?")
    with pytest.raises(LookupError):
        run_agent(db, viewer, "hi", conversation_id=r.conversation_id)


def test_decimal_money_is_exact():
    from app.services.pricing import Line, quote
    q = quote([Line("A-1", "x", 3, Decimal("0.10"))])
    assert q.subtotal == Decimal("0.30")


def test_wrong_category_hint_is_relaxed_but_never_crosses_tenants(db, manager, verdant):
    exact = run(db, manager, "search_documents", query="return window days after delivery").output
    assert exact.data["passages"]
    # a model guessed the wrong category: the correct document must still be found, and the tool says so
    wrong = run(db, manager, "search_documents", query="return window days after delivery", category="support")
    wrong2 = run(db, manager, "search_documents", query="return window days after delivery", category="legal")
    relaxed = [r for r in (wrong, wrong2) if "category filter was ignored" in r.output.summary]
    assert wrong.ok and wrong2.ok and (relaxed or all(r.output.data["passages"] for r in (wrong, wrong2)))
    # fallback is still tenant-scoped
    helix_docs = {p["document_id"] for p in exact.data["passages"]}
    other = run(db, verdant, "search_documents", query="return window days after delivery", category="legal").output
    assert not helix_docs & {p["document_id"] for p in other.data["passages"]}
