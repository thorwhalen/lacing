"""Tests for lacing.store.memory.MemoryStore."""

from uuid import uuid4

import pytest

from lacing.allen import AllenRelation
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore
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


class TestMappingInterface:
    def test_empty_store(self):
        s = MemoryStore()
        assert len(s) == 0
        assert list(s) == []

    def test_add_creates_key(self):
        s = MemoryStore()
        a = _ann(_ti(0, 10))
        s.add(a)
        assert len(s) == 1
        assert _ti(0, 10) in s

    def test_two_at_same_interval(self):
        s = MemoryStore()
        iv = _ti(0, 10)
        s.add(_ann(iv, tier="words"))
        s.add(_ann(iv, tier="phonemes"))
        assert len(s) == 1  # one key, two values
        assert len(s[iv]) == 2

    def test_setitem_replaces(self):
        s = MemoryStore()
        iv = _ti(0, 10)
        s.add(_ann(iv))
        s[iv] = [_ann(iv, tier="phonemes")]
        assert len(s[iv]) == 1
        assert s[iv][0].tier == "phonemes"

    def test_setitem_empty_drops_key(self):
        s = MemoryStore()
        iv = _ti(0, 10)
        s.add(_ann(iv))
        s[iv] = []
        assert len(s) == 0

    def test_delitem(self):
        s = MemoryStore()
        iv = _ti(0, 10)
        s.add(_ann(iv))
        del s[iv]
        assert len(s) == 0

    def test_delitem_missing_raises(self):
        s = MemoryStore()
        with pytest.raises(KeyError):
            del s[_ti(0, 1)]

    def test_getitem_missing_raises(self):
        s = MemoryStore()
        with pytest.raises(KeyError):
            s[_ti(0, 1)]

    def test_iter_yields_distinct_intervals(self):
        s = MemoryStore()
        s.add(_ann(_ti(0, 10)))
        s.add(_ann(_ti(0, 10), tier="phonemes"))
        s.add(_ann(_ti(20, 30)))
        intervals = list(s)
        assert len(intervals) == 2

    def test_remove_by_id(self):
        s = MemoryStore()
        iv = _ti(0, 10)
        a = _ann(iv)
        s.add(a)
        removed = s.remove(a.id)
        assert removed == a
        assert len(s) == 0

    def test_remove_missing_returns_none(self):
        s = MemoryStore()
        assert s.remove(uuid4()) is None


class TestAllenQueries:
    def _setup(self) -> MemoryStore:
        s = MemoryStore()
        s.add(_ann(_ti(0, 10)))  # before query
        s.add(_ann(_ti(15, 25)))  # overlaps query
        s.add(_ann(_ti(30, 40)))  # equals query
        s.add(_ann(_ti(33, 37)))  # during query
        s.add(_ann(_ti(50, 60)))  # after query
        return s

    def test_intersects(self):
        s = self._setup()
        query = _ti(30, 40)
        results = list(s.intersects(query))
        # equals + during = 2 annotations
        assert len(results) == 2

    def test_during(self):
        s = self._setup()
        results = list(s.during(_ti(30, 40)))
        assert len(results) == 1
        assert results[0].interval == _ti(33, 37)

    def test_contains(self):
        s = self._setup()
        results = list(s.contains(_ti(33, 37)))
        assert len(results) == 1
        assert results[0].interval == _ti(30, 40)

    def test_equals(self):
        s = self._setup()
        results = list(s.equals(_ti(30, 40)))
        assert len(results) == 1

    def test_overlaps_strict(self):
        s = self._setup()
        results = list(s.overlaps(_ti(20, 35)))
        # _ti(15, 25) overlaps [20, 35) → start<query.start<end<query.end
        assert any(r.interval == _ti(15, 25) for r in results)

    def test_meets(self):
        s = MemoryStore()
        s.add(_ann(_ti(0, 10)))
        results = list(s.meets(_ti(10, 20)))
        assert len(results) == 1

    def test_relate_with_multiple(self):
        s = self._setup()
        results = list(
            s.relate(
                _ti(30, 40),
                {AllenRelation.DURING, AllenRelation.EQUALS},
            )
        )
        assert len(results) == 2  # the equal one + the during one


class TestTierRegistry:
    def test_add_and_get(self):
        s = MemoryStore()
        t = Tier("words")
        s.add_tier(t)
        assert s.get_tier("words") == t

    def test_get_missing(self):
        s = MemoryStore()
        assert s.get_tier("missing") is None

    def test_iter_tiers(self):
        s = MemoryStore()
        s.add_tier(Tier("words"))
        s.add_tier(Tier("phonemes", stereotype=TierStereotype.TIME_SUBDIVISION, parent="words"))
        names = {t.name for t in s.tiers()}
        assert names == {"words", "phonemes"}


class TestTierFilter:
    def test_by_tier(self):
        s = MemoryStore()
        s.add(_ann(_ti(0, 10), tier="words"))
        s.add(_ann(_ti(0, 10), tier="phonemes"))
        s.add(_ann(_ti(20, 30), tier="words"))
        words = list(s.by_tier("words"))
        assert len(words) == 2

    def test_at_tier(self):
        s = MemoryStore()
        s.add(_ann(_ti(0, 10), tier="words"))
        s.add(_ann(_ti(0, 10), tier="phonemes"))
        s.add(_ann(_ti(20, 30), tier="words"))
        results = list(s.at_tier("words", _ti(0, 10)))
        assert len(results) == 1


class TestBulkAndIteration:
    def test_extend(self):
        s = MemoryStore()
        s.extend([_ann(_ti(0, 10)), _ann(_ti(20, 30))])
        assert len(s) == 2

    def test_all_includes_timeless(self):
        # Phase 0: every Annotation we build has a MediaRef interval, but
        # AnnotationRef without a sub-interval is "timeless" in the store.
        from lacing.model import AnnotationRef

        s = MemoryStore()
        s.add(_ann(_ti(0, 10)))
        s.add(
            Annotation(
                id=uuid4(),
                tier="comments",
                reference=AnnotationRef(target_id=uuid4()),
                body={"text": "what about this?"},
                body_schema_uri="annot://schema/comment/v1",
                provenance=Provenance(
                    was_generated_by="user:test",
                    was_attributed_to="test",
                    generated_at_time=RationalTime(0),
                ),
            )
        )
        assert len(list(s.all())) == 2
        # but only one shows up under interval queries
        assert len(list(s.intersects(_ti(0, 10)))) == 1
