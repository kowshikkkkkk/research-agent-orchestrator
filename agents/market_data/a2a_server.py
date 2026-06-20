# agents/market_data/a2a_server.py

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any
import uuid
import time
from agents.market_data.agent import run_market_data_research

app = FastAPI(title="Market Data Agent")

AGENT_CARD = {
    "name": "Market Data Agent",
    "version": "1.0.0",
    "description": "Fetches quantitative market data — sizes, growth rates, funding amounts, statistics",
    "capabilities": ["market_size", "growth_rates", "funding_data", "statistics"],
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"}
        },
        "required": ["query"]
    },
    "endpoint": "http://localhost:8003/tasks/send",
    "health_check": "http://localhost:8003/health"
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
    return {"status": "healthy", "agent": "market_data"}

@app.post("/tasks/send", response_model=A2ATaskResult)
def handle_task(task: A2ATask) -> A2ATaskResult:
    task_id = task.task_id or str(uuid.uuid4())
    start_time = time.time()

    try:
        query = task.input.get("query", "")
        if not query:
            return A2ATaskResult(
                task_id=task_id,
                status="failed",
                output={"error": "No query provided"},
                agent_name="market_data",
                execution_time_ms=0
            )

        result = run_market_data_research(query)

        return A2ATaskResult(
            task_id=task_id,
            status="completed",
            output=result,
            agent_name="market_data",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )

    except Exception as e:
        return A2ATaskResult(
            task_id=task_id,
            status="failed",
            output={"error": str(e)},
            agent_name="market_data",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)