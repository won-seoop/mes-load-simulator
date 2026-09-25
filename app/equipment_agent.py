"""Rule-based baseline 'equipment agent': repeated DOWNs in a recent window
become an INSPECT_EQUIPMENT proposal. It only proposes; the control tower decides."""

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.control_tower import Proposal
from app.models import Equipment, EquipmentDowntimeEvent

AGENT_NAME = "rule:equipment-downtime"

# Demo values for the simulator's fault rate, not taken from any standard or real fab.
EQUIPMENT_DOWN_WINDOW_SECONDS = 600.0
# (min DOWN count in window, risk), highest first; the lowest count is the proposal threshold.
EQUIPMENT_DOWN_RISK_TIERS = ((6, "HIGH"), (4, "MEDIUM"), (3, "LOW"))

# Many different tools going DOWN close together points at a shared cause (utility,
# power, network), not at any one tool. Demo values: random simulator faults can
# occasionally reach the lowest tier by chance.
CONCURRENT_DOWN_WINDOW_SECONDS = 40.0  # a bit above the 30 s check interval so a check cannot miss the burst
# (min distinct equipment DOWN in window, risk), highest first.
CONCURRENT_DOWN_RISK_TIERS = ((8, "HIGH"), (5, "MEDIUM"))


def _risk_for(count: int) -> str | None:
    for min_count, risk in EQUIPMENT_DOWN_RISK_TIERS:
        if count >= min_count:
            return risk
    return None


def propose_from_downtime(db: Session, now: datetime) -> list[Proposal]:
    since = now - timedelta(seconds=EQUIPMENT_DOWN_WINDOW_SECONDS)
    events = (
        db.query(EquipmentDowntimeEvent)
        .filter(EquipmentDowntimeEvent.started_at >= since, EquipmentDowntimeEvent.started_at <= now)
        .all()
    )
    reasons: dict[int, Counter] = {}
    for ev in events:
        reasons.setdefault(ev.equipment_id, Counter())[ev.reason] += 1

    proposals: list[Proposal] = []
    for equipment_id, counter in sorted(reasons.items()):
        count = sum(counter.values())
        risk = _risk_for(count)
        eq = db.get(Equipment, equipment_id)
        if risk is None or eq is None:
            continue
        by_reason = ", ".join(f"{r} {n}회" for r, n in counter.most_common())
        proposals.append(
            Proposal(
                source_agent=AGENT_NAME,
                equipment_id=eq.id,
                equipment_name=eq.name,
                title=f"{eq.name} 반복 DOWN ({count}회)",
                proposal=f"{eq.name} 설비를 점검한다",
                evidence=(
                    f"최근 {EQUIPMENT_DOWN_WINDOW_SECONDS / 60:.0f}분 내 DOWN {count}회 ({by_reason})"
                ),
                risk_level=risk,
                action_kind="INSPECT_EQUIPMENT",
                dedupe_key=f"equipment-down:{eq.id}",
            )
        )
    return proposals


def propose_from_concurrent_downs(db: Session, now: datetime) -> list[Proposal]:
    since = now - timedelta(seconds=CONCURRENT_DOWN_WINDOW_SECONDS)
    equipment_ids = {
        row[0]
        for row in db.query(EquipmentDowntimeEvent.equipment_id)
        .filter(EquipmentDowntimeEvent.started_at >= since, EquipmentDowntimeEvent.started_at <= now)
        .all()
    }
    count = len(equipment_ids)
    risk = next((r for n, r in CONCURRENT_DOWN_RISK_TIERS if count >= n), None)
    if risk is None:
        return []
    names = ", ".join(
        sorted(eq.name for eq in db.query(Equipment).filter(Equipment.id.in_(equipment_ids)).all())
    )
    return [
        Proposal(
            source_agent=AGENT_NAME,
            equipment_id=None,
            equipment_name="공장 전체",
            title=f"설비 {count}대 동시 DOWN",
            proposal="공통 원인(전력·유틸리티·네트워크)을 점검한다",
            evidence=(
                f"최근 {CONCURRENT_DOWN_WINDOW_SECONDS:.0f}초 내 서로 다른 설비 {count}대 DOWN ({names})"
            ),
            risk_level=risk,
            action_kind="INSPECT_EQUIPMENT",
            dedupe_key="factory-wide-down",
        )
    ]
