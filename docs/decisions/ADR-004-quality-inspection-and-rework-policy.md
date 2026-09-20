# ADR-004: Explicit Quality Inspection and Bounded Rework

## Status

Accepted — 2026-09-20

## Problem

기존 수율은 LOT 완료 시 무작위 Scrap Flag를 넣어 계산했다. 어떤 공정·설비·검사에서 왜 불량이
발생했는지 추적할 수 없고 Rework Flow도 없었다.

## Options

### A. 완료 시 Random Scrap 유지

- 장점: 구현이 단순하고 Load 생성이 쉽다.
- 단점: 품질 이력, 원인추적, 재작업 의사결정을 검증할 수 없다.

### B. Inspection + Defect + Disposition State Machine

- 장점: PASS/FAIL, Defect Code, Equipment, Scrap/Rework를 실제 Event와 연결한다.
- 단점: 동시 검사, 중복 Disposition, 반복 Rework 정책이 필요하다.

## Decision

B를 선택했다. 마지막 공정 후 `QUALITY_HOLD`로 이동하고 검사 PASS 시에만 DONE으로 완료한다. FAIL은
Defect Code와 `PENDING` Disposition을 만들며 SCRAP 또는 REWORK를 명시적으로 선택한다.

초기 부하에서 같은 결함이 4차 검사까지 반복되는 무한 Rework 위험을 발견했다. 한 번의 교정 Rework만
허용하고 두 번째 실패에는 SCRAP만 허용한다. REWORK 요청을 조용히 SCRAP으로 바꾸지 않고 HTTP 409로
거부해 호출자가 의사결정을 명시하도록 한다.

## Verification

- 검사/Disposition/Rework/FPY Unit/Integration Test
- 동시 검사 충돌을 409로 분리
- 50 VU, 3분 EXP-004 전후 비교
- 수정 후 최대 검사차수 2, 3차 이상 검사 0건 확인
