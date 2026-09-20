# PAR-002 반복 품질 실패의 무한 재작업 방지

1. 한줄 요약

지속되는 검사 결함이 4차 검사까지 반복되던 문제를 1회 재작업 정책과 두 번째 실패 Scrap 강제로
제한해 3차 이상 검사를 5건에서 0건으로 줄였다.

2. 문제가 뭐였는가?

품질 FAIL LOT이 같은 조건으로 다시 검사돼도 계속 REWORK로 돌아갈 수 있었고 최대 4차 검사까지
발생했다.

3. 왜 이 문제가 중요했는가?

반복 Rework는 WIP와 Cycle Time을 계속 증가시키고 지속 설비 결함을 정상 공정처럼 숨긴다. 수율과
작업지시 완료도 왜곡한다.

4. 원인이 뭐였는가?

서버에 Rework 횟수 정책이 없었고 Load 조건에서 실패 LOT ID가 항상 짝수여서 Disposition이 전부
REWORK로 선택됐다. DB에서 3차 4건, 4차 1건을 확인했다.

5. A를 고민하였는데 왜 안 했는가?

무제한 Rework를 유지하고 현장 판단에 맡기는 방법은 유연하지만 현재 프로젝트에는 승인 Workflow가
없어 Loop를 제어할 근거가 없었다.

6. B를 고민하였고 왜 적용했는가?

한 번의 교정 Rework만 허용하고 두 번째 실패에는 SCRAP을 요구했다. 정책이 단순하고 State Machine,
HTTP Conflict, Regression Test로 검증할 수 있기 때문이다.

7. 어떤 방식으로 검증했는가?

동일한 50 VU/3분 Locust 시나리오, SQLite, 결정론적 `INSPECT_SENSOR_DRIFT` 조건에서 EXP-004 전후를
비교했다. Unit/Integration Test와 DB Attempt 분포를 함께 확인했다.

8. 개선된 수치적인 결과가 무엇이었는가?

- 최대 검사차수: 4 → 2
- 3차 이상 검사: 5 → 0
- Server 5xx: 0 → 0
- IntegrityError: 0 → 0

9. 재발 방지 대책

최대 Rework 정책을 서버에서 강제하고 두 번째 REWORK 거부 Test, 시도차수 Unique Constraint,
부하 후 검사차수 분포 확인을 유지한다.
