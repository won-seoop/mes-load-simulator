"""Audit trail for significant state changes outside the approval queue.

ApprovalRequest already keeps who/when/why for a decision made through the
Human-in-the-Loop queue. This module gives the same who/when/what/why record
to state changes that never go through that queue (equipment status PATCH,
work order release), and also records approval decisions here so one place
answers "what changed and why" across both paths.

`record()` only adds the row; it does not commit. Callers add it inside the
same transaction as the state change it describes and let their own
`db.commit()` cover both, so the audit row and the change it documents can
never disagree about whether something happened.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: Optional[int],
    summary: str,
    before: Optional[str] = None,
    after: Optional[str] = None,
    reason: Optional[str] = None,
    now: Optional[datetime] = None,
) -> AuditLog:
    row = AuditLog(
        occurred_at=now or datetime.utcnow(),
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        before_value=before,
        after_value=after,
        reason=reason,
    )
    db.add(row)
    return row


def list_recent(
    db: Session,
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    limit: int = 100,
) -> list[AuditLog]:
    q = db.query(AuditLog)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        q = q.filter(AuditLog.entity_id == entity_id)
    return q.order_by(AuditLog.occurred_at.desc()).limit(limit).all()
