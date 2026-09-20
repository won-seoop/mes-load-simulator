# ADR-005: Dispatch Count as the Primary Fairness Signal

## Status

Accepted — 2026-09-20

## Problem

설비별 `run_seconds`가 비슷해 보여 Dispatch가 균등하다고 판단했지만 EXP-004 DB를 장비별 검사 건수로
분해하자 `INSPECT-01=1`, `INSPECT-02=1`, `INSPECT-03=268`이었다. Simulator가 한 번 RUN이 된 설비를
계속 RUN으로 유지해 모든 설비의 Wall-clock Run Time이 비슷하게 증가했고, 마지막에 시작한 장비가
항상 최소값으로 남는 구조였다.

## Options

### A. Run Time 계산 또는 Tie-breaker만 미세 조정

- 실제 사용시간 기반 Dispatch 의도를 유지할 수 있다.
- 현재 Instant Process Simulator에서는 RUN 구간 자체가 실제 작업시간이 아니어서 같은 착시가 반복된다.

### B. Dispatch Count를 별도 저장해 1차 기준으로 사용

- 작업 배정 횟수를 직접 측정하고 Test할 수 있다.
- 작업시간이 다른 현실 공정에는 Count만으로 부하를 표현할 수 없다.

## Decision

현재 Simulator에서는 B를 선택한다. `(dispatch_count, effective_run_seconds, equipment_id)` 순으로
최소값을 선택한다. 추후 Process Duration Simulator가 생기면 Queue Length와 예상 완료시간을 포함한
Dispatch Rule을 별도 실험한다.

## Regression

한 공정의 3대 설비에 30개 LOT을 배정했을 때 `dispatch_count=[10,10,10]`을 검증한다. 가동시간만
비교하는 기존 Test는 배정 균등의 근거로 사용하지 않는다.
