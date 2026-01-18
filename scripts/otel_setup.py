"""
OpenTelemetry setup module for Python scripts.

Provides initialization and tracing utilities for JIRA sandbox scripts
and skill testing. Supports both OTLP tracing and Loki logging.

Usage:
    from otel_setup import init_telemetry, traced, log_to_loki

    # Initialize at script startup
    tracer = init_telemetry("script-name")

    # Decorate functions to trace
    @traced("operation-name")
    def my_function():
        pass

    # Log to Loki
    log_to_loki("message", level="info", extra={"key": "value"})
"""

import functools
import json
import os
import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Optional

# Optional dependency for HTTP logging
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

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

# Module-level state
_tracer: Optional[Any] = None
_trace_provider: Optional[Any] = None
_loki_endpoint: Optional[str] = None
_debug_enabled: bool = True
_scenario_name: str = "unknown"


def init_telemetry(
    service_name: str,
    scenario: str = "unknown",
    debug: bool = True,
) -> Optional[Any]:
    """
    Initialize OpenTelemetry tracing and Loki logging.

    Args:
        service_name: Name for this service in traces
        scenario: Scenario name for log labels (default: "unknown")
        debug: Enable telemetry (default: True, set False to disable)

    Returns:
        Tracer instance if OTel is available and debug enabled, None otherwise
    """
    global _tracer, _trace_provider, _loki_endpoint, _debug_enabled, _scenario_name

    _debug_enabled = debug
    _scenario_name = scenario

    if not debug:
        print("[OTEL] Debug mode disabled, telemetry off", file=sys.stderr)
        return None

    # Configure endpoints with Docker-aware defaults
    if os.path.exists("/.dockerenv"):
        # Inside Docker container
        otel_endpoint = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://host.docker.internal:4318"
        )
        _loki_endpoint = os.environ.get(
            "LOKI_ENDPOINT", "http://host.docker.internal:3100"
        )
    else:
        # Host machine
        otel_endpoint = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
        )
        _loki_endpoint = os.environ.get("LOKI_ENDPOINT", "http://localhost:3100")

    # Initialize tracing if available
    if OTEL_AVAILABLE:
        try:
            # Create resource with service name and scenario
            resource = Resource.create({
                "service.name": service_name,
                "service.version": "1.0.0",
                "scenario": scenario,
            })

            # Create tracer provider
            _trace_provider = TracerProvider(resource=resource)

            # Add OTLP exporter
            exporter = OTLPSpanExporter(endpoint=f"{otel_endpoint}/v1/traces")
            _trace_provider.add_span_processor(BatchSpanProcessor(exporter))

            # Set as global provider
            trace.set_tracer_provider(_trace_provider)

            # Get tracer
            _tracer = trace.get_tracer(service_name)

            print(f"[OTEL] Tracing initialized -> {otel_endpoint}", file=sys.stderr)
        except Exception as e:
            print(f"[OTEL] Failed to initialize tracing: {e}", file=sys.stderr)
            _tracer = None
    else:
        print("[OTEL] OpenTelemetry not installed, tracing disabled", file=sys.stderr)

    if _loki_endpoint:
        print(f"[OTEL] Loki logging -> {_loki_endpoint}", file=sys.stderr)

    return _tracer


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


def shutdown_telemetry() -> None:
    """Shutdown telemetry and flush all pending spans."""
    global _trace_provider
    if _trace_provider is not None:
        try:
            _trace_provider.force_flush(timeout_millis=5000)
            _trace_provider.shutdown()
            print("[OTEL] Telemetry shutdown complete", file=sys.stderr)
        except Exception as e:
            print(f"[OTEL] Shutdown error: {e}", file=sys.stderr)


def log_to_loki(
    message: str,
    level: str = "info",
    labels: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> None:
    """
    Send a log entry to Loki.

    Args:
        message: Log message
        level: Log level (info, warning, error, debug)
        labels: Additional stream labels
        extra: Additional fields to include in log JSON
    """
    if not _debug_enabled or not _loki_endpoint or not REQUESTS_AVAILABLE:
        return

    try:
        timestamp_ns = str(int(time.time() * 1e9))

        # Build log line with extra data
        log_data = {"message": message, "level": level}
        if extra:
            log_data.update(extra)

        log_line = json.dumps(log_data)

        # Build stream labels
        stream_labels = {
            "job": "skill-test",
            "scenario": _scenario_name,
            "level": level,
        }
        if labels:
            stream_labels.update(labels)

        payload = {
            "streams": [{
                "stream": stream_labels,
                "values": [[timestamp_ns, log_line]],
            }]
        }

        # Fire and forget
        requests.post(
            f"{_loki_endpoint}/loki/api/v1/push",
            json=payload,
            timeout=2,
        )
    except Exception:
        pass  # Don't fail due to logging issues


def get_scenario_name() -> str:
    """Get the current scenario name."""
    return _scenario_name


def is_debug_enabled() -> bool:
    """Check if debug/telemetry is enabled."""
    return _debug_enabled
