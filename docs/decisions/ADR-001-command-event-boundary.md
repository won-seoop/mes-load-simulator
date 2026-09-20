# ADR-001: 동기 Command와 비동기 Event 경계

- 상태: Accepted
- 날짜: 2026-09-19
- 영향: High

## Context

현재 API는 요청 안에서 Lot 상태와 설비 상태를 직접 변경한다. 메시지 큐를 바로 도입하면 어떤 처리가
동기 결과를 보장해야 하고 어떤 처리가 지연되어도 되는지 불분명해진다.

## Options Considered

### A. 모든 변경 요청을 메시지 큐로 전달

장점:

- 요청 처리와 Worker를 분리할 수 있다.
- Burst를 Buffering할 수 있다.

단점:

- 작업 시작/Interlock 실패를 호출자가 즉시 알기 어렵다.
- 정합성과 응답 의미가 복잡해진다.
- 현재 규모에서는 운영 복잡도가 문제보다 크다.

### B. Command는 동기 Transaction, 확정 Event만 비동기 발행

장점:

- Validation과 상태 변경 성공/실패가 명확하다.
- Outbox로 DB 상태와 Event 기록의 원자성을 확보할 수 있다.
- 후속 Consumer는 독립적으로 확장할 수 있다.

단점:

- Command API DB 병목은 별도로 해결해야 한다.
- Outbox Publisher 운영이 추가된다.

## Decision

B를 선택한다.

현재 Phase에서는 Broker를 추가하지 않고 Lot Event Journal을 같은 DB Transaction에 저장한다. 이후
Direct Publish 실패를 재현한 뒤 Outbox와 Broker를 비교한다.

## Consequences

- 작업 시작, Interlock, 핵심 상태 변경은 동기 API로 유지한다.
- KPI, 알림, 분석, 외부 전달은 확정 Event의 비동기 Consumer 후보가 된다.
- Event Journal이 Traceability와 향후 Outbox의 기반이 된다.
