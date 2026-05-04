"""Tests for ``lacing.processors``.

Covers the registry, ``run_sync`` / ``run_async`` runners, and the two
built-in processors. Arq integration is exercised separately in
``test_worker.py``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from lacing.model import Annotation, MediaRef, Provenance
from lacing.oplog import InMemoryOpLog
from lacing.processors import (
    ProcessorError,
    detect_density_change_points,  # noqa: F401  ensure import side-effects
    get_processor,
    low_confidence_review,  # noqa: F401
    register_processor,
    registered_processors,
    run_async,
    run_sync,
)
from lacing.store import MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


def _ti(s: int, e: int, rate: int = 1000) -> TimeInterval:
    return TimeInterval(RationalTime(s, rate), RationalTime(e, rate))


def _ann(
    *,
    tier: str,
    interval: TimeInterval,
    text: str = "x",
    confidence: float | None = None,
    asset_id: str = "blake3:test",
) -> Annotation:
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(asset_id=asset_id, interval=interval),
        body={"text": text},
        body_schema_uri="annot://schema/word/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime(0),
        ),
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_built_ins_registered(self):
        names = registered_processors()
        assert "low_confidence_review" in names
        assert "detect_density_change_points" in names

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError):
            get_processor("never-heard-of")

    def test_register_decorator_with_name(self):
        @register_processor(name="custom_test_proc")
        async def _proc(*, store, oplog, **kw):
            return "ok"

        try:
            assert "custom_test_proc" in registered_processors()
            store = MemoryStore()
            log = InMemoryOpLog()
            assert run_sync("custom_test_proc", store=store, oplog=log) == "ok"
        finally:
            from lacing.processors import _PROCESSORS

            _PROCESSORS.pop("custom_test_proc", None)

    def test_register_sync_wrapped_to_async(self):
        @register_processor(name="sync_test_proc")
        def _proc(*, store, oplog, **kw):
            return 42

        try:
            store = MemoryStore()
            log = InMemoryOpLog()
            assert run_sync("sync_test_proc", store=store, oplog=log) == 42
        finally:
            from lacing.processors import _PROCESSORS

            _PROCESSORS.pop("sync_test_proc", None)


# ---------------------------------------------------------------------------
# runners
# ---------------------------------------------------------------------------


class TestRunners:
    def test_run_sync_unknown_raises(self):
        store = MemoryStore()
        log = InMemoryOpLog()
        with pytest.raises(KeyError):
            run_sync("never-heard-of", store=store, oplog=log)

    def test_run_sync_propagates_processor_error(self):
        @register_processor(name="explode_test")
        async def _proc(*, store, oplog, **kw):
            raise ValueError("boom")

        try:
            store = MemoryStore()
            log = InMemoryOpLog()
            with pytest.raises(ProcessorError, match="boom"):
                run_sync("explode_test", store=store, oplog=log)
        finally:
            from lacing.processors import _PROCESSORS

            _PROCESSORS.pop("explode_test", None)

    @pytest.mark.anyio
    async def test_run_async(self):
        store = MemoryStore()
        log = InMemoryOpLog()
        store.add_tier(Tier("words"))
        store.add(_ann(tier="words", interval=_ti(0, 1000), confidence=0.1))
        result = await run_async(
            "low_confidence_review",
            store=store,
            oplog=log,
            threshold=0.5,
        )
        assert result["flagged"] == 1

    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"


# ---------------------------------------------------------------------------
# low_confidence_review
# ---------------------------------------------------------------------------


class TestLowConfidenceReview:
    def _setup(self, *, confidences: list[float | None]):
        store = MemoryStore()
        log = InMemoryOpLog()
        store.add_tier(Tier("words"))
        for i, c in enumerate(confidences):
            store.add(
                _ann(
                    tier="words",
                    interval=_ti(i * 1000, (i + 1) * 1000),
                    confidence=c,
                )
            )
        return store, log

    def test_flags_below_threshold(self):
        store, log = self._setup(confidences=[0.1, 0.4, 0.6, 0.9])
        result = run_sync(
            "low_confidence_review",
            store=store,
            oplog=log,
            threshold=0.5,
        )
        assert result["flagged"] == 2
        review_count = len(list(store.by_tier("for-review")))
        assert review_count == 2

    def test_skips_none_confidence(self):
        store, log = self._setup(confidences=[None, None, 0.1])
        result = run_sync(
            "low_confidence_review",
            store=store,
            oplog=log,
            threshold=0.5,
        )
        assert result["flagged"] == 1

    def test_creates_review_tier_if_missing(self):
        store, log = self._setup(confidences=[0.1])
        assert store.get_tier("for-review") is None
        run_sync("low_confidence_review", store=store, oplog=log, threshold=0.5)
        assert store.get_tier("for-review") is not None

    def test_records_oplog_entries(self):
        store, log = self._setup(confidences=[0.1, 0.2])
        run_sync("low_confidence_review", store=store, oplog=log, threshold=0.5)
        # add_tier (1) + 2 add_annotation = 3 entries.
        assert log.latest_clock() == 3

    def test_review_provenance_links_back(self):
        store, log = self._setup(confidences=[0.1])
        run_sync("low_confidence_review", store=store, oplog=log, threshold=0.5)
        review = next(store.by_tier("for-review"))
        assert review.provenance.activity == "derive"
        assert review.provenance.was_attributed_to == "processor:low_confidence_review"
        assert len(review.provenance.was_derived_from) == 1
        # The body links back to the source.
        assert review.body["reason"] == "low_confidence"

    def test_does_not_recurse_on_review_tier(self):
        # If we run twice, the second pass should not re-flag review entries.
        store, log = self._setup(confidences=[0.1, 0.2])
        run_sync("low_confidence_review", store=store, oplog=log, threshold=0.5)
        first_review = len(list(store.by_tier("for-review")))
        run_sync("low_confidence_review", store=store, oplog=log, threshold=0.5)
        second_review = len(list(store.by_tier("for-review")))
        # Still only the original two — the review entries themselves carry
        # no `confidence`, so they're skipped.
        assert second_review == first_review == 2


# ---------------------------------------------------------------------------
# detect_density_change_points
# ---------------------------------------------------------------------------


class TestDensityChangePoints:
    def _setup_burst(self):
        """Build a store with a burst of annotations at second 5."""
        store = MemoryStore()
        log = InMemoryOpLog()
        store.add_tier(Tier("words"))
        # 1 ann at second 0, then 5 at second 5, then 1 at second 10.
        store.add(_ann(tier="words", interval=_ti(0, 100)))
        for offset in range(5):
            store.add(
                _ann(
                    tier="words",
                    interval=_ti(5000 + offset * 10, 5000 + offset * 10 + 100),
                )
            )
        store.add(_ann(tier="words", interval=_ti(10_000, 10_100)))
        return store, log

    def test_emits_markers_on_density_jump(self):
        store, log = self._setup_burst()
        result = run_sync(
            "detect_density_change_points",
            store=store,
            oplog=log,
            bucket_seconds=1.0,
            min_delta=3,
        )
        assert result["markers"] >= 1
        markers = list(store.by_tier("density-change-points"))
        assert len(markers) == result["markers"]
        # All markers should be point intervals.
        assert all(m.interval.is_point for m in markers)

    def test_min_delta_filters(self):
        store, log = self._setup_burst()
        # Very high min_delta -> nothing.
        result = run_sync(
            "detect_density_change_points",
            store=store,
            oplog=log,
            bucket_seconds=1.0,
            min_delta=100,
        )
        assert result["markers"] == 0

    def test_invalid_bucket_seconds_raises(self):
        store, log = self._setup_burst()
        with pytest.raises(ProcessorError):
            run_sync(
                "detect_density_change_points",
                store=store,
                oplog=log,
                bucket_seconds=0,
            )

    def test_filters_by_asset(self):
        store, log = self._setup_burst()
        # Add another asset's burst — should be ignored when asset_id set.
        for offset in range(5):
            store.add(
                _ann(
                    tier="words",
                    interval=_ti(20_000 + offset * 10, 20_000 + offset * 10 + 100),
                    asset_id="blake3:other",
                )
            )
        result = run_sync(
            "detect_density_change_points",
            store=store,
            oplog=log,
            asset_id="blake3:test",  # only the original
            bucket_seconds=1.0,
            min_delta=3,
        )
        markers = list(store.by_tier("density-change-points"))
        # Only the original burst should produce markers.
        assert all(
            m.reference.asset_id in ("blake3:test", "density-change-points:any")
            for m in markers
        )
        assert len(markers) == result["markers"]


# ---------------------------------------------------------------------------
# Arq worker integration (skipped if arq not installed)
# ---------------------------------------------------------------------------


class TestArqIntegration:
    def test_build_worker_settings_returns_class(self):
        pytest.importorskip("arq", reason="arq not installed")
        from lacing.worker import build_worker_settings

        store = MemoryStore()
        log = InMemoryOpLog()

        settings = build_worker_settings(
            store_factory=lambda: store,
            oplog_factory=lambda: log,
        )
        assert isinstance(settings, type)
        assert hasattr(settings, "functions")
        assert len(settings.functions) >= 1
        assert hasattr(settings, "redis_settings")

    def test_missing_arq_raises_import_error(self, monkeypatch):
        # Even without arq installed we want a clean ImportError, not a
        # NameError or anything else. Force the import to fail and check.
        import sys

        original = sys.modules.pop("arq", None)
        sys.modules["arq"] = None  # type: ignore[assignment]
        try:
            from lacing.worker import build_worker_settings

            with pytest.raises(ImportError, match="lacing\\[arq\\]"):
                build_worker_settings(
                    store_factory=lambda: MemoryStore(),
                    oplog_factory=lambda: InMemoryOpLog(),
                )
        finally:
            if original is not None:
                sys.modules["arq"] = original
            else:
                sys.modules.pop("arq", None)
