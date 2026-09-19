# Roadmap

이 프로젝트는 매일 클라우드 에이전트(Claude Code Routine)가 자동으로 실행하며, 단순히 부하테스트만
반복하는 게 아니라 **매일 이 백로그에서 우선순위가 높은 항목을 스스로 판단해서 하나씩 구현**합니다.
완료한 항목은 체크하고 커밋 메시지/리포트에 무엇을 왜 바꿨는지 남기며, 백로그가 마르지 않도록
새 개선 아이디어를 최소 1개 이상 추가합니다.

## 완료

- [x] FastAPI 기반 MES 도메인 API (설비/로트/공정경로/수율)
- [x] Locust 부하테스트 + 일일 리포트(md/json) 파이프라인
- [x] Notion 자동 리포트 DB 연동
- [x] (2026-09-17) Locust `advance_lot` 태스크가 WAITING 상태만 조회해서 로트가 1단계 이후
      멈추던 버그 수정 — PROCESSING 상태도 함께 조회하도록 수정
- [x] (2026-09-17) pytest 기반 단위/통합 테스트 19개 추가 (API 엔드포인트, 공정 진행 로직,
      설비 다운/HOLD/재개 시나리오). 테스트를 작성하는 과정에서 실제 버그 2건을 발견해 함께 수정:
      (1) 한 번 HOLD가 된 로트는 설비가 복구돼도 영원히 advance 불가능했던 문제
      (`advance_lot`이 DONE/HOLD를 동일하게 차단), (2) 평균 사이클타임이 정확히 0초일 때
      `if avg_cycle else None`의 falsy 0 판정 때문에 지표가 `None`으로 숨겨지던 문제.
      `scripts/run_daily_test.sh`가 부하테스트 전에 `pytest tests/`를 먼저 실행하도록 연결.
- [x] (2026-09-18) 설비 선택 로직을 최소 가동시간 우선(least-utilized-first)으로 개선.
      기존 `advance_lot`은 `Equipment.status != DOWN`인 설비 중 쿼리 결과의 첫 번째(`.first()`)만
      골랐는데, SQLite 기본 정렬 순서가 항상 같아서 스텝당 3대 중 `-01` 설비만 계속 선택되고
      나머지 2대는 가동률 0%로 남는 문제가 있었다(어제 리포트의 `equipment_utilization` 참고:
      `ETCH-01: 179.6`, `ETCH-02/03: 0.0`). `_effective_run_seconds` 헬퍼(현재 RUN 중이면
      누적시간에 진행 중인 시간까지 더해서 계산, `/metrics`와 로직 공유)로 스텝별 가용 설비 중
      누적 가동시간이 가장 적은 설비를 매번 다시 계산해서 배정하도록 변경. 오늘 50명/3분
      부하테스트에서 스텝당 3대 모두 176~180s로 고르게 가동됨을 확인했고(수정 전: 1대만
      178~180s, 2대는 0.0), 실제 3대 병렬 처리 용량이 살아나면서 오늘 완료 로트 수도
      280 -> 322건으로 늘었다. 회귀 테스트
      (`test_advance_lot_load_balances_across_equipment_of_same_step`) 추가.
- [x] (2026-09-19) 리포트 날짜/`completed_today` 집계 기준을 UTC에서 KST로 통일. 스케줄러는
      매일 오전 7시 **KST**에 도는데 `scripts/run_daily_test.sh`는 `date -u`로, `/metrics`의
      `completed_today`는 `datetime.utcnow()` 자정 기준으로 "오늘"을 계산하고 있어서, KST
      00:00~08:59 사이에 도는 실행은 리포트 날짜와 당일 완료 집계가 실제 KST 날짜보다 하루
      전으로 찍히는 버그가 있었다(전날 리포트에 이미 기록된 문제). 실제로 이번 실행 시각이
      UTC 2026-09-18 22:12 = KST **2026-09-19 07:12**여서 고치기 전이었다면 이 실행 결과가
      `reports/2026-09-18.md`(혹은 더 나쁘게 이미 있던 파일)를 잘못된 날짜로 덮어썼을
      상황이었는데, 수정 후 정확히 `reports/2026-09-19.md`로 생성됨을 확인했다. 새 모듈
      `app/timeutils.kst_midnight_utc(now_utc)`(naive-UTC 입력을 받아 그 시각이 속한 KST
      달력일의 자정을 naive-UTC로 반환하는 순수 함수)를 추가해 `/metrics`의 `today_start`
      계산에 사용하고, `scripts/run_daily_test.sh`의 `RUN_DATE`는 `TZ=Asia/Seoul date`로
      변경했다. `tests/test_timeutils.py`(경계값 3건)와 `tests/test_process_flow.py`의
      `test_completed_today_resets_at_kst_midnight_not_utc_midnight`(KST 자정을 사이에 두고
      완료된 두 로트로 `completed_today`가 KST 기준으로만 리셋됨을 검증, `datetime.utcnow`를
      monkeypatch로 고정하는 방식 사용)를 추가했다. 50명/3분 부하테스트로 파이프라인 전체가
      정상 동작함을 재확인(실패율 0%, RPS 99.36, 완료 318건).
- [x] (2026-09-20) GitHub Actions CI 추가. 지금까지 24개짜리 pytest 스위트가 있어도 실제로 매
      push/PR마다 자동 실행되는 곳이 없어서, 로컬에서 돌리는 걸 깜빡하면 깨진 코드가 그대로
      머지될 수 있었다(포트폴리오로서도 "테스트가 있다"보다 "CI가 초록불이다"가 더 설득력 있는
      신호). `.github/workflows/ci.yml`을 추가해 master push와 master 대상 PR마다 Python
      3.11/3.12 매트릭스로 `pytest tests/ -v`를 돌리도록 설정했고, README에 CI 배지를 달았다.
      로컬에서 동일한 커맨드로 24개 테스트가 통과하는 것을 확인했고, `scripts/run_daily_test.sh`
      전체 파이프라인도 다시 정상 동작함을 재확인(실패율 0%, RPS 98.59, p95 48ms/p99 110ms,
      완료 272건 — DB가 매 실행마다 초기화되므로 전날과 절대치 비교는 무의미하고 추세만 참고).
      실행 시각이 이미 KST 2026-09-20 07:10이라 어제 고친 KST 기준 날짜 계산이 실제로
      `reports/2026-09-20.md`를 정확히 만들어내는 것도 함께 확인했다.

## 다음 후보 (우선순위 순서는 참고용, 상황 따라 조정 가능)

- [ ] OEE(설비종합효율 = 가동률 x 성능 x 양품률) 지표 계산 및 `/metrics`에 추가
- [ ] 설비 다운타임/알람 이벤트 모델 (DOWN 상태 발생·복구 이력 기록)
- [ ] 전일 대비 이상 탐지 고도화 (단순 임계치 대신 최근 N일 평균/표준편차 기반)
- [ ] Locust 시나리오 다양화 (설비 랜덤 다운, 우선순위 로트, 배치 사이즈 변화)
- [ ] SQLite -> Postgres 전환 옵션 (docker-compose, 동시성 부하테스트에 더 현실적)
- [ ] 일자별 트렌드를 보여주는 간단한 대시보드 (정적 HTML + Chart.js, reports/ 데이터를 읽어서 생성)
- [ ] API 인증(JWT 또는 API key) 추가
- [ ] Dockerfile 작성 (배포/실행 편의성)
- [ ] README에 아키텍처 다이어그램 추가
- [ ] 구조화된 로깅 (structlog 등) 및 요청 추적 ID
- [ ] 설비 다운/HOLD가 반복될 때 HOLD 상태로 머무는 시간(대기시간)을 지표로 노출 —
      현재는 HOLD로 빠진 로트가 언제부터 대기 중인지 알 수 없어 실제 병목 파악이 어려움
- [ ] `reports/raw/<date>/`의 locust CSV/서버 로그가 무기한 누적되므로 보관 기간 정책
      (예: N일 지난 raw 데이터는 압축하거나 삭제) 추가
- [ ] CI(`ci.yml`)에 ruff(lint/format)와 `pytest-cov` 커버리지 리포트 단계 추가 — 지금은
      테스트 통과 여부만 보고 코드 스타일이나 커버리지는 확인하지 않음

## 에이전트 작업 원칙

- 매일 최소 1개 항목을 실제로 구현하고 검증(테스트 또는 스모크 테스트) 후 커밋합니다.
- 리스크가 크거나 사용자 판단이 필요한 항목(과금되는 외부 서비스, 큰 아키텍처 변경 등)은 건너뛰고
  리포트의 "사용자에게 요청" 항목에 이유와 함께 남깁니다.
- 항목을 완료하면 체크 표시하고, 새로운 개선 아이디어를 최소 1개 이상 추가해 백로그를 유지합니다.
- 매일의 변경 이력은 git 커밋 로그와 `reports/`, 이 파일의 "완료" 섹션에 남아 그 자체로 성장 과정을
  보여주는 포트폴리오 스토리가 됩니다.
