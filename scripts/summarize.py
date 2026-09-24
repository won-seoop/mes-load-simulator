import csv
import json
import re
import sys
from pathlib import Path

def load_locust_stats(raw_dir: Path) -> dict:
    stats_file = raw_dir / "locust_stats.csv"
    if not stats_file.exists():
        return {}
    with stats_file.open() as f:
        rows = list(csv.DictReader(f))
    total = next((r for r in rows if r["Name"] == "Aggregated"), None)
    if not total:
        return {}
    business_conflicts = sum(
        int(row["Request Count"]) for row in rows if "[conflict]" in row["Name"]
    )
    server_log = raw_dir / "server.log"
    server_log_text = server_log.read_text() if server_log.exists() else ""
    return {
        "requests": int(total["Request Count"]),
        "failures": int(total["Failure Count"]),
        "failure_rate": round(int(total["Failure Count"]) / max(int(total["Request Count"]), 1), 4),
        "rps": float(total["Requests/s"]),
        "p95_ms": float(total["95%"]),
        "p99_ms": float(total["99%"]),
        "avg_ms": float(total["Average Response Time"]),
        "business_conflicts": business_conflicts,
        "server_5xx": len(re.findall(r'HTTP/1\.1 5\d\d ', server_log_text)),
        "integrity_errors": server_log_text.count("IntegrityError"),
    }


def load_metrics_samples(raw_dir: Path) -> list[dict]:
    """/metrics polled every 10s while locust ran, not just the final snapshot.

    Equipment-down HOLD is meant to be transient, so a lot can be stuck for
    much of the run and still show 0 in a single end-of-run scrape once
    recovery clears it. Peak values across these samples catch that.
    """
    samples_file = raw_dir / "mes_metrics_samples.jsonl"
    if not samples_file.exists():
        return []
    samples = []
    for line in samples_file.read_text().splitlines():
        if not line.strip():
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return samples


def main():
    run_date = sys.argv[1]
    raw_dir = Path("reports/raw") / run_date
    load_stats = load_locust_stats(raw_dir)

    mes_metrics_file = raw_dir / "mes_metrics.json"
    mes_metrics = json.loads(mes_metrics_file.read_text()) if mes_metrics_file.exists() else {}
    metrics_samples = load_metrics_samples(raw_dir)
    peak_lots_on_hold = max(
        (s.get("lots_on_hold_count", 0) for s in metrics_samples), default=None
    )
    hold_wait_samples = [
        s.get("longest_current_hold_seconds")
        for s in metrics_samples
        if s.get("longest_current_hold_seconds") is not None
    ]
    peak_hold_wait_seconds = max(hold_wait_samples) if hold_wait_samples else None
    quality_metrics_file = raw_dir / "quality_metrics.json"
    quality_metrics = (
        json.loads(quality_metrics_file.read_text()) if quality_metrics_file.exists() else {}
    )
    quality_anomalies_file = raw_dir / "quality_anomalies.json"
    quality_anomalies = (
        json.loads(quality_anomalies_file.read_text())
        if quality_anomalies_file.exists()
        else {}
    )
    equipment_file = raw_dir / "equipment.json"
    equipment = json.loads(equipment_file.read_text()) if equipment_file.exists() else []
    # MTBF/MTTR are None until a tool has logged at least one DOWN event
    # (see app.main._equipment_reliability) — only equipment that actually
    # failed during this run has real numbers here, so a quiet run can
    # legitimately show none.
    mttr_by_equipment = {
        eq["name"]: eq["mttr_seconds"] for eq in equipment if eq.get("mttr_seconds") is not None
    }
    mtbf_by_equipment = {
        eq["name"]: eq["mtbf_seconds"] for eq in equipment if eq.get("mtbf_seconds") is not None
    }
    # Factory-wide downtime totals grouped by `reason` (see
    # app.main._downtime_by_reason), summed across every tool. This is what
    # separates "Locust's own FAULT_INJECTION/STEP_FAULT_INJECTION tasks
    # caused N seconds of DOWN this run" from "the simulation's RANDOM_FAULT
    # caused M seconds" — the per-equipment MTBF/MTTR above blends both.
    downtime_by_reason: dict[str, dict] = {}
    for eq in equipment:
        for reason, stats in (eq.get("downtime_by_reason") or {}).items():
            agg = downtime_by_reason.setdefault(
                reason, {"count": 0, "closed_count": 0, "total_seconds": 0.0}
            )
            agg["count"] += stats.get("count", 0)
            agg["closed_count"] += stats.get("closed_count", 0)
            agg["total_seconds"] += stats.get("total_seconds", 0.0)
    for reason, agg in downtime_by_reason.items():
        agg["total_seconds"] = round(agg["total_seconds"], 1)
        agg["mean_seconds"] = (
            round(agg["total_seconds"] / agg["closed_count"], 1) if agg["closed_count"] else None
        )

    summary = {
        "date": run_date,
        "load_test": load_stats,
        "mes_metrics": mes_metrics,
        "mes_metrics_peak_during_run": {
            "sample_count": len(metrics_samples),
            "peak_lots_on_hold_count": peak_lots_on_hold,
            "peak_longest_hold_seconds": peak_hold_wait_seconds,
        },
        "quality_metrics": quality_metrics,
        "quality_anomalies": quality_anomalies,
        "equipment_reliability": {
            "equipment_with_recorded_failures": len(
                [eq for eq in equipment if eq.get("mtbf_seconds") is not None or eq.get("mttr_seconds") is not None]
            ),
            "mttr_seconds_by_equipment": mttr_by_equipment,
            "mtbf_seconds_by_equipment": mtbf_by_equipment,
            "downtime_seconds_by_reason": downtime_by_reason,
        },
    }

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / f"{run_date}.json").write_text(json.dumps(summary, indent=2))

    md = [f"# MES Daily Load Report - {run_date}", ""]
    md.append("## Load Test")
    if load_stats:
        md.append(f"- Requests: {load_stats['requests']}")
        md.append(f"- Failure rate: {load_stats['failure_rate'] * 100:.2f}%")
        md.append(f"- RPS: {load_stats['rps']:.2f}")
        md.append(f"- p95 latency: {load_stats['p95_ms']:.0f} ms")
        md.append(f"- p99 latency: {load_stats['p99_ms']:.0f} ms")
        md.append(f"- Expected state conflicts (409): {load_stats['business_conflicts']}")
        md.append(f"- Server 5xx: {load_stats['server_5xx']}")
        md.append(f"- Integrity errors: {load_stats['integrity_errors']}")
    else:
        md.append("- (no data)")

    md.append("")
    md.append("## Quality Anomalies")
    if quality_anomalies:
        anomalies = quality_anomalies.get("anomalies", [])
        md.append(f"- Method: {quality_anomalies.get('method')}")
        md.append(f"- Detected: {len(anomalies)}")
        for anomaly in anomalies:
            md.append(
                f"- {anomaly['equipment_name']}: {anomaly['severity']}, "
                f"defect rate {anomaly['defect_rate'] * 100:.2f}% vs "
                f"peer mean {anomaly['peer_mean_rate'] * 100:.2f}% "
                f"(n={anomaly['total_inspections']})"
            )
    else:
        md.append("- (no data)")

    md.append("")
    md.append("## Quality Metrics")
    if quality_metrics:
        md.append(f"- Total inspections: {quality_metrics.get('total_inspections')}")
        md.append(f"- First pass yield: {quality_metrics.get('first_pass_yield', 0) * 100:.2f}%")
        md.append(f"- Defect rate: {quality_metrics.get('defect_rate', 0) * 100:.2f}%")
        md.append(f"- Scrap count: {quality_metrics.get('scrap_count')}")
        md.append(f"- Rework count: {quality_metrics.get('rework_count')}")
        md.append(f"- Defects by equipment: {quality_metrics.get('defects_by_equipment')}")
    else:
        md.append("- (no data)")

    md.append("")
    md.append("## MES Business Metrics")
    if mes_metrics:
        md.append(f"- WIP: {mes_metrics.get('wip_count')}")
        md.append(f"- Completed today: {mes_metrics.get('completed_today')}")
        md.append(f"- Yield rate: {mes_metrics.get('yield_rate', 0) * 100:.2f}%")
        md.append(f"- Avg cycle time (s): {mes_metrics.get('avg_cycle_time_seconds')}")
        md.append(f"- Throughput/hr: {mes_metrics.get('throughput_per_hour')}")
        md.append(f"- Equipment utilization (s run): {mes_metrics.get('equipment_utilization')}")
        md.append(f"- Lots on equipment-down HOLD (end of run): {mes_metrics.get('lots_on_hold_count')}")
        md.append(
            f"- Longest current HOLD wait, end of run (s): "
            f"{mes_metrics.get('longest_current_hold_seconds')}"
        )
        md.append(
            f"- Peak lots on HOLD during run (of {len(metrics_samples)} samples): "
            f"{peak_lots_on_hold}"
        )
        md.append(f"- Peak HOLD wait observed during run (s): {peak_hold_wait_seconds}")
        md.append(
            f"- Avg resolved HOLD wait (s): {mes_metrics.get('avg_resolved_hold_seconds')}"
        )
        md.append(
            f"- OEE (Availability x Performance x Quality): "
            f"{mes_metrics.get('oee')}"
            f" (Availability={mes_metrics.get('oee_availability')}, "
            f"Performance={mes_metrics.get('oee_performance')}, "
            f"Quality={mes_metrics.get('oee_quality')})"
        )
    else:
        md.append("- (no data)")

    md.append("")
    md.append("## Equipment Reliability (MTBF/MTTR)")
    if equipment:
        md.append(
            f"- Equipment with recorded failures: "
            f"{summary['equipment_reliability']['equipment_with_recorded_failures']}/{len(equipment)}"
        )
        md.append(f"- MTTR by equipment (s): {mttr_by_equipment}")
        md.append(f"- MTBF by equipment (s): {mtbf_by_equipment}")
        md.append(f"- Downtime by reason, factory-wide: {downtime_by_reason}")
    else:
        md.append("- (no data)")

    (reports_dir / f"{run_date}.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
