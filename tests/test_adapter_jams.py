"""Tests for the JAMS adapter.

Skipped if ``jams`` is not installed.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

jams_lib = pytest.importorskip("jams")

from lacing.adapters import find_adapter, get_adapter  # noqa: E402
from lacing.adapters import jams as adapter_module  # noqa: E402, F401  registers
from lacing.model import Annotation, MediaRef, Provenance  # noqa: E402
from lacing.store import MemoryStore  # noqa: E402
from lacing.tier import Tier  # noqa: E402
from lacing.time import RationalTime, TimeInterval  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_jams_path(tmp_path) -> Path:
    """Build a small JAMS file with chord and beat annotations."""
    j = jams_lib.JAMS()
    j.file_metadata.duration = 4.0
    j.file_metadata.title = "demo"

    chord = jams_lib.Annotation(namespace="chord")
    chord.append(time=0.0, duration=2.0, value="C")
    chord.append(time=2.0, duration=2.0, value="G")
    chord.annotation_metadata.annotator = {"name": "thor"}
    j.annotations.append(chord)

    beat = jams_lib.Annotation(namespace="beat")
    beat.append(time=0.5, duration=0.0, value=1)
    beat.append(time=1.0, duration=0.0, value=2, confidence=0.9)
    j.annotations.append(beat)

    out = tmp_path / "sample.jams"
    j.save(str(out))
    return out


def _make_store_for_dump(rate: int = 1000) -> MemoryStore:
    s = MemoryStore()
    s.add_tier(Tier("chord"))
    s.add_tier(Tier("beat"))

    def _ann(
        tier: str, start_ms: int, end_ms: int, value, confidence: float | None = None
    ) -> Annotation:
        return Annotation(
            id=uuid4(),
            tier=tier,
            reference=MediaRef(
                asset_id="jams:title:demo",
                interval=TimeInterval(
                    RationalTime(start_ms, rate), RationalTime(end_ms, rate)
                ),
            ),
            body={"value": value, "namespace": tier},
            body_schema_uri="annot://schema/jams-observation/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="thor",
                generated_at_time=RationalTime.zero(rate),
            ),
            confidence=confidence,
        )

    s.add(_ann("chord", 0, 2000, "C"))
    s.add(_ann("chord", 2000, 4000, "G"))
    s.add(_ann("beat", 500, 500, 1))  # zero-duration = beat marker
    s.add(_ann("beat", 1000, 1000, 2, confidence=0.9))
    return s


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("jams")
        assert spec.name == "jams"
        assert ".jams" in spec.extensions

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".jams") is not None

    def test_lookup_by_media_type(self):
        assert find_adapter(media_type="application/vnd.jams+json") is not None


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_from_path(self, sample_jams_path):
        store = adapter_module.load(sample_jams_path, rate=1000)
        # 2 chords + 2 beats = 4
        assert len(list(store.all())) == 4

    def test_creates_tiers_per_namespace(self, sample_jams_path):
        store = adapter_module.load(sample_jams_path, rate=1000)
        names = {t.name for t in store.tiers()}
        assert names == {"chord", "beat"}

    def test_chord_intervals_and_values(self, sample_jams_path):
        store = adapter_module.load(sample_jams_path, rate=1000)
        chords = sorted(
            store.by_tier("chord"),
            key=lambda a: a.interval.start.to_fraction(),
        )
        assert len(chords) == 2
        assert chords[0].body["value"] == "C"
        assert chords[1].body["value"] == "G"
        assert chords[0].interval.start.value == 0
        assert chords[0].interval.end.value == 2000

    def test_beats_can_be_zero_duration(self, sample_jams_path):
        store = adapter_module.load(sample_jams_path, rate=1000)
        beats = sorted(
            store.by_tier("beat"),
            key=lambda a: a.interval.start.to_fraction(),
        )
        assert all(b.interval.is_point for b in beats)
        assert beats[0].body["value"] == 1
        assert beats[1].body["value"] == 2

    def test_confidence_preserved(self, sample_jams_path):
        store = adapter_module.load(sample_jams_path, rate=1000)
        beats = sorted(
            store.by_tier("beat"),
            key=lambda a: a.interval.start.to_fraction(),
        )
        assert beats[0].confidence is None
        assert beats[1].confidence == pytest.approx(0.9)

    def test_attribution_from_annotator(self, sample_jams_path):
        store = adapter_module.load(sample_jams_path, rate=1000)
        chord = next(store.by_tier("chord"))
        assert chord.provenance.was_attributed_to == "thor"
        assert chord.provenance.was_generated_by == "adapter:jams"

    def test_default_attribution_when_missing(self, tmp_path):
        # Build a JAMS without annotator info.
        j = jams_lib.JAMS()
        j.file_metadata.duration = 1.0
        ann = jams_lib.Annotation(namespace="tag_open")
        ann.append(time=0.0, duration=1.0, value="hello")
        j.annotations.append(ann)
        path = tmp_path / "noannot.jams"
        j.save(str(path))

        store = adapter_module.load(path, rate=1000)
        a = next(store.all())
        assert a.provenance.was_attributed_to == "anonymous"

    def test_attribution_override(self, sample_jams_path):
        store = adapter_module.load(
            sample_jams_path, rate=1000, attribution="alice"
        )
        a = next(store.all())
        assert a.provenance.was_attributed_to == "alice"

    def test_asset_id_override(self, sample_jams_path):
        store = adapter_module.load(
            sample_jams_path, rate=1000, asset_id="blake3:hash"
        )
        a = next(store.all())
        assert a.reference.asset_id == "blake3:hash"

    def test_asset_id_from_title(self, sample_jams_path):
        # No override -> uses file_metadata.title prefixed with jams:title:
        store = adapter_module.load(sample_jams_path, rate=1000)
        a = next(store.all())
        assert a.reference.asset_id == "jams:title:demo"

    def test_load_from_bytes(self, sample_jams_path):
        blob = sample_jams_path.read_bytes()
        store = adapter_module.load(blob, rate=1000)
        assert len(list(store.all())) == 4

    def test_load_from_inline_string(self, sample_jams_path):
        text = sample_jams_path.read_text()
        store = adapter_module.load(text, rate=1000)
        assert len(list(store.all())) == 4


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


class TestDump:
    def test_dump_returns_bytes(self):
        store = _make_store_for_dump()
        blob = adapter_module.dump(store)
        assert isinstance(blob, bytes)
        assert b"chord" in blob
        assert b"beat" in blob

    def test_dump_to_path(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.jams"
        result = adapter_module.dump(store, out)
        assert result is None
        assert out.exists()
        assert b"chord" in out.read_bytes()

    def test_dump_emits_valid_jams(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.jams"
        adapter_module.dump(store, out, title="demo", artist="thor")
        # jams.load() parses what we wrote
        j = jams_lib.load(str(out), validate=False)
        assert len(j.annotations) == 2
        assert j.file_metadata.title == "demo"
        assert j.file_metadata.artist == "thor"

    def test_dump_computes_duration_from_max_end(self):
        store = _make_store_for_dump()
        blob = adapter_module.dump(store)
        # Re-load and verify duration
        j_path = "/tmp/_lacing_jams_dump_test.jams"
        Path(j_path).write_bytes(blob)
        try:
            j = jams_lib.load(j_path, validate=False)
            assert j.file_metadata.duration == pytest.approx(4.0)
        finally:
            Path(j_path).unlink()

    def test_dump_preserves_confidence(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.jams"
        adapter_module.dump(store, out)
        j = jams_lib.load(str(out), validate=False)
        beats = next(a for a in j.annotations if a.namespace == "beat")
        confidences = [obs.confidence for obs in beats.data]
        assert pytest.approx(0.9) in [c for c in confidences if c is not None]


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_roundtrip_via_path(self, tmp_path):
        original = _make_store_for_dump()
        path = tmp_path / "rt.jams"
        adapter_module.dump(original, path, title="demo")

        loaded = adapter_module.load(path, rate=1000)
        assert len(list(loaded.all())) == len(list(original.all()))

        # Chord values + intervals
        original_chords = sorted(
            (a.body["value"], a.interval.start.value, a.interval.end.value)
            for a in original.by_tier("chord")
        )
        loaded_chords = sorted(
            (a.body["value"], a.interval.start.value, a.interval.end.value)
            for a in loaded.by_tier("chord")
        )
        assert original_chords == loaded_chords

        # Beat values (zero-duration round-trips)
        original_beats = sorted(
            (a.body["value"], a.interval.start.value, a.interval.end.value, a.confidence)
            for a in original.by_tier("beat")
        )
        loaded_beats = sorted(
            (a.body["value"], a.interval.start.value, a.interval.end.value, a.confidence)
            for a in loaded.by_tier("beat")
        )
        assert original_beats == loaded_beats

    def test_roundtrip_via_bytes(self):
        original = _make_store_for_dump()
        blob = adapter_module.dump(original, title="demo")
        loaded = adapter_module.load(blob, rate=1000)
        assert len(list(loaded.all())) == 4


# ---------------------------------------------------------------------------
# top-level dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_load_via_top_level(self, sample_jams_path):
        from lacing.adapters import load as top_load

        store = top_load(sample_jams_path, rate=1000)
        assert len(list(store.all())) == 4

    def test_dump_via_top_level(self, tmp_path):
        from lacing.adapters import dump as top_dump

        out = tmp_path / "out.jams"
        top_dump(_make_store_for_dump(), out, format="jams", title="demo")
        assert out.exists()
