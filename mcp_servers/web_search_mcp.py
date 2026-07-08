# mcp_servers/web_search_mcp.py
#
# MCP server exposing web_search and news_search tools, backed by Tavily.
# Runs over SSE transport (not stdio) so it works identically on
# Windows, Linux, and inside Docker — stdio's ProactorEventLoop pipe
# issue on Windows does not apply to SSE, which is just HTTP.

import os
import sys
import re
import json
import requests
from dotenv import load_dotenv
from pathlib import Path
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp import types
from tavily import TavilyClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount
import uvicorn

load_dotenv(Path(__file__).parent.parent / '.env')

app = Server("web-search-mcp-server")
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

MCP_WEB_SEARCH_PORT = int(os.getenv("MCP_WEB_SEARCH_PORT", "8010"))

# Wikipedia's API is free, requires no key, and has no meaningful rate
# limit for this scale of use -- but it does require a descriptive
# User-Agent per Wikimedia's API etiquette, or requests can get throttled.
WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIPEDIA_HEADERS = {
    "User-Agent": "research-agent-orchestrator/1.0 (https://github.com/kowshikkkkkk/research-agent-orchestrator)"
}


def _wikipedia_search(query: str, max_results: int) -> dict:
    """
    Genuinely different provider from Tavily -- encyclopedic background
    content rather than live web crawl. Two-step lookup: search for
    matching page titles, then fetch a clean plain-text summary for each
    (the raw search snippet has HTML highlighting tags in it, so the
    summary endpoint gives cleaner content for the LLM to read).
    """
    search_resp = requests.get(
        WIKIPEDIA_SEARCH_URL,
        params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": max_results},
        headers=WIKIPEDIA_HEADERS,
        timeout=10
    )
    search_resp.raise_for_status()
    hits = search_resp.json().get("query", {}).get("search", [])

    formatted = []
    sources = []
    for i, hit in enumerate(hits, 1):
        title = hit.get("title", "")
        try:
            summary_resp = requests.get(
                WIKIPEDIA_SUMMARY_URL.format(title=requests.utils.quote(title)),
                headers=WIKIPEDIA_HEADERS,
                timeout=10
            )
            summary_resp.raise_for_status()
            summary_data = summary_resp.json()
            extract = summary_data.get("extract", "")
            url = summary_data.get("content_urls", {}).get("desktop", {}).get(
                "page", f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
            )
        except requests.RequestException:
            # Disambiguation pages and some redirects 404 on the summary
            # endpoint -- fall back to the raw search snippet with its
            # HTML highlighting tags stripped out.
            extract = re.sub("<[^<]+?>", "", hit.get("snippet", ""))
            url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"

        formatted.append(f"Result {i}:\nTitle: {title}\nURL: {url}\nContent: {extract}\n")
        sources.append(url)

    return {
        "results": "\n---\n".join(formatted),
        "sources": sources,
        "result_count": len(hits)
    }


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
        ),
        types.Tool(
            name="wikipedia_background",
            description=(
                "Look up encyclopedic background information on a topic -- how something "
                "works, definitions, history, established facts. Backed by Wikipedia, not "
                "live web search: use this for evergreen/background questions, not for "
                "current events, prices, or anything time-sensitive."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The topic or question to look up background on"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of Wikipedia articles to return (default: 3)",
                        "default": 3
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

    elif name == "wikipedia_background":
        query = arguments.get("query", "")
        max_results = arguments.get("max_results", 3)

        print(f"[Web MCP] wikipedia_background called for: {query}", file=sys.stderr)

        try:
            data = _wikipedia_search(query, max_results)
        except requests.RequestException as e:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Wikipedia lookup failed: {str(e)}"})
            )]

        return [types.TextContent(type="text", text=json.dumps(data))]

    else:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: {name}"})
        )]


# ── SSE TRANSPORT WIRING ──────────────────────────────────────────────────────
# SseServerTransport handles the two halves of MCP-over-HTTP:
#   GET  /sse       — long-lived event stream the client listens on
#   POST /messages/ — client sends JSON-RPC requests here, tagged with session_id
sse = SseServerTransport("/messages/")


async def handle_sse(request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())


async def health(request):
    return JSONResponse({"status": "healthy", "server": "web_search_mcp"})


starlette_app = Starlette(routes=[
    Route("/health", endpoint=health),
    Route("/sse", endpoint=handle_sse),
    Mount("/messages/", app=sse.handle_post_message),
])


if __name__ == "__main__":
    print(f"[Web MCP] Starting SSE server on port {MCP_WEB_SEARCH_PORT}", file=sys.stderr)
    print("[Web MCP] Tools registered: web_search, news_search, wikipedia_background", file=sys.stderr)
    uvicorn.run(starlette_app, host="0.0.0.0", port=MCP_WEB_SEARCH_PORT)