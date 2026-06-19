# orchestrator/orchestrator.py

from dotenv import load_dotenv
import os
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
import httpx

load_dotenv()

# ── 1. STATE ──────────────────────────────────────────────────────────────────
# This is the shared memory of the entire pipeline.
# Every agent reads from and writes to this state object.
# Think of it as the "briefcase" passed between agents.

class ResearchState(TypedDict):
    query: str                  # The original user question
    web_results: str            # Output from Web Research Agent
    rag_results: str            # Output from RAG Knowledge Agent
    market_data: str            # Output from Market Data Agent
    report: str                 # Output from Report Synthesis Agent
    critique: str               # Output from Critic Agent
    quality_score: float        # Score from Critic (0.0 to 1.0)
    retry_count: int            # How many times we've retried
    final_output: str           # What gets shown to the user

# ── 2. LLM ────────────────────────────────────────────────────────────────────
# We initialize Groq here once and reuse it across all nodes.
# llama-3.3-70b-versatile is Groq's best free model for reasoning tasks.

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1  # Low temperature = more consistent, less creative. Good for research.
)

# ── 3. NODES ──────────────────────────────────────────────────────────────────
# Each node is a function that takes state and returns updated state.
# Right now these are stubs — we'll replace them with real agents in later phases.

import httpx

def web_research_node(state: ResearchState) -> ResearchState:
    """
    Calls the Web Research Agent via A2A protocol.
    This is a real HTTP call to an independent service — not a function call.
    That's what makes it truly multi-agent.
    """
    print(f"[Orchestrator] Calling Web Research Agent via A2A for: {state['query']}")
    
    try:
        # A2A Task object — standardized structure
        task_payload = {
            "task_id": f"web-{state['query'][:20].replace(' ', '-')}",
            "input": {"query": state['query']},
            "context": {}
        }
        
        response = httpx.post(
            "http://localhost:8001/tasks/send",
            json=task_payload,
            timeout=30.0
        )
        
        result = response.json()
        
        if result["status"] == "completed":
            return {"web_results": result["output"]["synthesis"]}
        else:
            return {"web_results": f"Web research failed: {result['output'].get('error', 'Unknown error')}"}
            
    except Exception as e:
        return {"web_results": f"Web Research Agent unreachable: {str(e)}"}

def rag_knowledge_node(state: ResearchState) -> ResearchState:
    """
    Calls the RAG Knowledge Agent via A2A protocol.
    Returns knowledge base results to complement web research.
    """
    print(f"[Orchestrator] Calling RAG Knowledge Agent via A2A")
    
    try:
        task_payload = {
            "task_id": f"rag-{state['query'][:20].replace(' ', '-')}",
            "input": {"query": state['query']},
            "context": {}
        }
        
        response = httpx.post(
            "http://localhost:8002/tasks/send",
            json=task_payload,
            timeout=30.0
        )
        
        result = response.json()
        
        if result["status"] == "completed":
            return {"rag_results": result["output"]["synthesis"]}
        else:
            return {"rag_results": f"RAG search failed: {result['output'].get('error', 'Unknown error')}"}
            
    except Exception as e:
        return {"rag_results": f"RAG Knowledge Agent unreachable: {str(e)}"}

def market_data_node(state: ResearchState) -> ResearchState:
    """Calls the Market Data Agent. Returns structured market data."""
    print(f"[Orchestrator] Calling Market Data Agent")
    return {"market_data": "[MARKET STUB] Market data results"}

def report_synthesis_node(state: ResearchState) -> ResearchState:
    """Calls Report Synthesis Agent. Combines all results into a structured report."""
    print(f"[Orchestrator] Synthesizing report")
    
    prompt = f"""You are a business intelligence analyst.
    
Based on the following research, write a structured report answering the query.

Query: {state['query']}

Web Research: {state['web_results']}
Knowledge Base: {state['rag_results']}
Market Data: {state['market_data']}

Write a clear, structured report with sections: Executive Summary, Key Findings, Market Analysis, Conclusion.
"""
    response = llm.invoke(prompt)
    return {"report": response.content}

def critic_node(state: ResearchState) -> ResearchState:
    """Evaluates report quality. Assigns a score between 0.0 and 1.0."""
    print(f"[Orchestrator] Critic Agent evaluating report quality")
    
    prompt = f"""You are a quality evaluator for business research reports.

Evaluate this report on the following criteria:
1. Does it directly answer the query?
2. Is it specific and detailed?
3. Does it have clear structure?
4. Is it free of vague or generic statements?

Query: {state['query']}
Report: {state['report']}

Respond in this exact format:
SCORE: [a number between 0.0 and 1.0]
FEEDBACK: [one paragraph explaining the score]
"""
    response = llm.invoke(prompt)
    content = response.content
    
    # Parse score from response
    try:
        score_line = [l for l in content.split('\n') if l.startswith('SCORE:')][0]
        score = float(score_line.replace('SCORE:', '').strip())
    except:
        score = 0.5  # Default if parsing fails
    
    feedback = content
    current_retry = state.get('retry_count', 0)
    
    return {
        "critique": feedback,
        "quality_score": score,
        "retry_count": current_retry
    }

def should_retry(state: ResearchState) -> str:
    """
    This is the conditional edge — the brain of the retry loop.
    If quality is below threshold AND we haven't retried too many times,
    send back to report synthesis. Otherwise, pass to user.
    
    This is what separates a real production system from a simple chain.
    """
    score = state.get('quality_score', 0)
    retry_count = state.get('retry_count', 0)
    max_retries = 2
    threshold = 0.7  # 70% quality threshold
    
    if score < threshold and retry_count < max_retries:
        print(f"[Orchestrator] Quality score {score} below threshold. Retry {retry_count + 1}/{max_retries}")
        return "retry"
    else:
        print(f"[Orchestrator] Quality score {score} accepted. Sending to user.")
        return "accept"

def increment_retry(state: ResearchState) -> ResearchState:
    """Increments retry counter before sending back to synthesis."""
    return {"retry_count": state.get('retry_count', 0) + 1}

def final_output_node(state: ResearchState) -> ResearchState:
    """Packages the final report for the user."""
    return {"final_output": state['report']}

# ── 4. GRAPH ──────────────────────────────────────────────────────────────────
# This is where we wire everything together.
# Nodes = what to do. Edges = when to do it.

def build_graph():
    graph = StateGraph(ResearchState)
    
    # Add all nodes
    graph.add_node("web_research", web_research_node)
    graph.add_node("rag_knowledge", rag_knowledge_node)
    graph.add_node("market_data", market_data_node)
    graph.add_node("report_synthesis", report_synthesis_node)
    graph.add_node("critic", critic_node)
    graph.add_node("increment_retry", increment_retry)
    graph.add_node("final_output", final_output_node)
    
    # Define the flow
    graph.set_entry_point("web_research")
    graph.add_edge("web_research", "rag_knowledge")
    graph.add_edge("rag_knowledge", "market_data")
    graph.add_edge("market_data", "report_synthesis")
    graph.add_edge("report_synthesis", "critic")
    
    # Conditional edge — the retry loop
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
    
    return graph.compile()

# ── 5. RUN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    graph = build_graph()
    
    result = graph.invoke({
        "query": "What is the competitive landscape for fintech lending in Southeast Asia?",
        "web_results": "",
        "rag_results": "",
        "market_data": "",
        "report": "",
        "critique": "",
        "quality_score": 0.0,
        "retry_count": 0,
        "final_output": ""
    })
    
    print("\n" + "="*60)
    print("FINAL REPORT")
    print("="*60)
    print(result['final_output'])
    print(f"\nQuality Score: {result['quality_score']}")
    print(f"Retries: {result['retry_count']}")