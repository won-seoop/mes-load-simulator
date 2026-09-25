from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import control_tower as ct
from app import equipment_agent
from app.database import SessionLocal
from app.models import ApprovalRequest, ControlTowerDecision, EquipmentDowntimeEvent
from app.simulation import SimulationEngine
from tests.test_simulation import _freeze_main_time, _seed_inspect03_anomaly

T0 = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture()
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _proposal(**overrides) -> ct.Proposal:
    base = dict(
        source_agent="rule:quality-anomaly",
        equipment_id=1,
        equipment_name="ETCH-01",
        title="ETCH-01 품질 이상",
        proposal="신규 배정을 중지하고 점검한다",
        evidence="불량률 30%",
        risk_level="HIGH",
        action_kind="STOP_NEW_DISPATCH",
        dedupe_key="quality-anomaly:1",
    )
    base.update(overrides)
    return ct.Proposal(**base)


def _equipment(client, name):
    return next(e for e in client.get("/equipment").json() if e["name"] == name)


def _add_downs(db, equipment_id, count, *, end=T0, spacing=30, reason="RANDOM_FAULT"):
    for i in range(count):
        db.add(
            EquipmentDowntimeEvent(
                equipment_id=equipment_id,
                reason=reason,
                started_at=end - timedelta(seconds=spacing * i),
            )
        )
    db.commit()


def test_two_agents_on_one_equipment_merge_into_one_queued_request(db):
    quality = _proposal()
    downtime = _proposal(
        source_agent="rule:equipment-downtime",
        title="ETCH-01 반복 DOWN",
        proposal="ETCH-01 설비를 점검한다",
        evidence="10분 내 DOWN 4회",
        risk_level="MEDIUM",
        action_kind="INSPECT_EQUIPMENT",
        dedupe_key="equipment-down:1",
    )
    written = ct.process(db, [quality, downtime], T0)

    assert len(written) == 1
    assert written[0].disposition == ct.QUEUE
    assert written[0].contributing_agents == "rule:quality-anomaly,rule:equipment-downtime"
    rows = db.query(ApprovalRequest).all()
    assert len(rows) == 1
    assert "불량률 30%" in rows[0].evidence and "DOWN 4회" in rows[0].evidence
    assert "rule:quality-anomaly" in rows[0].source_agent
    assert "rule:equipment-downtime" in rows[0].source_agent


def test_merged_risk_is_the_highest_of_the_contributors(db):
    planned = ct.plan(
        [
            _proposal(risk_level="MEDIUM", source_agent="a"),
            _proposal(risk_level="CRITICAL", source_agent="b"),
            _proposal(risk_level="LOW", source_agent="c"),
        ]
    )
    assert len(planned) == 1
    assert planned[0].risk_level == "CRITICAL"
    assert planned[0].contributing_agents == ("a", "b", "c")


def test_different_equipment_is_not_merged():
    planned = ct.plan([_proposal(equipment_id=1), _proposal(equipment_id=2, equipment_name="ETCH-02")])
    assert len(planned) == 2


def test_non_whitelisted_action_is_blocked_and_never_queued(db):
    written = ct.process(db, [_proposal(action_kind="SET_EQUIPMENT_DOWN", risk_level="CRITICAL")], T0)

    assert [w.disposition for w in written] == [ct.BLOCK]
    assert "SET_EQUIPMENT_DOWN" in written[0].reason
    assert written[0].approval_id is None
    assert db.query(ApprovalRequest).count() == 0


def test_blocked_action_does_not_ride_along_with_an_allowed_one(db):
    written = ct.process(
        db,
        [
            _proposal(action_kind="SCRAP_LOT", source_agent="rule:x", dedupe_key="x"),
            _proposal(),
        ],
        T0,
    )
    assert sorted(w.disposition for w in written) == [ct.BLOCK, ct.QUEUE]
    queued = db.query(ApprovalRequest).one()
    assert queued.source_agent == "rule:quality-anomaly"


def test_low_risk_is_auto_recorded_without_a_human(db):
    written = ct.process(db, [_proposal(risk_level="LOW")], T0)

    assert [w.disposition for w in written] == [ct.AUTO_RECORD]
    assert written[0].approval_id is None
    assert db.query(ApprovalRequest).count() == 0


@pytest.mark.parametrize("risk", ["MEDIUM", "HIGH", "CRITICAL"])
def test_medium_and_above_are_queued_with_an_approval_request(db, risk):
    written = ct.process(db, [_proposal(risk_level=risk)], T0)

    assert [w.disposition for w in written] == [ct.QUEUE]
    approval = db.get(ApprovalRequest, written[0].approval_id)
    assert approval.status == "PENDING"
    assert approval.risk_level == risk
    assert approval.equipment_id == 1


def test_invalid_risk_level_is_rejected_at_construction():
    with pytest.raises(ValueError):
        _proposal(risk_level="SUPER")


def test_standing_condition_folds_into_one_approval_and_one_decision(db):
    for i in range(3):
        ct.process(db, [_proposal()], T0 + timedelta(seconds=30 * i))

    approval = db.query(ApprovalRequest).one()
    assert approval.occurrence_count == 3
    assert db.query(ControlTowerDecision).count() == 1


def test_changed_risk_is_a_new_decision(db):
    ct.process(db, [_proposal(risk_level="HIGH")], T0)
    ct.process(db, [_proposal(risk_level="CRITICAL")], T0 + timedelta(seconds=30))

    assert db.query(ControlTowerDecision).count() == 2
    assert db.query(ApprovalRequest).one().risk_level == "CRITICAL"


def test_decisions_endpoint_returns_persisted_rows_newest_first(client, db):
    ct.process(db, [_proposal(risk_level="LOW", equipment_id=1)], T0)
    ct.process(db, [_proposal(action_kind="X", equipment_id=2, equipment_name="ETCH-02")], T0 + timedelta(seconds=60))
    ct.process(db, [_proposal(risk_level="HIGH", equipment_id=3, equipment_name="ETCH-03")], T0 + timedelta(seconds=120))

    body = client.get("/control-tower/decisions").json()

    assert [d["disposition"] for d in body] == [ct.QUEUE, ct.BLOCK, ct.AUTO_RECORD]
    assert body[0]["equipment_name"] == "ETCH-03"
    assert body[0]["contributing_agents"] == ["rule:quality-anomaly"]
    assert body[0]["approval_id"] is not None
    assert body[1]["approval_id"] is None


def test_decisions_endpoint_is_empty_at_first_and_capped_at_100(client, db):
    assert client.get("/control-tower/decisions").json() == []
    for i in range(105):
        db.add(
            ControlTowerDecision(
                decided_at=T0 + timedelta(seconds=i),
                disposition=ct.AUTO_RECORD,
                reason="r",
                contributing_agents="a",
                risk_level="LOW",
            )
        )
    db.commit()
    assert len(client.get("/control-tower/decisions").json()) == 100


def test_equipment_agent_proposes_after_repeated_downs(client, db):
    eq = _equipment(client, "ETCH-01")
    _add_downs(db, eq["id"], 4)

    proposals = equipment_agent.propose_from_downtime(db, T0)

    assert len(proposals) == 1
    p = proposals[0]
    assert p.action_kind == "INSPECT_EQUIPMENT"
    assert p.equipment_id == eq["id"]
    assert p.risk_level == "MEDIUM"
    assert "4회" in p.evidence


def test_equipment_agent_stays_quiet_below_threshold_and_outside_window(client, db):
    eq = _equipment(client, "ETCH-01")
    _add_downs(db, eq["id"], 2)
    old = _equipment(client, "ETCH-02")
    _add_downs(db, old["id"], 5, end=T0 - timedelta(seconds=equipment_agent.EQUIPMENT_DOWN_WINDOW_SECONDS + 60))

    assert equipment_agent.propose_from_downtime(db, T0) == []


def test_repeated_downs_at_threshold_are_low_and_only_recorded(client, db):
    eq = _equipment(client, "ETCH-01")
    _add_downs(db, eq["id"], 3)

    written = ct.process(db, equipment_agent.propose_from_downtime(db, T0), T0)

    assert [w.disposition for w in written] == [ct.AUTO_RECORD]
    assert db.query(ApprovalRequest).count() == 0


def _check(engine, monkeypatch, now):
    from app import main as mes_main

    _freeze_main_time(monkeypatch, now)
    engine._next_anomaly_check_at = now
    session = SessionLocal()
    try:
        engine._maybe_check_anomalies(session, now, mes_main)
    finally:
        session.close()


def test_simulation_merges_quality_and_equipment_agents_into_one_request(client, db, monkeypatch):
    _seed_inspect03_anomaly(client)
    _add_downs(db, _equipment(client, "INSPECT-03")["id"], 4)

    _check(SimulationEngine(), monkeypatch, T0)

    rows = db.query(ApprovalRequest).all()
    assert len(rows) == 1
    assert rows[0].risk_level == "CRITICAL"
    assert "rule:quality-anomaly" in rows[0].source_agent
    assert "rule:equipment-downtime" in rows[0].source_agent
    decision = db.query(ControlTowerDecision).one()
    assert decision.disposition == ct.QUEUE
    assert decision.contributing_agents == "rule:quality-anomaly,rule:equipment-downtime"


def test_watch_anomaly_still_creates_no_approval_request(client, db, monkeypatch):
    from app import main as mes_main

    watch = SimpleNamespace(
        equipment_id=1,
        equipment_name="ETCH-01",
        process_step="ETCH",
        severity="WATCH",
        defect_rate=0.2,
        peer_mean_rate=0.1,
        z_score=1.1,
        total_inspections=20,
    )
    monkeypatch.setattr(mes_main, "_detect_quality_anomalies", lambda _db: [watch])

    _check(SimulationEngine(), monkeypatch, T0)

    assert db.query(ApprovalRequest).count() == 0
    assert db.query(ControlTowerDecision).count() == 0
