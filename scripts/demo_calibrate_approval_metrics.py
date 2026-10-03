"""Calibration run for the approval-queue decision-quality metrics
(approval_rate, edit_rate, avg_decision_wait_seconds, fast_approval_rate --
see app/approvals.py::summary()).

Why this script exists
-----------------------
Those four metrics were added 2026-09-27 (PAR/ROADMAP) but every daily
50 VU/3min Locust run leaves them at `None`: the Locust scenario never starts
the autonomous simulation, so the rule-based agents never propose anything,
so nothing ever reaches the approval queue, so nothing ever gets *decided*.
ROADMAP's "다음 후보" and the HITL Notion hub's Stage 5 row both name the
same next step: run the simulation long enough, with scripted decisions, to
see real (non-None) numbers and judge whether `FAST_APPROVAL_THRESHOLD_SECONDS
= 5.0` is a sane cut line.

What this is NOT
-----------------
This does not make the system execute anything automatically. Deciding an
approval only writes a row (ApprovalRequest.status/decided_at/decided_by) --
it still never touches equipment or lot state (see app/approvals.py docstring).
The "decider" here is this script, not a real operator, so every decision is
recorded with decided_by="demo-calibration" (never a name that could be
mistaken for a real reviewer) and this file documents exactly when/why each
decision fires. This is a synthetic timing exercise to sanity-check a metric
definition, not a claim about real human approval behavior.

Usage
-----
    python scripts/demo_calibrate_approval_metrics.py [--base http://127.0.0.1:PORT]

Expects an isolated server already running at --base with the simulation
NOT yet started (the script starts it) and an otherwise-empty approval queue
(run against a fresh DB, not the daily load-test server).
"""

import argparse
import json
import time
import urllib.error
import urllib.request

POLL_INTERVAL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = 240.0


def call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def equipment_by_name(base):
    return {e["name"]: e for e in call(base, "GET", "/equipment")}


def toggle_down_up(base, equipment_id, times=4):
    for _ in range(times):
        call(base, "PATCH", f"/equipment/{equipment_id}/status", {"status": "DOWN", "reason": "FAULT_INJECTION"})
        call(base, "PATCH", f"/equipment/{equipment_id}/status", {"status": "IDLE", "reason": "FAULT_INJECTION"})


def pending_by_key(base):
    rows = call(base, "GET", "/approvals?status=PENDING")
    return {r["dedupe_key"]: r for r in rows}


def wait_for_key(base, key, deadline, label):
    while time.time() < deadline:
        pending = pending_by_key(base)
        if key in pending:
            return pending[key]
        time.sleep(POLL_INTERVAL_SECONDS)
    print(f"  [timeout] {label} (dedupe_key={key}) never appeared within the poll window")
    return None


def decide(base, approval_id, action, *, reason=None, edited_proposal=None):
    body = {"action": action, "decided_by": "demo-calibration"}
    if reason:
        body["reason"] = reason
    if edited_proposal:
        body["edited_proposal"] = edited_proposal
    return call(base, "POST", f"/approvals/{approval_id}/decision", body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:18300")
    args = ap.parse_args()
    base = args.base
    t0 = time.time()

    def log(msg):
        print(f"[{time.time() - t0:6.1f}s] {msg}")

    try:
        call(base, "POST", "/simulation/start")
    except urllib.error.HTTPError as e:
        if e.code != 409:
            raise
    log("simulation started (or already running)")

    eq = equipment_by_name(base)

    # Two distinct single-equipment downtime proposals (different equipment_id
    # => different dedupe_key => the control tower will not merge them).
    log(f"triggering equipment-downtime on {eq['ETCH-01']['name']} (target: MEDIUM, 4 DOWN/IDLE)")
    toggle_down_up(base, eq["ETCH-01"]["id"], times=4)
    log(f"triggering equipment-downtime on {eq['CMP-02']['name']} (target: MEDIUM, 4 DOWN/IDLE)")
    toggle_down_up(base, eq["CMP-02"]["id"], times=4)

    # Factory-wide concurrent-down (equipment_id=None -> merges by dedupe_key
    # only, so it cannot collide with the two proposals above regardless of
    # which tools it touches). Avoid ETCH-01/CMP-02/INSPECT-03 to keep each
    # proposal's evidence attributable to one scenario.
    concurrent_tools = [eq[n] for n in ("CVD-01", "CVD-02", "CVD-03", "INSPECT-01", "INSPECT-02")]
    log("triggering factory-wide concurrent-down (5 tools DOWN then IDLE, target: MEDIUM)")
    for e in concurrent_tools:
        call(base, "PATCH", f"/equipment/{e['id']}/status", {"status": "DOWN", "reason": "FAULT_INJECTION"})
    time.sleep(1)
    for e in concurrent_tools:
        call(base, "PATCH", f"/equipment/{e['id']}/status", {"status": "IDLE", "reason": "FAULT_INJECTION"})

    # Quality anomaly: needs ~10 real inspections to accumulate at this one
    # tool under the injected defect rate, so it is the slowest of the four.
    log(f"injecting defect-bias on {eq['INSPECT-03']['name']} (60% fail rate, needs ~10 inspections)")
    call(
        base, "POST", "/simulation/inject/defect-bias",
        {"equipment_id": eq["INSPECT-03"]["id"], "defect_rate": 0.6, "duration_seconds": 900},
    )

    deadline = time.time() + POLL_TIMEOUT_SECONDS
    results = {}

    # Proposals with an equipment_id are re-keyed by the control tower's merge
    # step to "control-tower:equipment:<id>" regardless of which agent proposed
    # them (see app/control_tower.py::_merge) -- only an equipment_id=None
    # proposal (factory-wide-down) keeps the agent's own dedupe_key. Found by
    # actually inspecting GET /approvals output: the agent-level keys
    # (equipment-down:<id>, quality-anomaly:<id>) never appear in the queue.
    def eq_key(equipment_id):
        return f"control-tower:equipment:{equipment_id}"

    # req A: decide the instant it is first observed PENDING -- the fastest a
    # script polling every 2s can simulate a rubber-stamp click.
    key_a = eq_key(eq["ETCH-01"]["id"])
    row = wait_for_key(base, key_a, deadline, "ETCH-01 downtime")
    if row:
        log(f"req A (ETCH-01 downtime, id={row['id']}) seen PENDING -> approving immediately")
        results["A"] = decide(base, row["id"], "approve")

    # req B: wait 20s of simulated review time, then approve with an edited
    # proposal (also the edit_rate sample).
    key_b = eq_key(eq["CMP-02"]["id"])
    row = wait_for_key(base, key_b, deadline, "CMP-02 downtime")
    if row:
        log(f"req B (CMP-02 downtime, id={row['id']}) seen PENDING -> reviewing for 20s, then approve+edit")
        time.sleep(20)
        results["B"] = decide(
            base, row["id"], "approve",
            edited_proposal=f"{eq['CMP-02']['name']} 점검 + 최근 FAULT_INJECTION 이력 로그 첨부해서 재확인 요청",
        )

    # req C: wait 15s, then reject -- honest reason: we caused this DOWN burst
    # ourselves for this calibration run, it is not a real correlated fault.
    key_c = "factory-wide-down"
    row = wait_for_key(base, key_c, deadline, "factory-wide concurrent-down")
    if row:
        log(f"req C (factory-wide concurrent-down, id={row['id']}) seen PENDING -> reviewing for 15s, then reject")
        time.sleep(15)
        results["C"] = decide(
            base, row["id"], "reject",
            reason="이 세션의 demo_calibrate_approval_metrics.py가 테스트용으로 수동 DOWN시킨 것이라 "
                   "실제 공통 원인 장애가 아님을 확인함",
        )

    # req D: wait 10s, then approve -- the slowest-to-appear signal (needs
    # accumulated inspections), so it naturally has the longest raw wait.
    key_d = eq_key(eq["INSPECT-03"]["id"])
    row = wait_for_key(base, key_d, deadline, "INSPECT-03 quality anomaly")
    if row:
        log(f"req D (INSPECT-03 quality anomaly, id={row['id']}) seen PENDING -> reviewing for 10s, then approve")
        time.sleep(10)
        results["D"] = decide(base, row["id"], "approve")

    call(base, "DELETE", "/simulation/inject/defect-bias")

    summary = call(base, "GET", "/approvals/summary")
    log("decisions recorded: " + ", ".join(f"{k}={v['status']}" for k, v in results.items()))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
