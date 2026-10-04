"""Read-only MCP gateway for MES operational context.

The gateway intentionally exposes observation capabilities only. Production
commands such as releasing a work order, changing equipment state or applying
quality disposition stay behind the MES API's explicit command boundary.
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from mcp.server.mcpserver import MCPServer


MES_API_BASE_URL = os.environ.get("MES_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

mcp = MCPServer(
    "FactoryFlow MES",
    website_url="https://github.com/won-seoop/mes-load-simulator",
)


def _get(path: str):
    request = Request(
        f"{MES_API_BASE_URL}{path}",
        headers={"Accept": "application/json", "User-Agent": "FactoryFlow-MCP/1.0"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"MES API returned HTTP {exc.code} for {path}") from exc
    except URLError as exc:
        raise RuntimeError(f"MES API is unavailable at {MES_API_BASE_URL}") from exc


@mcp.resource("mes://overview", mime_type="application/json")
def mes_overview() -> dict:
    """Current MES production, quality and anomaly summary."""
    return {
        "production": _get("/metrics"),
        "quality": _get("/quality/metrics"),
        "anomalies": _get("/quality/anomalies"),
    }


@mcp.resource("mes://lots/{lot_id}/trace", mime_type="application/json")
def lot_trace_resource(lot_id: str) -> dict:
    """Immutable process events and inspections for one lot."""
    return {
        "lot": _get(f"/lots/{int(lot_id)}"),
        "events": _get(f"/lots/{int(lot_id)}/events"),
        "inspections": _get(f"/lots/{int(lot_id)}/inspections"),
    }


@mcp.tool()
def get_quality_anomalies() -> dict:
    """Return reproducible equipment quality anomalies and their thresholds."""
    return _get("/quality/anomalies")


@mcp.tool()
def get_lot_trace(lot_id: int) -> dict:
    """Investigate a lot using process events and quality inspection history."""
    return lot_trace_resource(str(lot_id))


@mcp.tool()
def list_work_orders(limit: int = 20) -> list[dict]:
    """List recent work orders, capped to avoid flooding an agent context."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    return _get("/work-orders")[:limit]


@mcp.tool()
def get_equipment_status() -> list[dict]:
    """List all equipment with current RUN/IDLE/DOWN status, OEE inputs
    (Availability/Performance) and reliability (MTBF/MTTR, downtime by reason)."""
    return _get("/equipment")


@mcp.tool()
def get_equipment_downtime(equipment_id: int) -> list[dict]:
    """Downtime history (open and closed) for one equipment, most recent first."""
    return _get(f"/equipment/{int(equipment_id)}/downtime")


@mcp.tool()
def get_anomaly_log(limit: int = 20) -> list[dict]:
    """Persisted quality anomaly history (when an anomaly first showed up),
    unlike get_quality_anomalies which is a live snapshot recomputed on every call."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    return _get("/quality/anomaly-log")[:limit]


@mcp.tool()
def get_approval_queue(status: str | None = None) -> list[dict]:
    """List human-in-the-loop approval requests proposed by MES agents.
    Optionally filter by status: PENDING, APPROVED, REJECTED or EXPIRED."""
    if status:
        return _get(f"/approvals?status={quote(status)}")
    return _get("/approvals")


@mcp.tool()
def get_approval_summary() -> dict:
    """Counts of approval requests by status and risk level."""
    return _get("/approvals/summary")


@mcp.tool()
def get_control_tower_decisions() -> list[dict]:
    """Recent control tower BLOCK/AUTO_RECORD/QUEUE decisions, most recent first,
    including merged agent evidence for decisions that combined multiple proposals."""
    return _get("/control-tower/decisions")


@mcp.tool()
def get_audit_log(entity_type: str | None = None, entity_id: int | None = None) -> list[dict]:
    """Who/when/what/why for state changes: equipment status PATCH, work order
    release and approval decisions, most recent first. Optionally filter by
    entity_type ("equipment", "work_order" or "approval_request") and/or
    entity_id."""
    query = []
    if entity_type:
        query.append(f"entity_type={quote(entity_type)}")
    if entity_id is not None:
        query.append(f"entity_id={int(entity_id)}")
    path = "/audit-log" + (f"?{'&'.join(query)}" if query else "")
    return _get(path)


@mcp.tool()
def get_agent_card() -> dict:
    """AgentCard-shaped description of the quality investigation agent
    (name/skills/capabilities) -- see app/a2a.py for what this borrows from
    the publicly described A2A protocol and what it does not implement."""
    return _get("/a2a/agent-card")


@mcp.tool()
def get_investigation_tasks(equipment_id: int | None = None, limit: int = 20) -> list[dict]:
    """A2A-style investigation tasks the quality agent created for detected
    anomalies, most recent first. Each completed task carries an Artifact
    (structured evidence: defect rate vs peers, z-score, recent downtime)."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    query = [] if equipment_id is None else [f"equipment_id={int(equipment_id)}"]
    query.append(f"limit={limit}")
    return _get(f"/a2a/tasks?{'&'.join(query)}")


@mcp.tool()
def get_investigation_task(task_id: int) -> dict:
    """One investigation task by id, including its state and Artifact (or
    None if it is still working or failed)."""
    return _get(f"/a2a/tasks/{int(task_id)}")


if __name__ == "__main__":
    mcp.run()
