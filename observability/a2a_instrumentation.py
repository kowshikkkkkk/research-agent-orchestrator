# observability/a2a_instrumentation.py

import time
from contextlib import contextmanager

from observability.logging_config import get_logger, set_trace_id, get_trace_id
from observability.tracing import init_tracing, extract_trace_context, get_current_trace_id
from observability.metrics import record_agent_request, record_guardrail_violation


class A2AInstrumentation:
    """
    One instance per agent service, created at module load time, e.g.:
        instrumentation = A2AInstrumentation("web_research")
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.tracer = init_tracing(agent_name)
        self.logger = get_logger(agent_name)

    @contextmanager
    def task_span(self, task_id: str, incoming_headers: dict | None = None):
        parent_ctx = extract_trace_context(incoming_headers or {})
        start = time.time()

        with self.tracer.start_as_current_span(
            f"{self.agent_name}.handle_task",
            context=parent_ctx,
            attributes={"a2a.task_id": task_id, "a2a.agent": self.agent_name},
        ) as span:
            trace_id = get_current_trace_id()
            set_trace_id(trace_id if trace_id != "-" else task_id)

            self.logger.info(
                "task received",
                extra={"extra_fields": {"task_id": task_id, "event": "task_start"}},
            )

            ctx = _SpanContext(span, self)
            try:
                yield ctx
            except Exception as e:
                # start_as_current_span() already records the exception
                # and sets ERROR status automatically once it propagates
                # out of this context manager.
                ctx.record_outcome("failed")
                self.logger.error(
                    f"task failed: {e}",
                    extra={"extra_fields": {"task_id": task_id, "event": "task_error"}},
                    exc_info=True,
                )
                raise
            finally:
                duration = time.time() - start
                status = ctx.outcome or "unknown"
                record_agent_request(self.agent_name, status, duration)
                self.logger.info(
                    "task finished",
                    extra={"extra_fields": {
                        "task_id": task_id,
                        "event": "task_end",
                        "status": status,
                        "duration_ms": round(duration * 1000, 2),
                    }},
                )

    def log_guardrail_violation(self, action: str, violations: list):
        record_guardrail_violation(self.agent_name, action)
        self.logger.warning(
            "guardrail violation",
            extra={"extra_fields": {"event": "guardrail_violation", "action": action, "violations": violations}},
        )


class _SpanContext:
    def __init__(self, span, instrumentation: A2AInstrumentation):
        self.span = span
        self.instrumentation = instrumentation
        self.outcome: str | None = None

    def record_outcome(self, status: str):
        self.outcome = status
        self.span.set_attribute("a2a.status", status)