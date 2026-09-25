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

## 다음 후보 (우선순위 순서는 참고용, 상황 따라 조정 가능)

- [ ] Gateway에 추가한 `get_approval_queue`/`get_control_tower_decisions`를 실제로 사용하는
      LLM 에이전트(또는 A2A Quality Investigation Agent)가 승인 큐 상태를 근거로 삼아 조사
      결과를 보강하는 예시를 만들어본다 (지금은 Tool만 있고 이를 소비하는 에이전트 로직은 없음)
- [ ] A2A Quality Investigation Agent: Agent Card, Task 상태, 조사 Artifact와 승인 Gate
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

## 에이전트 작업 원칙

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
