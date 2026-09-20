# EXP-005 Dispatch Fairness and Quality Anomaly

## Goal

설비 가동시간이 아니라 실제 작업 배정이 균등한지 검증하고, 비교 가능한 표본에서 장비 연관 품질
이상을 재현 가능하게 탐지한다.

## Hypothesis

현재 `effective_run_seconds` 최소값 Dispatch는 RUN 상태를 지속하는 Instant Simulator에서 배정 횟수를
대표하지 못한다. `dispatch_count`를 1차 기준으로 쓰면 같은 공정 설비 간 표본이 균등해지고,
INSPECT-03에 주입한 불량률 상승을 Peer 비교로 탐지할 수 있다.

## Problem Measurement

EXP-004-after DB의 검사 배정은 `INSPECT-01=1`, `02=1`, `03=268`이었다. Run Time은 세 장비 모두
176~178초라 균등해 보였으므로 기존 Metric과 Regression Test가 문제를 숨겼다.

## Alternatives

- A: Run Time 계산/Tie-breaker 보정 — 실제 Duration이 없는 현재 Simulator에서는 같은 착시 가능.
- B: Dispatch Count 저장 후 Count, Run Time, ID 순으로 선택 — 배정 자체를 직접 측정 가능.

B를 선택했다. 실제 Process Duration이 추가되면 Queue Length/예상 완료시간 Rule과 다시 비교한다.

## Anomaly Baseline

장비별 Total/Fail/Defect Rate를 계산하고 같은 공정의 다른 장비를 Peer로 삼는다. 최소 10회 검사,
절대 불량률 차이 10%p, z-score 2.0을 Guard로 사용한다. Peer 분산이 0이면 양의 절대 차이 Guard를
사용한다. LLM은 이 판정에 관여하지 않는다.

## Result

- 검사 배정: `1/1/268` → `79/80/79`
- 전체 공정 Dispatch Count 편차: 각 공정 최대 1건
- 17,982 requests, 실패 0, 5xx 0, IntegrityError 0
- INSPECT-03: 79회 중 22회 실패, 불량률 27.85%
- Peer Mean: 0%, 판정: WARNING 1건
- 전체 Test 62개, C# UI Release Build 오류/경고 0
- MCP Tool Smoke Test가 동일 WARNING과 Threshold를 반환

부하 지연 p95 150ms/p99 370ms는 관찰값이다. Random Scheduling과 DB 상태가 달라 Dispatch 변경만의
인과적 성능 향상으로 주장하지 않는다.

## Decision

ADR-005, ADR-006, PAR-003에 연결한다. 다음은 이상 LOT Drill-down과 Agent Investigation Artifact다.
