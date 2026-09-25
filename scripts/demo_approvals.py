"""Trigger the demo scenarios that put requests into the approval queue.

    python scripts/demo_approvals.py s1|s2|s3 [--base http://127.0.0.1:8000]

The simulation must be running (POST /simulation/start); the agents check every
30 seconds, so a request shows up within about a minute (S2 needs ~10 inspections
per INSPECT tool first). All thresholds are demo values, not from public sources.
Scenario notes: Notion "시뮬레이션 시나리오".
"""

import argparse
import json
import time
import urllib.request


def call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or "null")


def equipment(base):
    return call(base, "GET", "/equipment")


def s1(base):
    """One tool goes DOWN 4 times inside 10 minutes -> MEDIUM request (INSPECT_EQUIPMENT)."""
    eq = next(e for e in equipment(base) if e["process_step"] == "ETCH")
    for _ in range(4):
        call(base, "PATCH", f"/equipment/{eq['id']}/status", {"status": "DOWN", "reason": "FAULT_INJECTION"})
        call(base, "PATCH", f"/equipment/{eq['id']}/status", {"status": "IDLE", "reason": "FAULT_INJECTION"})
    print(f"S1: {eq['name']} DOWN x4 injected")


def s2(base):
    """One INSPECT tool starts failing far more often than its peers -> HIGH/CRITICAL request (STOP_NEW_DISPATCH)."""
    eq = next(e for e in equipment(base) if e["process_step"] == "INSPECT")
    out = call(base, "POST", "/simulation/inject/defect-bias",
               {"equipment_id": eq["id"], "defect_rate": 0.6, "duration_seconds": 900})
    print(f"S2: {eq['name']} defect rate 60% until {out['expires_at']}")


def s3(base):
    """Five different tools go DOWN within 30 seconds -> MEDIUM factory-level request."""
    tools = equipment(base)[:5]
    for eq in tools:
        call(base, "PATCH", f"/equipment/{eq['id']}/status", {"status": "DOWN", "reason": "FAULT_INJECTION"})
    time.sleep(1)
    # Manually downed tools are not recovered by the simulation itself; restore them
    # right away. The DOWN events stay in the downtime history, which is what the agent reads.
    for eq in tools:
        call(base, "PATCH", f"/equipment/{eq['id']}/status", {"status": "IDLE", "reason": "FAULT_INJECTION"})
    print("S3: DOWN then IDLE injected on " + ", ".join(e["name"] for e in tools))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=["s1", "s2", "s3"])
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    a = ap.parse_args()
    {"s1": s1, "s2": s2, "s3": s3}[a.scenario](a.base)
