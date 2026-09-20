# Target Architecture

## 원칙

- 즉시 확인이 필요한 Command와 확정 상태 이후 Event를 분리한다.
- 현재 상태와 변경 이력을 함께 유지한다.
- Broker는 Event Journal과 실패 재현이 완료된 뒤 도입한다.
- 실제 설비 대신 결정론적 Simulator를 사용한다.

## Architecture

```text
ERP / Plan Simulator
        │ Work Order Command
        ▼
┌─────────────────────────────────────────────┐
│ Manufacturing Operation                    │
│ Work Order / Lot / Route / Quality / WIP   │
│ State Transition / Interlock / Traceability│
└───────────────┬─────────────────────────────┘
                │ synchronous transaction
                ▼
       PostgreSQL (현재 SQLite)
       ├─ Current State
       ├─ Lot Event Journal
       ├─ Quality Inspection / Anomaly
       └─ Outbox (후속 Phase)
                │
                ▼
       Outbox Publisher (후속 Phase)
                │
                ▼
     Kafka 또는 RabbitMQ (실험 후 선택)
       ├─ KPI Consumer
       ├─ Quality Consumer
       ├─ Notification Consumer
       └─ Replay / DLQ

Equipment Simulator
        │ equipment event
        ▼
Machine Control Adapter
        │ validated event
        ▼
Equipment Event Ingestion
        └───────────────► Manufacturing Operation
```

## 동기 Command

- Work Order 생성/Release
- Lot 생성/Release
- 공정 시작 요청
- Interlock 확인
- Quality Hold/Release
- 중요 상태 변경

요청자는 성공/실패를 즉시 알아야 하며 DB Transaction과 Validation 결과를 반환한다.

## 비동기 Event

- 확정된 Lot/공정 상태 변경
- 설비 상태·알람·측정 데이터
- KPI 집계
- 외부 알림
- 분석용 이력 전달

비동기 처리는 명령 성공을 가장하거나 핵심 정합성 검사를 우회하지 않는다.

## 단계적 진화

1. SQLite Current State
2. Lot Event Journal
3. 명시적 State Machine과 동시성 테스트
4. PostgreSQL
5. Outbox
6. Broker 비교 실험
7. Idempotent Consumer / Retry / DLQ
8. Replay / Operations Dashboard

## Operator and Agent Access

```text
C# Avalonia Operator Console ──REST──► MES API
Claude / Codex Host ──MCP──► Read-only MES Gateway ──REST──► MES API
Independent Agents ──A2A Task/Artifact──► Agent Orchestrator (후속 Phase)
```

MCP/A2A는 Domain Event Broker를 대체하지 않는다. 현재 MCP는 조회만 제공하며 안전에 영향을 주는
생산 Command는 사용자 승인, 권한, Audit, Idempotency를 검증한 뒤 별도 Phase에서 검토한다.
