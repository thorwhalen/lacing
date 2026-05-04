"""Tests for the OpenTimelineIO (OTIO) adapter."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

otio = pytest.importorskip("opentimelineio")

from lacing.adapters import find_adapter, get_adapter  # noqa: E402
from lacing.adapters import otio as adapter_module  # noqa: E402, F401  registers
from lacing.model import Annotation, MediaRef, Provenance  # noqa: E402
from lacing.store import MemoryStore  # noqa: E402
from lacing.tier import Tier  # noqa: E402
from lacing.time import RationalTime, TimeInterval  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_otio_path(tmp_path) -> Path:
    """Build a small OTIO file: timeline with two tracks of clips and a marker."""
    tl = otio.schema.Timeline(name="demo")

    video = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    tl.tracks.append(video)
    clip1 = otio.schema.Clip(
        name="Intro",
        media_reference=otio.schema.ExternalReference(target_url="file://intro.mov"),
        source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, 24),
            duration=otio.opentime.RationalTime(24, 24),  # 1s
        ),
    )
    video.append(clip1)
    clip2 = otio.schema.Clip(
        name="Body",
        media_reference=otio.schema.ExternalReference(target_url="file://body.mov"),
        source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, 24),
            duration=otio.opentime.RationalTime(48, 24),  # 2s
        ),
    )
    video.append(clip2)

    audio = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)
    tl.tracks.append(audio)
    audio_clip = otio.schema.Clip(
        name="Music",
        media_reference=otio.schema.ExternalReference(target_url="file://music.wav"),
        source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, 1000),
            duration=otio.opentime.RationalTime(3000, 1000),  # 3s
        ),
    )
    audio.append(audio_clip)

    # Marker on the second video clip at clip-time t=12 (= track-time 1.5s)
    clip2.markers.append(
        otio.schema.Marker(
            name="cue",
            marked_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(12, 24),
                duration=otio.opentime.RationalTime(0, 24),
            ),
            color=otio.schema.MarkerColor.RED,
        )
    )

    out = tmp_path / "demo.otio"
    otio.adapters.write_to_file(tl, str(out))
    return out


def _make_store_for_dump() -> MemoryStore:
    s = MemoryStore()
    s.add_tier(Tier("V1"))
    s.add_tier(Tier("markers"))
    rate = 1000

    def _clip(start_ms: int, end_ms: int, name: str, asset: str = "file://demo.mov") -> Annotation:
        return Annotation(
            id=uuid4(),
            tier="V1",
            reference=MediaRef(
                asset_id=asset,
                interval=TimeInterval(
                    RationalTime(start_ms, rate), RationalTime(end_ms, rate)
                ),
            ),
            body={"name": name, "kind": "clip"},
            body_schema_uri="annot://schema/otio-clip/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="thor",
                generated_at_time=RationalTime.zero(rate),
            ),
        )

    s.add(_clip(0, 1000, "Intro"))
    s.add(_clip(1000, 3000, "Body"))
    return s


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("otio")
        assert spec.name == "otio"
        assert ".otio" in spec.extensions

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".otio") is not None

    def test_two_body_schema_uris(self):
        spec = get_adapter("otio")
        assert "annot://schema/otio-clip/v1" in spec.body_schema_uris
        assert "annot://schema/otio-marker/v1" in spec.body_schema_uris


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_from_path(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        # 2 video clips + 1 audio clip + 1 marker = 4
        anns = list(store.all())
        assert len(anns) == 4

    def test_creates_track_tiers(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        names = {t.name for t in store.tiers()}
        assert "V1" in names
        assert "A1" in names
        assert "markers" in names

    def test_clip_intervals(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        v1 = sorted(
            store.by_tier("V1"),
            key=lambda a: a.interval.start.to_fraction(),
        )
        # Intro 0-1s, Body 1-3s
        assert v1[0].interval.start.value == 0
        assert v1[0].interval.end.value == 1000
        assert v1[1].interval.start.value == 1000
        assert v1[1].interval.end.value == 3000

    def test_clip_asset_id_from_media_ref(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        intro = next(a for a in store.by_tier("V1") if a.body.get("name") == "Intro")
        assert intro.reference.asset_id == "file://intro.mov"

    def test_marker_is_point_annotation(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        markers = list(store.by_tier("markers"))
        assert len(markers) == 1
        m = markers[0]
        assert m.interval.is_point
        # Marker is at clip-relative t=12/24 = 0.5s; clip starts at track-time 1s.
        # So track-time = 1.0 + 0.5 = 1.5s = 1500 ticks at rate 1000.
        assert m.interval.start.value == 1500

    def test_marker_color(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000)
        m = next(store.by_tier("markers"))
        assert m.body["color"] == "RED"

    def test_provenance(self, sample_otio_path):
        store = adapter_module.load(sample_otio_path, rate=1000, attribution="thor")
        a = next(store.all())
        assert a.provenance.was_generated_by == "adapter:otio"
        assert a.provenance.was_attributed_to == "thor"
        assert a.provenance.activity == "import"

    def test_load_from_bytes(self, sample_otio_path):
        blob = sample_otio_path.read_bytes()
        store = adapter_module.load(blob, rate=1000)
        assert len(list(store.all())) == 4

    def test_asset_id_override(self, sample_otio_path):
        store = adapter_module.load(
            sample_otio_path, rate=1000, asset_id="blake3:hash"
        )
        v1 = next(a for a in store.by_tier("V1"))
        assert v1.reference.asset_id == "blake3:hash"


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


class TestDump:
    def test_dump_returns_bytes(self):
        store = _make_store_for_dump()
        blob = adapter_module.dump(store)
        assert isinstance(blob, bytes)
        assert b"OTIO_SCHEMA" in blob
        assert b"Intro" in blob
        assert b"Body" in blob

    def test_dump_to_path(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.otio"
        result = adapter_module.dump(store, out)
        assert result is None
        assert out.exists()

    def test_dump_emits_valid_otio(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.otio"
        adapter_module.dump(store, out)
        # Re-parse with native otio
        tl = otio.adapters.read_from_file(str(out))
        assert tl.name == "lacing"
        v1 = next(t for t in tl.tracks if t.name == "V1")
        clip_names = [c.name for c in v1.find_clips()]
        assert "Intro" in clip_names
        assert "Body" in clip_names


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_roundtrip_clip_intervals(self, tmp_path):
        original = _make_store_for_dump()
        path = tmp_path / "rt.otio"
        adapter_module.dump(original, path)

        loaded = adapter_module.load(path, rate=1000)
        # Clips on V1 round-trip; markers tier is empty in our dump (no markers in source).
        v1_loaded = sorted(
            (a.body["name"], a.interval.start.value, a.interval.end.value)
            for a in loaded.by_tier("V1")
        )
        v1_orig = sorted(
            (a.body["name"], a.interval.start.value, a.interval.end.value)
            for a in original.by_tier("V1")
        )
        assert v1_loaded == v1_orig


# ---------------------------------------------------------------------------
# top-level dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_load_via_top_level(self, sample_otio_path):
        from lacing.adapters import load as top_load

        store = top_load(sample_otio_path, rate=1000)
        assert len(list(store.all())) == 4

    def test_dump_via_top_level(self, tmp_path):
        from lacing.adapters import dump as top_dump

        out = tmp_path / "out.otio"
        top_dump(_make_store_for_dump(), out, format="otio")
        assert out.exists()
