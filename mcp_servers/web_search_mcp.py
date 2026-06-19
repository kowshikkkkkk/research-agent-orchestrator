# mcp_servers/web_search_mcp.py

import os
import sys
import json
import asyncio
from dotenv import load_dotenv
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from tavily import TavilyClient

load_dotenv(Path(__file__).parent.parent / '.env')

app = Server("web-search-mcp-server")
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="web_search",
            description="Search the web for real-time information on any topic. Returns synthesized results with sources.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5)",
                        "default": 5
                    },
                    "search_depth": {
                        "type": "string",
                        "description": "Search depth: 'basic' or 'advanced'",
                        "default": "advanced"
                    }
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="news_search",
            description="Search for recent news articles on a topic. Returns latest news with sources.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The news search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    if name == "web_search":
        query = arguments.get("query", "")
        max_results = arguments.get("max_results", 5)
        search_depth = arguments.get("search_depth", "advanced")

        print(f"[Web MCP] web_search called for: {query}", file=sys.stderr)

        response = tavily.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth
        )

        results = response.get("results", [])

        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append(
                f"Result {i}:\n"
                f"URL: {r.get('url', '')}\n"
                f"Content: {r.get('content', '')}\n"
            )

        output = "\n---\n".join(formatted)
        sources = [r.get("url", "") for r in results]

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "results": output,
                "sources": sources,
                "result_count": len(results)
            })
        )]

    elif name == "news_search":
        query = arguments.get("query", "")
        max_results = arguments.get("max_results", 5)

        print(f"[Web MCP] news_search called for: {query}", file=sys.stderr)

        response = tavily.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            topic="news"
        )

        results = response.get("results", [])

        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append(
                f"News {i}:\n"
                f"URL: {r.get('url', '')}\n"
                f"Content: {r.get('content', '')}\n"
            )

        output = "\n---\n".join(formatted)
        sources = [r.get("url", "") for r in results]

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "results": output,
                "sources": sources,
                "result_count": len(results)
            })
        )]

    else:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: {name}"})
        )]

async def main():
    print("[Web MCP] Web Search MCP Server starting...", file=sys.stderr)
    print("[Web MCP] Tools registered: web_search, news_search", file=sys.stderr)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())