# agents/web_research/agent.py

import os
import json
from dotenv import load_dotenv
from pathlib import Path
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, ToolMessage
from mcp_servers.mcp_client import call_mcp_tool_sync, discover_mcp_tools_sync
from orchestrator.llm_utils import invoke_llm_with_retry

load_dotenv(Path(__file__).parent.parent.parent / '.env')

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

MCP_WEB_SEARCH_URL = os.getenv("MCP_WEB_SEARCH_URL", "http://localhost:8010")

# This agent discovers tools from the MCP server at call time (not
# hardcoded) and lets the LLM itself decide which one to use — this is
# what makes tool selection genuinely dynamic rather than deterministic.
# The server currently exposes three tools, backed by two different
# providers: 'web_search' and 'news_search' (both Tavily, live web),
# and 'wikipedia_background' (Wikipedia — genuinely different provider,
# for evergreen/background questions rather than live or recent content).
# If a fourth tool is added to the server later, this agent picks it up
# automatically — no code change needed here.

TOOL_SELECTION_GUIDANCE = (
    "You are a web research specialist with access to search tools. "
    "Use 'web_search' for general topic research or current information "
    "that needs a live web crawl. Use 'news_search' when the query is "
    "specifically about recent events, breaking news, or 'what happened' "
    "questions. Use 'wikipedia_background' for evergreen, encyclopedic, "
    "or definitional questions — how something works, established facts, "
    "history — where a live crawl isn't needed. Call exactly one tool "
    "with an appropriate search query derived from the research request "
    "below."
)

SYNTHESIS_INSTRUCTION = (
    "Based on the tool results above, provide a structured research summary:\n"
    "1. Key findings from the web (bullet points)\n"
    "2. Recent developments or news\n"
    "3. Notable companies or players mentioned\n"
    "4. Data points or statistics found\n\n"
    "Be specific and cite which source each finding comes from."
)


def run_web_research(query: str) -> dict:
    print(f"[Web Research Agent] Researching: {query}")

    available_tools = discover_mcp_tools_sync(MCP_WEB_SEARCH_URL)
    llm_with_tools = llm.bind_tools(available_tools)

    messages = [HumanMessage(content=f"{TOOL_SELECTION_GUIDANCE}\n\nResearch request: {query}")]
    ai_response = invoke_llm_with_retry(llm_with_tools, messages)
    messages.append(ai_response)

    if not ai_response.tool_calls:
        print("[Web Research Agent] Model chose not to call a tool.")
        return {
            "query": query,
            "synthesis": ai_response.content or "No research tool was invoked for this query.",
            "sources": [],
            "raw_results_count": 0,
            "tool_used": None,
        }

    sources = []
    result_count = 0
    tools_used = []

    for tool_call in ai_response.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tools_used.append({"tool": tool_name, "args": tool_args})
        print(f"[Web Research Agent] Model selected tool: {tool_name}({tool_args})")

        raw = call_mcp_tool_sync(MCP_WEB_SEARCH_URL, tool_name, tool_args)
        data = json.loads(raw)
        sources.extend(data.get("sources", []))
        result_count += data.get("result_count", 0)

        messages.append(ToolMessage(content=raw, tool_call_id=tool_call["id"]))

    messages.append(HumanMessage(content=SYNTHESIS_INSTRUCTION))
    final_response = invoke_llm_with_retry(llm, messages)  # plain llm here — no need to re-bind tools for synthesis

    return {
        "query": query,
        "synthesis": final_response.content,
        "sources": sources,
        "raw_results_count": result_count,
        "tool_used": tools_used,
    }