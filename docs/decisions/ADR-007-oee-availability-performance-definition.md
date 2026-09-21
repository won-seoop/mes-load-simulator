# ADR-007: OEE Availability/Performance Definition Without a Shift Schedule

## Status

Accepted — 2026-09-22

## Problem

`equipment_utilization`(누적 RUN 시간)만으로는 "얼마나 오래 돌았는지"만 보이고 "얼마나 효율적으로
돌았는지"는 알 수 없었다. Samsung SDS Nexplant MES 공개 자료가 다루는 Equipment Engineering /
제조 KPI 영역(OEE = Availability x Performance x Quality)을 재현하려 했으나, 이 프로젝트에는
실제 Fab의 Shift Schedule, Planned Downtime, 실측 Ideal Cycle Time 스펙이 존재하지 않는다.
분모(Planned Production Time)와 Performance의 기준값(Ideal Cycle Time)을 어떻게 정의할지가
핵심 결정이었다.

## Options — Availability 분모

### A. Availability = RUN 시간 / (RUN + DOWN) 시간, IDLE 제외

- IDLE(작업 대기)을 계산에서 완전히 빼서 "실제로 일하고 있던 시간 대비 고장 시간"만 본다.
- 이 Simulator는 부하가 낮을 때 IDLE 비중이 커서, IDLE이 늘어날수록 분모가 줄어 Availability가
  실제 설비 상태와 무관하게 출렁인다 — 설비가 멀쩡히 대기 중인데도 "가용성이 나쁘다"처럼 보일
  위험이 있다.

### B. Availability = (전체 경과시간 - DOWN 시간) / 전체 경과시간 (IDLE 포함)

- IDLE은 "고장이 아니라 작업이 없어서 쉬는 것"이라는 이 프로젝트의 상태 정의(`EquipmentStatus`
  주석)와 일치한다. DOWN만 손실로 계산하므로 Equipment Engineering이 실제로 추적하고 싶은
  "고장으로 얼마나 못 썼는가"를 직접 answer한다.
- Shift Schedule이 없어 분모가 "설비 생성 이후 누적 전체 시간"이 된다 — 서버가 오래 켜져 있을수록
  초기의 짧은 DOWN 한 번의 영향이 희석된다는 한계가 있다(문서화하고 받아들임).

## Decision — B를 선택

DOWN 상태의 의미(설비 고장)와 IDLE 상태의 의미(작업 대기)가 이미 `EquipmentStatus`로 구분되어
있으므로, Availability도 그 구분을 그대로 반영해야 한다. `run_seconds`와 대칭인 `down_seconds`를
추가하고(`set_equipment_status`에서 DOWN을 벗어날 때 flush), `Equipment.created_at`을 관측 시작
시점으로 사용한다.

## Options — Performance 기준값

### A. `LotEvent`에서 실측 평균 처리시간을 계산

- 실제 측정값이라 더 정확하다.
- 현재 이벤트 저널에는 `PROCESS_COMPLETED`만 있고 `PROCESS_STARTED`가 없어서, 한 공정 Step에
  실제로 얼마나 머물렀는지(대기시간 vs 처리시간)를 구분할 데이터가 없다. 이 값을 만들려면
  이벤트 모델을 먼저 확장해야 한다 — 오늘 범위를 벗어난다.

### B. 자율 시뮬레이션 엔진의 설계 목표값(`step_dwell_min/max_seconds`, 기본 6~14초) 중간값 사용

- 이 프로젝트에 이미 존재하는, 유일하게 "설계된 목표 처리시간"이다. Locust 부하테스트는 이
  dwell 타이머가 없지만, 같은 기준값을 Performance의 분자(Ideal Cycle Time)로 두어 두 트래픽
  소스를 같은 잣대로 비교할 수 있다.
- 실제 Fab Recipe Time이 아니라 이 프로젝트가 임의로 설계한 값이므로, 실제 처리능력 스펙으로
  오인되지 않도록 코드 주석과 문서에 "measured가 아니라 designed target"임을 명시해야 한다.

## Decision — B를 선택, A는 후속 과제로 남김

`OEE_IDEAL_CYCLE_SECONDS = 10.0`을 `app/main.py`에 상수로 선언하고 주석으로 근거와 한계를
명시한다. `PROCESS_STARTED` 이벤트를 추가해 실측값과 비교하는 것을 ROADMAP 다음 후보로 남긴다.

## Quality는 설비별로 만들지 않는다

검사 합/불 데이터는 INSPECT 설비에만 존재하므로, ETCH/CVD/CMP 설비에 Quality 값을 부여하면
지어낸 숫자가 된다. Quality는 공장 전체 수준(`yield_rate`)에서만 계산하고, 3요소 완전한 "OEE"도
공장 전체에서만 계산한다. 설비별 응답(`GET /equipment`)에는 `availability`/`performance`만
노출하고 `oee`라는 이름을 붙이지 않는다.

## Regression

- `tests/test_oee.py`: Availability/Performance 각 공식(정상, DOWN 반영, 캡핑, 미배정 시 `None`),
  `set_equipment_status`가 DOWN 이탈 시 `down_seconds`를 flush하는지, `/equipment`·`/metrics`
  응답 배선을 고정한다.
- 데이터가 없는 값(한 번도 배정되지 않은 설비의 Performance)은 0이 아니라 `None`으로 유지한다.
