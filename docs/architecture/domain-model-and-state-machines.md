# Domain Model and State Machines

## Core Aggregate 후보

### WorkOrder

- work_order_no
- product_id
- planned_quantity
- released_quantity
- completed_quantity
- priority
- due_at
- status

구현 상태: CREATED → RELEASED → IN_PROGRESS → COMPLETED와 계획수량 조건부 예약을 지원한다.

### Lot

- lot_id
- work_order_id
- quantity
- route_version
- current_step
- status
- version

### LotEvent

- event_id
- lot_id
- sequence_number
- event_type
- process_step
- equipment_id
- from_status
- to_status
- occurred_at

### Equipment

- equipment_id
- process_step
- status
- recipe_capability
- last_heartbeat_at
- version
- dispatch_count

### QualityInspection

- inspection_id / lot_id / attempt_number
- process_step / equipment_id
- PASS/FAIL / defect_code
- NONE/PENDING/REWORK/SCRAP disposition
- inspected_at

## Lot State Machine 초안

```text
WAITING → PROCESSING → QUALITY_HOLD → DONE
   │          │              ├─→ REWORK → WAITING
   └─→ HOLD ──┘              └─→ SCRAPPED
```

현재 구현은 위 전이 Matrix와 검사·Defect·Disposition Event를 지원한다. 한 번의 Rework만 허용하며
두 번째 실패는 SCRAP Disposition을 요구한다.

## Equipment State Machine 초안

```text
IDLE → SETUP → RUN → IDLE
  │       │      │
  └───────┴──────┴→ DOWN → IDLE
                  └→ PM → IDLE
```

## 불변조건

- DONE Lot은 다시 진행할 수 없다.
- `step_index`는 공정경로 길이를 초과할 수 없다.
- 하나의 Lot Event sequence는 Lot 안에서 유일하다.
- 공정 완료 Event에는 해당 공정과 설비가 기록되어야 한다.
- HOLD는 가용 설비가 없을 때만 발생한다.
- 동일 상태에서 반복된 HOLD 요청은 중복 상태전이 Event를 만들지 않는다.
- 같은 Lot의 검사 시도차수는 유일하다.
- 검사 PASS 전에는 DONE으로 전이할 수 없다.
- 같은 공정 설비의 Dispatch Count 편차는 균등 Rule에서 최대 1건이다.
