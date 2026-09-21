from app.models import LotStatus


ALLOWED_LOT_TRANSITIONS = {
    LotStatus.WAITING: {LotStatus.PROCESSING, LotStatus.HOLD},
    LotStatus.PROCESSING: {
        LotStatus.PROCESSING,
        LotStatus.HOLD,
        LotStatus.QUALITY_HOLD,
    },
    # A lot HOLD-ed at the *last* process step (equipment was down at INSPECT)
    # completes that step directly into QUALITY_HOLD once released, same as a
    # PROCESSING lot would; it never passes through PROCESSING again.
    LotStatus.HOLD: {LotStatus.PROCESSING, LotStatus.QUALITY_HOLD},
    LotStatus.QUALITY_HOLD: {
        LotStatus.DONE,
        LotStatus.REWORK,
        LotStatus.SCRAPPED,
    },
    LotStatus.REWORK: {LotStatus.WAITING},
    LotStatus.SCRAPPED: set(),
    LotStatus.DONE: set(),
}


def ensure_lot_transition(from_status: LotStatus, to_status: LotStatus) -> None:
    """Raise when a command tries to bypass the explicit lot state machine."""
    if to_status not in ALLOWED_LOT_TRANSITIONS[from_status]:
        raise ValueError(f"invalid lot transition: {from_status} -> {to_status}")
