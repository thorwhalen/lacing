# lacing.otel

Optional OpenTelemetry instrumentation for the lacing server.

OTel is the “cherry on top” of the op-log architecture (BACK-DOC §4.7).
The op-log captures *what* happened; OTel publishes spans so downstream
distributed-tracing infra (Jaeger, Tempo, Honeycomb, …) can correlate
those mutations with calls from upstream services.

Design rules:

- **Optional.** `opentelemetry-*` packages are heavy. This module
  imports cleanly without them — every helper falls back to a no-op
  when OTel isn’t installed.
- **Auto-detect.** If `opentelemetry.api` is importable AND a
  `TracerProvider` has been configured (via the standard env vars
  `OTEL_EXPORTER_*` or programmatic setup), spans are emitted.
  Otherwise everything is a no-op and there’s no perf cost.
- **No globals.** Callers pass tracers around explicitly.

Usage:

```default
from lacing.otel import get_tracer, traced

tracer = get_tracer("lacing.server")

@traced(tracer, "my_operation", record_args=True)
def my_op(x, y):
    return x + y
```

In Phase 2.0+, the FastAPI middleware (`lacing.server.otel_middleware`,
opt-in) wraps every request in a span and tags it with the Lamport clock
returned by the op-log. The ASGI middleware is added to the app via
[`instrument_app()`](#lacing.otel.instrument_app) only when explicitly called — we don’t auto-mount
it because that would change behavior depending on whether opentelemetry
happened to be installed.

### Functions

| [`get_tracer`](#lacing.otel.get_tracer)([name, version])              | Return a tracer or a no-op fallback.                            |
|-------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| [`instrument_app`](#lacing.otel.instrument_app)(app, \*[, tracer_name])   | Add OpenTelemetry instrumentation to a FastAPI app.             |
| [`is_otel_active`](#lacing.otel.is_otel_active)()                         | Quick check: is OTel installed AND a TracerProvider configured? |
| [`maybe_span`](#lacing.otel.maybe_span)(tracer, name, \*\*attributes) | Open a span on `tracer`, attaching `attributes` if supported.   |
| [`traced`](#lacing.otel.traced)(tracer[, span_name, record_args]) | Decorator: wrap a function in a span on `tracer`.               |

### lacing.otel.get_tracer(name='lacing', version=None)

Return a tracer or a no-op fallback.

* **Parameters:**
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Instrumentation name (typically `__name__` of the caller’s
    module or a logical name like `"lacing.server"`).
  * **version** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional package version string.
* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)
* **Returns:**
  `opentelemetry.trace.Tracer` if OTel is installed, else a no-op
  object whose `start_as_current_span()` is a context manager
  yielding a no-op span.

### lacing.otel.instrument_app(app, , tracer_name='lacing.server')

Add OpenTelemetry instrumentation to a FastAPI app.

Wraps every request in a span; tags the span with the response’s
`X-Lacing-Clock` header value (when present) as `lacing.clock`.

No-op when OTel isn’t installed — the app is returned unchanged.

* **Parameters:**
  * **app** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – The FastAPI app (from `lacing.server.create_app()`).
  * **tracer_name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name passed to [`get_tracer()`](#lacing.otel.get_tracer).
* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)
* **Returns:**
  The same app, with middleware installed if OTel is available.

### lacing.otel.is_otel_active()

Quick check: is OTel installed AND a TracerProvider configured?

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.otel.maybe_span(tracer, name, \*\*attributes)

Open a span on `tracer`, attaching `attributes` if supported.

Works with both real OTel tracers and the no-op fallback.

### lacing.otel.traced(tracer, span_name=None, , record_args=False)

Decorator: wrap a function in a span on `tracer`.

* **Parameters:**
  * **tracer** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – From [`get_tracer()`](#lacing.otel.get_tracer).
  * **span_name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override the span name. Default: `func.__qualname__`.
  * **record_args** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, attach (str-coerced) positional + keyword
    args as span attributes `arg.<n>` / `kwarg.<name>`. Off
    by default — args may contain large or sensitive data.
