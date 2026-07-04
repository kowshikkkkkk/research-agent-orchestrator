# mcp_servers/mcp_client.py
#
# Shared helper so every agent talks to MCP servers the same way.
# The agents themselves (agent.py files) are synchronous — they're called
# from FastAPI sync route handlers in a2a_server.py — but the MCP SDK's
# ClientSession and sse_client are async context managers. This module
# is the bridge: call_mcp_tool_sync() wraps the async call in asyncio.run()
# so agent.py code can stay plain, synchronous Python.

import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client


class MCPToolError(Exception):
    """Raised when the MCP server itself reports the tool call failed
    (isError=True) — e.g. the upstream API (Tavily/Qdrant) rejected the
    request. Kept distinct from transport-level failures (connection
    refused, timeout) so callers can tell 'server unreachable' apart
    from 'server reachable but the tool call failed'."""
    pass


async def _call_mcp_tool_async(server_url: str, tool_name: str, arguments: dict) -> str:
    """
    Opens a fresh SSE connection, initializes an MCP session, calls the
    named tool once, and returns its text content. One connection per
    call — simple and correct, though not the most efficient pattern
    for high call volume (a pooled/persistent session would be the
    next optimization if this became a bottleneck).
    """
    async with sse_client(url=f"{server_url}/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

            if result.isError:
                error_text = result.content[0].text if result.content else "Unknown MCP tool error"
                raise MCPToolError(f"MCP tool '{tool_name}' failed: {error_text or '(empty error message from upstream)'}")

            if not result.content:
                return "{}"
            return result.content[0].text
async def _discover_mcp_tools_async(server_url: str) -> list[dict]:
    """
    Calls the MCP server's list_tools() and converts each tool into the
    OpenAI function-calling format (name/description/parameters) that
    LangChain's bind_tools() accepts directly. This is what makes tool
    selection dynamic rather than hardcoded: if a new tool gets added to
    the MCP server, the agent picks it up automatically next call — no
    code change needed here.
    """
    async with sse_client(url=f"{server_url}/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            return [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema,
                    },
                }
                for t in tools_result.tools
            ]


def discover_mcp_tools_sync(server_url: str) -> list[dict]:
    """
    Synchronous entry point for tool discovery. Returns a list ready to
    pass straight into llm.bind_tools(...).
    """
    return asyncio.run(_discover_mcp_tools_async(server_url))


def call_mcp_tool_sync(server_url: str, tool_name: str, arguments: dict) -> str:
    """
    Synchronous entry point used by agent.py files.
    Returns the raw JSON string the MCP tool produced — callers are
    responsible for json.loads()-ing it, since each tool's schema differs.
    """
    return asyncio.run(_call_mcp_tool_async(server_url, tool_name, arguments))
