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


def main():
    run_date = sys.argv[1]
    raw_dir = Path("reports/raw") / run_date
    load_stats = load_locust_stats(raw_dir)

    mes_metrics_file = raw_dir / "mes_metrics.json"
    mes_metrics = json.loads(mes_metrics_file.read_text()) if mes_metrics_file.exists() else {}
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

    summary = {
        "date": run_date,
        "load_test": load_stats,
        "mes_metrics": mes_metrics,
        "quality_metrics": quality_metrics,
        "quality_anomalies": quality_anomalies,
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
    else:
        md.append("- (no data)")

    (reports_dir / f"{run_date}.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
