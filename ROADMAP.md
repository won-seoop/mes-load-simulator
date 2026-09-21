# Roadmap

모든 작업은 먼저 루트의 `CLAUDE.md`에 정의된 프로젝트 지침, 공식 자료 구분 원칙, 실험·검증·PAR
기준을 따른다.

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
- [x] (2026-09-20) Lot Event Journal과 `GET /lots/{id}/events`를 추가해 Lot 생성, HOLD, 복구,
      공정 완료, 최종 완료를 같은 Transaction에 기록. 첫 50 VU/3분 부하에서 동시 Advance가 같은
      Event Sequence를 생성해 27건의 500을 발생시키는 문제를 발견했다. 프로세스 내부 Lock 대신
      `lot_id + status + step_index` 조건부 UPDATE를 적용해 한 요청만 상태를 전이시키고 경쟁 요청은
      409로 분리했다. 동시성 회귀 테스트를 포함해 29개 테스트가 통과했고, 재측정 17,869건에서
      실패 0건, Server 5xx 0건, IntegrityError 0건, 예상 409 충돌 34건을 확인했다. 개발 중이던
      다른 8000 포트 서버에 부하가 잘못 들어간 무효 실행도 발견해 부하 서버를 전용 18080 포트로
      분리하고 PID/Health 검증을 추가했다. EXP-002, ADR-002, PAR-001에 근거를 기록했다.
- [x] (2026-09-20) Product Master, Work Order와 명시적 Lot State Machine 추가. 미등록/비활성
      Product, 중복 작업지시 번호, Release 전 Lot 생성, 계획수량 초과를 거부한다. 계획 100에 동시
      60/60 Lot 분할 시 DB 조건부 UPDATE로 한 건만 성공해 Released Quantity 60을 유지했다. 전체
      48개 테스트 통과. Work Order 생성→Release→Lot 분할을 포함한 별도 50 VU/3분 EXP-003에서
      18,976 requests, 0 failures, 105.68 RPS, P95 34ms, P99 77ms, Work Order 각 단계 878건,
      Server 5xx 0을 측정했다. Workload 구성이 달라 EXP-002와 직접 성능 비교하지 않는다.
- [x] (2026-09-20) Quality Inspection, Defect Code, Scrap/Rework와 설비 추적 구현. 첫 부하에서 최대
      4차까지 반복되는 Rework Loop를 발견해 한 번의 재작업만 허용하고 두 번째 실패는 Scrap을
      요구하도록 수정했다. 동일 50 VU/3분 재측정에서 최대 검사차수 4→2, 3차 이상 5→0,
      18,050 requests, 실패/5xx/IntegrityError 0을 확인했다. EXP-004, ADR-004, PAR-002에 기록했다.
- [x] (2026-09-20) Run Time이 균등해도 실제 검사 배정은 1/1/268로 편향된 Metric Blind Spot을 발견.
      Equipment `dispatch_count`를 1차 Dispatch 기준으로 추가해 79/80/79로 균등화했다. 같은 공정
      Peer 불량률 Baseline이 INSPECT-03의 27.85% vs Peer 0%를 WARNING으로 탐지했다. EXP-005는
      17,982 requests, 실패 0, p95 150ms, p99 370ms, 5xx/IntegrityError 0이었다.
- [x] (2026-09-20) C# Avalonia XAML + MVVM Operator Console 구현. 실제 FastAPI에서 WIP/작업지시/
      설비/품질/이상 데이터를 조회하며 .NET 10 Release Build 오류·경고 0을 확인했다.
- [x] (2026-09-20) 공식 MCP Python SDK 기반 read-only MES Gateway 구현. Overview/Lot Trace Resource와
      품질 이상/Lot 추적/작업지시 Tool을 제공하며 In-memory MCP Smoke Test에서 INSPECT-03 WARNING을
      실제 호출해 확인했다. A2A 역할과 Command Safety 경계는 Architecture/ADR-006에 기록했다.
- [x] (2026-09-21) 설비 다운으로 인한 HOLD 대기시간을 `/metrics`에 노출. 기존 Lot 테이블은 로트가
      HOLD라는 사실만 보여주고 언제부터 대기 중인지는 알 수 없어 병목 판단이 불가능했는데, 이미
      기록 중이던 `LOT_HELD`/`LOT_RELEASED_FROM_HOLD` Event Journal을 짝지어 `lots_on_hold_count`,
      `longest_current_hold_seconds`, `avg_resolved_hold_seconds`를 계산하는 `_equipment_hold_wait_metrics`를
      추가했다(해소되지 않은 값은 `avg_resolved_hold_seconds`를 `None`으로 유지 — 값을 지어내지 않음).
      Freeze-time 기반 pytest 3개(대기 0건 baseline, 진행 중 대기 330초, 해소된 대기 120초)로 정확한
      초 단위 계산을 검증했고, 실행 중인 서버에 curl로 직접 HOLD를 만들고 해제하는 수동 스모크
      테스트로도 동일하게 확인했다. 이 지표를 실제 부하테스트에서 관찰하려면 설비 Down이 필요한데
      기존 Locust 시나리오에는 설비 Down/복구가 전혀 없어서, 저확률 Fault Injection Task 2개
      (`fault_inject_equipment_down`, `fault_recover_equipment`)를 추가했다. 첫 시도(매번 실행,
      확률 Gate 없음)는 3분간 설비 상태를 579회 DOWN시켜 12대 설비가 평균 48회씩 뒤집혔고, 그 결과
      완료 로트가 평소 270~320건에서 149건으로 급감하고 702개 로트가 미해소 HOLD로 쌓이는 실패
      사례를 만들었다 — 삭제하지 않고 `FAULT_DOWN_PROBABILITY` 상수 도입 근거로 `load_test/locustfile.py`
      주석에 그대로 남겼다. `FAULT_DOWN_PROBABILITY=0.05`로 낮추자 완료 로트 207~219건, WIP 2369~2497건으로
      전일 EXP-005 Baseline(완료 216건, WIP 2648건)과 같은 범위로 돌아왔다. 다만 이 확률에서는 같은
      공정의 설비 3대가 동시에 모두 DOWN되는 경우가 드물어(해당 실행에서 다운 29회/복구 32회에도
      HOLD 0건) 일일 부하테스트가 새 지표를 매번 관측하지는 못했는데, `/metrics`를 실행 끝에 한 번만
      읽으면 이미 해소된 짧은 HOLD도 놓칠 수 있어서 `scripts/run_daily_test.sh`가 10초 간격으로
      `/metrics`를 백그라운드로 샘플링해 `mes_metrics_samples.jsonl`에 남기고, `scripts/summarize.py`가
      실행 중 관측된 최대 HOLD 로트 수/최대 대기시간을 리포트에 추가로 표기하도록 했다. 65개 pytest
      전체 통과, 50 VU/3분 파이프라인 정상 동작(실패율 0%, Server 5xx/IntegrityError 0)을 재확인했다.
- [x] (2026-09-21) 실시간 웹 대시보드 추가. 지금까지 지표를 보려면 `/metrics`, `/equipment` 등을
      직접 curl하거나 C# 데스크톱 앱을 빌드/실행해야 했는데, 브라우저(특히 폰)에서 바로 볼 수 있는
      화면이 없었다. `app/static/index.html`(의존성 없는 순수 HTML/CSS/JS, 4초 간격 폴링)을 만들어
      `StaticFiles(html=True)`로 `/`에 마운트했다. API 라우트들보다 뒤에 등록해서(Starlette는 라우트를
      등록 순서대로 매칭) `/health`, `/metrics` 같은 기존 경로를 절대 가리지 않는지 확인했다. 화면은
      WIP/완료/수율/사이클타임/HOLD대기 카드, 설비 12대 상태, 작업지시·로트 테이블, 품질 이상 목록을
      보여준다. work order 생성→release→lot 분할→advance까지 실제 호출로 데이터를 채워 모든 위젯이
      올바른 필드로 렌더링되는지 확인했고, pytest 65개 전체 통과도 재확인했다. 인증이 없는 서버이므로
      0.0.0.0 대신 Tailscale 사설망 주소(100.71.82.85:8020)에만 bind해서 노트북 자신에서의 접속은
      curl로 확인했다; 같은 tailnet의 아이폰에서 실제로 열리는지는 사용자 확인이 필요하다.
      reports/ 히스토리를 그래프로 보여주는 일자별 트렌드 대시보드는
      별개 항목으로 아래에 남겨둔다(이번 것은 실시간 현재 상태만 보여줌, 과거 추이는 아직 없음).
- [x] (2026-09-21) 자율 시뮬레이션 엔진 추가. 위 대시보드는 만들었지만 Locust 부하테스트는 외부에서
      API를 두드리는 용도라 서버를 그냥 띄워만 놓으면 화면에 아무 움직임이 없었다 — 사용자가 "실제
      시뮬레이션하게 UI 만들어야지"라고 정확히 이 문제를 지적했다. `app/simulation.py`에
      `SimulationEngine`을 추가했다: 1초마다 tick하면서 (a) 도착 간격마다 새 로트를 투입하고,
      (b) 각 로트가 현재 공정에 실제로 6~14초(설정 가능) 머무른 뒤에만 다음 공정으로 넘어가게 하고,
      (c) 설비를 낮은 확률로 랜덤 DOWN시켰다가 일정 시간 후 복구시키고, (d) QUALITY_HOLD 로트를
      자동 검사(불량률 설정 가능)해서 합격/불합격, 1회 REWORK, 재발 시 SCRAP까지 판정한다. 핵심
      설계 결정은 이 엔진이 상태 전이 로직을 절대 재구현하지 않는다는 것이다 — `advance_lot`,
      `inspect_lot`, `disposition_lot`, `release_rework`, `set_equipment_status`, `create_lot`을
      `app.main`에서 그대로 가져와 호출한다(순환 임포트를 피하려고 tick 시점에 지연 임포트). 그래서
      시뮬레이션 시계가 만든 상태와 사람이 curl로 만든 상태가 절대 어긋날 수 없다. `POST
      /simulation/start`·`/stop`·`GET /simulation/status`를 추가했는데, 이 세 개만 `async def`로
      선언했다 — FastAPI의 동기 `def` 라우트는 스레드풀에서 실행되어 그 스레드에는 실행 중인 asyncio
      루프가 없으므로 그 안에서 `asyncio.create_task()`를 호출하면 실패한다.
      `_tick_once(now=...)`가 순수 동기 함수라 asyncio 없이도 직접 단위테스트할 수 있게 설계했고,
      `tests/test_simulation.py`에 로트가 4단계를 거쳐 QUALITY_HOLD까지 가는 것, 설비 전체가
      DOWN되면 로트가 HOLD됐다가 복구 후 재개되는 것, 설비가 DOWN→복구 스케줄대로 동작하는 것,
      그리고 실제 `POST /simulation/start`로 백그라운드 태스크가 살아서 tick이 올라가는 것까지
      확인하는 테스트 7개를 추가했다(전체 72개 통과). 로컬에서 20초간 실제로 돌려서 로트 7건 투입,
      ETCH→CVD 진행, 설비 2대 DOWN/복구가 로그에 실시간으로 찍히는 것을 직접 확인했다. 대시보드에
      시작/정지 버튼, tick 카운터, 최근 이벤트 피드, 공정별 진행 중 로트 수 막대를 추가해서 실제로
      "돌아가는 공장"처럼 보이게 했다.
- [x] (2026-09-21) 대시보드를 실제 MES 형태의 좌측 GNB + 상단바 구조로 재구성. 이전까지는 모든
      위젯이 한 페이지에 세로로 쌓여 있어서 정보가 많아질수록 스크롤이 길어지기만 했는데, 실제 MES
      제품들처럼 대시보드/설비현황/작업지시/로트-WIP/품질/시뮬레이션을 별도 화면(탭)으로 분리했다
      (Samsung SDS Nexplant의 실제 UI·로고는 상표라 그대로 베끼지 않고, 좌측 GNB + 상단바 + 브랜딩
      영역이라는 구조만 참고해서 이 프로젝트 자체 브랜드 "FactoryFlow"로 만들었다 — C# 데스크톱 앱과
      이름을 통일). 새로 추가한 것: (1) 설비 화면에 RUN/IDLE/DOWN 수동 제어 버튼(PATCH
      `/equipment/{id}/status` 재사용), (2) 작업지시 화면에 실제 생성 폼(주문번호/제품/수량/우선순위)과
      Release 버튼, (3) 로트 화면에 상태 필터와 행 클릭 시 우측에서 열리는 이벤트 타임라인
      드로어(`GET /lots/{id}/events` 재사용, 실시간 트레이서빌리티), (4) 품질 화면에 공정별·설비별
      불량 집계 테이블(`defects_by_process`, `defects_by_equipment` — 이미 API에는 있었지만 화면에
      노출된 적은 없었음). 폰 폭(<760px)에서는 좌측 GNB가 상단 가로 탭으로 접히도록 반응형 처리했다.
      새 작업지시 생성→Release→시뮬레이션 시작→로트 진행→검사 이벤트가 타임라인 드로어에 그대로
      찍히는 것까지 curl로 전 구간 직접 확인했고, 백엔드 로직은 손대지 않아 pytest 72개 그대로
      통과한다.

## 다음 후보 (우선순위 순서는 참고용, 상황 따라 조정 가능)

- [ ] A2A Quality Investigation Agent: Agent Card, Task 상태, 조사 Artifact와 승인 Gate
- [ ] C# UI LOT 검색/Event Timeline과 Work Order 상세 화면
- [ ] 품질 이상 신호에서 관련 LOT/검사/Event 자동 Drill-down
- [ ] PostgreSQL 전환 후 조건부 UPDATE vs `SELECT FOR UPDATE` 동시성 비교
- [ ] OEE(설비종합효율 = 가동률 x 성능 x 양품률) 지표 계산 및 `/metrics`에 추가
- [ ] 설비 다운타임/알람 이벤트 모델 (DOWN 상태 발생·복구 이력 기록)
- [ ] 전일 대비 이상 탐지 고도화 (단순 임계치 대신 최근 N일 평균/표준편차 기반)
- [ ] Locust 우선순위 로트/배치 사이즈 변화 시나리오 (설비 랜덤 다운은 2026-09-21에 추가 완료)
- [ ] 같은 공정 스텝의 설비를 한꺼번에 묶어 내리는 "스텝 전체 다운" Fault 추가 — 현재의 개별 설비
      독립 확률 다운(`FAULT_DOWN_PROBABILITY=0.05`)만으로는 3대가 동시에 모두 DOWN될 확률이 낮아
      일일 부하테스트가 HOLD 대기시간 지표를 매번 실제로 관측하지 못한다(2026-09-21 리포트 참고).
      이 Fault를 추가하면 회귀 테스트가 매 실행마다 최소 1회 이상 HOLD/복구 사이클을 안정적으로
      재현할 수 있다.
- [ ] SQLite -> Postgres 전환 옵션 (docker-compose, 동시성 부하테스트에 더 현실적)
- [ ] 일자별 트렌드를 보여주는 간단한 대시보드 (정적 HTML + Chart.js, reports/ 데이터를 읽어서 생성)
- [ ] API 인증(JWT 또는 API key) 추가
- [ ] Dockerfile 작성 (배포/실행 편의성)
- [ ] README에 아키텍처 다이어그램 추가
- [ ] 구조화된 로깅 (structlog 등) 및 요청 추적 ID
- [ ] `reports/raw/<date>/`의 locust CSV/서버 로그가 무기한 누적되므로 보관 기간 정책
      (예: N일 지난 raw 데이터는 압축하거나 삭제) 추가
- [ ] CI(`ci.yml`)에 ruff(lint/format)와 `pytest-cov` 커버리지 리포트 단계 추가 — 지금은
      테스트 통과 여부만 보고 코드 스타일이나 커버리지는 확인하지 않음
- [ ] Pydantic class Config와 FastAPI `on_event` deprecation warning 제거

## 에이전트 작업 원칙

- 매일 최소 1개 항목을 실제로 구현하고 검증(테스트 또는 스모크 테스트) 후 커밋합니다.
- 리스크가 크거나 사용자 판단이 필요한 항목(과금되는 외부 서비스, 큰 아키텍처 변경 등)은 건너뛰고
  리포트의 "사용자에게 요청" 항목에 이유와 함께 남깁니다.
- 항목을 완료하면 체크 표시하고, 새로운 개선 아이디어를 최소 1개 이상 추가해 백로그를 유지합니다.
- 매일의 변경 이력은 git 커밋 로그와 `reports/`, 이 파일의 "완료" 섹션에 남아 그 자체로 성장 과정을
  보여주는 포트폴리오 스토리가 됩니다.
