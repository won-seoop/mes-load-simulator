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


if __name__ == "__main__":
    mcp.run()
