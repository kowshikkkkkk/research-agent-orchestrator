# orchestrator/orchestrator.py

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / '.env')

import os
import httpx
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import RedisSaver
from langchain_groq import ChatGroq

# ── AGENT URLs ────────────────────────────────────────────────────────────────
# Defaults to localhost for local development.
# In Docker Compose, these are overridden via environment variables
# to use service names: http://web_research:8001 etc.

WEB_RESEARCH_URL = os.getenv("WEB_RESEARCH_URL", "http://localhost:8001")
RAG_KNOWLEDGE_URL = os.getenv("RAG_KNOWLEDGE_URL", "http://localhost:8002")
MARKET_DATA_URL = os.getenv("MARKET_DATA_URL", "http://localhost:8003")
REPORT_SYNTHESIS_URL = os.getenv("REPORT_SYNTHESIS_URL", "http://localhost:8004")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ── LLM ───────────────────────────────────────────────────────────────────────
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1
)

# ── STATE ─────────────────────────────────────────────────────────────────────
class ResearchState(TypedDict):
    query: str
    web_results: str
    rag_results: str
    market_data: str
    report: str
    critique: str
    quality_score: float
    retry_count: int
    final_output: str

# ── NODES ─────────────────────────────────────────────────────────────────────

def web_research_node(state: ResearchState) -> ResearchState:
    print(f"[Orchestrator] Calling Web Research Agent via A2A for: {state['query']}")
    try:
        task_payload = {
            "task_id": f"web-{state['query'][:20].replace(' ', '-')}",
            "input": {"query": state['query']},
            "context": {}
        }
        response = httpx.post(
            f"{WEB_RESEARCH_URL}/tasks/send",
            json=task_payload,
            timeout=30.0
        )
        result = response.json()
        if result["status"] == "completed":
            return {"web_results": result["output"]["synthesis"]}
        else:
            return {"web_results": f"Web research failed: {result['output'].get('error', 'Unknown')}"}
    except Exception as e:
        return {"web_results": f"Web Research Agent unreachable: {str(e)}"}

def rag_knowledge_node(state: ResearchState) -> ResearchState:
    print(f"[Orchestrator] Calling RAG Knowledge Agent via A2A")
    try:
        task_payload = {
            "task_id": f"rag-{state['query'][:20].replace(' ', '-')}",
            "input": {"query": state['query']},
            "context": {}
        }
        response = httpx.post(
            f"{RAG_KNOWLEDGE_URL}/tasks/send",
            json=task_payload,
            timeout=30.0
        )
        result = response.json()
        if result["status"] == "completed":
            return {"rag_results": result["output"]["synthesis"]}
        else:
            return {"rag_results": f"RAG search failed: {result['output'].get('error', 'Unknown')}"}
    except Exception as e:
        return {"rag_results": f"RAG Knowledge Agent unreachable: {str(e)}"}

def market_data_node(state: ResearchState) -> ResearchState:
    print(f"[Orchestrator] Calling Market Data Agent via A2A")
    try:
        task_payload = {
            "task_id": f"market-{state['query'][:20].replace(' ', '-')}",
            "input": {"query": state['query']},
            "context": {}
        }
        response = httpx.post(
            f"{MARKET_DATA_URL}/tasks/send",
            json=task_payload,
            timeout=30.0
        )
        result = response.json()
        if result["status"] == "completed":
            return {"market_data": result["output"]["market_data"]}
        else:
            return {"market_data": f"Market data failed: {result['output'].get('error', 'Unknown')}"}
    except Exception as e:
        return {"market_data": f"Market Data Agent unreachable: {str(e)}"}

def report_synthesis_node(state: ResearchState) -> ResearchState:
    print(f"[Orchestrator] Calling Report Synthesis Agent via A2A")
    try:
        task_payload = {
            "task_id": f"synthesis-{state['query'][:20].replace(' ', '-')}",
            "input": {
                "query": state['query'],
                "web_results": state['web_results'],
                "rag_results": state['rag_results'],
                "market_data": state['market_data'],
                "critique": state.get('critique', ''),
                "retry_count": state.get('retry_count', 0)
            },
            "context": {}
        }
        response = httpx.post(
            f"{REPORT_SYNTHESIS_URL}/tasks/send",
            json=task_payload,
            timeout=60.0
        )
        result = response.json()
        if result["status"] == "completed":
            return {"report": result["output"]["report"]}
        else:
            return {"report": f"Synthesis failed: {result['output'].get('error', 'Unknown')}"}
    except Exception as e:
        return {"report": f"Report Synthesis Agent unreachable: {str(e)}"}

def critic_node(state: ResearchState) -> ResearchState:
    print(f"[Orchestrator] Critic Agent evaluating report quality")

    prompt = f"""You are a quality evaluator for business research reports.

Evaluate this report on:
1. Does it directly answer the query with specific details?
2. Does it include named companies, statistics, and data points?
3. Is it well structured with clear sections?
4. Is it free of vague or generic statements?

Query: {state['query']}
Report: {state['report']}

Respond in this exact format:
SCORE: [a number between 0.0 and 1.0]
FEEDBACK: [one paragraph explaining the score and what specifically needs improvement]"""

    response = llm.invoke(prompt)
    content = response.content

    try:
        score_line = [l for l in content.split('\n') if l.startswith('SCORE:')][0]
        score = float(score_line.replace('SCORE:', '').strip())
    except:
        score = 0.5

    return {
        "critique": content,
        "quality_score": score,
        "retry_count": state.get('retry_count', 0)
    }

def should_retry(state: ResearchState) -> str:
    score = state.get('quality_score', 0)
    retry_count = state.get('retry_count', 0)
    max_retries = 2
    threshold = 0.7

    if score < threshold and retry_count < max_retries:
        print(f"[Orchestrator] Quality score {score} below threshold. Retry {retry_count + 1}/{max_retries}")
        return "retry"
    else:
        print(f"[Orchestrator] Quality score {score} accepted. Sending to user.")
        return "accept"

def increment_retry(state: ResearchState) -> ResearchState:
    return {"retry_count": state.get('retry_count', 0) + 1}

def final_output_node(state: ResearchState) -> ResearchState:
    return {"final_output": state['report']}

# ── GRAPH ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(ResearchState)

    graph.add_node("web_research", web_research_node)
    graph.add_node("rag_knowledge", rag_knowledge_node)
    graph.add_node("market_data", market_data_node)
    graph.add_node("report_synthesis", report_synthesis_node)
    graph.add_node("critic", critic_node)
    graph.add_node("increment_retry", increment_retry)
    graph.add_node("final_output", final_output_node)

    graph.set_entry_point("web_research")
    graph.add_edge("web_research", "rag_knowledge")
    graph.add_edge("rag_knowledge", "market_data")
    graph.add_edge("market_data", "report_synthesis")
    graph.add_edge("report_synthesis", "critic")

    graph.add_conditional_edges(
        "critic",
        should_retry,
        {
            "retry": "increment_retry",
            "accept": "final_output"
        }
    )
    graph.add_edge("increment_retry", "report_synthesis")
    graph.add_edge("final_output", END)

    return graph

# ── RUN WITH REDIS MEMORY ─────────────────────────────────────────────────────

if __name__ == "__main__":
    with RedisSaver.from_conn_string(REDIS_URL) as checkpointer:
        checkpointer.setup()
        graph = build_graph().compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "research-session-001"}}

        print("\n" + "="*60)
        print("QUERY 1: Initial research")
        print("="*60)

        result1 = graph.invoke({
            "query": "What is the competitive landscape for fintech lending in Southeast Asia?",
            "web_results": "",
            "rag_results": "",
            "market_data": "",
            "report": "",
            "critique": "",
            "quality_score": 0.0,
            "retry_count": 0,
            "final_output": ""
        }, config)

        print("\nFINAL REPORT:")
        print(result1['final_output'])
        print(f"\nQuality Score: {result1['quality_score']}")
        print(f"Retries: {result1['retry_count']}")