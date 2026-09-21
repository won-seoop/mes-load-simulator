# PAR-005 Shift Schedule 없이 OEE(Availability x Performance x Quality) 정의하기

1. 한줄 요약

누적 RUN 시간(`equipment_utilization`)만으로는 답할 수 없던 "얼마나 효율적으로 돌았는가"를
DOWN 시간 누적과 설계 목표 Cycle Time을 추가해 OEE로 계산했고, 검사 데이터가 없는 세 공정
설비에 Quality를 지어내지 않기 위해 3요소 완전한 OEE는 공장 전체 수준에서만 노출했다.

2. 문제가 뭐였는가?

`GET /equipment`와 `/metrics`는 설비별 누적 RUN 시간과 배정 횟수만 보여줬다. 두 설비의
RUN 시간이 같아도 하나는 계속 고장 나서 겨우 그 시간을 채운 것이고 다른 하나는 한 번도
멈추지 않고 채운 것일 수 있는데, 이 차이를 구분할 지표가 전혀 없었다.

3. 왜 이 문제가 중요했는가?

Samsung SDS Nexplant MES가 공개적으로 다루는 Equipment Engineering / 제조 KPI 영역의 핵심이
OEE다. OEE 없이는 "설비가 오래 켜져 있었다"와 "설비가 효율적으로 생산했다"를 구분할 수 없고,
Dispatching 개선(ADR-005)이나 HOLD 대기시간 개선(PAR-004)의 효과를 하나의 종합 지표로
추적할 수 없다. 또한 OEE Quality를 설비별로 억지로 만들면 검사 데이터가 없는 ETCH/CVD/CMP
설비에 대해 지어낸 숫자를 근거로 잘못된 의사결정(예: 실제로는 측정된 적 없는 설비를 "불량률
낮음"으로 오해)을 유도할 위험이 있었다.

4. 원인이 뭐였는가?

`Equipment` 모델에 `run_seconds`만 있고 그 대칭인 `down_seconds`가 없어서 Availability의
분자(손실 시간)를 계산할 데이터 자체가 없었다. 또한 이 프로젝트에는 Shift Schedule이나 실제
Recipe Time 스펙이 없어 OEE 공식의 "Planned Production Time"과 "Ideal Cycle Time"을 무엇으로
정의할지가 정해져 있지 않았다.

5. A를 고민하였는데 왜 안 했는가?

Availability 분모에서 IDLE(작업 대기)까지 손실로 계산하는 방식(RUN / (RUN+DOWN), IDLE 완전
제외)을 검토했으나, 이 프로젝트의 `EquipmentStatus` 정의상 IDLE은 "작업이 없어서 쉬는 것"이지
고장이 아니다. 부하가 낮아 IDLE이 늘어날 때마다 Availability가 실제 설비 상태와 무관하게
나빠 보이는 결과가 나와 채택하지 않았다(ADR-007 참고). Performance도 `LotEvent`에서 실측 평균
처리시간을 계산하는 방법을 검토했지만, 현재 이벤트 저널에는 `PROCESS_COMPLETED`만 있고
`PROCESS_STARTED`가 없어 대기시간과 처리시간을 구분할 데이터가 없어 오늘 범위에서는
포기했다.

6. B를 고민하였고 왜 적용했는가?

Availability = (전체 경과시간 - DOWN 시간) / 전체 경과시간(IDLE 포함, DOWN만 손실)을
적용했다. `down_seconds`를 `run_seconds`와 똑같은 패턴(현재 상태를 벗어날 때 flush)으로
추가했으므로 기존 코드와 일관되고 검증하기 쉬웠다. Performance는 자율 시뮬레이션 엔진에
이미 존재하는 설계 목표 Cycle Time(`step_dwell_min/max_seconds` 중간값 10초)을 Ideal Cycle
Time으로 사용해 `Ideal Cycle Time x 배정횟수 / 실제 가동시간`으로 계산하고 1.0으로
캡핑했다(표준 OEE 관례). Quality는 새로 만들지 않고 기존 `yield_rate`를 재사용해 공장 전체
수준에서만 3요소 OEE를 계산했고, 설비별 응답에는 Availability/Performance만 노출해 "OEE"라는
이름을 붙이지 않았다.

7. 어떤 방식으로 검증했는가?

- Environment: 로컬, SQLite, 단일 Instance.
- Unit: `tests/test_oee.py` 11건 — Availability(무손실/DOWN 반영/진행 중인 DOWN 구간 처리),
  Performance(목표 Cycle Time과 동일할 때 1.0, 더 빠를 때 캡핑, 더 느릴 때 0.2 등 정확한 값),
  `set_equipment_status`의 `down_seconds` flush, 미배정 설비의 Performance가 0이 아니라
  `None`인지, `/equipment`·`/metrics` 응답 배선까지 포함. 전체 89개 pytest 통과(78→89).
- 수동 스모크: 로컬 서버에 설비 하나를 DOWN 2초 후 IDLE로 되돌려 `down_seconds=2.0`,
  Availability가 그만큼 정확히 감소하는지 curl로 직접 확인.
- Workload: `scripts/run_daily_test.sh` 50 VU, ramp 5/s, 3분 파이프라인 전체 재실행.

8. 개선된 수치적인 결과가 무엇이었는가?

이전에는 존재하지 않던 지표라 Before/After 비교가 아니라 최초 측정값이다. 2026-09-22
50 VU/3분 실행: Requests 17,200, 실패율 0.00%, RPS 95.88, p95 66ms/p99 160ms, Server
5xx/IntegrityError 0/0. 같은 실행에서 측정된 OEE: Availability=0.9954,
Performance=1.0(모든 설비가 캡핑됨 — 부하테스트의 배정 빈도가 설계 목표 Cycle Time보다
훨씬 빨라 예상된 결과), Quality=1.0(같은 실행에서 Scrap 0건), OEE=0.9954.

9. 재발 방지 대책

- `tests/test_oee.py`가 Availability/Performance 공식과 `None` 처리(데이터 없을 때 0으로
  지어내지 않음)를 회귀 테스트로 고정한다.
- ADR-007에 Availability 분모와 Performance 기준값을 고른 이유, 그리고 검토했지만 채택하지
  않은 대안을 남겼다.
- ROADMAP에 "설비 다운타임/알람 이벤트 모델"(개별 DOWN 구간 이력, MTBF/MTTR 계산에 필요)과
  "`PROCESS_STARTED` 이벤트 추가로 실측 Ideal Cycle Time과 비교"를 후속 과제로 남겼다.
