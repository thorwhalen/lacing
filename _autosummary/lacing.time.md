# lacing.time

Rational time and half-open intervals — the foundations.

Time in lacing is always rational, never float. See
`.claude/skills/lacing-time-and-intervals/SKILL.md` and BACK-DOC §2.1.

Wire format: `{"v": int, "r": int}`. Python uses `fractions.Fraction`
for arithmetic. `to_seconds()` is a one-way escape hatch for display
and third-party libs that demand a float.

### Module Attributes

| [`DEFAULT_RATE`](#lacing.time.DEFAULT_RATE)              | Default rate (ticks/second).                                                |
|----------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`RATIONAL_TIME_JSON_SCHEMA`](#lacing.time.RATIONAL_TIME_JSON_SCHEMA) | JSON Schema for the `RationalTime` wire shape `{"v": int, "r": int}`.       |
| [`TIME_INTERVAL_JSON_SCHEMA`](#lacing.time.TIME_INTERVAL_JSON_SCHEMA) | JSON Schema for the `TimeInterval` wire shape `{"start": ..., "end": ...}`. |

### Classes

| [`RationalTime`](#lacing.time.RationalTime)(value[, rate])   | A point in time as `value / rate` seconds.   |
|--------------------------------------------------------------------------------|----------------------------------------------|
| [`TimeInterval`](#lacing.time.TimeInterval)(start, end)      | A half-open interval `[start, end)`.         |

### Exceptions

| [`LossyTimeConversionError`](#lacing.time.LossyTimeConversionError)   | Raised when a rate or seconds conversion would lose precision.   |
|-----------------------------------------------------------------------------|------------------------------------------------------------------|

### lacing.time.DEFAULT_RATE *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 24000*

Default rate (ticks/second). LCM 1008000 covers all common video rates exactly.

### *exception* lacing.time.LossyTimeConversionError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

Raised when a rate or seconds conversion would lose precision.

### lacing.time.RATIONAL_TIME_JSON_SCHEMA *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]* *= {'additionalProperties': False, 'description': 'A point in time as v/r seconds. Both members are integers — never a float, never a JSON number with a fractional part.', 'properties': {'r': {'description': 'Rate in ticks per second. Strictly positive.', 'exclusiveMinimum': 0, 'type': 'integer'}, 'v': {'description': 'Tick count (may be negative).', 'type': 'integer'}}, 'required': ['v', 'r'], 'title': 'RationalTime', 'type': 'object'}*

JSON Schema for the `RationalTime` wire shape `{"v": int, "r": int}`.

Non-negotiable 1 lives here as much as in the constructor: `integer`, not
`number`. A JSON Schema validator must reject `{"v": 0.5, "r": 48000}`.

### *class* lacing.time.RationalTime(value, rate=24000)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A point in time as `value / rate` seconds.

Immutable. Two `RationalTime` values with different rates compare via
their rational value, so `RationalTime(24, 24) == RationalTime(1, 1)`.

### Examples

```pycon
>>> RationalTime(24000) == RationalTime(1, 1)
True
>>> RationalTime.from_seconds("1.5", rate=2).value
3
```

#### *classmethod* from_seconds(seconds, rate=24000)

Build from seconds. Quantizes to `rate`; raises if lossy.

`seconds` may be a `str` like `"1.001"` to avoid float ingestion.

* **Return type:**
  [`RationalTime`](#lacing.time.RationalTime)

#### *classmethod* from_seconds_lossy(seconds, , rate=24000, mode='round')

Build from seconds, quantizing to the nearest sample at `rate`.

Unlike [`from_seconds()`](#lacing.time.RationalTime.from_seconds) — which raises
[`LossyTimeConversionError`](#lacing.time.LossyTimeConversionError) when the value cannot be
represented exactly — this method always succeeds by quantizing.
`mode` selects the rounding rule:

- `"round"` — nearest sample, ties to even (default)
- `"floor"` — largest sample <= `seconds`
- `"ceil"`  — smallest sample >= `seconds`

Use this when sample-level quantization is knowingly acceptable —
the common case for user-supplied durations. Use [`from_seconds()`](#lacing.time.RationalTime.from_seconds)
when exactness matters and a lossy conversion should be an error.

### Examples

```pycon
>>> RationalTime.from_seconds_lossy("0.1", rate=3).value
0
>>> RationalTime.from_seconds_lossy("0.1", rate=3, mode="ceil").value
1
```

* **Return type:**
  [`RationalTime`](#lacing.time.RationalTime)

#### *classmethod* from_wire(d)

Build from the wire form. Unknown keys are an error, not ignored.

`RATIONAL_TIME_JSON_SCHEMA` sets `additionalProperties: false` and
lacing-ui’s Zod mirror is `.strict()`; accepting extras here would
make Python the one lax end of a contract both other ends enforce, so
a `{"v": 0, "r": 1, "seconds": 0.0}` payload would round-trip through
Python and then be rejected by the frontend.

* **Return type:**
  [`RationalTime`](#lacing.time.RationalTime)

#### *classmethod* now(rate=24000)

Wall-clock time as a [`RationalTime`](#lacing.time.RationalTime), quantized to `rate`.

Uses `time.time_ns()` and builds the value directly, sidestepping
the float-quantization landmine of `from_seconds(float)`. Every
producer of an annotation or artifact needs this for
`Provenance.generated_at_time` — the only value that field reads
as a *known* time. Tick 0 there is the UNKNOWN sentinel
(`lacing.model.UNKNOWN_GENERATED_AT`), never the epoch.

* **Return type:**
  [`RationalTime`](#lacing.time.RationalTime)

#### to_rate(new_rate)

Re-express at `new_rate`. Raises `LossyTimeConversionError` on loss.

* **Return type:**
  [`RationalTime`](#lacing.time.RationalTime)

#### to_seconds()

Float seconds — for display only. Never round-trip through this.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### *classmethod* zero(rate=24000)

Tick 0 at `rate` — the start of a media timeline.

Not a wall-clock timestamp: as a `Provenance.generated_at_time` it
is the UNKNOWN sentinel (`lacing.model.UNKNOWN_GENERATED_AT`), not
the epoch. Producers stamp [`now()`](#lacing.time.RationalTime.now) there.

* **Return type:**
  [`RationalTime`](#lacing.time.RationalTime)

### lacing.time.TIME_INTERVAL_JSON_SCHEMA *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]* *= {'additionalProperties': False, 'description': 'A half-open interval [start, end). start == end is a point.', 'properties': {'end': {'additionalProperties': False, 'description': 'A point in time as v/r seconds. Both members are integers — never a float, never a JSON number with a fractional part.', 'properties': {'r': {'description': 'Rate in ticks per second. Strictly positive.', 'exclusiveMinimum': 0, 'type': 'integer'}, 'v': {'description': 'Tick count (may be negative).', 'type': 'integer'}}, 'required': ['v', 'r'], 'title': 'RationalTime', 'type': 'object'}, 'start': {'additionalProperties': False, 'description': 'A point in time as v/r seconds. Both members are integers — never a float, never a JSON number with a fractional part.', 'properties': {'r': {'description': 'Rate in ticks per second. Strictly positive.', 'exclusiveMinimum': 0, 'type': 'integer'}, 'v': {'description': 'Tick count (may be negative).', 'type': 'integer'}}, 'required': ['v', 'r'], 'title': 'RationalTime', 'type': 'object'}}, 'required': ['start', 'end'], 'title': 'TimeInterval', 'type': 'object'}*

JSON Schema for the `TimeInterval` wire shape `{"start": ..., "end": ...}`.

`start <= end` is a constructor invariant that JSON Schema cannot express;
Pydantic validation still enforces it.

### *class* lacing.time.TimeInterval(start, end)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A half-open interval `[start, end)`.

`start == end` is a valid point annotation, not a degenerate case.
Always `start <= end`; constructor raises `ValueError` otherwise.

#### *property* duration *: [RationalTime](#lacing.time.RationalTime)*

`end - start` at the same rate as `start`.

#### *classmethod* from_wire(d)

Build from the wire form. See [`RationalTime.from_wire()`](#lacing.time.RationalTime.from_wire) on extras.

* **Return type:**
  [`TimeInterval`](#lacing.time.TimeInterval)
