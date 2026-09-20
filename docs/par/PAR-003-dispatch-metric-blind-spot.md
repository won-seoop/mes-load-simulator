# PAR-003 설비 가동시간 Metric이 숨긴 Dispatch 편향 제거

1. 한줄 요약

가동시간은 균등했지만 검사 배정이 1/1/268로 편향된 문제를 Dispatch Count 기반 Rule로 바꿔
79/80/79로 균등화하고 장비 연관 불량을 실제로 탐지했다.

2. 문제가 뭐였는가?

기존 Report는 3대 검사설비의 Run Time이 비슷하다고 표시했지만 거의 모든 검사가 INSPECT-03에
배정됐다.

3. 왜 이 문제가 중요했는가?

Dispatch 편향은 Capacity를 사용하지 못하게 하고 장비별 품질률의 비교 표본을 망가뜨린다. 잘못된
Metric을 믿으면 병목과 원인 장비를 반대로 해석할 수 있다.

4. 원인이 뭐였는가?

Instant Simulator가 설비를 RUN으로 계속 유지해 모든 설비의 Wall-clock Run Time이 함께 증가했다.
마지막으로 시작한 장비가 계속 최소 Effective Run Time으로 남았다.

5. A를 고민하였는데 왜 안 했는가?

Run Time 수식과 Tie-breaker를 보정할 수 있었지만 실제 Process Duration이 없는 구조에서는 Run Time이
배정 부하를 나타내지 못한다.

6. B를 고민하였고 왜 적용했는가?

설비별 Dispatch Count를 저장하고 Count를 1차 선택 기준으로 사용했다. 작업 배정이라는 문제를 같은
단위로 직접 측정할 수 있기 때문이다.

7. 어떤 방식으로 검증했는가?

30 LOT을 3대 설비에 보내 10/10/10을 확인하는 Regression Test를 추가했다. 이후 50 VU/3분 EXP-005와
DB Group-by, 품질 이상 API, MCP Tool Smoke Test로 검증했다.

8. 개선된 수치적인 결과가 무엇이었는가?

- 검사 배정: 1/1/268 → 79/80/79
- 공정별 Dispatch Count 최대 편차: 1건
- INSPECT-03 불량률: 27.85%, Peer Mean 0%, WARNING 탐지
- Server 5xx/IntegrityError: 0/0

9. 재발 방지 대책

Equipment API와 C# UI에 Dispatch Count를 노출하고 30 LOT 균등 배정 Test를 유지한다. 향후 실제
Process Duration을 추가할 때 Count, Queue Length, 예상 완료시간을 별도 Experiment로 비교한다.
