"""Tests for the Praat TextGrid adapter.

Skipped if ``praatio`` is not installed.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

praatio = pytest.importorskip("praatio")

from lacing.adapters import find_adapter, get_adapter, registered  # noqa: E402
from lacing.adapters import textgrid as adapter_module  # noqa: E402, F401  registers
from lacing.model import Annotation, MediaRef, Provenance  # noqa: E402
from lacing.store import MemoryStore  # noqa: E402
from lacing.tier import Tier  # noqa: E402
from lacing.time import RationalTime, TimeInterval  # noqa: E402


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def sample_textgrid_path(tmp_path) -> Path:
    """Build a small TextGrid on disk using praatio directly.

    Two tiers: ``words`` (interval) + ``tones`` (point), times exact at rate 1000.
    """
    from praatio.data_classes.interval_tier import IntervalTier
    from praatio.data_classes.point_tier import PointTier
    from praatio.data_classes.textgrid import Textgrid
    from praatio.utilities.constants import Interval, Point

    grid = Textgrid(minTimestamp=0.0, maxTimestamp=1.0)
    grid.addTier(
        IntervalTier(
            "words",
            [Interval(0.0, 0.5, "hello"), Interval(0.5, 1.0, "world")],
            minT=0.0,
            maxT=1.0,
        )
    )
    grid.addTier(
        PointTier(
            "tones",
            [Point(0.25, "H"), Point(0.75, "L")],
            minT=0.0,
            maxT=1.0,
        )
    )
    out = tmp_path / "sample.TextGrid"
    grid.save(str(out), format="long_textgrid", includeBlankSpaces=True)
    return out


def _make_store_for_dump() -> MemoryStore:
    """Build a store with intervals + points across two tiers."""
    s = MemoryStore()
    s.add_tier(Tier("words"))
    s.add_tier(Tier("tones"))
    rate = 1000  # exact for the sample times below

    def _ann(tier: str, interval: TimeInterval, text: str) -> Annotation:
        return Annotation(
            id=uuid4(),
            tier=tier,
            reference=MediaRef(asset_id="textgrid:sample", interval=interval),
            body={"text": text},
            body_schema_uri="annot://schema/textgrid-label/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="test",
                generated_at_time=RationalTime.zero(rate),
            ),
        )

    s.add(_ann("words", TimeInterval.from_seconds("0.0", "0.5", rate=rate), "hello"))
    s.add(_ann("words", TimeInterval.from_seconds("0.5", "1.0", rate=rate), "world"))
    s.add(_ann("tones", TimeInterval.point(RationalTime.from_seconds("0.25", rate)), "H"))
    s.add(_ann("tones", TimeInterval.point(RationalTime.from_seconds("0.75", rate)), "L"))
    return s


# --- registry --------------------------------------------------------------


class TestRegistry:
    def test_textgrid_registered(self):
        spec = get_adapter("textgrid")
        assert spec.name == "textgrid"
        assert ".textgrid" in spec.extensions

    def test_extension_lookup_case_insensitive(self):
        assert find_adapter(extension=".TextGrid") is not None
        assert find_adapter(extension=".textgrid") is not None
        assert find_adapter(extension="TextGrid") is not None  # no leading dot

    def test_unknown_format(self):
        assert find_adapter(extension=".bogus") is None

    def test_textgrid_in_registered_list(self):
        names = {s.name for s in registered()}
        assert "textgrid" in names


# --- load ------------------------------------------------------------------


class TestLoad:
    def test_load_from_path(self, sample_textgrid_path):
        store = adapter_module.load(sample_textgrid_path, rate=1000)
        # 2 words + 2 tones
        assert len(list(store.all())) == 4

    def test_load_creates_tiers(self, sample_textgrid_path):
        store = adapter_module.load(sample_textgrid_path, rate=1000)
        names = {t.name for t in store.tiers()}
        assert names == {"words", "tones"}

    def test_load_interval_tier_annotations(self, sample_textgrid_path):
        store = adapter_module.load(sample_textgrid_path, rate=1000)
        words = sorted(
            store.by_tier("words"),
            key=lambda a: a.interval.start.to_fraction(),
        )
        assert len(words) == 2
        assert words[0].body["text"] == "hello"
        assert words[1].body["text"] == "world"
        assert not words[0].interval.is_point
        # rate=1000: 0.5s = 500 ticks
        assert words[0].interval.end.value == 500

    def test_load_point_tier_annotations(self, sample_textgrid_path):
        store = adapter_module.load(sample_textgrid_path, rate=1000)
        tones = sorted(
            store.by_tier("tones"),
            key=lambda a: a.interval.start.to_fraction(),
        )
        assert len(tones) == 2
        assert tones[0].body["text"] == "H"
        assert tones[0].interval.is_point
        assert tones[1].body["text"] == "L"

    def test_load_provenance(self, sample_textgrid_path):
        store = adapter_module.load(
            sample_textgrid_path, rate=1000, attribution="thor"
        )
        a = next(store.all())
        assert a.provenance.was_generated_by == "adapter:textgrid"
        assert a.provenance.was_attributed_to == "thor"
        assert a.provenance.activity == "import"

    def test_load_from_bytes(self, sample_textgrid_path):
        blob = sample_textgrid_path.read_bytes()
        store = adapter_module.load(blob, rate=1000)
        assert len(list(store.all())) == 4


# --- dump ------------------------------------------------------------------


class TestDump:
    def test_dump_returns_bytes(self):
        store = _make_store_for_dump()
        blob = adapter_module.dump(store)
        assert isinstance(blob, bytes)
        assert b"IntervalTier" in blob
        assert b"TextTier" in blob

    def test_dump_to_path(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.TextGrid"
        result = adapter_module.dump(store, out)
        assert result is None
        assert out.exists()
        assert b"hello" in out.read_bytes()


# --- round trip -------------------------------------------------------------


class TestRoundTrip:
    def test_roundtrip_via_path(self, tmp_path):
        original = _make_store_for_dump()
        path = tmp_path / "rt.TextGrid"
        adapter_module.dump(original, path)

        loaded = adapter_module.load(path, rate=1000)

        # same count
        assert len(list(loaded.all())) == len(list(original.all())) == 4

        # words round-trip
        loaded_words = sorted(
            (a.body["text"], a.interval.start.value, a.interval.end.value)
            for a in loaded.by_tier("words")
        )
        original_words = sorted(
            (a.body["text"], a.interval.start.value, a.interval.end.value)
            for a in original.by_tier("words")
        )
        assert loaded_words == original_words

        # tones round-trip
        loaded_tones = sorted(
            (a.body["text"], a.interval.start.value)
            for a in loaded.by_tier("tones")
        )
        original_tones = sorted(
            (a.body["text"], a.interval.start.value)
            for a in original.by_tier("tones")
        )
        assert loaded_tones == original_tones

    def test_roundtrip_through_bytes(self):
        original = _make_store_for_dump()
        blob = adapter_module.dump(original)
        loaded = adapter_module.load(blob, rate=1000)
        assert len(list(loaded.all())) == 4
        assert {a.body["text"] for a in loaded.all()} == {"hello", "world", "H", "L"}


# --- top-level convenience -------------------------------------------------


class TestTopLevelDispatch:
    def test_load_dispatches_by_extension(self, sample_textgrid_path):
        from lacing.adapters import load as top_load

        store = top_load(sample_textgrid_path, rate=1000)
        assert len(list(store.all())) == 4

    def test_load_dispatches_by_format(self, sample_textgrid_path):
        from lacing.adapters import load as top_load

        store = top_load(sample_textgrid_path, format="textgrid", rate=1000)
        assert len(list(store.all())) == 4

    def test_load_unknown_extension_raises(self, tmp_path):
        from lacing.adapters import load as top_load

        bogus = tmp_path / "x.bogus"
        bogus.write_text("hi")
        with pytest.raises(ValueError):
            top_load(bogus)

    def test_dump_via_format(self, tmp_path):
        from lacing.adapters import dump as top_dump

        out = tmp_path / "out.TextGrid"
        top_dump(_make_store_for_dump(), out, format="textgrid")
        assert out.exists()
