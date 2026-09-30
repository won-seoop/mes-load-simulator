"""Trigger the demo scenarios that put requests into the approval queue.

    python scripts/demo_approvals.py s1|s2|s3|s4 [--base http://127.0.0.1:8000]

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


def s4(base, step="ETCH", hold_seconds=100, isolate=False):
    """All tools on one process step stay DOWN long enough for the step-wide HOLD
    wait to cross rule:production-hold's MEDIUM tier (>=90s) -> QUEUE request
    (INSPECT_EQUIPMENT). Needs the simulation running so lots are actually queued
    at `step` and get HOLD'd once every tool on it is down (see app/production_agent.py).
    Unlike s1/s3, this scenario deliberately keeps the tools down (does not recover
    them immediately) — ROADMAP's "다음 후보" noted rule:production-hold had never
    been observed firing in a real run because every prior fault-injection scenario
    recovers each tool within a few seconds, well under its 30s lowest threshold.

    --isolate suppresses the engine's own background random equipment-down
    faults (via POST /simulation/inject/fault-rate, rate=0) for the duration of
    this scenario, so no *new* random DOWN starts once isolation is active.
    Without it (the default), the run stays realistic — a real factory does
    not pause unrelated random failures just because one step is down — but
    an unrelated rule (e.g. rule:equipment-downtime's factory-wide
    concurrent-down check) can coincidentally fire in the same window if the
    RNG happens to down other tools too (observed 2026-09-30, PAR-016); that
    is not a bug, just a second signal in the same demo run.
    Caveat measured 2026-10-01: isolation only blocks *new* random downs from
    the moment this call injects the override — a random DOWN that started in
    the seconds just before this call is unaffected and can still fall inside
    rule:equipment-downtime's 40s concurrent-down window together with this
    scenario's own DOWN calls, producing that same second proposal anyway. To
    fully isolate the signal, inject the override (or call this with
    --isolate) at least ~40s before starting the scenario, not only for its
    duration."""
    if isolate:
        out = call(base, "POST", "/simulation/inject/fault-rate",
                   {"rate": 0, "duration_seconds": hold_seconds + 30})
        print(f"S4: background random faults suppressed until {out['expires_at']}")
    tools = [e for e in equipment(base) if e["process_step"] == step]
    for eq in tools:
        call(base, "PATCH", f"/equipment/{eq['id']}/status", {"status": "DOWN", "reason": "FAULT_INJECTION"})
    print(f"S4: {step} tools DOWN ({', '.join(e['name'] for e in tools)}), "
          f"holding {hold_seconds:.0f}s so wait crosses the MEDIUM tier (90s)...")
    time.sleep(hold_seconds)
    for eq in tools:
        call(base, "PATCH", f"/equipment/{eq['id']}/status", {"status": "IDLE", "reason": "FAULT_INJECTION"})
    if isolate:
        call(base, "DELETE", "/simulation/inject/fault-rate")
        print("S4: background random faults restored")
    print(f"S4: {step} tools restored. Check GET /approvals for a rule:production-hold request.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=["s1", "s2", "s3", "s4"])
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--step", default="ETCH", help="s4 only: process step to hold down")
    ap.add_argument("--hold-seconds", type=float, default=100.0, help="s4 only: DOWN duration")
    ap.add_argument("--isolate", action="store_true",
                     help="s4 only: suppress background random equipment faults during the run")
    a = ap.parse_args()
    if a.scenario == "s4":
        s4(a.base, step=a.step, hold_seconds=a.hold_seconds, isolate=a.isolate)
    else:
        {"s1": s1, "s2": s2, "s3": s3}[a.scenario](a.base)
