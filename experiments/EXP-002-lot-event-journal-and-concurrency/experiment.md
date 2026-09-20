# EXP-002 Lot Event Journal and Concurrent Transition Safety

## Goal

Lot의 생성, HOLD, 복구, 공정 완료, 최종 완료 이력을 Transaction 안에 저장하고, 동시 Advance에서도
Lot 상태와 Event Sequence가 어긋나지 않게 한다.

## Hypothesis

Lot 상태 변경과 Event Journal을 같은 Transaction에 저장하면 Traceability를 확보할 수 있다. 단,
상태 전이 권한을 먼저 원자적으로 획득하지 않으면 동시 요청에서 Event Sequence 충돌과 중복 공정
진행이 발생할 것이다.

## Problem

기존 시스템은 현재 상태만 저장해 Lot이 어떤 공정과 설비를 거쳤는지 복원할 수 없었다. Event Journal
첫 구현 후 부하 테스트에서는 27건의 500이 발생했다.

서버 로그의 공통 원인:

```text
sqlite3.IntegrityError: UNIQUE constraint failed:
lot_events.lot_id, lot_events.sequence_number
```

## Official MES Connection

Samsung SDS Nexplant MES 공식 자료가 공개한 WIP Management와 Production Tracking & Traceability 문제
영역을 참고했다. `LotEvent` Schema와 동시성 방식은 이 프로젝트의 자체 구현이다.

## Workload

- Locust 50 VU
- Spawn rate 5 users/s
- Duration 3 minutes
- Create/Advance/List/Metrics Random Mixed Tasks

## Environment

- Baseline: 2026-09-19 KST
- Result: 2026-09-20 KST
- Runtime: Python 3.11.5 / FastAPI / Uvicorn 단일 프로세스
- Database: SQLite
- Machine: 동일 MacBook Air
- 주의: 같은 Task 비율이지만 Random Request Sequence는 완전히 동일하지 않다.

## Baseline Implementation

- `LotEvent`에 Lot별 Sequence Unique Constraint 추가
- `MAX(sequence_number) + 1`로 다음 순번 계산
- Lot 상태 변경과 Event를 같은 Transaction에 Commit

## Failure Analysis

두 요청이 같은 Lot 상태와 같은 마지막 Sequence를 동시에 읽었다. 둘 다 다음 순번을 만들었고 먼저
Commit한 요청만 성공했다. 늦은 요청은 Unique Constraint에서 500이 됐다. 순번 재시도만 하면 늦은
요청도 공정을 한 단계 더 진행할 위험이 있으므로 상태 전이 전체를 보호해야 했다.

## Options Considered

### A. 프로세스 내부 Lot별 Lock

구현은 단순하지만 다중 Worker/Instance로 확장하면 Lock을 공유하지 못해 선택하지 않았다.

### B. DB 조건부 UPDATE

`lot_id + status + step_index`가 조회 당시 값과 같을 때만 다음 상태로 전이한다. DB가 원자적으로 한
요청만 성공시키며, 나머지는 409로 구분할 수 있어 선택했다.

### C. PostgreSQL Row Lock

실제 운영 확장 후보지만 현재 SQLite Baseline과 함께 바꾸면 개선 원인을 분리하기 어려워 후속
실험으로 남겼다.

## Result

| Metric | Before | After |
|---|---:|---:|
| Requests | 17,980 | 17,869 |
| HTTP Failures | 28 | 0 |
| Server 5xx | 27 | 0 |
| Expected 409 Conflicts | 구분 안 됨 | 34 |
| RPS | 100.20 | 99.50 |
| P95 Latency | 18 ms | 24 ms |
| P99 Latency | 57 ms | 49 ms |
| Integrity Error Responses | 27 | 0 |

핵심 정합성 문제와 500은 제거됐다. RPS는 0.69% 낮아졌고 P95는 6 ms 증가했으므로 성능이 전부
개선됐다고 주장하지 않는다. P99는 8 ms 감소했지만 Random Workload 변동이 있어 동시성 수정의 직접
효과로 단정하지 않는다.

## Regression Test

- 총 29 tests passed
- 동시 Advance 2개를 Barrier로 같은 상태에서 시작
- 결과: HTTP 200 한 건, 409 한 건
- 최종 공정 진행: 1단계
- `PROCESS_COMPLETED`: 1건

## Decision

Event Journal과 DB 조건부 상태 전이를 유지한다. 409는 예상 가능한 Business Conflict로 부하 통계에
별도 기록하며, 서버 5xx와 섞지 않는다.

## Next Action

Work Order와 명시적 Lot State Machine을 추가해 임의 Advance API를 생산지시 기반 흐름으로 확장한다.
이후 PostgreSQL에서 조건부 UPDATE와 Row Lock을 비교한다.

## Evidence

- Before: `reports/2026-09-19.json`, `reports/raw/2026-09-19/server.log`
- After: `reports/2026-09-20.json`, `reports/raw/2026-09-20/server.log`
- Tests: `tests/test_lot_events.py`
- Decision: `docs/decisions/ADR-002-lot-transition-concurrency.md`

