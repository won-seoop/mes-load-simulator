# EXP-004 Quality Traceability and Bounded Rework

## Goal

무작위 Scrap Flag를 실제 검사·불량·Disposition·재작업 이력으로 교체하고 반복 실패가 WIP를 무한히
증가시키지 않는지 검증한다.

## Hypothesis

마지막 공정 뒤 명시적 `QUALITY_HOLD`와 검사 이력을 만들면 품질 수치가 LOT/Event/Equipment까지
추적된다. 단, Rework 횟수 제한이 없으면 지속 결함이 무한 Loop를 만들 수 있다.

## Baseline

완료 LOT에 Random Scrap Flag를 부여했다. 검사 시점, Defect Code, 원인 장비, Disposition은 없었다.

## Implementation

- `QUALITY_HOLD`, `REWORK`, `SCRAPPED` 상태와 허용 전이
- `QualityInspection`: 시도차수, 공정, 설비, 결과, Defect Code, Disposition
- PASS 완료, FAIL 후 SCRAP/REWORK, Rework Release API
- FPY, 불량률, Scrap/Rework, 공정/설비별 불량 지표
- 동시 검사는 조건부 UPDATE로 한 요청만 확정하고 나머지는 409

## Failure Case

첫 50 VU/3분 실행에서 같은 `INSPECT_SENSOR_DRIFT` 조건이 Rework 후에도 계속 발생했다. DB에는 3차
검사 4건, 4차 검사 1건이 남았고 Scrap은 0건이었다. Load Client의 실패 LOT가 항상 짝수 ID라
Disposition도 항상 REWORK가 되는 조건까지 겹쳤다.

## Alternatives

- A: Rework를 무제한 허용 — 현장 판단 유연성은 있지만 지속 결함이 WIP를 무한히 만든다.
- B: 최대 1회 Rework, 두 번째 실패는 SCRAP만 허용 — 현재 Simulator에 명확하고 Test 가능하다.

B를 선택했다. 서버는 두 번째 REWORK를 409로 거부하고 호출자가 SCRAP을 명시하도록 한다.

## Result

동일 50 VU/3분 재측정에서 18,050 requests, 실패 0, 5xx 0, IntegrityError 0이었다. 최대 검사차수는
4 → 2, 3차 이상 검사는 5 → 0이 됐다. Scrap 10건이 실제 수율에 반영됐다. p95 170 → 180ms는
개선되지 않았으며 Rework 정책의 성공 근거로 사용하지 않는다.

## Regression

- 62개 전체 Test 중 품질 Flow, 중복 검사, 재작업 후 재검사, 두 번째 Rework 거부 포함
- 고유 `(lot_id, attempt_number)` 제약
- Load Report에서 5xx/IntegrityError/예상 409 분리

## Decision

ADR-004와 PAR-002에 연결한다. 다음 실험에서 장비별 실제 검사 배정 건수를 확인한다.
