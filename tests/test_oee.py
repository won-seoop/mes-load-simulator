from datetime import datetime, timedelta

from app.database import SessionLocal
from app.main import OEE_IDEAL_CYCLE_SECONDS, _equipment_oee
from app.models import Equipment, EquipmentStatus


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


def test_equipment_availability_is_full_when_never_down(client):
    db = SessionLocal()
    try:
        eq = db.query(Equipment).first()
        eq.created_at = datetime.utcnow() - timedelta(seconds=1000)
        eq.down_seconds = 0.0
        eq.status = EquipmentStatus.IDLE
        eq.last_status_change = datetime.utcnow()
        db.commit()
        result = _equipment_oee(eq, datetime.utcnow())
    finally:
        db.close()
    assert result["availability"] == 1.0


def test_equipment_availability_reflects_flushed_down_time(client):
    db = SessionLocal()
    try:
        eq = db.query(Equipment).first()
        now = datetime.utcnow()
        eq.created_at = now - timedelta(seconds=1000)
        eq.down_seconds = 250.0  # already flushed, equipment is IDLE now
        eq.status = EquipmentStatus.IDLE
        eq.last_status_change = now
        db.commit()
        result = _equipment_oee(eq, now)
    finally:
        db.close()
    assert result["availability"] == 0.75


def test_equipment_availability_counts_ongoing_down_stretch(client):
    """down_seconds only gets flushed on the *next* status change, so a tool
    that has been sitting DOWN since t0 must still count that time at t0+dt
    even though nothing has flushed it into down_seconds yet."""
    db = SessionLocal()
    try:
        eq = db.query(Equipment).first()
        started = datetime.utcnow() - timedelta(seconds=1000)
        eq.created_at = started
        eq.down_seconds = 0.0
        eq.status = EquipmentStatus.DOWN
        eq.last_status_change = started + timedelta(seconds=800)  # DOWN for the last 200s
        db.commit()
        result = _equipment_oee(eq, started + timedelta(seconds=1000))
    finally:
        db.close()
    assert result["availability"] == 0.8


def test_equipment_performance_is_none_when_never_dispatched(client):
    db = SessionLocal()
    try:
        eq = db.query(Equipment).first()
        eq.run_seconds = 0.0
        eq.dispatch_count = 0
        eq.status = EquipmentStatus.IDLE
        db.commit()
        result = _equipment_oee(eq, datetime.utcnow())
    finally:
        db.close()
    assert result["performance"] is None


def test_equipment_performance_at_ideal_cycle_time_is_one(client):
    db = SessionLocal()
    try:
        eq = db.query(Equipment).first()
        eq.run_seconds = 5 * OEE_IDEAL_CYCLE_SECONDS
        eq.dispatch_count = 5
        eq.status = EquipmentStatus.IDLE
        db.commit()
        result = _equipment_oee(eq, datetime.utcnow())
    finally:
        db.close()
    assert result["performance"] == 1.0


def test_equipment_performance_is_capped_at_one_when_faster_than_ideal(client):
    db = SessionLocal()
    try:
        eq = db.query(Equipment).first()
        eq.run_seconds = 5 * OEE_IDEAL_CYCLE_SECONDS
        eq.dispatch_count = 10  # would be a 2.0 ratio uncapped
        eq.status = EquipmentStatus.IDLE
        db.commit()
        result = _equipment_oee(eq, datetime.utcnow())
    finally:
        db.close()
    assert result["performance"] == 1.0


def test_equipment_performance_below_one_when_slower_than_ideal(client):
    db = SessionLocal()
    try:
        eq = db.query(Equipment).first()
        eq.run_seconds = 100.0
        eq.dispatch_count = 2  # 10 * 2 / 100 = 0.2
        eq.status = EquipmentStatus.IDLE
        db.commit()
        result = _equipment_oee(eq, datetime.utcnow())
    finally:
        db.close()
    assert result["performance"] == 0.2


def test_set_equipment_status_flushes_down_seconds_on_recovery(client, monkeypatch):
    eq = _first_equipment(client)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    _freeze_time(monkeypatch, t0)
    client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})

    _freeze_time(monkeypatch, t0 + timedelta(seconds=40))
    resp = client.patch(f"/equipment/{eq['id']}/status", json={"status": "IDLE"})
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        refreshed = db.get(Equipment, eq["id"])
        assert refreshed.down_seconds == 40.0
    finally:
        db.close()


def test_equipment_endpoint_exposes_availability_and_performance(client):
    equipment = client.get("/equipment").json()
    assert equipment
    for eq in equipment:
        assert "availability" in eq
        assert "performance" in eq
        assert eq["availability"] == 1.0  # fresh, never down
        assert eq["performance"] is None  # fresh, never dispatched


def test_metrics_oee_is_none_before_any_dispatch(client):
    metrics = client.get("/metrics").json()
    assert metrics["oee_performance"] is None
    assert metrics["oee"] is None
    assert metrics["oee_availability"] == 1.0
    assert metrics["oee_quality"] == 1.0


def test_metrics_oee_becomes_available_after_a_dispatch(client):
    lot = client.post("/lots", json={"product": "WAFER-A"}).json()
    client.post(f"/lots/{lot['id']}/advance")

    metrics = client.get("/metrics").json()
    assert metrics["oee_performance"] is not None
    assert metrics["oee"] is not None
    assert 0.0 <= metrics["oee"] <= 1.0
