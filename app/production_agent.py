"""Rule-based baseline "production agent": lots stuck in HOLD too long at the
same process step become a bottleneck proposal. It only proposes; the control
tower decides.

This is a different signal from rule:equipment-downtime, which counts how
many times one tool went DOWN. A step only shows up here once every piece of
equipment on that step is DOWN at once (advance_lot() only HOLDs a lot when
no eligible equipment remains for its step — see app/main.py::advance_lot),
so this measures production impact (how long WIP has actually been stalled,
and where) rather than individual equipment health. A single flaky tool that
recovers quickly never triggers this agent as long as its peers keep the step
running.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.control_tower import Proposal
from app.models import Lot, LotEvent, LotEventType, LotStatus

AGENT_NAME = "rule:production-hold"

# Demo values for this simulator, not from a real fab or standard. A single
# tool's own DOWN duration in the autonomous simulation engine tops out at
# 30s (SimulationConfig.equipment_down_max_seconds), so an unresolved
# step-wide HOLD past that point already means more than one bad-luck DOWN
# stacked up, not just one slow recovery.
HOLD_RISK_TIERS = ((240.0, "HIGH"), (90.0, "MEDIUM"), (30.0, "LOW"))


def _risk_for(seconds: float) -> str | None:
    for min_seconds, risk in HOLD_RISK_TIERS:
        if seconds >= min_seconds:
            return risk
    return None


def propose_from_step_hold_wait(db: Session, now: datetime) -> list[Proposal]:
    """One proposal per process step whose longest currently-open HOLD wait
    crosses the lowest risk tier.

    Reconstructs open HOLD spans from the LOT_HELD / LOT_RELEASED_FROM_HOLD
    journal the same way app.main._equipment_hold_wait_metrics does, but kept
    per process_step instead of collapsed to one factory-wide number.
    """
    hold_events = (
        db.query(LotEvent)
        .filter(LotEvent.event_type.in_([LotEventType.LOT_HELD, LotEventType.LOT_RELEASED_FROM_HOLD]))
        .order_by(LotEvent.lot_id, LotEvent.sequence_number)
        .all()
    )
    open_hold: dict[int, tuple[datetime, str | None]] = {}  # lot_id -> (started_at, process_step)
    for event in hold_events:
        if event.event_type == LotEventType.LOT_HELD:
            open_hold[event.lot_id] = (event.occurred_at, event.process_step)
        else:
            open_hold.pop(event.lot_id, None)

    held_lot_ids = {lot_id for (lot_id,) in db.query(Lot.id).filter(Lot.status == LotStatus.HOLD).all()}

    longest_wait_by_step: dict[str, float] = {}
    stuck_count_by_step: dict[str, int] = {}
    for lot_id, (started_at, step) in open_hold.items():
        if lot_id not in held_lot_ids or step is None:
            continue
        wait = (now - started_at).total_seconds()
        stuck_count_by_step[step] = stuck_count_by_step.get(step, 0) + 1
        longest_wait_by_step[step] = max(longest_wait_by_step.get(step, 0.0), wait)

    proposals: list[Proposal] = []
    for step, wait in sorted(longest_wait_by_step.items()):
        risk = _risk_for(wait)
        if risk is None:
            continue
        count = stuck_count_by_step[step]
        proposals.append(
            Proposal(
                source_agent=AGENT_NAME,
                equipment_id=None,
                equipment_name=step,
                title=f"{step} 공정 정체 ({wait:.0f}초 대기)",
                proposal=f"{step} 공정 설비를 점검하고 신규 배정을 중지한다",
                evidence=(
                    f"{step} 공정 전체 설비 DOWN으로 로트 {count}건이 최대 {wait:.0f}초째 대기 중"
                ),
                risk_level=risk,
                action_kind="INSPECT_EQUIPMENT",
                dedupe_key=f"production-hold:{step}",
                window_seconds=wait,
            )
        )
    return proposals
