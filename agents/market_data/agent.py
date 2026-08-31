# agents/market_data/agent.py

import os
import json
from dotenv import load_dotenv
from pathlib import Path
from langchain_groq import ChatGroq
from mcp_servers.mcp_client import call_mcp_tool_sync
from orchestrator.llm_utils import invoke_llm_with_retry

load_dotenv(Path(__file__).parent.parent.parent / '.env')

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

# Same MCP web search tool as the Web Research Agent — one server,
# two different consumers with two different prompt strategies.
# This is the reuse benefit of MCP: the tool doesn't know or care
# which agent is calling it or why.
MCP_WEB_SEARCH_URL = os.getenv("MCP_WEB_SEARCH_URL", "http://localhost:8010")

def run_market_data_research(query: str) -> dict:
    """
    Searches specifically for quantitative market data.
    Unlike the Web Research Agent which returns broad findings,
    this agent focuses on numbers — market size, growth rates,
    funding amounts, valuations, statistics.
    Structured numerical data is what makes reports credible.
    """
    print(f"[Market Data Agent] Fetching market data for: {query}")

    # We append "market size statistics data" to bias the search
    # toward quantitative sources like reports and filings
    market_query = f"{query} market size statistics growth rate funding data 2024"

    raw = call_mcp_tool_sync(
        MCP_WEB_SEARCH_URL,
        "web_search",
        {"query": market_query, "max_results": 5, "search_depth": "advanced"}
    )
    data = json.loads(raw)

    raw_content = data.get("results", "")
    sources = data.get("sources", [])
    result_count = data.get("result_count", 0)

    prompt = f"""You are a market data specialist. Extract only quantitative data from the search results.

Original Query: {query}

Search Results:
{raw_content}

Extract and structure the following if available:
1. Market size figures (with currency and year)
2. Growth rates (CAGR, YoY percentages)
3. Funding amounts raised by companies
4. User/customer counts
5. Transaction volumes
6. Any other specific numerical data points

Format as clean bullet points with source citations.
If no quantitative data is found for a category, skip it.
Do not include vague statements — numbers only."""

    response = invoke_llm_with_retry(llm, prompt)

    return {
        "query": query,
        "market_data": response.content,
        "sources": sources,
        "data_points_found": result_count
    }
