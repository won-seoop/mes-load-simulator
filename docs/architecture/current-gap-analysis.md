# Current Architecture Gap Matrix

기준 Commit: `4eb3a36906b4915239fd9d6afa881103580df051`

## 현재 구현

- FastAPI + SQLAlchemy + SQLite 단일 프로세스
- 고정 공정경로: ETCH → CVD → CMP → INSPECT
- 공정별 설비 3대, RUN/IDLE/DOWN 상태
- Lot WAITING/PROCESSING/HOLD/DONE 상태
- 최소 누적가동시간 기반 설비 선택
- WIP, 완료수, 수율, 사이클타임, 처리량, 설비 가동시간
- pytest 회귀 테스트
- Locust 50 VU, 3분 일일 부하테스트

## Gap Matrix

| MES 영역 | 현재 수준 | 핵심 Gap | 우선순위 |
|---|---|---|---|
| Master Data | Product, Route 이름/Version, 활성 여부 | Process/Recipe 상세와 Version 변경 정책 없음 | 높음 |
| Work Order | 계획수량, 납기, 우선순위, Lot 분할 | Cancel, Split/Merge 이력, 납기 성과 없음 | 높음 |
| Lot State | 허용/금지 전이 Matrix | Rework/Scrap/Cancel 상태 없음 | 높음 |
| Traceability | Lot Event Journal 구현 | 조회 API와 기본 이력은 있으나 Query/계통도/보존정책 없음 | 높음 |
| Dispatching | 최소가동시간 규칙 1개 | FIFO/납기/우선순위 비교와 Queue Wait 측정 없음 | 높음 |
| Equipment | 상태와 누적시간 | Alarm, Downtime Reason, Heartbeat, Interlock 없음 | 높음 |
| Quality | 랜덤 Scrap Flag | 검사, Defect Code, Rework, 원인추적 없음 | 높음 |
| KPI | 단순 집계 | OEE 구성요소, MTBF/MTTR, 대기시간 없음 | 중간 |
| Event Ingestion | Transactional Lot Event 기록 | 외부 설비 Event의 중복, 역순, Schema Version 처리 없음 | 높음 |
| Async Reliability | 없음 | Outbox, Broker, Retry, DLQ, Replay 없음 | Event Journal 이후 |
| Material Control | 없음 | Carrier/Transport Order/Buffer 없음 | 후순위 |
| Observability | 서버 로그와 결과 파일 | Correlation ID, 구조화 로그, Metric/Trace 없음 | 중간 |
| Security/Audit | 없음 | 사용자/권한/명령 Audit 없음 | Core 이후 |

## 가장 먼저 해결할 문제

현재 `Lot` 테이블은 최종 `step_index`, `status`, `completed_at`만 저장한다. 동일한 최종 상태라도 어떤
설비에서 언제 처리됐고 HOLD가 발생했는지 복원할 수 없다.

영향:

```text
공정 이력 부재
→ Lot Trace 불가
→ 불량 원인과 설비 연관 분석 불가
→ 중복/역순 Event 판별 근거 부재
→ Outbox와 Replay의 Source Event 부재
```

첫 개선으로 `LotEvent` Journal을 동일 Transaction에 저장했다. 동시 전이 충돌은 `status +
step_index` 조건부 UPDATE로 해결했다. Work Order와 Lot State Machine까지 추가했으며, 다음 Core
Gap은 Quality/Defect/Rework와 Equipment Alarm이다.
