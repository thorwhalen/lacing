"""Allen's 13 interval relations as pure predicates.

Public predicate API — never write ad-hoc overlap checks elsewhere in lacing.
See ANN-DOC §A and ``.claude/skills/lacing-time-and-intervals/SKILL.md``.

Convention: intervals are half-open ``[start, end)``. Boundary cases for
``meets``/``met_by`` use exact equality on rational time. Half-open
intervals share zero measure at a boundary, so ``meets`` is NOT an
intersection — see :func:`intersects`.

Relation table (a R b means: a's relation to b is R):

================  ====  =====================================
Relation          Sym.  Predicate (with intervals a, b)
================  ====  =====================================
before            <     a.end < b.start
after             >     a.start > b.end
meets             m     a.end == b.start
met_by            mi    a.start == b.end
overlaps          o     a.start < b.start < a.end < b.end
overlapped_by     oi    b.start < a.start < b.end < a.end
starts            s     a.start == b.start and a.end < b.end
started_by        si    a.start == b.start and a.end > b.end
during            d     a.start > b.start and a.end < b.end
contains          di    a.start < b.start and a.end > b.end
finishes          f     a.start > b.start and a.end == b.end
finished_by       fi    a.start < b.start and a.end == b.end
equals            =     a.start == b.start and a.end == b.end
================  ====  =====================================
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

from lacing.time import TimeInterval


class AllenRelation(str, Enum):
    """The thirteen Allen relations.

    Symbols match Allen (1983); inverse pairs end in ``i``.
    """

    BEFORE = "<"
    AFTER = ">"
    MEETS = "m"
    MET_BY = "mi"
    OVERLAPS = "o"
    OVERLAPPED_BY = "oi"
    STARTS = "s"
    STARTED_BY = "si"
    DURING = "d"
    CONTAINS = "di"
    FINISHES = "f"
    FINISHED_BY = "fi"
    EQUALS = "="

    def inverse(self) -> "AllenRelation":
        """The inverse relation."""
        return _INVERSE[self]


_INVERSE: dict[AllenRelation, AllenRelation] = {
    AllenRelation.BEFORE: AllenRelation.AFTER,
    AllenRelation.AFTER: AllenRelation.BEFORE,
    AllenRelation.MEETS: AllenRelation.MET_BY,
    AllenRelation.MET_BY: AllenRelation.MEETS,
    AllenRelation.OVERLAPS: AllenRelation.OVERLAPPED_BY,
    AllenRelation.OVERLAPPED_BY: AllenRelation.OVERLAPS,
    AllenRelation.STARTS: AllenRelation.STARTED_BY,
    AllenRelation.STARTED_BY: AllenRelation.STARTS,
    AllenRelation.DURING: AllenRelation.CONTAINS,
    AllenRelation.CONTAINS: AllenRelation.DURING,
    AllenRelation.FINISHES: AllenRelation.FINISHED_BY,
    AllenRelation.FINISHED_BY: AllenRelation.FINISHES,
    AllenRelation.EQUALS: AllenRelation.EQUALS,
}


# --- The thirteen predicates --------------------------------------------------


def before(a: TimeInterval, b: TimeInterval) -> bool:
    return a.end < b.start


def after(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start > b.end


def meets(a: TimeInterval, b: TimeInterval) -> bool:
    return a.end == b.start and a != b


def met_by(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start == b.end and a != b


def overlaps(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start < b.start < a.end < b.end


def overlapped_by(a: TimeInterval, b: TimeInterval) -> bool:
    return b.start < a.start < b.end < a.end


def starts(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start == b.start and a.end < b.end


def started_by(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start == b.start and a.end > b.end


def during(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start > b.start and a.end < b.end


def contains(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start < b.start and a.end > b.end


def finishes(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start > b.start and a.end == b.end


def finished_by(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start < b.start and a.end == b.end


def equals(a: TimeInterval, b: TimeInterval) -> bool:
    return a.start == b.start and a.end == b.end


# --- Aggregate predicates ----------------------------------------------------


def intersects(a: TimeInterval, b: TimeInterval) -> bool:
    """True iff ``a`` and ``b`` share any positive measure of time.

    ``meets``/``met_by`` are NOT intersections (half-open boundaries share
    zero measure). Two zero-length point intervals at the same instant DO
    intersect (they're equal).
    """
    if a.is_point and b.is_point:
        return a.start == b.start
    if a.is_point:
        return b.start <= a.start < b.end
    if b.is_point:
        return a.start <= b.start < a.end
    return a.start < b.end and b.start < a.end


PREDICATE_BY_RELATION: dict[AllenRelation, Callable[[TimeInterval, TimeInterval], bool]] = {
    AllenRelation.BEFORE: before,
    AllenRelation.AFTER: after,
    AllenRelation.MEETS: meets,
    AllenRelation.MET_BY: met_by,
    AllenRelation.OVERLAPS: overlaps,
    AllenRelation.OVERLAPPED_BY: overlapped_by,
    AllenRelation.STARTS: starts,
    AllenRelation.STARTED_BY: started_by,
    AllenRelation.DURING: during,
    AllenRelation.CONTAINS: contains,
    AllenRelation.FINISHES: finishes,
    AllenRelation.FINISHED_BY: finished_by,
    AllenRelation.EQUALS: equals,
}
"""Lookup table — used by ``IntervalAnnotationStore`` to dispatch by relation."""


def relate(a: TimeInterval, b: TimeInterval) -> AllenRelation:
    """Return the unique Allen relation between two well-formed intervals.

    Exactly one of the 13 relations holds for any pair of well-formed
    (``start <= end``) intervals.

    Caveat: when both ``a`` and ``b`` are point intervals (zero-length),
    ``meets`` and ``met_by`` would both technically apply alongside ``equals``.
    We resolve that by preferring ``equals`` for identical intervals; the
    ``meets``/``met_by`` predicates exclude ``a == b`` accordingly.
    """
    for rel, pred in PREDICATE_BY_RELATION.items():
        if pred(a, b):
            return rel
    raise RuntimeError(  # pragma: no cover  — unreachable for well-formed intervals
        f"no Allen relation matched for a={a!r}, b={b!r}"
    )


# --- Composition table -------------------------------------------------------
#
# Allen's composition: given (a R1 b) and (b R2 c), what set of relations is
# possible between a and c?  We don't ship the full 13×13 table in Phase 0 —
# the doc only requires Phase 5 to expose the algebra fully (ANN-DOC §A,
# ORD-Horn tractable subalgebra). The function exists with a stub-but-correct
# fallback (the universal set) so callers can be written today.


_ALL_RELATIONS: frozenset[AllenRelation] = frozenset(AllenRelation)


def compose(r1: AllenRelation, r2: AllenRelation) -> set[AllenRelation]:
    """Allen's composition. See module docstring.

    Phase 0 returns the universal set (all 13 relations) for any pair where
    a unique answer is not encoded — correct but uninformative. The full
    table lands in Phase 5; this function is a stable surface for callers
    written against it now.
    """
    # A few obvious singletons cost nothing and demo the API:
    if r1 == AllenRelation.EQUALS:
        return {r2}
    if r2 == AllenRelation.EQUALS:
        return {r1}
    return set(_ALL_RELATIONS)
