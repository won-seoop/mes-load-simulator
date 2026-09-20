# FactoryFlow MES MCP Gateway

Claude, Codex 또는 다른 MCP Host가 MES의 현재 상태를 같은 방식으로 읽기 위한 read-only Gateway다.
MCP는 Agent 간 작업 위임 프로토콜이 아니라, Host가 MES 데이터와 도구를 안전한 경계 안에서 사용할 수
있게 하는 Context/Tool 연결 계층으로 사용한다.

## 제공 범위

- Resource `mes://overview`: 생산 KPI, 품질 KPI, 이상탐지 결과
- Resource Template `mes://lots/{lot_id}/trace`: LOT 상태·Event·검사 이력
- Tool `get_quality_anomalies`: 장비별 이상 신호와 판정 Threshold
- Tool `get_lot_trace`: 이상 LOT 원인 추적
- Tool `list_work_orders`: 최근 작업지시 조회

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
