from datetime import datetime, timedelta

from app.database import SessionLocal
from app.main import _downtime_by_reason, _equipment_reliability
from app.models import Equipment, EquipmentDowntimeEvent, EquipmentStatus


def _freeze_time(monkeypatch, when):
    """Make app.main's datetime.utcnow() return a fixed instant."""

    class _Frozen(datetime):
        @classmethod
        def utcnow(cls):
            return when

    monkeypatch.setattr("app.main.datetime", _Frozen)


def _first_equipment(client, process_step="ETCH"):
    equipment = client.get("/equipment").json()
    return next(eq for eq in equipment if eq["process_step"] == process_step)


def test_status_update_to_down_opens_a_downtime_event(client, monkeypatch):
    eq = _first_equipment(client)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    _freeze_time(monkeypatch, t0)

    resp = client.patch(
        f"/equipment/{eq['id']}/status", json={"status": "DOWN", "reason": "RANDOM_FAULT"}
    )
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        events = (
            db.query(EquipmentDowntimeEvent)
            .filter(EquipmentDowntimeEvent.equipment_id == eq["id"])
            .all()
        )
    finally:
        db.close()
    assert len(events) == 1
    assert events[0].reason == "RANDOM_FAULT"
    assert events[0].started_at == t0
    assert events[0].ended_at is None
    assert events[0].duration_seconds is None


def test_status_update_omitting_reason_defaults_to_manual(client):
    eq = _first_equipment(client)
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})

    db = SessionLocal()
    try:
        event = (
            db.query(EquipmentDowntimeEvent)
            .filter(EquipmentDowntimeEvent.equipment_id == eq["id"])
            .one()
        )
    finally:
        db.close()
    assert event.reason == "MANUAL"


def test_recovery_closes_the_open_downtime_event(client, monkeypatch):
    eq = _first_equipment(client)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    _freeze_time(monkeypatch, t0)
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})

    _freeze_time(monkeypatch, t0 + timedelta(seconds=45))
    resp = client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        event = (
            db.query(EquipmentDowntimeEvent)
            .filter(EquipmentDowntimeEvent.equipment_id == eq["id"])
            .one()
        )
    finally:
        db.close()
    assert event.ended_at == t0 + timedelta(seconds=45)
    assert event.duration_seconds == 45.0


def test_redundant_down_call_does_not_open_a_second_event(client):
    """PATCH to DOWN while already DOWN must not open a second open row —
    otherwise leaving_down would have two open events to choose from and the
    later close would silently pick the wrong one."""
    eq = _first_equipment(client)
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})

    db = SessionLocal()
    try:
        events = (
            db.query(EquipmentDowntimeEvent)
            .filter(EquipmentDowntimeEvent.equipment_id == eq["id"])
            .all()
        )
    finally:
        db.close()
    assert len(events) == 1


def test_equipment_downtime_endpoint_orders_most_recent_first(client, monkeypatch):
    eq = _first_equipment(client)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    _freeze_time(monkeypatch, t0)
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})
    _freeze_time(monkeypatch, t0 + timedelta(seconds=10))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})

    _freeze_time(monkeypatch, t0 + timedelta(seconds=100))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})
    _freeze_time(monkeypatch, t0 + timedelta(seconds=130))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})

    resp = client.get(f"/equipment/{eq['id']}/downtime")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["duration_seconds"] == 30.0
    assert body[1]["duration_seconds"] == 10.0


def test_equipment_downtime_404s_for_unknown_equipment(client):
    resp = client.get("/equipment/999999/downtime")
    assert resp.status_code == 404


def test_reliability_is_none_before_any_failure(client):
    eq = _first_equipment(client)
    db = SessionLocal()
    try:
        equipment = db.get(Equipment, eq["id"])
        result = _equipment_reliability(db, equipment, datetime.utcnow())
    finally:
        db.close()
    assert result == {"mtbf_seconds": None, "mttr_seconds": None}


def test_mttr_is_mean_of_closed_downtime_durations(client, monkeypatch):
    eq = _first_equipment(client)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    _freeze_time(monkeypatch, t0)
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})
    _freeze_time(monkeypatch, t0 + timedelta(seconds=20))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})

    _freeze_time(monkeypatch, t0 + timedelta(seconds=200))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})
    _freeze_time(monkeypatch, t0 + timedelta(seconds=240))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})

    db = SessionLocal()
    try:
        equipment = db.get(Equipment, eq["id"])
        result = _equipment_reliability(db, equipment, t0 + timedelta(seconds=240))
    finally:
        db.close()
    # durations 20s and 40s -> mean 30s
    assert result["mttr_seconds"] == 30.0


def test_mtbf_uses_uptime_over_total_life_divided_by_failure_count(client, monkeypatch):
    eq = _first_equipment(client)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    db = SessionLocal()
    try:
        equipment = db.get(Equipment, eq["id"])
        equipment.created_at = t0
        equipment.last_status_change = t0
        db.commit()
    finally:
        db.close()

    _freeze_time(monkeypatch, t0 + timedelta(seconds=100))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})
    _freeze_time(monkeypatch, t0 + timedelta(seconds=120))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})

    _freeze_time(monkeypatch, t0 + timedelta(seconds=300))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})
    _freeze_time(monkeypatch, t0 + timedelta(seconds=320))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})

    db = SessionLocal()
    try:
        equipment = db.get(Equipment, eq["id"])
        now = t0 + timedelta(seconds=400)
        result = _equipment_reliability(db, equipment, now)
    finally:
        db.close()
    # total_elapsed=400, down=20+20=40, uptime=360, 2 failures -> 180s
    assert result["mtbf_seconds"] == 180.0


def test_downtime_by_reason_is_empty_before_any_failure(client):
    eq = _first_equipment(client)
    db = SessionLocal()
    try:
        equipment = db.get(Equipment, eq["id"])
        result = _downtime_by_reason(db, equipment)
    finally:
        db.close()
    assert result == {}


def test_downtime_by_reason_splits_totals_per_reason(client, monkeypatch):
    """Same tool failing under two different reasons must not blend into one
    MTTR — each reason keeps its own count/total/mean, which is the whole
    point of separating Locust's fault injection from the simulation's own
    random faults (see app.main._downtime_by_reason)."""
    eq = _first_equipment(client)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    _freeze_time(monkeypatch, t0)
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN", "reason": "RANDOM_FAULT"})
    _freeze_time(monkeypatch, t0 + timedelta(seconds=10))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})

    _freeze_time(monkeypatch, t0 + timedelta(seconds=100))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN", "reason": "RANDOM_FAULT"})
    _freeze_time(monkeypatch, t0 + timedelta(seconds=130))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})

    _freeze_time(monkeypatch, t0 + timedelta(seconds=200))
    client.patch(
        f"/equipment/{eq['id']}/status", json={"status": "DOWN", "reason": "STEP_FAULT_INJECTION"}
    )
    # left open on purpose to check `count` still includes an open stretch
    # without it contributing to closed_count/total_seconds/mean_seconds.

    db = SessionLocal()
    try:
        equipment = db.get(Equipment, eq["id"])
        result = _downtime_by_reason(db, equipment)
    finally:
        db.close()

    assert result["RANDOM_FAULT"] == {
        "count": 2,
        "closed_count": 2,
        "total_seconds": 40.0,
        "mean_seconds": 20.0,
    }
    assert result["STEP_FAULT_INJECTION"] == {
        "count": 1,
        "closed_count": 0,
        "total_seconds": 0.0,
        "mean_seconds": None,
    }


def test_equipment_list_exposes_downtime_by_reason(client, monkeypatch):
    eq = _first_equipment(client)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    _freeze_time(monkeypatch, t0)
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN", "reason": "MANUAL"})
    _freeze_time(monkeypatch, t0 + timedelta(seconds=5))
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})

    body = next(e for e in client.get("/equipment").json() if e["id"] == eq["id"])
    assert body["downtime_by_reason"]["MANUAL"] == {
        "count": 1,
        "closed_count": 1,
        "total_seconds": 5.0,
        "mean_seconds": 5.0,
    }


def test_equipment_endpoint_exposes_mtbf_and_mttr_fields(client):
    equipment = client.get("/equipment").json()
    assert equipment
    for eq in equipment:
        assert "mtbf_seconds" in eq
        assert "mttr_seconds" in eq
        assert eq["mtbf_seconds"] is None
        assert eq["mttr_seconds"] is None
