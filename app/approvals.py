"""Human-in-the-Loop approval queue logic.

Agents (rule-based today) only *propose*; a person approves, rejects or edits.
Nothing in this module executes an action on the factory.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import ApprovalRequest, ApprovalRisk, ApprovalStatus

RISK_ORDER = {
    ApprovalRisk.LOW.value: 0,
    ApprovalRisk.MEDIUM.value: 1,
    ApprovalRisk.HIGH.value: 2,
    ApprovalRisk.CRITICAL.value: 3,
}
VALID_ACTIONS = {"approve", "reject"}


class ApprovalNotFound(Exception):
    pass


class ApprovalConflict(Exception):
    """The request was already decided (or expired) by someone else."""


class ApprovalInvalid(Exception):
    pass


def expire_stale(db: Session, now: datetime) -> int:
    result = db.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
            ApprovalRequest.expires_at.is_not(None),
            ApprovalRequest.expires_at < now,
        )
        .values(status=ApprovalStatus.EXPIRED.value, decided_at=now, decided_by="system")
    )
    db.commit()
    return result.rowcount or 0


def upsert_request(
    db: Session,
    *,
    source_agent: str,
    title: str,
    proposal: str,
    dedupe_key: str,
    risk_level: str = ApprovalRisk.MEDIUM.value,
    evidence: Optional[str] = None,
    equipment_id: Optional[int] = None,
    ttl_seconds: Optional[int] = 900,
    now: Optional[datetime] = None,
) -> tuple[ApprovalRequest, bool]:
    """Create a PENDING request, or fold into the existing PENDING one with the
    same dedupe_key (occurrence_count += 1). Returns (row, created)."""
    if risk_level not in RISK_ORDER:
        raise ApprovalInvalid(f"invalid risk_level: {risk_level}")
    now = now or datetime.utcnow()
    expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None

    existing = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.dedupe_key == dedupe_key,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        )
        .first()
    )
    if existing is not None:
        existing.occurrence_count += 1
        existing.last_seen_at = now
        existing.expires_at = expires_at
        # Title/proposal/evidence describe the latest observation; risk_level stays the
        # peak so a brief dip cannot hide a request that was HIGH earlier.
        existing.title = title
        existing.proposal = proposal
        if evidence is not None:
            existing.evidence = evidence
        if RISK_ORDER[risk_level] > RISK_ORDER[existing.risk_level]:
            existing.risk_level = risk_level
        db.commit()
        db.refresh(existing)
        return existing, False

    row = ApprovalRequest(
        created_at=now,
        last_seen_at=now,
        expires_at=expires_at,
        status=ApprovalStatus.PENDING.value,
        risk_level=risk_level,
        source_agent=source_agent,
        title=title,
        proposal=proposal,
        evidence=evidence,
        equipment_id=equipment_id,
        dedupe_key=dedupe_key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, True


def decide(
    db: Session,
    approval_id: int,
    *,
    action: str,
    reason: Optional[str],
    edited_proposal: Optional[str],
    decided_by: str,
    now: Optional[datetime] = None,
) -> ApprovalRequest:
    if action not in VALID_ACTIONS:
        raise ApprovalInvalid("action must be 'approve' or 'reject'")
    if action == "reject" and not (reason and reason.strip()):
        raise ApprovalInvalid("reject requires a reason (it is the feedback signal)")
    if action == "reject" and edited_proposal:
        raise ApprovalInvalid("edited_proposal is only valid with approve")

    now = now or datetime.utcnow()
    if db.get(ApprovalRequest, approval_id) is None:
        raise ApprovalNotFound(approval_id)

    new_status = (
        ApprovalStatus.APPROVED.value if action == "approve" else ApprovalStatus.REJECTED.value
    )
    # Conditional UPDATE: only one concurrent decider can move PENDING -> decided.
    result = db.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
            (ApprovalRequest.expires_at.is_(None)) | (ApprovalRequest.expires_at >= now),
        )
        .values(
            status=new_status,
            decided_at=now,
            decided_by=decided_by,
            decision_reason=reason,
            edited_proposal=edited_proposal,
        )
    )
    db.commit()
    if not result.rowcount:
        raise ApprovalConflict(approval_id)
    row = db.get(ApprovalRequest, approval_id)
    db.refresh(row)
    return row


def summary(db: Session, now: Optional[datetime] = None) -> dict:
    now = now or datetime.utcnow()
    pending = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.status == ApprovalStatus.PENDING.value)
        .all()
    )
    by_risk = {r: 0 for r in RISK_ORDER}
    for row in pending:
        by_risk[row.risk_level] = by_risk.get(row.risk_level, 0) + 1
    oldest = min((r.created_at for r in pending), default=None)

    def count(status: ApprovalStatus) -> int:
        return db.query(ApprovalRequest).filter(ApprovalRequest.status == status.value).count()

    edited = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.status == ApprovalStatus.APPROVED.value,
            ApprovalRequest.edited_proposal.is_not(None),
        )
        .count()
    )
    approved, rejected, expired = (
        count(ApprovalStatus.APPROVED),
        count(ApprovalStatus.REJECTED),
        count(ApprovalStatus.EXPIRED),
    )
    return {
        "pending_count": len(pending),
        "oldest_pending_age_seconds": (now - oldest).total_seconds() if oldest else None,
        "pending_by_risk": by_risk,
        "decided_total": approved + rejected + expired,
        "approved_total": approved,
        "rejected_total": rejected,
        "expired_total": expired,
        "edited_total": edited,
    }
