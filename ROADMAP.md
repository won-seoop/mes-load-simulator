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
- [x] (2026-09-21) HOLD 로트가 마지막 공정에서 영원히 멈추는 버그 수정. 자율 시뮬레이션 엔진을
      껐다 켜지 않고 108분(tick 6495)간 무인으로 돌려봤더니, INSPECT에서 설비다운으로 HOLD된
      로트가 복구 후 완료(QUALITY_HOLD)로 못 넘어가는 상태전이 누락(`ALLOWED_LOT_TRANSITIONS[HOLD]`가
      `{PROCESSING}`만 허용) 때문에 `ensure_lot_transition`이 매 tick `ValueError`를 던졌다. 그런데
      `_advance_due_lots`가 `HTTPException`만 잡고 있어서 이 예외가 tick 전체를 abort시켰고, 실패한
      로트가 재스케줄되지 않아 다음 tick에도 또 맨 먼저 실패해 같은 tick의 나머지 로트까지 전부
      막았다 — 그 결과 ETCH에 로트 26개가 쌓이고 완료는 0건인 채로 멈춰 있었다. `state_machine.py`에
      `HOLD → QUALITY_HOLD`를 추가하고, `simulation.py`의 예외 처리를 로트 단위로 격리(다른 예외도
      잡아서 서버 로그+대시보드 이벤트 피드에 남기고 15초 백오프로 재스케줄)하도록 고쳤다. 회귀
      테스트 2건 추가(마지막 공정 HOLD→QUALITY_HOLD 전이, 고장 로트가 tick 내 다른 로트를 막지
      않는지 몽키패치 합성 실패로 검증) — pytest 72→74. 재기동 후 80 tick(~80초) 동안 완료 39건·
      에러 0건으로 정상 동작 확인. 5분 헬스체크 루프가 uvicorn 로그만 grep해서 이 버그를 못 잡았던
      관측 공백도 함께 드러나서(시뮬레이션 예외가 메모리 이벤트 피드에만 있었음) 서버 로그에도
      남기도록 고쳤다(Notion "07. PAR Experience" PAR-007 참고).
- [x] (2026-09-22) 설비 상세 드릴다운, 설비 카테고리 분류, 이상 이력 영구 저장 추가. 사용자가 대시보드를
      보다가 "설비 클릭하면 그 설비 로그도 보게", "설비도 카테고리 나눠서", "이상 데이터 저장해서 전용
      UI 페이지로"를 요청했다. `GET /equipment/{id}/events`를 추가해 LotEvent를 equipment_id로
      필터링해서 그 설비가 처리한 공정 이력 + (INSPECT 설비는) 검사 이력을 한 번에 보여주고, 대시보드
      설비 화면을 공정별 카테고리 섹션(식각/박막증착/평탄화/검사)으로 재구성하고 카드 클릭 시 상세
      드로어(누적가동시간·배정횟수·로그)를 열게 했다. 품질 이상은 지금까지 `/quality/anomalies`가
      매 요청마다 새로 계산하고 응답 즉시 버리는 라이브 스냅샷만 있어서 "언제부터 이 이상이 있었는지"
      기록이 없었는데, 탐지 로직을 `_detect_quality_anomalies()`로 분리해 시뮬레이션 엔진이 30초마다
      같은 로직으로 자동 재검사하고 새로 발견한 이상만(같은 설비는 5분 동안 중복 기록 안 함)
      `AnomalyLog` 테이블에 저장하도록 했다. 새 대시보드 페이지 "이상 이력"에서 이 영구 기록을 볼 수
      있다. 이 작업을 하다가 드로어의 닫기 버튼이 상단 고정 헤더(`z-index: 40`)에 가려 클릭이 안 되는
      버그를 실제로 Playwright 클릭 테스트에서 발견했다 — 원래 있던 로트 드로어도 같은 CSS를 공유해서
      똑같이 영향받고 있었는데 그동안 아무도(사람도, 이전 스크린샷 검증도) 실제로 닫기 버튼을 눌러본
      적이 없어서 몰랐다. `.drawer`/`.drawer-overlay` z-index를 50/51로 올려 고쳤다. 회귀 테스트 4건
      추가(설비 이벤트 조회 범위·404, 이상 신규 저장·중복 억제) — pytest 74→78.
- [x] (2026-09-22) OEE(설비종합효율 = Availability x Performance x Quality) 계산을 추가했다.
      지금까지는 `equipment_utilization`(누적 RUN 시간)만 있어서 "이 설비가 얼마나 오래
      돌았는지"는 보여도 "얼마나 효율적으로 돌았는지"는 알 수 없었다. Equipment에 `run_seconds`와
      대칭인 `down_seconds`(DOWN 상태를 벗어날 때 `set_equipment_status`에서 flush, 기존
      `run_seconds` 패턴 그대로 재사용)와 `created_at`을 추가해 Availability = 1 -
      (DOWN 시간 / 설비 생성 이후 전체 경과시간)으로 계산했다(IDLE은 "작업 대기"이지 "고장"이
      아니므로 가용시간에 포함, DOWN만 손실로 계산). Performance = 목표 Cycle Time(자율
      시뮬레이션 엔진의 `step_dwell_min/max_seconds`(6~14s) 중간값 10s, 이 프로젝트에 존재하는
      유일한 "설계 목표 처리시간") x 배정횟수 / 실제 가동시간으로 계산하고 1.0으로 캡핑했다(표준
      OEE 관례 — 100% 초과는 "설비가 더 빠르다"가 아니라 "목표시간 가정이 느슨하다"는 뜻).
      Quality는 설비별로 조작해내지 않고(검사 합/불 데이터는 INSPECT 설비에만 존재) 기존
      `yield_rate`를 그대로 재사용해 공장 전체 수준에서만 3요소 OEE를 계산했다 — 설비별
      응답(`GET /equipment`)에는 Availability/Performance만 노출하고 "OEE"라는 이름은 붙이지
      않았다. 데이터가 없으면(한 번도 배정된 적 없는 설비) 0이 아니라 `None`을 반환해서 지어낸
      숫자를 노출하지 않는다. 단위테스트 11개(가동률/성능 각 공식, DOWN 시간 flush, `/metrics`·
      `/equipment` 응답 배선) 추가로 pytest 78→89, 50 VU/3분 파이프라인 재확인(실패율 0%, RPS
      95.88, p95 66ms/p99 160ms, Server 5xx/IntegrityError 0, 측정된 OEE
      Availability=0.9954/Performance=1.0(캡핑됨)/Quality=1.0). 대시보드 개요 카드와 설비
      드릴다운 드로어에도 노출했다.
- [x] (2026-09-23) 설비 다운타임 이벤트 모델과 MTBF/MTTR 계산 추가. 어제 추가한 OEE
      Availability는 `Equipment.down_seconds` 누적값만 썼는데, 이 값은 총합만 있어서 "몇 번
      고장났는지", "각 고장이 얼마나 걸렸는지", "왜(수동 조작인지 랜덤 Fault인지 Locust Fault
      Injection인지) DOWN이었는지"를 사후에 감사할 방법이 없었다(어제 리포트의 "다음 후보"에
      남겨둔 문제). `EquipmentDowntimeEvent` 테이블(equipment_id, reason, started_at, ended_at,
      duration_seconds)을 추가해 `set_equipment_status`가 DOWN으로 들어갈 때 행을 열고 DOWN을
      벗어날 때 그 설비의 열린 행을 닫도록 했다(같은 DOWN 상태에서 중복 PATCH가 와도 이미 열린
      행이 있으면 새로 열지 않음 — 회귀 테스트로 고정). `app.main._equipment_reliability`가 이
      이력으로 MTTR(닫힌 다운타임 duration의 평균)과 MTBF((총 경과시간 - 총 다운시간) / 고장
      횟수, OEE Availability와 같은 분모를 재사용해 두 지표가 서로 어긋나지 않게 함)를 계산해
      `GET /equipment` 응답과 새 `GET /equipment/{id}/downtime`(개별 다운타임 이력, 최신순)에
      노출한다. 값이 없으면(아직 한 번도 고장난 적 없는 설비) 0이 아니라 `None`을 반환한다.
      자율 시뮬레이션 엔진의 랜덤 Fault는 `reason="RANDOM_FAULT"`, Locust Fault Injection Task는
      `reason="FAULT_INJECTION"`, 그 외 PATCH는 기본값 `reason="MANUAL"`로 태깅했다. 단위테스트
      10건 추가(다운타임 행 열기/닫기, 중복 열기 방지, 엔드포인트 정렬·404, MTTR/MTBF 공식,
      `/equipment` 응답 배선) — pytest 89→99, 전체 통과. `scripts/run_daily_test.sh`가 실행 끝에
      `/equipment`도 스크랩하도록 하고 `summarize.py`에 "Equipment Reliability (MTBF/MTTR)" 절을
      추가해, 50 VU/3분 재측정(실패율 0%, RPS 92.58, p95 190ms/p99 460ms, Server 5xx/IntegrityError 0)에서
      Locust Fault Injection Task로 실제 12대 중 10대가 최소 1회 DOWN/복구를 겪어 MTTR
      0.1~0.5초·MTBF 44.7~180.7초라는 실측값이 리포트에 찍히는 것까지 확인했다(MTTR이 매우
      짧은 것은 실제 결함이 아니라 Locust의 `fault_recover_equipment` Task가 다음 반복에서
      거의 즉시 그 설비를 골라 복구시키기 때문 — 이 부하 시나리오가 만드는 실제 패턴이며 지어낸
      값이 아니다). 이 실행에서 INSPECT-03 불량률 33.33%(피어 평균 0%) CRITICAL 이상도
      함께 관측했다(품질 이상 탐지 절 참고).
- [x] (2026-09-24) Locust에 스텝 전체 다운(whole-step) Fault Injection을 추가하고, 그 과정에서
      HOLD 대기시간 지표가 실제로는 한 번도 관측되지 못하던 두 가지 원인을 찾아 함께 고쳤다.
      먼저 `fault_inject_step_down` 태스크를 추가해 같은 공정 스텝의 설비 3대를 한꺼번에 DOWN시켰다
      (`_STEP_DOWN_FIRED` 플래그로 프로세스당 1회만 발동 — gevent는 I/O에서만 그린렛을 전환하므로
      플래그 확인 직후 I/O 전에 set하면 두 그린렛이 동시에 발동을 결정할 수 없다). 첫 실행에서
      3대가 실제로 함께 DOWN되는 것은 확인했지만(`PATCH .../status [fault: step down]` 3건),
      `/metrics` 10초 샘플링 18개 전부와 최종 응답 모두 `lots_on_hold_count=0`이었다 — 원인은
      기존 `fault_recover_equipment` 태스크가 확률 Gate 없이 매번 임의의 DOWN 설비 1대를 즉시
      복구시켜서(50명 동시 사용자 기준 초당 여러 번 선택됨) 3대 모두가 약 1초 내에 개별
      복구되어(MTTR 0.1~0.7초로 이미 리포트에 찍혀 있던 값과 일치) 그 사이에 `/advance`가 그
      스텝을 정확히 때린 적이 없었기 때문이다. `_down_since`(Locust 프로세스 자체가 그 설비를
      DOWN시킨 시각)를 기록해 `fault_recover_equipment`가 `MIN_DOWN_DWELL_SECONDS=5`초 이상 지난
      설비만 복구 대상으로 삼도록 바꿨다(대안 A: 서버 스키마에 `last_status_change` 노출 후
      서버 계산에 맡기는 방법도 있었지만, 이번 문제는 Locust 시나리오의 타이밍 설계 문제이고
      서버 스키마/마이그레이션까지 건드릴 필요가 없어 Locust 쪽 최소 수정을 선택했다). 재측정에서
      HOLD가 처음으로 관측됐지만(`peak lots_on_hold=15`), 이번엔 실행 종료 시점까지 15건이 전혀
      해소되지 않고(`avg_resolved_hold_seconds=None`) 남아 있는 새 문제를 발견했다 — 원인은
      `advance_lot` 태스크가 `WAITING`/`PROCESSING` 상태만 조회해서 설비가 복구된 뒤에도 HOLD 로트를
      다시 시도하는 호출이 전혀 없었기 때문이다(서버 `advance_lot`은 HOLD 로트 재시도를 이미
      지원하고 있었음 — Locust 쪽 조회 누락). 상태 선택에 `HOLD`를 추가했더니(처음엔 균등 3분할)
      HOLD 대기 로트가 해소되는 것(`avg_resolved_hold_seconds=4.1~11.0`)은 확인했지만 RPS가
      93->86, 완료 로트가 ~200->142로 눈에 띄게 줄었다 — HOLD 리스트가 거의 항상 비어 있어서
      3분의 1의 picks가 헛일이었기 때문이다. `random.choices(weights=[45,45,10])`로 HOLD 비중을
      낮춰 재측정한 결과 RPS 90.79(기존 기준선 범위 내), 완료 179건, `peak lots_on_hold=28`,
      `avg_resolved_hold_seconds=11.0`, 실행 종료 시점 HOLD 0건을 확인했다 — 부하 강도를 거의
      깎지 않으면서 스텝 전체 다운/복구 사이클을 안정적으로 관측할 수 있게 됐다. pytest 99개
      전체 통과(Locust 태스크 자체는 이전 Fault Injection 태스크들과 같은 이유로 pytest 대상이
      아니라 `scripts/run_daily_test.sh` 전체 실행으로 검증), Server 5xx/IntegrityError 0,
      실패율 0% 재확인.
- [x] (2026-09-25) `GET /equipment`/일일 리포트의 MTBF/MTTR을 `reason`별로 쪼개는
      `_downtime_by_reason` 함수와 `EquipmentOut.downtime_by_reason` 필드를 추가해, 이제
      "FAULT_INJECTION이 만든 다운타임"과 "RANDOM_FAULT/MANUAL이 만든 다운타임"을 설비별·
      공장 전체별로 구분해서 볼 수 있다(`scripts/summarize.py`가 전 설비를 합산한
      `downtime_seconds_by_reason`도 일일 리포트에 추가). 구현 직후 50 VU·3분 파이프라인으로
      검증하다가 `GET /equipment [list]`의 p95가 기존 34ms 수준에서 510\\~600ms대로 뛰는 걸
      발견했다 — 원인은 새 함수가 이미 `_equipment_reliability`가 설비당 한 번 조회하던
      `EquipmentDowntimeEvent`를 설비당 한 번 더(총 두 번) 조회하고 있었기 때문이었다(N+1의
      변형: 쿼리 자체는 O(N)이었지만 그 배수가 2배로 늘어난 것). `_downtime_events(db, id)`로
      조회를 분리하고 `/equipment` 라우트가 설비마다 그 결과를 한 번만 가져와 두 함수
      (`_equipment_reliability`, `_downtime_by_reason`)에 `events=` 인자로 재사용하도록
      고쳐서, 라우트 하나당 설비별 다운타임 쿼리 횟수를 다시 1회로 되돌렸다. 고친 뒤 재측정한
      `/equipment [list]` p95는 320ms로 낮아졌으나(중앙값은 94ms -> 33ms로 정상 범위 복귀),
      이 세션에서 파이프라인을 여러 번 반복 실행한 뒤라 공유 컨테이너의 CPU 경합 가능성을
      배제하지 못해 전체 Aggregated p95(240ms)가 여전히 최근 기준선(34\\~190ms) 상단에
      있다 — 지어낸 결론을 내지 않고 그대로 기록한다. pytest 99 -> 102개(신규 3개: 실패
      전 빈 값, reason별 분리, `/equipment` 응답 배선) 전체 통과, Server 5xx/IntegrityError 0,
      실패율 0%. 회귀 방지를 위해 "설비당 반복 조회를 만들 때는 같은 쿼리를 두 번 부르고
      있지 않은지 확인한다"는 교훈을 이 항목에 남긴다.
- [x] (2026-09-24) Human-in-the-Loop 승인 큐 1단계 구현. AI/에이전트가 조치를 "제안만" 하고 사람이
      승인/반려/수정하는 흐름의 뼈대다. `ApprovalRequest` 테이블과 `POST/GET /approvals`,
      `GET /approvals/summary`, `POST /approvals/{id}/decision` API, 대시보드 "승인 큐" 페이지를 추가했다.
      운영자 부담이 쌓이지 않도록 세 가지 장치를 처음부터 넣었다: 위험도(`risk_level`, 위험 높은 순 정렬),
      같은 원인 병합(`dedupe_key`+`occurrence_count`, 대기 중인 같은 키는 새 행이 아니라 횟수만 증가),
      만료(`expires_at`, 만료된 요청은 승인 불가·EXPIRED). 결정은 조건부 UPDATE로 처리해 동시에 두 명이
      결정해도 한 명만 성공하고 나머지는 409를 받는다. 반려는 사유가 필수(피드백 신호). 첫 요청 생산자는
      AI 없는 규칙 기반 "품질 에이전트"(`rule:quality-anomaly`)로, 기존 30초 이상탐지 결과 중 WARNING/CRITICAL만
      요청으로 만든다(WATCH는 이상 이력에만 남김). 이 규칙 기반 동작이 이후 LLM 에이전트와 비교할 Baseline이다.
      승인해도 설비/로트는 자동으로 바뀌지 않는다(사람이 직접 실행). 검증: pytest 78→92(신규 14), Playwright로
      승인/반려/수정 클릭 흐름, 폴링 중 입력 유지, XSS 문자열의 텍스트 렌더링, 모바일 가로 스크롤 없음 확인.
      UI 테스트에서 "폼을 여는 클릭까지 재렌더가 막히는" 버그를 발견해 수정했다.
      한계: 승인 후 실제 실행, Audit Trail, 설비·이상이력·승인 큐용 MCP 도구(읽기 전용 agent_gateway는 이미 있음), LLM 에이전트, 컨트롤타워는 아직 없다.
- [x] (2026-09-25) 컨트롤타워 + 설비 에이전트 구현. 에이전트가 승인 큐에 직접 쓰지 않고 `app/control_tower.py`를
      거치도록 바꿨다. 같은 설비에 대한 여러 에이전트 제안은 한 건으로 합치고(근거 결합, 위험도는 최댓값,
      기여 에이전트 목록 보존), 병합 건마다 BLOCK(허용 목록 `INSPECT_EQUIPMENT`/`STOP_NEW_DISPATCH`/
      `REVIEW_RECIPE` 밖의 조치: 기록만 하고 큐에 넣지 않음) / AUTO_RECORD(LOW: 기록만) / QUEUE(MEDIUM 이상:
      `upsert_request`로 승인 큐)를 판정한다. 허용되지 않은 제안은 허용된 제안과 합치기 전에 먼저 분리해
      함께 통과하지 못하게 했다. 모든 판정은 `ControlTowerDecision` 테이블에 저장하고
      `GET /control-tower/decisions`(최신 100건)와 승인 큐 화면의 "컨트롤타워 판단" 탭에 보인다.
      점검 주기마다 같은 상태가 반복 제안되므로 직전 판정과 (처분·위험도·에이전트·요청 id)가 같으면 새 행을
      쓰지 않는다. 설비 에이전트(`app/equipment_agent.py`, 규칙 기반, AI 없음)는 `EquipmentDowntimeEvent`에서
      최근 10분 내 DOWN이 3회 이상이면 `INSPECT_EQUIPMENT`를 제안한다(3회 LOW, 4회 MEDIUM, 6회 HIGH).
      기존 품질 에이전트도 같은 경로를 쓰며, WATCH는 여전히 승인 요청을 만들지 않고, 지속되는 CRITICAL은
      요청 1건의 `occurrence_count`만 올린다. 검증: pytest 116 -> 135개(신규 19개) 전체 통과, 격리 서버에서
      Playwright로 새 탭 렌더링, 서버 문자열의 XSS 텍스트 처리, 기존 승인/반려 흐름과 폴링 중 입력 유지,
      모바일 390px 가로 스크롤 없음 확인(긴 무공백 문자열이 넘치는 것을 발견해 카드에 줄바꿈 규칙 추가).
      한계: 승인 후 실제 실행 없음, Audit Trail 없음, LLM 에이전트와 A2A 프로토콜 없음, 설비 에이전트의
      창(10분)과 임계값(3/4/6회)은 시뮬레이터 고장률에 맞춘 데모 값이며 근거가 있는 기준이 아니다.
      병합 승인 요청은 설비 단위 `dedupe_key`를 쓰므로 기존 대기 중이던 `quality-anomaly:<id>` 키의 요청과는
      이어지지 않는다.
- [x] (2026-09-26) `agent_gateway/`(read-only MCP Gateway)에 설비·이상이력·승인 큐 조회 Tool 6개를
      추가했다. 2026-09-25 HITL 항목이 "한계"로 남겨둔 gap이다 — 그때까지 Gateway는
      `get_quality_anomalies`(매 호출 재계산되는 Live 이상탐지)만 있었고, 설비 상태/MTBF·MTTR,
      영구 이상 이력(`AnomalyLog`), 승인 큐, 컨트롤타워 판정은 MCP로 조회할 방법이 없어서 향후
      LLM 에이전트가 근거를 모으려면 결국 REST를 직접 호출해야 했다. `get_equipment_status`,
      `get_equipment_downtime`, `get_anomaly_log`, `get_approval_queue`(status 필터),
      `get_approval_summary`, `get_control_tower_decisions`를 각각 기존 `/equipment`,
      `/equipment/{id}/downtime`, `/quality/anomaly-log`, `/approvals`, `/approvals/summary`,
      `/control-tower/decisions` REST 엔드포인트에 얇게 위임하는 방식으로 추가했다(새 서버 로직
      없음 — Gateway는 여전히 read-only 원칙 유지, 조회 권한 범위만 넓어짐). 검증: 실행 중인
      서버에 대해 `agent_gateway/smoke_test.py`를 갱신해 9개 Tool 전체 이름을 assert하고
      `get_equipment_status`(12건 반환)·`get_approval_summary`·`get_control_tower_decisions`
      실제 호출까지 확인했고, `get_equipment_downtime`/`get_approval_queue(status=...)`처럼
      인자가 있는 Tool은 별도 스크립트로 실제 값(`equipment_id=1`, `status=PENDING`) 호출까지
      확인했다. pytest는 `agent_gateway/`를 수집하지 않으므로(`pytest.ini`) 영향 없이 167개
      그대로 통과, 50 VU/3분 파이프라인도 실패율 0%/Server 5xx·IntegrityError 0으로 재확인했다.
      한계: 여전히 Command(작업지시 Release, 설비 상태 변경, 승인 결정)는 Gateway에 없다 — 의도적.
- [x] (2026-09-27) 승인 큐 지표(승인율·수정율·평균 결정 대기시간·너무 빠른 승인 비율) 집계 추가.
      기존 `/approvals/summary`는 대기/처리 건수(`pending_count`, `approved_total`,
      `rejected_total`, `expired_total`, `edited_total`)만 있어서 "이 승인 큐가 실제로 사람의
      건전한 검토를 거치고 있는지"는 알 수 없었다(예: 위험도 높은 제안이 늘 즉시 승인되면 그건
      운영자가 실제로 근거를 읽은 게 아니라 그냥 통과시키는 것일 수 있다 — HITL 트랙의 핵심 전제인
      "사람이 실제로 검토한다"를 뒷받침할 지표가 없었다). `app/approvals.py.summary()`에 네 값을
      추가했다: `approval_rate`(승인 / (승인+반려), 만료는 사람의 결정이 아니라서 분모 제외),
      `edit_rate`(수정 후 승인 / 승인), `avg_decision_wait_seconds`(결정된 요청의
      `decided_at - created_at` 평균), `fast_approval_rate`(승인까지 걸린 시간이
      `FAST_APPROVAL_THRESHOLD_SECONDS=5`초 미만이었던 승인의 비율 — 제목+근거 한 줄을 읽는 데
      걸리는 최소 시간을 데모로 잡은 임계값이며, 실제 운영자 타이밍 연구에 근거한 검증된 기준이
      아니라는 점을 코드 주석에 명시했다). 값이 없으면(결정된 요청이 아직 없음) 0이 아니라
      `None`을 반환한다. 대시보드 "승인 큐" 화면 요약 카드에 세 항목(승인율·수정율, 평균 결정
      대기시간, 너무 빠른 승인 비율)을 추가로 노출했다. 검증: `tests/test_approvals.py`에 3건
      추가(빈 큐일 때 네 값 모두 `None`, 승인 2/반려 1 + 수정 1건으로 승인율 2/3·수정율 1/2 확인,
      `created_at`을 30초 전으로 옮긴 요청과 즉시 승인한 요청을 섞어 평균 대기시간 > 10초·
      `fast_approval_rate=0.5` 확인) — pytest 171 -> 173개 전체 통과. 살아있는 서버에 curl로
      직접 승인 1건을 만들고 결정해 실제 JSON 응답의 네 필드가 기대한 값(승인율 1.0, 평균 대기
      0.03초, `fast_approval_rate=1.0`)으로 나오는 것도 확인했다. `agent_gateway`의
      `get_approval_summary`는 `/approvals/summary`를 그대로 위임하는 얇은 Tool이라 새 필드가
      코드 변경 없이 그대로 노출된다. 50 VU/3분 파이프라인도 재확인(실패율 0%, RPS 89.37,
      p95 61ms/p99 140ms, Server 5xx/IntegrityError 0) — 이 부하 시나리오 자체는 승인 큐를
      건드리지 않으므로(자율 시뮬레이션 엔진을 켜야 품질 에이전트가 승인 요청을 만든다) 이번
      리포트의 승인 큐 지표는 관측되지 않는다. 한계: 이 지표들은 아직 대시보드에만 있고
      `agent_gateway`나 일일 리포트(`summarize.py`)에는 아직 노출하지 않았다 — 승인 큐가 비어
      있는 날이 많아 일일 리포트에 넣어도 대부분 `None`으로 찍힐 것이라 판단해 보류했다.
- [x] (2026-09-28) 승인 큐 밖(설비 상태 수동 PATCH, 작업지시 Release)까지 포함하는 통합
      Audit Trail 추가. 기존 `ApprovalRequest`는 결정 하나(누가/언제/무엇을/왜)만 자기 행에
      담아 승인 큐 안에서는 이력이 남았지만, `PATCH /equipment/{id}/status`나
      `POST /work-orders/{id}/release`처럼 승인 큐를 거치지 않는 상태 변경은 감사 로그가
      전혀 없었다(2026-09-25 HITL 진행 현황 페이지가 "한계"로 남겨둔 항목). 범용 `AuditLog`
      테이블(`app/audit.py`)을 추가해 설비 상태 PATCH·작업지시 Release·승인 결정 3곳 모두
      같은 트랜잭션(같은 `db.commit()`)으로 기록하도록 했다 — 감사 로그 `add()`와 실제 상태
      변경이 항상 같이 커밋되거나 같이 롤백되어 서로 불일치할 수 없다. 승인 결정 경로는
      기존에 "조건부 UPDATE 성공 후 즉시 commit"하던 것을 "조건부 UPDATE 성공 확인 → 감사
      로그 add → 같이 commit"으로 재구성했다. `GET /audit-log`(entity_type/entity_id 필터)
      API와 `agent_gateway`의 `get_audit_log` 읽기 도구를 추가했다. 검증:
      `tests/test_audit_log.py` 6건 신규(설비 상태 변경 기록, 같은 상태로 PATCH하면 기록 안
      함, 작업지시 Release 기록, 승인 결정 기록·actor 반영, 이미 결정된 요청 재결정 시도
      (409)는 기록 안 함, 여러 entity_type이 한 Feed에서 최신순 정렬) 전체 통과. 50 VU/3분
      파이프라인 재확인.
- [x] (2026-09-28) 일일 리포트의 `Server 5xx` 카운트가 항상 0으로 찍히던 버그 발견·수정
      (PAR-014). Audit Trail 검증용 50 VU/3분 파이프라인 실행 중 `server.log`에 SQLite
      `database is locked`로 인한 실제 500이 2건 있었는데도 생성된 리포트는 "Server 5xx: 0"
      이었다. 원인은 `scripts/summarize.py`의 `server_5xx` 정규식(`HTTP/1\.1 5\d\d `)이
      uvicorn이 실제로 남기는, 요청 라인을 큰따옴표로 감싸는 형식(`"...HTTP/1.1" 500 ...`)과
      달라 한 번도 매치되지 않았던 것 — 과거 리포트들에 반복해서 적힌 "Server 5xx: 0"도 이
      버그 때문이었을 가능성이 높다(진짜 0이었는지는 이제 검증할 수 없다). 정규식을
      `HTTP/1\.1"\s+5\d\d `로 수정하고 오늘 캡처된 실제 로그로 수정 전(0건)/후(2건)를 직접
      대조해 검증했다. `tests/test_summarize.py` 3건 신규(uvicorn 실제 포맷에서 5xx 카운트,
      5xx 없을 때 0, 4xx는 세지 않음). `python scripts/summarize.py 2026-09-28`을 재실행해
      `reports/2026-09-28.md`/`.json`의 Server 5xx를 0→2로 정정했다. pytest 179 -> 182개
      전체 통과(Audit Trail 6건 + 이 항목 3건). 이 500 2건의 근본 원인(SQLite 동시 Write
      Lock)은 오늘 범위 밖이라 아래 "다음 후보"에 별도로 남긴다.

- [x] (2026-09-29) HITL 트랙 "규칙 기반 에이전트(Baseline)" 단계에 3번째 에이전트
      `rule:production-hold`(`app/production_agent.py`)를 추가했다. Notion HITL 허브
      페이지의 "지금 어디까지 왔나" 표를 다시 확인하다가, 이미 구현된 `equipment_agent`/
      `llm_agent`(둘 다 2026-09-25~26에 커밋됨)가 반영되지 않은 채 여전히 "품질 에이전트
      1개만 구현"으로 남아 있는 것도 함께 발견해 Notion 쪽을 정정했다(아래 "E. 문제·해결
      로그" 기록 참고). 정작 진짜로 비어 있던 것은 "생산" 에이전트였다 — 코드를 읽다가
      기존 두 규칙(`equipment_agent.propose_from_downtime`: 설비 1대가 10분 내 3회 이상
      DOWN, `propose_from_concurrent_downs`: 서로 다른 설비 5대 이상이 40초 내 동시 DOWN)의
      임계값 사이에 실제 탐지 공백이 있음을 확인했다: 같은 공정 스텝의 설비 정확히 3대가
      거의 동시에(각자 1회씩만) DOWN되면 그 스텝은 완전히 정지(로트 전원 HOLD)하지만, 3 <
      5(동시 다운 임계값)라 `propose_from_concurrent_downs`가 잡지 못하고, 설비별 DOWN
      횟수도 각각 1회뿐이라 `propose_from_downtime`의 3회 임계값도 넘지 못한다 — 즉 "가장
      심각한 상태(공정 전체 정지)"가 오히려 두 기존 규칙 모두의 사각지대에 있었다. 대안
      A(기존 `propose_from_downtime`에 DOWN *횟수* 대신 *누적 시간* 가중치를 추가하거나
      `propose_from_concurrent_downs`의 임계값을 3으로 낮추는 방법)는 검토했지만 채택하지
      않았다 — 임계값을 3으로 낮추면 서로 무관한 다른 스텝의 설비들이 우연히 40초 내에
      겹쳐 DOWN되는 정상적인 노이즈도 오탐으로 잡히고(공정 스텝 정보를 아예 안 보는
      규칙이라 상관관계를 구분 못함), 어느 쪽이든 "설비가 몇 번/얼마나 DOWN됐는가"라는
      설비 건강 신호와 "실제로 생산이 얼마나 오래 멈췄는가"라는 생산 영향 신호를 한 규칙에
      섞어 두 신호 모두 불분명해진다. 대신 B: 이미 `/metrics`의 팩토리 전체
      HOLD 대기시간 계산(`_equipment_hold_wait_metrics`, 2026-09-21)이 쓰던 것과 같은
      `LOT_HELD`/`LOT_RELEASED_FROM_HOLD` 이벤트 저널을 공정 스텝별로 재구성해, "이 스텝에서
      가장 오래 걸린 로트가 지금 몇 초째 대기 중인가"를 직접 측정하는 새 에이전트를
      추가했다 — DOWN 이벤트 개수의 대리 지표가 아니라 실제 생산 정체 시간을 직접 보므로
      기존 두 규칙과 겹치지 않는다. 위험도 3단계(LOW ≥30초/MEDIUM ≥90초/HIGH ≥240초,
      시뮬레이션 엔진의 단일 설비 최대 DOWN 시간(30초, `SimulationConfig.equipment_down_max_seconds`)을
      기준으로 잡은 데모 값, 실제 표준 근거 아님)이며 action_kind는 기존에 이미 허용된
      `INSPECT_EQUIPMENT`를 재사용해 `control_tower.py` 스키마 변경이 필요 없었다.
      검증: 유닛테스트 9개(`tests/test_production_agent.py` — 무이상 시 빈 목록, 임계값
      바로 아래/LOW/HIGH 경계, HOLD 해소 시 카운트 중단, 같은 스텝 2개 로트 시 evidence
      건수만 증가, 서로 다른 두 스텝이 각각 별도 제안 생성, 컨트롤타워가 MEDIUM+는 QUEUE·
      LOW는 AUTO_RECORD로 분기)와 `tests/test_control_tower.py`에 통합 테스트 1개(시뮬레이션
      엔진의 `_maybe_check_anomalies`를 직접 거쳐 `rule:production-hold`가 다른 에이전트와
      섞이지 않고 별도 승인 요청으로 도착하는지) 추가 — pytest 182 -> 192개 전체 통과.
      살아있는 서버(전용 스모크용 DB)에 실제로 ETCH 설비 3대를 curl로 모두 DOWN시켜 로트를
      HOLD시킨 뒤, 그 진짜 `LOT_HELD` 이벤트 시각을 읽어 MEDIUM 임계값(90초) 시점의
      `now`로 `propose_from_step_hold_wait`를 직접 호출해 제안이 만들어지는 것과, 그 결과가
      `ct.process`를 거쳐 실제 `GET /approvals`·`GET /control-tower/decisions` 응답에 정확히
      나타나는 것까지 확인했다. 50 VU/3분 파이프라인도 재확인(실패율 0%, RPS 88.42,
      p95 150ms/p99 360ms, Server 5xx/IntegrityError 0) — 이번 Locust 시나리오에서는
      관측된 최대 HOLD 대기가 10.1초로 새 에이전트의 최저 임계값(30초)에 못 미쳐 실제로는
      발동하지 않았다(지어낸 결과를 적지 않기 위해 그대로 기록 — 이 시나리오는 스텝 전체
      다운 후 빠른 복구를 재현하도록 튜닝돼 있어 30초 이상 정체가 드물다). 대시보드는
      `equipment_id: null` 제안(예: 기존 "공장 전체" 동시다운 제안)을 이미 지원하고 있어
      화면 쪽 변경은 필요 없었다.

- [x] (2026-09-30) `rule:production-hold`가 실제 시나리오에서 발동하는 것을 wall-clock으로
      직접 관측했다. 어제(2026-09-29) PAR-015는 `propose_from_step_hold_wait`를 코드로 직접
      호출해 합성 시각(now)으로만 검증했고, 실제 Locust/시뮬레이션 부하에서는 관측된 최대
      HOLD 대기가 10.1초로 최저 임계값(30초) 미달이었다(ROADMAP에 "다음 후보"로 이월). 원인은
      기존 Fault Injection들이 전부 짧게(수 초 내) 복구되도록 설계돼 있어(개별 설비 다운:
      `MIN_DOWN_DWELL_SECONDS=5`초 후 복구, 스텝 전체 다운: 동일, `demo_approvals.py`의 s1/s3도
      1초 내 복구) 어떤 시나리오도 "한 공정 스텝의 설비 전체가 30초 이상 묶여 있는" 상황을
      만들지 않았기 때문이다. 대안 A(기존 임계값 30/90/240초를 낮춰서 짧은 다운으로도 잡히게
      하는 방법)는 검토했지만 채택하지 않았다 — 이 임계값은 시뮬레이션 엔진의 설비 최대
      DOWN 시간(30초)에 근거해 이미 문서화돼 있고, 임의로 낮추면 "실제로 30초 이상 정체됐다"는
      의미가 사라져 데모를 관측 가능하게 만드는 대신 지표의 의미 자체를 훼손한다고 판단했다.
      대신 B: `scripts/demo_approvals.py`에 새 시나리오 `s4`를 추가해 한 공정 스텝(기본 ETCH)의
      설비 전체를 의도적으로 100초간 묶어두도록 했다(기존 s1/s3처럼 즉시 복구하지 않음). 전용
      서버(포트 18099, 격리 DB)에 시뮬레이션을 켜고 15초간 로트가 ETCH에 쌓이게 한 뒤 `s4`를
      실행해 실제로 관측했다: 다운 후 약 34초 시점에 LOW 위험도로 AUTO_RECORD(사람에게 안 보냄,
      컨트롤타워 판정 id=2)가 먼저 기록되고, 약 94초 시점에 MEDIUM 위험도로
      `rule:production-hold` 제안("ETCH 공정 정체 (94초 대기)", 로트 25건 대기)이 실제
      `GET /approvals`에 PENDING 상태로 나타나는 것을 확인했다(승인 요청 id=2, 컨트롤타워
      판정 id=3, disposition=QUEUE). 같은 창(40초) 안에 시뮬레이션 자체의 무작위 고장으로
      CMP-01·INSPECT-02도 우연히 DOWN되어, 기존 `rule:equipment-downtime`의 팩토리 전체
      동시다운 규칙(5대/40초)도 함께 발동하는 것을 관측했다(두 규칙이 서로 다른 승인 요청으로
      분리되어 나타남 — 병합 오류 없음). 서버 로그에 에러/트레이스백 0건. pytest는 스크립트
      변경이라 영향 없이 192개 그대로 통과, 50 VU/3분 파이프라인 재확인(요청 15,998건, 실패율
      0.00%, RPS 89.16, p95 88ms/p99 250ms, Server 5xx/IntegrityError 0). PAR-016에 기록했다.

- [x] (2026-10-01) 2026-09-30에 "판단이 필요하다"로 이월했던 `s4` 데모의 신호 고립 문제를
      결정했다: 시뮬레이션의 무작위 고장 확률을 영구적으로(config 기본값) 낮추는 방법은
      기각했다 — 그 값은 이미 baseline 부하테스트의 MTBF/MTTR 실측치(PAR-010)와 얽혀 있어
      건드리면 기존 기준선 전체가 흔들린다. 대신 새 임시 override API
      (`POST/DELETE /simulation/inject/fault-rate`, `app/simulation.py`의 `_fault_rate_override`)를
      추가해 `scripts/demo_approvals.py`의 `s4`에 opt-in `--isolate` 플래그로 노출했다 —
      기본값(옵션 없음)은 기존처럼 현실적인 동작(다른 규칙이 우연히 겹쳐 발동할 수 있음)을
      유지하고, 격리가 필요한 데모에서만 껐다 켤 수 있다. 전용 서버(포트 18124)에 실제로
      시뮬레이션을 켜고 `--isolate`로 `s4`를 실행해 wall-clock으로 검증: 격리 주입 시각
      (22:18:38)부터 해제 시각(22:19:18)까지 40초 동안 새로운 무작위 DOWN이 0건이었고,
      주입 직전(22:18:24~22:18:31)에 이미 발생해 있던 무작위 DOWN 3건은 격리 대상이 아니라
      `rule:equipment-downtime`의 40초 동시다운 창에 `s4`의 ETCH DOWN과 함께 걸려 예상대로
      제안이 발동했다 — "주입 이후 새 무작위 DOWN을 막는다"는 범위 안에서는 정확히 동작하지만
      "그 시나리오 실행 중 어떤 부가 신호도 절대 발생하지 않는다"는 보장은 아니라는 것을
      실측으로 확인했고, 이 경계 조건을 스크립트 docstring에 그대로 남겼다(격리를 완전히
      하려면 시나리오 시작 최소 40초 전부터 override를 걸어야 한다). 신규 pytest 4건
      (`tests/test_simulation.py` 2건, `tests/test_control_tower.py` 2건) 추가, 전체
      192 -> 196개 통과. 50 VU/3분 파이프라인 재확인(요청 15,455건, 실패율 0.00%, RPS 86.09,
      p95 190ms/p99 440ms, Server 5xx/IntegrityError 0 — 회귀 없음, 이 부하테스트 자체는 새
      엔드포인트를 호출하지 않아 새 기능의 동시성 부하 검증은 아님).

- [x] (2026-10-02) 대시보드에 감사 로그(Audit Trail) 화면 추가. `GET /audit-log`는 2026-09-28에
      이미 있었지만 보려면 매번 curl이나 `/docs`를 직접 열어야 했다(HITL 허브 페이지가 "다음
      단계"로 남겨둔 항목). `app/static/index.html`에 새 메뉴 "감사 로그"를 추가해 설비 상태
      PATCH·작업지시 Release·승인 큐 결정을 시각/대상/동작/요약/이전→이후/사유/처리자 컬럼의
      표로 보여주고, 대상(설비/작업지시/승인 요청) 필터를 달았다. 기존 "이상 이력" 페이지와
      같은 테이블 패턴을 그대로 재사용했고 새 백엔드 로직은 추가하지 않았다(순수 프론트엔드 +
      이미 있던 `/audit-log` 호출 1개를 메인 polling 루프에 추가). 검증: 격리 서버(포트 18211,
      전용 DB)에 설비 DOWN→IDLE PATCH 2건과 작업지시 생성→Release 1건을 실제로 만든 뒤
      Playwright로 "감사 로그" 탭 클릭 → 행 3건 렌더링, `equipment.status_changed`/
      `work_order.released` 텍스트와 한글 라벨("설비"/"작업지시") 노출, 대상 필터를 "설비"로
      바꾸면 2건만 남는 것, 모바일 390px 폭에서 가로 스크롤 없음을 모두 실제로 확인했다(남은
      console 404는 사전에 있던 `/favicon.ico` 요청이며 이번 변경과 무관함을 별도 curl로
      확인). 백엔드 변경이 없어 pytest 196개 전체 그대로 통과, 50 VU/3분 파이프라인도
      재확인했다(요청 16,208건, 실패율 0.00%, RPS 90.40, p95 35ms/p99 84ms, Server
      5xx/IntegrityError 0 — 회귀 없음). 같은 실행에서 INSPECT-03 WARNING(불량률 18.64% vs
      피어 평균 0%, n=59)이 다시 관측됐는데, 전날(2026-10-01, 26.67%)과 그 이전 여러 날에도
      반복된 동일 패턴이라(2026-09-20에 이미 Baseline으로 문서화된 특성) 새로운 이상으로
      판단하지 않고 이상 이력에만 쌓이게 두었다(Notion 'Quality Anomaly Log' 신규 행 없음).
      한계: 승인 큐 화면처럼 실시간 배지나 상세 드로어는 아직 없고, 단순 목록+필터만 제공한다.

- [x] (2026-10-03) SQLite 동시 Write Lock 재현·원인 분석 (EXP-011, PAR-014 후속
      과제). PAR-014(2026-09-28)가 50 VU/3분 부하테스트 중 `database is locked`로
      인한 실제 500 2건(16,208건 중 0.012%)을 발견했지만 근본 원인은 그날 범위 밖으로
      남겨뒀었다. 오늘은 재현부터 시도했다: 단일 엔드포인트·단일 프로세스 스레드풀
      하네스(SQLAlchemy 기본 Pool 용량과 같은 15스레드, 9,000회 타이트 루프)로는 전혀
      재현되지 않았다(Python sqlite3 드라이버의 기본 5초 busy-timeout이 모든 경합을
      흡수). 그래서 실제 조건을 그대로 재현하는 `scripts/repro_sqlite_lock.sh`를
      새로 만들어(격리 서버 + 자율 시뮬레이션 백그라운드 writer + Locust 전체
      엔드포인트 믹스), 정확히 운영과 같은 50 VU로 원래 실행(3분)의 2배인 6분간
      두 차례(baseline 1·2) 돌렸는데도 `database is locked`는 한 번도 재현되지
      않았다 — 매우 낮은 빈도(0.012%)의 사건이라는 것 자체가 실측으로 재확인됐다.
      재현에 실패했으므로 "락 에러 감소"를 비교 지표로 쓸 수 없어, 대신 같은
      워크로드에서 p95/p99 지연과 RPS로 각 대안의 안전성을 비교했다. 대안 A(WAL
      모드 + `synchronous=NORMAL` + `busy_timeout=15000`, SQLAlchemy `connect`
      이벤트로 PRAGMA 설정)를 먼저 구현해 측정했는데 — 교과서적으로는 WAL이
      Reader가 Writer에게 막히는 문제의 정석 해법이라 선택했었다 — 같은 워크로드에서
      RPS 83→53(-35%), p95 310ms→1400ms(4.5배), `-wal` 파일이 6분 만에 300MB
      이상으로 계속 커지는 명백한 회귀를 실측했다. 이게 세션 내 연속 실행에 따른
      컨테이너 CPU 경합(PAR-013에서 이미 겪은 유형) 때문이 아닌지 의심해, WAL 적용
      없이 baseline을 동일 세션에서 한 번 더 재실행(control rerun)했더니 p95
      270ms로 원래 baseline과 같은 범위로 돌아왔다 — 회귀가 WAL 자체의 효과임을
      확인했다(세션 노이즈가 아님). 원인은 WAL Checkpoint 기아 상태로 추정된다:
      FastAPI 커넥션 풀이 계속 겹치는 Reader 스냅샷을 열어두는 지속적인 읽기/쓰기
      혼합 트래픽 아래에서는 Passive Auto-checkpoint가 오래된 WAL 프레임을 충분히
      빠르게 회수하지 못해 파일이 무한정 자란다. WAL은 기각했다 — 재현조차 안 되는
      0.012% 빈도 에러 하나를 막으려고 평상시 지연을 4.5배로 늘리는 트레이드오프는
      받아들일 수 없다고 판단했다. 대신 B(=실제로는 더 단순한 두 번째 대안):
      `connect_args={"timeout": 15}`로 sqlite3 드라이버 자체의 busy-wait만 기본
      5초에서 15초로 늘렸다(Journal Mode는 그대로 유지). 같은 워크로드에서 재측정한
      결과 RPS ~81, p95 360ms, p99 720ms로 두 baseline(270~310ms/590~670ms)과
      같은 범위 — 평상시 비용 없이 드문 경합 상황에만 여유를 3배 늘리는 변경이라
      채택했다. 검증: `tests/test_database.py` 신규 1건(엔진의 실제 `PRAGMA
      busy_timeout`이 15000으로 적용되는지), pytest 196→197개 전체 통과,
      `scripts/run_daily_test.sh` 50 VU/3분 전체 파이프라인 재확인(요청 15,095건,
      실패율 0.00%, RPS 84.10, p95 240ms/p99 540ms, Server 5xx/IntegrityError 0 —
      이 범위는 어제(p95 35ms/p99 84ms)보다 높지만, 바로 이전에 같은 세션에서
      6분짜리 50 VU 부하테스트를 5회 연속 실행한 직후라 PAR-013과 같은 공유
      컨테이너 CPU 경합으로 판단된다 — EXP-011 자체의 통제된 비교(각 실행마다
      독립된 격리 서버 사용)에서는 이 변경이 회귀를 만들지 않음을 이미 확인했다).
      실패한 실험(WAL 회귀)을 그대로 `experiments/EXP-011-sqlite-write-lock/
      experiment.md`에 남겼다. PAR-018로 기록.

- [x] (2026-10-04) HITL 승인 큐의 결정-품질 지표(승인율·수정율·평균 결정 대기시간·너무 빠른
      승인 비율, 2026-09-27 추가)가 그동안 한 번도 실제 값으로 채워진 적이 없었던 문제를
      해소했다. 원인: 일일 50 VU/3분 Locust 파이프라인은 `POST /simulation/start`를 호출하지
      않아 규칙 기반 에이전트가 전혀 발동하지 않고, 설령 승인 요청이 생겨도 결정할 사람이 없어
      `decided_at`이 항상 비어 있었다(모든 리포트에서 네 지표가 계속 `None`). 대안 A(자동화가
      매일 도는 동안 사람이 자연스럽게 승인 큐를 써서 데이터가 쌓이길 기다림)는 기각했다 — 이
      저장소는 사람이 상시 상주하는 운영 환경이 아니라 짧게 도는 자동화 루틴이라 쌓일 보장이
      없고, 쌓이더라도 분포(빠른 승인/느린 승인/거절/수정)를 통제할 수 없어 "5초 임계값이
      그럴듯한가"를 판단할 의도된 표본을 만들 수 없었다. 대신 B: 새 스크립트
      `scripts/demo_calibrate_approval_metrics.py`를 추가해, 격리 서버(포트 18300, 전용
      `mes_calibration.db`)에서 시뮬레이션을 켜고 서로 다른 설비/에이전트로 4건의 구분되는
      승인 요청(설비 다운 2건, 팩토리 전체 동시다운 1건, 품질 이상 1건)을 만든 뒤, 각기 다른
      대기시간(즉시/10초/15초/20초)과 결과(승인 2건+수정 1건, 반려 1건)로 결정했다 — 결정자는
      `decided_by="demo-calibration"`으로 명시해 실제 운영자 결정과 혼동되지 않게 했다(Audit
      Trail에도 이 actor로 남음). 이 과정에서 스크립트 초안이 agent 코드(`equipment_agent.py`,
      `simulation.py`)의 `dedupe_key` 형식(`equipment-down:<id>`, `quality-anomaly:<id>`)을
      그대로 쓰면 될 거라 가정했다가 실제 `GET /approvals` 응답으로 확인해보니, `equipment_id`가
      있는 모든 제안은 `control_tower.py`의 병합 로직이 `control-tower:equipment:<id>` 형태로
      재작성한다는 것을 발견해 정정했다(코드를 읽기 전에 가정부터 세운 경우라 Notion 'E.
      문제·해결 로그'에도 남김). 검증: `GET /approvals/summary` before(전부 `None`)/after 비교.
      결과: 승인율 `None`→0.75(3/4), 수정율 `None`→0.333(1/3), 평균 결정 대기시간 `None`→17.14초,
      너무 빠른 승인 비율(<5초) `None`→0.333(1/3). 개별 대기시간: ETCH-01 설비다운 1.09초(즉시
      승인), CMP-02 설비다운 21.11초(승인+수정), 설비 10대 동시다운 36.12초(반려 — 테스트로
      인위적으로 만든 것이라 실제 공통원인 장애 아님을 사유로 기록), INSPECT-03 품질이상
      10.24초(승인). 5초 임계값은 "즉시 클릭"(1.09초)만 정확히 잡아내고 10~20초대의 비교적
      빠르지만 근거를 읽었을 법한 결정은 플래그하지 않았다 — 표본 4건으로 통계적 확정은
      아니지만, 과도하게 엄격하거나 느슨해 보이지는 않는다는 정성적 결론을 PAR-019에 남겼다.
      pytest는 스크립트 추가라 영향 없이 197개 그대로 통과. 한계: 결정자가 스크립트(합성)이지
      실제 사람이 아니므로 이 타이밍은 사람의 인지 시간을 대표하지 않는다 — 이후 실제
      운영자/사용자가 대시보드에서 직접 승인/반려를 누르는 데이터가 쌓이면 재검증이 필요하다.

- [x] (2026-10-05) A2A(Agent2Agent) Quality Investigation Agent 1단계 구현 — "다음 후보"에
      남아 있던 "A2A Quality Investigation Agent: Agent Card, Task 상태, 조사 Artifact와
      승인 Gate" 항목. Google이 공개하고 현재 Linux Foundation이 호스팅하는 A2A 프로토콜의
      공개 개념 3가지(AgentCard: 에이전트가 할 수 있는 일을 알리는 정적 설명, Task: submitted
      -> working -> completed/failed로 진행하는 작업 단위, Artifact: Task의 구조화된 출력물)만
      빌려 기존 규칙 기반 품질 에이전트(`simulation.py`의 `_quality_proposal`)의 조사 과정을
      감싸는 새 모듈 `app/a2a.py`를 추가했다 — A2A의 JSON-RPC 전송, 스트리밍, Push 알림 등
      전체 프로토콜/SDK는 구현하지 않았고, `AGENT_CARD`의 `capabilities`에도
      `streaming: false`/`pushNotifications: false`를 있는 그대로 표기해 과장하지 않았다.
      삼성SDS는 A2A나 내부 에이전트 프로토콜을 공개한 바 없으므로 Nexplant와 연결짓지 않고
      "공개된 A2A 개념을 참고해 자체 설계"로만 표현했다. 새 `InvestigationTask` 테이블(상태,
      `anomaly_log_id` 연결, `artifact_json`)을 추가해, `_maybe_check_anomalies`가 새
      `AnomalyLog` 행을 쓸 때(기존 5분 억제 로직 그대로 재사용 — 매 점검 주기가 아니라 신규
      이상당 1회) `investigate_quality_anomaly()`를 호출해 해당 설비의 최근 30분 다운타임
      이력을 모아 Artifact(불량률/동료평균/z-score/다운타임 목록)를 만들고 완료 상태로
      전환한다. 중요한 순서 변경: 기존 코드는 `_propose_actions`(승인 큐로 가는 제안 생성)를
      먼저 호출한 뒤 `AnomalyLog`를 기록했는데, 조사 Task를 그 제안의 근거로 인용하려면
      Task가 먼저 만들어져야 해서 순서를 뒤집었다(로그 기록 → 조사 → 제안). `_quality_proposal`의
      `evidence` 문자열 끝에 `A2A Task #<id>`를 덧붙여 승인 큐 화면에서 조사 결과로 바로
      연결할 수 있게 했다. 조사 자체가 실패해도(예외) 기존 품질 제안 로직은 영향받지 않도록
      try/except로 격리했다(이 Task는 증거를 보강할 뿐, 사람 승인 경로의 필수 경로가 아님).
      읽기 전용 `GET /a2a/agent-card`, `GET /a2a/tasks`(설비 필터), `GET /a2a/tasks/{id}`
      API와 `agent_gateway`의 `get_agent_card`/`get_investigation_tasks`/`get_investigation_task`
      Tool 3개를 추가했다(기존 read-only 원칙 유지 — Command는 추가하지 않음). 이 Task도
      LLM을 호출하지 않는다(규칙 기반 유지, HITL 트랙 원칙 (b): LLM 에이전트는 Baseline 이후).
      승인/실행 Gate 자체는 바꾸지 않았다 — Task 완료는 근거를 승인 큐에 보강할 뿐, 여전히
      사람이 승인해야 실행된다는 원칙(HITL 원칙 (a))은 그대로다. 검증: 신규 pytest 12개
      (`tests/test_a2a.py` 9개 — AgentCard 필드, Task 완료/Artifact 내용, `anomaly_log_id`
      연결, 다운타임 Lookback 윈도 포함/제외, `/a2a/agent-card`·`/a2a/tasks`·`/a2a/tasks/{id}`
      엔드포인트와 404; `tests/test_control_tower.py` 1개 — `_seed_inspect03_anomaly`로 실제
      이상을 만들어 `_maybe_check_anomalies`를 호출하면 `InvestigationTask`가 생성되고 그
      id가 승인 요청 evidence에 그대로 나타나는지 통합 검증) 전체 197 -> 208개 통과. 격리
      서버(포트 18401, 전용 DB)에 실제로 INSPECT-03만 불량나는 시나리오를 curl로 만들고
      시뮬레이션을 켜서 실시간으로 확인: `GET /a2a/tasks`에 완료된 Task(불량률 100%, 최근
      다운타임 2건 포함)가 나타났고, `GET /approvals`의 evidence에 정확히 `A2A Task #1`이
      붙어 있었다. `agent_gateway/smoke_test.py`를 갱신해 신규 Tool 3개를 포함한 13개 전체
      이름 assert와 `get_agent_card`/`get_investigation_tasks`의 실제 호출까지 확인했다
      (agent_gateway 전용 `mcp[cli]` 패키지의 `pydantic`/`starlette` 버전이 메인 앱
      requirements와 충돌하는 것을 발견해, 메인 venv를 agent_gateway 설치 전 상태로
      재설치해 복구했다 — "다음 후보"에 분리된 venv 필요성으로 남긴다). 50 VU/3분
      파이프라인 재확인(요청 15,332건, 실패율 0.00%, RPS 85.42, p95 200ms/p99 440ms, Server
      5xx/IntegrityError 0 — 이 부하 시나리오는 `/simulation/start`를 호출하지 않으므로
      A2A Task 생성 자체는 이번 리포트에 반영되지 않음, 기존에 이미 알려진 한계와 동일).
      한계: Task는 품질 에이전트 1개에만 연결돼 있고(설비/생산 에이전트는 아직 미연결),
      Task 실행은 여전히 동기(백그라운드 작업이 아님) — 지금 쿼리 비용으로는 문제없지만
      조사 로직이 커지면 재검토 필요. A2A의 "진짜" 에이전트 간(A2A) 통신(여러 에이전트가
      서로 Task를 주고받는 것)은 구현하지 않았다 — 지금은 한 에이전트 내부에서 Task
      개념만 빌려 쓴 것이다.

- [x] (2026-10-06) A2A Quality Investigation Agent(2026-10-05)를 설비 에이전트
      (`rule:equipment-downtime`)에도 확장했다 — 어제 "다음 후보"에 명시적으로 남겨둔 항목이다.
      `app/a2a.py`에 두 번째 AgentCard(`EQUIPMENT_AGENT_CARD`, skill
      `investigate-equipment-downtime`)와 `investigate_equipment_downtime()`을 추가했는데,
      새 테이블을 만들지 않고 기존 `InvestigationTask`를 `agent_id`로만 구분해 그대로
      재사용했다(둘 다 submitted/working/completed라는 같은 Task 모양이라 테이블을 복제할
      이유가 없었다). 핵심 설계 결정 하나: Artifact가 보여주는 다운타임 건수가 그 조사를
      유발한 제안의 건수와 항상 일치해야 한다고 판단해, `investigate_equipment_downtime()`이
      조회 Lookback(window)을 자체적으로 고정하지 않고 호출자(`simulation.py`)가
      `equipment_agent.EQUIPMENT_DOWN_WINDOW_SECONDS`(600초, 실제 감지에 쓰는 값과 동일)를
      그대로 넘겨받게 했다 — 품질 조사가 쓰는 고정 1800초 Lookback과는 다른 값이며, 섞어 쓰면
      Artifact와 제안의 근거 숫자가 서로 어긋나는 모순이 생길 수 있었다. 품질 에이전트와 같은
      억제 로직(`ANOMALY_LOG_SUPPRESS_SECONDS=300초` 재사용)을 `simulation.py`에 새로 추가해,
      같은 설비의 반복 DOWN 조건이 서 있는 동안 매 30초 점검 주기마다 새 Task를 만들지 않고
      기존 Task id를 재사용하도록 했다(품질 에이전트는 `AnomalyLog` 중복 억제로 이미 같은
      효과를 얻고 있었는데, 설비 에이전트에는 그런 로그 테이블이 없어서 `InvestigationTask`
      자체를 5분 창으로 조회하는 방식을 썼다). `rule:equipment-downtime`의 두 함수 중
      `propose_from_downtime`(설비 1대 반복 DOWN, `equipment_id` 보유)만 연결했고
      `propose_from_concurrent_downs`(공장 전체 동시 다운, `equipment_id=None`)는 연결하지
      않았다 — 조사 대상이 "이 설비의 다운타임 이력"이라 단일 설비가 없는 제안에는 같은 패턴이
      그대로 맞지 않는다. 읽기 전용 `GET /a2a/agent-cards`(전체 에이전트 카드 목록, 기존
      `GET /a2a/agent-card`는 하위 호환으로 유지)와 `agent_gateway`의 `get_agent_cards` Tool을
      추가했다. 이 작업을 하다가 ROADMAP에 이미 "다음 후보"로 남겨 있던 또 다른 항목
      (`agent_gateway` 전용 가상환경 `.venv-mcp/` 분리)도 실제로 만들어 써서 함께 해결했다 —
      메인 `.venv`에는 `mcp[cli]`를 전혀 설치하지 않고 `.venv-mcp/`에서 `pytest`와 별개로
      `agent_gateway/smoke_test.py`와 신규 Tool 2개를 검증해 2026-10-05에 겪었던 버전 충돌이
      재발하지 않았다. 검증: 신규 pytest 7개(`tests/test_a2a.py` 5개 — 설비 AgentCard, 레지스트리,
      조사 완료+Artifact, 호출자가 넘긴 window 적용, `/a2a/agent-cards` 엔드포인트;
      `tests/test_control_tower.py` 2개 — 설비 다운타임 조사 Task가 생성되고 evidence에 인용되는지
      통합 검증, 같은 조건이 5분 억제 창 안에서 두 번째 점검 때 새 Task를 만들지 않는지) 전체
      208 -> 215개 통과. 격리 서버(포트 18700, 전용 DB)에서 설비 1대를 curl로 4회
      DOWN/IDLE시키고 시뮬레이션을 켜서 실시간으로 확인: 첫 조사(Task #1, DOWN 4회)가
      `GET /approvals`의 evidence에 `A2A Task #3`(품질 Task #2가 그 사이 끼어든 뒤 두 번째
      설비 조사가 5분 억제 창을 벗어나 새로 생성됨)으로 정확히 인용되는 것까지 확인했다.
      `.venv-mcp`의 `agent_gateway/smoke_test.py`도 신규 Tool 2개를 포함해 통과, MCP Client로
      `get_agent_cards`/`get_investigation_tasks`를 직접 호출해 두 에이전트 이름과 `agent_id`가
      구분되어 나오는 것도 확인했다. 50 VU/3분 파이프라인 재확인(요청 15,808건, 실패율 0.00%,
      RPS 88.11, p95 150ms/p99 390ms, Server 5xx/IntegrityError 0 — 이 Locust 시나리오는
      `/simulation/start`를 호출하지 않아 새 설비 투자 Task 생성 자체는 이번 리포트에 반영되지
      않음, 품질 Task와 같은 기존 한계). 한계: 생산 에이전트(`rule:production-hold`)는 아직
      연결하지 않았다(`equipment_id=None`이라 변형이 필요 — 다음 후보에 남김).

- [x] (2026-10-07) A2A 투자 Task/Artifact 패턴을 생산 에이전트(`rule:production-hold`)에도
      확장했다 — 어제 "다음 후보"에 남겨둔 항목이자 HITL 트랙의 다음 미완료 단계였다. 품질·설비
      조사와 다른 점: 이 에이전트의 제안은 `equipment_id`가 없다(공정 스텝 전체가 멈춘 것이라
      단일 설비가 아니다). `app/a2a.py`에 `investigate_step_hold()`를 추가해, 먼저 그 스텝에
      배정된 설비 목록(`Equipment.process_step` 일치)을 조회하고 그 설비들의 다운타임을 설비별로
      풀링하는 방식으로 설계했다. 조사 Lookback 창도 품질(1800초)·설비(600초, 2026-10-06)처럼
      고정값이 아니라, 그 제안이 측정한 HOLD 대기시간 자체(예: 91초)를 그대로 쓰도록 했다 — "조사
      Artifact가 보여주는 건수가 그 조사를 유발한 제안의 구간과 항상 일치해야 한다"는 기존 설계
      원칙(2026-10-06 엔트리)을 그대로 따른 것이다. 이를 위해 `control_tower.Proposal`에 선택
      필드 `window_seconds`(기본값 `None`)를 추가했다 — 기존 모든 호출부(`production_agent`,
      `equipment_agent`, `llm_agent`, `simulation.py`, 테스트)가 전부 키워드 인자만 쓰고 있어서
      하위 호환이 깨지지 않는 것을 코드로 확인했다.

      격리 서버(포트 18799, 전용 DB)에 ETCH 설비 3대를 전부 curl로 DOWN시켜 로트를 HOLD시키고
      시뮬레이션을 켜서 실시간으로 확인하던 중, 첫 조사 결과가 `down_count_in_window=0`으로
      나오는 실제 버그를 발견했다 — 분명히 방금 3대를 다운시켰는데도 조사 Artifact는 "다운타임
      없음"이라고 보고했다. 원인: `window_seconds`가 정확히 "지금 - HOLD 시작 시각"이어서 조회
      컷오프 `since`가 HOLD 시작 시각과 거의 같은 지점에 놓이는데, HOLD를 유발한 다운타임은
      반드시 HOLD가 시작되기 "직전"에 시작된다(그 설비가 먼저 DOWN되어야 `advance_lot`이 그
      로트를 HOLD시킬 수 있음, 결코 그 반대가 아님) — 실측에서는 단 32밀리초 차이로
      `started_at >= since` 조건에 걸려 잘려나갔다. 품질/설비 조사가 쓰는 `_recent_downtime`도
      구조적으로 같은 버그를 안고 있지만, 고정 창(600~1800초)이 실제 다운타임 길이(몇 초~몇십
      초)보다 훨씬 커서 지금까지 경계에 걸릴 일이 없었을 뿐이다(생산 조사는 창 자체가 HOLD
      대기시간과 같아서 이 경계 조건을 즉시, 매번 만든다). 두 조회 함수 모두 "아직 닫히지 않은
      (`ended_at IS NULL`) 다운타임은 시작 시각과 무관하게 항상 포함"하는 OR 조건으로 고쳤다 —
      지금 실제로 멈춰 있는 설비는 언제부터 DOWN이었는지와 무관하게 조사 범위 안에 있어야
      한다는 것이 올바른 의미이기 때문이다. 고친 뒤 같은 재현 시나리오를 다시 실행해
      `down_count_in_window=3`(ETCH-01/02/03 각 1건)으로 정확히 나오는 것, 그리고 LOW
      티어(30초)에서 조사 Task #1이 먼저 만들어지고 같은 Task가 5분 억제 창 안에서 재사용되다가
      MEDIUM 티어(91초 대기)의 실제 승인 요청 evidence에 `A2A Task #1`로 정확히 인용되는 것까지
      wall-clock으로 확인했다.

      검증: 신규 pytest 5개(`tests/test_a2a.py` 3개 — 스텝 전체 설비의 다운타임 풀링, 이번에 찾은
      경계 버그의 회귀 테스트, 캘리브레이션된 Window 존중; `tests/test_control_tower.py` 2개 —
      Task 생성과 evidence 인용 통합 검증, 5분 억제 창 안에서 재발동 안 함) + 기존 2개 수정
      (`agent_cards` 레지스트리·엔드포인트가 이제 세 에이전트를 반환하는지로 Assertion 갱신)
      전체 215 -> 220개 통과. `GET /a2a/agent-cards` 실호출로 세 번째 카드
      (`production-investigation-agent`)가 포함되는 것도 확인했다. 50 VU/3분 파이프라인
      재확인(요청 16,257건, 실패율 0.00%, RPS 90.68, p95 34ms/p99 85ms, Server
      5xx/IntegrityError 0) — 이 Locust 시나리오는 `/simulation/start`를 호출하지 않아 새 생산
      투자 Task 생성 자체는 이번 리포트에 반영되지 않는다(품질·설비 Task와 같은 기존 한계).
      한계: 세 에이전트 모두 A2A "진짜" 에이전트 간 통신은 구현하지 않았다(여전히 한 에이전트
      내부에서 Task 개념만 빌려 쓴 것, 2026-10-05/06과 동일). `GET /a2a/tasks`는 `equipment_id`로만
      필터하므로 생산 Task(항상 `equipment_id=null`)를 공정 스텝으로 좁혀 조회할 방법이 아직 없다.

- [x] (2026-10-08) `GET /a2a/tasks`에 `process_step` 쿼리 파라미터를 추가했다 — 바로 위
      2026-10-07 엔트리에 남긴 한계이자 HITL 진행 현황 DB의 "2 규칙 에이전트" 행에 적힌 다음
      할 일이었다. `rule:production-hold`의 Task(`investigate_step_hold`)는 공정 스텝 전체가
      멈춘 것이라 `equipment_id=null`이고 공정 스텝 이름이 `equipment_name`에 들어가므로, 기존의
      `equipment_id` 필터로는 좁혀 조회할 수 없었다. `process_step` 파라미터는
      `equipment_id IS NULL AND equipment_name = process_step` 조건으로 매칭한다. 설계 결정:
      `equipment_id`와 `process_step`을 동시에 넘기면 두 조건을 AND로 합쳐 항상 빈 결과를 조용히
      돌려주는 대신 422로 명시적으로 거부한다 — 어떤 Task 행도 특정 설비를 가지면서 동시에
      `equipment_id=null`일 수 없으므로 "둘 다 지정"은 항상 사용자 실수이기 때문이다. `agent_gateway`
      MCP Tool `get_investigation_tasks`와 README도 같은 파라미터로 맞췄다. 신규 pytest 2개
      (`process_step`으로 생산 Task만 걸러지는지, 두 파라미터를 함께 주면 422인지) 포함 전체
      220 -> 222개 통과. 격리 포트(18810)에 실제 uvicorn 서버를 띄워 `curl`로 필터 없음/
      `process_step=ETCH`/`equipment_id`+`process_step` 동시 지정(422) 세 가지를 직접 확인했고,
      `.venv-mcp`의 `agent_gateway.smoke_test`에 `process_step="ETCH"` 호출을 추가해 통과시켰다.
      (실제 production Task 행으로 end-to-end 필터링까지 확인하려면 ETCH 설비 3대를 전부 DOWN시켜
      HOLD를 유발해야 하는데, 수동 PATCH로 설비를 DOWN시켜도 시뮬레이션 틱이 자체 Fault 모델에
      따라 금방 RUN으로 되돌려 격리 서버에서는 재현하지 못했다 — 이 메커니즘 자체는 2026-10-07에
      이미 실제로 검증됐으므로, 오늘은 유닛 테스트 + 실제 서버에 대한 파라미터/검증 동작 확인으로
      충분하다고 판단했다.) 50 VU/3분 파이프라인 재확인(요청 15,498건, 실패율 0.00%, RPS 86.32,
      p95 190ms/p99 460ms, Server 5xx/IntegrityError 0, 예상 409 충돌 90건).

- [x] (2026-10-09) 대시보드 승인 큐 카드에 A2A 조사 Task/Artifact("조사 근거 보기") 노출 — 2026-10-06
      엔트리부터 반복해서 ROADMAP "다음 후보"와 HITL 허브 Section 5 한계로 남아 있던 "대시보드에
      세 에이전트의 Task/Artifact가 아직 노출되지 않는다" 항목을 닫았다. 지금까지는 승인 카드의
      `evidence` 문자열 끝에 `A2A Task #<id>`가 붙어 있어도 실제 조사 내용(불량률/동료평균/
      z-score, 또는 다운타임 목록)을 보려면 `GET /a2a/tasks/{id}`를 직접 호출해야 했다. 승인
      PENDING/DECIDED 카드 모두에 `evidence`에서 `A2A Task #(\d+)`를 정규식으로 추출해 "조사 근거
      보기" 버튼을 추가하고, 클릭 시 기존 로트/설비 드로어와 같은 패턴의 읽기 전용 드로어를 열어
      `GET /a2a/tasks/{id}` 응답(상태·요약·evidence 전체)을 보여준다. 백엔드 변경 없음(이미 있는
      API를 그대로 사용) — 순수 프론트엔드 추가. 검증 중 실제 버그를 하나 발견해 함께 고쳤다:
      `recent_downtime_events`를 일반 key/value 테이블로 렌더링했더니 드로어 폭(420px)보다 넓은
      696px 테이블이 만들어져 드로어 내부에서 가로 스크롤이 필요했다(Playwright로
      `drawer.scrollWidth`(696) vs `drawer.clientWidth`(419)를 직접 측정해 확인 — 페이지 레벨
      `document.documentElement.scrollWidth` 검사만으로는 이 내부 overflow를 잡지 못했다는 것도
      함께 확인). 대안 A(테이블을 `overflow-x:auto` 컨테이너로 감싸 가로 스크롤 허용)는 기각하지
      않고 그 외 임의의 object 모양(예: `by_reason`/`by_equipment` 집계)에 대한 fallback으로는
      남겨뒀지만, `recent_downtime_events`처럼 모양이 고정된 필드는 대안 B(설비명·사유·시작→종료
      시각·지속시간을 한 줄로 합친 compact 목록, 기존 로트/설비 드로어의 timeline 스타일과 통일)를
      선택했다 — 폭 문제를 근본적으로 없애고 다른 드로어들과 시각적으로도 일관된다. 검증: 격리
      서버(포트 18900)에서 `scripts/demo_approvals.py s2`로 INSPECT-01 품질 이상을 실제로 만들어
      A2A Task #1을 생성한 뒤 Playwright로 (1) PENDING 탭에서 버튼 클릭 → 드로어에 요약·evidence
      전체(불량률 0.75, peer_mean 0.039, z-score 18.5, 다운타임 1건)가 compact 한 줄로 표시, (2)
      반려 없이 승인 처리 후 DECIDED 탭에서도 같은 버튼으로 같은 Task가 열리는 것, (3) 1280px·
      390px 두 뷰포트 모두 `document.documentElement.scrollWidth`가 `clientWidth`와 같아 페이지
      레벨 가로 스크롤 없음, (4) 드로어 자체의 `scrollWidth`도 수정 후 419=419로 내부 overflow
      해소, (5) 닫기 버튼 동작, (6) 콘솔 에러가 기존에 이미 있던(2026-10-02에 문서화된)
      `/favicon.ico` 404 외에는 없음을 모두 확인했다. pytest는 프론트엔드만 바꿔 영향 없이
      222개 그대로 통과. 50 VU/3분 파이프라인도 재확인(요청 15,168건, 실패율 0.00%, RPS 84.49,
      p95 210ms/p99 490ms, Server 5xx/IntegrityError 0, 예상 409 충돌 67건) — p95/p99가 최근
      기준선(34~200ms대)보다 다소 높은 편인데, 이 실행 직전 같은 세션에서 UI 검증용 uvicorn
      서버와 Playwright를 여러 차례 띄워 작업했던 것과 겹친 공유 컨테이너 CPU 경합 가능성이
      높다(PAR-013/PAR-018과 같은 유형) — 2026-10-08 리포트도 비슷한 범위(p95 190/p99 460)였어서
      이 변경 자체가 일으킨 회귀라는 근거는 없다. INSPECT-03 WARNING(불량률 25.93% vs 피어
      0%, n=54)은 2026-09-20부터 반복돼 온 동일 Baseline 패턴이라 새 이상으로 기록하지 않았다.
      PAR 판단: 이번 작업은 계획된 기능 추가(승인 근거 가시성)였고 찾은 버그도 구현 중 자체
      검증(Playwright)으로 배포 전에 잡은 레이아웃 문제라 "두 개 이상 해결 방향을 실제로 비교"
      조건은 약하게만 충족한다고 보고, 전체 PAR 9문항 대신 Notion 'D. 설계 결정'과 'E. 문제·해결
      로그'에만 기록했다(CLAUDE.md 42번 PAR 후보 조건 참고 — 매번 PAR를 억지로 만들지 않는다).

## 다음 후보 (우선순위 순서는 참고용, 상황 따라 조정 가능)

- [x] (2026-10-11 완료) ~~2026-10-10에 컨트롤타워 판단 탭에 추가한 `app.a2a.latest_task_ids`를
      설비 드릴다운 드로어와 "이상 이력" 화면에도 연결~~ → 설비 드로어는 기존 `GET
      /a2a/tasks?equipment_id=` 필터(이력 전체를 이미 반환)를 그대로 재사용했고, "이상 이력"은
      `anomaly_log_id` 직접 FK 조회용 `task_ids_by_anomaly_log`를 새로 추가했다 — 둘 다
      `latest_task_ids`를 재사용하지 않았다(위 완료 섹션 참고). 새 "다음 후보": 컨트롤타워 판단
      탭도 "결정 시점 이전 최신 1건" 대신 이력 전체를 보여주도록 확장할 가치가 있는지 판단, 설비
      드로어의 조사 이력도 감사 로그처럼 페이지네이션 없이 `limit=100`을 그대로 쓴다.
- [x] (2026-10-06 완료) ~~agent_gateway 전용 가상환경 분리~~ → `.venv-mcp/`를 실제로 만들어
      `pip install -r agent_gateway/requirements.txt`로 `mcp[cli]`를 설치하고, 메인 `.venv`와
      완전히 분리된 상태로 smoke test와 신규 Tool 2개(`get_agent_cards` 호출 포함)를 모두
      통과시켰다 — 메인 venv는 전혀 건드리지 않아 2026-10-05에 겪었던 `pydantic`/`starlette`
      충돌이 재발하지 않았다. README(`agent_gateway/README.md`)가 이미 이 명령을 문서화하고
      있었다는 것도 확인했다(실제로 만들어 쓴 적만 없었던 것). 아래 완료 섹션 참고.
- [x] (2026-10-06 완료) ~~A2A Quality Investigation Agent를 설비 에이전트에도 확장~~ →
      `app/a2a.py`에 `investigate_equipment_downtime()`과 `EQUIPMENT_AGENT_CARD` 추가, 품질
      에이전트와 같은 `InvestigationTask` 테이블을 `agent_id`로 구분해 재사용. 아래 완료 섹션
      참고. 생산 에이전트(`rule:production-hold`)는 아직 연결되지 않았다 — 다음 항목.
- [x] (2026-10-07 완료) ~~A2A 투자 Task/Artifact 패턴을 생산 에이전트(`rule:production-hold`)에도
      확장~~ → `app/a2a.py`에 `investigate_step_hold()`와 `PRODUCTION_AGENT_CARD` 추가(그 스텝에
      배정된 설비 전체의 다운타임을 모으는 방식). 이 작업 중 조사 Window 경계에서 실제 버그를
      발견·수정했다(아래 완료 섹션, PAR 후보 참고).
- [ ] 오늘(2026-10-04) 승인 큐 지표 보정은 스크립트가 대신 결정한 합성 표본 4건 기반이었다 —
      실제 사람이 대시보드 승인 큐 화면에서 직접 승인/반려를 누른 데이터가 쌓이면
      (`decided_by`가 `demo-calibration`이 아닌 실제 사용자/운영자인 행 기준으로) 같은 네
      지표를 다시 집계해 합성 표본과 실제 사람 표본이 얼마나 다른지 비교할 가치가 있다.
- [ ] `scripts/demo_approvals.py`의 `s4 --isolate`가 "주입 시점부터"만 격리한다는 경계 조건을
      실측으로 확인했다(2026-10-01) — 완전한 격리가 필요하면 호출부가 시나리오 시작 40초
      전부터 override를 걸어야 한다. 지금은 문서화만 했고 스크립트가 자동으로 그 여유 시간을
      기다려주지는 않는다. 필요하면 `s4`가 `--isolate` 시 자체적으로 40초(또는
      `CONCURRENT_DOWN_WINDOW_SECONDS`를 gateway 도구로 조회해 그 값) 만큼 먼저 대기한 뒤
      DOWN을 시작하도록 만들 가치가 있는지 판단.
- [ ] Gateway에 추가한 `get_approval_queue`/`get_control_tower_decisions`를 실제로 사용하는
      LLM 에이전트(또는 A2A Quality Investigation Agent)가 승인 큐 상태를 근거로 삼아 조사
      결과를 보강하는 예시를 만들어본다 (지금은 Tool만 있고 이를 소비하는 에이전트 로직은 없음)
- [x] (2026-09-28 완료) ~~승인 큐 Audit Trail~~ → `app/audit.py` + `GET /audit-log`로 구현
      완료. (2026-10-02 완료) ~~대시보드 감사 로그 화면~~ → 위 완료 섹션 참고. 다음 단계는
      감사 로그에도 승인 큐처럼 신규 행 배지나 행 클릭 시 해당 설비/작업지시로 바로 이동하는
      drill-down을 붙일지 검토 (지금은 단순 목록+필터만 제공)
- [x] (2026-10-03 완료) ~~SQLite 동시 Write Lock 재현·원인 분석~~ → EXP-011/PAR-018
      참고. 재현에는 실패했고(0.012% 빈도), WAL 모드는 측정 결과 채택하지 않았다(아래
      새 항목 참고). 대신 `connect_args={"timeout": 15}`만 적용.
- [ ] EXP-011에서 WAL 모드가 측정상 기각됐지만(p95 4.5배 회귀, `-wal` 파일 300MB+
      무한 증가 — checkpoint 기아 추정), 명시적 주기적 `PRAGMA wal_checkpoint`
      튜닝을 곁들이면 그 회귀 없이 WAL의 이점을 얻을 수 있는지는 확인하지 못했다.
      `database is locked`가 다시 실제로 관측되면(현재는 0.012% 빈도라 일상적으로는
      우선순위 낮음) 재검토할 가치가 있음.
- [ ] `scripts/summarize.py`의 다른 정규식/파서(예: `integrity_errors`의 단순 부분 문자열
      매칭)도 실제 캡처된 `server.log`로 한 번씩 대조해 `server_5xx`와 같은 "실제 로그
      포맷과 안 맞아 조용히 0만 찍히는" 문제가 더 있는지 감사 (2026-09-28 PAR-014 재발 방지
      연장)
- [ ] 오늘 추가한 승인 큐 지표(승인율/수정율/대기시간/너무 빠른 승인 비율)를 시뮬레이션 엔진이
      자동으로 승인 요청을 만들도록 데모 시나리오를 하루 이상 돌려 실제 0이 아닌 값으로 채워보고,
      `fast_approval_rate` 임계값(5초)이 데모 시나리오에서 그럴듯한 값을 만드는지 확인
- [x] (2026-10-05 완료) ~~A2A Quality Investigation Agent: Agent Card, Task 상태, 조사
      Artifact와 승인 Gate~~ → `app/a2a.py` + 품질 에이전트 연결로 구현. 완료 섹션과 위
      "다음 후보"의 확장 항목(설비/생산 에이전트로 확대) 참고.
- [ ] C# UI LOT 검색/Event Timeline과 Work Order 상세 화면
- [ ] 품질 이상 신호에서 관련 LOT/검사/Event 자동 Drill-down
- [ ] PostgreSQL 전환 후 조건부 UPDATE vs `SELECT FOR UPDATE` 동시성 비교
- [ ] `/metrics`에 설비별 MTBF/MTTR이 아니라 공장 전체 평균 MTBF/MTTR을 노출 (2026-09-23에
      `GET /equipment`와 일일 리포트에는 추가했지만 대시보드 개요 카드에는 아직 없음 — 지금은
      설비 상세 드릴다운을 열어야만 개별 값을 볼 수 있다)
- [ ] Performance 계산에 쓰는 목표 Cycle Time(현재 시뮬레이션 dwell 설정 중간값 10s로 고정)을
      공정 스텝별로 다르게 설정하거나, 실제 `PROCESS_STARTED` 이벤트를 추가해 측정된 실제
      평균 처리시간과 비교하는 것으로 고도화 (현재 이벤트 저널에는 `PROCESS_COMPLETED`만 있고
      공정 시작 시점을 별도로 기록하지 않아 "설계 목표"와 "실측값"을 나란히 비교할 수 없다)
- [ ] 전일 대비 이상 탐지 고도화 (단순 임계치 대신 최근 N일 평균/표준편차 기반)
- [ ] Locust 우선순위 로트/배치 사이즈 변화 시나리오 (설비 랜덤 다운은 2026-09-21에 추가 완료)
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
- [ ] 헬스체크가 uvicorn stdout/stderr 로그(Traceback/500)뿐 아니라 `/simulation/status`의
      `recent_events`에서 반복되는 "⚠️" 패턴도 함께 감지하도록 확장 — PAR-007에서 tick을 통째로
      멈추게 한 예외가 서버 로그에는 전혀 안 남고 시뮬레이션 메모리 이벤트 피드에만 기록되던
      관측 공백을 로그 출력 추가로 일부 메웠지만, 적극적으로 그 패턴을 찾아 알려주는 건 아직 없음
- [ ] `run_daily_test.sh`에 "포트/DB 파일이 이미 사용 중이면 즉시 실패"만 있고 "이전 실행이
      아직 안 끝났으면 기다렸다 이어서 돈다" 옵션이 없다 — 2026-09-25 실행 중 같은 파이프라인을
      두 번째로 띄웠다가 첫 번째가 쓰던 `mes.db`를 두 번째의 `rm -f mes.db`가 지워버려서
      "attempt to write a readonly database" 500 에러가 대량 발생한 사고를 겪었다(PAR-006과
      같은 유형의 실수 재발). 스크립트 시작 시 락 파일(`reports/raw/.run.lock`)을 만들어 이미
      실행 중이면 그 사실을 명확히 에러로 알리고 종료하도록 방어 코드를 추가할 가치가 있다.
- [ ] 2026-09-25 재측정에서 N+1 쿼리를 고친 뒤에도 `GET /equipment [list]` p95(320ms)와
      전체 Aggregated p95(240ms)가 최근 기준선(34\\~190ms) 상단에 남아 있었다 — 같은 세션에서
      파이프라인을 여러 번 반복 실행한 뒤라 공유 컨테이너 CPU 경합 때문일 가능성이 높지만
      확인하지 못했다. 별도의 조용한 세션에서 한 번 더 50 VU·3분을 돌려 반복 재현되는지
      확인하고, 재현되면 진짜 회귀로 조사한다.

- [ ] 오늘 추가한 감사 로그 화면은 `GET /audit-log`의 기본 `limit=100`(최대 500)을 그대로 쓰고
      페이지네이션이 없다 — 하루 동안 기록이 그 이상 쌓이면 오래된 변경은 화면에서 조회할 방법이
      없다(API 자체는 `entity_id`로 좁혀 조회 가능하지만 UI에는 그 입력이 없음). 날짜/건수 기반
      페이지네이션이나 "더 보기" 버튼을 추가할 가치가 있는지 다음에 실제 누적량을 보고 판단한다.

- [x] (2026-10-09 부분 완료) ~~대시보드 "이상 이력"/"승인 큐" 화면에 설비 조사 Task를 노출하지
      않는 문제~~ → 승인 큐 카드(PENDING/DECIDED 둘 다)에 "조사 근거 보기" 버튼을 추가해 세
      에이전트(품질·설비·생산) 모두의 Task/Artifact를 볼 수 있게 됐다(아래 완료 섹션 참고). 다만
      이건 evidence 문자열에 `A2A Task #<id>`가 붙은 승인 요청에서만 진입 가능하다 — 설비 상세
      드릴다운 드로어에 "이 설비 관련 조사 이력"을 보여주는 것과 "이상 이력" 화면에서 과거 이상에
      연결된 조사를 보여주는 것은 아직 없다. 또한 컨트롤타워가 AUTO_RECORD(LOW)로 분류해 승인
      요청을 만들지 않은 조사 Task는 승인 큐 어디에도 나타나지 않아 여전히 API로만 조회 가능하다.
- [x] (2026-10-08 완료) ~~`GET /a2a/tasks`는 `equipment_id`로만 필터할 수 있어 생산 조사
      Task를 스텝 단위로 좁혀 조회할 방법이 없는 문제~~ → `process_step` 쿼리 파라미터 추가.
      아래 완료 섹션 참고.
- [ ] 오늘(2026-10-07) `app/a2a.py`의 다운타임 조회 두 함수에서 "조사 Window가 정확히 그 제안이
      측정한 구간과 같을 때, 원인이 되는 다운타임이 그 구간 시작 직전에 시작해 경계에서 잘려나갈
      수 있다"는 버그를 발견·수정했다(`ended_at IS NULL`이면 시작 시각과 무관하게 항상 포함).
      이 수정이 실제로 막는 조건(원인 이벤트가 조사 대상 윈도 시작 수십 ms 전에 시작하는 경우)이
      품질·설비 조사의 고정 창(1800초/600초)에서도 아주 드물게 일어날 수 있는지는 확인하지
      않았다 — 두 조사 모두 고정 창이 실제 다운타임 길이보다 훨씬 커서 이론상으로만 가능하다고
      판단했지만, 실제로 재현된 적은 없다. 세 조사 모두에 대해 "닫힌 다운타임 중 경계 몇 ms
      차이로 빠진 사례가 과거 Task에 있었는지"를 `artifact_json`을 다시 읽어 감사할 가치가
      있는지 다음에 판단한다.
- [ ] 2026-10-08에 `process_step` 필터를 실제 설비 다운으로 end-to-end 확인하려다 겪은 제약:
      시뮬레이션이 켜져 있는 상태에서 `PATCH /equipment/{id}`로 설비를 수동 DOWN시켜도, 그
      설비를 직접 추적하지 않는 시뮬레이션 틱의 자체 Fault 모델이 몇 초 안에 다시 RUN으로
      되돌린다(수동 PATCH가 `EquipmentDowntimeEvent`를 만들지 않아 시뮬레이션이 "이것도 내가
      추적해야 할 다운타임"으로 인식하지 못하는 것으로 추정 — 코드까지 추적해 확정하지는 않음).
      이미 있는 `inject_defect_bias`/`fault_rate_override` 패턴처럼, 디버그·시연용으로 특정
      설비를 일정 시간 "강제 DOWN 유지"하는 주입 엔드포인트를 추가하면 다음에 같은 종류의 수동
      재현(오늘처럼 설비 전체를 DOWN시켜 생산 조사 Task를 직접 만들어보는 것)이 쉬워질 가치가
      있는지 판단한다.
- [x] (2026-10-10 완료) ~~2026-10-09에 승인 큐 카드에 "조사 근거 보기"를 추가하면서 확인한 gap:
      컨트롤타워가 AUTO_RECORD(LOW 위험도)로 판정해 승인 요청을 만들지 않은 조사 Task는 승인 큐
      어디에도 evidence 문자열이 없어 "조사 근거 보기" 진입점이 없던 문제~~ → `towerDecisionCard`
      (컨트롤타워 판단 탭, AUTO_RECORD/BLOCK/QUEUE 전부)에도 같은 버튼을 추가했다. 접근 방식은
      기존 PENDING/DECIDED 카드가 쓰던 evidence 문자열 정규식 파싱과 다르다 — `ControlTowerDecision`
      테이블 자체에는 evidence/title 컬럼이 전혀 없어(`equipment_id`/`equipment_name`/`reason`만
      저장, app/control_tower.py) AUTO_RECORD 행은 애초에 파싱할 문자열이 없기 때문이다. 대신
      `app.a2a.latest_task_ids(db, keys)`를 새로 추가해, `(equipment_id, equipment_name, cutoff)`
      키마다 "그 설비(또는 생산 에이전트처럼 equipment_id가 없으면 공정 스텝 `equipment_name`)의,
      `cutoff`(=decided_at) 시각 이전에 생성된 가장 최근 InvestigationTask" id를 직접 조회해
      `GET /control-tower/decisions`가 `latest_task_id` 필드로 내려주게 했다.

      설계 결정 두 가지: (1) 결정 건당 쿼리 1회(N+1)가 아니라 전체 decisions의 equipment_id
      집합과 process-step 집합 각각 1회씩, 총 2회 쿼리로 배치 처리한다 — 2026-09-25에 `GET
      /equipment`에서 겪은 것과 같은 유형의 N+1 회귀를 이 폴링 전용(4초 간격) 엔드포인트에
      새로 들여오지 않기 위함이다. (2) `cutoff`로 `decided_at` 이전 Task만 매칭한다 — cutoff
      없이 그냥 "그 설비의 가장 최근 Task"를 썼다면, 목록에 오래 남아있는 과거 AUTO_RECORD
      행이 그 이후 같은 설비에 발생한 무관한 최신 조사와 잘못 연결될 수 있었다.

      검증: 신규 pytest 5개(222→227 — `latest_task_ids`의 cutoff 전후 경계 2건, 공정 스텝 매칭
      1건, 엔드포인트 통합 2건) 전체 통과. 격리 서버(포트 18950)에 ETCH 설비 1대를 3회
      DOWN/IDLE시켜(4회가 아닌 3회라 MEDIUM이 아닌 LOW/AUTO_RECORD) 실시간으로 `GET
      /control-tower/decisions`가
      `approval_id: null`인 행에 `latest_task_id: 1`을 정확히 채우는 것을 확인했고(해당 Task는
      실제로 그 3회 DOWN을 모은 Artifact를 갖고 있었다), Playwright로 컨트롤타워 판단 탭에서
      버튼 클릭 → 드로어가 올바른 Task #1을 열고 닫히는 것, 1280px·390px 두 뷰포트 모두 페이지와
      드로어 내부 모두 가로 스크롤 없음을 확인했다(기존 /favicon.ico 404 외 콘솔/네트워크 에러
      없음). 50 VU/3분 파이프라인 재확인(요청 14,850건, 실패율 0.00%, RPS 82.70, p95 250ms/
      p99 590ms, Server 5xx/IntegrityError 0, 예상 409 충돌 102건) — p95/p99가 최근 기준선보다
      다소 높은데, 이 실행 직전 같은 세션에서 격리 서버·Playwright 검증을 여러 차례 띄운 뒤라
      PAR-013/018/2026-10-09와 같은 유형의 공유 컨테이너 CPU 경합으로 추정하며 코드 회귀 근거는
      없다. INSPECT-03이 오늘 처음 CRITICAL로 분류됐다(불량률 31.48% vs 피어 0%, n=54,
      `rate_delta>=0.30` 임계값을 근소하게 넘김) — 2026-09-22 Notion '12. Quality Anomaly Log'에
      이미 기록된 대로 이는 `load_test/locustfile.py`의 의도된 결정론적 Fault Injection(약
      25%가 실패하도록 설계)이 내는 자연스러운 표본 변동 범위(약 20~30%) 안이라 새 이상으로
      기록하지 않았다.

      한계: 설비 상세 드릴다운 드로어와 "이상 이력" 화면에서의 조사 연결은 여전히 없다(아래
      새 항목 참고). `latest_task_id`는 "그 결정 시점 이전 가장 최근" 매칭일 뿐, 그 결정을
      실제로 유발한 조사라는 보장은 아니다 — 같은 설비에 대한 두 조사 Task가 억제 창(5분) 안에서
      합쳐지지 않고 모두 결정 이전에 생성된 드문 경우, 더 최근 것이 선택된다(그 둘의 조사
      결과가 거의 항상 같은 조건을 설명하므로 실질적으로는 문제되지 않는다고 판단).

- [x] (2026-10-11 완료) ~~2026-10-10에 남긴 두 gap: (1) 설비 상세 드릴다운 드로어에 "이 설비 관련
      조사 이력", (2) "이상 이력" 화면에서 과거 AnomalyLog 행에 연결된 조사 표시~~ → 둘 다 닫았다.
      먼저 코드를 확인해보니 (1)은 새 배치 조회 함수가 필요 없었다 — `GET /a2a/tasks?equipment_id=`
      필터(2026-10-05부터 이미 존재)가 "그 설비의 Task 전체 목록"을 최신순으로 그대로 돌려주고
      있어서, 설비 드로어가 `/equipment/{id}/events`와 같은 `Promise.all`로 그 엔드포인트를 한 번
      더 호출해 "이 설비 관련 조사 이력" 섹션에 나열하기만 하면 됐다(새 백엔드 쿼리 없음). (2)는
      `InvestigationTask.anomaly_log_id`가 이미 1:1 FK로 존재하지만(품질 에이전트가 `AnomalyLog`
      행을 쓸 때 그 행의 id를 그대로 넘겨 호출 — `app/simulation.py`) `GET /a2a/tasks`에는 그 값으로
      거르는 필터가 없었다. `latest_task_id`(2026-10-10)처럼 "커서 이전 최신값 추정" 방식이 아니라
      — 이 관계는 추정이 아니라 직접 FK이므로 — 새 `app.a2a.task_ids_by_anomaly_log(db, ids)`가
      `anomaly_log_id IN (...)` 한 번의 쿼리로 `{anomaly_log_id: task_id}` 맵을 돌려주게 했고,
      `GET /quality/anomaly-log`가 이를 `investigation_task_id` 필드로 노출한다. `GET /a2a/tasks`에도
      `anomaly_log_id` 쿼리 파라미터를 추가해(기존 `equipment_id`/`process_step`과 상호 배타,
      2개 이상 지정 시 422) 같은 값으로 직접 조회할 수 있게 했다. `agent_gateway`의
      `get_investigation_tasks`/`get_anomaly_log`와 README도 함께 맞췄다.

      검증: 신규 pytest 7개(234개 전체 통과 — `anomaly_log_id` 필터 3건, 상호배타 422 2건,
      `task_ids_by_anomaly_log` 2건, `/quality/anomaly-log` 응답 배선 2건). 격리 서버(포트 19010)에서
      시뮬레이션을 켜고 `scripts/demo_approvals.py s2`로 INSPECT-01 품질 이상을 실제로 만들어
      `AnomalyLog` 행(id=1)과 그 조사 Task(id=1)가 실제로 생성되는 것을 wall-clock으로 확인했고,
      `GET /quality/anomaly-log`가 `investigation_task_id: 1`을, `GET /a2a/tasks?anomaly_log_id=1`이
      같은 Task를 정확히 돌려주는 것을 curl로 확인했다. Playwright로 (1) "이상 이력" 탭의 "조사 근거
      보기" 버튼 클릭 → 기존 드로어가 올바른 Task를 열고, (2) 설비 현황의 INSPECT-01 카드를 클릭 →
      드로어에 "이 설비 관련 조사 이력" 섹션이 나타나고 그 안의 버튼도 같은 드로어를 여는 것,
      (3) 모바일 390px에서 페이지 레벨 가로 스크롤 없음을 확인했다(기존 `/favicon.ico` 404 외
      콘솔/네트워크 에러 없음). `.venv-mcp`의 `agent_gateway.smoke_test`도 `anomaly_log_id` 호출을
      추가해 통과시켰다. 50 VU/3분 파이프라인 재확인(요청 16,214건, 실패율 0.00%, RPS 90.01,
      p95 69ms/p99 160ms, Server 5xx/IntegrityError 0, 예상 409 충돌 44건 — 최근 기준선 안).
      INSPECT-03 WARNING(24.59% vs 피어 0%, n=61)은 2026-09-20부터 반복된 동일 Baseline 패턴이라
      새 이상으로 기록하지 않았다.

      PAR 판단: 실제 버그를 발견·수정한 것이 아니라 계획된 기능(이미 있던 설계 결정 2026-10-10의
      "자매 함수 필요성 판단"을 실행)이고, 두 화면 모두 기존 데이터·엔드포인트 패턴을 그대로
      재사용해 "두 대안을 실제로 비교"한 것도 약하다고 보아 PAR 대신 'D. 설계 결정'·'E. 문제·해결
      로그'에만 기록했다(CLAUDE.md 42번 기준, 2026-10-08과 같은 판단).

      한계: 설비 드로어의 조사 이력은 `GET /a2a/tasks`의 기본 `limit=100`을 그대로 쓰고
      페이지네이션이 없다(2026-10-02 감사 로그 화면이 남긴 것과 같은 유형의 한계). 컨트롤타워
      판단 탭은 여전히 "그 결정 시점 이전 최신 1건"만 보여준다(`latest_task_id`) — 이제 다른 두
      화면이 "이력 전체"를 보여주는 패턴이 생겼으니, 컨트롤타워 탭도 같은 식으로 확장할 가치가
      있는지는 다음에 판단한다.

## 에이전트 작업 원칙

- 매일 작업을 시작할 때 `TZ=Asia/Seoul date`로 오늘 날짜(KST)를 먼저 확인하고, ROADMAP/리포트/Notion
  날짜를 전부 그 값으로 통일합니다 — 실행 시각의 UTC 날짜만 보고 그대로 적으면 KST 00:00~08:59
  사이 실행에서 하루 전으로 틀리게 됩니다(2026-09-19에 같은 유형의 버그를 이미 고쳤는데, 2026-10-02
  실행에서 에이전트가 그 관례를 다시 확인하지 않아 또 틀릴 뻔했습니다 — Notion 'E. 문제·해결 로그' 참고).
- 매일 최소 1개 항목을 실제로 구현하고 검증(테스트 또는 스모크 테스트) 후 커밋합니다.
- 리스크가 크거나 사용자 판단이 필요한 항목(과금되는 외부 서비스, 큰 아키텍처 변경 등)은 건너뛰고
  리포트의 "사용자에게 요청" 항목에 이유와 함께 남깁니다.
- 항목을 완료하면 체크 표시하고, 새로운 개선 아이디어를 최소 1개 이상 추가해 백로그를 유지합니다.
- 매일의 변경 이력은 git 커밋 로그와 `reports/`, 이 파일의 "완료" 섹션에 남아 그 자체로 성장 과정을
  보여주는 포트폴리오 스토리가 됩니다.
- [x] (2026-09-25) 시뮬레이션 시나리오 근거 조사 후 UI(시뮬레이션 패널)와 README에 "학습용 축소 모델·데모 값" 안내를 추가했다.
      공개 자료로 확인된 것: 공정 종류, 수백 단계 규모, SEMI E10 상태 분류와 MTBF/MTTR, cycle time = WIP/시작률(Little's law),
      수율 정의와 FPY(재작업 제외). 확인되지 않은 것: 단일 통과 경로, 12대/3대씩 구성, 도착 4초·공정 6~14초·WIP 40,
      고장 0.4%/초·수리 10~30초, 최소 dispatch 횟수 규칙, 불량률 10%, 재작업 1회 후 스크랩. 접근하지 못한 자료(ResearchGate 403 등)는 UNVERIFIED로 두었다.
- [x] (2026-09-25) 라이브 재기동 시 `no such column: equipment.down_seconds`로 서버 기동 실패. 원인: 라이브 `mes.db`가
      구버전 스키마였고 `create_all`은 없는 테이블만 만들 뿐 컬럼은 추가하지 않는다(마이그레이션 도구 없음, 테스트는 매번
      새 DB라 못 잡음). 조치: `mes.db` 백업 후 nullable 컬럼 2개(`down_seconds`, `created_at`)만 `ALTER TABLE ADD COLUMN`,
      모델과 대조해 다른 테이블 차이 없음 확인, 엔드포인트 6개 200 확인. DB 삭제·재생성은 데이터 손실이라 선택하지 않았다.
      한계: 시작 시 스키마 차이 검사와 마이그레이션 도구(Alembic 등)는 아직 없다. 같은 일이 다시 생길 수 있다.
      함께 `pytest.ini`(`testpaths = tests`)를 추가해 루트 `pytest`가 `agent_gateway/smoke_test.py`를 수집하지 않게 했다.
