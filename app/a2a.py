"""Investigation agents, framed with the publicly described A2A
(Agent2Agent) protocol's AgentCard / Task / Artifact concepts.

Google published the A2A protocol (now hosted by the Linux Foundation) with
three public ideas this module borrows: an AgentCard (a static, discoverable
description of what an agent can do), a Task that moves through a small
state machine (submitted -> working -> completed/failed) while the agent
works, and an Artifact (the task's structured output). This module does
*not* implement the A2A wire protocol or SDK — no JSON-RPC transport, no
streaming, no push notifications, no multi-agent handshake. It only reuses
that state/output shape for rule-based agents that already existed in this
project (quality-anomaly and equipment-downtime, both in simulation.py /
equipment_agent.py), because nothing Samsung SDS has publicly described
compares to an internal agent protocol. Two agents share one
`InvestigationTask` table (distinguished by `agent_id`) rather than one
table each, since both tasks are the same submitted/working/completed
shape and nothing about either one needs its own schema.

Nothing here calls an LLM and nothing here executes a factory action. A
completed task's artifact only adds evidence to the same `Proposal` that
already flows through control_tower -> approval queue (app/control_tower.py)
— the human-in-the-loop boundary is unchanged.
"""

import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Equipment, EquipmentDowntimeEvent, InvestigationTask, InvestigationTaskState

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

EQUIPMENT_AGENT_ID = "equipment-investigation-agent"

# A second AgentCard, same honesty rules as AGENT_CARD above: this agent is
# polled from the simulation tick, not streamed or pushed to.
EQUIPMENT_AGENT_CARD = {
    "name": EQUIPMENT_AGENT_ID,
    "description": (
        "반복 DOWN이 감지된 설비에 대해 최근 다운타임 이력을 사유별로 모아 조사 "
        "결과(Artifact)를 만드는 규칙 기반 조사 에이전트. LLM을 호출하지 않으며, "
        "조치를 직접 실행하지 않는다 — 결과는 승인 큐로만 전달된다."
    ),
    "version": "0.1.0",
    "provider": "FactoryFlow MES Lab (self-built; not Samsung SDS Nexplant)",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": "investigate-equipment-downtime",
            "name": "Investigate equipment downtime",
            "description": (
                "rule:equipment-downtime (app/equipment_agent.py)가 반복 DOWN "
                "임계값을 넘겨 제안을 만들 때 한 번 조사한다: 같은 감지 window 안의 "
                "다운타임 이력을 사유별로 집계해 Artifact로 남긴다."
            ),
        }
    ],
}

PRODUCTION_AGENT_ID = "production-investigation-agent"

# A third AgentCard, same honesty rules as the two above: this agent is
# polled from the simulation tick, not streamed or pushed to.
PRODUCTION_AGENT_CARD = {
    "name": PRODUCTION_AGENT_ID,
    "description": (
        "공정 스텝 전체가 HOLD로 정체된 것이 감지되면 그 스텝에 배정된 설비들의 "
        "최근 다운타임 이력을 모아 조사 결과(Artifact)를 만드는 규칙 기반 조사 "
        "에이전트. LLM을 호출하지 않으며, 조치를 직접 실행하지 않는다 — 결과는 "
        "승인 큐로만 전달된다."
    ),
    "version": "0.1.0",
    "provider": "FactoryFlow MES Lab (self-built; not Samsung SDS Nexplant)",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": "investigate-step-hold",
            "name": "Investigate process step hold",
            "description": (
                "rule:production-hold (app/production_agent.py)가 한 공정 스텝의 "
                "모든 설비가 DOWN이라 로트가 HOLD로 쌓인 것을 감지해 제안을 만들 때 "
                "한 번 조사한다: 그 스텝에 배정된 설비들의 다운타임 이력을 설비별로 "
                "집계해 Artifact로 남긴다(단일 설비 조사와 달리, 대상이 한 설비가 "
                "아니라 그 스텝에 속한 설비 전체다)."
            ),
        }
    ],
}

# Every registered agent's static card, for a caller that wants to discover
# all investigation agents at once rather than one at a time.
AGENT_CARDS = [AGENT_CARD, EQUIPMENT_AGENT_CARD, PRODUCTION_AGENT_CARD]

# How far back (seconds) to pull downtime events into the quality
# investigation artifact's evidence. Generous enough to catch a fault that
# preceded the anomaly without dragging in unrelated older history. No
# published standard behind this number -- a demo-scale choice, like the
# other windows in this project.
DOWNTIME_LOOKBACK_SECONDS = 1800.0


def _recent_downtime(
    db: Session, equipment_id: int, now: datetime, lookback_seconds: float = DOWNTIME_LOOKBACK_SECONDS
) -> list[dict]:
    since = now - timedelta(seconds=lookback_seconds)
    rows = (
        db.query(EquipmentDowntimeEvent)
        .filter(
            EquipmentDowntimeEvent.equipment_id == equipment_id,
            # A downtime event still open right now (ended_at is NULL) is
            # always in scope no matter when it started -- the tool is down
            # *right now*, which is always relevant to "what's happening to
            # this equipment". Dropping the `started_at >= since` clause for
            # open rows avoids clipping the one downtime actually causing the
            # investigation when it started a moment before `since` (see the
            # equivalent, user-visible version of this bug documented at
            # _recent_downtime_for_equipment_ids below).
            or_(EquipmentDowntimeEvent.started_at >= since, EquipmentDowntimeEvent.ended_at.is_(None)),
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


def investigate_equipment_downtime(
    db: Session, equipment_id: int, equipment_name: str, window_seconds: float, now: datetime
) -> InvestigationTask:
    """Run one equipment-downtime investigation end to end (submitted ->
    working -> completed/failed) and return the row.

    `window_seconds` is passed in by the caller (equipment_agent.py's own
    detection window) rather than hard-coded here, so the artifact's event
    count always matches the exact window the proposal that triggered this
    investigation was computed over -- a different window would make the
    artifact's own evidence disagree with the proposal it is backing.
    """
    task = InvestigationTask(
        agent_id=EQUIPMENT_AGENT_ID,
        created_at=now,
        updated_at=now,
        state=InvestigationTaskState.SUBMITTED.value,
        equipment_id=equipment_id,
        equipment_name=equipment_name,
        anomaly_log_id=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    task.state = InvestigationTaskState.WORKING.value
    task.updated_at = now
    db.commit()

    try:
        downtime = _recent_downtime(db, equipment_id, now, lookback_seconds=window_seconds)
        by_reason = Counter(d["reason"] for d in downtime)
        by_reason_str = ", ".join(f"{r} {n}회" for r, n in by_reason.most_common())
        window_minutes = window_seconds / 60
        artifact = {
            "name": "equipment-investigation-result",
            "equipment_id": equipment_id,
            "equipment_name": equipment_name,
            "summary": (
                f"{equipment_name} 최근 {window_minutes:.0f}분 내 DOWN {len(downtime)}회"
                + (f" ({by_reason_str})" if by_reason else "")
            ),
            "evidence": {
                "window_seconds": window_seconds,
                "down_count_in_window": len(downtime),
                "by_reason": dict(by_reason),
                "recent_downtime_events": downtime,
            },
        }
        task.artifact_json = json.dumps(artifact)
        task.state = InvestigationTaskState.COMPLETED.value
    except Exception as exc:  # the equipment agent's own proposal must not depend on this
        logger.warning("equipment investigation task %s failed: %s", task.id, exc)
        task.state = InvestigationTaskState.FAILED.value
        task.error = str(exc)
    task.updated_at = now
    db.commit()
    db.refresh(task)
    return task


def _recent_downtime_for_equipment_ids(
    db: Session, equipment_ids: list[int], now: datetime, lookback_seconds: float
) -> list[dict]:
    if not equipment_ids:
        return []
    since = now - timedelta(seconds=lookback_seconds)
    rows = (
        db.query(EquipmentDowntimeEvent)
        .filter(
            EquipmentDowntimeEvent.equipment_id.in_(equipment_ids),
            # window_seconds for the production investigation is exactly the
            # HOLD's own wait (now - hold_started_at, see
            # investigate_step_hold), so `since` lands almost exactly on the
            # moment the HOLD began -- and the downtime that *caused* the
            # HOLD necessarily started at or microseconds *before* that
            # instant (the last tool on the step must go down before
            # advance_lot() can HOLD the lot), not after. A strict
            # `started_at >= since` therefore clips the one piece of
            # evidence the investigation exists to show (found live: the
            # very first manual repro of this investigation returned
            # down_count_in_window=0 while all 3 ETCH tools were actually
            # down). A downtime event still open right now (ended_at is
            # NULL) is always in scope regardless of when it started, since
            # the tool is down *right now*.
            or_(EquipmentDowntimeEvent.started_at >= since, EquipmentDowntimeEvent.ended_at.is_(None)),
        )
        .order_by(EquipmentDowntimeEvent.started_at.desc())
        .all()
    )
    return [
        {
            "equipment_id": r.equipment_id,
            "reason": r.reason,
            "started_at": r.started_at.isoformat(),
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "duration_seconds": r.duration_seconds,
        }
        for r in rows
    ]


def investigate_step_hold(
    db: Session, process_step: str, window_seconds: float, now: datetime
) -> InvestigationTask:
    """Run one process-step HOLD investigation end to end (submitted ->
    working -> completed/failed) and return the row.

    Unlike the two single-equipment investigations above,
    rule:production-hold's proposals carry no equipment_id — a whole step,
    not one tool, is stuck (advance_lot only HOLDs a lot once every tool on
    its step is DOWN, see app/production_agent.py) — so this first resolves
    every tool currently assigned to `process_step` and pools their
    downtime events rather than one tool's history. `window_seconds` is the
    exact HOLD wait the triggering proposal measured, passed in by the
    caller rather than a fixed constant, so the artifact's downtime count
    always matches the span of time the proposal is actually about (the
    same reasoning investigate_equipment_downtime already documents for its
    own window_seconds argument).
    """
    task = InvestigationTask(
        agent_id=PRODUCTION_AGENT_ID,
        created_at=now,
        updated_at=now,
        state=InvestigationTaskState.SUBMITTED.value,
        equipment_id=None,
        equipment_name=process_step,
        anomaly_log_id=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    task.state = InvestigationTaskState.WORKING.value
    task.updated_at = now
    db.commit()

    try:
        name_by_id = dict(
            db.query(Equipment.id, Equipment.name).filter(Equipment.process_step == process_step).all()
        )
        downtime = _recent_downtime_for_equipment_ids(db, list(name_by_id), now, window_seconds)
        for d in downtime:
            d["equipment_name"] = name_by_id.get(d["equipment_id"])
        by_equipment = Counter(d["equipment_name"] for d in downtime)
        by_equipment_str = ", ".join(f"{n} {c}회" for n, c in by_equipment.most_common())
        artifact = {
            "name": "production-investigation-result",
            "process_step": process_step,
            "equipment_count": len(name_by_id),
            "summary": (
                f"{process_step} 정체 구간({window_seconds:.0f}초) 내 설비 다운 {len(downtime)}건"
                + (f" ({by_equipment_str})" if by_equipment else "")
            ),
            "evidence": {
                "window_seconds": window_seconds,
                "down_count_in_window": len(downtime),
                "by_equipment": dict(by_equipment),
                "recent_downtime_events": downtime,
            },
        }
        task.artifact_json = json.dumps(artifact)
        task.state = InvestigationTaskState.COMPLETED.value
    except Exception as exc:  # the production agent's own proposal must not depend on this
        logger.warning("production investigation task %s failed: %s", task.id, exc)
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


def task_ids_by_anomaly_log(db: Session, anomaly_log_ids: list[int]) -> dict[int, int]:
    """Batch-resolve each AnomalyLog row's own InvestigationTask id, keyed by
    anomaly_log_id, in one query rather than one query per row.

    Unlike latest_task_ids above, this is not a "most recent before a
    cutoff" heuristic -- investigate_quality_anomaly() is called at most
    once per AnomalyLog row, passing that row's own id as anomaly_log_id
    (simulation.py's _maybe_check_anomalies writes the log row, then
    investigates, in that order), so the relationship is a direct foreign
    key, not an inference. Used by GET /quality/anomaly-log so the
    dashboard's "이상 이력" page can offer "조사 근거 보기" per row without
    an extra round trip per row.
    """
    if not anomaly_log_ids:
        return {}
    rows = (
        db.query(InvestigationTask)
        .filter(InvestigationTask.anomaly_log_id.in_(anomaly_log_ids))
        .order_by(InvestigationTask.id.desc())
        .all()
    )
    result: dict[int, int] = {}
    for t in rows:
        result.setdefault(t.anomaly_log_id, t.id)
    return result


def latest_task_ids(
    db: Session, keys: list[tuple[Optional[int], Optional[str], datetime]]
) -> list[Optional[int]]:
    """Batch-resolve, for each (equipment_id, equipment_name, cutoff) key, the
    most recent InvestigationTask created at or before `cutoff` that matches
    it -- in one pair of queries rather than one query per key.

    Used by GET /control-tower/decisions to offer "조사 근거 보기" even on
    AUTO_RECORD rows, which carry no evidence string at all (they never reach
    the approval queue, see app/control_tower.py's QUEUE_MIN_RISK gate) and so
    have nothing for the dashboard's existing `A2A Task #<id>` regex
    (app/static/index.html) to find. `equipment_id=None` pairs with
    `equipment_name` as the process step instead (rule:production-hold's
    rows, see investigate_step_hold) -- the same two-shape matching
    simulation.py already uses for its own suppression-window lookups.

    `cutoff` keeps a decision from linking to a task created after it (e.g. a
    later, unrelated anomaly on the same equipment); without it, an old
    decision further down a long list could point at the wrong task.
    """
    equipment_ids = {eid for eid, _, _ in keys if eid is not None}
    step_names = {name for eid, name, _ in keys if eid is None and name is not None}
    by_equipment: dict[int, list[InvestigationTask]] = {}
    by_step: dict[str, list[InvestigationTask]] = {}
    if equipment_ids:
        for t in (
            db.query(InvestigationTask)
            .filter(InvestigationTask.equipment_id.in_(equipment_ids))
            .order_by(InvestigationTask.id.desc())
            .all()
        ):
            by_equipment.setdefault(t.equipment_id, []).append(t)
    if step_names:
        for t in (
            db.query(InvestigationTask)
            .filter(
                InvestigationTask.equipment_id.is_(None),
                InvestigationTask.equipment_name.in_(step_names),
            )
            .order_by(InvestigationTask.id.desc())
            .all()
        ):
            by_step.setdefault(t.equipment_name, []).append(t)

    result: list[Optional[int]] = []
    for eid, name, cutoff in keys:
        candidates = by_equipment.get(eid, []) if eid is not None else by_step.get(name, [])
        match = next((t for t in candidates if t.created_at <= cutoff), None)
        result.append(match.id if match else None)
    return result
