from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from auth.security import hash_password, verify_password, create_access_token, decode_access_token
from db.session import get_db
from db.models import User, QueryLog
from auth.dependencies import get_current_user
import uuid as uuid_lib
from langgraph.checkpoint.redis import RedisSaver
from orchestrator.orchestrator import build_graph
import os
from fastapi import Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from cache.cache import get_cached_result, set_cached_result
from memory.agent_memory import retrieve_relevant_memories, store_memory

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

app = FastAPI(title="Research Orchestrator API")

def rate_limit_key(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_access_token(token)
            return f"user:{payload.get('sub')}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"

limiter = Limiter(key_func=rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/health")
def health_check():
    return {"status": "healthy"}

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = User(email=body.email.lower(), hashed_password=hash_password(body.password))
    db.add(user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    db.refresh(user)
    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@app.post("/auth/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token)


@app.get("/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email}


class ResearchRequest(BaseModel):
    query: str
    thread_id: str | None = None


class ResearchResponse(BaseModel):
    query_id: str
    thread_id: str
    final_output: str
    quality_score: float
    retry_count: int


@app.post("/research", response_model=ResearchResponse)
@limiter.limit("5/minute")
def run_research(
    request: Request,
    body: ResearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    thread_id = body.thread_id or f"{current_user.id}-{uuid_lib.uuid4().hex[:8]}"

    query_log = QueryLog(
        user_id=current_user.id,
        thread_id=thread_id,
        query=body.query,
        status="pending",
    )
    db.add(query_log)
    db.commit()
    db.refresh(query_log)

    cached = get_cached_result(body.query)
    if cached is not None:
        query_log.status = "completed"
        query_log.final_report = cached["final_output"]
        query_log.quality_score = cached["quality_score"]
        query_log.retry_count = cached["retry_count"]
        db.commit()

        return {
            "query_id": query_log.id,
            "thread_id": thread_id,
            "final_output": cached["final_output"],
            "quality_score": cached["quality_score"],
            "retry_count": cached["retry_count"],
        }

    try:
        with RedisSaver.from_conn_string(REDIS_URL) as checkpointer:
            checkpointer.setup()
            graph = build_graph().compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": thread_id}}

            memories = retrieve_relevant_memories(current_user.id, body.query)
            if memories:
                past_context = "\n\n".join(
                    f"Past query: {m['query']}\nSummary: {m['report'][:300]}"
                    for m in memories
                )
            else:
                past_context = ""

            result = graph.invoke(
                {
                    "query": body.query,
                    "web_results": "",
                    "rag_results": "",
                    "market_data": "",
                    "report": "",
                    "critique": "",
                    "quality_score": 0.0,
                    "retry_count": 0,
                    "final_output": "",
                    "past_context": past_context,
                },
                config,
            )
    except Exception as e:
        query_log.status = "failed"
        query_log.final_report = None
        db.commit()
        raise HTTPException(status_code=502, detail="Research pipeline failed. Please try again.")

    query_log.status = "completed"
    query_log.final_report = result.get("final_output", "")
    query_log.quality_score = result.get("quality_score", 0.0)
    query_log.retry_count = result.get("retry_count", 0)
    db.commit()

    store_memory(current_user.id, body.query, query_log.final_report, thread_id)

    set_cached_result(body.query, {
        "final_output": query_log.final_report,
        "quality_score": query_log.quality_score,
        "retry_count": query_log.retry_count,
    })

    return {
        "query_id": query_log.id,
        "thread_id": thread_id,
        "final_output": query_log.final_report,
        "quality_score": query_log.quality_score,
        "retry_count": query_log.retry_count,
    }

@app.get("/history")
def get_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logs = (
        db.query(QueryLog)
        .filter(QueryLog.user_id == current_user.id)
        .order_by(QueryLog.created_at.desc())
        .limit(20)
        .all()
    )

    return [
        {
            "id": log.id,
            "thread_id": log.thread_id,
            "query": log.query,
            "quality_score": log.quality_score,
            "status": log.status,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]




