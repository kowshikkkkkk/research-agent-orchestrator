# agents/rag_knowledge/a2a_server.py

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any
import uuid
import time
from agents.rag_knowledge.agent import run_rag_research, ingest_document
from guardrails.guardrails import guard_a2a_task

app = FastAPI(title="RAG Knowledge Agent")

AGENT_CARD = {
    "name": "RAG Knowledge Agent",
    "version": "1.0.0",
    "description": "Searches a curated knowledge base using semantic similarity via Qdrant vector database",
    "capabilities": ["vector_search", "document_retrieval", "knowledge_base_query"],
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "ingest": {"type": "object"}
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

@app.post("/tasks/send", response_model=A2ATaskResult)
def handle_task(task: A2ATask) -> A2ATaskResult:
    task_id = task.task_id or str(uuid.uuid4())
    start_time = time.time()

    guard_result = guard_a2a_task(task.input, source="rag_knowledge_agent")
    if not guard_result["safe"]:
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

    try:
        if "ingest" in sanitized_input:
            ingest_data = sanitized_input["ingest"]
            result = ingest_document(
                text=ingest_data.get("text", ""),
                source=ingest_data.get("source", "unknown"),
                metadata=ingest_data.get("metadata", {})
            )
            return A2ATaskResult(
                task_id=task_id,
                status="completed",
                output=result,
                agent_name="rag_knowledge",
                execution_time_ms=round((time.time() - start_time) * 1000, 2)
            )

        query = sanitized_input.get("query", "")
        if not query:
            return A2ATaskResult(
                task_id=task_id,
                status="failed",
                output={"error": "No query provided"},
                agent_name="rag_knowledge",
                execution_time_ms=0
            )

        result = run_rag_research(query)

        return A2ATaskResult(
            task_id=task_id,
            status="completed",
            output=result,
            agent_name="rag_knowledge",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )

    except Exception as e:
        return A2ATaskResult(
            task_id=task_id,
            status="failed",
            output={"error": str(e)},
            agent_name="rag_knowledge",
            execution_time_ms=round((time.time() - start_time) * 1000, 2)
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
