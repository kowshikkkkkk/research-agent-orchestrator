# orchestrator/orchestrator.py

import os
import uuid
import time
import httpx
from typing import TypedDict
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.redis import RedisSaver
from langchain_groq import ChatGroq

from observability.logging_config import get_logger, set_trace_id
from observability.tracing import init_tracing, inject_trace_headers, get_current_trace_id
from observability.metrics import (
    record_llm_usage,
    record_retry,
    record_quality_score,
    record_downstream_call,
)

logger = get_logger("orchestrator")
tracer = init_tracing("orchestrator")

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
    with tracer.start_as_current_span("orchestrator.web_research_node") as span:
        logger.info("calling web research agent", extra={"extra_fields": {"query": state["query"]}})
        task_id = f"web-{state['query'][:20].replace(' ', '-')}"
        start = time.time()
        try:
            task_payload = {"task_id": task_id, "input": {"query": state['query']}, "context": {}}
            headers = inject_trace_headers({})
            response = httpx.post(
                f"{WEB_RESEARCH_URL}/tasks/send",
                json=task_payload,
                headers=headers,
                timeout=30.0
            )
            elapsed = time.time() - start
            result = response.json()
            status = result.get("status", "unknown")
            record_downstream_call("web_research_agent", status, elapsed)
            span.set_attribute("a2a.status", status)

            if status == "completed":
                logger.info("web research completed", extra={"extra_fields": {"duration_ms": round(elapsed * 1000, 2)}})
                return {"web_results": result["output"]["synthesis"]}
            else:
                error = result.get('output', {}).get('error', 'Unknown')
                logger.warning("web research failed", extra={"extra_fields": {"error": error}})
                return {"web_results": f"Web research failed: {error}"}
        except Exception as e:
            elapsed = time.time() - start
            record_downstream_call("web_research_agent", "unreachable", elapsed)
            span.record_exception(e)
            logger.error(f"web research agent unreachable: {e}", exc_info=True)
            return {"web_results": f"Web Research Agent unreachable: {str(e)}"}

def rag_knowledge_node(state: ResearchState) -> ResearchState:
    with tracer.start_as_current_span("orchestrator.rag_knowledge_node") as span:
        logger.info("calling rag knowledge agent")
        task_id = f"rag-{state['query'][:20].replace(' ', '-')}"
        start = time.time()
        try:
            task_payload = {"task_id": task_id, "input": {"query": state['query']}, "context": {}}
            headers = inject_trace_headers({})
            response = httpx.post(
                f"{RAG_KNOWLEDGE_URL}/tasks/send",
                json=task_payload,
                headers=headers,
                timeout=30.0
            )
            elapsed = time.time() - start
            result = response.json()
            status = result.get("status", "unknown")
            record_downstream_call("rag_knowledge_agent", status, elapsed)
            span.set_attribute("a2a.status", status)

            if status == "completed":
                logger.info("rag knowledge completed", extra={"extra_fields": {"duration_ms": round(elapsed * 1000, 2)}})
                return {"rag_results": result["output"]["synthesis"]}
            else:
                error = result.get('output', {}).get('error', 'Unknown')
                logger.warning("rag search failed", extra={"extra_fields": {"error": error}})
                return {"rag_results": f"RAG search failed: {error}"}
        except Exception as e:
            elapsed = time.time() - start
            record_downstream_call("rag_knowledge_agent", "unreachable", elapsed)
            span.record_exception(e)
            logger.error(f"rag knowledge agent unreachable: {e}", exc_info=True)
            return {"rag_results": f"RAG Knowledge Agent unreachable: {str(e)}"}

def market_data_node(state: ResearchState) -> ResearchState:
    with tracer.start_as_current_span("orchestrator.market_data_node") as span:
        logger.info("calling market data agent")
        task_id = f"market-{state['query'][:20].replace(' ', '-')}"
        start = time.time()
        try:
            task_payload = {"task_id": task_id, "input": {"query": state['query']}, "context": {}}
            headers = inject_trace_headers({})
            response = httpx.post(
                f"{MARKET_DATA_URL}/tasks/send",
                json=task_payload,
                headers=headers,
                timeout=30.0
            )
            elapsed = time.time() - start
            result = response.json()
            status = result.get("status", "unknown")
            record_downstream_call("market_data_agent", status, elapsed)
            span.set_attribute("a2a.status", status)

            if status == "completed":
                logger.info("market data completed", extra={"extra_fields": {"duration_ms": round(elapsed * 1000, 2)}})
                return {"market_data": result["output"]["market_data"]}
            else:
                error = result.get('output', {}).get('error', 'Unknown')
                logger.warning("market data failed", extra={"extra_fields": {"error": error}})
                return {"market_data": f"Market data failed: {error}"}
        except Exception as e:
            elapsed = time.time() - start
            record_downstream_call("market_data_agent", "unreachable", elapsed)
            span.record_exception(e)
            logger.error(f"market data agent unreachable: {e}", exc_info=True)
            return {"market_data": f"Market Data Agent unreachable: {str(e)}"}

def report_synthesis_node(state: ResearchState) -> ResearchState:
    with tracer.start_as_current_span("orchestrator.report_synthesis_node") as span:
        retry_count = state.get('retry_count', 0)
        logger.info("calling report synthesis agent", extra={"extra_fields": {"attempt": retry_count + 1}})
        task_id = f"synthesis-{state['query'][:20].replace(' ', '-')}"
        start = time.time()
        try:
            task_payload = {
                "task_id": task_id,
                "input": {
                    "query": state['query'],
                    "web_results": state['web_results'],
                    "rag_results": state['rag_results'],
                    "market_data": state['market_data'],
                    "critique": state.get('critique', ''),
                    "retry_count": retry_count
                },
                "context": {}
            }
            headers = inject_trace_headers({})
            response = httpx.post(
                f"{REPORT_SYNTHESIS_URL}/tasks/send",
                json=task_payload,
                headers=headers,
                timeout=60.0
            )
            elapsed = time.time() - start
            result = response.json()
            status = result.get("status", "unknown")
            record_downstream_call("report_synthesis_agent", status, elapsed)
            span.set_attribute("a2a.status", status)

            if status == "completed":
                logger.info("report synthesis completed", extra={"extra_fields": {"duration_ms": round(elapsed * 1000, 2)}})
                return {"report": result["output"]["report"]}
            else:
                error = result.get('output', {}).get('error', 'Unknown')
                logger.warning("report synthesis failed", extra={"extra_fields": {"error": error}})
                return {"report": f"Synthesis failed: {error}"}
        except Exception as e:
            elapsed = time.time() - start
            record_downstream_call("report_synthesis_agent", "unreachable", elapsed)
            span.record_exception(e)
            logger.error(f"report synthesis agent unreachable: {e}", exc_info=True)
            return {"report": f"Report Synthesis Agent unreachable: {str(e)}"}

def critic_node(state: ResearchState) -> ResearchState:
    with tracer.start_as_current_span("orchestrator.critic_node") as span:
        logger.info("critic evaluating report quality")

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
        record_llm_usage("critic", response)
        content = response.content

        try:
            score_line = [l for l in content.split('\n') if l.startswith('SCORE:')][0]
            score = float(score_line.replace('SCORE:', '').strip())
        except:
            score = 0.5
            logger.warning("critic score parse failure, defaulting to 0.5", extra={"extra_fields": {"raw_content": content[:200]}})

        span.set_attribute("critic.quality_score", score)
        record_quality_score(score)
        logger.info("critic evaluation complete", extra={"extra_fields": {"quality_score": score}})

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
        logger.info(
            "quality below threshold, retrying",
            extra={"extra_fields": {"quality_score": score, "retry_attempt": retry_count + 1, "max_retries": max_retries}}
        )
        record_retry()
        return "retry"
    else:
        logger.info(
            "quality accepted, returning to user",
            extra={"extra_fields": {"quality_score": score, "retry_count": retry_count}}
        )
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

    graph.add_edge(START, "web_research")
    graph.add_edge(START, "rag_knowledge")
    graph.add_edge(START, "market_data")

    graph.add_edge("web_research", "report_synthesis")
    graph.add_edge("rag_knowledge", "report_synthesis")
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

        query_text = "What is the competitive landscape for fintech lending in Southeast Asia?"

        with tracer.start_as_current_span("orchestrator.run_query") as root_span:
            trace_id = get_current_trace_id()
            set_trace_id(trace_id)
            root_span.set_attribute("query", query_text)

            logger.info("query started", extra={"extra_fields": {"query": query_text, "trace_id": trace_id}})

            result1 = graph.invoke({
                "query": query_text,
                "web_results": "",
                "rag_results": "",
                "market_data": "",
                "report": "",
                "critique": "",
                "quality_score": 0.0,
                "retry_count": 0,
                "final_output": ""
            }, config)

            logger.info(
                "query finished",
                extra={"extra_fields": {
                    "quality_score": result1['quality_score'],
                    "retry_count": result1['retry_count'],
                }}
            )

        print("\nFINAL REPORT:")
        print(result1['final_output'])
        print(f"\nQuality Score: {result1['quality_score']}")
        print(f"Retries: {result1['retry_count']}")
        print(f"\nTrace ID (search this in Jaeger / grep logs for the full request path): {trace_id}")