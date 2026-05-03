"""Tests for lacing.quality — IAA and boundary metrics."""

from __future__ import annotations

import math

import pytest

from lacing.quality import (
    boundary_iou,
    cohen_kappa,
    interval_iou,
    krippendorff_alpha,
)
from lacing.time import RationalTime, TimeInterval


# --- Cohen's kappa ----------------------------------------------------------


class TestCohenKappa:
    def test_perfect_agreement(self):
        assert cohen_kappa(["A", "B", "A"], ["A", "B", "A"]) == 1.0

    def test_total_disagreement(self):
        assert cohen_kappa(["A", "B"], ["B", "A"]) == pytest.approx(-1.0)

    def test_chance_level(self):
        # Independent uniform → expected ≈ 0
        a = ["A", "B"] * 50
        b = ["A", "A", "B", "B"] * 25
        # Observed agreement: 50% (A,A) + 0% (B,A) + 0% (A,B) + 50% (B,B)
        k = cohen_kappa(a, b)
        assert -0.1 < k < 0.1

    def test_single_category(self):
        # Both annotators always say "X" — perfect by convention.
        assert cohen_kappa(["X"] * 5, ["X"] * 5) == 1.0

    def test_known_value(self):
        # Sanity check from a well-known textbook example.
        # 50 cases. Both rate "yes" 30 times. They agree on 25 of those.
        # Both rate "no" 20 times. They agree on 15 of those.
        # Disagreements: 5 yes/no + 5 no/yes = 10
        a = ["Y"] * 25 + ["Y"] * 5 + ["N"] * 5 + ["N"] * 15
        b = ["Y"] * 25 + ["N"] * 5 + ["Y"] * 5 + ["N"] * 15
        k = cohen_kappa(a, b)
        # p_o = 40/50 = 0.8
        # p_a = 30/50 = 0.6 (Y rate annotator a), 30/50 = 0.6 Y rate b
        # p_e = 0.6*0.6 + 0.4*0.4 = 0.52
        # k = (0.8 - 0.52) / (1 - 0.52) ≈ 0.583
        assert k == pytest.approx(0.5833333, abs=1e-4)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            cohen_kappa(["A"], ["A", "B"])

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            cohen_kappa([], [])


# --- Krippendorff's alpha ---------------------------------------------------


class TestKrippendorffAlpha:
    def test_perfect_agreement(self):
        rows = [
            ["A", "B", "C", "D"],
            ["A", "B", "C", "D"],
        ]
        assert krippendorff_alpha(rows) == 1.0

    def test_three_annotators_perfect(self):
        rows = [
            ["A", "A", "B", "B"],
            ["A", "A", "B", "B"],
            ["A", "A", "B", "B"],
        ]
        assert krippendorff_alpha(rows) == 1.0

    def test_disagreement_negative(self):
        rows = [
            ["A", "A", "A"],
            ["B", "B", "B"],
        ]
        # All values present and they always disagree → α should be very negative.
        a = krippendorff_alpha(rows)
        assert a < 0

    def test_handles_missing(self):
        rows = [
            ["A", "B", None, "D"],
            ["A", "B", "C", None],
        ]
        # Two paired observations (A,A and B,B) both agree → α = 1.0
        a = krippendorff_alpha(rows)
        assert a == 1.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            krippendorff_alpha([["A"], ["A", "B"]])

    def test_too_few_annotators_raises(self):
        with pytest.raises(ValueError):
            krippendorff_alpha([["A", "B"]])

    def test_no_paired_observations_raises(self):
        rows = [
            ["A", None],
            [None, "B"],
        ]
        with pytest.raises(ValueError):
            krippendorff_alpha(rows)

    def test_custom_distance(self):
        # Ordinal-style distance: closer numbers disagree less.
        def ordinal(x, y):
            return abs(x - y)

        rows = [
            [1, 2, 3, 4],
            [1, 2, 3, 5],  # only the last one differs by 1
        ]
        a = krippendorff_alpha(rows, distance=ordinal)
        # Strong agreement; α should be close to 1.
        assert 0.7 < a <= 1.0


# --- interval_iou -----------------------------------------------------------


def _ti(s: int, e: int) -> TimeInterval:
    return TimeInterval(RationalTime(s), RationalTime(e))


class TestIntervalIoU:
    def test_identical(self):
        a = _ti(0, 100)
        assert interval_iou(a, a) == 1.0

    def test_disjoint(self):
        assert interval_iou(_ti(0, 10), _ti(20, 30)) == 0.0

    def test_half_overlap(self):
        # [0, 100) vs [50, 150): intersection 50, union 150
        score = interval_iou(_ti(0, 100), _ti(50, 150))
        assert score == pytest.approx(50 / 150)

    def test_contained(self):
        # [0, 100) contains [25, 75): intersection 50, union 100
        score = interval_iou(_ti(0, 100), _ti(25, 75))
        assert score == pytest.approx(0.5)

    def test_touching_is_zero(self):
        # Half-open: [0, 10) and [10, 20) share zero measure
        assert interval_iou(_ti(0, 10), _ti(10, 20)) == 0.0

    def test_two_points_equal(self):
        a = TimeInterval.point(RationalTime(5))
        b = TimeInterval.point(RationalTime(5))
        assert interval_iou(a, b) == 1.0

    def test_two_points_different(self):
        a = TimeInterval.point(RationalTime(5))
        b = TimeInterval.point(RationalTime(6))
        assert interval_iou(a, b) == 0.0

    def test_point_vs_interval(self):
        p = TimeInterval.point(RationalTime(5))
        i = _ti(0, 10)
        assert interval_iou(p, i) == 0.0


# --- boundary_iou ----------------------------------------------------------


class TestBoundaryIoU:
    def test_both_empty(self):
        assert boundary_iou([], []) == 0.0

    def test_identical_sets(self):
        ivs = [_ti(0, 10), _ti(20, 30), _ti(40, 50)]
        assert boundary_iou(ivs, ivs) == 1.0

    def test_one_off(self):
        a = [_ti(0, 100), _ti(200, 300)]
        b = [_ti(0, 100), _ti(200, 300), _ti(400, 500)]
        # Two perfect matches; one extra in b unmatched.
        # denominator = max(2, 3) = 3; total = 2.0
        score = boundary_iou(a, b)
        assert score == pytest.approx(2 / 3)

    def test_all_disjoint(self):
        a = [_ti(0, 10)]
        b = [_ti(100, 200)]
        assert boundary_iou(a, b) == 0.0

    def test_partial_overlap(self):
        a = [_ti(0, 100)]
        b = [_ti(50, 150)]
        score = boundary_iou(a, b)
        assert score == pytest.approx(50 / 150)
