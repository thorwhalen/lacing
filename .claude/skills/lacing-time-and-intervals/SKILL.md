---
name: lacing-time-and-intervals
description: Use when writing or reviewing any code in the lacing project that touches time, intervals, durations, rates, frame numbers, sample positions, timestamps, or interval queries. Triggers on `RationalTime`, `TimeInterval`, `fractions.Fraction`, `intervaltree`, Allen relations (overlap/during/meets/before), interval boundaries, half-open ranges, snapping, or any conversion between seconds/ticks/frames/samples. Catches the most common landmines: float drift, closed-vs-open boundaries, mixed rates, and ad-hoc overlap predicates.
---

# Lacing — Time and Intervals

Time correctness is the #1 source of subtle bugs in annotation systems. All
four design docs converge on the same rules. Follow them or annotations
silently desync over long timelines.

## Rule 1 — Time is rational, never float

```python
from fractions import Fraction
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class RationalTime:
    value: int      # numerator
    rate: int = 24000   # denominator (ticks per second)

    def to_fraction(self) -> Fraction:
        return Fraction(self.value, self.rate)

    def to_seconds(self) -> float:
        # ONLY for display / external systems that demand float
        return self.value / self.rate
```

- **Default rate: 24000.** LCM 1008000 if you need exact representation of all common video rates simultaneously.
- **Wire format:** `{"v": int, "r": int}`. TS mirrors with `bigint`.
- Use `fractions.Fraction` for arithmetic. `float` only at the *very* edge (display, third-party libs that demand it).
- `to_seconds()` returns float **for display only.** Never round-trip through it.

**Banned patterns:**
- `time_in_seconds: float` anywhere in the model, wire, or storage layer.
- `start + duration` where any operand is a float.
- `time1 == time2` on floats — use `Fraction` equality.

## Rule 2 — Intervals are half-open `[start, end)`

```python
@dataclass(frozen=True, slots=True)
class TimeInterval:
    start: RationalTime
    end: RationalTime  # exclusive

    @property
    def is_point(self) -> bool:
        return self.start == self.end  # zero-length = point annotation
```

- `start <= end` always. `start == end` is a **valid point annotation**, not a degenerate case.
- Match OTIO's `end_time_exclusive` naming. If you ever expose `end_time_inclusive`, name it explicitly.
- Two intervals with identical bounds are **equal**, not "touching."

## Rule 3 — Mixed rates: convert, don't compare

Two `RationalTime`s with different rates are comparable via `Fraction`, but
**adding/subtracting them across rates is a smell**. Either:
- Keep one canonical rate per project, OR
- Convert explicitly at the boundary via `t.to_rate(new_rate)` and document the rate.

The actual implementation is in `lacing.time`:
- `RationalTime.from_seconds(value, rate=...)` accepts `int | float | str | Fraction` and raises `LossyTimeConversionError` if the value can't be exactly represented at `rate`. Use **strings** for ingest from text formats (`"0.001"` is exact; `0.001` isn't).
- `RationalTime.to_rate(new_rate)` raises `LossyTimeConversionError` on loss — never rounds silently.
- `__add__` / `__sub__` operate on `Fraction` then quantize back at `self.rate`. They raise `LossyTimeConversionError` if the sum isn't exact at that rate. **This is stricter than you might expect** — adding `Fraction(1,3)` to a rate-2 `RationalTime` raises rather than rounding.

Lossy conversion always raises, never rounds.

## Rule 4 — Allen's 13 relations are the public predicate API

Don't write ad-hoc `if a.start < b.end and b.start < a.end:` predicates.
Use the registered Allen relations (in `lacing/allen.py`):

| Relation | Symbol | Predicate |
|----------|--------|-----------|
| `before` | `<`   | `a.end < b.start` |
| `after`  | `>`   | `a.start > b.end` |
| `meets`  | `m`   | `a.end == b.start` |
| `met_by` | `mi`  | `a.start == b.end` |
| `overlaps` | `o` | `a.start < b.start < a.end < b.end` |
| `overlapped_by` | `oi` | (mirror) |
| `starts` | `s`   | `a.start == b.start and a.end < b.end` |
| `started_by` | `si` | (mirror) |
| `during` | `d`   | `a.start > b.start and a.end < b.end` |
| `contains` | `di` | (mirror) |
| `finishes` | `f` | `a.start > b.start and a.end == b.end` |
| `finished_by` | `fi` | (mirror) |
| `equals` | `=`   | `a.start == b.start and a.end == b.end` |

For "any kind of overlap" use the disjunction `overlaps | overlapped_by | during | contains | starts | started_by | finishes | finished_by | equals` — exposed as `intersects(a, b)`. Don't reinvent it.

## Rule 5 — Use the right index for the query

| Query shape | In-memory | Persistent |
|-------------|-----------|------------|
| Point query / overlap with a single interval | `intervaltree.IntervalTree` (Apache-2.0) | `PostgresStore` (`int8range` + GiST) or `SqliteStore` (R*Tree, embedded) |
| Aggregate over fixed range (count, sum) | segment tree with lazy propagation | PostgreSQL with materialized view |
| Many concurrent reads, append-mostly writes | `intervaltree` is fine | GiST |
| Bulk batch analytics | `pyranges` v1 (Rust/Polars) | Parquet/Arrow IPC export |
| Embedded / single-file | n/a | SQLite + R*Tree (`.annot` format) |
| Multi-dim (time × channel) | `rtree` (libspatialindex) | composite GiST |

**Banned:** `portion` (LGPL-3.0). Use `intervaltree` for in-memory work.

## Rule 6 — UI and storage layers can use different units

The frontend doc allows **integer microseconds** at the UI layer for
arithmetic speed, but **only**:
- Convert at the wire boundary (`RationalTime ↔ µs`).
- Reject non-exact conversions (raise on lossy).
- Document the unit on every UI variable name (`pos_us`, `dur_us`).

The Python model never speaks microseconds. It speaks `RationalTime`.

## Rule 7 — Snapping is rate-aware

Snap targets (playhead, in/out points, clip edges, markers, grid) are all
`RationalTime`. Snapping logic stays in `Fraction` arithmetic. **Never**
snap by rounding floats.

## Quick checklist before commit

- [ ] No `float` in any signature/field except display layers and external library bridges.
- [ ] Every `TimeInterval` is half-open; point intervals (`start == end`) handled.
- [ ] Overlap/containment predicates go through `lacing/allen.py`, not ad-hoc.
- [ ] Any rate conversion has an explicit lossy-→-raise path.
- [ ] No `portion` import (LGPL).
- [ ] In-memory store uses `intervaltree`; persistent goes through `PostgresStore` (`int8range`/GiST) or `SqliteStore` (R*Tree).

## Source pointers

- Concrete Pydantic models: BACK-DOC §2.1.
- Algorithm choices and complexity: ANN-DOC §C–D.
- 13 relations + ORD-Horn tractable subalgebra: ANN-DOC §A.
- UI µs convention: FRONT-DOC §3 "Time representation".
- OTIO `RationalTime` parity: OSS-DOC OTIO section.
