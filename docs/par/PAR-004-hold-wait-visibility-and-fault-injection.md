# PAR-004 HOLD 대기시간 가시화와 저확률 Fault Injection 튜닝

1. 한줄 요약

Lot 상태만으로는 알 수 없던 설비 다운 HOLD 대기시간을 Event Journal로 복원해 `/metrics`에
노출하고, 이를 실제로 관측할 Fault Injection을 추가하는 과정에서 무조건 실행하면 하루치
생산 실적을 절반으로 무너뜨리는 실패를 겪은 뒤 확률 Gate로 Baseline 수준을 회복했다.

2. 문제가 뭐였는가?

`Lot.status == HOLD`는 로트가 대기 중이라는 사실만 보여주고 언제부터 대기했는지는 보여주지
않았다. 방금 HOLD에 들어간 로트와 10분째 갇힌 로트가 API 응답에서 구분되지 않아 실제 병목
공정을 지목할 수 없었다. 또한 이를 고치는 과정에서, 기존 Locust 시나리오에는 설비 Down이
전혀 없어 새 지표가 항상 0으로만 보인다는 두 번째 문제를 발견했고, 첫 번째로 시도한 Fault
Injection(매 호출마다 무조건 실행)은 3분 동안 설비 상태를 579회 뒤집어 완료 로트를
149건(평소 270~320건)까지 떨어뜨리고 702개 로트를 미해소 HOLD로 쌓는 새로운 문제를 만들었다.

3. 왜 이 문제가 중요했는가?

설비 다운 → HOLD → 병목이라는 사슬은 MES의 핵심 관심사인데, "얼마나 오래 멈췄는가"가 없으면
병목 공정을 찾을 수 없고 재발 방지 대책도 세울 수 없다. 동시에 부하테스트 시나리오 자체가
지나치게 공격적이면 매일 추세를 비교하는 다른 핵심 지표(완료 로트, WIP)가 실제 코드 문제가
아닌 테스트 설계 때문에 왜곡되어, 이후 리포트를 신뢰할 수 없게 된다.

4. 원인이 뭐였는가?

- HOLD 대기시간 부재: `advance_lot`이 HOLD 진입/해제 시 `LOT_HELD`/`LOT_RELEASED_FROM_HOLD`
  이벤트를 이미 Event Journal에 기록하고 있었지만, `/metrics`는 이 이벤트를 전혀 읽지 않고
  현재 `Lot.status` 개수만 세고 있었다.
- Fault Injection 붕괴: Locust Task 가중치 1은 사용자당 약 0.7초마다 한 번꼴로 선택되는데,
  50명의 사용자가 동시에 이 Task를 실행하면서 실제로는 초당 3회 이상 설비 상태를 전환했다.
  12대 설비에 이 정도 빈도로 무작위 DOWN/복구가 겹치면 특정 공정의 3대가 동시에 DOWN인
  구간이 자주 발생해 그 공정 전체가 장시간 막혔다(Locust 통계상 다운 579회/복구 568회,
  `server.log` 확인 결과 500/IntegrityError는 0건으로 서버 자체는 정상 동작).

5. A를 고민하였는데 왜 안 했는가?

Fault Injection을 Task 가중치로만 조절하는 방법(예: 가중치를 1보다 작게)은 Locust가 정수
가중치만 지원해 불가능했고, 대신 다른 모든 Task의 가중치를 올려 상대적으로 희석시키는
방법은 기존에 확립된 3/1/6/2/2/2 가중치 체계를 전부 재조정해야 해서 그 자체로 시나리오
비교 가능성을 해쳤다. 또한 완전히 제거(가중치 0)하는 방법은 새 HOLD 대기시간 지표를 매일
파이프라인에서 전혀 검증하지 못하게 만들어 선택하지 않았다.

6. B를 고민하였고 왜 적용했는가?

Task 본문 안에서 `FAULT_DOWN_PROBABILITY=0.05`로 실행 자체를 확률적으로 건너뛰는 방식을
적용했다. 기존 가중치 체계를 건드리지 않고, 상수 하나로 강도를 조절할 수 있어 향후 실험에서
값을 바꿔가며 비교하기 쉽다. 실패했던 첫 시도(Gate 없음)의 수치를 코드 주석에 그대로 남겨
왜 이 상수가 필요한지 재발 방지 근거로 삼았다.

7. 어떤 방식으로 검증했는가?

- Environment: 로컬, SQLite, 단일 Instance, Commit `99051cc`.
- Unit/Integration: Freeze-time pytest 3건 — 대기 0건 baseline, 진행 중 대기 330초 정확히
  계산, 해소된 대기 120초 정확히 계산 및 이후 재대기 상태 초기화. 전체 65개 pytest 통과.
- 수동 스모크 테스트: 실행 중인 서버에 curl로 ETCH 3대를 모두 DOWN시켜 HOLD와
  `lots_on_hold_count=1`, `longest_current_hold_seconds` 증가를 확인하고, 1대를 복구시켜
  `avg_resolved_hold_seconds`가 실제 경과시간(2.1초)으로 채워지는 것을 확인했다.
- Workload: `scripts/run_daily_test.sh` 50 VU, ramp 5/s, 3분, 동일 Locust 시나리오로
  Gate 없음(1회) vs `FAULT_DOWN_PROBABILITY=0.05`(2회) 비교.
- Baseline: 같은 날 이전 실험인 EXP-005(품질 + Dispatch Fairness, Work Order 포함
  시나리오, Fault Injection 없음) 완료 로트 216건, WIP 2648건.

8. 개선된 수치적인 결과가 무엇이었는가?

| Metric | Gate 없음 (실패) | `FAULT_DOWN_PROBABILITY=0.05` | 같은 날 EXP-005 Baseline |
|---|---:|---:|---:|
| 완료 로트 | 149 | 207~219 | 216 |
| WIP | 2255 | 2369~2497 | 2648 |
| 설비 상태 변경(다운) 횟수 | 579 | 29~34 | 0(Fault 없음) |
| 실행 종료 시점 미해소 HOLD | 702 | 0 | N/A |
| Server 5xx / IntegrityError | 0 / 0 | 0 / 0 | 0 / 0 |

`FAULT_DOWN_PROBABILITY=0.05`에서도 같은 공정 3대가 동시에 DOWN되는 사례는 관측되지 않아
(다운 29회/복구 32회에도 HOLD 0건), 해당 실행에서는 `lots_on_hold_count`,
`longest_current_hold_seconds`, `avg_resolved_hold_seconds`가 모두 0/None으로 기록됐다.
값을 억지로 만들지 않고 그대로 두었으며, 안정적으로 재현하려면 "스텝 전체 다운" Fault가
추가로 필요하다는 것을 ROADMAP 다음 후보로 남겼다.

9. 재발 방지 대책

- `tests/test_process_flow.py`의 3개 Freeze-time Regression Test가 HOLD 대기시간 계산
  로직을 고정한다(0건/진행 중/해소됨 세 가지 경계).
- `load_test/locustfile.py`에 실패했던 첫 시도의 수치(579회 다운, 완료 149건, 702건 HOLD)를
  주석으로 남겨, 이후 `FAULT_DOWN_PROBABILITY` 값을 올리기 전에 반드시 참고하도록 했다.
- `scripts/run_daily_test.sh`의 10초 간격 `/metrics` 샘플러와 `scripts/summarize.py`의
  Peak-during-run 리포트가, 실행 종료 시점 스냅샷만으로는 놓칠 수 있는 짧은 HOLD를 앞으로도
  계속 감시한다.
- ROADMAP에 "스텝 전체 다운 Fault" 후속 작업을 남겨, 이 지표가 매 실행마다 실제로 값을
  가지도록 개선할 다음 단계를 명시했다.
