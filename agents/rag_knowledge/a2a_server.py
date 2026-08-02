# agents/rag_knowledge/a2a_server.py

# agents/rag_knowledge/a2a_server.py

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any
import uuid
import time
from agents.rag_knowledge.agent import run_rag_research, ingest_document
from guardrails.guardrails import guard_a2a_task
from observability.a2a_instrumentation import A2AInstrumentation
from observability.metrics import metrics_response

app = FastAPI(title="RAG Knowledge Agent")
instrumentation = A2AInstrumentation("rag_knowledge")


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
            "agent_name": "rag_knowledge",
            "execution_time_ms": 0,
        },
    )

AGENT_CARD = {
    "name": "RAG Knowledge Agent",
    "version": "1.0.0",
    "description": "Searches a curated knowledge base using semantic similarity via Qdrant vector database",
    "capabilities": ["vector_search", "document_retrieval", "knowledge_base_query"],
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "ingest": {"type": "object", "description": "Optional — ingest a document instead of searching"}
        },
        "required": ["query"]
    },
    "endpoint": "http://localhost:8002/tasks/send",
    "health_check": "http://localhost:8002/health"
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
    return {"status": "healthy", "agent": "rag_knowledge"}

@app.get("/metrics")
def metrics():
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)

@app.post("/tasks/send", response_model=A2ATaskResult)
def handle_task(task: A2ATask, request: Request) -> A2ATaskResult:
    task_id = task.task_id or str(uuid.uuid4())
    start_time = time.time()

    with instrumentation.task_span(task_id, dict(request.headers)) as span_ctx:
        guard_result = guard_a2a_task(task.input, source="rag_knowledge_agent")
        if not guard_result["safe"]:
            instrumentation.log_guardrail_violation("blocked", guard_result["violations"])
            span_ctx.record_outcome("blocked")
            return A2ATaskResult(
                task_id=task_id,
                status="blocked",
                output={
                    "error": "Content blocked by guardrails",
                    "violations": guard_result["violations"]
                },
                agent_name="rag_knowledge",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

        sanitized_input = guard_result["sanitized_input"]

        if "ingest" in sanitized_input:
            ingest_data = sanitized_input["ingest"]
            result = ingest_document(
                text=ingest_data.get("text", ""),
                source=ingest_data.get("source", "unknown"),
                metadata=ingest_data.get("metadata", {})
            )
            status = "completed" if result.get("status") == "success" else "failed"
            span_ctx.record_outcome(status)
            return A2ATaskResult(
                task_id=task_id,
                status=status,
                output=result,
                agent_name="rag_knowledge",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

        query = sanitized_input.get("query", "")
        if not query:
            span_ctx.record_outcome("failed")
            return A2ATaskResult(
                task_id=task_id,
                status="failed",
                output={"error": "No query provided"},
                agent_name="rag_knowledge",
                execution_time_ms=0
            )

        result = run_rag_research(query)
        span_ctx.record_outcome("completed")

        return A2ATaskResult(
            task_id=task_id,
            status="completed",
            output=result,
            agent_name="rag_knowledge",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
