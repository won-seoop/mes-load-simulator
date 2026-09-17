from app.models import PROCESS_ROUTE


def _create_lot(client, product="WAFER-A"):
    return client.post("/lots", json={"product": product}).json()


def test_advance_lot_walks_full_route_to_done(client):
    lot = _create_lot(client)

    for expected_step in range(len(PROCESS_ROUTE)):
        resp = client.post(f"/lots/{lot['id']}/advance")
        assert resp.status_code == 200
        lot = resp.json()
        assert lot["step_index"] == expected_step + 1

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


def test_cannot_advance_a_done_lot(client):
    lot = _create_lot(client)
    for _ in range(len(PROCESS_ROUTE)):
        lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["status"] == "DONE"

    resp = client.post(f"/lots/{lot['id']}/advance")
    assert resp.status_code == 400


def test_advance_nonexistent_lot(client):
    resp = client.post("/lots/9999/advance")
    assert resp.status_code == 404


def test_scrap_flag_and_metrics_reflect_forced_scrap(client, monkeypatch):
    monkeypatch.setattr("app.main.random.random", lambda: 0.0)  # force scrap path

    lot = _create_lot(client)
    lot = client.post(f"/lots/{lot['id']}/advance").json()
    assert lot["is_scrap"] == 1

    metrics = client.get("/metrics").json()
    assert metrics["scrap_count"] >= 1
    assert metrics["yield_rate"] < 1.0


def test_completed_lot_counts_toward_metrics(client):
    lot = _create_lot(client)
    for _ in range(len(PROCESS_ROUTE)):
        lot = client.post(f"/lots/{lot['id']}/advance").json()

    metrics = client.get("/metrics").json()
    assert metrics["completed_today"] >= 1
    assert metrics["avg_cycle_time_seconds"] is not None
    assert metrics["avg_cycle_time_seconds"] >= 0
