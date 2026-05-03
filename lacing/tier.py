"""Tiers and the five ELAN stereotypes.

A tier is a named layer of annotations. Stereotypes constrain how a tier
relates to its parent. We adopt ELAN's five stereotypes verbatim — see
ANN-DOC §C and OSS-DOC tier-2.4.
"""

from __future__ import annotations

from enum import Enum

from lacing.time import TimeInterval


class TierStereotype(str, Enum):
    """Constraints on how a child tier relates to its parent tier.

    Names match ELAN exactly so EAF round-trips are trivial.
    """

    NONE = "NONE"
    """No parent constraint. Top-level tier."""

    TIME_SUBDIVISION = "TIME_SUBDIVISION"
    """Children fully partition the parent's interval (no gaps, no overlap)."""

    INCLUDED_IN = "INCLUDED_IN"
    """Children lie within the parent but gaps between siblings are allowed."""

    SYMBOLIC_SUBDIVISION = "SYMBOLIC_SUBDIVISION"
    """Ordered subdivision; children share parent's interval as a sequence (no times)."""

    SYMBOLIC_ASSOCIATION = "SYMBOLIC_ASSOCIATION"
    """One-to-one association with parent; child shares parent's interval exactly."""


class Tier:
    """A named annotation layer with optional parent and stereotype.

    Tiers are pure metadata; they don't own annotations. The store is keyed
    by interval, not by tier — annotations carry their tier name as a field.
    This matches ELAN's TIME_ORDER indirection (see ANN-DOC §C).
    """

    __slots__ = ("_name", "_stereotype", "_parent", "_metadata")

    def __init__(
        self,
        name: str,
        *,
        stereotype: TierStereotype = TierStereotype.NONE,
        parent: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(stereotype, TierStereotype):
            raise TypeError(
                f"stereotype must be a TierStereotype, got {type(stereotype).__name__}"
            )
        if parent is not None and not isinstance(parent, str):
            raise TypeError(f"parent must be str or None, got {type(parent).__name__}")
        if stereotype != TierStereotype.NONE and parent is None:
            raise ValueError(f"stereotype {stereotype.value} requires a parent tier")
        if stereotype == TierStereotype.NONE and parent is not None:
            raise ValueError("stereotype NONE cannot have a parent tier")
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_stereotype", stereotype)
        object.__setattr__(self, "_parent", parent)
        object.__setattr__(self, "_metadata", dict(metadata or {}))

    @property
    def name(self) -> str:
        return self._name

    @property
    def stereotype(self) -> TierStereotype:
        return self._stereotype

    @property
    def parent(self) -> str | None:
        return self._parent

    @property
    def metadata(self) -> dict:
        # Defensive copy — Tier is intended to be value-like.
        return dict(self._metadata)

    def to_wire(self) -> dict:
        d: dict = {
            "name": self._name,
            "stereotype": self._stereotype.value,
        }
        if self._parent is not None:
            d["parent"] = self._parent
        if self._metadata:
            d["metadata"] = dict(self._metadata)
        return d

    @classmethod
    def from_wire(cls, d: dict) -> "Tier":
        return cls(
            d["name"],
            stereotype=TierStereotype(d.get("stereotype", "NONE")),
            parent=d.get("parent"),
            metadata=d.get("metadata"),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Tier):
            return NotImplemented
        return (
            self._name == other._name
            and self._stereotype == other._stereotype
            and self._parent == other._parent
            and self._metadata == other._metadata
        )

    def __hash__(self) -> int:
        return hash((self._name, self._stereotype, self._parent))

    def __repr__(self) -> str:
        return (
            f"Tier({self._name!r}, stereotype={self._stereotype.value}, "
            f"parent={self._parent!r})"
        )


def validate_tier_constraint(
    parent: Tier | None,
    child: Tier,
    parent_intervals: list[TimeInterval],
    child_intervals: list[TimeInterval],
) -> list[str]:
    """Check that ``child_intervals`` satisfy ``child.stereotype`` against ``parent_intervals``.

    Returns a list of violation messages (empty list = valid). Pure function;
    callers decide whether to raise, log, or surface in UI.

    Lives here rather than on ``Tier`` so the constraint logic is testable
    in isolation and reusable from server validators and UI plugins alike.
    """
    violations: list[str] = []

    if child.stereotype == TierStereotype.NONE:
        if parent is not None:
            violations.append(
                f"tier {child.name!r} has stereotype NONE but parent={parent.name!r}"
            )
        return violations

    if parent is None:
        violations.append(
            f"tier {child.name!r} stereotype {child.stereotype.value} requires a parent"
        )
        return violations

    if child.parent != parent.name:
        violations.append(
            f"tier {child.name!r} declares parent={child.parent!r} "
            f"but was validated against parent={parent.name!r}"
        )

    if child.stereotype == TierStereotype.INCLUDED_IN:
        for ci in child_intervals:
            if not any(
                pi.start <= ci.start and ci.end <= pi.end for pi in parent_intervals
            ):
                violations.append(
                    f"child interval {ci!r} is not contained in any parent interval"
                )

    elif child.stereotype == TierStereotype.SYMBOLIC_ASSOCIATION:
        # 1-1 with parent; child shares parent's interval exactly.
        if len(child_intervals) != len(parent_intervals):
            violations.append(
                f"SYMBOLIC_ASSOCIATION expects {len(parent_intervals)} child "
                f"intervals to match parent count, got {len(child_intervals)}"
            )
        else:
            for pi, ci in zip(parent_intervals, child_intervals):
                if pi != ci:
                    violations.append(
                        f"SYMBOLIC_ASSOCIATION mismatch: child {ci!r} != parent {pi!r}"
                    )

    elif child.stereotype == TierStereotype.TIME_SUBDIVISION:
        # Children fully partition each parent: contiguous, no gaps, no overlap.
        # Group children by parent they fall in, then check coverage.
        for pi in parent_intervals:
            within = sorted(
                (
                    ci
                    for ci in child_intervals
                    if pi.start <= ci.start and ci.end <= pi.end
                ),
                key=lambda x: (x.start.to_fraction(), x.end.to_fraction()),
            )
            if not within:
                violations.append(f"TIME_SUBDIVISION: parent {pi!r} has no children")
                continue
            if within[0].start != pi.start:
                violations.append(
                    f"TIME_SUBDIVISION: first child {within[0]!r} does not start at {pi.start!r}"
                )
            if within[-1].end != pi.end:
                violations.append(
                    f"TIME_SUBDIVISION: last child {within[-1]!r} does not end at {pi.end!r}"
                )
            for left, right in zip(within, within[1:]):
                if left.end != right.start:
                    violations.append(
                        f"TIME_SUBDIVISION: gap or overlap between {left!r} and {right!r}"
                    )

    elif child.stereotype == TierStereotype.SYMBOLIC_SUBDIVISION:
        # Symbolic — no time validation (children are an ordered sequence
        # within the parent's interval). We check containment only.
        for ci in child_intervals:
            if not any(
                pi.start <= ci.start and ci.end <= pi.end for pi in parent_intervals
            ):
                violations.append(
                    f"SYMBOLIC_SUBDIVISION: child {ci!r} is not within any parent"
                )

    return violations
