from datetime import datetime

from app.models import PROCESS_ROUTE


def _create_lot(client, product="WAFER-A"):
    return client.post("/lots", json={"product": product}).json()


def _pass_inspection(client, lot_id):
    response = client.post(f"/lots/{lot_id}/inspections", json={"result": "PASS"})
    assert response.status_code == 200
    return client.get(f"/lots/{lot_id}").json()


def _freeze_time(monkeypatch, when):
    """Make app.main's datetime.utcnow() return a fixed instant."""

    class _Frozen(datetime):
        @classmethod
        def utcnow(cls):
            return when

    monkeypatch.setattr("app.main.datetime", _Frozen)


def test_advance_lot_walks_full_route_to_done(client):
    lot = _create_lot(client)

    for expected_step in range(len(PROCESS_ROUTE)):
        resp = client.post(f"/lots/{lot['id']}/advance")
        assert resp.status_code == 200
        lot = resp.json()
        assert lot["step_index"] == expected_step + 1

    assert lot["status"] == "QUALITY_HOLD"
    assert lot["completed_at"] is None

    lot = _pass_inspection(client, lot["id"])
    assert lot["status"] == "DONE"
    assert lot["completed_at"] is not None


def test_advance_lot_sets_processing_status_before_last_step(client):
    lot = _create_lot(client)
    resp = client.post(f"/lots/{lot['id']}/advance")
    assert resp.status_code == 200
    lot = resp.json()
    assert lot["status"] == "PROCESSING"
    assert lot["step_index"] == 1


def test_advance_lot_uses_equipment_of_current_step(client):
    lot = _create_lot(client)
    client.post(f"/lots/{lot['id']}/advance")

    equipment = client.get("/equipment").json()
    etch_equipment = [eq for eq in equipment if eq["process_step"] == PROCESS_ROUTE[0]]
    assert any(eq["status"] == "RUN" for eq in etch_equipment)


def test_advance_lot_holds_when_no_equipment_available(client):
    lot = _create_lot(client)

    equipment = client.get("/equipment").json()
    first_step = PROCESS_ROUTE[0]
    for eq in equipment:
        if eq["process_step"] == first_step:
            resp = client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})
            assert resp.status_code == 200

    resp = client.post(f"/lots/{lot['id']}/advance")
    assert resp.status_code == 200
    lot = resp.json()
    assert lot["status"] == "HOLD"
    assert lot["step_index"] == 0  # never advanced


def test_advance_lot_load_balances_across_equipment_of_same_step(client):
    """Regression test for the dispatch bug where advance_lot always picked
    the same equipment (deterministic query order) leaving the other two
    tools per step idle at 0% utilization. Now it should spread lots across
    all three tools of a step by picking whichever has the least run time."""
    first_step = PROCESS_ROUTE[0]

    lots = [_create_lot(client, product=f"WAFER-{i}") for i in range(3)]
    for lot in lots:
        client.post(f"/lots/{lot['id']}/advance")

    equipment = client.get("/equipment").json()
    step_equipment = [eq for eq in equipment if eq["process_step"] == first_step]
    assert len(step_equipment) == 3
    assert sum(1 for eq in step_equipment if eq["status"] == "RUN") == 3
    assert sorted(eq["dispatch_count"] for eq in step_equipment) == [1, 1, 1]

    more_lots = [_create_lot(client, product=f"PANEL-{i}") for i in range(27)]
    for lot in more_lots:
        assert client.post(f"/lots/{lot['id']}/advance").status_code == 200

    equipment = client.get("/equipment").json()
    step_equipment = [eq for eq in equipment if eq["process_step"] == first_step]
    assert sorted(eq["dispatch_count"] for eq in step_equipment) == [10, 10, 10]


def test_advance_lot_resumes_once_equipment_is_freed(client):
    lot = _create_lot(client)
    equipment = client.get("/equipment").json()
    first_step_ids = [eq["id"] for eq in equipment if eq["process_step"] == PROCESS_ROUTE[0]]

    for eq_id in first_step_ids:
        client.patch(f"/equipment/{eq_id}/status", json={"status": "DOWN"})

    lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["status"] == "HOLD"

    client.patch(f"/equipment/{first_step_ids[0]}/status", json={"status": "IDLE"})
    lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["status"] == "PROCESSING"
    assert lot["step_index"] == 1


def test_advance_lot_resumes_to_quality_hold_when_held_at_last_step(client):
    """Regression test: a lot HELD at the *last* step (all INSPECT tools
    DOWN) completes that step straight into QUALITY_HOLD once equipment is
    freed, instead of the state machine rejecting HOLD -> QUALITY_HOLD as an
    invalid transition (it previously only allowed HOLD -> PROCESSING)."""
    lot = _create_lot(client)
    for _ in range(len(PROCESS_ROUTE) - 1):
        lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["step_index"] == len(PROCESS_ROUTE) - 1

    last_step = PROCESS_ROUTE[-1]
    equipment = client.get("/equipment").json()
    last_step_ids = [eq["id"] for eq in equipment if eq["process_step"] == last_step]
    for eq_id in last_step_ids:
        client.patch(f"/equipment/{eq_id}/status", json={"status": "DOWN"})

    lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["status"] == "HOLD"
    assert lot["step_index"] == len(PROCESS_ROUTE) - 1

    client.patch(f"/equipment/{last_step_ids[0]}/status", json={"status": "IDLE"})
    resp = client.post(f"/lots/{lot['id']}/advance")
    assert resp.status_code == 200
    lot = resp.json()
    assert lot["status"] == "QUALITY_HOLD"
    assert lot["step_index"] == len(PROCESS_ROUTE)


def test_cannot_advance_a_done_lot(client):
    lot = _create_lot(client)
    for _ in range(len(PROCESS_ROUTE)):
        lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["status"] == "QUALITY_HOLD"
    lot = _pass_inspection(client, lot["id"])
    assert lot["status"] == "DONE"

    resp = client.post(f"/lots/{lot['id']}/advance")
    assert resp.status_code == 409


def test_advance_nonexistent_lot(client):
    resp = client.post("/lots/9999/advance")
    assert resp.status_code == 404


def test_scrap_flag_and_metrics_reflect_quality_disposition(client):
    lot = _create_lot(client)
    for _ in PROCESS_ROUTE:
        lot = client.post(f"/lots/{lot['id']}/advance").json()
    failed = client.post(
        f"/lots/{lot['id']}/inspections",
        json={"result": "FAIL", "defect_code": "CD_OUT_OF_SPEC"},
    )
    assert failed.status_code == 200
    lot = client.post(
        f"/lots/{lot['id']}/quality-disposition",
        json={"disposition": "SCRAP"},
    ).json()
    assert lot["is_scrap"] == 1
    assert lot["status"] == "SCRAPPED"

    metrics = client.get("/metrics").json()
    assert metrics["scrap_count"] >= 1
    assert metrics["yield_rate"] < 1.0


def test_completed_lot_counts_toward_metrics(client):
    lot = _create_lot(client)
    for _ in range(len(PROCESS_ROUTE)):
        lot = client.post(f"/lots/{lot['id']}/advance").json()
    _pass_inspection(client, lot["id"])

    metrics = client.get("/metrics").json()
    assert metrics["completed_today"] >= 1
    assert metrics["avg_cycle_time_seconds"] is not None
    assert metrics["avg_cycle_time_seconds"] >= 0


def test_completed_today_resets_at_kst_midnight_not_utc_midnight(client, monkeypatch):
    """Regression test: completed_today used to reset at UTC midnight
    (KST 09:00), so a lot finished at 23:00 KST yesterday was still counted
    as "today" for another 9 hours. It must reset at KST midnight instead."""
    yesterday_kst_23h = datetime(2026, 9, 17, 14, 0, 0)  # 2026-09-17 23:00 KST
    today_kst_00h30 = datetime(2026, 9, 17, 15, 30, 0)  # 2026-09-18 00:30 KST

    _freeze_time(monkeypatch, yesterday_kst_23h)
    old_lot = _create_lot(client, product="OLD-KST-DAY")
    for _ in range(len(PROCESS_ROUTE)):
        old_lot = client.post(f"/lots/{old_lot['id']}/advance").json()
    old_lot = _pass_inspection(client, old_lot["id"])
    assert old_lot["status"] == "DONE"

    _freeze_time(monkeypatch, today_kst_00h30)
    new_lot = _create_lot(client, product="NEW-KST-DAY")
    for _ in range(len(PROCESS_ROUTE)):
        new_lot = client.post(f"/lots/{new_lot['id']}/advance").json()
    new_lot = _pass_inspection(client, new_lot["id"])
    assert new_lot["status"] == "DONE"

    metrics = client.get("/metrics").json()
    assert metrics["completed_today"] == 1


def _hold_first_step_lot(client):
    """Create a lot and drive it into HOLD by taking down all first-step tools."""
    lot = _create_lot(client)
    equipment = client.get("/equipment").json()
    first_step_ids = [eq["id"] for eq in equipment if eq["process_step"] == PROCESS_ROUTE[0]]
    for eq_id in first_step_ids:
        client.patch(f"/equipment/{eq_id}/status", json={"status": "DOWN"})
    lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["status"] == "HOLD"
    return lot, first_step_ids


def test_metrics_report_no_hold_wait_when_nothing_is_held(client):
    """Baseline: with no HOLD lots the hold-wait fields must stay empty/None,
    never a fabricated zero duration for something that never happened."""
    metrics = client.get("/metrics").json()
    assert metrics["lots_on_hold_count"] == 0
    assert metrics["longest_current_hold_seconds"] is None
    assert metrics["avg_resolved_hold_seconds"] is None


def test_metrics_expose_current_hold_wait_duration(client, monkeypatch):
    """Regression test: the Lot table only says a lot is HOLD, not since when.
    /metrics must recover "how long" from the LOT_HELD event journal so a lot
    stuck for 10 minutes is distinguishable from one held a second ago."""
    held_at = datetime(2026, 9, 21, 1, 0, 0)
    checked_at = datetime(2026, 9, 21, 1, 5, 30)  # 330s later

    _freeze_time(monkeypatch, held_at)
    _hold_first_step_lot(client)

    _freeze_time(monkeypatch, checked_at)
    metrics = client.get("/metrics").json()
    assert metrics["lots_on_hold_count"] == 1
    assert metrics["longest_current_hold_seconds"] == 330.0
    assert metrics["avg_resolved_hold_seconds"] is None  # not yet resolved


def test_metrics_expose_avg_resolved_hold_duration_after_recovery(client, monkeypatch):
    """Once equipment frees up and the lot is released from HOLD, that wait
    becomes a resolved sample instead of vanishing from the metric."""
    held_at = datetime(2026, 9, 21, 1, 0, 0)
    released_at = datetime(2026, 9, 21, 1, 2, 0)  # 120s hold

    _freeze_time(monkeypatch, held_at)
    lot, first_step_ids = _hold_first_step_lot(client)

    _freeze_time(monkeypatch, released_at)
    client.patch(f"/equipment/{first_step_ids[0]}/status", json={"status": "IDLE"})
    lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["status"] == "PROCESSING"

    metrics = client.get("/metrics").json()
    assert metrics["lots_on_hold_count"] == 0
    assert metrics["longest_current_hold_seconds"] is None
    assert metrics["avg_resolved_hold_seconds"] == 120.0
