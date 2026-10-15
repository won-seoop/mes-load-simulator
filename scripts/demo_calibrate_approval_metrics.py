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

This run also covers all three rule-based agents, not just two. Until
2026-10-15 this script only ever produced decided samples for
`rule:equipment-downtime` (reqs A/B/C) and `rule:quality-anomaly` (req D) --
`rule:production-hold` (app/production_agent.py) never appeared, so
`GET /approvals/summary`'s `by_agent` stayed without that key on every daily
report (ROADMAP "다음 후보"). Req E below reproduces the same step-wide
ETCH downtime that PAR-016 (2026-09-30) first observed firing
`rule:production-hold` in real time, then decides it, so all three agents
have at least one decided sample.

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
(run against a fresh DB, not the daily load-test server). Takes roughly
3-4 minutes end to end, mostly req E's ~165s isolation/hold/poll window.
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


def trigger_and_decide_production_hold(base, eq, log, step="ETCH", hold_seconds=110.0):
    """req E: hold every tool on one process step DOWN long enough for
    rule:production-hold's own HOLD-wait measurement to cross its MEDIUM tier
    (>=90s, app/production_agent.py HOLD_RISK_TIERS), then decide it.

    Mirrors scripts/demo_approvals.py's `s4` scenario (same technique PAR-016
    used to observe this agent fire for the first time) instead of importing
    it directly, because this script intentionally runs as a single
    self-contained file against an isolated server.

    Runs first, before reqs A-D, and fully recovers the step before
    returning -- so by the time A-D touch ETCH-01/CMP-02/CVD/INSPECT, this
    phase has already been decided and cleaned up and cannot merge with or
    shadow their proposals.
    """
    tools = [eq[f"{step}-0{i}"] for i in (1, 2, 3)]

    # Suppress the engine's own background random equipment-down faults so a
    # coincidental DOWN on another tool cannot blur which signal caused which
    # proposal (demo_approvals.py's s4 --isolate documents the same need).
    # Inject well before downing the step's own tools: isolation only blocks
    # *new* random downs from the moment of injection, not ones already in
    # flight (caveat recorded 2026-10-01 on s4).
    isolate_settle = 40.0
    queue_buildup = 15.0
    total_duration = isolate_settle + queue_buildup + hold_seconds + 30.0
    call(base, "POST", "/simulation/inject/fault-rate", {"rate": 0, "duration_seconds": total_duration})
    log(f"req E setup: background random faults suppressed for {total_duration:.0f}s")
    time.sleep(isolate_settle)

    log(f"req E setup: waiting {queue_buildup:.0f}s for lots to queue at {step} before cutting it off")
    time.sleep(queue_buildup)

    log(f"req E: {step} tools DOWN ({', '.join(t['name'] for t in tools)}), "
        f"holding {hold_seconds:.0f}s so the step-wide HOLD wait crosses MEDIUM (90s)")
    for t in tools:
        call(base, "PATCH", f"/equipment/{t['id']}/status", {"status": "DOWN", "reason": "FAULT_INJECTION"})
    time.sleep(hold_seconds)

    key_e = f"production-hold:{step}"
    deadline = time.time() + 60.0
    row = wait_for_key(base, key_e, deadline, f"{step} production-hold")

    for t in tools:
        call(base, "PATCH", f"/equipment/{t['id']}/status", {"status": "IDLE", "reason": "FAULT_INJECTION"})
    call(base, "DELETE", "/simulation/inject/fault-rate")
    log(f"req E: {step} tools restored, background faults re-enabled")

    if not row:
        return None
    log(f"req E ({step} production-hold, id={row['id']}) seen PENDING -> reviewing for 5s, then approve")
    time.sleep(5)
    return decide(
        base, row["id"], "approve",
        reason=f"{step} 공정 설비 점검 지시 승인 (이 세션의 보정 실행이 테스트용으로 전체 DOWN시킨 것)",
    )


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

    result_e = trigger_and_decide_production_hold(base, eq, log)

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

    if result_e:
        results["E"] = result_e

    summary = call(base, "GET", "/approvals/summary")
    log("decisions recorded: " + ", ".join(f"{k}={v['status']}" for k, v in results.items()))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
