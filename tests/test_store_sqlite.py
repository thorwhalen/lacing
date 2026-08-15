"""Tests for ``SqliteStore``.

Mirrors ``test_store_memory.py`` so we cover the same shape, plus
SQLite-specific behaviors: persistence, schema versioning, R*Tree
filtering, and from_memory/to_memory round-tripping.
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

from lacing.allen import AllenRelation
from lacing.model import Annotation, AnnotationRef, MediaRef, Provenance
from lacing.store import (
    MemoryStore,
    SchemaMismatchError,
    SqliteStore,
)
from lacing.store.sqlite import SCHEMA_VERSION, from_memory, to_memory
from lacing.tier import Tier, TierStereotype
from lacing.time import RationalTime, TimeInterval


def _ti(s: int, e: int) -> TimeInterval:
    return TimeInterval(RationalTime(s), RationalTime(e))


def _ann(interval: TimeInterval, *, tier: str = "words", body: dict | None = None) -> Annotation:
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(asset_id="blake3:test", interval=interval),
        body=body or {"text": "x"},
        body_schema_uri="annot://schema/word/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime(0),
        ),
    )


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(tmp_path / "test.annot")
    # Tiers must exist before any annotation referencing them.
    s.add_tier(Tier("words"))
    s.add_tier(Tier("phonemes"))
    s.add_tier(Tier("tones"))
    s.add_tier(Tier("speakers"))
    s.add_tier(Tier("comments"))
    s.add_tier(Tier("other"))
    yield s
    s.close()


# --- schema + meta ---------------------------------------------------------


class TestSchema:
    def test_schema_version(self, tmp_path):
        s = SqliteStore(tmp_path / "v.annot")
        try:
            assert s.schema_version == SCHEMA_VERSION
            assert s.get_meta("schema_version") == str(SCHEMA_VERSION)
            assert s.get_meta("created_at") is not None
        finally:
            s.close()

    def test_set_meta(self, tmp_path):
        s = SqliteStore(tmp_path / "m.annot")
        try:
            s.set_meta("project", "demo")
            assert s.get_meta("project") == "demo"
            s.set_meta("project", "demo2")
            assert s.get_meta("project") == "demo2"
        finally:
            s.close()

    def test_in_memory(self):
        s = SqliteStore(":memory:")
        try:
            assert s.schema_version == SCHEMA_VERSION
        finally:
            s.close()

    def test_schema_mismatch_detected(self, tmp_path):
        path = tmp_path / "bad.annot"
        # Build a "valid" file then corrupt the schema_version meta.
        s = SqliteStore(path)
        s.set_meta("schema_version", "999")
        s.close()
        with pytest.raises(SchemaMismatchError):
            SqliteStore(path)


# --- mapping interface ----------------------------------------------------


class TestMapping:
    def test_empty(self, store):
        assert len(store) == 0
        assert list(store) == []

    def test_add_creates_key(self, store):
        store.add(_ann(_ti(0, 10)))
        assert len(store) == 1
        assert _ti(0, 10) in store

    def test_two_at_same_interval(self, store):
        iv = _ti(0, 10)
        store.add(_ann(iv, tier="words"))
        store.add(_ann(iv, tier="phonemes"))
        assert len(store) == 1
        assert len(store[iv]) == 2

    def test_setitem_replaces(self, store):
        iv = _ti(0, 10)
        store.add(_ann(iv))
        store[iv] = [_ann(iv, tier="phonemes")]
        assert len(store[iv]) == 1
        assert store[iv][0].tier == "phonemes"

    def test_setitem_empty_drops_key(self, store):
        iv = _ti(0, 10)
        store.add(_ann(iv))
        store[iv] = []
        assert len(store) == 0

    def test_delitem(self, store):
        iv = _ti(0, 10)
        store.add(_ann(iv))
        del store[iv]
        assert len(store) == 0

    def test_delitem_missing_raises(self, store):
        with pytest.raises(KeyError):
            del store[_ti(0, 1)]

    def test_getitem_missing_raises(self, store):
        with pytest.raises(KeyError):
            store[_ti(0, 1)]

    def test_iter_yields_distinct_intervals(self, store):
        store.add(_ann(_ti(0, 10), tier="words"))
        store.add(_ann(_ti(0, 10), tier="phonemes"))
        store.add(_ann(_ti(20, 30)))
        assert len(list(store)) == 2

    def test_remove_by_id(self, store):
        a = _ann(_ti(0, 10))
        store.add(a)
        removed = store.remove(a.id)
        assert removed.id == a.id
        assert removed.body == a.body
        assert len(store) == 0

    def test_remove_missing_returns_none(self, store):
        assert store.remove(uuid4()) is None


# --- Allen queries --------------------------------------------------------


class TestAllen:
    def _populate(self, store: SqliteStore) -> None:
        store.add(_ann(_ti(0, 10)))    # before query
        store.add(_ann(_ti(15, 25)))   # overlaps query
        store.add(_ann(_ti(30, 40)))   # equals query
        store.add(_ann(_ti(33, 37)))   # during query
        store.add(_ann(_ti(50, 60)))   # after query

    def test_intersects(self, store):
        self._populate(store)
        results = list(store.intersects(_ti(30, 40)))
        assert len(results) == 2

    def test_during(self, store):
        self._populate(store)
        results = list(store.during(_ti(30, 40)))
        assert len(results) == 1
        assert results[0].interval == _ti(33, 37)

    def test_contains(self, store):
        self._populate(store)
        results = list(store.contains(_ti(33, 37)))
        assert len(results) == 1

    def test_equals(self, store):
        self._populate(store)
        results = list(store.equals(_ti(30, 40)))
        assert len(results) == 1

    def test_overlaps_strict(self, store):
        self._populate(store)
        results = list(store.overlaps(_ti(20, 35)))
        assert any(r.interval == _ti(15, 25) for r in results)

    def test_meets(self, store):
        store.add(_ann(_ti(0, 10)))
        results = list(store.meets(_ti(10, 20)))
        assert len(results) == 1

    def test_relate_multi(self, store):
        self._populate(store)
        results = list(
            store.relate(_ti(30, 40), {AllenRelation.DURING, AllenRelation.EQUALS})
        )
        assert len(results) == 2

    def test_relate_only_before_after_uses_scan(self, store):
        # before: [0, 10) is before query [50, 60)
        store.add(_ann(_ti(0, 10)))
        store.add(_ann(_ti(70, 80)))
        results = list(
            store.relate(_ti(50, 60), {AllenRelation.BEFORE, AllenRelation.AFTER})
        )
        assert len(results) == 2

    def test_intersects_does_not_match_meets(self, store):
        # Half-open semantics: [0,10) and [10,20) share zero measure.
        store.add(_ann(_ti(0, 10)))
        results = list(store.intersects(_ti(10, 20)))
        assert results == []


# --- tier registry --------------------------------------------------------


class TestTiers:
    def test_get_added(self, store):
        store.add_tier(Tier("custom"))
        t = store.get_tier("custom")
        assert t is not None
        assert t.name == "custom"

    def test_get_missing(self, store):
        assert store.get_tier("nope") is None

    def test_iter(self, store):
        names = {t.name for t in store.tiers()}
        # The fixture pre-loaded six tiers.
        assert {"words", "phonemes", "tones", "speakers", "comments", "other"} <= names

    def test_with_stereotype(self, tmp_path):
        s = SqliteStore(tmp_path / "stereo.annot")
        try:
            s.add_tier(Tier("words"))
            s.add_tier(Tier("phonemes", stereotype=TierStereotype.TIME_SUBDIVISION, parent="words"))
            t = s.get_tier("phonemes")
            assert t.stereotype == TierStereotype.TIME_SUBDIVISION
            assert t.parent == "words"
        finally:
            s.close()

    def test_metadata_round_trip(self, tmp_path):
        s = SqliteStore(tmp_path / "meta.annot")
        try:
            s.add_tier(Tier("x", metadata={"language": "fr", "bpm": 120}))
            t = s.get_tier("x")
            assert t.metadata == {"language": "fr", "bpm": 120}
        finally:
            s.close()


# --- tier filters ---------------------------------------------------------


class TestTierFilter:
    def test_by_tier(self, store):
        store.add(_ann(_ti(0, 10), tier="words"))
        store.add(_ann(_ti(0, 10), tier="phonemes"))
        store.add(_ann(_ti(20, 30), tier="words"))
        words = list(store.by_tier("words"))
        assert len(words) == 2

    def test_at_tier(self, store):
        store.add(_ann(_ti(0, 10), tier="words"))
        store.add(_ann(_ti(0, 10), tier="phonemes"))
        store.add(_ann(_ti(20, 30), tier="words"))
        results = list(store.at_tier("words", _ti(0, 10)))
        assert len(results) == 1


# --- bulk + persistence ----------------------------------------------------


class TestPersistence:
    def test_extend_inside_transaction(self, store):
        store.extend([_ann(_ti(0, 10)), _ann(_ti(20, 30))])
        assert len(store) == 2

    def test_persists_across_open(self, tmp_path):
        path = tmp_path / "persist.annot"
        s = SqliteStore(path)
        s.add_tier(Tier("words"))
        s.add(_ann(_ti(0, 10)))
        s.close()

        s2 = SqliteStore(path)
        try:
            assert len(s2) == 1
            assert s2.get_tier("words") is not None
        finally:
            s2.close()


# --- annotation references ------------------------------------------------


class TestReferences:
    def test_annotation_ref_with_interval(self, store):
        target = uuid4()
        a = Annotation(
            id=uuid4(),
            tier="comments",
            reference=AnnotationRef(target_id=target, interval=_ti(0, 10)),
            body={"text": "comment"},
            body_schema_uri="annot://schema/comment/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="test",
                generated_at_time=RationalTime(0),
            ),
        )
        store.add(a)
        roundtripped = next(store.all())
        assert isinstance(roundtripped.reference, AnnotationRef)
        assert roundtripped.reference.target_id == target
        assert roundtripped.reference.interval == _ti(0, 10)

    def test_annotation_ref_without_interval_is_timeless(self, store):
        a = Annotation(
            id=uuid4(),
            tier="comments",
            reference=AnnotationRef(target_id=uuid4()),
            body={"text": "general comment"},
            body_schema_uri="annot://schema/comment/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="test",
                generated_at_time=RationalTime(0),
            ),
        )
        store.add(a)
        # Timeless annotations don't show up under interval queries
        # but appear under `all`.
        assert len(list(store.all())) == 1
        assert len(store) == 0
        assert len(list(store.intersects(_ti(0, 1000)))) == 0

    def test_confidence_round_trip(self, store):
        a = _ann(_ti(0, 10))
        a = a.model_copy(update={"confidence": 0.7})
        store.add(a)
        loaded = next(store.all())
        assert loaded.confidence == 0.7


# --- conversion to/from memory --------------------------------------------


class TestConversion:
    def test_from_memory(self, tmp_path):
        mem = MemoryStore()
        mem.add_tier(Tier("words"))
        mem.add_tier(Tier("phonemes", stereotype=TierStereotype.TIME_SUBDIVISION, parent="words"))
        mem.add(_ann(_ti(0, 10), tier="words"))
        mem.add(_ann(_ti(0, 5), tier="phonemes"))
        mem.add(_ann(_ti(5, 10), tier="phonemes"))

        sqlite = from_memory(mem, tmp_path / "from-mem.annot")
        try:
            assert len(list(sqlite.all())) == 3
            t = sqlite.get_tier("phonemes")
            assert t.stereotype == TierStereotype.TIME_SUBDIVISION
        finally:
            sqlite.close()

    def test_to_memory(self, store):
        store.add(_ann(_ti(0, 10)))
        store.add(_ann(_ti(20, 30)))
        mem = to_memory(store)
        assert len(list(mem.all())) == 2

    def test_roundtrip(self, tmp_path):
        original = MemoryStore()
        original.add_tier(Tier("words"))
        original.add(_ann(_ti(0, 10)))
        original.add(_ann(_ti(15, 25)))

        sqlite = from_memory(original, tmp_path / "rt.annot")
        try:
            mem2 = to_memory(sqlite)
        finally:
            sqlite.close()

        original_ivs = sorted(
            (a.interval.start.value, a.interval.end.value, a.tier) for a in original.all()
        )
        loaded_ivs = sorted(
            (a.interval.start.value, a.interval.end.value, a.tier) for a in mem2.all()
        )
        assert original_ivs == loaded_ivs


# --- foreign key enforcement ---------------------------------------------


class TestForeignKeys:
    def test_unknown_tier_rejected(self, tmp_path):
        s = SqliteStore(tmp_path / "fk.annot")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                s.add(_ann(_ti(0, 10), tier="nonexistent"))
        finally:
            s.close()
