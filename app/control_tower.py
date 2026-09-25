"""Control tower: the single gate between agents and the approval queue.

Agents (rule-based today) only *propose*. The control tower merges proposals
about the same equipment into one, then decides what happens to it:
BLOCK (not an allowed action kind: recorded, never queued), AUTO_RECORD (LOW
risk: recorded, no human interrupted) or QUEUE (MEDIUM+: approval queue).
Nothing here executes anything on the factory.

plan() is pure; process() adds the DB writes.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app import approvals as approvals_service
from app.approvals import RISK_ORDER
from app.models import ApprovalRisk, ControlTowerDecision

BLOCK = "BLOCK"
AUTO_RECORD = "AUTO_RECORD"
QUEUE = "QUEUE"

# Ordered by how directly the action limits production; used to break risk ties.
ALLOWED_ACTION_KINDS = ("STOP_NEW_DISPATCH", "REVIEW_RECIPE", "INSPECT_EQUIPMENT")
QUEUE_MIN_RISK = ApprovalRisk.MEDIUM.value
APPROVAL_TTL_SECONDS = 900


@dataclass(frozen=True)
class Proposal:
    source_agent: str
    equipment_id: Optional[int]
    equipment_name: Optional[str]
    title: str
    proposal: str
    evidence: Optional[str]
    risk_level: str
    action_kind: str
    dedupe_key: str

    def __post_init__(self) -> None:
        if self.risk_level not in RISK_ORDER:
            raise ValueError(f"invalid risk_level: {self.risk_level}")
        if "," in self.source_agent:
            raise ValueError("source_agent must not contain ','")


@dataclass(frozen=True)
class PlannedDecision:
    disposition: str
    reason: str
    equipment_id: Optional[int]
    equipment_name: Optional[str]
    title: str
    proposal: str
    evidence: Optional[str]
    risk_level: str
    action_kinds: tuple[str, ...]
    contributing_agents: tuple[str, ...]
    dedupe_key: str


def _merge(group: list[Proposal]) -> dict:
    def priority(p: Proposal) -> int:
        kinds = ALLOWED_ACTION_KINDS
        return kinds.index(p.action_kind) if p.action_kind in kinds else len(kinds)

    top = max(group, key=lambda p: (RISK_ORDER[p.risk_level], -priority(p)))
    agents = tuple(dict.fromkeys(p.source_agent for p in group))
    kinds = tuple(dict.fromkeys(p.action_kind for p in group))
    first = group[0]
    if len(group) == 1:
        title, proposal, evidence = first.title, first.proposal, first.evidence
    else:
        name = first.equipment_name or "설비"
        title = f"{name} 복합 이상 ({' + '.join(agents)})"
        proposal = " / ".join(dict.fromkeys(p.proposal for p in group))
        evidence = "\n".join(f"[{p.source_agent}] {p.evidence}" for p in group if p.evidence) or None
    key = (
        f"control-tower:equipment:{first.equipment_id}"
        if first.equipment_id is not None
        else first.dedupe_key
    )
    return dict(
        equipment_id=first.equipment_id,
        equipment_name=first.equipment_name,
        title=title,
        proposal=proposal,
        evidence=evidence,
        risk_level=top.risk_level,
        action_kinds=kinds,
        contributing_agents=agents,
        dedupe_key=key,
    )


def _group_by_equipment(proposals: list[Proposal]) -> list[list[Proposal]]:
    # Proposals without equipment are unrelated to each other, so they group by their own key.
    groups: dict[tuple, list[Proposal]] = {}
    for p in proposals:
        key = ("eq", p.equipment_id) if p.equipment_id is not None else ("key", p.dedupe_key)
        groups.setdefault(key, []).append(p)
    return list(groups.values())


def plan(proposals: list[Proposal]) -> list[PlannedDecision]:
    """Merge per equipment, then pick a disposition. Blocked proposals are
    split off first so a disallowed action never rides along with an allowed one."""
    blocked = [p for p in proposals if p.action_kind not in ALLOWED_ACTION_KINDS]
    allowed = [p for p in proposals if p.action_kind in ALLOWED_ACTION_KINDS]
    planned: list[PlannedDecision] = []

    for group in _group_by_equipment(blocked):
        merged = _merge(group)
        reason = (
            f"허용되지 않은 조치 유형 {', '.join(merged['action_kinds'])} "
            f"(허용: {', '.join(ALLOWED_ACTION_KINDS)}) — 기록만 하고 큐에 넣지 않음"
        )
        planned.append(PlannedDecision(disposition=BLOCK, reason=reason, **merged))

    for group in _group_by_equipment(allowed):
        merged = _merge(group)
        if RISK_ORDER[merged["risk_level"]] < RISK_ORDER[QUEUE_MIN_RISK]:
            disposition = AUTO_RECORD
            reason = f"{merged['risk_level']} 위험 — 기록만 하고 사람에게 보내지 않음"
        else:
            disposition = QUEUE
            reason = f"{merged['risk_level']} 위험 — 승인 큐로 전달"
        planned.append(PlannedDecision(disposition=disposition, reason=reason, **merged))
    return planned


def _is_repeat(db: Session, d: PlannedDecision, approval_id: Optional[int]) -> bool:
    """A standing condition is re-proposed every check cycle; only a change
    (risk, agents, approval row or reason) is a new decision."""
    query = db.query(ControlTowerDecision).filter(
        ControlTowerDecision.disposition == d.disposition
    )
    if d.equipment_id is not None:
        query = query.filter(ControlTowerDecision.equipment_id == d.equipment_id)
    else:
        query = query.filter(
            ControlTowerDecision.equipment_id.is_(None),
            ControlTowerDecision.equipment_name == d.equipment_name,
        )
    last = query.order_by(ControlTowerDecision.id.desc()).first()
    return (
        last is not None
        and last.disposition == d.disposition
        and last.risk_level == d.risk_level
        and last.contributing_agents == ",".join(d.contributing_agents)
        and last.approval_id == approval_id
        and (d.disposition == QUEUE or last.reason == d.reason)
    )


def process(
    db: Session,
    proposals: list[Proposal],
    now: Optional[datetime] = None,
    advisor: Optional[Callable[[list[PlannedDecision]], list[PlannedDecision]]] = None,
) -> list[ControlTowerDecision]:
    """Plan, queue what must reach a human, and persist each decision.
    Returns the rows written (an unchanged repeat of the last decision is not rewritten)."""
    now = now or datetime.utcnow()
    written: list[ControlTowerDecision] = []
    planned = plan(proposals)
    if advisor is not None:
        planned = advisor(planned)  # may raise the risk level; never lowers it or un-blocks
    for d in planned:
        approval_id = None
        reason = d.reason
        if d.disposition == QUEUE:
            row, created = approvals_service.upsert_request(
                db,
                source_agent=", ".join(d.contributing_agents),
                title=d.title,
                proposal=d.proposal,
                evidence=d.evidence,
                risk_level=d.risk_level,
                equipment_id=d.equipment_id,
                dedupe_key=d.dedupe_key,
                ttl_seconds=APPROVAL_TTL_SECONDS,
                now=now,
            )
            approval_id = row.id
            reason += f" (요청 #{row.id}{'' if created else '에 병합'})"
        if _is_repeat(db, d, approval_id):
            continue
        decision = ControlTowerDecision(
            decided_at=now,
            equipment_id=d.equipment_id,
            equipment_name=d.equipment_name,
            disposition=d.disposition,
            reason=reason,
            contributing_agents=",".join(d.contributing_agents),
            risk_level=d.risk_level,
            approval_id=approval_id,
        )
        db.add(decision)
        db.commit()
        db.refresh(decision)
        written.append(decision)
    return written
