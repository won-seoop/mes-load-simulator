import time
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import PROCESS_ROUTE, AnomalyLog, Equipment, EquipmentStatus, Lot, LotStatus
from app.simulation import SimulationConfig, SimulationEngine


def _seed_inspect03_anomaly(client):
    """Reproduces the same equipment-correlated defect pattern as
    test_quality.py's anomaly test: INSPECT-03 fails 10/10 while its two
    peers pass 10/10 each, which /quality/anomalies flags CRITICAL."""
    inspect_equipment = [
        item for item in client.get("/equipment").json() if item["process_step"] == "INSPECT"
    ]
    for target in inspect_equipment:
        for equipment in inspect_equipment:
            status = "IDLE" if equipment["id"] == target["id"] else "DOWN"
            client.patch(f"/equipment/{equipment['id']}/status", json={"status": status})
        for _ in range(10):
            lot = client.post("/lots", json={"product": "WAFER-A", "quantity": 25}).json()
            for _ in PROCESS_ROUTE:
                lot = client.post(f"/lots/{lot['id']}/advance").json()
            if target["name"] == "INSPECT-03":
                client.post(
                    f"/lots/{lot['id']}/inspections",
                    json={"result": "FAIL", "defect_code": "SENSOR_DRIFT"},
                )
                client.post(f"/lots/{lot['id']}/quality-disposition", json={"disposition": "SCRAP"})
            else:
                client.post(f"/lots/{lot['id']}/inspections", json={"result": "PASS"})


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


def test_broken_lot_does_not_block_other_due_lots_in_same_tick(client, monkeypatch):
    """Regression test for a production incident: a lot HELD at the last
    process step used to raise an uncaught ValueError (HOLD -> QUALITY_HOLD
    was missing from the state machine). Because _advance_due_lots only
    caught HTTPException, that error propagated out of the whole tick and
    left every other due lot in that tick — and every tick after, since the
    failing lot was never rescheduled — permanently stuck. This reproduces
    that shape with a synthetic failure (independent of which bug caused it)
    and asserts the *isolation* fix: one lot's exception must not block
    lots scheduled earlier in the same _next_action dict, and the broken lot
    must be rescheduled with backoff rather than spinning or vanishing.
    """
    from app import main as mes_main

    db = SessionLocal()
    try:
        bad_lot = mes_main.create_lot(mes_main.LotCreate(product="WAFER-A", quantity=10), db=db)
        good_lot = mes_main.create_lot(mes_main.LotCreate(product="WAFER-B", quantity=10), db=db)
        bad_id, good_id = bad_lot.id, good_lot.id
    finally:
        db.close()

    real_advance_lot = mes_main.advance_lot

    def flaky_advance_lot(lot_id, db):
        if lot_id == bad_id:
            raise ValueError("synthetic invalid transition for regression test")
        return real_advance_lot(lot_id, db=db)

    monkeypatch.setattr(mes_main, "advance_lot", flaky_advance_lot)

    engine = SimulationEngine()
    t0 = datetime(2026, 1, 1, 0, 0, 0)
    _freeze_main_time(monkeypatch, t0)
    engine._next_lot_arrival_at = t0 + timedelta(days=1)  # no new spawns this tick
    # bad_id is due *before* good_id in iteration order — under the old code
    # bad_id's exception would abort the loop before good_id was ever tried.
    engine._next_action = {bad_id: t0, good_id: t0}

    engine._tick_once(now=t0)

    db = SessionLocal()
    try:
        good = db.get(Lot, good_id)
        assert good.status == LotStatus.PROCESSING
        assert good.step_index == 1
        bad = db.get(Lot, bad_id)
        assert bad.status == LotStatus.WAITING  # untouched by the failed call
        assert bad.step_index == 0
    finally:
        db.close()

    assert bad_id in engine._next_action
    assert engine._next_action[bad_id] > t0 + timedelta(seconds=5)


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


def test_anomaly_check_persists_a_new_finding_and_logs_the_event(client, monkeypatch):
    _seed_inspect03_anomaly(client)

    engine = SimulationEngine()
    from app import main as mes_main

    t0 = datetime(2026, 1, 1, 0, 0, 0)
    _freeze_main_time(monkeypatch, t0)
    engine._next_anomaly_check_at = t0

    db = SessionLocal()
    try:
        engine._maybe_check_anomalies(db, t0, mes_main)
    finally:
        db.close()

    db = SessionLocal()
    try:
        rows = db.query(AnomalyLog).all()
        assert len(rows) == 1
        assert rows[0].equipment_name == "INSPECT-03"
        assert rows[0].severity == "CRITICAL"
    finally:
        db.close()
    assert any("품질 이상 감지" in e for e in engine._events)


def test_anomaly_check_suppresses_duplicate_rows_within_the_window(client, monkeypatch):
    _seed_inspect03_anomaly(client)

    engine = SimulationEngine()
    from app import main as mes_main

    t0 = datetime(2026, 1, 1, 0, 0, 0)
    _freeze_main_time(monkeypatch, t0)
    engine._next_anomaly_check_at = t0
    db = SessionLocal()
    try:
        engine._maybe_check_anomalies(db, t0, mes_main)
    finally:
        db.close()

    # Still well inside the suppression window: same equipment must not log again.
    t1 = t0 + timedelta(seconds=60)
    _freeze_main_time(monkeypatch, t1)
    engine._next_anomaly_check_at = t1
    db = SessionLocal()
    try:
        engine._maybe_check_anomalies(db, t1, mes_main)
        assert db.query(AnomalyLog).count() == 1
    finally:
        db.close()

    # Past the suppression window: the still-standing anomaly logs again.
    t2 = t0 + timedelta(seconds=400)
    _freeze_main_time(monkeypatch, t2)
    engine._next_anomaly_check_at = t2
    db = SessionLocal()
    try:
        engine._maybe_check_anomalies(db, t2, mes_main)
        assert db.query(AnomalyLog).count() == 2
    finally:
        db.close()
