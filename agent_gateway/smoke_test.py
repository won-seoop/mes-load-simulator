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
        print(
            {
                "tools": sorted(tool_names),
                "resources": [str(resource.uri) for resource in resources.resources],
                "anomalies": anomalies,
            }
        )


if __name__ == "__main__":
    asyncio.run(main())
