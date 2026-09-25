"""In-memory MCP protocol smoke test against a running MES API."""

import asyncio
import json

from mcp import Client

from agent_gateway.server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        assert tool_names == {
            "get_quality_anomalies",
            "get_lot_trace",
            "list_work_orders",
            "get_equipment_status",
            "get_equipment_downtime",
            "get_anomaly_log",
            "get_approval_queue",
            "get_approval_summary",
            "get_control_tower_decisions",
        }

        resources = await client.list_resources()
        assert {str(resource.uri) for resource in resources.resources} == {"mes://overview"}

        result = await client.call_tool("get_quality_anomalies", {})
        assert not result.is_error
        if result.structured_content is not None:
            payload = result.structured_content.get("result", result.structured_content)
        else:
            payload = json.loads(result.content[0].text)
        anomalies = payload["anomalies"]

        equipment_result = await client.call_tool("get_equipment_status", {})
        assert not equipment_result.is_error
        if equipment_result.structured_content is not None:
            equipment_payload = equipment_result.structured_content.get(
                "result", equipment_result.structured_content
            )
        else:
            equipment_payload = json.loads(equipment_result.content[0].text)
        assert isinstance(equipment_payload, list) and len(equipment_payload) > 0

        summary_result = await client.call_tool("get_approval_summary", {})
        assert not summary_result.is_error

        decisions_result = await client.call_tool("get_control_tower_decisions", {})
        assert not decisions_result.is_error

        print(
            {
                "tools": sorted(tool_names),
                "resources": [str(resource.uri) for resource in resources.resources],
                "anomalies": anomalies,
                "equipment_count": len(equipment_payload),
            }
        )


if __name__ == "__main__":
    asyncio.run(main())
