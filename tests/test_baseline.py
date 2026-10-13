"""scripts/baseline.py: day-over-day statistical baseline check.

See ROADMAP.md "전일 대비 이상 탐지 고도화" and scripts/baseline.py's module
docstring for why a plain z-score with a fixed low threshold would have
flagged already-explained, high-variance runs (e.g. peak_lots_on_hold_count)
every single day.
"""

import json
from pathlib import Path

from scripts import baseline


def _write_report(reports_dir: Path, date: str, failure_rate: float, wip: int = 2300) -> None:
    summary = {
        "date": date,
        "load_test": {"failure_rate": failure_rate, "p95_ms": 80.0, "p99_ms": 200.0, "rps": 90.0},
        "mes_metrics": {
            "wip_count": wip,
            "yield_rate": 0.99,
            "completed_today": 200,
            "avg_resolved_hold_seconds": 10.0,
        },
        "mes_metrics_peak_during_run": {
            "peak_lots_on_hold_count": 20,
            "peak_longest_hold_seconds": 15.0,
        },
        "quality_metrics": {"defect_rate": 0.08},
    }
    (reports_dir / f"{date}.json").write_text(json.dumps(summary))


def test_insufficient_history_is_reported_not_silently_skipped(tmp_path):
    _write_report(tmp_path, "2026-01-01", failure_rate=0.0)
    result = baseline.check_today(
        {"load_test": {"failure_rate": 0.0}}, tmp_path, "2026-01-10"
    )
    assert result["failure_rate"]["flag"] == "insufficient_history"
    assert result["failure_rate"]["baseline"] is None


def test_exact_historical_mean_is_not_flagged(tmp_path):
    for i in range(6):
        _write_report(tmp_path, f"2026-01-{i + 1:02d}", failure_rate=0.0)
    today_summary = {"load_test": {"failure_rate": 0.0}}
    result = baseline.check_today(today_summary, tmp_path, "2026-01-20")
    assert result["failure_rate"]["flag"] == "normal"
    assert result["failure_rate"]["z_score"] == 0.0


def test_extreme_value_in_the_worse_direction_is_flagged_anomaly(tmp_path):
    # Six historical days with a small failure rate that varies slightly
    # (a flat stdev=0 baseline would make z-score meaningless)...
    rates = [0.0005, 0.0008, 0.0012, 0.0009, 0.0006, 0.0011]
    for i, rate in enumerate(rates):
        _write_report(tmp_path, f"2026-01-{i + 1:02d}", failure_rate=rate)
    # ...then today's run fails far more often than ever observed.
    today_summary = {"load_test": {"failure_rate": 0.5}}
    result = baseline.check_today(today_summary, tmp_path, "2026-01-20")
    assert result["failure_rate"]["flag"] == "anomaly"
    assert result["failure_rate"]["z_score"] > baseline.Z_THRESHOLD


def test_extreme_value_in_the_better_direction_is_not_flagged(tmp_path):
    # rps is lower_is_worse: a historically high rps dropping to near zero
    # would be bad, but a rps *spike* above history is not a problem.
    for i in range(6):
        _write_report(tmp_path, f"2026-01-{i + 1:02d}", failure_rate=0.0)
    today_summary = {"load_test": {"failure_rate": 0.0, "rps": 10_000.0}}
    result = baseline.check_today(today_summary, tmp_path, "2026-01-20")
    assert result["rps"]["flag"] == "normal"


def test_informational_metric_is_never_flagged_even_when_extreme(tmp_path):
    for i in range(6):
        _write_report(tmp_path, f"2026-01-{i + 1:02d}", failure_rate=0.0, wip=2300)
    today_summary = {
        "load_test": {"failure_rate": 0.0},
        "mes_metrics": {"wip_count": 50_000},
    }
    result = baseline.check_today(today_summary, tmp_path, "2026-01-20")
    assert result["wip_count"]["direction"] == "informational"
    assert result["wip_count"]["flag"] == "normal"


def test_high_cv_metric_is_marked_low_confidence(tmp_path):
    # peak_lots_on_hold_count values spread widely across history (as
    # actually observed in reports/*.json) -> cv should exceed the
    # high-variance threshold and the flag should say so.
    reports_dir = tmp_path
    for i, peak in enumerate([2, 49, 5, 40, 3, 30]):
        summary = {
            "load_test": {"failure_rate": 0.0},
            "mes_metrics": {},
            "mes_metrics_peak_during_run": {"peak_lots_on_hold_count": peak},
            "quality_metrics": {},
        }
        (reports_dir / f"2026-01-{i + 1:02d}.json").write_text(json.dumps(summary))
    today_summary = {
        "load_test": {"failure_rate": 0.0},
        "mes_metrics": {},
        "mes_metrics_peak_during_run": {"peak_lots_on_hold_count": 20},
        "quality_metrics": {},
    }
    result = baseline.check_today(today_summary, reports_dir, "2026-01-20")
    assert result["peak_lots_on_hold_count"]["baseline"]["cv"] > baseline.HIGH_VARIANCE_CV
    assert result["peak_lots_on_hold_count"]["confidence"] == "low"


def test_todays_own_report_is_excluded_from_its_own_baseline(tmp_path):
    # Re-running summarize.py for the same date must never let today's file
    # (if it already exists from a prior run) baseline against itself.
    for i in range(6):
        _write_report(tmp_path, f"2026-01-{i + 1:02d}", failure_rate=0.0)
    _write_report(tmp_path, "2026-01-20", failure_rate=0.9)
    history = baseline.load_history(tmp_path, exclude_date="2026-01-20")
    assert all(h["load_test"]["failure_rate"] == 0.0 for h in history)


def test_experiment_snapshot_filenames_are_excluded_from_history(tmp_path):
    _write_report(tmp_path, "2026-01-01", failure_rate=0.0)
    (tmp_path / "2026-01-01-exp003.json").write_text(
        json.dumps({"load_test": {"failure_rate": 0.9}})
    )
    history = baseline.load_history(tmp_path, exclude_date="2026-01-20")
    assert len(history) == 1
    assert history[0]["load_test"]["failure_rate"] == 0.0


def test_no_data_today_is_reported_distinctly_from_insufficient_history(tmp_path):
    for i in range(6):
        _write_report(tmp_path, f"2026-01-{i + 1:02d}", failure_rate=0.0)
    today_summary = {"load_test": {}}
    result = baseline.check_today(today_summary, tmp_path, "2026-01-20")
    assert result["failure_rate"]["flag"] == "no_data_today"
    assert result["failure_rate"]["baseline"] is not None
