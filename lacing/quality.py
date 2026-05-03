"""Inter-annotator agreement and boundary metrics.

Phase 0 ships four metrics from ANN-DOC §D, all as pure functions:

- :func:`cohen_kappa` — agreement between two annotators on a categorical label.
- :func:`krippendorff_alpha` — agreement across any number of annotators
  (handles missing data, multiple distance metrics).
- :func:`interval_iou` — Intersection-over-Union for two time intervals.
- :func:`boundary_iou` — Average IoU between two sets of intervals (greedy match).

The doc cites Krippendorff thresholds: α > 0.8 reliable, 0.67–0.8 tentative,
< 0.67 discard. Kappa traditionally: >0.8 almost perfect, 0.6–0.8 substantial,
0.4–0.6 moderate.

Pure functions — no numpy dependency in Phase 0.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable, Sequence
from typing import Callable, TypeVar

from lacing.allen import intersects
from lacing.time import TimeInterval


T = TypeVar("T", bound=Hashable)


# ---------------------------------------------------------------------------
# Cohen's kappa
# ---------------------------------------------------------------------------


def cohen_kappa(a: Sequence[T], b: Sequence[T]) -> float:
    """Cohen's kappa for two annotators on a categorical label.

    Args:
        a: Annotator A's labels.
        b: Annotator B's labels (must be the same length).

    Returns:
        κ ∈ [-1, 1]. 1 = perfect agreement, 0 = chance, negative = worse than chance.

    Raises:
        ValueError: If sequences differ in length or are empty.

    Edge cases:
        If only one category appears across both annotators, both observed
        and expected agreement are 1.0; we return 1.0 by convention.
    """
    if len(a) != len(b):
        raise ValueError(f"length mismatch: {len(a)} vs {len(b)}")
    n = len(a)
    if n == 0:
        raise ValueError("empty sequences")

    p_observed = sum(1 for x, y in zip(a, b) if x == y) / n

    counts_a = Counter(a)
    counts_b = Counter(b)
    categories = set(counts_a) | set(counts_b)
    p_expected = sum((counts_a[c] / n) * (counts_b[c] / n) for c in categories)

    if p_expected == 1.0:
        # Both annotators always agree on a single category — perfect.
        return 1.0
    return (p_observed - p_expected) / (1.0 - p_expected)


# ---------------------------------------------------------------------------
# Krippendorff's alpha
# ---------------------------------------------------------------------------


def _nominal_distance(x: T, y: T) -> float:
    return 0.0 if x == y else 1.0


def krippendorff_alpha(
    annotations: Sequence[Sequence[T | None]],
    *,
    distance: Callable[[T, T], float] = _nominal_distance,
) -> float:
    """Krippendorff's α across any number of annotators.

    Args:
        annotations: A list of annotators, each a sequence of labels (one per
            unit). Use ``None`` for a missing annotation by that annotator on
            that unit.
        distance: Function ``(x, y) -> float`` measuring disagreement between
            two label values. Default is the nominal (0/1) distance.

    Returns:
        α. 1.0 = perfect agreement, 0.0 = chance.

    Raises:
        ValueError: If sequences differ in length, fewer than 2 annotators
            given, or fewer than 2 paired observations exist.
    """
    if len(annotations) < 2:
        raise ValueError("need at least 2 annotators")
    n_units = len(annotations[0])
    for row in annotations:
        if len(row) != n_units:
            raise ValueError(
                f"all annotator rows must have the same length; got {len(row)} vs {n_units}"
            )

    # Observed disagreement: across all unordered pairs of annotators within
    # each unit (with both values present).
    observed_sum = 0.0
    observed_pairs = 0
    for u in range(n_units):
        present = [row[u] for row in annotations if row[u] is not None]
        if len(present) < 2:
            continue
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                observed_sum += distance(present[i], present[j])  # type: ignore[arg-type]
                observed_pairs += 1

    if observed_pairs == 0:
        raise ValueError("not enough paired observations to compute alpha")

    # Expected disagreement: across all unordered pairs of values regardless
    # of which annotator/unit.
    all_values: list[T] = [
        v
        for row in annotations
        for v in row
        if v is not None  # type: ignore[misc]
    ]
    counts = Counter(all_values)
    n_total = sum(counts.values())
    if n_total < 2:
        raise ValueError("not enough total observations to compute alpha")

    expected_sum = 0.0
    keys = list(counts.keys())
    for i, ki in enumerate(keys):
        for j in range(i, len(keys)):
            kj = keys[j]
            if i == j:
                pairs = counts[ki] * (counts[ki] - 1)
            else:
                pairs = 2 * counts[ki] * counts[kj]
            expected_sum += pairs * distance(ki, kj)

    expected_pairs = n_total * (n_total - 1)
    if expected_pairs == 0 or expected_sum == 0:
        # All values identical → perfect agreement
        return 1.0

    do = observed_sum / observed_pairs
    de = expected_sum / expected_pairs
    if de == 0:
        return 1.0
    return 1.0 - do / de


# ---------------------------------------------------------------------------
# Interval IoU
# ---------------------------------------------------------------------------


def interval_iou(a: TimeInterval, b: TimeInterval) -> float:
    """Intersection-over-Union for two time intervals.

    Returns 1.0 if both are equal point intervals at the same instant; 0.0
    if they don't intersect (including when only one is a point).
    """
    if a.is_point and b.is_point:
        return 1.0 if a.start == b.start else 0.0
    if a.is_point or b.is_point:
        # A point and an interval can't have a meaningful Lebesgue IoU.
        return 0.0
    if not intersects(a, b):
        return 0.0

    a_start = a.start.to_fraction()
    a_end = a.end.to_fraction()
    b_start = b.start.to_fraction()
    b_end = b.end.to_fraction()

    inter_start = max(a_start, b_start)
    inter_end = min(a_end, b_end)
    intersection = inter_end - inter_start

    union_start = min(a_start, b_start)
    union_end = max(a_end, b_end)
    union = union_end - union_start

    if union == 0:
        return 0.0
    return float(intersection / union)


def boundary_iou(a: Iterable[TimeInterval], b: Iterable[TimeInterval]) -> float:
    """Mean IoU between two sets of intervals via greedy best-match.

    For each interval in ``a``, finds its highest-IoU match in ``b`` (without
    replacement — once a ``b`` interval is matched it's removed from the pool).
    Unmatched intervals in either set contribute 0.0 to the mean.

    Returns:
        Mean IoU ∈ [0, 1]. Returns 0.0 if both sets are empty (defensible
        as a "no agreement to measure" baseline).
    """
    a_list = list(a)
    b_list = list(b)
    if not a_list and not b_list:
        return 0.0

    available_b = list(b_list)
    total = 0.0
    matched = 0

    # Greedy: for each `a` find best `b`. (For Phase 0 this is fine; switching
    # to Hungarian assignment would matter only with many-to-many ambiguity.)
    for ai in a_list:
        if not available_b:
            break
        best_score = 0.0
        best_idx = -1
        for j, bj in enumerate(available_b):
            score = interval_iou(ai, bj)
            if score > best_score:
                best_score = score
                best_idx = j
        if best_idx >= 0:
            available_b.pop(best_idx)
            total += best_score
            matched += 1

    # Unmatched intervals on either side count as 0 → divisor is the union count.
    denominator = max(len(a_list), len(b_list))
    return total / denominator
