"""Tests for lacing.time."""

from fractions import Fraction

import pytest

from lacing.time import (
    DEFAULT_RATE,
    LossyTimeConversionError,
    RationalTime,
    TimeInterval,
)


class TestRationalTime:
    def test_construction(self):
        t = RationalTime(48000, 24000)
        assert t.value == 48000
        assert t.rate == 24000

    def test_default_rate(self):
        t = RationalTime(0)
        assert t.rate == DEFAULT_RATE

    def test_negative_rate_rejected(self):
        with pytest.raises(ValueError):
            RationalTime(0, -1)

    def test_zero_rate_rejected(self):
        with pytest.raises(ValueError):
            RationalTime(0, 0)

    def test_float_value_rejected(self):
        with pytest.raises(TypeError):
            RationalTime(1.5)  # type: ignore[arg-type]

    def test_bool_rejected(self):
        # bool is a subclass of int, but it's a smell to allow it.
        with pytest.raises(TypeError):
            RationalTime(True)  # type: ignore[arg-type]

    def test_equality_across_rates(self):
        assert RationalTime(24, 24) == RationalTime(1, 1)
        assert RationalTime(48000, 24000) == RationalTime(2, 1)

    def test_ordering(self):
        a = RationalTime(1, 2)  # 0.5s
        b = RationalTime(1, 1)  # 1s
        assert a < b
        assert b > a
        assert a <= b
        assert a != b

    def test_hash_matches_equality(self):
        s = {RationalTime(2, 4), RationalTime(1, 2), RationalTime(4, 8)}
        assert len(s) == 1

    def test_from_seconds_string(self):
        t = RationalTime.from_seconds("1.5", rate=2)
        assert t.value == 3
        assert t.rate == 2

    def test_from_seconds_int(self):
        t = RationalTime.from_seconds(2, rate=10)
        assert t.value == 20

    def test_from_seconds_lossy_raises(self):
        with pytest.raises(LossyTimeConversionError):
            RationalTime.from_seconds("0.1", rate=3)

    def test_from_seconds_fraction(self):
        t = RationalTime.from_seconds(Fraction(1, 3), rate=3)
        assert t.value == 1
        assert t.rate == 3

    def test_to_fraction(self):
        assert RationalTime(3, 4).to_fraction() == Fraction(3, 4)

    def test_to_seconds_is_float(self):
        s = RationalTime(1, 2).to_seconds()
        assert isinstance(s, float)
        assert s == 0.5

    def test_to_rate_exact(self):
        t = RationalTime(1, 2).to_rate(48000)
        assert t.value == 24000
        assert t.rate == 48000

    def test_to_rate_lossy_raises(self):
        with pytest.raises(LossyTimeConversionError):
            RationalTime(1, 3).to_rate(2)

    def test_addition(self):
        a = RationalTime(1, 4)
        b = RationalTime(1, 4)
        c = a + b
        assert c.to_fraction() == Fraction(1, 2)
        assert c.rate == 4

    def test_subtraction(self):
        a = RationalTime(3, 4)
        b = RationalTime(1, 4)
        assert (a - b).to_fraction() == Fraction(1, 2)

    def test_addition_lossy_raises(self):
        # rate=2 can't represent (1/2 + 1/3) = 5/6
        with pytest.raises(LossyTimeConversionError):
            RationalTime(1, 2) + Fraction(1, 3)

    def test_wire_round_trip(self):
        t = RationalTime(123, 456)
        assert RationalTime.from_wire(t.to_wire()) == t

    def test_wire_format(self):
        assert RationalTime(7, 8).to_wire() == {"v": 7, "r": 8}

    def test_zero(self):
        z = RationalTime.zero()
        assert z.value == 0
        assert z.rate == DEFAULT_RATE

    def test_repr(self):
        assert repr(RationalTime(1, 2)) == "RationalTime(1, 2)"


class TestTimeInterval:
    def test_construction(self):
        i = TimeInterval(RationalTime(0), RationalTime(24000))
        assert i.start == RationalTime(0)
        assert i.end == RationalTime(24000)

    def test_end_before_start_rejected(self):
        with pytest.raises(ValueError):
            TimeInterval(RationalTime(2), RationalTime(1))

    def test_point_interval_allowed(self):
        i = TimeInterval(RationalTime(5), RationalTime(5))
        assert i.is_point
        assert i.duration == RationalTime(0, DEFAULT_RATE)

    def test_point_classmethod(self):
        t = RationalTime(7)
        i = TimeInterval.point(t)
        assert i.start == t == i.end
        assert i.is_point

    def test_duration(self):
        i = TimeInterval(RationalTime(10), RationalTime(30))
        assert i.duration == RationalTime(20, DEFAULT_RATE)

    def test_from_seconds(self):
        i = TimeInterval.from_seconds("0.5", "1.5", rate=2)
        assert i.start.value == 1
        assert i.end.value == 3

    def test_shift(self):
        i = TimeInterval(RationalTime(10), RationalTime(20))
        shifted = i.shift(RationalTime(5))
        assert shifted.start == RationalTime(15)
        assert shifted.end == RationalTime(25)

    def test_equality(self):
        a = TimeInterval(RationalTime(0), RationalTime(24000))
        b = TimeInterval(RationalTime(0, DEFAULT_RATE), RationalTime(1, 1))
        assert a == b

    def test_hash(self):
        a = TimeInterval(RationalTime(0), RationalTime(10))
        b = TimeInterval(RationalTime(0), RationalTime(10))
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_wire_round_trip(self):
        i = TimeInterval(RationalTime(0), RationalTime(24000))
        assert TimeInterval.from_wire(i.to_wire()) == i

    def test_repr(self):
        s = repr(TimeInterval(RationalTime(0), RationalTime(1)))
        assert "TimeInterval" in s
