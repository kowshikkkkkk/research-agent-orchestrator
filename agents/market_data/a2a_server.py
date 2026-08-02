# agents/market_data/a2a_server.py

# agents/market_data/a2a_server.py

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any
import uuid
import time
from agents.market_data.agent import run_market_data_research
from guardrails.guardrails import guard_a2a_task
from observability.a2a_instrumentation import A2AInstrumentation
from observability.metrics import metrics_response

app = FastAPI(title="Market Data Agent")
instrumentation = A2AInstrumentation("market_data")


@app.exception_handler(Exception)
async def handle_uncaught_exception(request: Request, exc: Exception):
    task_id = "unknown"
    try:
        body = await request.json()
        task_id = body.get("task_id", "unknown")
    except Exception:
        pass

    return JSONResponse(
        status_code=200,
        content={
            "task_id": task_id,
            "status": "failed",
            "output": {"error": str(exc)},
            "agent_name": "market_data",
            "execution_time_ms": 0,
        },
    )

AGENT_CARD = {
    "name": "Market Data Agent",
    "version": "1.0.0",
    "description": "Fetches quantitative market data",
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

@app.get("/metrics")
def metrics():
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)

@app.post("/tasks/send", response_model=A2ATaskResult)
def handle_task(task: A2ATask, request: Request) -> A2ATaskResult:
    task_id = task.task_id or str(uuid.uuid4())
    start_time = time.time()

    with instrumentation.task_span(task_id, dict(request.headers)) as span_ctx:
        guard_result = guard_a2a_task(task.input, source="market_data_agent")
        if not guard_result["safe"]:
            instrumentation.log_guardrail_violation("blocked", guard_result["violations"])
            span_ctx.record_outcome("blocked")
            return A2ATaskResult(
                task_id=task_id,
                status="blocked",
                output={"error": "Content blocked by guardrails", "violations": guard_result["violations"]},
                agent_name="market_data",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

        sanitized_input = guard_result["sanitized_input"]

        query = sanitized_input.get("query", "")
        if not query:
            span_ctx.record_outcome("failed")
            return A2ATaskResult(
                task_id=task_id,
                status="failed",
                output={"error": "No query provided"},
                agent_name="market_data",
                execution_time_ms=0
            )

        result = run_market_data_research(query)
        span_ctx.record_outcome("completed")

        return A2ATaskResult(
            task_id=task_id,
            status="completed",
            output=result,
            agent_name="market_data",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)