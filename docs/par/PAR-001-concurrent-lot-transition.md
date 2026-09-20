# PAR-001 동시 Lot 상태 전이 정합성 개선

## 1. 한줄 요약

Lot Event Journal 도입 후 동시 Advance에서 발생한 Sequence 충돌과 중복 공정 위험을 DB 조건부 상태
전이로 해결해 50 VU/3분의 27건 500을 0건으로 줄였다.

## 2. 문제가 뭐였는가?

동일 Lot을 여러 요청이 동시에 Advance하면 같은 Event Sequence를 생성해 Unique Constraint 위반으로
500이 발생했다. 첫 부하 테스트에서 17,980건 중 28건이 실패했고 그중 27건이 500이었다.

## 3. 왜 이 문제가 중요했는가?

MES의 Lot 이력은 생산실적, WIP, 품질 원인추적의 근거다. 동일 공정이 두 번 반영되거나 Event가
누락되면 Lot Trace와 실적수량이 함께 틀어진다.

```text
동시 상태 전이
→ 중복 공정 완료 가능성
→ Lot Trace 불일치
→ WIP/완료수량 오염
→ 품질 원인추적 신뢰도 저하
```

## 4. 원인이 뭐였는가?

로그에서 `lot_events(lot_id, sequence_number)` Unique Constraint 위반을 확인했다. 두 요청이 같은
Lot 상태와 `MAX(sequence_number)`를 읽고 모두 `+1`을 생성한 것이 직접 원인이었다.

## 5. A를 고민하였는데 왜 안 했는가?

프로세스 내부의 Lot별 Lock을 검토했다. 구현은 쉽지만 Worker나 Instance가 둘 이상이면 Lock을
공유하지 못해 Scale-out 환경에서 같은 문제가 재발한다. 포트폴리오의 확장 방향과 맞지 않아
선택하지 않았다.

## 6. B를 고민하였고 왜 적용했는가?

DB 조건부 UPDATE를 적용했다. 조회한 `status`와 `step_index`가 여전히 같을 때만 상태를 변경하므로
DB가 한 요청만 전이시킨다. 경쟁 요청은 409를 반환해 장애와 구분할 수 있고, 별도 분산 Lock 없이
현재 SQLite에서도 검증할 수 있어 선택했다.

## 7. 어떤 방식으로 검증했는가?

- Unit/Integration: 29 tests
- Concurrency Regression: Barrier로 두 요청을 동일 상태에서 동시 시작
- Load: Locust 50 VU, spawn 5/s, 3분, Create/Advance/List/Metrics 혼합
- Server Log: 5xx, IntegrityError 별도 검색
- Before/After: 2026-09-19과 2026-09-20 리포트 비교
- 제한: Random Task 순서는 완전히 동일하지 않다.

## 8. 개선된 수치적인 결과가 무엇이었는가?

| Metric | Before | After |
|---|---:|---:|
| HTTP Failures | 28 | 0 |
| Server 5xx | 27 | 0 |
| Integrity Error Responses | 27 | 0 |
| Expected 409 Conflicts | 구분 안 됨 | 34 |
| RPS | 100.20 | 99.50 |
| P95 | 18 ms | 24 ms |

정합성과 오류율은 개선됐지만 P95는 6 ms 증가했다. 이를 숨기지 않고 PostgreSQL 전환 시 다시 비교할
성능 Trade-off로 남겼다.

## 9. 재발 방지 대책

- `status + step_index` 조건부 UPDATE 유지
- 동시 Advance 회귀 테스트 유지
- 409 Business Conflict와 5xx를 부하 리포트에서 분리
- Event Sequence Unique Constraint 유지
- PostgreSQL 전환 시 다중 Worker 조건으로 동일 실험 반복

## Evidence

- Experiment: `EXP-002 Lot Event Journal and Concurrent Transition Safety`
- Test: `tests/test_lot_events.py::test_concurrent_advance_allows_only_one_state_transition`
- Before: `reports/2026-09-19.json`
- After: `reports/2026-09-20.json`
- Decision: `ADR-002`

