from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import a2a
from app.database import SessionLocal
from app.models import EquipmentDowntimeEvent, InvestigationTask

T0 = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture()
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _anomaly(**overrides):
    base = dict(
        equipment_id=1,
        equipment_name="ETCH-01",
        process_step="ETCH",
        severity="CRITICAL",
        defect_rate=0.3,
        peer_mean_rate=0.05,
        z_score=2.4,
        total_inspections=20,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_agent_card_reports_honest_capabilities():
    assert a2a.AGENT_CARD["name"] == "quality-investigation-agent"
    assert a2a.AGENT_CARD["capabilities"] == {"streaming": False, "pushNotifications": False}
    assert [s["id"] for s in a2a.AGENT_CARD["skills"]] == ["investigate-quality-anomaly"]


def test_investigation_task_completes_with_an_artifact(db):
    task = a2a.investigate_quality_anomaly(db, _anomaly(), anomaly_log_id=None, now=T0)

    assert task.state == "completed"
    assert task.error is None
    artifact = a2a.artifact_of(task)
    assert artifact["name"] == "quality-investigation-result"
    assert artifact["evidence"]["defect_rate"] == 0.3
    assert artifact["evidence"]["z_score"] == 2.4
    assert artifact["evidence"]["recent_downtime_events"] == []


def test_investigation_task_links_the_anomaly_log_row(db):
    task = a2a.investigate_quality_anomaly(db, _anomaly(), anomaly_log_id=42, now=T0)

    assert task.anomaly_log_id == 42


def test_artifact_includes_downtime_within_the_lookback_window(db):
    db.add(
        EquipmentDowntimeEvent(
            equipment_id=1,
            reason="RANDOM_FAULT",
            started_at=T0 - timedelta(seconds=60),
            ended_at=T0 - timedelta(seconds=30),
            duration_seconds=30.0,
        )
    )
    db.commit()

    task = a2a.investigate_quality_anomaly(db, _anomaly(), anomaly_log_id=None, now=T0)

    events = a2a.artifact_of(task)["evidence"]["recent_downtime_events"]
    assert len(events) == 1
    assert events[0]["reason"] == "RANDOM_FAULT"
    assert events[0]["duration_seconds"] == 30.0


def test_artifact_excludes_downtime_outside_the_lookback_window(db):
    db.add(
        EquipmentDowntimeEvent(
            equipment_id=1,
            reason="RANDOM_FAULT",
            started_at=T0 - timedelta(seconds=a2a.DOWNTIME_LOOKBACK_SECONDS + 60),
            ended_at=T0 - timedelta(seconds=a2a.DOWNTIME_LOOKBACK_SECONDS + 30),
            duration_seconds=30.0,
        )
    )
    db.commit()

    task = a2a.investigate_quality_anomaly(db, _anomaly(), anomaly_log_id=None, now=T0)

    assert a2a.artifact_of(task)["evidence"]["recent_downtime_events"] == []


def test_a2a_agent_card_endpoint(client):
    response = client.get("/a2a/agent-card")

    assert response.status_code == 200
    assert response.json()["name"] == "quality-investigation-agent"


def test_a2a_tasks_endpoint_lists_newest_first(client, db):
    a2a.investigate_quality_anomaly(db, _anomaly(equipment_id=1), anomaly_log_id=None, now=T0)
    a2a.investigate_quality_anomaly(
        db, _anomaly(equipment_id=2, equipment_name="ETCH-02"), anomaly_log_id=None, now=T0
    )

    response = client.get("/a2a/tasks")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert rows[0]["equipment_id"] == 2
    assert rows[0]["artifact"]["evidence"]["defect_rate"] == 0.3


def test_a2a_tasks_endpoint_filters_by_equipment(client, db):
    a2a.investigate_quality_anomaly(db, _anomaly(equipment_id=1), anomaly_log_id=None, now=T0)
    a2a.investigate_quality_anomaly(
        db, _anomaly(equipment_id=2, equipment_name="ETCH-02"), anomaly_log_id=None, now=T0
    )

    response = client.get("/a2a/tasks", params={"equipment_id": 2})

    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["equipment_id"] == 2


def test_a2a_task_detail_404_when_missing(client):
    response = client.get("/a2a/tasks/9999")

    assert response.status_code == 404


def test_a2a_task_detail_returns_artifact(client, db):
    task = a2a.investigate_quality_anomaly(db, _anomaly(), anomaly_log_id=None, now=T0)

    response = client.get(f"/a2a/tasks/{task.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "completed"
    assert body["artifact"]["evidence"]["total_inspections"] == 20
