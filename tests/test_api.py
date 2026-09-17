from app.models import PROCESS_ROUTE

EXPECTED_EQUIPMENT_COUNT = len(PROCESS_ROUTE) * 3


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_equipment_seeded_on_startup(client):
    resp = client.get("/equipment")
    assert resp.status_code == 200
    equipment = resp.json()
    assert len(equipment) == EXPECTED_EQUIPMENT_COUNT
    steps = {eq["process_step"] for eq in equipment}
    assert steps == set(PROCESS_ROUTE)
    assert all(eq["status"] == "IDLE" for eq in equipment)


def test_set_equipment_status(client):
    eq_id = client.get("/equipment").json()[0]["id"]
    resp = client.patch(f"/equipment/{eq_id}/status", json={"status": "DOWN"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "DOWN"


def test_set_equipment_status_not_found(client):
    resp = client.patch("/equipment/9999/status", json={"status": "DOWN"})
    assert resp.status_code == 404


def test_create_lot(client):
    resp = client.post("/lots", json={"product": "WAFER-A", "quantity": 25})
    assert resp.status_code == 200
    lot = resp.json()
    assert lot["product"] == "WAFER-A"
    assert lot["quantity"] == 25
    assert lot["status"] == "WAITING"
    assert lot["step_index"] == 0
    assert lot["completed_at"] is None


def test_create_lot_default_quantity(client):
    resp = client.post("/lots", json={"product": "PANEL-X"})
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 25


def test_list_lots_filtered_by_status(client):
    client.post("/lots", json={"product": "WAFER-A"})
    client.post("/lots", json={"product": "WAFER-B"})

    resp = client.get("/lots", params={"status": "WAITING"})
    assert resp.status_code == 200
    lots = resp.json()
    assert len(lots) == 2
    assert all(lot["status"] == "WAITING" for lot in lots)


def test_get_lot(client):
    created = client.post("/lots", json={"product": "WAFER-A"}).json()
    resp = client.get(f"/lots/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_lot_not_found(client):
    resp = client.get("/lots/9999")
    assert resp.status_code == 404


def test_metrics_shape(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    for field in (
        "wip_count",
        "completed_today",
        "scrap_count",
        "yield_rate",
        "avg_cycle_time_seconds",
        "equipment_utilization",
        "throughput_per_hour",
    ):
        assert field in body
    assert body["yield_rate"] == 1.0  # no lots yet -> perfect yield
    assert body["avg_cycle_time_seconds"] is None  # nothing completed yet
