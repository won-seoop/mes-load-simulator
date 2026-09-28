from datetime import datetime, timedelta

import pytest

from app import control_tower as ct
from app import production_agent
from app.database import SessionLocal
from app.models import ApprovalRequest, PROCESS_ROUTE

T0 = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture()
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _freeze_time(monkeypatch, when):
    """Make app.main's datetime.utcnow() return a fixed instant."""

    class _Frozen(datetime):
        @classmethod
        def utcnow(cls):
            return when

    monkeypatch.setattr("app.main.datetime", _Frozen)


def _hold_lot_at_step(client, monkeypatch, held_at, step_index=0):
    """Create a lot and drive it into HOLD by taking down every tool on
    PROCESS_ROUTE[step_index] at a fixed, known timestamp."""
    _freeze_time(monkeypatch, held_at)
    lot = client.post("/lots", json={"product": "WAFER-A"}).json()
    for _ in range(step_index):
        lot = client.post(f"/lots/{lot['id']}/advance").json()

    equipment = client.get("/equipment").json()
    step = PROCESS_ROUTE[step_index]
    step_equipment_ids = [eq["id"] for eq in equipment if eq["process_step"] == step]
    for eq_id in step_equipment_ids:
        client.patch(f"/equipment/{eq_id}/status", json={"status": "DOWN"})

    lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["status"] == "HOLD"
    return lot, step, step_equipment_ids


def test_no_proposal_when_nothing_is_held(db):
    assert production_agent.propose_from_step_hold_wait(db, T0) == []


def test_no_proposal_below_the_lowest_risk_tier(client, db, monkeypatch):
    _hold_lot_at_step(client, monkeypatch, T0)
    checked_at = T0 + timedelta(seconds=production_agent.HOLD_RISK_TIERS[-1][0] - 1)

    assert production_agent.propose_from_step_hold_wait(db, checked_at) == []


def test_low_risk_proposal_at_the_lowest_tier(client, db, monkeypatch):
    _, step, _ = _hold_lot_at_step(client, monkeypatch, T0)
    checked_at = T0 + timedelta(seconds=production_agent.HOLD_RISK_TIERS[-1][0])

    proposals = production_agent.propose_from_step_hold_wait(db, checked_at)

    assert len(proposals) == 1
    p = proposals[0]
    assert p.source_agent == "rule:production-hold"
    assert p.equipment_id is None
    assert p.equipment_name == step
    assert p.action_kind == "INSPECT_EQUIPMENT"
    assert p.risk_level == "LOW"
    assert p.dedupe_key == f"production-hold:{step}"
    assert "1건" in p.evidence


def test_high_risk_proposal_past_the_highest_tier(client, db, monkeypatch):
    _hold_lot_at_step(client, monkeypatch, T0)
    checked_at = T0 + timedelta(seconds=production_agent.HOLD_RISK_TIERS[0][0])

    proposals = production_agent.propose_from_step_hold_wait(db, checked_at)

    assert proposals[0].risk_level == "HIGH"


def test_resolved_hold_stops_counting(client, db, monkeypatch):
    lot, step, step_equipment_ids = _hold_lot_at_step(client, monkeypatch, T0)
    released_at = T0 + timedelta(seconds=production_agent.HOLD_RISK_TIERS[0][0])
    _freeze_time(monkeypatch, released_at)
    client.patch(f"/equipment/{step_equipment_ids[0]}/status", json={"status": "IDLE"})
    lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["status"] != "HOLD"

    assert production_agent.propose_from_step_hold_wait(db, released_at) == []


def test_second_stuck_lot_at_the_same_step_only_raises_the_count(client, db, monkeypatch):
    _hold_lot_at_step(client, monkeypatch, T0)
    _hold_lot_at_step(client, monkeypatch, T0 + timedelta(seconds=5))
    checked_at = T0 + timedelta(seconds=production_agent.HOLD_RISK_TIERS[-1][0] + 5)

    proposals = production_agent.propose_from_step_hold_wait(db, checked_at)

    assert len(proposals) == 1
    assert "2건" in proposals[0].evidence


def test_two_different_steps_produce_two_proposals(client, db, monkeypatch):
    _hold_lot_at_step(client, monkeypatch, T0, step_index=0)
    lot_step1, _, _ = None, None, None
    # Drive a second lot through step 0 (needs its tools back up) then hold it at step 1.
    equipment = client.get("/equipment").json()
    step0_ids = [eq["id"] for eq in equipment if eq["process_step"] == PROCESS_ROUTE[0]]
    for eq_id in step0_ids:
        client.patch(f"/equipment/{eq_id}/status", json={"status": "IDLE"})
    _hold_lot_at_step(client, monkeypatch, T0, step_index=1)

    checked_at = T0 + timedelta(seconds=production_agent.HOLD_RISK_TIERS[-1][0])
    proposals = production_agent.propose_from_step_hold_wait(db, checked_at)

    assert {p.equipment_name for p in proposals} == {PROCESS_ROUTE[0], PROCESS_ROUTE[1]}


def test_control_tower_queues_medium_and_above(client, db, monkeypatch):
    _hold_lot_at_step(client, monkeypatch, T0)
    checked_at = T0 + timedelta(seconds=production_agent.HOLD_RISK_TIERS[1][0])

    written = ct.process(db, production_agent.propose_from_step_hold_wait(db, checked_at), checked_at)

    assert [w.disposition for w in written] == [ct.QUEUE]
    assert db.query(ApprovalRequest).count() == 1


def test_control_tower_only_records_low_risk(client, db, monkeypatch):
    _hold_lot_at_step(client, monkeypatch, T0)
    checked_at = T0 + timedelta(seconds=production_agent.HOLD_RISK_TIERS[-1][0])

    written = ct.process(db, production_agent.propose_from_step_hold_wait(db, checked_at), checked_at)

    assert [w.disposition for w in written] == [ct.AUTO_RECORD]
    assert db.query(ApprovalRequest).count() == 0
