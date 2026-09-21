import time
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import Equipment, EquipmentStatus, Lot, LotStatus
from app.simulation import SimulationConfig, SimulationEngine


def _freeze_main_time(monkeypatch, when):
    """Make app.main's datetime.utcnow() return a fixed instant.

    The engine's own scheduling math is driven by the `now` explicitly
    passed into _tick_once, but the route functions it calls (advance_lot,
    inspect_lot, ...) stamp timestamps with app.main's own datetime.utcnow(),
    so both must agree for a fully deterministic test.
    """

    class _Frozen(datetime):
        @classmethod
        def utcnow(cls):
            return when

    monkeypatch.setattr("app.main.datetime", _Frozen)


def _no_fault_config(**overrides) -> SimulationConfig:
    base = SimulationConfig(equipment_down_probability_per_tick=0.0)
    return SimulationConfig(**{**base.__dict__, **overrides})


def test_status_before_start_is_idle():
    engine = SimulationEngine()
    status = engine.status()
    assert status["running"] is False
    assert status["ticks"] == 0
    assert status["recent_events"] == []


def test_tick_spawns_a_lot_once_arrival_time_elapses(client, monkeypatch):
    engine = SimulationEngine()
    engine._config = _no_fault_config()
    t0 = datetime(2026, 1, 1, 0, 0, 0)
    _freeze_main_time(monkeypatch, t0)
    engine._next_lot_arrival_at = t0

    engine._tick_once(now=t0)

    db = SessionLocal()
    try:
        assert db.query(Lot).count() == 1
    finally:
        db.close()


def test_tick_does_not_spawn_before_arrival_time(client, monkeypatch):
    engine = SimulationEngine()
    engine._config = _no_fault_config()
    t0 = datetime(2026, 1, 1, 0, 0, 0)
    _freeze_main_time(monkeypatch, t0)
    engine._next_lot_arrival_at = t0 + timedelta(seconds=30)

    engine._tick_once(now=t0)

    db = SessionLocal()
    try:
        assert db.query(Lot).count() == 0
    finally:
        db.close()


def test_lot_walks_all_process_steps_to_quality_hold(client, monkeypatch):
    engine = SimulationEngine()
    engine._config = _no_fault_config(step_dwell_min_seconds=5, step_dwell_max_seconds=5)
    t0 = datetime(2026, 1, 1, 0, 0, 0)
    _freeze_main_time(monkeypatch, t0)
    engine._next_lot_arrival_at = t0
    engine._tick_once(now=t0)

    db = SessionLocal()
    try:
        lot_id = db.query(Lot).one().id
    finally:
        db.close()

    t = t0
    for _ in range(len(["ETCH", "CVD", "CMP", "INSPECT"])):
        t = t + timedelta(seconds=6)
        _freeze_main_time(monkeypatch, t)
        engine._next_lot_arrival_at = t + timedelta(days=1)  # stop spawning more lots
        engine._tick_once(now=t)

    db = SessionLocal()
    try:
        lot = db.get(Lot, lot_id)
        assert lot.status == LotStatus.QUALITY_HOLD
        assert lot.step_index == 4
    finally:
        db.close()


def test_held_lot_is_released_once_equipment_recovers(client, monkeypatch):
    engine = SimulationEngine()
    engine._config = _no_fault_config(step_dwell_min_seconds=5, step_dwell_max_seconds=5)
    t0 = datetime(2026, 1, 1, 0, 0, 0)
    _freeze_main_time(monkeypatch, t0)

    db = SessionLocal()
    try:
        for eq in db.query(Equipment).filter(Equipment.process_step == "ETCH").all():
            eq.status = EquipmentStatus.DOWN
        db.commit()
    finally:
        db.close()

    engine._next_lot_arrival_at = t0
    engine._tick_once(now=t0)  # spawns lot #1

    db = SessionLocal()
    try:
        lot_id = db.query(Lot).one().id
    finally:
        db.close()

    t1 = t0 + timedelta(seconds=6)
    _freeze_main_time(monkeypatch, t1)
    engine._next_lot_arrival_at = t1 + timedelta(days=1)
    engine._tick_once(now=t1)  # advance is due but all ETCH tools are DOWN -> HOLD

    db = SessionLocal()
    try:
        assert db.get(Lot, lot_id).status == LotStatus.HOLD
    finally:
        db.close()

    db = SessionLocal()
    try:
        for eq in db.query(Equipment).filter(Equipment.process_step == "ETCH").all():
            eq.status = EquipmentStatus.IDLE
        db.commit()
    finally:
        db.close()

    t2 = t1 + timedelta(seconds=6)
    _freeze_main_time(monkeypatch, t2)
    engine._tick_once(now=t2)

    db = SessionLocal()
    try:
        lot = db.get(Lot, lot_id)
        assert lot.status == LotStatus.PROCESSING
        assert lot.step_index == 1
    finally:
        db.close()


def test_equipment_trips_down_and_recovers_on_schedule(client, monkeypatch):
    engine = SimulationEngine()
    engine._config = SimulationConfig(
        equipment_down_probability_per_tick=1.0,
        equipment_down_min_seconds=5,
        equipment_down_max_seconds=5,
    )
    t0 = datetime(2026, 1, 1, 0, 0, 0)
    _freeze_main_time(monkeypatch, t0)
    engine._next_lot_arrival_at = t0 + timedelta(days=1)  # no lot arrivals in this test

    engine._tick_once(now=t0)

    db = SessionLocal()
    try:
        total_equipment = db.query(Equipment).count()
        assert db.query(Equipment).filter(Equipment.status == EquipmentStatus.DOWN).count() == (
            total_equipment
        )
    finally:
        db.close()

    t1 = t0 + timedelta(seconds=6)
    _freeze_main_time(monkeypatch, t1)
    engine._config = SimulationConfig(
        equipment_down_probability_per_tick=0.0,
        equipment_down_min_seconds=5,
        equipment_down_max_seconds=5,
    )
    engine._tick_once(now=t1)

    db = SessionLocal()
    try:
        assert db.query(Equipment).filter(Equipment.status == EquipmentStatus.DOWN).count() == 0
    finally:
        db.close()


def test_http_start_and_stop_actually_control_the_background_task(client):
    resp = client.post("/simulation/start")
    assert resp.status_code == 200
    assert resp.json()["running"] is True

    time.sleep(1.5)
    status = client.get("/simulation/status").json()
    assert status["running"] is True
    assert status["ticks"] >= 1

    resp = client.post("/simulation/stop")
    assert resp.status_code == 200
    assert resp.json()["running"] is False

    # Give the background loop time to actually exit before the next test's
    # fixture drops and recreates the schema out from under it.
    time.sleep(1.5)
