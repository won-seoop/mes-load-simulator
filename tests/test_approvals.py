from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import ApprovalRequest
from app.simulation import SimulationEngine
from tests.test_simulation import _freeze_main_time, _seed_inspect03_anomaly


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


def test_create_and_list_pending_request(client):
    res = client.post("/approvals", json=_payload())
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "PENDING"
    assert body["occurrence_count"] == 1

    listed = client.get("/approvals", params={"status": "PENDING"}).json()
    assert [r["id"] for r in listed] == [body["id"]]


def test_same_dedupe_key_folds_into_one_row_and_escalates_risk(client):
    first = client.post("/approvals", json=_payload(risk_level="MEDIUM")).json()
    res = client.post("/approvals", json=_payload(risk_level="CRITICAL"))
    assert res.status_code == 200
    merged = res.json()

    assert merged["id"] == first["id"]
    assert merged["occurrence_count"] == 2
    assert merged["risk_level"] == "CRITICAL"
    assert len(client.get("/approvals").json()) == 1


def test_different_dedupe_key_makes_a_separate_request(client):
    client.post("/approvals", json=_payload(dedupe_key="a"))
    client.post("/approvals", json=_payload(dedupe_key="b"))
    assert len(client.get("/approvals").json()) == 2


def test_pending_list_is_sorted_by_risk_then_age(client):
    client.post("/approvals", json=_payload(dedupe_key="low", risk_level="LOW"))
    client.post("/approvals", json=_payload(dedupe_key="crit", risk_level="CRITICAL"))
    client.post("/approvals", json=_payload(dedupe_key="high", risk_level="HIGH"))
    order = [r["risk_level"] for r in client.get("/approvals").json()]
    assert order == ["CRITICAL", "HIGH", "LOW"]


def test_invalid_risk_level_and_unknown_equipment_are_rejected(client):
    assert client.post("/approvals", json=_payload(risk_level="SUPER")).status_code == 422
    assert client.post("/approvals", json=_payload(equipment_id=99999)).status_code == 404


def test_approve_records_who_and_when(client):
    created = client.post("/approvals", json=_payload()).json()
    res = client.post(
        f"/approvals/{created['id']}/decision",
        json={"action": "approve", "decided_by": "kim"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "APPROVED"
    assert body["decided_by"] == "kim"
    assert body["decided_at"] is not None
    assert body["edited_proposal"] is None


def test_approve_with_edit_keeps_the_edited_text(client):
    created = client.post("/approvals", json=_payload()).json()
    body = client.post(
        f"/approvals/{created['id']}/decision",
        json={"action": "approve", "edited_proposal": "점검만 하고 배정은 유지"},
    ).json()
    assert body["status"] == "APPROVED"
    assert body["edited_proposal"] == "점검만 하고 배정은 유지"
    assert client.get("/approvals/summary").json()["edited_total"] == 1


def test_reject_requires_a_reason(client):
    created = client.post("/approvals", json=_payload()).json()
    url = f"/approvals/{created['id']}/decision"
    assert client.post(url, json={"action": "reject"}).status_code == 422
    assert client.post(url, json={"action": "reject", "reason": "  "}).status_code == 422
    ok = client.post(url, json={"action": "reject", "reason": "이미 점검 완료"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "REJECTED"
    assert ok.json()["decision_reason"] == "이미 점검 완료"


def test_deciding_twice_returns_409_and_keeps_first_decision(client):
    created = client.post("/approvals", json=_payload()).json()
    url = f"/approvals/{created['id']}/decision"
    assert client.post(url, json={"action": "approve"}).status_code == 200
    second = client.post(url, json={"action": "reject", "reason": "늦은 반려"})
    assert second.status_code == 409
    row = client.get("/approvals", params={"status": "APPROVED"}).json()[0]
    assert row["status"] == "APPROVED"


def test_decision_on_unknown_id_and_bad_action(client):
    assert client.post("/approvals/9999/decision", json={"action": "approve"}).status_code == 404
    created = client.post("/approvals", json=_payload()).json()
    bad = client.post(f"/approvals/{created['id']}/decision", json={"action": "maybe"})
    assert bad.status_code == 422


def test_expired_request_cannot_be_approved_and_is_reported_expired(client):
    created = client.post("/approvals", json=_payload(ttl_seconds=1)).json()
    db = SessionLocal()
    try:
        row = db.get(ApprovalRequest, created["id"])
        row.expires_at = datetime.utcnow() - timedelta(seconds=5)
        db.commit()
    finally:
        db.close()

    res = client.post(f"/approvals/{created['id']}/decision", json={"action": "approve"})
    assert res.status_code == 409
    listed = client.get("/approvals", params={"status": "EXPIRED"}).json()
    assert [r["id"] for r in listed] == [created["id"]]


def test_summary_counts_pending_by_risk_and_decisions(client):
    a = client.post("/approvals", json=_payload(dedupe_key="a", risk_level="CRITICAL")).json()
    client.post("/approvals", json=_payload(dedupe_key="b", risk_level="HIGH"))
    client.post("/approvals", json=_payload(dedupe_key="c", risk_level="HIGH"))
    client.post(f"/approvals/{a['id']}/decision", json={"action": "approve"})

    s = client.get("/approvals/summary").json()
    assert s["pending_count"] == 2
    assert s["pending_by_risk"]["HIGH"] == 2
    assert s["pending_by_risk"]["CRITICAL"] == 0
    assert s["approved_total"] == 1
    assert s["oldest_pending_age_seconds"] is not None


def test_summary_with_empty_queue_reports_no_oldest_age(client):
    s = client.get("/approvals/summary").json()
    assert s["pending_count"] == 0
    assert s["oldest_pending_age_seconds"] is None


def test_quality_anomaly_creates_one_request_that_counts_up_not_duplicates(client, monkeypatch):
    _seed_inspect03_anomaly(client)
    engine = SimulationEngine()
    from app import main as mes_main

    t0 = datetime(2026, 1, 1, 0, 0, 0)
    _freeze_main_time(monkeypatch, t0)
    for i in range(3):
        engine._next_anomaly_check_at = t0
        db = SessionLocal()
        try:
            engine._maybe_check_anomalies(db, t0 + timedelta(seconds=30 * i), mes_main)
        finally:
            db.close()

    rows = client.get("/approvals", params={"status": "PENDING"}).json()
    assert len(rows) == 1
    assert rows[0]["source_agent"] == "rule:quality-anomaly"
    assert rows[0]["risk_level"] == "CRITICAL"
    assert rows[0]["occurrence_count"] == 3
    assert "INSPECT-03" in rows[0]["title"]


def test_folding_refreshes_title_and_proposal_but_keeps_peak_risk(client):
    body = dict(source_agent="a", title="X 반복 DOWN (4회)", proposal="점검", evidence="4회",
                risk_level="HIGH", dedupe_key="k1")
    first = client.post("/approvals", json=body)
    assert first.status_code == 201
    second = client.post("/approvals", json={**body, "title": "X 반복 DOWN (5회)", "evidence": "5회", "risk_level": "MEDIUM"})
    assert second.status_code == 200
    row = second.json()
    assert row["title"] == "X 반복 DOWN (5회)" and row["evidence"] == "5회"
    assert row["risk_level"] == "HIGH" and row["occurrence_count"] == 2
