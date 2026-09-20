from app.models import LotStatus


ALLOWED_LOT_TRANSITIONS = {
    LotStatus.WAITING: {LotStatus.PROCESSING, LotStatus.HOLD},
    LotStatus.PROCESSING: {LotStatus.PROCESSING, LotStatus.HOLD, LotStatus.DONE},
    LotStatus.HOLD: {LotStatus.PROCESSING},
    LotStatus.DONE: set(),
}


def ensure_lot_transition(from_status: LotStatus, to_status: LotStatus) -> None:
    """Raise when a command tries to bypass the explicit lot state machine."""
    if to_status not in ALLOWED_LOT_TRANSITIONS[from_status]:
        raise ValueError(f"invalid lot transition: {from_status} -> {to_status}")
