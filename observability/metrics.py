# observability/metrics.py

from prometheus_client import Counter, Histogram, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

registry = CollectorRegistry()

AGENT_REQUEST_LATENCY = Histogram(
    "agent_request_duration_seconds",
    "A2A task handling latency per agent",
    ["agent_name", "status"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120),
    registry=registry,
)

AGENT_REQUESTS_TOTAL = Counter(
    "agent_requests_total",
    "Total A2A tasks handled per agent, by outcome",
    ["agent_name", "status"],  # status: completed | failed | blocked
    registry=registry,
)

LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed, by agent and token type",
    ["agent_name", "token_type"],  # token_type: prompt | completion
    registry=registry,
)

LLM_CALLS_TOTAL = Counter(
    "llm_calls_total",
    "Total LLM invocations per agent",
    ["agent_name"],
    registry=registry,
)

RETRY_TOTAL = Counter(
    "orchestrator_retry_total",
    "Number of times the Critic sent a report back for re-synthesis",
    registry=registry,
)

QUALITY_SCORE = Histogram(
    "orchestrator_quality_score",
    "Distribution of Critic quality scores",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
    registry=registry,
)

GUARDRAIL_VIOLATIONS_TOTAL = Counter(
    "guardrail_violations_total",
    "Guardrail checks that found a violation, by action taken",
    ["agent_name", "action"],  # action: sanitized | blocked
    registry=registry,
)

DOWNSTREAM_CALL_LATENCY = Histogram(
    "downstream_call_duration_seconds",
    "Latency of outbound calls to downstream dependencies (MCP, Qdrant, Groq)",
    ["dependency", "status"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
    registry=registry,
)


def record_agent_request(agent_name: str, status: str, duration_seconds: float) -> None:
    AGENT_REQUESTS_TOTAL.labels(agent_name=agent_name, status=status).inc()
    AGENT_REQUEST_LATENCY.labels(agent_name=agent_name, status=status).observe(duration_seconds)


def record_llm_usage(agent_name: str, response) -> None:
    """
    Pulls token counts off a LangChain ChatGroq response's usage_metadata
    (present on AIMessage). No-ops safely if it's missing.
    """
    LLM_CALLS_TOTAL.labels(agent_name=agent_name).inc()
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    if input_tokens:
        LLM_TOKENS_TOTAL.labels(agent_name=agent_name, token_type="prompt").inc(input_tokens)
    if output_tokens:
        LLM_TOKENS_TOTAL.labels(agent_name=agent_name, token_type="completion").inc(output_tokens)


def record_guardrail_violation(agent_name: str, action: str) -> None:
    GUARDRAIL_VIOLATIONS_TOTAL.labels(agent_name=agent_name, action=action).inc()


def record_retry() -> None:
    RETRY_TOTAL.inc()


def record_quality_score(score: float) -> None:
    QUALITY_SCORE.observe(score)


def record_downstream_call(dependency: str, status: str, duration_seconds: float) -> None:
    DOWNSTREAM_CALL_LATENCY.labels(dependency=dependency, status=status).observe(duration_seconds)


def metrics_response() -> tuple[bytes, str]:
    """Returns (body, content_type) ready to hand to a FastAPI Response."""
    return generate_latest(registry), CONTENT_TYPE_LATEST