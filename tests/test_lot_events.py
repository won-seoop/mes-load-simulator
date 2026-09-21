from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import app.main as main_module

from app.models import PROCESS_ROUTE


def _create_lot(client, product="WAFER-A"):
    response = client.post("/lots", json={"product": product, "quantity": 25})
    assert response.status_code == 200
    return response.json()


def _events(client, lot_id):
    response = client.get(f"/lots/{lot_id}/events")
    assert response.status_code == 200
    return response.json()


def test_create_lot_writes_first_trace_event(client):
    lot = _create_lot(client)

    events = _events(client, lot["id"])

    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "LOT_CREATED"
    assert event["sequence_number"] == 1
    assert event["from_status"] is None
    assert event["to_status"] == "WAITING"
    assert event["process_step"] is None
    assert event["equipment_id"] is None


def test_full_route_records_ordered_process_and_completion_events(client):
    lot = _create_lot(client)

    for _ in PROCESS_ROUTE:
        response = client.post(f"/lots/{lot['id']}/advance")
        assert response.status_code == 200
    passed = client.post(f"/lots/{lot['id']}/inspections", json={"result": "PASS"})
    assert passed.status_code == 200

    events = _events(client, lot["id"])

    assert [event["sequence_number"] for event in events] == list(range(1, 7))
    assert [event["event_type"] for event in events] == [
        "LOT_CREATED",
        "PROCESS_COMPLETED",
        "PROCESS_COMPLETED",
        "PROCESS_COMPLETED",
        "PROCESS_COMPLETED",
        "LOT_COMPLETED",
    ]
    process_events = [event for event in events if event["event_type"] == "PROCESS_COMPLETED"]
    assert [event["process_step"] for event in process_events] == PROCESS_ROUTE
    assert all(event["equipment_id"] is not None for event in process_events)
    assert process_events[-1]["to_status"] == "QUALITY_HOLD"
    assert events[-1]["from_status"] == "QUALITY_HOLD"
    assert events[-1]["to_status"] == "DONE"


def test_hold_is_not_duplicated_and_recovery_is_traced(client):
    lot = _create_lot(client)
    first_step = PROCESS_ROUTE[0]
    equipment = client.get("/equipment").json()
    first_step_equipment = [eq for eq in equipment if eq["process_step"] == first_step]

    for eq in first_step_equipment:
        response = client.patch(f"/equipment/{eq['id']}/status", json={"status": "DOWN"})
        assert response.status_code == 200

    first_hold = client.post(f"/lots/{lot['id']}/advance")
    repeated_hold = client.post(f"/lots/{lot['id']}/advance")
    assert first_hold.json()["status"] == "HOLD"
    assert repeated_hold.json()["status"] == "HOLD"

    events_while_held = _events(client, lot["id"])
    assert [event["event_type"] for event in events_while_held] == [
        "LOT_CREATED",
        "LOT_HELD",
    ]

    restored_equipment = first_step_equipment[0]
    client.patch(f"/equipment/{restored_equipment['id']}/status", json={"status": "IDLE"})
    resumed = client.post(f"/lots/{lot['id']}/advance")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "PROCESSING"

    events = _events(client, lot["id"])
    assert [event["event_type"] for event in events] == [
        "LOT_CREATED",
        "LOT_HELD",
        "LOT_RELEASED_FROM_HOLD",
        "PROCESS_COMPLETED",
    ]
    assert [event["sequence_number"] for event in events] == [1, 2, 3, 4]
    assert events[1]["from_status"] == "WAITING"
    assert events[1]["to_status"] == "HOLD"
    assert events[2]["from_status"] == "HOLD"
    assert events[2]["equipment_id"] == restored_equipment["id"]


def test_lot_events_returns_not_found_for_unknown_lot(client):
    response = client.get("/lots/9999/events")
    assert response.status_code == 404


def test_concurrent_advance_allows_only_one_state_transition(client, monkeypatch):
    lot = _create_lot(client)
    barrier = Barrier(2)
    original_compare_and_set = main_module._compare_and_set_lot

    def synchronized_compare_and_set(*args, **kwargs):
        barrier.wait(timeout=5)
        return original_compare_and_set(*args, **kwargs)

    monkeypatch.setattr(
        main_module,
        "_compare_and_set_lot",
        synchronized_compare_and_set,
    )

    def advance():
        return client.post(f"/lots/{lot['id']}/advance")

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: advance(), range(2)))

    assert sorted(response.status_code for response in responses) == [200, 409]

    current_lot = client.get(f"/lots/{lot['id']}").json()
    assert current_lot["step_index"] == 1
    process_events = [
        event
        for event in _events(client, lot["id"])
        if event["event_type"] == "PROCESS_COMPLETED"
    ]
    assert len(process_events) == 1


def test_equipment_events_returns_only_that_equipment_dispatch_history(client):
    lot = _create_lot(client)
    resp = client.post(f"/lots/{lot['id']}/advance")
    assert resp.status_code == 200
    advanced = resp.json()

    equipment = client.get("/equipment").json()
    etch_equipment = [eq for eq in equipment if eq["process_step"] == PROCESS_ROUTE[0]]
    dispatched = next(eq for eq in etch_equipment if eq["dispatch_count"] == 1)
    idle_peer = next(eq for eq in etch_equipment if eq["dispatch_count"] == 0)

    events = client.get(f"/equipment/{dispatched['id']}/events")
    assert events.status_code == 200
    body = events.json()
    assert len(body) == 1
    assert body[0]["lot_id"] == advanced["id"]
    assert body[0]["event_type"] == "PROCESS_COMPLETED"
    assert body[0]["equipment_id"] == dispatched["id"]

    assert client.get(f"/equipment/{idle_peer['id']}/events").json() == []


def test_equipment_events_404s_for_unknown_equipment(client):
    resp = client.get("/equipment/999999/events")
    assert resp.status_code == 404
