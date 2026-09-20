from app.models import PROCESS_ROUTE


def _lot_at_quality_hold(client, product="WAFER-A"):
    lot = client.post("/lots", json={"product": product, "quantity": 25}).json()
    for _ in PROCESS_ROUTE:
        response = client.post(f"/lots/{lot['id']}/advance")
        assert response.status_code == 200
        lot = response.json()
    assert lot["status"] == "QUALITY_HOLD"
    return lot


def test_pass_inspection_completes_lot_with_equipment_trace(client):
    lot = _lot_at_quality_hold(client)

    response = client.post(f"/lots/{lot['id']}/inspections", json={"result": "PASS"})

    assert response.status_code == 200
    inspection = response.json()
    assert inspection["attempt_number"] == 1
    assert inspection["process_step"] == "INSPECT"
    assert inspection["equipment_id"] is not None
    assert inspection["disposition"] == "NONE"
    assert client.get(f"/lots/{lot['id']}").json()["status"] == "DONE"


def test_failed_inspection_requires_defect_code_and_disposition(client):
    lot = _lot_at_quality_hold(client)

    missing_code = client.post(
        f"/lots/{lot['id']}/inspections", json={"result": "FAIL"}
    )
    assert missing_code.status_code == 422

    failed = client.post(
        f"/lots/{lot['id']}/inspections",
        json={"result": "FAIL", "defect_code": "PARTICLE"},
    )
    assert failed.status_code == 200
    assert failed.json()["disposition"] == "PENDING"

    duplicate = client.post(
        f"/lots/{lot['id']}/inspections",
        json={"result": "FAIL", "defect_code": "PARTICLE"},
    )
    assert duplicate.status_code == 409


def test_scrap_disposition_updates_trace_and_quality_metrics(client):
    lot = _lot_at_quality_hold(client)
    client.post(
        f"/lots/{lot['id']}/inspections",
        json={"result": "FAIL", "defect_code": "CRACK"},
    )

    response = client.post(
        f"/lots/{lot['id']}/quality-disposition",
        json={"disposition": "SCRAP"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "SCRAPPED"
    events = client.get(f"/lots/{lot['id']}/events").json()
    assert [event["event_type"] for event in events[-2:]] == [
        "DEFECT_RECORDED",
        "LOT_SCRAPPED",
    ]
    metrics = client.get("/quality/metrics").json()
    assert metrics["fail_count"] == 1
    assert metrics["defect_rate"] == 1.0
    assert metrics["scrap_count"] == 1
    assert metrics["defects_by_process"] == {"INSPECT": 1}
    assert sum(metrics["defects_by_equipment"].values()) == 1


def test_rework_flow_records_second_attempt_and_first_pass_yield(client):
    lot = _lot_at_quality_hold(client)
    client.post(
        f"/lots/{lot['id']}/inspections",
        json={"result": "FAIL", "defect_code": "CD_OUT_OF_SPEC"},
    )
    rework = client.post(
        f"/lots/{lot['id']}/quality-disposition",
        json={"disposition": "REWORK"},
    )
    assert rework.status_code == 200
    assert rework.json()["status"] == "REWORK"

    released = client.post(
        f"/lots/{lot['id']}/rework-release", json={"step_index": 2}
    )
    assert released.status_code == 200
    assert released.json()["status"] == "WAITING"
    assert released.json()["step_index"] == 2

    for _ in range(2):
        advanced = client.post(f"/lots/{lot['id']}/advance")
        assert advanced.status_code == 200
    passed = client.post(f"/lots/{lot['id']}/inspections", json={"result": "PASS"})
    assert passed.status_code == 200
    assert passed.json()["attempt_number"] == 2

    metrics = client.get("/quality/metrics").json()
    assert metrics["total_inspections"] == 2
    assert metrics["rework_count"] == 1
    assert metrics["rework_rate"] == 1.0
    assert metrics["first_pass_yield"] == 0.0


def test_second_failed_inspection_requires_scrap_instead_of_rework_loop(client):
    lot = _lot_at_quality_hold(client)
    first_failure = client.post(
        f"/lots/{lot['id']}/inspections",
        json={"result": "FAIL", "defect_code": "SENSOR_DRIFT"},
    )
    assert first_failure.status_code == 200
    assert first_failure.json()["attempt_number"] == 1
    assert client.post(
        f"/lots/{lot['id']}/quality-disposition",
        json={"disposition": "REWORK"},
    ).status_code == 200
    assert client.post(
        f"/lots/{lot['id']}/rework-release", json={"step_index": 2}
    ).status_code == 200

    for _ in range(2):
        assert client.post(f"/lots/{lot['id']}/advance").status_code == 200
    second_failure = client.post(
        f"/lots/{lot['id']}/inspections",
        json={"result": "FAIL", "defect_code": "SENSOR_DRIFT"},
    )
    assert second_failure.status_code == 200
    assert second_failure.json()["attempt_number"] == 2

    blocked = client.post(
        f"/lots/{lot['id']}/quality-disposition",
        json={"disposition": "REWORK"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == (
        "maximum rework cycles reached; SCRAP disposition is required"
    )

    scrapped = client.post(
        f"/lots/{lot['id']}/quality-disposition",
        json={"disposition": "SCRAP"},
    )
    assert scrapped.status_code == 200
    assert scrapped.json()["status"] == "SCRAPPED"

    inspections = client.get(f"/lots/{lot['id']}/inspections").json()
    assert [item["disposition"] for item in inspections] == ["REWORK", "SCRAP"]


def test_quality_anomaly_detects_equipment_correlated_defect_rate(client):
    inspect_equipment = [
        item
        for item in client.get("/equipment").json()
        if item["process_step"] == "INSPECT"
    ]

    for target in inspect_equipment:
        for equipment in inspect_equipment:
            status = "IDLE" if equipment["id"] == target["id"] else "DOWN"
            assert client.patch(
                f"/equipment/{equipment['id']}/status", json={"status": status}
            ).status_code == 200

        for _ in range(10):
            lot = _lot_at_quality_hold(client)
            events = client.get(f"/lots/{lot['id']}/events").json()
            inspect_event = next(
                event
                for event in reversed(events)
                if event["event_type"] == "PROCESS_COMPLETED"
                and event["process_step"] == "INSPECT"
            )
            assert inspect_event["equipment_id"] == target["id"]
            if target["name"] == "INSPECT-03":
                failed = client.post(
                    f"/lots/{lot['id']}/inspections",
                    json={"result": "FAIL", "defect_code": "SENSOR_DRIFT"},
                )
                assert failed.status_code == 200
                assert client.post(
                    f"/lots/{lot['id']}/quality-disposition",
                    json={"disposition": "SCRAP"},
                ).status_code == 200
            else:
                assert client.post(
                    f"/lots/{lot['id']}/inspections", json={"result": "PASS"}
                ).status_code == 200

    response = client.get("/quality/anomalies")

    assert response.status_code == 200
    report = response.json()
    assert report["method"] == "same-process peer defect-rate comparison"
    assert report["minimum_inspections"] == 10
    assert len(report["anomalies"]) == 1
    anomaly = report["anomalies"][0]
    assert anomaly["equipment_name"] == "INSPECT-03"
    assert anomaly["total_inspections"] == 10
    assert anomaly["fail_count"] == 10
    assert anomaly["defect_rate"] == 1.0
    assert anomaly["peer_mean_rate"] == 0.0
    assert anomaly["z_score"] is None
    assert anomaly["severity"] == "CRITICAL"
