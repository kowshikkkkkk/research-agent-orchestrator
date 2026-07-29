# observability/tracing.py

import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.propagate import inject, extract

_propagator = TraceContextTextMapPropagator()
_initialized_services: set[str] = set()


def init_tracing(service_name: str) -> trace.Tracer:
    """
    Call once per service at process startup. Idempotent per service_name.
    """
    if service_name not in _initialized_services:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        else:
            # No collector configured — still create real spans, just
            # print them to console instead of shipping over the network.
            exporter = ConsoleSpanExporter()

        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _initialized_services.add(service_name)

    return trace.get_tracer(service_name)


def inject_trace_headers(headers: dict) -> dict:
    """
    Call before every outbound httpx request. Mutates and returns the
    headers dict with the W3C traceparent header added.
    """
    inject(headers)
    return headers


def extract_trace_context(headers: dict):
    """
    Call at the top of every A2A task handler, so spans created here
    attach as children of the caller's span instead of starting fresh.
    """
    return extract(headers)


def get_current_trace_id() -> str:
    """
    Returns the active trace's 32-hex-char ID, or '-' if no span is active.
    """
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.trace_id == 0:
        return "-"
    return format(ctx.trace_id, "032x")