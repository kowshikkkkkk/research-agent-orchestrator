# agents/web_research/agent.py

import os
import json
import asyncio
from dotenv import load_dotenv
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_groq import ChatGroq

load_dotenv(Path(__file__).parent.parent.parent / '.env')

# ── LLM ───────────────────────────────────────────────────────────────────────
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

# ── MCP CLIENT ────────────────────────────────────────────────────────────────
# This is where the agent becomes an MCP Client.
# Instead of importing Tavily directly, it connects to the MCP Server
# and calls tools by name. The agent has no idea Tavily exists.
# This is the abstraction that makes tools swappable.

async def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """
    Connects to the MCP server as a client and calls a tool by name.
    The server is spawned as a subprocess communicating via stdio.
    """
    
    # Path to the MCP server
    server_path = Path(__file__).parent.parent.parent / "mcp_servers" / "web_search_mcp.py"
    
    server_params = StdioServerParameters(
        command="python",
        args=[str(server_path)],
        env={
            "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", ""),
            "PATH": os.environ.get("PATH", "")
        }
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()
            
            # List available tools (discovery)
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"[MCP Client] Available tools: {tool_names}")
            
            # Call the requested tool
            result = await session.call_tool(tool_name, arguments)
            
            # Parse result
            if result.content:
                raw = result.content[0].text
                return json.loads(raw)
            return {"results": "", "sources": [], "result_count": 0}

def run_web_research(query: str) -> dict:
    """
    Runs web research using MCP tool layer.
    The agent calls tools by name — not by importing libraries directly.
    """
    print(f"[Web Research Agent] Starting MCP-based research for: {query}")
    
    # Run the async MCP call in sync context
    raw_data = asyncio.run(call_mcp_tool("web_search", {
        "query": query,
        "max_results": 5,
        "search_depth": "advanced"
    }))
    
    results_text = raw_data.get("results", "")
    sources = raw_data.get("sources", [])
    
    if not results_text:
        return {
            "query": query,
            "synthesis": "No results found.",
            "sources": [],
            "raw_results_count": 0
        }
    
    # Synthesize with LLM
    prompt = f"""You are a web research specialist for business intelligence.

Based on the following web search results, provide a structured research summary.

Original Query: {query}

Search Results:
{results_text}

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
        "raw_results_count": raw_data.get("result_count", 0)
    }