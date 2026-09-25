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
