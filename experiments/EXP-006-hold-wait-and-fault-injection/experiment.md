# EXP-006 Equipment-Down HOLD Wait Visibility and Fault Injection Tuning

## Goal

`Lot.status == HOLD`가 로트의 대기 사실만 보여주고 언제부터 대기했는지는 보여주지 않는 문제를
Event Journal로 해결하고, 실제 부하테스트에서 그 값을 관측할 수 있는 Fault Injection 강도를
찾는다.

## Hypothesis

이미 기록 중인 `LOT_HELD`/`LOT_RELEASED_FROM_HOLD` 이벤트를 짝지으면 현재 대기시간과 과거 해소된
대기시간을 정확히 복원할 수 있다. 다만 기존 Locust 시나리오에는 설비 Down이 전혀 없어 이 값이
항상 비어 있을 것이므로, Fault Injection을 추가해야 한다. Fault Injection을 Task 가중치 1로 매번
실행하면(Gate 없음) 50명 동시 사용자 환경에서 너무 잦은 설비 전환을 일으켜 다른 핵심 지표(완료
로트, WIP)를 왜곡할 것이다.

## Problem Measurement (Baseline)

같은 날 EXP-005(품질 + Dispatch Fairness, Fault Injection 없음) 결과: 완료 로트 216건, WIP 2648건.

## Alternatives

- A: Fault Injection Task를 Gate 없이 매 선택마다 실행. 구현이 단순하지만 실측 결과 3분간 설비
  상태를 579회 전환시켜 완료 로트가 149건까지 떨어지고 702개 로트가 미해소 HOLD로 쌓였다.
  기존 가중치 체계(3/1/6/2/2/2)를 유지하는 장점만으로는 이 붕괴를 정당화할 수 없어 기각했다.
- B: Task 본문에 `FAULT_DOWN_PROBABILITY=0.05` 확률 Gate를 추가. 기존 가중치 체계를 그대로 두고
  강도만 상수 하나로 조절할 수 있어 채택했다.

## Result

### Run 1 — Gate 없음 (실패 사례로 보존)

- Requests 17,854, 실패 0%, RPS 99.18, p95 260ms/p99 620ms
- 설비 상태 변경(다운) 579회 / 복구 568회
- 완료 로트 149건, WIP 2255건
- 실행 종료 시점 `lots_on_hold_count=702`, `longest_current_hold_seconds=175.0`,
  `avg_resolved_hold_seconds=0.6`

### Run 2 — `FAULT_DOWN_PROBABILITY=0.05` (최종 채택)

- Requests 17,238~17,289, 실패 0%, RPS 95~96, p95 84~120ms/p99 230~320ms
- 설비 상태 변경(다운) 29~34회 / 복구 32~38회
- 완료 로트 207~219건, WIP 2369~2497건 (EXP-005 Baseline 216건/2648건과 같은 범위)
- 실행 종료 시점과 10초 간격 Peak 샘플 모두 `lots_on_hold_count=0`,
  `longest_current_hold_seconds=None`, `avg_resolved_hold_seconds=None` — 같은 공정 3대가
  동시에 DOWN되는 사례가 이 실행에서는 발생하지 않았다.

### 지표 계산 자체의 정확성 (pytest, freeze-time)

- 대기 0건 baseline → `lots_on_hold_count=0`, 나머지 `None`
- 진행 중 대기 330초 → `longest_current_hold_seconds=330.0`
- 해소된 대기 120초 → `avg_resolved_hold_seconds=120.0`, `lots_on_hold_count=0`으로 복귀

## Decision

`FAULT_DOWN_PROBABILITY=0.05`를 채택해 ROADMAP·PAR-004에 기록한다. 이 확률에서는 HOLD 대기시간
지표가 매 실행마다 실제 값을 갖지는 못하므로, 같은 공정의 설비를 한꺼번에 묶어 내리는 "스텝 전체
다운" Fault를 다음 후보로 남긴다. `run_daily_test.sh`의 10초 간격 `/metrics` 샘플러는 이번 실행처럼
값이 0/None일 때도 실행 종료 시점 스냅샷이 놓칠 수 있는 짧은 HOLD를 앞으로 계속 감시한다.
