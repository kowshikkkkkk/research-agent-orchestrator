# agents/web_research/agent.py

import os
import json
from dotenv import load_dotenv
from pathlib import Path
from langchain_groq import ChatGroq
from mcp_servers.mcp_client import call_mcp_tool_sync

load_dotenv(Path(__file__).parent.parent.parent / '.env')

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

# This agent no longer imports TavilyClient directly. It calls the
# web_search tool on the Web Search MCP server over SSE — the MCP
# server owns the Tavily client and credentials, this agent just
# consumes the tool through the standard MCP interface.
MCP_WEB_SEARCH_URL = os.getenv("MCP_WEB_SEARCH_URL", "http://localhost:8010")

def run_web_research(query: str) -> dict:
    print(f"[Web Research Agent] Searching for: {query}")

    raw = call_mcp_tool_sync(
        MCP_WEB_SEARCH_URL,
        "web_search",
        {"query": query, "max_results": 5, "search_depth": "advanced"}
    )
    data = json.loads(raw)

    raw_content = data.get("results", "")
    sources = data.get("sources", [])
    result_count = data.get("result_count", 0)

    prompt = f"""You are a web research specialist for business intelligence.

Based on the following web search results, provide a structured research summary.

Original Query: {query}

Search Results:
{raw_content}

Provide:
1. Key findings from the web (bullet points)
2. Recent developments or news
3. Notable companies or players mentioned
4. Data points or statistics found

Be specific and cite which source each finding comes from."""

    response = llm.invoke(prompt)

    return {
        "query": query,
        "synthesis": response.content,
        "sources": sources,
        "raw_results_count": result_count
    }
