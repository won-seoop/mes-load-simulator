# MCP / A2A Agent Architecture

## 현재 Claude와 작업 상태 공유

현재 Claude와 Codex 사이에 실시간 Agent-to-Agent Session이 직접 연결된 것은 아니다. 대신 다음을
단일 기준으로 공유한다.

- Git: `CLAUDE.md`, 구현 코드, Experiment/ADR/PAR, Commit과 CI
- Notion: Project Overview, Roadmap, Experiment, Failure, Decision, PAR
- 측정 Artifact: `reports/`와 원본 `reports/raw/`

같은 저장소와 Notion을 보는 Agent는 마지막 Commit과 문서를 읽어 작업을 이어갈 수 있다. 직접 Task
위임·진행 상태 Stream·결과 Artifact 교환은 A2A 단계에서 추가한다.

## Protocol 역할 분리

[MCP 공식 Architecture](https://modelcontextprotocol.io/specification/2025-03-26/architecture)는
Host-Client-Server 구조에서 Server가 Resource, Tool, Prompt를 노출하고 Host가 권한과 보안 경계를
관리하도록 정의한다. FactoryFlow에서는 “Agent가 MES 데이터와 기능을 어떻게 안전하게 사용하나”에
MCP를 쓴다.

[A2A 공식 Specification](https://a2a-protocol.org/latest/specification/)은 Agent Card, Message,
Task, Artifact와 Task 상태/Streaming/Push Update를 정의한다. FactoryFlow에서는 “독립 Agent가 서로
어떤 작업을 위임하고 상태와 결과를 교환하나”에 A2A를 쓴다.

```text
Claude / Codex / Operator
          │
          │ MCP resource/tool
          ▼
FactoryFlow MCP Gateway (현재 read-only)
 ├─ mes://overview
 ├─ mes://lots/{lot_id}/trace
 ├─ get_quality_anomalies
 ├─ get_lot_trace
 └─ list_work_orders
          │ REST
          ▼
FastAPI MES ── SQLite/PostgreSQL
          │
          ├─ deterministic quality anomaly detector
          └─ Lot Event / Inspection trace

A2A Orchestrator (후속 Phase)
 ├─ Operations Agent
 ├─ Quality Investigation Agent
 ├─ Experiment Agent
 └─ Documentation Agent
          │ Task / Artifact / Status
          └────────► Claude 또는 Codex
```

## 현재 구현한 MCP 범위

`agent_gateway/server.py`는 공식 Python MCP SDK 2.x의 `MCPServer`를 사용한다.

- Overview와 LOT Trace를 Resource로 제공
- 이상탐지, LOT 추적, 작업지시 조회를 Tool로 제공
- MES Backend와 별도 Python Environment를 사용해 FastAPI의 기존 Dependency를 흔들지 않음
- 생산 상태를 바꾸는 Tool은 제공하지 않음

## 이상탐지와 Agent 책임

이상탐지는 LLM 판단이 아니라 MES가 계산한 재현 가능한 Baseline을 사용한다.

```text
Inspection Result
  → Equipment별 Total/Fail/Defect Rate
  → 같은 Process의 Peer Mean/Stddev
  → 최소 Sample + 절대 Rate 차이 + Z-score Guard
  → Anomaly Record
  → Agent가 Lot Trace/Work Order/Equipment Context 수집
  → 원인 가설과 확인 절차 제안
```

Agent가 할 일:

- 이상 장비의 관련 LOT와 검사 이력을 모은다.
- 수치와 Threshold를 인용해 현상을 설명한다.
- 원인 가설과 추가 확인 항목을 제안한다.
- Experiment/Failure/Decision 문서 초안을 만든다.

Agent가 자동으로 하면 안 되는 일:

- 근거 없이 이상 수치를 만든다.
- 설비를 정지/재가동한다.
- LOT을 Scrap/Rework 처리한다.
- Work Order를 Release/Cancel 한다.

위 Command는 Policy, 사용자 승인, Audit Log, Idempotency가 갖춰진 후 별도 MCP Tool로 검토한다.

## A2A 도입 순서

1. Agent Card와 Skill 정의만 작성
2. Quality Investigation read-only Task
3. Task 상태와 Artifact를 Git/Notion Experiment ID에 연결
4. Retry/Timeout/Idempotency/권한 Test
5. Operations와 Experiment Agent 추가
6. 사람 승인 없이는 생산 Command가 실행되지 않는 Policy Gate 검증

MCP와 A2A는 Message Broker 대체재가 아니다. 확정된 MES Domain Event 전달은 Outbox + Broker Phase에서
별도로 검증한다.
