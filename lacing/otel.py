"""Optional OpenTelemetry instrumentation for the lacing server.

OTel is the "cherry on top" of the op-log architecture (BACK-DOC §4.7).
The op-log captures *what* happened; OTel publishes spans so downstream
distributed-tracing infra (Jaeger, Tempo, Honeycomb, ...) can correlate
those mutations with calls from upstream services.

Design rules:

- **Optional.** ``opentelemetry-*`` packages are heavy. This module
  imports cleanly without them — every helper falls back to a no-op
  when OTel isn't installed.
- **Auto-detect.** If ``opentelemetry.api`` is importable AND a
  ``TracerProvider`` has been configured (via the standard env vars
  ``OTEL_EXPORTER_*`` or programmatic setup), spans are emitted.
  Otherwise everything is a no-op and there's no perf cost.
- **No globals.** Callers pass tracers around explicitly.

Usage::

    from lacing.otel import get_tracer, traced

    tracer = get_tracer("lacing.server")

    @traced(tracer, "my_operation", record_args=True)
    def my_op(x, y):
        return x + y

In Phase 2.0+, the FastAPI middleware (``lacing.server.otel_middleware``,
opt-in) wraps every request in a span and tags it with the Lamport clock
returned by the op-log. The ASGI middleware is added to the app via
:func:`instrument_app` only when explicitly called — we don't auto-mount
it because that would change behavior depending on whether opentelemetry
happened to be installed.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any, TypeVar


T = TypeVar("T")


def _otel_available() -> bool:
    try:
        import opentelemetry.trace  # noqa: F401
    except ImportError:
        return False
    return True


def get_tracer(name: str = "lacing", version: str | None = None) -> Any:
    """Return a tracer or a no-op fallback.

    Args:
        name: Instrumentation name (typically ``__name__`` of the caller's
            module or a logical name like ``"lacing.server"``).
        version: Optional package version string.

    Returns:
        ``opentelemetry.trace.Tracer`` if OTel is installed, else a no-op
        object whose ``start_as_current_span()`` is a context manager
        yielding a no-op span.
    """
    if not _otel_available():
        return _NoOpTracer()
    import opentelemetry.trace as ot

    return ot.get_tracer(name, version)


@contextmanager
def maybe_span(tracer: Any, name: str, **attributes: Any):
    """Open a span on ``tracer``, attaching ``attributes`` if supported.

    Works with both real OTel tracers and the no-op fallback.
    """
    span_ctx = tracer.start_as_current_span(name)
    span = span_ctx.__enter__()
    try:
        if attributes and hasattr(span, "set_attribute"):
            for key, value in attributes.items():
                if value is None:
                    continue
                # OTel attribute values must be primitive — coerce others to str.
                if not isinstance(value, (str, int, float, bool)):
                    value = str(value)
                try:
                    span.set_attribute(_attr_key(key), value)
                except Exception:  # pragma: no cover  — defensive
                    pass
        yield span
    except Exception as exc:
        if hasattr(span, "record_exception"):
            try:
                span.record_exception(exc)
            except Exception:  # pragma: no cover
                pass
        if hasattr(span, "set_status"):
            try:
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:  # pragma: no cover
                pass
        raise
    finally:
        span_ctx.__exit__(None, None, None)


def _attr_key(key: str) -> str:
    """Namespace lacing-specific attribute keys to ``lacing.<key>``."""
    if "." in key:
        return key
    return f"lacing.{key}"


def traced(
    tracer: Any,
    span_name: str | None = None,
    *,
    record_args: bool = False,
):
    """Decorator: wrap a function in a span on ``tracer``.

    Args:
        tracer: From :func:`get_tracer`.
        span_name: Override the span name. Default: ``func.__qualname__``.
        record_args: If True, attach (str-coerced) positional + keyword
            args as span attributes ``arg.<n>`` / ``kwarg.<name>``. Off
            by default — args may contain large or sensitive data.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        name = span_name or func.__qualname__

        @wraps(func)
        def wrapper(*args, **kwargs):
            extra: dict[str, Any] = {}
            if record_args:
                for i, val in enumerate(args):
                    extra[f"arg.{i}"] = val
                for k, val in kwargs.items():
                    extra[f"kwarg.{k}"] = val
            with maybe_span(tracer, name, **extra):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def is_otel_active() -> bool:
    """Quick check: is OTel installed AND a TracerProvider configured?"""
    if not _otel_available():
        return False
    try:
        import opentelemetry.trace as ot

        provider = ot.get_tracer_provider()
        # Default no-op provider has class name 'ProxyTracerProvider' or
        # 'NoOpTracerProvider' depending on SDK version. If the user
        # configured a real provider, the class will be different.
        provider_cls = type(provider).__name__
        return provider_cls not in {"ProxyTracerProvider", "NoOpTracerProvider"}
    except Exception:  # pragma: no cover
        return False


# ---------------------------------------------------------------------------
# no-op fallback
# ---------------------------------------------------------------------------


class _NoOpSpan:
    """Drop-in replacement for ``opentelemetry.trace.Span`` when OTel is off."""

    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def record_exception(self, exception: BaseException, **kwargs: Any) -> None:
        return None

    def set_status(self, status: Any) -> None:
        return None


class _NoOpSpanContext:
    """Drop-in for the context manager returned by ``start_as_current_span``."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __enter__(self) -> _NoOpSpan:
        return _NoOpSpan()

    def __exit__(self, *exc_info) -> None:
        return None


class _NoOpTracer:
    """Tracer fallback for when OTel isn't installed.

    Mimics enough of ``opentelemetry.trace.Tracer`` for ``maybe_span``
    and ``traced`` to work without conditionals at every call site.
    """

    def start_as_current_span(self, name: str) -> _NoOpSpanContext:
        return _NoOpSpanContext(name)


# ---------------------------------------------------------------------------
# server integration
# ---------------------------------------------------------------------------


def instrument_app(app: Any, *, tracer_name: str = "lacing.server") -> Any:
    """Add OpenTelemetry instrumentation to a FastAPI app.

    Wraps every request in a span; tags the span with the response's
    ``X-Lacing-Clock`` header value (when present) as ``lacing.clock``.

    No-op when OTel isn't installed — the app is returned unchanged.

    Args:
        app: The FastAPI app (from :func:`lacing.server.create_app`).
        tracer_name: Name passed to :func:`get_tracer`.

    Returns:
        The same app, with middleware installed if OTel is available.
    """
    if not _otel_available():
        return app

    tracer = get_tracer(tracer_name)

    @app.middleware("http")
    async def _otel_middleware(request, call_next):
        path = request.url.path
        method = request.method
        span_name = f"{method} {path}"
        with maybe_span(
            tracer,
            span_name,
            **{
                "http.method": method,
                "http.target": path,
            },
        ) as span:
            response = await call_next(request)
            if hasattr(span, "set_attribute"):
                clock_header = response.headers.get("X-Lacing-Clock")
                if clock_header is not None:
                    try:
                        span.set_attribute("lacing.clock", int(clock_header))
                    except (TypeError, ValueError):
                        pass
                try:
                    span.set_attribute("http.status_code", response.status_code)
                except Exception:  # pragma: no cover
                    pass
            return response

    return app
