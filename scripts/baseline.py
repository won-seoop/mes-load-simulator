"""Day-over-day statistical baseline check for the daily report.

ROADMAP.md "다음 후보": today's single number for metrics like `Peak lots on
HOLD` or p95 latency has so far only been judged by eye against yesterday's
report, or against a hand-picked fixed threshold (see
scripts/summarize.py quality anomaly handling). This module instead builds
a mean/stdev baseline from every prior daily report under reports/*.json
and flags today's value as a day-over-day anomaly candidate only when it is
both statistically extreme (|z-score| >= Z_THRESHOLD) and moving in the
direction that is actually bad for that metric (a lower p95 is not a
problem; a lower yield rate is).

Before picking the z-score threshold, the actual historical spread of 25
daily reports (2026-09-17 .. 2026-10-12) was measured directly (not
assumed): metrics like `peak_lots_on_hold_count` and `p95_ms` have a
coefficient of variation (stdev / mean) of 0.7-0.8, because a handful of
runs hit stochastic multi-equipment-down fault injection bursts or shared
container CPU contention from concurrent Playwright sessions -- both
already documented in ROADMAP.md as normal, non-regression variation.
A low z-threshold would have flagged those same already-explained runs
every time. Z_THRESHOLD=3.0 keeps those runs below the flag line (e.g.
peak_lots_on_hold_count: mean=19.2, stdev=15.4 -> 3-sigma bound=65.4,
above the historical max of 49) while still catching a value genuinely
outside the historical envelope. Each flagged (or unflagged) metric also
reports `confidence`: "low" when that metric's own historical CV is above
HIGH_VARIANCE_CV, so a human reading the report knows which flags to trust
less, instead of the check silently going quiet on noisy metrics.

This augments, and does not replace, the existing peer-equipment defect
rate comparison in scripts/summarize.py (quality_anomalies) and the
quality agent's own anomaly detection (app/simulation.py) -- those compare
equipment against each other within one run; this compares one day's
factory-wide numbers against the history of prior days.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Callable, Optional

MIN_HISTORY = 5
Z_THRESHOLD = 3.0
HIGH_VARIANCE_CV = 0.5

_DAILY_REPORT_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# name -> (getter over a summary dict as produced by scripts/summarize.py's
# `summary`, direction). direction controls which side of the baseline
# counts as "worse": a value moving the other way is never flagged, even if
# statistically extreme, and "informational" metrics are never flagged at
# all (their baseline/z-score is still reported for context).
MetricGetter = Callable[[dict], Optional[float]]
METRIC_SPECS: dict[str, tuple[MetricGetter, str]] = {
    "failure_rate": (lambda s: s.get("load_test", {}).get("failure_rate"), "higher_is_worse"),
    "p95_ms": (lambda s: s.get("load_test", {}).get("p95_ms"), "higher_is_worse"),
    "p99_ms": (lambda s: s.get("load_test", {}).get("p99_ms"), "higher_is_worse"),
    "rps": (lambda s: s.get("load_test", {}).get("rps"), "lower_is_worse"),
    "peak_lots_on_hold_count": (
        lambda s: s.get("mes_metrics_peak_during_run", {}).get("peak_lots_on_hold_count"),
        "higher_is_worse",
    ),
    "peak_hold_wait_seconds": (
        lambda s: s.get("mes_metrics_peak_during_run", {}).get("peak_longest_hold_seconds"),
        "higher_is_worse",
    ),
    "avg_resolved_hold_seconds": (
        lambda s: s.get("mes_metrics", {}).get("avg_resolved_hold_seconds"),
        "higher_is_worse",
    ),
    "defect_rate": (lambda s: s.get("quality_metrics", {}).get("defect_rate"), "higher_is_worse"),
    "yield_rate": (lambda s: s.get("mes_metrics", {}).get("yield_rate"), "lower_is_worse"),
    "wip_count": (lambda s: s.get("mes_metrics", {}).get("wip_count"), "informational"),
    "completed_today": (lambda s: s.get("mes_metrics", {}).get("completed_today"), "lower_is_worse"),
}


def load_history(reports_dir: Path, exclude_date: str) -> list[dict]:
    """Every prior daily report under reports_dir, oldest-format-safe.

    Skips the file being written for `exclude_date` (so a re-run of the
    same date never baselines against itself) and non-daily filenames such
    as `2026-09-20-exp003.json`, which are experiment snapshots, not daily
    pipeline runs, and would otherwise double-count that date or compare
    today against an unrelated experiment configuration.
    """
    history = []
    for f in sorted(reports_dir.glob("*.json")):
        if f.stem == exclude_date or not _DAILY_REPORT_NAME.match(f.stem):
            continue
        try:
            history.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            continue
    return history


def _compute_baseline(history: list[dict], getter: MetricGetter) -> Optional[dict]:
    values = [v for v in (getter(h) for h in history) if v is not None]
    if len(values) < MIN_HISTORY:
        return None
    mean = statistics.mean(values)
    stdev = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": round(mean, 4),
        "stdev": round(stdev, 4),
        "cv": round(stdev / mean, 4) if mean else None,
    }


def check_today(today_summary: dict, reports_dir: Path, run_date: str) -> dict[str, dict]:
    """Day-over-day baseline check for `run_date`'s summary dict (the same
    shape scripts/summarize.py builds before writing reports/<date>.json).
    Returns one entry per metric in METRIC_SPECS; never raises on missing
    or insufficient data -- it reports why a metric could not be checked
    instead (see CLAUDE.md "Ground Truth": never fabricate a number)."""
    history = load_history(reports_dir, run_date)
    results: dict[str, dict] = {}
    for name, (getter, direction) in METRIC_SPECS.items():
        baseline = _compute_baseline(history, getter)
        today_value = getter(today_summary)
        if baseline is None:
            results[name] = {
                "today": today_value,
                "baseline": None,
                "z_score": None,
                "direction": direction,
                "flag": "insufficient_history",
                "confidence": None,
            }
            continue
        if today_value is None:
            results[name] = {
                "today": None,
                "baseline": baseline,
                "z_score": None,
                "direction": direction,
                "flag": "no_data_today",
                "confidence": None,
            }
            continue
        z = (today_value - baseline["mean"]) / baseline["stdev"] if baseline["stdev"] else 0.0
        is_extreme = abs(z) >= Z_THRESHOLD
        worse_direction = (
            (direction == "higher_is_worse" and z > 0)
            or (direction == "lower_is_worse" and z < 0)
        )
        flag = "anomaly" if (direction != "informational" and is_extreme and worse_direction) else "normal"
        confidence = "low" if (baseline["cv"] is not None and baseline["cv"] > HIGH_VARIANCE_CV) else "normal"
        results[name] = {
            "today": today_value,
            "baseline": baseline,
            "z_score": round(z, 2),
            "direction": direction,
            "flag": flag,
            "confidence": confidence,
        }
    return results
