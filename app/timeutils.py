"""Timezone helpers.

Every timestamp in the app is stored as naive UTC (`datetime.utcnow()`), but
the daily reporting cadence is KST: the scheduler runs at 07:00 KST and the
report/roadmap are read by a human on KST calendar days. Without this, a
"today" computed from UTC midnight actually flips at 09:00 KST, so a run
between KST 00:00 and 08:59 attributes its results to the previous KST day
(see ROADMAP.md's 2026-09-18 backlog note for the bug this fixes).
"""

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def kst_midnight_utc(now_utc: datetime) -> datetime:
    """Naive-UTC instant of KST midnight for the KST calendar day containing now_utc."""
    now_kst = now_utc.replace(tzinfo=timezone.utc).astimezone(KST)
    midnight_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_kst.astimezone(timezone.utc).replace(tzinfo=None)
