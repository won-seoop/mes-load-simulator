# FactoryFlow MES Lab 프로젝트 지침

나는 삼성SDS Nexplant MES와 같은 제조 실행 시스템을 참고하여 MES·스마트팩토리·제조 플랫폼
백엔드 직무 취업을 준비하고 있다.

이 프로젝트의 목적은 단순한 CRUD 화면이나 부하테스트 데모를 만드는 것이 아니다.

삼성SDS가 **공식적으로 공개한** Nexplant MES의 문제 영역을 참고하여, 공개 기술과 오픈소스를
이용해 제조 실행 시스템의 핵심 문제를 직접 설계하고 구현하고 검증한다.

특히 다음 문제를 실제 엔지니어처럼 경험하는 것이 중요하다.

문제 발견
→ 왜 중요한지 분석
→ 원인 분석
→ Baseline 구축
→ 대안 A 검토
→ 대안 A를 선택하지 않은 이유
→ 대안 B 검토
→ 대안 B를 선택한 이유
→ 구현
→ 테스트
→ 정량 검증
→ 실패 사례 분석
→ 개선
→ Regression Test
→ 재발 방지
→ PAR 경험 정리

최종적으로 프로젝트에서 발생한 실제 문제 해결 경험을 자기소개서와 기술면접에서 사용할 수
있도록 코드, 실험 결과, Git 이력, Notion 기록으로 남긴다.

---

## 1. 프로젝트 이름

**FactoryFlow MES Lab**

삼성SDS Nexplant MES가 공개적으로 다루는 제조 실행 문제를 참고한 오픈소스 기반 MES 엔지니어링
프로젝트다.

GitHub 저장소 이름은 현재의 `mes-load-simulator`를 유지할 수 있다. 프로젝트 이름에 Nexplant를
직접 사용해 삼성SDS 공식 제품 또는 제휴 프로젝트처럼 보이게 하지 않는다.

---

## 2. 프로젝트 목표

다음 능력을 실제 코드와 측정 결과로 보여주는 것이 목표다.

- 제조 공정과 Lot 상태를 일관성 있게 관리하는 능력
- 작업지시, 공정경로, 설비, 자재, 품질 데이터를 연결하는 도메인 모델링 능력
- 실시간 설비 이벤트와 사용자 명령을 구분하는 시스템 설계 능력
- Dispatching, Interlock, Traceability 같은 MES 핵심 로직 구현 능력
- 장애, 중복, 순서 역전, 재시도 상황에서도 데이터 정합성을 지키는 능력
- 부하테스트와 장애 주입을 통해 병목과 실패 원인을 찾는 능력
- 선택하지 않은 대안까지 포함해 기술적 판단을 설명하는 능력

---

## 3. 내 배경

- 컴퓨터공학 학사
- C++ 기반 반도체 설비 SW 개발 인턴 경험 6개월
- Java, Spring Boot 기반 백엔드 개발 경험
- Python, FastAPI 사용 가능
- MacBook Air M3 사용
- MES, 스마트팩토리, 제조 플랫폼, 설비 연동 백엔드 직무에 관심이 있음
- 삼성SDS 및 제조 IT 기업 취업을 준비하고 있음
- 실제 Fab, 생산설비, Nexplant 내부 코드에는 접근할 수 없음
- 공개 자료, 공개 표준, 시뮬레이터, 오픈소스만 사용함

---

## 4. 가장 중요한 원칙

기능 개수보다 문제 해결 깊이를 중요하게 생각한다.

Claude는 많은 기능을 한 번에 구현하지 않는다. 하나의 기능이라도 다음 과정이 실제로 발생하도록
진행한다.

Baseline
→ 실제 테스트
→ 문제 관찰
→ 문제 측정
→ 원인 분석
→ 해결 방법 비교
→ 선택
→ 개선
→ 동일 조건 재측정
→ 결과 기록

처음부터 모든 최적화, 메시지 큐, 캐시, 마이크로서비스를 붙여 문제를 숨기지 않는다.

그렇다고 일부러 나쁜 코드나 비현실적인 장애를 만들지도 않는다. 동시 요청, 설비 Down, 중복 이벤트,
순서 역전, 부분 실패, 재시작, 느린 DB 쿼리처럼 실제 제조 시스템에서 자연스럽게 발생할 수 있는
문제를 기반으로 개선 경험을 만든다.

---

## 5. 삼성SDS Nexplant MES 기준으로 생각하는 원칙

모든 주요 기능을 구현하기 전에 먼저 확인한다.

1. 삼성SDS 공식 자료에서 이 기능 또는 유사한 문제를 확인할 수 있는가?
2. 이 기능이 실제 제조 실행에서 왜 필요한가?
3. 반도체·배터리·디스플레이처럼 공정과 설비가 복잡한 환경에서는 왜 더 중요한가?
4. 이 기능은 Planning, MES, Machine Control, Equipment Engineering, Material Control 중 어디에
   위치하는가?
5. 신입 개발자가 이 기능을 구현함으로써 어떤 역량을 보여줄 수 있는가?

공식 근거의 출발점:

- Nexplant MES 공식 페이지:
  https://www.samsungsds.com/en/mes/nexplant-mes.html
- Nexplant MES 공식 소개 자료:
  https://image.samsungsds.com/en/resources/__icsFiles/afieldfile/2016/12/09/%28Leaflet%29_Nexplant_MES_Eng.pdf
- 삼성SDS 스마트 공장 구축 사례:
  https://www.samsungsds.com/kr/case-study/smart-factory-automobile.html

공식 자료에서 확인할 수 있는 주요 문제 영역은 다음과 같다.

- Scheduling & Dispatching
- Manufacturing Operation
- Equipment Engineering
- Machine Control
- Material Control
- 실시간 데이터 수집
- WIP 관리와 Lot Tracking/Traceability
- 품질 검사와 불량 추적
- 설비 상태, 이벤트, 로그, 알람 처리
- 생산·품질·설비 KPI 및 가시성

---

## 6. 공개 기능과 내 구현을 구분하는 원칙

삼성SDS가 공개하지 않은 내부 아키텍처, 메시지 브로커, 알고리즘, 데이터 모델을 추측하지 않는다.

올바른 표현:

> 삼성SDS가 공개한 실시간 Dispatching과 Lot Tracking 문제 정의를 참고하여, 우선순위 기반
> Dispatching 규칙과 Lot 이력 모델을 자체 구현했다.

잘못된 표현:

> Nexplant MES는 Kafka와 Redis를 사용한다.

공식 자료에 특정 기술이 명시되지 않았다면 특정 내부 기술을 사용한다고 주장하지 않는다.

항상 다음을 구분한다.

Nexplant MES 공개 기능
→ 실제 제조 현장에서 해결하는 문제

내 프로젝트 구현
→ 해당 문제를 재현하기 위해 선택한 오픈소스 기술과 설계

---

## 7. Manufacturing Perception 관점

이 프로젝트를 단순 CRUD 프로젝트로 만들지 않는다.

제조 현장의 데이터를 다음과 같이 의미 있는 의사결정 정보로 변환하는 것이 목표다.

ERP 생산계획
→ Work Order
→ Lot
→ Process Route
→ Dispatching
→ Equipment Command
→ Equipment Event
→ Process Result
→ Inspection / Defect
→ Genealogy / Traceability
→ WIP / OEE / Yield / TAT
→ Alert / Decision

즉, 로트를 생성하고 상태를 바꾸는 것에서 끝나지 않고 다음 질문에 답할 수 있어야 한다.

- 어떤 제품과 작업지시에서 만들어진 Lot인가?
- 어떤 공정과 설비를 언제 통과했는가?
- 어떤 Recipe와 자재가 사용되었는가?
- 어느 공정에서 대기 또는 불량이 발생했는가?
- 어떤 설비 이벤트가 생산 지연에 영향을 주었는가?
- 현재 WIP와 병목 공정은 어디인가?
- 동일 문제가 재발했는가?

---

## 8. 목표 Architecture

```text
ERP / Production Plan Simulator
              ↓
        Work Order API
              ↓
      Manufacturing Operation
        ├─ Master Data
        ├─ Lot / WIP
        ├─ Process Route
        ├─ Genealogy
        ├─ Quality
        └─ Audit Trail
              ↕
    Scheduling & Dispatching
              ↕
      Machine Control Adapter
              ↕
 Equipment / SECS-GEM-like Simulator
              ↓
       Equipment Event Ingestion
              ↓
      Event Journal / Outbox
              ↓
 Message Broker (필요성이 검증된 뒤)
              ↓
 Idempotent Consumers / Retry / DLQ
              ↓
 Metrics / Alert / Replay / Dashboard
              ↓
 Load Test / Fault Injection / Benchmark
```

실제 SECS/GEM 장비가 없으므로 초기에는 공개 표준의 개념을 참고한 설비 시뮬레이터를 사용한다.
실제 장비와 통신했다고 표현하지 않는다.

---

## 9. 현재 Baseline

현재 저장소에는 다음이 구현되어 있다.

- FastAPI 기반 API
- SQLite + SQLAlchemy
- Equipment 12대와 ETCH → CVD → CMP → INSPECT 공정경로
- Lot 생성, 조회, 공정 진행, HOLD/DONE 상태
- 설비 RUN/IDLE/DOWN 상태
- 최소 누적 가동시간 기반 설비 선택
- WIP, 완료 수, 수율, 사이클타임, 처리량, 설비 가동시간 지표
- pytest 단위·통합 테스트
- Locust 50명·3분 부하테스트
- 일일 Markdown/JSON 리포트와 Notion 기록 자동화

이 목록은 구현 사실만 의미한다. 실제 생산환경 수준의 처리량, 가용성, 설비 연동, 품질 인증을
의미하지 않는다.

---

## 10. Core MVP와 Stretch Goal

### Core MVP

반드시 먼저 완성한다.

Master Data
→ Work Order
→ Process Route
→ Lot State Machine
→ Equipment State / Interlock
→ Dispatching Rule
→ Process Event Journal
→ WIP / Traceability
→ Quality / Defect
→ OEE / Yield / TAT
→ Dashboard / Search
→ Load Test
→ Fault Injection
→ Regression Test

### Stretch Goal

Core MVP가 완성되기 전에 우선 구현하지 않는다.

- PostgreSQL 전환
- Transactional Outbox
- Kafka 또는 RabbitMQ
- Idempotent Consumer, Retry, DLQ, Replay UI
- 설비 이벤트 대량 수집
- SECS/GEM 형태의 장비 시뮬레이터
- Material Control / Carrier / Transport Order
- SPC / FDC 형태의 품질·설비 분석
- Capacity Simulation
- Active-Active 또는 다중 인스턴스 실험
- Zero-downtime 배포 실험
- Redis Cache
- Kubernetes

기술 이름을 많이 넣는 것보다 Core 기능에서 깊이 있는 문제 해결 경험을 만드는 것이 우선이다.

---

## 11. Phase 1 Master Data와 Work Order

최소 모델:

- Product
- Process Definition
- Process Route
- Equipment
- Work Order
- Lot
- Material
- Recipe Version

검증할 문제:

- 존재하지 않는 Product로 Work Order 생성
- 비활성 Process Route 사용
- Work Order 수량보다 많은 Lot 분할
- 중복 Work Order 번호
- Recipe Version 변경 중 생산 시작

측정:

- 생성 성공/실패 수
- Validation 오류 유형
- 조회 P50/P95/P99
- DB 쿼리 수
- 동시 생성 시 중복 발생 여부

---

## 12. Phase 2 Lot State Machine

상태 전이를 명시적으로 관리한다.

예:

```text
CREATED
→ RELEASED
→ WAITING
→ PROCESSING
→ COMPLETED
→ SHIPPED
```

예외 상태:

```text
HOLD
SCRAPPED
CANCELLED
REWORK
```

관찰할 문제:

- DONE Lot 재진행
- 동일 공정 중복 완료
- 순서가 바뀐 공정 완료 이벤트
- HOLD 해제 후 잘못된 Step 진행
- 재작업 Route에서 이력 단절
- 동시에 두 설비에 배정되는 Lot

상태 전이는 코드 분기만으로 흩어놓지 않고 허용 전이와 금지 전이를 테스트로 고정한다.

---

## 13. Phase 3 Equipment State와 Interlock

설비 상태 후보:

- IDLE
- SETUP
- RUN
- DOWN
- PM
- OFFLINE

Interlock 예:

- DOWN 설비에는 Lot 배정 금지
- Recipe 불일치 시 시작 금지
- 품질 Hold Lot 시작 금지
- 설비 Capacity 초과 금지
- Maintenance Due 설비 사용 제한

테스트:

- 정상 상태 전이
- 잘못된 상태 전이
- 설비 Down 직전/직후 동시 요청
- 공정 시작 중 설비 Down
- 복구 후 대기 Lot 재배정
- 중복 Start/Complete 명령

---

## 14. Phase 4 Scheduling & Dispatching

Baseline:

Random 또는 First Available Equipment

대안 후보:

- Least Utilized
- FIFO
- Earliest Due Date
- Shortest Processing Time
- Priority + Due Date
- Setup Change 최소화
- Bottleneck 우선

처음부터 복잡한 최적화 알고리즘을 넣지 않는다.

동일한 Workload에서 규칙을 비교한다.

측정:

- Throughput
- Average/P95 Cycle Time
- Queue Wait Time
- WIP
- 설비별 Utilization 편차
- 납기 지연 Lot 수
- Setup Change 횟수
- Starvation 발생 여부

---

## 15. Phase 5 WIP, Genealogy, Traceability

Lot 이력은 현재 상태만 저장하지 않는다.

최소 이벤트:

- LOT_CREATED
- LOT_RELEASED
- PROCESS_STARTED
- PROCESS_COMPLETED
- LOT_HELD
- LOT_RELEASED_FROM_HOLD
- DEFECT_RECORDED
- LOT_SCRAPPED
- LOT_REWORKED
- LOT_COMPLETED

검색:

- 특정 Work Order의 Lot 목록
- 특정 Lot이 거친 공정과 설비
- 특정 설비에서 처리된 Lot
- 특정 자재 Batch가 투입된 제품
- 특정 Defect와 연관된 공정/설비/Recipe
- Event 전후의 상태 변화

현재 상태 테이블과 변경 이력 테이블의 역할을 구분한다.

---

## 16. Phase 6 Quality와 Defect

최소 기능:

- Inspection Result
- Defect Code
- Pass / Fail
- Scrap / Rework
- Quality Hold
- 공정·설비·제품별 불량 집계

측정:

- Yield
- First Pass Yield
- Defect Rate
- Rework Rate
- 공정별 불량률
- 설비별 불량률

랜덤 불량률만으로 끝내지 않는다. 실험 단계에서는 특정 설비 또는 Recipe에서 불량률이 증가하는
재현 가능한 시나리오를 만들고, 원인 추적이 가능한지 검증한다.

---

## 17. Phase 7 OEE와 제조 KPI

OEE를 단순 숫자 하나로 만들지 않는다.

```text
OEE = Availability × Performance × Quality
```

각 항목의 분모와 시간 구간을 문서화한다.

측정 후보:

- Availability
- Performance
- Quality
- OEE
- Throughput
- WIP
- TAT / Cycle Time
- Queue Wait Time
- MTBF
- MTTR
- Downtime by Reason

데이터가 없어서 정확히 계산할 수 없는 지표는 `N/A`로 표시하고 임의의 값을 만들지 않는다.

---

## 18. Phase 8 Equipment Event Ingestion

실제 장비 대신 설비 시뮬레이터를 만든다.

이벤트 예:

- MACHINE_STATE_CHANGED
- PROCESS_STARTED
- PROCESS_COMPLETED
- ALARM_RAISED
- ALARM_CLEARED
- MEASUREMENT_RECORDED
- HEARTBEAT

각 이벤트 최소 필드:

- event_id
- equipment_id
- event_type
- occurred_at
- received_at
- sequence_number
- lot_id
- process_id
- payload
- schema_version

검증할 문제:

- 중복 이벤트
- 늦게 도착한 이벤트
- 순서가 바뀐 이벤트
- 잘못된 Schema
- 알 수 없는 설비
- 재전송
- 장비 연결 끊김
- Burst Traffic

---

## 19. 메시지 큐 도입 원칙

현재 프로젝트에는 메시지 큐가 없다.

메시지 큐를 포트폴리오 키워드 때문에 바로 붙이지 않는다. 먼저 동기 Baseline 또는 DB Event Journal로
다음 문제를 재현하고 측정한다.

- 설비 이벤트 Burst로 API 응답이 느려짐
- 외부 시스템 장애가 생산 명령을 지연시킴
- 프로세스 종료 후 후속 집계 실패
- 재시작 중 이벤트 유실
- 여러 Consumer가 독립적으로 같은 이벤트를 필요로 함

메시지 큐 도입 시 후보:

- Kafka: 대량 이벤트 스트림, 여러 Consumer, 보존과 Replay가 중요한 경우
- RabbitMQ: 작업 분배, Routing, ACK/Retry/DLQ가 중요한 경우
- Redis Streams: 단일 프로젝트 내부의 가벼운 Stream과 기존 Redis 활용이 타당한 경우

선택 전에 비교할 항목:

- Delivery Guarantee
- Ordering 범위
- Retention / Replay
- Consumer 확장성
- Routing
- 운영 복잡도
- 로컬 재현 가능성
- 장애 복구

모든 REST 요청을 메시지 큐 뒤에 넣지 않는다.

즉시 성공/실패를 확인해야 하는 작업 시작, Interlock, 재고 차감 같은 명령은 동기 Transaction으로
처리하고, **확정된 상태 변경 이후의 이벤트**를 Outbox를 통해 비동기로 발행하는 방식을 우선 검토한다.

권장 흐름:

```text
Command API
→ DB Transaction
   ├─ Domain State 변경
   └─ Outbox Event 저장
→ Outbox Publisher
→ Kafka/RabbitMQ
→ Idempotent Consumer
→ Retry / DLQ
→ Replay / 운영 가시성
```

Nexplant가 Kafka 또는 RabbitMQ를 사용한다고 주장하지 않는다. 이것은 프로젝트가 공개된 제조 문제를
재현하기 위해 선택한 자체 아키텍처다.

---

## 20. Transactional Outbox

Outbox 도입 전 다음 실패를 재현한다.

```text
DB Commit 성공
→ Broker Publish 실패
→ 생산 상태는 바뀌었지만 후속 이벤트 유실
```

비교:

- A: Transaction 후 직접 Publish
- B: Transactional Outbox

검증:

- DB Commit과 Event 저장의 원자성
- Publisher 재시작
- 중복 Publish
- Consumer Idempotency
- Retry Backoff
- Poison Message
- DLQ 이동
- Replay 후 최종 상태

---

## 21. Phase 9 Material Control

Core MVP 이후 진행한다.

최소 모델:

- Carrier
- Buffer
- Stocker
- Transport Order
- Source / Destination
- Priority
- Transport State

처음에는 실제 OHT/AGV 제어가 아니라 이송 주문과 상태 시뮬레이션만 구현한다.

측정:

- 이동 시간
- Queue Length
- Transport Throughput
- 교착 또는 Starvation
- 우선순위 역전
- 생산 지연에 미친 영향

---

## 22. Dashboard와 Search

최소 화면:

- Factory Overview
- WIP by Process
- Equipment Status
- Lot Trace
- Work Order Progress
- Quality / Defect
- Alarm / Downtime
- Throughput / Cycle Time / OEE
- Event Replay 상태

프론트 디자인에 과도하게 시간을 쓰지 않는다. 제조 상태와 문제 원인이 보이는 운영 가시성이 목적이다.

---

## 23. 데이터베이스 원칙

SQLite Baseline을 먼저 유지하되 동시성 한계를 측정한다.

PostgreSQL 전환 조건 예:

- 동시 Write Lock 문제가 재현됨
- Row Lock 또는 Isolation Level 실험이 필요함
- JSON/Event Query와 Index 비교가 필요함
- Outbox Polling과 `SKIP LOCKED` 실험이 필요함

전환 전후는 동일 Workload로 비교한다.

측정:

- TPS/RPS
- P50/P95/P99
- Lock Wait
- Deadlock
- 실패율
- CPU/Memory
- DB Size
- 쿼리 실행계획

---

## 24. 동시성과 정합성

우선 검증 대상:

- 같은 Lot에 대한 동시 Advance
- 같은 설비에 대한 동시 배정
- Work Order 수량 초과 Lot 생성
- 중복 Process Complete
- 재고 음수
- 낙관적 Lock 충돌
- Deadlock
- Lost Update

해결 후보:

- DB Constraint
- Atomic Update
- Optimistic Lock
- Pessimistic Lock
- Idempotency Key
- State Transition Guard
- Unique Event ID

애플리케이션 Lock만으로 해결했다고 단정하지 않는다. DB 제약과 Transaction 경계를 함께 검토한다.

---

## 25. Load Test 원칙

가상 사용자 수와 RPS를 혼동하지 않는다.

부하 유형을 분리한다.

- Operator UI Traffic
- Work Order Command Traffic
- Lot Transaction Traffic
- Equipment Event Traffic
- Metrics / Dashboard Read Traffic

Closed Model과 Open Model을 구분한다.

- `ramping-vus`: 사용자 행동 기반
- `constant-arrival-rate`: 고정 이벤트 유입률 또는 TPS 목표

반드시 기록:

- 실행 환경
- Commit SHA
- 데이터베이스
- 인스턴스 수
- VU
- 요청률과 실제 처리 요청 수
- Duration
- P50/P95/P99
- 실패율
- `dropped_iterations`
- Business TPS

---

## 26. Performance Metric

평균만 기록하지 않는다.

상황에 맞는 값을 선택한다.

- Requests/sec
- Events/sec
- Commands/sec
- Business Transactions/sec
- P50/P95/P99 Latency
- Error Rate
- Timeout
- Queue Lag
- Consumer Lag
- Retry Count
- DLQ Count
- DB Connection Pool
- Lock Wait
- CPU
- Memory
- Disk I/O
- Throughput
- WIP
- Cycle Time

HTTP RPS, 설비 이벤트 유입률, Business TPS를 서로 다른 값으로 기록한다.

---

## 27. Fault Injection

정상 상황만 테스트하지 않는다.

다음 실패를 하나씩 독립적으로 재현한다.

- DB 연결 지연/실패
- Broker 중단
- Consumer 중단
- 중복 이벤트
- Out-of-order 이벤트
- Poison Message
- 설비 Heartbeat 누락
- 설비 Down
- 외부 ERP Timeout
- 프로세스 재시작
- Disk Full에 가까운 상태
- 잘못된 Schema Version

장애를 주입할 때 예상 결과를 먼저 적고 실제 결과와 비교한다.

---

## 28. Reliability와 Recovery

다음을 증명 가능한 형태로 구현한다.

- Timeout
- Retry with Backoff
- Idempotency
- Circuit Breaker가 필요한지 여부
- DLQ
- Replay
- Health Check
- Graceful Shutdown
- Startup Recovery
- Audit Trail

“장애에 강하다”는 표현을 쓰지 않는다. 어떤 장애에서 어떤 상태까지 복구되는지 구체적으로 적는다.

---

## 29. Event Ordering과 Idempotency

이벤트 처리 시 최소 다음을 고려한다.

- `event_id` Unique Constraint
- Aggregate별 `sequence_number`
- 이미 처리한 이벤트 재수신
- 이전 상태 이벤트가 늦게 도착
- Consumer 처리 후 ACK 전 장애
- 동일 Outbox Event 중복 Publish

검증 결과는 최종 DB 상태뿐 아니라 처리 이력과 중복 방지 근거까지 확인한다.

---

## 30. Observability

최소 관찰 항목:

- Request ID
- Correlation ID
- Lot ID
- Work Order ID
- Equipment ID
- Event ID
- Trace/Span 또는 처리 단계
- 구조화 로그
- 핵심 Metric
- Alert

한 Lot의 명령부터 설비 이벤트, 품질 결과, 비동기 Consumer까지 연결해서 추적할 수 있게 한다.

Prometheus와 Grafana는 관찰할 Metric이 정의된 뒤 도입한다.

---

## 31. Security와 Audit

Core MVP 후 최소한 다음을 검토한다.

- Operator / Engineer / Admin 역할
- 변경 권한
- 설비 원격 명령 권한
- 중요 상태 변경 Audit Log
- 누가, 언제, 무엇을, 왜 변경했는지 기록
- API Key 또는 JWT
- Secret 관리
- 입력 Validation

실제 현장 작업자 감시 기능은 프로젝트 범위에서 제외한다.

---

## 32. Long Running Test

MES와 설비 이벤트 처리 시스템은 장시간 실행된다.

테스트 시간:

- 10분
- 30분
- 1시간
- 가능하면 그 이상

측정:

- Memory 변화
- P95/P99 변화
- DB 크기 증가
- Queue/Consumer Lag
- Retry/DLQ 증가
- Connection 누수
- Thread/Task 증가
- 로그 파일 증가
- 처리량 감소
- 중복 처리
- 미처리 Event 수

---

## 33. Regression Test

고정 시나리오를 만든다.

예:

- 정상 Lot 전체 공정 완료
- 설비 Down 후 HOLD와 복구
- 동시 Advance
- 불량과 Scrap
- Rework
- 중복 Equipment Event
- Out-of-order Event
- Outbox 재시작
- Consumer 중단과 복구
- KST 자정 경계

새 기능을 추가하거나 Parameter를 바꾸면 같은 시나리오를 다시 실행한다.

---

## 34. Ground Truth와 수치 원칙

수치를 절대 만들어내지 않는다.

실제 실행 결과만 사용한다.

정확하게 측정할 수 없는 Metric은 억지로 작성하지 않는다.

다음을 구분한다.

- 설계 목표
- 구현된 기능
- 테스트로 확인된 동작
- 로컬에서 측정한 수치
- 운영환경에서 검증되지 않은 가정

로컬 SQLite 단일 인스턴스 결과를 운영 PostgreSQL, 다중 인스턴스, Kafka/RabbitMQ 환경의 성능으로
일반화하지 않는다.

---

## 35. 테스트 코드

우선 대상:

- Lot 상태 전이
- 금지된 상태 전이
- Dispatching 규칙
- Equipment Interlock
- 동시 배정
- Work Order 수량 Constraint
- Genealogy
- Quality Hold / Release
- OEE 계산
- 이벤트 중복 방지
- 이벤트 순서 검증
- Outbox 원자성
- Consumer Idempotency
- Retry / DLQ / Replay
- 시간대 경계

FastAPI 단계에서는 pytest를 사용한다. 향후 Java/Spring Boot 모듈을 추가한다면 해당 언어의 테스트
프레임워크를 사용하되 같은 Business Rule을 중복 구현하지 않는다.

---

## 36. 실험 기록 구조

```text
docs/
    architecture/
    decisions/
experiments/
    EXP-001-.../
        experiment.md
        config.yaml
        metrics.json
        failures/
results/
    reports/
    plots/
    failures/
tests/
load_test/
simulators/
```

대용량 로그, DB 파일, Broker 데이터, Dataset은 Git에 직접 Commit하지 않는다.

---

## 37. 실험 번호

예:

- EXP-001 Current MES Baseline
- EXP-002 Concurrent Lot Advance
- EXP-003 Dispatching Rule Comparison
- EXP-004 Equipment Down Recovery
- EXP-005 SQLite Write Contention
- EXP-006 PostgreSQL Comparison
- EXP-007 Direct Publish Failure
- EXP-008 Transactional Outbox
- EXP-009 Duplicate Event Idempotency
- EXP-010 Consumer Recovery and Replay

각 실험에는 다음을 남긴다.

- Goal
- Hypothesis
- Problem
- Workload
- Environment
- Configuration
- Baseline
- Result
- Failure Cases
- Analysis
- Decision
- Next Action

---

## 38. Config 관리

다음 값을 코드에 흩뿌리지 않는다.

- 공정경로
- 처리시간
- 설비 수
- Scrap Probability
- Dispatching Rule
- Event Rate
- Retry Count
- Retry Backoff
- Consumer Batch Size
- Poll Interval
- Queue Capacity
- Timeout
- OEE Window

각 실험에서 어떤 Config를 사용했는지 남긴다.

---

## 39. Before / After

개선 전후는 동일한 Commit 기반 Scenario, 데이터, 환경, Duration으로 측정한다.

예:

| Metric | Before | After |
|---|---:|---:|
| 중복 공정 완료 | 실제 측정값 | 실제 측정값 |
| P95 command latency | 실제 측정값 | 실제 측정값 |
| Outbox 미발행 이벤트 | 실제 측정값 | 실제 측정값 |
| 완료 Lot 수 | 실제 측정값 | 실제 측정값 |

그리고 다음을 기록한다.

- 무엇을 변경했는가?
- 왜 변경했는가?
- 개선된 부분은 무엇인가?
- 새로 생긴 Trade-off는 무엇인가?

---

## 40. 실패한 실험

실패한 실험을 삭제하지 않는다.

예:

```text
가설
RabbitMQ 도입만으로 Command API P95가 감소할 것이다.

결과
Command 자체가 동기 DB Transaction 병목이어서 유의미한 개선이 없었다.

결론
비동기화 대상과 동기 명령 경계를 다시 정의해야 한다.
```

숫자를 조작하거나 실패를 숨기지 않는다.

---

## 41. PAR 경험

중요한 문제 해결이 끝날 때마다 다음 9개 항목으로 정리한다. 형식과 질문은 변경하지 않는다.

### 1. 한줄 요약

문제와 핵심 해결 방법과 결과가 한 문장에 들어가도록 작성한다.

### 2. 문제가 뭐였는가?

실제 Test 또는 구현 과정에서 발견한 문제를 구체적으로 작성한다.

### 3. 왜 이 문제가 중요했는가?

MES와 제조 현장에서 왜 중요한지 설명한다. 다른 기능에 미치는 연쇄 영향도 작성한다.

예:

중복 Process Complete
→ 생산실적 중복
→ WIP 오류
→ 재고와 ERP 실적 불일치
→ 잘못된 납기 판단

### 4. 원인이 뭐였는가?

로그, Metric, DB 상태, 코드 분석에 근거해 작성한다. 추측만으로 확정하지 않는다.

### 5. A를 고민하였는데 왜 안 했는가?

첫 번째 해결 방법과 장점, 최종 선택하지 않은 이유를 작성한다.

판단 기준:

- 정합성
- Latency
- Throughput
- 장애 복구
- 복잡도
- 운영 비용
- 유지보수성

### 6. B를 고민하였고 왜 적용했는가?

최종 선택한 방식과 현재 문제에 더 적합한 이유를 작성한다.

### 7. 어떤 방식으로 검증했는가?

Environment, Commit, Workload, Configuration, Metric, Baseline, 비교 방식, Regression Test를 적는다.

### 8. 개선된 수치적인 결과가 무엇이었는가?

실제 측정값만 작성한다. 정량 결과가 없다면 억지로 숫자를 만들지 않고 정성 검증을 적는다.

### 9. 재발 방지 대책

Regression Test, DB Constraint, Idempotency, Monitoring, Alert, Runbook, Replay 절차 등을 적는다.

---

## 42. PAR 후보 조건

다음 조건을 만족할 때만 PAR 후보로 판단한다.

- 실제 문제가 있었다.
- 문제의 원인을 분석했다.
- 최소 두 개의 해결 방향을 검토했다.
- 선택 이유가 있었다.
- 실제 구현 또는 실험을 했다.
- 결과를 검증했다.
- 재발 방지책이 있다.

좋은 후보:

- 동시 Lot 진행의 중복 실적 방지
- 설비 Down 시 HOLD 복구
- Dispatching 병목 개선
- SQLite Lock 문제 분석과 PostgreSQL 전환
- DB Commit 후 Event 유실을 Outbox로 해결
- 중복 Equipment Event의 Idempotency 보장
- Consumer 장애 후 Replay
- P95/P99 Event Processing Latency 개선
- 장시간 실행 시 Memory 또는 Lag 증가 해결

---

## 43. Git 원칙

의미 있는 단위로 Commit한다.

예:

- `feat: add explicit lot state transitions`
- `test: reproduce concurrent lot advance race`
- `fix: prevent duplicate process completion`
- `feat: add priority dispatching baseline`
- `perf: reduce dispatch query latency`
- `feat: persist process events with outbox`
- `test: verify idempotent event consumption`
- `docs: record EXP-008 outbox decision`

한 Commit에 여러 Phase의 기능을 섞지 않는다.

Commit 전에 관련 테스트를 실행하고 결과를 기록한다.

---

## 44. Notion 기록 위치와 원칙

연결된 Notion Connector를 사용한다.

기존 `MES 부하테스트 리포트` 데이터베이스와 MES 관련 페이지를 먼저 검색한다. 같은 구조를 중복으로
만들지 않는다. 별도 기준 페이지 URL이 제공되면 그 페이지 아래를 기준 기록 공간으로 사용한다.

대화 안에서만 정리하고 끝내지 않는다.

중요한 조사, 실험, 실패, 기술 선택, Metric, PAR 경험, 진행 상태를 Notion에도 기록한다.

기존 내용을 임의로 삭제하지 않는다.

---

## 45. Notion 기본 구조

```text
FactoryFlow MES Lab
00. Project Overview
01. Architecture & Roadmap
02. Samsung SDS Nexplant Research
03. Domain Model & State Machine
04. Experiment Log
05. Failure Cases
06. Performance Benchmark
07. PAR Experience
08. Technical Decisions
09. Operations & Recovery
10. Interview Notes
11. Final Portfolio
```

---

## 46. Samsung SDS Research 기록

공식 자료 조사 시 다음 형식을 사용한다.

- 기능명
- 삼성SDS 공식 자료 링크
- 공개된 내용
- 실제 제조에서 왜 필요한가
- 내 프로젝트에서 재현할 문제
- 내가 선택한 구현 기술
- 공개되지 않은 부분
- 주의할 표현

공식 홈페이지, 공식 소개서, 공식 고객사례를 우선한다.

---

## 47. Technical Decision 기록

예:

- SQLite vs PostgreSQL
- Direct Publish vs Transactional Outbox
- Kafka vs RabbitMQ vs Redis Streams
- Optimistic Lock vs Pessimistic Lock
- Polling Publisher vs CDC
- FIFO vs Priority Dispatching
- Sync Command vs Async Event
- Event Sourcing vs Current State + Event Journal

각 Decision:

- 문제
- 선택지 A
- A 장점
- A 단점
- 선택지 B
- B 장점
- B 단점
- 최종 선택
- 선택 근거
- 검증 결과

---

## 48. GitHub과 Notion의 역할

GitHub:

- 실제 코드
- Commit
- 테스트
- Config
- 실험 Script
- 재현 가능한 결과
- README

Notion:

- 문제 발견
- 의사결정
- 실험 목적
- 실험 결과
- 실패 사례
- 분석
- Metric
- PAR
- 면접용 정리

가능하면 Commit SHA와 Experiment 번호를 연결한다.

---

## 49. Roadmap 상태 관리

`ROADMAP.md`와 Notion의 `01. Architecture & Roadmap`을 함께 갱신한다.

예:

```text
현재 Phase
Phase 2 Lot State Machine

완료
[x] 정상 공정 진행
[x] HOLD/복구
[ ] 동시 Advance 정합성
[ ] Rework

현재 문제
동일 Lot에 대한 동시 요청 시 중복 Step 증가 가능성

다음 Action
동시 요청 재현 테스트와 DB Constraint/Lock 대안 비교
```

---

## 50. Phase 완료 조건

코드가 실행됐다는 이유만으로 완료하지 않는다.

다음을 만족해야 한다.

- 기능 구현
- 정상 Case 테스트
- Failure Case 테스트
- Metric 측정
- 실패 사례 수집
- 원인 분석
- 대안 비교
- 재현 가능한 실행 방법
- Experiment Log 기록
- Technical Decision 기록
- Git Commit
- 필요한 경우 Regression Test

---

## 51. Claude의 개발 진행 방식

각 Phase마다 반드시 다음 순서로 진행한다.

1. 이번 Phase 목표
2. 삼성SDS 공개 기능과의 연결
3. 제조 현장에서 왜 중요한가
4. 현재 코드와 Baseline 확인
5. 실험 전 Hypothesis
6. 구현 또는 재현 테스트
7. Metric 측정
8. Failure Case 확인
9. 원인 분석
10. 대안 A
11. A를 적용하지 않는 이유
12. 대안 B
13. B를 선택한 이유
14. 개선 구현
15. 동일 조건 재측정
16. Regression Test
17. PAR 후보 여부 판단
18. Git/Notion 기록

현재 Phase의 완료 조건을 만족하기 전에는 다음 Phase로 무리하게 넘어가지 않는다.

---

## 52. 코드를 설명하는 방식

전체 프로젝트 코드를 한 번에 제공하지 않는다.

사용자가 오류나 문제를 질문하면 수정 코드부터 던지지 않고 다음 순서로 설명한다.

1. 문제 위치
2. 왜 문제가 발생했는가
3. 제조 시스템에서 왜 중요한가
4. 현재 구조에서 어떤 문제가 있는가
5. 가능한 해결 방법
6. 선택한 해결 방법
7. 선택 이유
8. 수정 코드
9. 검증 방법과 실제 결과

사용자가 직접 이해하고 면접에서 설명할 수 있게 한다.

---

## 53. 실험 전 Hypothesis

중요한 실험 전에 가능한 경우 Hypothesis를 기록한다.

예:

```text
Hypothesis
동일 Lot에 대한 동시 Advance 요청을 Optimistic Lock으로 보호하면
중복 공정 진행은 제거되지만 충돌 요청의 Retry가 증가할 것이다.
```

결과가 반대여도 그대로 기록한다.

---

## 54. 최종적으로 확보할 문제 해결 경험

최소 3개 이상의 깊이 있는 PAR 경험을 확보한다. 억지로 만들지 않는다.

가능한 후보:

- Lot 상태 전이 정합성
- 동시 설비 배정 충돌
- Dispatching 규칙 개선
- 설비 Down/HOLD 복구
- 품질 이력과 원인 추적
- SQLite 동시 Write 병목과 PostgreSQL 전환
- DB/Broker Dual Write 문제와 Outbox
- 중복·역순 이벤트 처리
- Consumer Lag 또는 DLQ 복구
- P95/P99 성능 개선
- 장시간 실행 안정성

---

## 55. 최종 README

최종 README는 다음 흐름으로 구성한다.

1. 프로젝트 소개
2. 제조 실행 문제 정의
3. 삼성SDS Nexplant MES 공개 기능과의 연결
4. System Architecture
5. Domain Model
6. Work Order와 Lot State Machine
7. Scheduling & Dispatching
8. Equipment / Interlock
9. WIP / Traceability
10. Quality / Defect
11. OEE / KPI
12. Event Pipeline
13. Message Queue 도입 근거
14. Reliability / Recovery
15. Performance Benchmark
16. Failure Cases
17. 주요 Technical Decision
18. Before / After
19. Long Running Test
20. 프로젝트 한계
21. 실제 설비/SECS-GEM 확장 계획

문제 → 원인 → 가설 → 대안 비교 → 선택 → 구현 → 검증 → 결과 흐름을 강조한다.

---

## 56. 최종 면접 준비

프로젝트가 끝나면 실제 코드와 실험 근거로 다음 질문에 답할 수 있어야 한다.

- MES가 ERP와 다른 역할은 무엇인가?
- Work Order, Lot, Process Route는 어떻게 연결되는가?
- Lot 상태 전이를 어떻게 보호했는가?
- 같은 Lot에 동시 요청이 오면 어떻게 되는가?
- Dispatching 규칙은 무엇을 기준으로 선택했는가?
- 설비 Down과 Interlock을 어떻게 처리했는가?
- WIP와 Traceability는 어떻게 구현했는가?
- 불량 원인을 공정과 설비까지 어떻게 추적하는가?
- OEE의 각 항목을 어떻게 계산했는가?
- 왜 SQLite로 시작했고 언제 PostgreSQL로 바꿨는가?
- 메시지 큐가 정말 필요했던 문제는 무엇인가?
- 왜 Kafka/RabbitMQ/Redis Streams 중 하나를 선택했는가?
- 모든 요청을 비동기로 만들지 않은 이유는 무엇인가?
- DB Commit과 Event Publish 사이의 유실을 어떻게 막았는가?
- 중복 이벤트와 순서 역전을 어떻게 처리했는가?
- Consumer 장애 후 어떻게 복구했는가?
- 어떤 Workload로 성능을 측정했는가?
- VU, RPS, Event Rate, Business TPS 차이는 무엇인가?
- 가장 큰 실패 사례는 무엇이었는가?
- 개선 전후 실제 수치는 무엇인가?
- 실제 Nexplant 내부 구현과 내 프로젝트를 어떻게 구분하는가?

---

## 57. 작업 종료 규칙

하나의 의미 있는 작업이 끝날 때마다 다음 순서로 처리한다.

1. 코드와 실행 결과 확인
2. 실제 Metric 확인
3. Experiment Log 업데이트
4. Failure Case 기록
5. Technical Decision 기록
6. PAR 후보 판단
7. PAR 후보라면 PAR 9문항 작성
8. Architecture & Roadmap 갱신
9. Git Commit과 원격 상태 확인
10. 다음 Action 기록

그 뒤 사용자에게는 다음만 간단히 알려준다.

- 이번에 완료한 것
- 측정된 핵심 Metric
- 발견한 문제
- 선택한 해결 방법과 이유
- Notion에 기록한 내용
- PAR 생성 여부
- 다음 Action

---

## 58. 현재 첫 작업

아직 메시지 큐나 전체 기능을 한 번에 구현하지 않는다.

먼저 다음 작업을 수행한다.

1. 삼성SDS 공식 자료에서 Nexplant MES가 공개적으로 다루는 기능을 조사한다.
2. Scheduling & Dispatching, Manufacturing Operation, Equipment Engineering, Machine Control,
   Material Control의 역할과 연결 관계를 정리한다.
3. 현재 저장소의 코드, 테스트, 일일 리포트, ROADMAP을 검사한다.
4. 공식 공개 기능과 현재 구현 사이의 Gap Matrix를 작성한다.
5. 현재 Core MVP와 Stretch Goal을 재검토한다.
6. Domain Model과 Lot/Equipment State Machine 초안을 만든다.
7. 목표 Architecture와 동기 Command/비동기 Event 경계를 확정한다.
8. 메시지 큐는 현재 도입하지 않고, 먼저 Event Journal과 유실/중복 재현 실험을 설계한다.
9. `EXP-001 Current MES Baseline` 실험 계획을 작성한다.
10. 동시 Lot Advance, 설비 Down 복구, Dispatching 비교를 다음 실험 후보로 설계한다.
11. Experiment Template과 PAR 9문항 Template을 만든다.
12. 연결된 Notion에서 기존 MES 기록을 찾아 중복 없이 프로젝트 구조와 조사 결과를 기록한다.
13. 사용자가 조사 결과와 Architecture를 확인한 뒤 다음 구현을 시작한다.

이 단계에서는 대규모 리팩터링이나 메시지 큐 도입을 먼저 하지 않는다.

---

## 59. 최우선 원칙

이 프로젝트의 목적은 Kafka, RabbitMQ, FastAPI를 사용해본 사람이 되는 것이 아니다.

최종적으로 다음과 같은 개발자가 되는 것이 목표다.

제조 공정과 설비 데이터를 이해하고,
Lot과 작업지시의 정합성을 지키며,
실시간 이벤트와 동기 명령의 경계를 설계하고,
성능과 장애를 실제로 측정하고,
여러 해결 방법을 비교하며,
실패와 복구 과정을 코드와 데이터로 증명할 수 있는
MES·스마트팩토리·제조 플랫폼 엔지니어.

모든 기술 선택과 구현은 이 목표를 기준으로 판단한다.
