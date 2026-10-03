"""Tests for ``lacing.store.MappingStore`` (persisted to any MutableMapping)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from lacing.allen import AllenRelation
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import (
    JSON_BYTES_CODEC,
    JSON_STR_CODEC,
    IntervalAnnotationStore,
    MappingStore,
    MemoryStore,
)
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


def _dump(store) -> dict:
    return {str(a.id): a.model_dump(mode="json") for a in store.all()}


def test_satisfies_protocol():
    assert isinstance(MappingStore({}), IntervalAnnotationStore)


class TestRoundTrip:
    def test_reopen_sees_annotations_and_tiers(self):
        backing: dict = {}
        s = MappingStore(backing)
        s.add_tier(Tier("words"))
        s.add_tier(Tier("syllables", stereotype=TierStereotype.INCLUDED_IN, parent="words", metadata={"k": 1}))
        a, b = _ann(_ti(0, 10)), _ann(_ti(5, 15), tier="syllables", body={"text": "é", "n": [1, 2]})
        s.extend([a, b])

        again = MappingStore(backing)
        assert _dump(again) == _dump(s)
        assert {t.name for t in again.tiers()} == {"words", "syllables"}
        assert again.get_tier("syllables") == s.get_tier("syllables")
        assert len(backing) == 3  # two annotations + the tiers key

    def test_one_key_per_annotation_is_its_id(self):
        backing: dict = {}
        a = _ann(_ti(0, 10))
        MappingStore(backing).add(a)
        assert list(backing) == [str(a.id)]
        assert backing[str(a.id)]["body"] == {"text": "x"}

    def test_values_are_json_ready(self):
        import json

        backing: dict = {}
        MappingStore(backing).add(_ann(_ti(0, 10)))
        json.dumps(backing)  # no custom types leak into the mapping

    def test_remove_persists(self):
        backing: dict = {}
        s = MappingStore(backing)
        a, b = _ann(_ti(0, 10)), _ann(_ti(0, 10), tier="other")
        s.extend([a, b])
        assert s.remove(a.id) == a
        assert s.remove(a.id) is None
        again = MappingStore(backing)
        assert [x.id for x in again.all()] == [b.id]

    def test_delitem_persists(self):
        backing: dict = {}
        s = MappingStore(backing)
        s.extend([_ann(_ti(0, 10)), _ann(_ti(0, 10)), _ann(_ti(20, 30))])
        del s[_ti(0, 10)]
        assert len(backing) == 1
        assert len(MappingStore(backing)) == 1

    def test_setitem_replaces_and_persists(self):
        backing: dict = {}
        s = MappingStore(backing)
        iv = _ti(0, 10)
        old = _ann(iv)
        s.add(old)
        new = _ann(iv, tier="phonemes")
        s[iv] = [new]
        assert list(backing) == [str(new.id)]
        assert [a.id for a in MappingStore(backing)[iv]] == [new.id]
        s[iv] = []
        assert backing == {}

    def test_zero_length_interval_survives(self):
        backing: dict = {}
        s = MappingStore(backing)
        point = _ann(_ti(5, 5))
        s.add(point)
        assert [a.id for a in MappingStore(backing).intersects(_ti(0, 10))] == [point.id]


class TestQueriesAfterReopen:
    @pytest.mark.parametrize("relation", list(AllenRelation))
    def test_every_relation_matches_memory_store(self, relation):
        anns = [_ann(_ti(s, e)) for s, e in [(0, 10), (2, 5), (5, 12), (10, 20), (0, 5), (5, 10), (-3, 0)]]
        mem = MemoryStore()
        backing: dict = {}
        persisted = MappingStore(backing)
        for a in anns:
            mem.add(a)
            persisted.add(a)
        reopened = MappingStore(backing)
        q = _ti(0, 10)
        want = sorted(str(a.id) for a in mem.relate(q, [relation]))
        assert sorted(str(a.id) for a in reopened.relate(q, [relation])) == want

    def test_tier_queries(self):
        backing: dict = {}
        s = MappingStore(backing)
        s.extend([_ann(_ti(0, 10), tier="a"), _ann(_ti(0, 10), tier="b")])
        r = MappingStore(backing)
        assert len(list(r.by_tier("a"))) == 1
        assert len(list(r.at_tier("b", _ti(5, 6)))) == 1


class TestGuards:
    def test_duplicate_id_raises_and_does_not_persist_twice(self):
        backing: dict = {}
        s = MappingStore(backing)
        a = _ann(_ti(0, 10))
        s.add(a)
        with pytest.raises(ValueError, match="already"):
            s.add(a)
        assert len(MappingStore(backing)) == 1

    def test_setitem_wrong_interval_raises(self):
        s = MappingStore({})
        with pytest.raises(ValueError, match="not the key"):
            s[_ti(0, 10)] = [_ann(_ti(1, 2))]
        assert len(s) == 0

    def test_foreign_key_raises(self):
        with pytest.raises(ValueError, match="foreign key"):
            MappingStore({"README.txt": {}})

    def test_tiers_key_cannot_be_a_uuid(self):
        with pytest.raises(ValueError, match="tiers_key"):
            MappingStore({}, tiers_key=str(uuid4()))

    def test_failed_write_leaves_index_untouched(self):
        class Boom(dict):
            def __setitem__(self, k, v):
                raise OSError("disk full")

        s = MappingStore(Boom())
        with pytest.raises(OSError):
            s.add(_ann(_ti(0, 10)))
        assert len(s) == 0 and list(s.all()) == []
        a = _ann(_ti(0, 10))
        with pytest.raises(OSError):
            s.add(a)  # not wedged by a phantom id


class TestCodecs:
    @pytest.mark.parametrize("codec, typ", [(JSON_BYTES_CODEC, bytes), (JSON_STR_CODEC, str)])
    def test_bytes_and_str_codecs(self, codec, typ):
        backing: dict = {}
        s = MappingStore(backing, codec=codec)
        s.add_tier(Tier("words"))
        a = _ann(_ti(0, 10))
        s.add(a)
        assert all(isinstance(v, typ) for v in backing.values())
        again = MappingStore(backing, codec=codec)
        assert [x.id for x in again.all()] == [a.id]
        assert again.get_tier("words") is not None


class TestDolJsonFiles:
    def test_jsonfiles_over_tmp_path(self, tmp_path):
        dol = pytest.importorskip("dol")
        files = dol.JsonFiles(str(tmp_path))
        s = MappingStore(files)
        s.add_tier(Tier("words"))
        a = _ann(_ti(0, 10))
        s.add(a)
        again = MappingStore(dol.JsonFiles(str(tmp_path)))
        assert [x.id for x in again.intersects(_ti(2, 3))] == [a.id]
        assert again.get_tier("words") is not None
        again.remove(a.id)
        assert len(MappingStore(dol.JsonFiles(str(tmp_path)))) == 0
