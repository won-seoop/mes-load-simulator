import json
from datetime import datetime, timedelta

import pytest

from app import control_tower as ct
from app import llm_agent
from app.database import SessionLocal
from app.models import ApprovalRequest, EquipmentDowntimeEvent, LlmAgentRun
from app.simulation import SimulationEngine
from tests.test_control_tower import T0, _add_downs, _equipment, _proposal


class FakeClient:
    model = "fake-model"

    def __init__(self, *replies, error=None):
        self.replies = list(replies)
        self.error = error
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return self.replies.pop(0), 120, 45


def _ok(hypothesis="정지가 반복되어 점검이 필요해 보입니다.", action="INSPECT_EQUIPMENT", **extra):
    return json.dumps({"hypothesis": hypothesis, "recommended_action": action, **extra}, ensure_ascii=False)


@pytest.fixture()
def db(client):
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _rule(db, client, count=4):
    eq = _equipment(client, "ETCH-01")
    _add_downs(db, eq["id"], count)
    return eq, _proposal(
        source_agent="rule:equipment-downtime", equipment_id=eq["id"], equipment_name="ETCH-01",
        risk_level="MEDIUM", action_kind="INSPECT_EQUIPMENT", dedupe_key=f"equipment-down:{eq['id']}",
    )


def _runs(db):
    return db.query(LlmAgentRun).order_by(LlmAgentRun.id).all()


# -- root-cause agent -------------------------------------------------------

def test_disabled_client_adds_nothing(client, db):
    _, rule = _rule(db, client)
    assert llm_agent.propose(db, None, [rule], T0) == []
    assert _runs(db) == []


def test_get_client_is_off_without_flag_and_without_key(monkeypatch):
    monkeypatch.delenv("LLM_AGENT_ENABLED", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert llm_agent.get_client() is None
    monkeypatch.setenv("LLM_AGENT_ENABLED", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert llm_agent.get_client() is None


def test_valid_answer_becomes_a_proposal_with_the_rules_risk(client, db):
    eq, rule = _rule(db, client)
    fake = FakeClient(_ok(risk_level="CRITICAL"))  # the model tries to set risk: ignored

    out = llm_agent.propose(db, fake, [rule], T0)

    assert len(out) == 1
    p = out[0]
    assert p.source_agent == llm_agent.AGENT_NAME and p.equipment_id == eq["id"]
    assert p.risk_level == "MEDIUM" and p.action_kind == "INSPECT_EQUIPMENT"
    run = _runs(db)[0]
    assert (run.status, run.role, run.input_tokens, run.output_tokens) == ("OK", "root-cause", 120, 45)
    assert run.latency_ms is not None


def test_only_medium_and_above_rule_findings_are_sent_to_the_model(client, db):
    _, rule = _rule(db, client)
    low = _proposal(**{**rule.__dict__, "risk_level": "LOW"})
    fake = FakeClient(_ok())
    assert llm_agent.propose(db, fake, [low], T0) == [] and fake.calls == []


def test_invented_number_is_rejected_and_logged(client, db):
    _, rule = _rule(db, client)
    out = llm_agent.propose(db, FakeClient(_ok("최근 99회 정지했습니다.")), [rule], T0)
    assert out == []
    run = _runs(db)[0]
    assert run.status == "UNGROUNDED" and "99" in run.detail


def test_invented_equipment_name_is_rejected(client, db):
    _, rule = _rule(db, client)
    out = llm_agent.propose(db, FakeClient(_ok("CVD-09 설비의 영향으로 보입니다.")), [rule], T0)
    assert out == [] and _runs(db)[0].status == "UNGROUNDED"


def test_a_number_that_is_in_the_facts_is_accepted(client, db):
    _, rule = _rule(db, client, count=4)
    out = llm_agent.propose(db, FakeClient(_ok("최근 60분 동안 4회 정지했습니다.")), [rule], T0)
    assert len(out) == 1 and _runs(db)[0].status == "OK"


def test_malformed_output_is_logged_and_skipped(client, db):
    _, rule = _rule(db, client)
    assert llm_agent.propose(db, FakeClient("설명만 있고 JSON이 없습니다"), [rule], T0) == []
    assert _runs(db)[0].status == "INVALID_OUTPUT"


def test_client_error_never_raises_and_is_logged(client, db):
    _, rule = _rule(db, client)
    assert llm_agent.propose(db, FakeClient(error=TimeoutError("slow")), [rule], T0) == []
    run = _runs(db)[0]
    assert run.status == "ERROR" and "slow" in run.detail


def test_same_equipment_is_not_analyzed_again_inside_the_cooldown(client, db):
    _, rule = _rule(db, client)
    fake = FakeClient(_ok(), _ok())
    llm_agent.propose(db, fake, [rule], T0)
    assert llm_agent.propose(db, fake, [rule], T0 + timedelta(seconds=30)) == []
    assert len(fake.calls) == 1
    assert len(llm_agent.propose(db, fake, [rule], T0 + timedelta(seconds=llm_agent.COOLDOWN_SECONDS + 1))) == 1


def test_action_outside_the_whitelist_is_blocked_by_the_tower_without_hiding_the_rule(client, db):
    _, rule = _rule(db, client)
    out = llm_agent.propose(db, FakeClient(_ok(action="SHUTDOWN_FACTORY")), [rule], T0)
    assert len(out) == 1

    written = ct.process(db, [rule] + out, T0)

    assert sorted(w.disposition for w in written) == [ct.BLOCK, ct.QUEUE]
    assert db.query(ApprovalRequest).count() == 1  # the rule's request still reached a human


def test_rule_and_llm_proposals_merge_into_one_request(client, db):
    _, rule = _rule(db, client)
    out = llm_agent.propose(db, FakeClient(_ok()), [rule], T0)
    ct.process(db, [rule] + out, T0)
    row = db.query(ApprovalRequest).one()
    assert "rule:equipment-downtime" in row.source_agent and llm_agent.AGENT_NAME in row.source_agent


def test_runs_endpoint_lists_calls(client, db):
    _, rule = _rule(db, client)
    llm_agent.propose(db, FakeClient(_ok()), [rule], T0)
    rows = client.get("/llm-agent/runs").json()
    assert rows[0]["status"] == "OK" and rows[0]["model"] == "fake-model"


# -- control tower advisor ----------------------------------------------------

def _planned(db, client, count=4):
    _, rule = _rule(db, client, count)
    return ct.plan([rule])


def _advice(summary="같은 설비에서 정지가 반복되고 있습니다.", escalate=False, reason=""):
    return json.dumps({"summary": summary, "escalate": escalate, "escalation_reason": reason}, ensure_ascii=False)


def test_advisor_adds_a_summary_but_keeps_the_risk_by_default(client, db):
    planned = _planned(db, client)
    out = llm_agent.advise(db, FakeClient(_advice()), planned, T0)
    assert out[0].risk_level == "MEDIUM" and out[0].disposition == ct.QUEUE
    assert "[관제탑 AI 종합]" in out[0].evidence


def test_advisor_can_raise_the_risk_by_exactly_one_level(client, db):
    planned = _planned(db, client)
    out = llm_agent.advise(db, FakeClient(_advice(escalate=True, reason="정지 4회가 60분 안에 반복됨")), planned, T0)
    assert out[0].risk_level == "HIGH" and "MEDIUM→HIGH" in out[0].reason


def test_advisor_escalation_without_reason_is_ignored(client, db):
    planned = _planned(db, client)
    out = llm_agent.advise(db, FakeClient(_advice(escalate=True, reason="")), planned, T0)
    assert out[0].risk_level == "MEDIUM"
    assert _runs(db)[0].status == "UNGROUNDED"


def test_advisor_cannot_lower_risk_or_unblock(client, db):
    _, rule = _rule(db, client)
    blocked = ct.plan([_proposal(action_kind="SHUTDOWN_FACTORY", dedupe_key="x")])
    fake = FakeClient(_advice())
    out = llm_agent.advise(db, fake, blocked, T0)
    assert out == blocked and fake.calls == []  # BLOCK never reaches the model
    planned = ct.plan([rule])
    out = llm_agent.advise(db, FakeClient(_advice(escalate=False)), planned, T0)
    assert ct.RISK_ORDER[out[0].risk_level] >= ct.RISK_ORDER["MEDIUM"]


def test_advisor_low_risk_stays_recorded_unless_escalated_into_queue(client, db):
    _, rule = _rule(db, client, count=3)
    low = ct.plan([_proposal(**{**rule.__dict__, "risk_level": "LOW"})])
    assert low[0].disposition == ct.AUTO_RECORD
    out = llm_agent.advise(db, FakeClient(_advice(escalate=True, reason="정지 3회 반복")), low, T0)
    assert out[0].risk_level == "MEDIUM" and out[0].disposition == ct.QUEUE


def test_advisor_invented_number_leaves_the_decision_untouched(client, db):
    planned = _planned(db, client)
    out = llm_agent.advise(db, FakeClient(_advice("정지가 77회입니다.")), planned, T0)
    assert out == planned and _runs(db)[0].status == "UNGROUNDED"


def test_advisor_error_and_disabled_leave_decisions_untouched(client, db):
    planned = _planned(db, client)
    assert llm_agent.advise(db, None, planned, T0) == planned
    assert llm_agent.advise(db, FakeClient(error=RuntimeError("down")), planned, T0) == planned
    assert _runs(db)[0].status == "ERROR"


def test_advisor_reuses_its_answer_inside_the_cooldown_without_a_new_call(client, db):
    planned = _planned(db, client)
    fake = FakeClient(_advice(escalate=True, reason="정지 4회가 반복됨"))
    first = llm_agent.advise(db, fake, planned, T0)
    second = llm_agent.advise(db, fake, planned, T0 + timedelta(seconds=30))
    assert len(fake.calls) == 1
    assert second[0].risk_level == first[0].risk_level == "HIGH"
    assert "[관제탑 AI 종합]" in second[0].evidence


def test_process_with_advisor_queues_the_escalated_risk(client, db):
    _, rule = _rule(db, client)
    fake = FakeClient(_advice(escalate=True, reason="정지 4회가 반복됨"))
    ct.process(db, [rule], T0, advisor=lambda pl: llm_agent.advise(db, fake, pl, T0))
    row = db.query(ApprovalRequest).one()
    assert row.risk_level == "HIGH" and "관제탑 AI" in row.evidence


def test_simulation_survives_an_llm_failure_and_still_queues_the_rule_request(client, db, monkeypatch):
    _, rule = _rule(db, client)
    monkeypatch.setattr(llm_agent, "get_client", lambda role="root-cause": FakeClient(error=RuntimeError("api down")))
    engine = SimulationEngine()
    engine._propose_actions(db, [], T0)
    assert db.query(ApprovalRequest).count() == 1
    assert {r.status for r in _runs(db)} == {"ERROR"}


def test_each_role_gets_its_own_model_and_env_overrides_it(monkeypatch):
    for var in ("LLM_MODEL_ROOT_CAUSE", "LLM_MODEL_TOWER"):
        monkeypatch.delenv(var, raising=False)
    assert llm_agent.model_for("root-cause") == "anthropic:claude-sonnet-5"
    assert llm_agent.model_for("tower-advisor") == "anthropic:claude-opus-5-5"
    monkeypatch.setenv("LLM_MODEL_TOWER", "openai:gpt-6-sol")
    assert llm_agent.model_for("tower-advisor") == "openai:gpt-6-sol"
    assert llm_agent.model_for("root-cause") == "anthropic:claude-sonnet-5"


def test_build_client_picks_the_provider_and_needs_its_credentials(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_COMPAT_BASE_URL", "LLM_COMPAT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert llm_agent.build_client("anthropic:claude-sonnet-5") is None
    assert llm_agent.build_client("openai:gpt-6-sol") is None
    assert llm_agent.build_client("compat:gpt-oss-20b") is None
    assert llm_agent.build_client("nope:model") is None

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    c = llm_agent.build_client("openai:gpt-6-sol")
    assert isinstance(c, llm_agent.OpenAICompatClient) and c.model == "openai:gpt-6-sol"
    assert c._url == "https://api.openai.com/v1/chat/completions" and c._token_param == "max_completion_tokens"

    monkeypatch.setenv("LLM_COMPAT_BASE_URL", "http://127.0.0.1:11434/v1/")
    c = llm_agent.build_client("compat:gpt-oss-20b")
    assert c._url == "http://127.0.0.1:11434/v1/chat/completions" and c._key is None
    assert c._token_param == "max_tokens"


def test_bare_model_name_still_means_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    built = []

    class Spy:
        def __init__(self, key, model, max_tokens):
            built.append(model)
            self.model = model

    monkeypatch.setattr(llm_agent, "AnthropicClient", Spy)
    llm_agent.build_client("claude-sonnet-5")
    assert built == ["claude-sonnet-5"]


def test_get_client_builds_each_role_from_its_spec(monkeypatch):
    monkeypatch.setenv("LLM_AGENT_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("LLM_MODEL_ROOT_CAUSE", raising=False)
    monkeypatch.delenv("LLM_MODEL_TOWER", raising=False)
    built = []

    class Spy:
        def __init__(self, key, model, max_tokens):
            built.append((model, max_tokens))
            self.model = model

    monkeypatch.setattr(llm_agent, "AnthropicClient", Spy)
    llm_agent.get_client("root-cause")
    llm_agent.get_client("tower-advisor")
    assert [m for m, _ in built] == ["claude-sonnet-5", "claude-opus-5-5"]
    assert built[0][1] == llm_agent.DEFAULT_MAX_TOKENS


def _serve(handler_body):
    """A real local HTTP server speaking a minimal Chat Completions API."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(length))
            status, payload = handler_body(seen["body"])
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def test_compat_client_speaks_chat_completions_and_reads_usage():
    server, seen = _serve(lambda body: (200, {
        "choices": [{"message": {"content": _ok()}}], "usage": {"prompt_tokens": 77, "completion_tokens": 33}}))
    try:
        c = llm_agent.OpenAICompatClient("compat:m", f"http://127.0.0.1:{server.server_port}/v1", "secret", "m", 123)
        text, tin, tout = c.complete("SYS", "USER")
    finally:
        server.shutdown()
    assert (tin, tout) == (77, 33) and "hypothesis" in text
    assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer secret"
    body = seen["body"]
    assert body["model"] == "m" and body["max_tokens"] == 123
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "temperature" not in body  # reasoning models reject sampling options


def test_compat_client_without_key_sends_no_auth_header_and_http_errors_become_error_runs(client, db):
    server, seen = _serve(lambda body: (500, {"error": "boom"}))
    try:
        c = llm_agent.OpenAICompatClient("compat:m", f"http://127.0.0.1:{server.server_port}/v1", None, "m")
        _, rule = _rule(db, client)
        assert llm_agent.propose(db, c, [rule], T0) == []
    finally:
        server.shutdown()
    assert seen["auth"] is None
    run = _runs(db)[0]
    assert run.status == "ERROR" and run.model == "compat:m"
