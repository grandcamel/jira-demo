"""
OpenTelemetry setup module for Python scripts.

Provides initialization and tracing utilities for JIRA sandbox scripts.

Usage:
    from otel_setup import init_telemetry, traced

    # Initialize at script startup
    tracer = init_telemetry("script-name")

    # Decorate functions to trace
    @traced("operation-name")
    def my_function():
        pass
"""

import functools
import os
from contextlib import contextmanager
from typing import Any, Callable, Optional

# OpenTelemetry imports - optional dependency
try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

# Module-level tracer
_tracer: Optional[Any] = None


def init_telemetry(service_name: str) -> Optional[Any]:
    """
    Initialize OpenTelemetry tracing.

    Args:
        service_name: Name for this service in traces

    Returns:
        Tracer instance if OTel is available, None otherwise
    """
    global _tracer

    if not OTEL_AVAILABLE:
        print("[OTEL] OpenTelemetry not installed, tracing disabled")
        return None

    # Check if OTEL endpoint is configured
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        # Default to local LGTM stack
        endpoint = "http://localhost:4318"

    try:
        # Create resource with service name
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": "1.0.0",
            }
        )

        # Create tracer provider
        provider = TracerProvider(resource=resource)

        # Add OTLP exporter
        exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))

        # Set as global provider
        trace.set_tracer_provider(provider)

        # Get tracer
        _tracer = trace.get_tracer(service_name)

        print(f"[OTEL] Tracing initialized for {service_name} -> {endpoint}")
        return _tracer

    except Exception as e:
        print(f"[OTEL] Failed to initialize tracing: {e}")
        return None


def get_tracer() -> Optional[Any]:
    """Get the module-level tracer instance."""
    return _tracer


def traced(operation_name: str) -> Callable:
    """
    Decorator to trace function execution.

    Args:
        operation_name: Name for the span

    Usage:
        @traced("delete_issues")
        def delete_user_created_issues(client, project_key):
            pass
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if _tracer is None:
                # No tracing available, just call the function
                return func(*args, **kwargs)

            with _tracer.start_as_current_span(operation_name) as span:
                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise

        return wrapper

    return decorator


@contextmanager
def trace_span(name: str, attributes: Optional[dict] = None):
    """
    Context manager for creating trace spans.

    Args:
        name: Span name
        attributes: Optional span attributes

    Usage:
        with trace_span("process_issue", {"issue.key": "DEMO-1"}):
            process_issue(issue)
    """
    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            if OTEL_AVAILABLE:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
            raise


def add_span_attribute(key: str, value: Any) -> None:
    """
    Add an attribute to the current span.

    Args:
        key: Attribute key
        value: Attribute value
    """
    if not OTEL_AVAILABLE:
        return

    current_span = trace.get_current_span()
    if current_span:
        current_span.set_attribute(key, value)


def record_span_event(name: str, attributes: Optional[dict] = None) -> None:
    """
    Record an event on the current span.

    Args:
        name: Event name
        attributes: Optional event attributes
    """
    if not OTEL_AVAILABLE:
        return

    current_span = trace.get_current_span()
    if current_span:
        current_span.add_event(name, attributes or {})
