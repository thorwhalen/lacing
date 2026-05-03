"""Tests for the ELAN EAF adapter.

Skipped if ``pympi-ling`` is not installed.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

pympi = pytest.importorskip("pympi")

from lacing.adapters import find_adapter, get_adapter  # noqa: E402
from lacing.adapters import eaf as adapter_module  # noqa: E402, F401  registers
from lacing.model import Annotation, MediaRef, Provenance  # noqa: E402
from lacing.store import MemoryStore  # noqa: E402
from lacing.tier import Tier, TierStereotype  # noqa: E402
from lacing.time import RationalTime, TimeInterval  # noqa: E402


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def sample_eaf_path(tmp_path) -> Path:
    """Build a small EAF on disk via pympi.

    Two tiers: ``words`` (NONE) + ``phonemes`` (TIME_SUBDIVISION child of words).
    Times in milliseconds.
    """
    from pympi import Eaf

    eaf = Eaf(suppress_version_warning=True)
    eaf.remove_tier("default")
    eaf.add_linguistic_type("lt_words", constraints=None)
    eaf.add_linguistic_type("lt_phon", constraints="Time_Subdivision")
    eaf.add_tier("words", ling="lt_words")
    eaf.add_tier("phonemes", ling="lt_phon", parent="words")
    eaf.add_annotation("words", 0, 1000, "hello")
    eaf.add_annotation("phonemes", 0, 500, "he")
    eaf.add_annotation("phonemes", 500, 1000, "llo")

    out = tmp_path / "sample.eaf"
    eaf.to_file(str(out))
    return out


def _make_store_for_dump() -> MemoryStore:
    s = MemoryStore()
    s.add_tier(Tier("words"))
    s.add_tier(
        Tier("phonemes", stereotype=TierStereotype.TIME_SUBDIVISION, parent="words")
    )
    s.add_tier(
        Tier("translation", stereotype=TierStereotype.SYMBOLIC_ASSOCIATION, parent="words")
    )

    def _ann(tier: str, start_ms: int, end_ms: int, text: str) -> Annotation:
        return Annotation(
            id=uuid4(),
            tier=tier,
            reference=MediaRef(
                asset_id="file://sample.wav",
                interval=TimeInterval(
                    RationalTime(start_ms, 1000),
                    RationalTime(end_ms, 1000),
                ),
            ),
            body={"text": text},
            body_schema_uri="annot://schema/eaf-label/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="test",
                generated_at_time=RationalTime.zero(1000),
            ),
        )

    s.add(_ann("words", 0, 1000, "hello"))
    s.add(_ann("phonemes", 0, 500, "he"))
    s.add(_ann("phonemes", 500, 1000, "llo"))
    s.add(_ann("translation", 0, 1000, "salut"))
    return s


# --- registry --------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("eaf")
        assert spec.name == "eaf"
        assert ".eaf" in spec.extensions

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".eaf") is not None

    def test_lookup_by_media_type(self):
        assert find_adapter(media_type="application/x-eaf+xml") is not None


# --- load ------------------------------------------------------------------


class TestLoad:
    def test_load_from_path(self, sample_eaf_path):
        store = adapter_module.load(sample_eaf_path, rate=1000)
        # 1 word + 2 phonemes = 3 annotations (default tier filtered)
        assert len(list(store.all())) == 3

    def test_load_creates_tiers(self, sample_eaf_path):
        store = adapter_module.load(sample_eaf_path, rate=1000)
        names = {t.name for t in store.tiers()}
        assert names == {"words", "phonemes"}

    def test_load_preserves_stereotype(self, sample_eaf_path):
        store = adapter_module.load(sample_eaf_path, rate=1000)
        phon = store.get_tier("phonemes")
        assert phon is not None
        assert phon.stereotype == TierStereotype.TIME_SUBDIVISION
        assert phon.parent == "words"

    def test_load_root_tier_has_none_stereotype(self, sample_eaf_path):
        store = adapter_module.load(sample_eaf_path, rate=1000)
        words = store.get_tier("words")
        assert words is not None
        assert words.stereotype == TierStereotype.NONE
        assert words.parent is None

    def test_load_intervals_in_ms(self, sample_eaf_path):
        store = adapter_module.load(sample_eaf_path, rate=1000)
        words = sorted(
            store.by_tier("words"),
            key=lambda a: a.interval.start.to_fraction(),
        )
        assert len(words) == 1
        assert words[0].interval.start.value == 0
        assert words[0].interval.end.value == 1000
        assert words[0].body["text"] == "hello"

    def test_load_provenance(self, sample_eaf_path):
        store = adapter_module.load(sample_eaf_path, rate=1000, attribution="thor")
        a = next(store.all())
        assert a.provenance.was_generated_by == "adapter:eaf"
        assert a.provenance.was_attributed_to == "thor"
        assert a.provenance.activity == "import"

    def test_load_from_bytes(self, sample_eaf_path):
        blob = sample_eaf_path.read_bytes()
        store = adapter_module.load(blob, rate=1000)
        assert len(list(store.all())) == 3

    def test_default_tier_filtered(self, sample_eaf_path):
        # The pympi default tier never has annotations; we filter it.
        store = adapter_module.load(sample_eaf_path, rate=1000)
        assert "default" not in {t.name for t in store.tiers()}

    def test_asset_id_override(self, sample_eaf_path):
        store = adapter_module.load(sample_eaf_path, rate=1000, asset_id="blake3:hash")
        a = next(store.all())
        assert a.reference.asset_id == "blake3:hash"


class TestLoadStereotypes:
    def _make_eaf_with_stereotype(self, tmp_path, name: str, constraint: str):
        from pympi import Eaf

        eaf = Eaf(suppress_version_warning=True)
        eaf.remove_tier("default")
        eaf.add_linguistic_type("lt_parent", constraints=None)
        eaf.add_linguistic_type("lt_child", constraints=constraint)
        eaf.add_tier("parent", ling="lt_parent")
        eaf.add_tier("child", ling="lt_child", parent="parent")
        eaf.add_annotation("parent", 0, 1000, "p")
        eaf.add_annotation("child", 0, 500, "c1")
        path = tmp_path / f"{name}.eaf"
        eaf.to_file(str(path))
        return path

    def test_included_in(self, tmp_path):
        path = self._make_eaf_with_stereotype(tmp_path, "included", "Included_In")
        store = adapter_module.load(path, rate=1000)
        assert store.get_tier("child").stereotype == TierStereotype.INCLUDED_IN

    def test_symbolic_subdivision(self, tmp_path):
        path = self._make_eaf_with_stereotype(
            tmp_path, "symsub", "Symbolic_Subdivision"
        )
        store = adapter_module.load(path, rate=1000)
        assert store.get_tier("child").stereotype == TierStereotype.SYMBOLIC_SUBDIVISION

    def test_symbolic_association(self, tmp_path):
        path = self._make_eaf_with_stereotype(
            tmp_path, "symassoc", "Symbolic_Association"
        )
        store = adapter_module.load(path, rate=1000)
        assert store.get_tier("child").stereotype == TierStereotype.SYMBOLIC_ASSOCIATION


# --- dump ------------------------------------------------------------------


class TestDump:
    def test_dump_returns_bytes(self):
        store = _make_store_for_dump()
        blob = adapter_module.dump(store)
        assert isinstance(blob, bytes)
        assert b"<?xml" in blob
        assert b"ANNOTATION_DOCUMENT" in blob

    def test_dump_to_path(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.eaf"
        adapter_module.dump(store, out)
        assert out.exists()
        assert b"hello" in out.read_bytes()
        assert b"phonemes" in out.read_bytes()

    def test_dump_includes_stereotype_constraint(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.eaf"
        adapter_module.dump(store, out)
        text = out.read_text()
        # phonemes uses TIME_SUBDIVISION
        assert "Time_Subdivision" in text
        # translation uses SYMBOLIC_ASSOCIATION
        assert "Symbolic_Association" in text

    def test_dump_preserves_tier_parent(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.eaf"
        adapter_module.dump(store, out)
        text = out.read_text()
        # phonemes tier should declare PARENT_REF="words"
        assert 'PARENT_REF="words"' in text


# --- round trip ------------------------------------------------------------


class TestRoundTrip:
    def test_roundtrip_via_path(self, tmp_path):
        original = _make_store_for_dump()
        path = tmp_path / "rt.eaf"
        adapter_module.dump(original, path)

        loaded = adapter_module.load(path, rate=1000)

        assert len(list(loaded.all())) == len(list(original.all()))

        # Stereotypes preserved
        loaded_phon = loaded.get_tier("phonemes")
        assert loaded_phon.stereotype == TierStereotype.TIME_SUBDIVISION
        assert loaded_phon.parent == "words"

        loaded_trans = loaded.get_tier("translation")
        assert loaded_trans.stereotype == TierStereotype.SYMBOLIC_ASSOCIATION

        # Words round-trip
        loaded_words = sorted(
            (a.body["text"], a.interval.start.value, a.interval.end.value)
            for a in loaded.by_tier("words")
        )
        original_words = sorted(
            (a.body["text"], a.interval.start.value, a.interval.end.value)
            for a in original.by_tier("words")
        )
        assert loaded_words == original_words

        # Phonemes round-trip
        loaded_phons = sorted(
            (a.body["text"], a.interval.start.value, a.interval.end.value)
            for a in loaded.by_tier("phonemes")
        )
        original_phons = sorted(
            (a.body["text"], a.interval.start.value, a.interval.end.value)
            for a in original.by_tier("phonemes")
        )
        assert loaded_phons == original_phons

    def test_roundtrip_through_bytes(self):
        original = _make_store_for_dump()
        blob = adapter_module.dump(original)
        loaded = adapter_module.load(blob, rate=1000)
        assert len(list(loaded.all())) == 4
        names = {a.body["text"] for a in loaded.all()}
        assert names == {"hello", "he", "llo", "salut"}


# --- top-level dispatch ----------------------------------------------------


class TestDispatch:
    def test_load_via_top_level(self, sample_eaf_path):
        from lacing.adapters import load as top_load

        store = top_load(sample_eaf_path, rate=1000)
        assert len(list(store.all())) == 3

    def test_dump_via_top_level(self, tmp_path):
        from lacing.adapters import dump as top_dump

        out = tmp_path / "out.eaf"
        top_dump(_make_store_for_dump(), out, format="eaf")
        assert out.exists()
