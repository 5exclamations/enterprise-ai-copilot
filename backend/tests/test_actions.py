from sqlalchemy import select

from app.agent import run_agent
from app.models import Order, PendingAction
from app.services import actions
from tests.conftest import hdr


def status(db, number, tenant):
    return db.scalar(select(Order.status).where(Order.number == number, Order.tenant_id == tenant))


def test_assistant_only_drafts_never_executes(db, manager):
    r = run_agent(db, manager, "Cancel order SO-10004")
    assert r.pending_actions and r.pending_actions[0]["action_type"] == "update_order_status"
    assert status(db, "SO-10004", manager.tenant_id) == "pending"  # untouched
    assert db.scalar(select(PendingAction.status)) == "pending"


def test_confirm_executes_once(db, manager):
    a = actions.draft(db, manager, {"action_type": "update_order_status", "order_number": "SO-10004", "new_status": "cancelled"})
    actions.confirm(db, manager, a.id)
    assert status(db, "SO-10004", manager.tenant_id) == "cancelled"
    try:
        actions.confirm(db, manager, a.id)
        raise AssertionError("second confirm must fail")
    except actions.ActionError as e:
        assert e.status == 409


def test_viewer_cannot_draft_or_confirm(db, manager, viewer):
    a = actions.draft(db, manager, {"action_type": "update_order_status", "order_number": "SO-10004", "new_status": "on_hold"})
    for fn in (lambda: actions.confirm(db, viewer, a.id), lambda: actions.draft(db, viewer, {"action_type": "update_order_status", "order_number": "SO-10004", "new_status": "on_hold"})):
        try:
            fn(); raise AssertionError
        except actions.ActionError as e:
            assert e.status == 403


def test_cross_tenant_confirm_is_404(db, manager, verdant):
    a = actions.draft(db, manager, {"action_type": "update_order_status", "order_number": "SO-10004", "new_status": "on_hold"})
    try:
        actions.confirm(db, verdant, a.id); raise AssertionError
    except actions.ActionError as e:
        assert e.status == 404


def test_invalid_transition_and_stale_state(db, manager):
    try:
        actions.draft(db, manager, {"action_type": "update_order_status", "order_number": "SO-10002", "new_status": "cancelled"})  # shipped
        raise AssertionError
    except actions.ActionError as e:
        assert e.status == 409
    a = actions.draft(db, manager, {"action_type": "update_order_status", "order_number": "SO-10004", "new_status": "cancelled"})
    db.scalar(select(Order).where(Order.number == "SO-10004", Order.tenant_id == manager.tenant_id)).status = "confirmed"
    db.commit()
    try:
        actions.confirm(db, manager, a.id); raise AssertionError
    except actions.ActionError as e:
        assert e.status == 409
    assert db.get(PendingAction, a.id).status == "failed"


def test_inventory_and_po_actions(db, manager):
    a = actions.draft(db, manager, {"action_type": "adjust_inventory", "sku": "FS-1003", "warehouse": "Reno", "delta": 150})
    assert a.preview["changes"][0]["to"] == 170 and a.preview["warnings"]
    assert actions.confirm(db, manager, a.id).result["to"] == 170
    po = actions.draft(db, manager, {"action_type": "create_purchase_order", "sku": "FS-1003", "quantity": 500})
    assert actions.confirm(db, manager, po.id).result["purchase_order"] == "PO-70001"


def test_extra_payload_fields_rejected(db, manager):
    try:
        actions.draft(db, manager, {"action_type": "update_order_status", "order_number": "SO-10004", "new_status": "cancelled", "tenant_id": 2})
        raise AssertionError
    except actions.ActionError as e:
        assert e.status == 400


def test_confirm_over_http(client, db):
    r = client.post("/api/chat", json={"message": "Put order SO-10004 on hold"}, headers=hdr("helix-manager")).json()
    aid = r["pending_actions"][0]["action_id"]
    assert client.post(f"/api/actions/{aid}/confirm", headers=hdr("helix-viewer")).status_code == 403
    assert client.post(f"/api/actions/{aid}/confirm", headers=hdr("verdant-manager")).status_code == 404
    ok = client.post(f"/api/actions/{aid}/confirm", headers=hdr("helix-manager"))
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
