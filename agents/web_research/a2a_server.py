# agents/web_research/a2a_server.py

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any
import uuid
import time
from agents.web_research.agent import run_web_research

app = FastAPI(title="Web Research Agent")

# ── A2A AGENTCARD ─────────────────────────────────────────────────────────────
# This is the A2A protocol's discovery mechanism.
# The Orchestrator calls this endpoint first to understand what this agent can do.
# In production, every agent must have this — it's how agents find each other
# without hardcoded dependencies.

AGENT_CARD = {
    "name": "Web Research Agent",
    "version": "1.0.0",
    "description": "Searches the web for real-time business intelligence and research data",
    "capabilities": ["web_search", "news_search", "market_research"],
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The research query to search for"}
        },
        "required": ["query"]
    },
    "output_schema": {
        "type": "object", 
        "properties": {
            "synthesis": {"type": "string"},
            "sources": {"type": "array"},
            "raw_results_count": {"type": "integer"}
        }
    },
    "endpoint": "http://localhost:8001/tasks/send",
    "health_check": "http://localhost:8001/health"
}

# ── A2A TASK MODEL ────────────────────────────────────────────────────────────
# Every A2A message follows this structure — standardized input/output.
# The Orchestrator sends a Task, gets back a TaskResult.
# This is the contract between agents.

class A2ATask(BaseModel):
    task_id: str = ""
    input: dict[str, Any]
    context: dict[str, Any] = {}  # Optional — for passing session data

class A2ATaskResult(BaseModel):
    task_id: str
    status: str          # "completed" | "failed"
    output: dict[str, Any]
    agent_name: str
    execution_time_ms: float

# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@app.get("/.well-known/agent.json")
def get_agent_card():
    """A2A discovery endpoint. Orchestrator calls this at startup."""
    return AGENT_CARD

@app.get("/health")
def health_check():
    return {"status": "healthy", "agent": "web_research"}

@app.post("/tasks/send", response_model=A2ATaskResult)
def handle_task(task: A2ATask) -> A2ATaskResult:
    """
    Main A2A task endpoint.
    Orchestrator sends a task here, we run the research, return structured result.
    """
    task_id = task.task_id or str(uuid.uuid4())
    start_time = time.time()
    
    try:
        query = task.input.get("query", "")
        if not query:
            return A2ATaskResult(
                task_id=task_id,
                status="failed",
                output={"error": "No query provided"},
                agent_name="web_research",
                execution_time_ms=0
            )
        
        # Run the actual research
        result = run_web_research(query)
        
        execution_time = (time.time() - start_time) * 1000
        
        return A2ATaskResult(
            task_id=task_id,
            status="completed",
            output=result,
            agent_name="web_research",
            execution_time_ms=round(execution_time, 2)
        )
        
    except Exception as e:
        return A2ATaskResult(
            task_id=task_id,
            status="failed",
            output={"error": str(e)},
            agent_name="web_research",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)