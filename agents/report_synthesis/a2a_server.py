# agents/report_synthesis/a2a_server.py

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any
import uuid
import time
from agents.report_synthesis.agent import run_report_synthesis
from guardrails.guardrails import guard_a2a_task

app = FastAPI(title="Report Synthesis Agent")

AGENT_CARD = {
    "name": "Report Synthesis Agent",
    "version": "1.0.0",
    "description": "Synthesizes research inputs into structured business intelligence reports",
    "capabilities": ["report_generation", "research_synthesis", "structured_output"],
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "web_results": {"type": "string"},
            "rag_results": {"type": "string"},
            "market_data": {"type": "string"},
            "critique": {"type": "string"},
            "retry_count": {"type": "integer"}
        },
        "required": ["query", "web_results", "rag_results", "market_data"]
    },
    "endpoint": "http://localhost:8004/tasks/send",
    "health_check": "http://localhost:8004/health"
}

class A2ATask(BaseModel):
    task_id: str = ""
    input: dict[str, Any]
    context: dict[str, Any] = {}

class A2ATaskResult(BaseModel):
    task_id: str
    status: str
    output: dict[str, Any]
    agent_name: str
    execution_time_ms: float

@app.get("/.well-known/agent.json")
def get_agent_card():
    return AGENT_CARD

@app.get("/health")
def health_check():
    return {"status": "healthy", "agent": "report_synthesis"}

@app.post("/tasks/send", response_model=A2ATaskResult)
def handle_task(task: A2ATask) -> A2ATaskResult:
    task_id = task.task_id or str(uuid.uuid4())
    start_time = time.time()

    guard_result = guard_a2a_task(task.input, source="report_synthesis_agent")
    if not guard_result["safe"]:
        return A2ATaskResult(
            task_id=task_id,
            status="blocked",
            output={
                "error": "Content blocked by guardrails",
                "violations": guard_result["violations"]
            },
            agent_name="report_synthesis",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )

    sanitized_input = guard_result["sanitized_input"]

    try:
        result = run_report_synthesis(
            query=sanitized_input.get("query", ""),
            web_results=sanitized_input.get("web_results", ""),
            rag_results=sanitized_input.get("rag_results", ""),
            market_data=sanitized_input.get("market_data", ""),
            critique=sanitized_input.get("critique", ""),
            retry_count=sanitized_input.get("retry_count", 0)
        )

        return A2ATaskResult(
            task_id=task_id,
            status="completed",
            output=result,
            agent_name="report_synthesis",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )

    except Exception as e:
        return A2ATaskResult(
            task_id=task_id,
            status="failed",
            output={"error": str(e)},
            agent_name="report_synthesis",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
