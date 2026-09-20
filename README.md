# MES Load & Metrics Simulator

[![CI](https://github.com/won-seoop/mes-load-simulator/actions/workflows/ci.yml/badge.svg)](https://github.com/won-seoop/mes-load-simulator/actions/workflows/ci.yml)

> 프로젝트의 개발 원칙, Nexplant MES 공개 자료와 자체 구현의 구분, 단계별 실험·검증 방식은
> [`CLAUDE.md`](CLAUDE.md)를 기준으로 합니다.

Samsung SDS Nexplant MES가 다루는 도메인 개념(설비 가동률, 로트/WIP 추적, 공정 경로, 수율, 처리량)을
참고해서 만든 오픈소스 기반 미니 MES 시뮬레이터입니다. FastAPI로 MES API를 구현하고, Locust로
매일 부하테스트를 돌려 성능 지표(RPS, p95/p99 latency, 실패율)와 MES 비즈니스 지표(WIP, 수율,
평균 사이클타임, 설비 가동률, 시간당 처리량)를 함께 수집합니다.

클라우드 스케줄러(Claude Code Routine)가 매일 오전 7시(KST)에 이 저장소를 체크아웃해서
`scripts/run_daily_test.sh`를 실행하고, 결과를 `reports/`에 커밋한 뒤 Notion에 요약을 정리합니다.

## Domain Model

- **Equipment**: 공정 스텝(ETCH → CVD → CMP → INSPECT)별 설비, 상태(RUN/IDLE/DOWN), 가동 시간 누적
- **Product / WorkOrder**: 활성 제품, 계획수량/납기/우선순위, Release와 Lot 분할 수량
- **Lot**: 제품/수량, 현재 공정 스텝, 상태(WAITING/PROCESSING/DONE/HOLD), scrap 여부
- **LotEvent**: 생성/HOLD/복구/공정완료/최종완료의 순서가 보장된 Lot 이력

## API

- `GET /health`
- `GET /equipment`, `PATCH /equipment/{id}/status`
- `GET/POST /products`
- `POST/GET /work-orders`, `GET /work-orders/{id}`
- `POST /work-orders/{id}/release`, `POST/GET /work-orders/{id}/lots`
- `POST /lots`, `GET /lots`, `GET /lots/{id}`, `POST /lots/{id}/advance`
- `GET /lots/{id}/events` — 공정, 설비, 상태 전이 Traceability
- `GET /metrics` — WIP, 완료 수, 수율, 평균 사이클타임, 설비 가동률, 시간당 처리량

## Local run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Daily load test

```bash
bash scripts/run_daily_test.sh
```

50명의 가상 유저로 3분간 부하를 주고 `reports/raw/<date>/`에 원본 데이터를,
`reports/<date>.md` / `reports/<date>.json`에 요약 리포트를 남깁니다.

부하 테스트 서버는 개발 서버와의 포트 충돌을 막기 위해 기본적으로 `127.0.0.1:18080`을 사용합니다.
예상 가능한 동시 상태 경쟁은 HTTP 409로 반환하고, 리포트에서 Server 5xx와 별도로 집계합니다.
