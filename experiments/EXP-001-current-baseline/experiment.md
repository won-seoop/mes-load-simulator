# EXP-001 Current MES Baseline

## Goal

현재 FastAPI + SQLite MES Simulator의 기능과 50 VU/3분 부하 결과를 후속 개선의 기준으로 고정한다.

## Hypothesis

현재 시스템은 HTTP 실패 없이 약 100 RPS를 처리하지만, Lot Event 이력이 없어 Traceability 요구를
충족하지 못하고 WIP가 계속 누적될 것이다.

## Problem

최종 상태와 집계 수치만으로는 Lot이 어떤 설비와 공정을 거쳤는지 복원할 수 없다.

## Official MES Connection

Samsung SDS 공식 Nexplant MES 자료의 WIP Management, Real-Time Production Tracking & Traceability,
Quality Control 문제 영역과 연결된다.

## Workload

- Locust 50 VU
- Spawn rate 5 users/s
- Duration 3 minutes
- Lot create/advance, equipment list, metrics 혼합

## Environment

- Date: 2026-09-19 KST
- Commit SHA: `4eb3a36906b4915239fd9d6afa881103580df051`
- Runtime: Python / FastAPI 단일 프로세스
- Database: SQLite
- Instance count: 1

## Baseline Result

`reports/2026-09-19.json`의 기존 측정 결과다.

| Metric | Result |
|---|---:|
| HTTP Requests | 17,810 |
| HTTP Failure Rate | 0.00% |
| RPS | 99.36 |
| P95 | 35 ms |
| P99 | 74 ms |
| Completed Lots | 318 |
| WIP | 2,544 |
| Yield | 93.82% |
| Avg Cycle Time | 12.6 s |

## Failure Cases / Gaps

- WIP가 2,544개로 완료 318개보다 크게 누적되었다.
- Lot별 공정·설비 이력이 없어 병목 원인을 Lot 단위로 확인할 수 없다.
- Random Scrap만 있어 불량 원인을 공정/설비와 연결할 수 없다.
- 동시 Advance의 정합성은 아직 검증되지 않았다.

## Decision

첫 개선은 메시지 큐가 아니라 Transaction 안에 `LotEvent`를 저장하는 Event Journal로 한다.

## Regression Test

- Lot 생성 Event
- 공정 완료 Event의 공정/설비 기록
- HOLD와 복구 Event
- Sequence 순서
- 전체 Route 완료 Event

## Next Action

`EXP-002 Lot Event Journal and Traceability`를 구현하고 동일 테스트를 다시 실행한다.

