# EXP-003 Work Order and Explicit Lot State Machine

## Goal

Product와 Work Order를 생산계획의 기준으로 추가하고, 계획수량을 초과하지 않는 Lot 분할과 명시적
Lot 상태 전이를 구현한다.

## Hypothesis

계획수량 예약 조건을 DB UPDATE에 포함하면 동시 Lot 분할에서도 `released_quantity <=
planned_quantity` 불변조건을 지킬 수 있다.

## Problem

기존 `/lots`는 Product Master나 생산계획 없이 임의 수량을 계속 생성했다. 애플리케이션 조회 후 수량을
검사하는 방식은 동시 요청 Race를 막지 못한다.

## Official MES Connection

Samsung SDS Nexplant MES 공식 자료의 Production Planning, Work Order, WIP Management 문제 영역과
연결한다. Product/WorkOrder Schema와 API는 프로젝트의 자체 구현이다.

## Implementation

- Product Master와 활성 여부
- Work Order CREATED → RELEASED → IN_PROGRESS → COMPLETED
- 중복 Work Order 번호 방지
- 미등록/비활성 Product Work Order 거부
- Work Order별 Lot 목록
- 계획수량 조건부 예약
- Lot 허용/금지 상태 전이 Matrix
- 연결된 Lot 전량 완료 시 Work Order 완료수량과 상태 갱신

## Tests

- 48 tests passed
- 미등록 Product 422
- 비활성 Product 409
- 중복 Work Order 번호 409
- Release 전 Lot 생성 409
- 계획 100에 40/35/25 성공, 추가 1 실패
- 동시 60/60 분할에서 한 건만 성공
- 전체 Route 완료 후 Work Order COMPLETED
- Lot 허용 전이 6개, 금지 전이 4개

## Load Workload

기존 Create/Advance/List/Metrics에 다음 흐름을 추가했다.

```text
Create Work Order
→ Release Work Order
→ Split Full-Quantity Lot
```

## Result

| Metric | Result |
|---|---:|
| Total Requests | 18,976 |
| Failure Rate | 0.00% |
| RPS | 105.68 |
| Average | 12.10 ms |
| P95 | 34 ms |
| P99 | 77 ms |
| Work Order Create | 878 |
| Work Order Release | 878 |
| Work Order Lot Create | 878 |
| Server 5xx | 0 |
| IntegrityError | 0 |

## Analysis

새 Work Order Command 2,634건이 모두 성공했다. 이전 EXP-002와는 Request Mix가 달라 RPS나 Latency를
개선 전후 수치로 직접 비교하지 않는다. 이번 결과를 Work Order 혼합 Workload의 새 Baseline으로
사용한다.

## Decision

Work Order 수량은 DB 조건부 UPDATE로 예약한다. 기존 직접 `/lots` API는 회귀 부하 기준을 위해 Legacy
경로로 유지하되, 포트폴리오의 정상 생산 흐름은 Work Order 경로를 기준으로 한다.

## PAR Candidate

아직 실제 장애를 해결한 경험이 아니라 설계 단계에서 동시성 위험을 방지한 것이므로 PAR로 만들지
않는다.

## Next Action

Quality Inspection, Defect Code, Scrap/Rework를 추가하고 랜덤 Scrap Flag를 추적 가능한 품질 결과로
대체한다.

