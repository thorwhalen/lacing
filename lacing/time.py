"""Rational time and half-open intervals — the foundations.

Time in lacing is always rational, never float. See
``.claude/skills/lacing-time-and-intervals/SKILL.md`` and BACK-DOC §2.1.

Wire format: ``{"v": int, "r": int}``. Python uses ``fractions.Fraction``
for arithmetic. ``to_seconds()`` is a one-way escape hatch for display
and third-party libs that demand a float.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


DEFAULT_RATE: int = 24000
"""Default rate (ticks/second). LCM 1008000 covers all common video rates exactly."""


class LossyTimeConversionError(ValueError):
    """Raised when a rate or seconds conversion would lose precision."""


class RationalTime:
    """A point in time as ``value / rate`` seconds.

    Immutable. Two ``RationalTime`` values with different rates compare via
    their rational value, so ``RationalTime(24, 24) == RationalTime(1, 1)``.

    Examples:
        >>> RationalTime(24000) == RationalTime(1, 1)
        True
        >>> RationalTime.from_seconds("1.5", rate=2).value
        3
    """

    __slots__ = ("_value", "_rate")

    def __init__(self, value: int, rate: int = DEFAULT_RATE) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"value must be int, got {type(value).__name__}")
        if not isinstance(rate, int) or isinstance(rate, bool):
            raise TypeError(f"rate must be int, got {type(rate).__name__}")
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_rate", rate)

    @property
    def value(self) -> int:
        return self._value

    @property
    def rate(self) -> int:
        return self._rate

    @classmethod
    def from_seconds(
        cls, seconds: float | Fraction | str, rate: int = DEFAULT_RATE
    ) -> "RationalTime":
        """Build from seconds. Quantizes to ``rate``; raises if lossy.

        ``seconds`` may be a ``str`` like ``"1.001"`` to avoid float ingestion.
        """
        if isinstance(seconds, str):
            f = Fraction(seconds)
        elif isinstance(seconds, Fraction):
            f = seconds
        elif isinstance(seconds, int) and not isinstance(seconds, bool):
            f = Fraction(seconds)
        elif isinstance(seconds, float):
            f = Fraction(seconds)
        else:
            raise TypeError(
                f"seconds must be str, int, float, or Fraction; got {type(seconds).__name__}"
            )
        scaled = f * rate
        if scaled.denominator != 1:
            raise LossyTimeConversionError(
                f"{seconds!r} cannot be exactly represented at rate {rate}"
            )
        return cls(int(scaled), rate)

    @classmethod
    def from_fraction(cls, f: Fraction, rate: int = DEFAULT_RATE) -> "RationalTime":
        return cls.from_seconds(f, rate=rate)

    @classmethod
    def zero(cls, rate: int = DEFAULT_RATE) -> "RationalTime":
        return cls(0, rate)

    def to_fraction(self) -> Fraction:
        return Fraction(self._value, self._rate)

    def to_seconds(self) -> float:
        """Float seconds — for display only. Never round-trip through this."""
        return self._value / self._rate

    def to_rate(self, new_rate: int) -> "RationalTime":
        """Re-express at ``new_rate``. Raises ``LossyTimeConversionError`` on loss."""
        if not isinstance(new_rate, int) or isinstance(new_rate, bool):
            raise TypeError(f"new_rate must be int, got {type(new_rate).__name__}")
        if new_rate <= 0:
            raise ValueError(f"new_rate must be positive, got {new_rate}")
        f = Fraction(self._value * new_rate, self._rate)
        if f.denominator != 1:
            raise LossyTimeConversionError(
                f"RationalTime({self._value}, {self._rate}) cannot be exactly "
                f"re-expressed at rate {new_rate}"
            )
        return type(self)(int(f), new_rate)

    def __add__(self, other: object) -> "RationalTime":
        if isinstance(other, RationalTime):
            f = self.to_fraction() + other.to_fraction()
        elif isinstance(other, Fraction):
            f = self.to_fraction() + other
        else:
            return NotImplemented
        scaled = f * self._rate
        if scaled.denominator != 1:
            raise LossyTimeConversionError(
                f"sum {f} cannot be exactly represented at rate {self._rate}"
            )
        return type(self)(int(scaled), self._rate)

    def __sub__(self, other: object) -> "RationalTime":
        if isinstance(other, RationalTime):
            f = self.to_fraction() - other.to_fraction()
        elif isinstance(other, Fraction):
            f = self.to_fraction() - other
        else:
            return NotImplemented
        scaled = f * self._rate
        if scaled.denominator != 1:
            raise LossyTimeConversionError(
                f"difference {f} cannot be exactly represented at rate {self._rate}"
            )
        return type(self)(int(scaled), self._rate)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RationalTime):
            return NotImplemented
        return self.to_fraction() == other.to_fraction()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, RationalTime):
            return NotImplemented
        return self.to_fraction() < other.to_fraction()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, RationalTime):
            return NotImplemented
        return self.to_fraction() <= other.to_fraction()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, RationalTime):
            return NotImplemented
        return self.to_fraction() > other.to_fraction()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, RationalTime):
            return NotImplemented
        return self.to_fraction() >= other.to_fraction()

    def __hash__(self) -> int:
        return hash(self.to_fraction())

    def __repr__(self) -> str:
        return f"RationalTime({self._value}, {self._rate})"

    def to_wire(self) -> dict[str, int]:
        return {"v": self._value, "r": self._rate}

    @classmethod
    def from_wire(cls, d: dict[str, int]) -> "RationalTime":
        return cls(d["v"], d["r"])

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        def _validate(value: Any) -> "RationalTime":
            if isinstance(value, RationalTime):
                return value
            if isinstance(value, dict):
                return cls.from_wire(value)
            raise TypeError(f"cannot build RationalTime from {type(value).__name__}")

        return core_schema.no_info_plain_validator_function(
            _validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: x.to_wire(), when_used="always"
            ),
        )


class TimeInterval:
    """A half-open interval ``[start, end)``.

    ``start == end`` is a valid point annotation, not a degenerate case.
    Always ``start <= end``; constructor raises ``ValueError`` otherwise.
    """

    __slots__ = ("_start", "_end")

    def __init__(self, start: RationalTime, end: RationalTime) -> None:
        if not isinstance(start, RationalTime):
            raise TypeError(f"start must be RationalTime, got {type(start).__name__}")
        if not isinstance(end, RationalTime):
            raise TypeError(f"end must be RationalTime, got {type(end).__name__}")
        if end < start:
            raise ValueError(f"end ({end!r}) must be >= start ({start!r})")
        object.__setattr__(self, "_start", start)
        object.__setattr__(self, "_end", end)

    @property
    def start(self) -> RationalTime:
        return self._start

    @property
    def end(self) -> RationalTime:
        return self._end

    @property
    def duration(self) -> RationalTime:
        """``end - start`` at the same rate as ``start``."""
        return self._end - self._start

    @property
    def is_point(self) -> bool:
        return self._start == self._end

    @classmethod
    def point(cls, t: RationalTime) -> "TimeInterval":
        return cls(t, t)

    @classmethod
    def from_seconds(
        cls,
        start: float | Fraction | str,
        end: float | Fraction | str,
        rate: int = DEFAULT_RATE,
    ) -> "TimeInterval":
        return cls(
            RationalTime.from_seconds(start, rate=rate),
            RationalTime.from_seconds(end, rate=rate),
        )

    def shift(self, by: RationalTime) -> "TimeInterval":
        return type(self)(self._start + by, self._end + by)

    def to_wire(self) -> dict[str, dict[str, int]]:
        return {"start": self._start.to_wire(), "end": self._end.to_wire()}

    @classmethod
    def from_wire(cls, d: dict) -> "TimeInterval":
        return cls(
            RationalTime.from_wire(d["start"]),
            RationalTime.from_wire(d["end"]),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TimeInterval):
            return NotImplemented
        return self._start == other._start and self._end == other._end

    def __hash__(self) -> int:
        return hash((self._start, self._end))

    def __repr__(self) -> str:
        return f"TimeInterval({self._start!r}, {self._end!r})"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        def _validate(value: Any) -> "TimeInterval":
            if isinstance(value, TimeInterval):
                return value
            if isinstance(value, dict):
                return cls.from_wire(value)
            raise TypeError(f"cannot build TimeInterval from {type(value).__name__}")

        return core_schema.no_info_plain_validator_function(
            _validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: x.to_wire(), when_used="always"
            ),
        )
