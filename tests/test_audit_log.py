"""Audit trail: who/when/what/why for state changes outside the approval
queue's own decision record (equipment status PATCH, work order release),
plus approval decisions themselves in the same feed."""

from tests.test_work_orders import _create_work_order


def _payload(**overrides):
    body = {
        "source_agent": "rule:test",
        "title": "INSPECT-03 품질 이상",
        "proposal": "신규 배정 중지 후 점검",
        "evidence": "불량률 100% vs 0%",
        "risk_level": "HIGH",
        "dedupe_key": "quality-anomaly:test",
        "ttl_seconds": 900,
    }
    body.update(overrides)
    return body


def test_equipment_status_change_is_audited(client):
    eq_id = client.get("/equipment").json()[0]["id"]

    resp = client.patch(f"/equipment/{eq_id}/status", json={"status": "DOWN", "reason": "MANUAL"})
    assert resp.status_code == 200

    rows = client.get("/audit-log", params={"entity_type": "equipment"}).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "equipment.status_changed"
    assert row["entity_id"] == eq_id
    assert row["before_value"] == "IDLE"
    assert row["after_value"] == "DOWN"
    assert row["reason"] == "MANUAL"


def test_setting_equipment_to_its_current_status_is_not_audited(client):
    eq_id = client.get("/equipment").json()[0]["id"]
    client.patch(f"/equipment/{eq_id}/status", json={"status": "IDLE"})

    rows = client.get("/audit-log", params={"entity_type": "equipment"}).json()
    assert rows == []


def test_work_order_release_is_audited(client):
    wo = _create_work_order(client)
    resp = client.post(f"/work-orders/{wo['id']}/release")
    assert resp.status_code == 200

    rows = client.get(
        "/audit-log", params={"entity_type": "work_order", "entity_id": wo["id"]}
    ).json()
    assert len(rows) == 1
    assert rows[0]["action"] == "work_order.released"
    assert rows[0]["before_value"] == "CREATED"
    assert rows[0]["after_value"] == "RELEASED"


def test_approval_decision_is_audited(client):
    created = client.post("/approvals", json=_payload()).json()
    resp = client.post(
        f"/approvals/{created['id']}/decision",
        json={"action": "reject", "reason": "false positive", "decided_by": "alice"},
    )
    assert resp.status_code == 200

    rows = client.get(
        "/audit-log", params={"entity_type": "approval_request", "entity_id": created["id"]}
    ).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "approval.decided"
    assert row["actor"] == "alice"
    assert row["before_value"] == "PENDING"
    assert row["after_value"] == "REJECTED"
    assert row["reason"] == "false positive"


def test_lost_decision_conflict_is_not_audited(client):
    created = client.post("/approvals", json=_payload()).json()
    client.post(f"/approvals/{created['id']}/decision", json={"action": "approve"})

    # Second decision on an already-decided request is a 409, not a new fact.
    conflict = client.post(
        f"/approvals/{created['id']}/decision",
        json={"action": "reject", "reason": "too late"},
    )
    assert conflict.status_code == 409

    rows = client.get(
        "/audit-log", params={"entity_type": "approval_request", "entity_id": created["id"]}
    ).json()
    assert len(rows) == 1


def test_audit_log_feed_spans_multiple_entity_types_newest_first(client):
    eq_id = client.get("/equipment").json()[0]["id"]
    client.patch(f"/equipment/{eq_id}/status", json={"status": "DOWN"})
    wo = _create_work_order(client)
    client.post(f"/work-orders/{wo['id']}/release")

    rows = client.get("/audit-log").json()
    assert [r["entity_type"] for r in rows] == ["work_order", "equipment"]
