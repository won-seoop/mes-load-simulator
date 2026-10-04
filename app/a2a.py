"""Quality Investigation Agent, framed with the publicly described A2A
(Agent2Agent) protocol's AgentCard / Task / Artifact concepts.

Google published the A2A protocol (now hosted by the Linux Foundation) with
three public ideas this module borrows: an AgentCard (a static, discoverable
description of what an agent can do), a Task that moves through a small
state machine (submitted -> working -> completed/failed) while the agent
works, and an Artifact (the task's structured output). This module does
*not* implement the A2A wire protocol or SDK — no JSON-RPC transport, no
streaming, no push notifications, no multi-agent handshake. It only reuses
that state/output shape for one agent that already existed in this project
(the rule-based quality-anomaly agent in simulation.py), because nothing
Samsung SDS has publicly described compares to an internal agent protocol.

Nothing here calls an LLM and nothing here executes a factory action. A
completed task's artifact only adds evidence to the same `Proposal` that
already flows through control_tower -> approval queue (app/control_tower.py)
— the human-in-the-loop boundary is unchanged.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import EquipmentDowntimeEvent, InvestigationTask, InvestigationTaskState

logger = logging.getLogger("app.a2a")

AGENT_ID = "quality-investigation-agent"

# A static AgentCard-shaped description. Not fetched from anywhere, and the
# "capabilities" are reported honestly: this agent is polled, it does not
# stream partial results and does not push notifications.
AGENT_CARD = {
    "name": AGENT_ID,
    "description": (
        "품질 이상(불량률)이 감지된 설비에 대해 최근 다운타임 이력과 검사 통계를 "
        "모아 조사 결과(Artifact)를 만드는 규칙 기반 조사 에이전트. LLM을 호출하지 "
        "않으며, 조치를 직접 실행하지 않는다 — 결과는 승인 큐로만 전달된다."
    ),
    "version": "0.1.0",
    "provider": "FactoryFlow MES Lab (self-built; not Samsung SDS Nexplant)",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": "investigate-quality-anomaly",
            "name": "Investigate quality anomaly",
            "description": (
                "A WARNING/CRITICAL AnomalyLog row triggers one investigation: "
                "the equipment's recent downtime events are correlated with the "
                "anomaly and summarized into an Artifact."
            ),
        }
    ],
}

# How far back (seconds) to pull downtime events into the artifact's
# evidence. Generous enough to catch a fault that preceded the anomaly
# without dragging in unrelated older history. No published standard behind
# this number -- a demo-scale choice, like the other windows in this project.
DOWNTIME_LOOKBACK_SECONDS = 1800.0


def _recent_downtime(db: Session, equipment_id: int, now: datetime) -> list[dict]:
    since = now - timedelta(seconds=DOWNTIME_LOOKBACK_SECONDS)
    rows = (
        db.query(EquipmentDowntimeEvent)
        .filter(
            EquipmentDowntimeEvent.equipment_id == equipment_id,
            EquipmentDowntimeEvent.started_at >= since,
        )
        .order_by(EquipmentDowntimeEvent.started_at.desc())
        .all()
    )
    return [
        {
            "reason": r.reason,
            "started_at": r.started_at.isoformat(),
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "duration_seconds": r.duration_seconds,
        }
        for r in rows
    ]


def investigate_quality_anomaly(
    db: Session, anomaly, anomaly_log_id: Optional[int], now: datetime
) -> InvestigationTask:
    """Run one investigation end to end (submitted -> working ->
    completed/failed) and return the row.

    Synchronous rather than a background task: the underlying queries are
    cheap, and this already runs off the simulation engine's own tick thread
    (not a request thread), so there is no caller blocked on I/O to justify
    deferring the work.
    """
    task = InvestigationTask(
        agent_id=AGENT_ID,
        created_at=now,
        updated_at=now,
        state=InvestigationTaskState.SUBMITTED.value,
        equipment_id=anomaly.equipment_id,
        equipment_name=anomaly.equipment_name,
        anomaly_log_id=anomaly_log_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    task.state = InvestigationTaskState.WORKING.value
    task.updated_at = now
    db.commit()

    try:
        downtime = _recent_downtime(db, anomaly.equipment_id, now)
        z = anomaly.z_score
        lookback_minutes = DOWNTIME_LOOKBACK_SECONDS / 60
        downtime_note = (
            f"최근 {lookback_minutes:.0f}분 내 다운타임 {len(downtime)}건"
            if downtime
            else f"최근 {lookback_minutes:.0f}분 내 다운타임 없음"
        )
        artifact = {
            "name": "quality-investigation-result",
            "equipment_id": anomaly.equipment_id,
            "equipment_name": anomaly.equipment_name,
            "process_step": anomaly.process_step,
            "summary": (
                f"{anomaly.equipment_name} 불량률 {anomaly.defect_rate * 100:.1f}% "
                f"vs 동일 공정 동료 평균 {anomaly.peer_mean_rate * 100:.1f}%"
                + (f" (z={z:.2f})" if z is not None else "")
                + f" · {downtime_note}"
            ),
            "evidence": {
                "defect_rate": anomaly.defect_rate,
                "peer_mean_rate": anomaly.peer_mean_rate,
                "z_score": z,
                "total_inspections": anomaly.total_inspections,
                "severity": anomaly.severity,
                "recent_downtime_events": downtime,
            },
        }
        task.artifact_json = json.dumps(artifact)
        task.state = InvestigationTaskState.COMPLETED.value
    except Exception as exc:  # the quality agent's own proposal must not depend on this
        logger.warning("investigation task %s failed: %s", task.id, exc)
        task.state = InvestigationTaskState.FAILED.value
        task.error = str(exc)
    task.updated_at = now
    db.commit()
    db.refresh(task)
    return task


def artifact_of(task: InvestigationTask) -> Optional[dict]:
    if not task.artifact_json:
        return None
    return json.loads(task.artifact_json)
