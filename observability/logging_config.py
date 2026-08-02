# observability/logging_config.py

import logging
import json
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

# Bound per async/sync call context. Set once at the entry point of a
# request (A2A task handler, orchestrator node) and read automatically
# by every log line emitted while that context is active.
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": record.name,
            "trace_id": trace_id_var.get(),
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if extra_fields:
            payload.update(extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(service_name: str) -> logging.Logger:
    logger = logging.getLogger(service_name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def set_trace_id(trace_id: str) -> None:
    trace_id_var.set(trace_id)


def get_trace_id() -> str:
    return trace_id_var.get()