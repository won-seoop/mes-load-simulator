import pytest

from app.models import LotStatus
from app.state_machine import ensure_lot_transition


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (LotStatus.WAITING, LotStatus.PROCESSING),
        (LotStatus.WAITING, LotStatus.HOLD),
        (LotStatus.PROCESSING, LotStatus.PROCESSING),
        (LotStatus.PROCESSING, LotStatus.HOLD),
        (LotStatus.PROCESSING, LotStatus.QUALITY_HOLD),
        (LotStatus.HOLD, LotStatus.PROCESSING),
        (LotStatus.QUALITY_HOLD, LotStatus.DONE),
        (LotStatus.QUALITY_HOLD, LotStatus.REWORK),
        (LotStatus.QUALITY_HOLD, LotStatus.SCRAPPED),
        (LotStatus.REWORK, LotStatus.WAITING),
    ],
)
def test_allowed_lot_transitions(from_status, to_status):
    ensure_lot_transition(from_status, to_status)


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (LotStatus.WAITING, LotStatus.DONE),
        (LotStatus.HOLD, LotStatus.DONE),
        (LotStatus.PROCESSING, LotStatus.DONE),
        (LotStatus.QUALITY_HOLD, LotStatus.PROCESSING),
        (LotStatus.REWORK, LotStatus.DONE),
        (LotStatus.SCRAPPED, LotStatus.PROCESSING),
        (LotStatus.DONE, LotStatus.PROCESSING),
        (LotStatus.DONE, LotStatus.HOLD),
    ],
)
def test_forbidden_lot_transitions(from_status, to_status):
    with pytest.raises(ValueError, match="invalid lot transition"):
        ensure_lot_transition(from_status, to_status)
