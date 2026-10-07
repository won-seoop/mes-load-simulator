# FactoryFlow MES MCP Gateway

Claude, Codex 또는 다른 MCP Host가 MES의 현재 상태를 같은 방식으로 읽기 위한 read-only Gateway다.
MCP는 Agent 간 작업 위임 프로토콜이 아니라, Host가 MES 데이터와 도구를 안전한 경계 안에서 사용할 수
있게 하는 Context/Tool 연결 계층으로 사용한다.

## 제공 범위

- Resource `mes://overview`: 생산 KPI, 품질 KPI, 이상탐지 결과
- Resource Template `mes://lots/{lot_id}/trace`: LOT 상태·Event·검사 이력
- Tool `get_quality_anomalies`: 장비별 이상 신호와 판정 Threshold (매 호출마다 재계산되는 Live Snapshot)
- Tool `get_lot_trace`: 이상 LOT 원인 추적
- Tool `list_work_orders`: 최근 작업지시 조회
- Tool `get_equipment_status`: 설비 전체 상태·OEE 입력값(Availability/Performance)·MTBF/MTTR
- Tool `get_equipment_downtime`: 설비 1대의 다운타임 이력(Open/Closed, 최신순)
- Tool `get_anomaly_log`: 이상탐지가 처음 발견된 시점까지 남는 영구 이력(`get_quality_anomalies`와 달리 저장됨)
- Tool `get_approval_queue`: Human-in-the-Loop 승인 큐 조회(status로 PENDING/APPROVED/REJECTED/EXPIRED 필터)
- Tool `get_approval_summary`: 승인 큐 상태별·위험도별 집계
- Tool `get_control_tower_decisions`: 컨트롤타워의 BLOCK/AUTO_RECORD/QUEUE 판정 이력(병합 근거 포함)
- Tool `get_audit_log`: 설비 상태 PATCH·작업지시 Release·승인 결정의 누가/언제/무엇을/왜 통합 이력
  (entity_type/entity_id로 필터)
- Tool `get_agent_card`: 품질 조사 에이전트(quality-investigation-agent)의 AgentCard(이름/skills/capabilities).
  하위 호환용으로 유지 — 모든 등록 에이전트를 보려면 `get_agent_cards` 사용
- Tool `get_agent_cards`: 등록된 모든 조사 에이전트(품질·설비·생산 공정 스텝 정체)의 AgentCard 목록
- Tool `get_investigation_tasks`: 품질·설비·생산 조사 에이전트가 만든 A2A 스타일 Task 목록(`agent_id`로 구분,
  equipment_id 또는 process_step으로 필터 — 생산 에이전트 Task는 `equipment_id=None`이라 공정 스텝
  이름으로만 좁혀진다. 둘을 동시에 넘기면 422)
- Tool `get_investigation_task`: Task 1건의 상태와 Artifact(불량률/다운타임 근거 등 구조화된 조사 결과)

현재 단계는 의도적으로 read-only다. 작업지시 Release, 설비 상태 변경, Scrap/Rework 같은 생산 Command를
LLM이 직접 실행하지 않는다.

## 실행

```bash
python -m venv .venv-mcp
source .venv-mcp/bin/activate
pip install -r agent_gateway/requirements.txt
MES_API_BASE_URL=http://127.0.0.1:8000 python agent_gateway/server.py
```

stdio 방식이므로 Claude Desktop/Claude Code/Codex 같은 MCP Host 설정에서 위 Python 실행 명령을
서버 Command로 등록한다. Host별 사용자 설정 파일은 저장소에 Commit하지 않는다.

실행 중인 MES API에 대해 Protocol 목록과 Tool 호출을 함께 검증한다.

```bash
MES_API_BASE_URL=http://127.0.0.1:8000 .venv-mcp/bin/python -m agent_gateway.smoke_test
```
