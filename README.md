# MES Load & Metrics Simulator

[![CI](https://github.com/won-seoop/mes-load-simulator/actions/workflows/ci.yml/badge.svg)](https://github.com/won-seoop/mes-load-simulator/actions/workflows/ci.yml)

Samsung SDS Nexplant MES가 다루는 도메인 개념(설비 가동률, 로트/WIP 추적, 공정 경로, 수율, 처리량)을
참고해서 만든 오픈소스 기반 미니 MES 시뮬레이터입니다. FastAPI로 MES API를 구현하고, Locust로
매일 부하테스트를 돌려 성능 지표(RPS, p95/p99 latency, 실패율)와 MES 비즈니스 지표(WIP, 수율,
평균 사이클타임, 설비 가동률, 시간당 처리량)를 함께 수집합니다.

클라우드 스케줄러(Claude Code Routine)가 매일 오전 7시(KST)에 이 저장소를 체크아웃해서
`scripts/run_daily_test.sh`를 실행하고, 결과를 `reports/`에 커밋한 뒤 Notion에 요약을 정리합니다.

## Domain Model

- **Equipment**: 공정 스텝(ETCH → CVD → CMP → INSPECT)별 설비, 상태(RUN/IDLE/DOWN), 가동 시간 누적
- **Lot**: 제품/수량, 현재 공정 스텝, 상태(WAITING/PROCESSING/DONE/HOLD), scrap 여부

## API

- `GET /health`
- `GET /equipment`, `PATCH /equipment/{id}/status`
- `POST /lots`, `GET /lots`, `GET /lots/{id}`, `POST /lots/{id}/advance`
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
