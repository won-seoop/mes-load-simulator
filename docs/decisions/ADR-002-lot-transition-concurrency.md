# ADR-002: Lot 상태 전이 동시성 제어

- 상태: Accepted
- 날짜: 2026-09-20
- 영향: High

## Context

Lot Event Journal을 추가한 뒤 50 VU/3분 부하에서 동일 Lot을 두 요청이 동시에 조회했다. 두 요청은
모두 같은 `step_index`와 Event `MAX(sequence_number)`를 기준으로 진행했고, 27건이 Event Sequence
Unique Constraint 충돌로 500을 반환했다. Event 순번만 재시도하면 같은 Lot이 한 공정을 두 번 통과할
수 있어 상태 정합성 문제를 숨기게 된다.

## Options Considered

### A. 애플리케이션 프로세스의 Lot별 Lock

장점:

- 현재 단일 프로세스에서 구현이 단순하다.
- 충돌 요청을 직렬화할 수 있다.

단점:

- 다중 Worker/Instance에서는 Lock을 공유하지 못한다.
- 프로세스 재시작과 Scale-out에서 정합성 근거가 사라진다.

### B. DB 조건부 UPDATE 기반 낙관적 상태 전이

`lot_id + expected_status + expected_step_index`가 여전히 일치할 때만 다음 상태를 저장한다.

장점:

- 상태 변경 권한을 DB에서 원자적으로 획득한다.
- 별도 분산 Lock 없이 다중 요청 충돌을 감지한다.
- 충돌을 500이 아닌 409로 명확히 표현한다.

단점:

- 호출자가 409를 재조회/재시도 정책으로 처리해야 한다.
- 고경합 환경에서는 PostgreSQL과 격리수준을 포함한 추가 검증이 필요하다.

### C. PostgreSQL `SELECT FOR UPDATE`

장점:

- 행 단위 Pessimistic Lock으로 전이를 직렬화할 수 있다.

단점:

- 현재 SQLite Baseline에서는 같은 방식으로 검증할 수 없다.
- 이번 문제 하나를 위해 DB 전환까지 묶으면 원인과 개선 효과를 분리하기 어렵다.

## Decision

B를 선택한다. 상태 전이를 획득한 요청만 Equipment와 Lot Event를 같은 Transaction에 저장하고,
경쟁에서 진 요청은 `409 Conflict`를 반환한다. PostgreSQL 전환 후 B와 C를 별도 실험한다.

## Validation

- 동시 요청 2개를 Barrier로 같은 상태에서 출발시킨 회귀 테스트: `200` 1건, `409` 1건
- 최종 `step_index`: 1
- `PROCESS_COMPLETED` Event: 1건
- 50 VU/3분: 17,869 requests, 0 failures, 34 expected conflicts, 0 server 5xx

