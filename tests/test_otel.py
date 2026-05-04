"""Tests for ``lacing.otel`` — optional OpenTelemetry instrumentation.

Two paths to cover:

1. **OTel is not installed / no provider configured** — every helper
   should be a clean no-op (no errors, no cost).
2. **OTel installed and a real provider is set up** — spans are
   produced and contain the expected attributes.

For (2) we use OTel's in-memory ``InMemorySpanExporter`` so we can assert
on emitted spans without running a collector.
"""

from __future__ import annotations

import pytest

from lacing.otel import (
    get_tracer,
    instrument_app,
    is_otel_active,
    maybe_span,
    traced,
)


# ---------------------------------------------------------------------------
# no-op behavior (always works, even without OTel)
# ---------------------------------------------------------------------------


class TestNoOpFallback:
    def test_get_tracer_returns_something(self):
        tracer = get_tracer("anything")
        assert tracer is not None
        # Must support start_as_current_span as a context manager.
        with tracer.start_as_current_span("test") as span:
            assert span is not None

    def test_maybe_span_no_op_swallows_attributes(self):
        tracer = get_tracer("test")
        with maybe_span(tracer, "name", clock=5, foo="bar") as span:
            assert span is not None
            # set_attribute is a no-op on the fallback span.
            span.set_attribute("anything", "x")

    def test_maybe_span_propagates_exceptions(self):
        tracer = get_tracer("test")
        with pytest.raises(ValueError):
            with maybe_span(tracer, "raise_test"):
                raise ValueError("boom")

    def test_traced_decorator_no_op(self):
        tracer = get_tracer("test")

        @traced(tracer, "double")
        def double(x):
            return x * 2

        assert double(3) == 6

    def test_traced_decorator_with_record_args(self):
        tracer = get_tracer("test")

        @traced(tracer, "add", record_args=True)
        def add(x, y, *, k=0):
            return x + y + k

        assert add(1, 2, k=3) == 6


# ---------------------------------------------------------------------------
# real OTel SDK behavior (skipped if SDK isn't installed)
# ---------------------------------------------------------------------------


sdk = pytest.importorskip("opentelemetry.sdk.trace", reason="OTel SDK not installed")


@pytest.fixture(scope="module")
def _otel_provider_setup():
    """Set up a session-wide TracerProvider with InMemorySpanExporter.

    OTel forbids replacing a configured TracerProvider, so we install ours
    once for the module and reuse it across tests. Each test gets a fresh
    span buffer via the function-scoped ``otel_collector`` fixture.
    """
    from opentelemetry import trace as ot
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Try to install. If a provider is already set (likely from a prior
    # test module), reuse it and create our own provider with the
    # exporter; we just won't be able to make get_tracer() see it. To
    # work around that, we use the provider directly — get_tracer comes
    # from the global, but our exporter watches our own provider's spans
    # only. Solution: install eagerly here and skip the OTel path tests
    # if the global is already non-mutable.
    try:
        ot.set_tracer_provider(provider)
    except Exception:  # pragma: no cover
        pass
    yield exporter


@pytest.fixture
def otel_collector(_otel_provider_setup):
    """Function-scoped: yields the exporter with its span buffer cleared."""
    _otel_provider_setup.clear()
    yield _otel_provider_setup


class TestRealOtel:
    def test_is_otel_active_after_setup(self, otel_collector):
        assert is_otel_active() is True

    def test_maybe_span_emits_span(self, otel_collector):
        tracer = get_tracer("test")
        with maybe_span(tracer, "demo", clock=42, op="add_annotation"):
            pass

        spans = otel_collector.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "demo"
        # Attributes get the lacing.* namespace prefix.
        assert span.attributes.get("lacing.clock") == 42
        assert span.attributes.get("lacing.op") == "add_annotation"

    def test_traced_decorator_emits_span(self, otel_collector):
        tracer = get_tracer("test")

        @traced(tracer, "compute")
        def compute(x):
            return x + 1

        compute(7)
        spans = otel_collector.get_finished_spans()
        assert any(s.name == "compute" for s in spans)

    def test_exception_recorded_and_status_set(self, otel_collector):
        from opentelemetry.trace import StatusCode

        tracer = get_tracer("test")
        with pytest.raises(RuntimeError):
            with maybe_span(tracer, "fails"):
                raise RuntimeError("nope")

        spans = otel_collector.get_finished_spans()
        fail_span = next(s for s in spans if s.name == "fails")
        assert fail_span.status.status_code == StatusCode.ERROR
        # Recorded exception should appear as an event.
        event_names = [e.name for e in fail_span.events]
        assert "exception" in event_names

    def test_attributes_with_dotted_keys_left_unchanged(self, otel_collector):
        tracer = get_tracer("test")
        with maybe_span(tracer, "demo", **{"http.method": "GET", "clock": 1}):
            pass

        spans = otel_collector.get_finished_spans()
        span = spans[0]
        # http.method already has a dot; should NOT be re-namespaced.
        assert span.attributes.get("http.method") == "GET"
        assert span.attributes.get("lacing.clock") == 1


# ---------------------------------------------------------------------------
# FastAPI integration
# ---------------------------------------------------------------------------


fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

from lacing.oplog import InMemoryOpLog  # noqa: E402
from lacing.server import create_app  # noqa: E402
from lacing.server.deps import get_oplog, get_store  # noqa: E402
from lacing.store import MemoryStore  # noqa: E402
from lacing.tier import Tier  # noqa: E402


def _build_client():
    store = MemoryStore()
    store.add_tier(Tier("words"))
    log = InMemoryOpLog()
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_oplog] = lambda: log
    instrument_app(app)
    return TestClient(app), log


class TestServerInstrumentation:
    def test_instrument_app_returns_app(self):
        app = create_app()
        result = instrument_app(app)
        assert result is app  # no-op or instrumented; same object

    def test_request_through_instrumented_app_succeeds(self):
        client, _log = _build_client()
        r = client.get("/health")
        assert r.status_code == 200

    def test_clock_header_attached_to_span(self, otel_collector):
        client, _log = _build_client()
        # Trigger a write — that returns X-Lacing-Clock.
        payload = {
            "tier": "words",
            "reference": {
                "kind": "media",
                "asset_id": "x",
                "interval": {
                    "start": {"v": 0, "r": 1000},
                    "end": {"v": 1000, "r": 1000},
                },
            },
            "body": {"text": "hi"},
            "body_schema_uri": "annot://schema/word/v1",
        }
        r = client.post("/annotations", json=payload)
        assert r.status_code == 201
        assert r.headers.get("X-Lacing-Clock") == "1"

        spans = otel_collector.get_finished_spans()
        # Find the POST span
        post_spans = [s for s in spans if s.name == "POST /annotations"]
        assert len(post_spans) == 1
        span = post_spans[0]
        assert span.attributes.get("lacing.clock") == 1
        assert span.attributes.get("http.status_code") == 201
