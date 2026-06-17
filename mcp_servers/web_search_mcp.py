# mcp_servers/web_search_mcp.py

import os
import json
import asyncio
from dotenv import load_dotenv
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from tavily import TavilyClient

load_dotenv(Path(__file__).parent.parent / '.env')

# ── MCP SERVER SETUP ──────────────────────────────────────────────────────────
# This is the MCP Server — it registers tools that agents can call by name.
# Think of it like an API registry. The agent doesn't know or care that
# Tavily is the implementation. It just calls "web_search" by name.
# If we swap Tavily for another provider tomorrow, this file changes
# but the agent code stays exactly the same.

app = Server("web-search-mcp-server")
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# ── TOOL REGISTRATION ─────────────────────────────────────────────────────────
# This is how MCP works — you register tools with a name, description,
# and input schema. The agent discovers these at runtime via list_tools().
# This is the MCP equivalent of an API spec.

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """
    Advertises available tools to any MCP client that connects.
    The Web Research Agent calls this at startup to discover what tools exist.
    """
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

# ── TOOL EXECUTION ────────────────────────────────────────────────────────────
# When the agent calls a tool by name, this function handles it.
# Notice the agent never imports Tavily — it just calls "web_search".
# This is the abstraction MCP provides.

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """
    Executes the requested tool and returns results.
    The MCP client (Web Research Agent) calls tools by name through here.
    """
    
    if name == "web_search":
        query = arguments.get("query", "")
        max_results = arguments.get("max_results", 5)
        search_depth = arguments.get("search_depth", "advanced")
        
        print(f"[MCP Server] web_search called for: {query}")
        
        response = tavily.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth
        )
        
        results = response.get("results", [])
        
        # Format results as structured text
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
        
        print(f"[MCP Server] news_search called for: {query}")
        
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

# ── RUN SERVER ────────────────────────────────────────────────────────────────
# MCP servers communicate over stdio by default — standard input/output.
# This is different from HTTP — the agent spawns this as a subprocess
# and communicates through stdin/stdout pipes.
# In production you'd use a network transport instead.

async def main():
    print("[MCP Server] Web Search MCP Server starting...")
    print("[MCP Server] Tools registered: web_search, news_search")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())