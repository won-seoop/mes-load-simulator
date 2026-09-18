from datetime import datetime

from app.timeutils import kst_midnight_utc


def test_kst_midnight_utc_after_kst_midnight_but_before_utc_midnight():
    # 2026-09-17 20:00 UTC == 2026-09-18 05:00 KST (already past KST midnight).
    now_utc = datetime(2026, 9, 17, 20, 0, 0)
    assert kst_midnight_utc(now_utc) == datetime(2026, 9, 17, 15, 0, 0)


def test_kst_midnight_utc_before_kst_midnight():
    # 2026-09-17 10:00 UTC == 2026-09-17 19:00 KST (still the same KST day).
    now_utc = datetime(2026, 9, 17, 10, 0, 0)
    assert kst_midnight_utc(now_utc) == datetime(2026, 9, 16, 15, 0, 0)


def test_kst_midnight_utc_is_idempotent_within_the_same_kst_day():
    early = kst_midnight_utc(datetime(2026, 9, 17, 15, 0, 1))
    late = kst_midnight_utc(datetime(2026, 9, 18, 14, 59, 59))
    assert early == late == datetime(2026, 9, 17, 15, 0, 0)
