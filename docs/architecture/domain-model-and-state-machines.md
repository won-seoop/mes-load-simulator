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

## Lot State Machine 초안

```text
CREATED → RELEASED → WAITING → PROCESSING → COMPLETED
                       │           │
                       ├─→ HOLD ←──┤
                       │           ├─→ REWORK → WAITING
                       └───────────→ SCRAPPED
```

현재 구현은 WAITING/PROCESSING/HOLD/DONE만 지원한다. 첫 단계에서는 기존 API 호환성을 유지하면서
상태 변경 Event를 남긴다. 이후 별도 실험으로 상태를 확장한다.

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

