"""LLM root-cause agent: explains *why* a rule-based finding may have happened.

The rule-based agents stay the baseline. This agent runs only on equipment that
already has a MEDIUM+ rule proposal, and it may only add a hypothesis and pick
one allowed action. It never sets the risk level (that stays the rule's), never
decides thresholds, and never executes anything. Its proposal goes through the
same control tower and approval queue as every other agent.

Guards, because an LLM can invent things:
- it is given only facts computed from the database, and any number or
  equipment name in its answer that is not in those facts rejects the answer;
- an action outside the allowed list is still forwarded, so the control tower's
  whitelist blocks and records it;
- errors, timeouts and unusable output are logged and skipped; the rule-based
  path keeps working without it;
- disabled unless LLM_AGENT_ENABLED=1 and ANTHROPIC_API_KEY is set.
"""

import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Optional, Protocol

from sqlalchemy.orm import Session

from app.approvals import RISK_ORDER
from app.control_tower import (
    ALLOWED_ACTION_KINDS, AUTO_RECORD, BLOCK, QUEUE, QUEUE_MIN_RISK, PlannedDecision, Proposal,
)
from app.models import (
    Equipment,
    EquipmentDowntimeEvent,
    InspectionResult,
    ApprovalRequest,
    LlmAgentRun,
    QualityInspection,
)

logger = logging.getLogger("app.llm_agent")

AGENT_NAME = "llm:root-cause"
# Model per role, from the model-selection research (Anthropic model docs, 2026-09-25):
# - root-cause: a short single-chain explanation, so the fast middle tier (Sonnet 5).
# - tower-advisor: cross-agent synthesis where the operator wants the stronger model
#   (Opus 5.5). This is a chosen default, NOT a proven win: the literature shows no
#   controlled evidence that a larger model synthesizes better, so scripts/compare_llm_models.py
#   measures it before it is trusted.
# Detection itself (defect-rate and downtime rules) stays statistical and uses no LLM.
DEFAULT_MODELS = {"root-cause": "anthropic:claude-sonnet-5", "tower-advisor": "anthropic:claude-opus-5-5"}
MODEL_ENV = {"root-cause": "LLM_MODEL_ROOT_CAUSE", "tower-advisor": "LLM_MODEL_TOWER"}
# A model spec is "provider:model" (a bare name means anthropic):
#   anthropic:<model>  ANTHROPIC_API_KEY
#   openai:<model>     OPENAI_API_KEY, https://api.openai.com/v1
#   compat:<model>     any OpenAI-compatible server (Ollama, vLLM, LM Studio, a hosted gateway):
#                      LLM_COMPAT_BASE_URL (required), LLM_COMPAT_API_KEY (optional)
# Keeping the provider a config value lets the same cases be compared across vendors and
# lets a factory keep data on-premise by pointing a role at a local model.
# Adaptive thinking on the larger models spends output tokens before the answer text.
DEFAULT_MAX_TOKENS = 2000
# Demo values: do not analyze the same equipment again inside this window, to bound cost.
COOLDOWN_SECONDS = 300.0
REQUEST_TIMEOUT_SECONDS = 20.0
FACT_WINDOW_SECONDS = 3600.0

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_EQUIPMENT_NAME = re.compile(r"\b(?:ETCH|CVD|CMP|INSPECT)-\d+\b")

SYSTEM_PROMPT = (
    "You assist a manufacturing operator by explaining possible causes of an equipment finding. "
    "Use ONLY the facts in the user message. Never invent numbers, equipment names, or events. "
    "Every number you write must appear in the facts exactly as given. "
    "If the facts do not support a cause, say the cause cannot be determined from these facts. "
    "Answer in Korean, in at most three sentences. "
    "Reply with a single JSON object and nothing else: "
    '{"hypothesis": "<text>", "recommended_action": "<one of ' + "|".join(ALLOWED_ACTION_KINDS) + '>"}. '
    "You do not decide risk, thresholds or whether to act; a human approves every action."
)


class LlmClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> tuple[str, Optional[int], Optional[int]]:
        """Return (text, input_tokens, output_tokens)."""


class AnthropicClient:
    def __init__(self, api_key: str, model: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> None:
        import anthropic  # imported lazily so the app and tests work without the SDK

        self.model = f"anthropic:{model}"
        self._api_model = model
        self._max_tokens = max_tokens
        self._client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)

    def complete(self, system: str, user: str) -> tuple[str, Optional[int], Optional[int]]:
        msg = self._client.messages.create(
            model=self._api_model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return text, msg.usage.input_tokens, msg.usage.output_tokens


def model_for(role: str) -> str:
    """The configured "provider:model" spec for a role."""
    return os.environ.get(MODEL_ENV[role], DEFAULT_MODELS[role])


class OpenAICompatClient:
    """Chat Completions over plain HTTP: OpenAI itself and any compatible server.

    No SDK dependency. Only the model, messages and a token limit are sent, so
    reasoning models that reject temperature and other sampling options work."""

    def __init__(self, label: str, base_url: str, api_key: Optional[str], model: str,
                 max_tokens: int = DEFAULT_MAX_TOKENS, token_param: str = "max_tokens") -> None:
        self.model = label
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._api_model = model
        self._max_tokens = max_tokens
        self._token_param = token_param

    def complete(self, system: str, user: str) -> tuple[str, Optional[int], Optional[int]]:
        import urllib.request

        body = {
            "model": self._api_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            self._token_param: self._max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        req = urllib.request.Request(self._url, data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
        text = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage") or {}
        return text, usage.get("prompt_tokens"), usage.get("completion_tokens")


def build_client(spec: str) -> Optional[LlmClient]:
    """Client for a "provider:model" spec, or None when its credentials are missing."""
    provider, _, model = spec.partition(":")
    if not model:  # a bare model name means anthropic
        provider, model = "anthropic", spec
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        return AnthropicClient(key, model, max_tokens) if key else _missing("ANTHROPIC_API_KEY", spec)
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return _missing("OPENAI_API_KEY", spec)
        # Reasoning models take max_completion_tokens rather than max_tokens.
        return OpenAICompatClient(spec, "https://api.openai.com/v1", key, model, max_tokens, "max_completion_tokens")
    if provider == "compat":
        base = os.environ.get("LLM_COMPAT_BASE_URL")
        if not base:
            return _missing("LLM_COMPAT_BASE_URL", spec)
        return OpenAICompatClient(spec, base, os.environ.get("LLM_COMPAT_API_KEY"), model, max_tokens,
                                  os.environ.get("LLM_COMPAT_TOKEN_PARAM", "max_tokens"))
    logger.warning("unknown LLM provider in %r", spec)
    return None


def _missing(var: str, spec: str) -> None:
    logger.warning("%s is not set, so %s is unavailable", var, spec)
    return None


def get_client(role: str = "root-cause") -> Optional[LlmClient]:
    """None unless explicitly enabled; keys and endpoints come from the environment only."""
    if os.environ.get("LLM_AGENT_ENABLED") != "1":
        return None
    return build_client(model_for(role))


def build_facts(db: Session, equipment_id: int, now: datetime) -> dict:
    """Everything the LLM may cite, computed from the database (reproducible)."""
    eq = db.get(Equipment, equipment_id)
    since = now - timedelta(seconds=FACT_WINDOW_SECONDS)

    downs = (
        db.query(EquipmentDowntimeEvent)
        .filter(
            EquipmentDowntimeEvent.equipment_id == equipment_id,
            EquipmentDowntimeEvent.started_at >= since,
            EquipmentDowntimeEvent.started_at <= now,
        )
        .all()
    )
    facts: dict = {
        "equipment": eq.name,
        "process_step": eq.process_step,
        "status_now": eq.status.value if hasattr(eq.status, "value") else str(eq.status),
        "window_minutes": int(FACT_WINDOW_SECONDS // 60),
        "down_count_in_window": len(downs),
        "down_reasons": dict(Counter(d.reason for d in downs)),
    }

    def rate(rows):
        total = len(rows)
        fails = sum(1 for r in rows if r.result == InspectionResult.FAIL)
        return total, fails, (round(fails / total * 100, 1) if total else None)

    own = db.query(QualityInspection).filter(QualityInspection.equipment_id == equipment_id).all()
    peers = (
        db.query(QualityInspection)
        .filter(
            QualityInspection.process_step == eq.process_step,
            QualityInspection.equipment_id != equipment_id,
        )
        .all()
    )
    if own:
        total, fails, pct = rate(own)
        facts["inspections"] = total
        facts["inspection_failures"] = fails
        facts["defect_rate_pct"] = pct
        facts["defect_codes"] = dict(
            Counter(r.defect_code for r in own if r.result == InspectionResult.FAIL and r.defect_code)
        )
    if peers:
        _, _, pct = rate(peers)
        facts["peer_defect_rate_pct"] = pct
    return facts


def _numbers(text: str) -> set[str]:
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in _NUMBER.findall(text)}


def grounding_problem(hypothesis: str, facts: dict) -> Optional[str]:
    """Why this text cites something that is not in the facts, else None."""
    fact_text = json.dumps(facts, ensure_ascii=False)
    allowed = _numbers(fact_text)
    bad_numbers = sorted(n for n in _numbers(hypothesis) if n not in allowed)
    if bad_numbers:
        return f"numbers not in facts: {', '.join(bad_numbers)}"
    known = set(_EQUIPMENT_NAME.findall(fact_text))
    bad_names = sorted(set(_EQUIPMENT_NAME.findall(hypothesis)) - known)
    if bad_names:
        return f"equipment not in facts: {', '.join(bad_names)}"
    return None


@dataclass(frozen=True)
class _Parsed:
    hypothesis: str
    action: str


def _parse(text: str) -> Optional[_Parsed]:
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        data = json.loads(text[start:end])
        hypothesis = data["hypothesis"]
        action = data["recommended_action"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(hypothesis, str) or not hypothesis.strip() or not isinstance(action, str):
        return None
    return _Parsed(hypothesis.strip(), action.strip())


def _recently_analyzed(db: Session, equipment_id: int, now: datetime, role: str = "root-cause") -> bool:
    return (
        db.query(LlmAgentRun.id)
        .filter(
            LlmAgentRun.role == role,
            LlmAgentRun.equipment_id == equipment_id,
            LlmAgentRun.created_at >= now - timedelta(seconds=COOLDOWN_SECONDS),
        )
        .first()
        is not None
    )


def _log_run(
    db: Session, now: datetime, equipment_id: Optional[int], model: str, status: str,
    role: str = "root-cause", **fields,
) -> None:
    db.add(LlmAgentRun(created_at=now, equipment_id=equipment_id, model=model, status=status, role=role, **fields))
    db.commit()


def propose(
    db: Session, client: Optional[LlmClient], rule_proposals: list[Proposal], now: datetime
) -> list[Proposal]:
    if client is None:
        return []
    # One call per equipment, only where a rule already found something worth a human's time.
    targets: dict[int, Proposal] = {}
    for p in rule_proposals:
        if p.equipment_id is None or RISK_ORDER[p.risk_level] < RISK_ORDER[QUEUE_MIN_RISK]:
            continue
        best = targets.get(p.equipment_id)
        if best is None or RISK_ORDER[p.risk_level] > RISK_ORDER[best.risk_level]:
            targets[p.equipment_id] = p

    out: list[Proposal] = []
    for equipment_id, rule in sorted(targets.items()):
        if _recently_analyzed(db, equipment_id, now):
            continue
        facts = build_facts(db, equipment_id, now)
        user = "Facts (JSON):\n" + json.dumps(facts, ensure_ascii=False)
        started = time.perf_counter()
        try:
            text, tokens_in, tokens_out = client.complete(SYSTEM_PROMPT, user)
        except Exception as exc:  # network, timeout, auth: the baseline must keep working
            _log_run(db, now, equipment_id, client.model, "ERROR",
                     latency_ms=(time.perf_counter() - started) * 1000, detail=repr(exc)[:300])
            continue
        latency = (time.perf_counter() - started) * 1000
        usage = dict(latency_ms=latency, input_tokens=tokens_in, output_tokens=tokens_out)

        parsed = _parse(text)
        if parsed is None:
            _log_run(db, now, equipment_id, client.model, "INVALID_OUTPUT", detail=text[:300], **usage)
            continue
        problem = grounding_problem(parsed.hypothesis, facts)
        if problem:
            _log_run(db, now, equipment_id, client.model, "UNGROUNDED", hypothesis=parsed.hypothesis,
                     recommended_action=parsed.action, detail=problem, **usage)
            continue

        _log_run(db, now, equipment_id, client.model, "OK", hypothesis=parsed.hypothesis,
                 recommended_action=parsed.action, **usage)
        out.append(
            Proposal(
                source_agent=AGENT_NAME,
                equipment_id=equipment_id,
                equipment_name=rule.equipment_name,
                title=f"{rule.equipment_name} 원인 가설",
                proposal=f"{rule.equipment_name}: {parsed.action}",
                evidence=parsed.hypothesis,
                risk_level=rule.risk_level,  # the rule sets risk; the LLM never does
                action_kind=parsed.action,  # not validated here: the control tower's whitelist blocks it
                dedupe_key=f"llm-root-cause:{equipment_id}",
            )
        )
    return out


# ---------------------------------------------------------------------------
# Control tower advisor: the AI part *inside* the control tower.
# ---------------------------------------------------------------------------

TOWER_SYSTEM_PROMPT = (
    "You are the control tower analyst of a manufacturing MES. Several agents proposed actions for "
    "one equipment or the whole factory. Read the facts and write what the operator needs to decide. "
    "Use ONLY the facts given. Never invent numbers, equipment names or events; every number must "
    "appear in the facts exactly as given. Answer in Korean. Reply with a single JSON object only: "
    '{"summary": "<at most two sentences: what is happening and what evidence agrees or conflicts>", '
    '"escalate": <true only if the facts show the situation is worse than the current risk level, '
    'otherwise false>, "escalation_reason": "<why, using only the facts, or empty>"}. '
    "You can only raise attention; you cannot lower a risk, unblock anything, or approve any action."
)
_RISK_UP = {"LOW": "MEDIUM", "MEDIUM": "HIGH", "HIGH": "CRITICAL", "CRITICAL": "CRITICAL"}


def _apply_advice(d: PlannedDecision, summary: str, escalate: bool, reason: str) -> PlannedDecision:
    risk = _RISK_UP[d.risk_level] if escalate else d.risk_level
    disposition = QUEUE if RISK_ORDER[risk] >= RISK_ORDER[QUEUE_MIN_RISK] else AUTO_RECORD
    note = f" · 관제탑 AI: 위험도 {d.risk_level}→{risk} ({reason})" if risk != d.risk_level else ""
    evidence = (d.evidence + "\n" if d.evidence else "") + f"[관제탑 AI 종합] {summary}"
    return replace(d, risk_level=risk, disposition=disposition, evidence=evidence, reason=d.reason + note)


def advise(
    db: Session, client: Optional[LlmClient], planned: list[PlannedDecision], now: datetime
) -> list[PlannedDecision]:
    """Add an AI summary to each non-blocked decision and allow one risk step up.

    The deterministic plan stays the floor: BLOCK never reaches the model, the
    risk can only rise by one level, and the disposition is recomputed by the
    same rule the plan uses. Unusable answers leave the decision untouched."""
    if client is None:
        return planned
    result: list[PlannedDecision] = []
    for d in planned:
        if d.disposition == BLOCK:
            result.append(d)
            continue
        cached = (
            db.query(LlmAgentRun)
            .filter(
                LlmAgentRun.role == "tower-advisor",
                LlmAgentRun.status == "OK",
                LlmAgentRun.equipment_id == d.equipment_id if d.equipment_id is not None
                else LlmAgentRun.equipment_id.is_(None),
                LlmAgentRun.created_at >= now - timedelta(seconds=COOLDOWN_SECONDS),
            )
            .order_by(LlmAgentRun.id.desc())
            .first()
        )
        if cached is not None:  # inside the cooldown: reuse the last answer, no new call
            info = json.loads(cached.detail or "{}")
            result.append(_apply_advice(d, cached.hypothesis, bool(info.get("escalate")), info.get("reason", "")))
            continue

        facts: dict = {
            "scope": d.equipment_name or "factory",
            "current_risk": d.risk_level,
            "agents": list(d.contributing_agents),
            "action_kinds": list(d.action_kinds),
            "proposal_evidence": d.evidence,
            "pending_requests_total": db.query(ApprovalRequest)
            .filter(ApprovalRequest.status == "PENDING").count(),
        }
        if d.equipment_id is not None:
            facts["equipment_facts"] = build_facts(db, d.equipment_id, now)
        started = time.perf_counter()
        try:
            text, tokens_in, tokens_out = client.complete(
                TOWER_SYSTEM_PROMPT, "Facts (JSON):\n" + json.dumps(facts, ensure_ascii=False)
            )
        except Exception as exc:
            _log_run(db, now, d.equipment_id, client.model, "ERROR", role="tower-advisor",
                     latency_ms=(time.perf_counter() - started) * 1000, detail=repr(exc)[:300])
            result.append(d)
            continue
        usage = dict(latency_ms=(time.perf_counter() - started) * 1000,
                     input_tokens=tokens_in, output_tokens=tokens_out)
        try:
            data = json.loads(text[text.index("{"): text.rindex("}") + 1])
            summary, escalate = data["summary"], data["escalate"]
            reason = data.get("escalation_reason") or ""
            valid = isinstance(summary, str) and summary.strip() and isinstance(escalate, bool)
        except (ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            _log_run(db, now, d.equipment_id, client.model, "INVALID_OUTPUT", role="tower-advisor",
                     detail=text[:300], **usage)
            result.append(d)
            continue
        problem = grounding_problem(summary + " " + reason, facts)
        if problem or (escalate and not reason.strip()):
            _log_run(db, now, d.equipment_id, client.model, "UNGROUNDED", role="tower-advisor",
                     hypothesis=summary, detail=problem or "escalate without reason", **usage)
            result.append(d)
            continue
        _log_run(db, now, d.equipment_id, client.model, "OK", role="tower-advisor", hypothesis=summary.strip(),
                 detail=json.dumps({"escalate": escalate, "reason": reason}, ensure_ascii=False), **usage)
        result.append(_apply_advice(d, summary.strip(), escalate, reason))
    return result
