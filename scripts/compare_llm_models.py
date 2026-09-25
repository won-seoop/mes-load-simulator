"""Compare models for one role on the same facts, so the model choice is measured.

    ANTHROPIC_API_KEY=... python scripts/compare_llm_models.py \
        --role tower-advisor --models claude-sonnet-5 claude-opus-5-5 --runs 5

Nothing is written to any database. For each model it reports, over --runs calls
on the same fixed cases: how often the answer was usable, how often it cited a
number or equipment name that is not in the facts (ungrounded), how often it
escalated, latency and token usage. It does not compute cost, because prices
change: pass --price MODEL=INPUT,OUTPUT ($ per million tokens, from the model
docs) to get one. Results are a sample from a demo simulator, not a benchmark.
"""

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import llm_agent  # noqa: E402

# Fixed cases: (name, facts, what a careful analyst would conclude).
CASES = [
    (
        "repeat-down",
        {"scope": "ETCH-01", "current_risk": "MEDIUM", "agents": ["rule:equipment-downtime"],
         "action_kinds": ["INSPECT_EQUIPMENT"],
         "proposal_evidence": "최근 10분 내 DOWN 4회 (RANDOM_FAULT 4회)", "pending_requests_total": 2},
        "no strong reason to escalate",
    ),
    (
        "quality-plus-down",
        {"scope": "INSPECT-01", "current_risk": "HIGH",
         "agents": ["rule:quality-anomaly", "rule:equipment-downtime"],
         "action_kinds": ["STOP_NEW_DISPATCH", "INSPECT_EQUIPMENT"],
         "proposal_evidence": "불량률 50.0% vs 동료 평균 8.3% · 검사 12건 / 최근 10분 내 DOWN 5회",
         "pending_requests_total": 3},
        "two independent signals on one tool: escalation is defensible",
    ),
    (
        "factory-wide",
        {"scope": "공장 전체", "current_risk": "MEDIUM", "agents": ["rule:equipment-downtime"],
         "action_kinds": ["INSPECT_EQUIPMENT"],
         "proposal_evidence": "최근 40초 내 서로 다른 설비 5대 DOWN (CVD-01, CVD-02, ETCH-01, ETCH-02, ETCH-03)",
         "pending_requests_total": 1},
        "common cause suspected; cause itself cannot be determined from these facts",
    ),
]


def run(model: str, role: str, runs: int, max_tokens: int, price):
    from app.llm_agent import AnthropicClient

    client = AnthropicClient(os.environ["ANTHROPIC_API_KEY"], model, max_tokens)
    system = llm_agent.TOWER_SYSTEM_PROMPT if role == "tower-advisor" else llm_agent.SYSTEM_PROMPT
    rows = []
    for name, facts, _ in CASES:
        for _ in range(runs):
            started = time.perf_counter()
            try:
                text, tin, tout = client.complete(system, "Facts (JSON):\n" + json.dumps(facts, ensure_ascii=False))
            except Exception as exc:
                rows.append(dict(case=name, status="ERROR", detail=repr(exc)[:120]))
                continue
            latency = time.perf_counter() - started
            try:
                data = json.loads(text[text.index("{"): text.rindex("}") + 1])
                body = data.get("summary") or data.get("hypothesis") or ""
                reason = data.get("escalation_reason") or ""
                problem = llm_agent.grounding_problem(f"{body} {reason}", facts)
                status = "UNGROUNDED" if problem else "OK"
                escalate = bool(data.get("escalate"))
            except (ValueError, TypeError, AttributeError):
                status, escalate = "INVALID_OUTPUT", False
            cost = (tin * price[0] + tout * price[1]) / 1e6 if price and tin is not None and tout is not None else None
            rows.append(dict(case=name, status=status, escalate=escalate, latency=latency,
                             tin=tin, tout=tout, cost=cost))
    return rows


def summarize(model: str, rows: list[dict]) -> dict:
    n = len(rows)
    ok = [r for r in rows if r["status"] == "OK"]
    lat = [r["latency"] for r in rows if "latency" in r]
    costs = [r["cost"] for r in rows if r.get("cost") is not None]
    return {
        "model": model, "calls": n,
        "ok_rate": round(len(ok) / n, 3) if n else None,
        "ungrounded_rate": round(sum(r["status"] == "UNGROUNDED" for r in rows) / n, 3) if n else None,
        "invalid_rate": round(sum(r["status"] == "INVALID_OUTPUT" for r in rows) / n, 3) if n else None,
        "error_rate": round(sum(r["status"] == "ERROR" for r in rows) / n, 3) if n else None,
        "escalate_rate_by_case": {
            name: round(sum(1 for r in ok if r["case"] == name and r.get("escalate")) /
                        max(1, sum(1 for r in rows if r["case"] == name)), 3)
            for name, _, _ in CASES
        },
        "latency_median_s": round(statistics.median(lat), 2) if lat else None,
        "latency_max_s": round(max(lat), 2) if lat else None,
        "avg_output_tokens": round(statistics.mean(r["tout"] for r in rows if r.get("tout") is not None), 0)
        if any(r.get("tout") is not None for r in rows) else None,
        "cost_per_call_usd": round(statistics.mean(costs), 5) if costs else None,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=["root-cause", "tower-advisor"], default="tower-advisor")
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--max-tokens", type=int, default=llm_agent.DEFAULT_MAX_TOKENS)
    ap.add_argument("--price", action="append", default=[], help="MODEL=INPUT,OUTPUT  ($/M tokens)")
    a = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set")
    prices = {}
    for spec in a.price:
        m, v = spec.split("=")
        i, o = v.split(",")
        prices[m] = (float(i), float(o))
    out = [summarize(m, run(m, a.role, a.runs, a.max_tokens, prices.get(m))) for m in a.models]
    print(json.dumps(out, ensure_ascii=False, indent=2))
