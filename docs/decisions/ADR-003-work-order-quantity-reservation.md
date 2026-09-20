# ADR-003: Work Order 계획수량 예약 방식

- 상태: Accepted
- 날짜: 2026-09-20
- 영향: High

## Context

Work Order의 계획수량보다 많은 Lot을 분할하면 생산계획과 실제 WIP가 즉시 불일치한다. 단순히
`released + request <= planned`를 애플리케이션에서 조회한 뒤 저장하면 동시 요청 두 개가 같은 잔여
수량을 보고 모두 통과할 수 있다.

## Options

### A. 조회 후 애플리케이션 Validation

구현은 단순하지만 Check와 Update 사이에 Race가 있다.

### B. DB 조건부 UPDATE로 수량 예약

`released_quantity + request <= planned_quantity` 조건을 UPDATE 자체에 포함한다. 한 요청이 먼저
수량을 예약하면 뒤 요청은 0 rows를 반환받고 409가 된다.

## Decision

B를 선택한다. Lot과 WorkOrderLot 연결, Lot 생성 Event도 같은 Transaction에 저장한다.

## Validation

- 계획 100에 40 + 35 + 25 분할 성공, 추가 1은 409
- 계획 100에 동시 60 + 60 요청: 200 한 건, 409 한 건
- 최종 Released Quantity 60, 생성 Lot 1개
- Work Order 혼합 50 VU/3분: Work Order 각 단계 878건, 전체 Failure 0, 5xx 0

