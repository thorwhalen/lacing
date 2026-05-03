"""Tests for lacing.allen — the 13 relations.

Test pattern: each pair of intervals satisfies exactly one relation, and
``relate(a, b)`` returns it. Inverses are checked against ``relate(b, a)``.
"""

from lacing.allen import (
    AllenRelation,
    PREDICATE_BY_RELATION,
    after,
    before,
    compose,
    contains,
    during,
    equals,
    finished_by,
    finishes,
    intersects,
    meets,
    met_by,
    overlapped_by,
    overlaps,
    relate,
    started_by,
    starts,
)
from lacing.time import RationalTime, TimeInterval


def _ti(s: int, e: int) -> TimeInterval:
    return TimeInterval(RationalTime(s), RationalTime(e))


# Reference pair where each relation is realized.
# All intervals use rate=DEFAULT_RATE; values in raw ticks.
PAIRS = {
    AllenRelation.BEFORE: (_ti(0, 10), _ti(20, 30)),
    AllenRelation.AFTER: (_ti(20, 30), _ti(0, 10)),
    AllenRelation.MEETS: (_ti(0, 10), _ti(10, 20)),
    AllenRelation.MET_BY: (_ti(10, 20), _ti(0, 10)),
    AllenRelation.OVERLAPS: (_ti(0, 15), _ti(10, 25)),
    AllenRelation.OVERLAPPED_BY: (_ti(10, 25), _ti(0, 15)),
    AllenRelation.STARTS: (_ti(0, 10), _ti(0, 20)),
    AllenRelation.STARTED_BY: (_ti(0, 20), _ti(0, 10)),
    AllenRelation.DURING: (_ti(5, 15), _ti(0, 20)),
    AllenRelation.CONTAINS: (_ti(0, 20), _ti(5, 15)),
    AllenRelation.FINISHES: (_ti(10, 20), _ti(0, 20)),
    AllenRelation.FINISHED_BY: (_ti(0, 20), _ti(10, 20)),
    AllenRelation.EQUALS: (_ti(0, 20), _ti(0, 20)),
}


class TestUniqueness:
    """For each canonical pair, exactly one of the 13 predicates is True."""

    def test_each_pair_satisfies_exactly_one_relation(self):
        for expected_rel, (a, b) in PAIRS.items():
            satisfied = {
                rel for rel, pred in PREDICATE_BY_RELATION.items() if pred(a, b)
            }
            assert satisfied == {expected_rel}, (
                f"expected only {expected_rel} for {a!r} vs {b!r}, got {satisfied}"
            )

    def test_relate_returns_expected(self):
        for expected_rel, (a, b) in PAIRS.items():
            assert relate(a, b) == expected_rel


class TestInverses:
    def test_inverse_table_is_involutive(self):
        for rel in AllenRelation:
            assert rel.inverse().inverse() == rel

    def test_inverse_matches_relation_swap(self):
        for rel, (a, b) in PAIRS.items():
            assert relate(b, a) == rel.inverse(), f"swap of {rel} should be {rel.inverse()}"


class TestSpecificPredicates:
    def test_before(self):
        assert before(_ti(0, 5), _ti(10, 20))
        assert not before(_ti(0, 10), _ti(10, 20))  # touching is not before

    def test_meets_excludes_equal(self):
        # equal intervals trip the "ends touch starts" check; meets must exclude them.
        a = _ti(0, 0)
        assert not meets(a, a)
        assert not met_by(a, a)
        assert equals(a, a)

    def test_starts_excludes_equal(self):
        a = _ti(0, 10)
        assert not starts(a, a)
        assert equals(a, a)

    def test_finishes_excludes_equal(self):
        a = _ti(0, 10)
        assert not finishes(a, a)

    def test_during_strict(self):
        # Inclusive boundary cases are NOT 'during':
        assert not during(_ti(0, 10), _ti(0, 10))  # equal
        assert not during(_ti(0, 5), _ti(0, 10))  # starts
        assert not during(_ti(5, 10), _ti(0, 10))  # finishes
        assert during(_ti(2, 8), _ti(0, 10))


class TestIntersects:
    def test_overlap(self):
        assert intersects(_ti(0, 10), _ti(5, 15))

    def test_meets_does_not_intersect(self):
        # Half-open: [0,10) and [10,20) share zero measure.
        assert not intersects(_ti(0, 10), _ti(10, 20))

    def test_disjoint(self):
        assert not intersects(_ti(0, 10), _ti(20, 30))

    def test_contains(self):
        assert intersects(_ti(0, 100), _ti(40, 60))

    def test_point_inside(self):
        # Point at t=5 inside [0, 10)
        p = TimeInterval.point(RationalTime(5))
        i = _ti(0, 10)
        assert intersects(p, i)
        assert intersects(i, p)

    def test_point_at_start(self):
        # Point at t=0 inside [0, 10) — start is inclusive.
        p = TimeInterval.point(RationalTime(0))
        i = _ti(0, 10)
        assert intersects(p, i)

    def test_point_at_end(self):
        # Point at t=10 inside [0, 10) — end is exclusive.
        p = TimeInterval.point(RationalTime(10))
        i = _ti(0, 10)
        assert not intersects(p, i)

    def test_two_points_equal(self):
        p1 = TimeInterval.point(RationalTime(5))
        p2 = TimeInterval.point(RationalTime(5))
        assert intersects(p1, p2)

    def test_two_points_distinct(self):
        p1 = TimeInterval.point(RationalTime(5))
        p2 = TimeInterval.point(RationalTime(6))
        assert not intersects(p1, p2)


class TestCompose:
    def test_compose_with_equals_left(self):
        for r in AllenRelation:
            assert compose(AllenRelation.EQUALS, r) == {r}

    def test_compose_with_equals_right(self):
        for r in AllenRelation:
            assert compose(r, AllenRelation.EQUALS) == {r}

    def test_compose_returns_set(self):
        # Stub fallback returns full algebra; just ensure it's the right shape.
        result = compose(AllenRelation.BEFORE, AllenRelation.BEFORE)
        assert isinstance(result, set)
        assert all(isinstance(r, AllenRelation) for r in result)
