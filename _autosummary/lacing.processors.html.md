# lacing.processors

Background processors — pluggable jobs that run against a store + op-log.

A *processor* is a registered async function that:

1. Takes an `IntervalAnnotationStore`, an `OpLog`, and processor-specific
   keyword arguments.
2. Either mutates the store (recording op-log entries) or returns a result
   (or both).

Two execution modes ship:

- **Synchronous** via [`run_sync()`](#lacing.processors.run_sync) — runs in the current event loop.
  Always available; no Redis or other infra. Use this from tests, CLIs,
  and scripts.
- **Async via Arq** — see `lacing.worker` (optional). The same
  processor can be queued through Redis when scale demands it.

Per BACK-DOC §6: Arq is preferred over Celery (lighter, async-native).
But the *processor pattern itself* is independent of Arq — most users
will never need Redis.

Example built-ins:

- [`low_confidence_review()`](#lacing.processors.low_confidence_review) — flag annotations whose confidence is
  below a threshold by adding a parallel `for-review` tier annotation.
- [`detect_density_change_points()`](#lacing.processors.detect_density_change_points) — emit point markers wherever the
  annotation density changes more than `min_delta` over a sliding
  window.

Register your own with [`register_processor()`](#lacing.processors.register_processor).

### Functions

| [`clear_processors`](#lacing.processors.clear_processors)()                             | Drop every registered processor.                                      |
|-------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`detect_density_change_points`](#lacing.processors.detect_density_change_points)(\*, store, oplog) | Emit point markers wherever annotation density changes sharply.       |
| `get_processor`(name)                                                                           |                                                                       |
| [`low_confidence_review`](#lacing.processors.low_confidence_review)(\*, store, oplog[, ...]) | Flag low-confidence annotations by mirroring them onto a review tier. |
| [`register_processor`](#lacing.processors.register_processor)([func, name])               | Register a processor under `name` (defaults to the function name).    |
| [`registered_processors`](#lacing.processors.registered_processors)()                        | Names of every registered processor, sorted.                          |
| [`run_async`](#lacing.processors.run_async)(name, \*, store, oplog, \*\*kwargs)  | Run a processor in the current event loop.                            |
| [`run_sync`](#lacing.processors.run_sync)(name, \*, store, oplog, \*\*kwargs)   | Run a processor synchronously and return its result.                  |

### Exceptions

| [`ProcessorError`](#lacing.processors.ProcessorError)   | Raised when a registered processor's invocation fails.   |
|-------------------------------------------------------------------|----------------------------------------------------------|

### *exception* lacing.processors.ProcessorError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when a registered processor’s invocation fails.

### lacing.processors.clear_processors()

Drop every registered processor. For tests.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *async* lacing.processors.detect_density_change_points(, store, oplog, asset_id=None, bucket_seconds=1.0, min_delta=3, rate=1000, target_tier='density-change-points', actor='processor:detect_density_change_points')

Emit point markers wherever annotation density changes sharply.

Buckets all annotations by `floor(start_seconds / bucket_seconds)`
and emits a point marker on `target_tier` for each bucket boundary
where the count differs from the previous bucket by at least
`min_delta`. Lightweight stand-in for a real CPD algorithm — the
architecture is what matters.

* **Parameters:**
  * **store** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – Source store.
  * **oplog** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – Where to record emitted markers.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – If set, only consider annotations on this asset.
    `None` = consider all media-referenced annotations.
  * **bucket_seconds** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Bucket width.
  * **min_delta** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Minimum 

    ```
    |Δ count|
    ```

     to emit a marker.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Quantization rate for the new point intervals.
  * **target_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Output tier; created if missing.
  * **actor** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Provenance attribution.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
* **Returns:**
  `{"markers": <count>, "target_tier": <name>}`.

### *async* lacing.processors.low_confidence_review(, store, oplog, threshold=0.5, review_tier='for-review', actor='processor:low_confidence_review')

Flag low-confidence annotations by mirroring them onto a review tier.

* **Parameters:**
  * **store** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – The annotation store to scan + mutate.
  * **oplog** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – Where to record the new annotations.
  * **threshold** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Confidence below this triggers a review entry. `None`
    confidences are skipped (treated as full-confidence, since the
    user didn’t supply one).
  * **review_tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name of the tier to write review entries onto. Created
    if missing.
  * **actor** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Provenance `was_attributed_to` for review entries.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]
* **Returns:**
  `{"flagged": <count>, "review_tier": <name>}`.

### lacing.processors.register_processor(func=None, , name=None)

Register a processor under `name` (defaults to the function name).

The function may be sync or async; we wrap sync funcs to a coroutine.

### lacing.processors.registered_processors()

Names of every registered processor, sorted.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *async* lacing.processors.run_async(name, , store, oplog, \*\*kwargs)

Run a processor in the current event loop. For async callers.

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### lacing.processors.run_sync(name, , store, oplog, \*\*kwargs)

Run a processor synchronously and return its result.

If the processor is async, we call it via `asyncio.run` (when no
loop is running) or schedule and wait on it (when a loop is already
active). Most callers from sync code want the former.

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)
