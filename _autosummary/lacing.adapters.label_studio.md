# lacing.adapters.label_studio

Label Studio JSON adapter.

Label Studio is a popular labeling tool whose canonical export shape is
a JSON array of *tasks*, each with one or more *annotations* containing
typed *results*. We focus on time-interval results (the `Audio`,
`Video`, and `TimeSeries` labeling controls) since lacing is an
interval-annotation system.

## Mapping

Label Studio                                ↔ lacing
`data.audio` / `data.video` / `data.url` ↔ `MediaRef.asset_id`
`result.from_name`                        ↔ `Tier.name`
`result.value.{start, end}` (seconds)     ↔ `MediaRef.interval`
`result.value.labels` (list of strings)   ↔ `body['labels']`
`annotation.completed_by` (or `user`)   ↔ `Provenance.was_attributed_to`
`result.origin` (“prediction”/…)        → `confidence` heuristic
`result.id`                               → preserved in body
`result.type`                             → preserved in body

## Lossy on dump

- Per-result Label Studio metadata (`image_rotation`,
  `original_width`, etc.) is dropped — they’re irrelevant for time
  intervals.
- Predictions vs annotations distinction is collapsed: lacing tracks
  AI vs human via `confidence` and `provenance.was_generated_by`,
  and we set Label Studio’s `origin` to `manual` on dump.
- Multi-annotator support: only one annotation per task is emitted on
  dump (the first), since lacing’s per-annotation provenance fits
  Label Studio’s per-task `annotations` list awkwardly.

Spec: [https://labelstud.io/guide/export.html](https://labelstud.io/guide/export.html)

### Functions

| [`dump`](#lacing.adapters.label_studio.dump)(store[, target, pretty])                   | Serialize `store` as a Label Studio JSON export.      |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| [`load`](#lacing.adapters.label_studio.load)(source, \*[, rate, asset_id, attribution]) | Load a Label Studio JSON export into a `MemoryStore`. |

### lacing.adapters.label_studio.dump(store, target=None, , pretty=True, \*\*\_kwargs)

Serialize `store` as a Label Studio JSON export.

Annotations are grouped by `MediaRef.asset_id` — each asset becomes
one task with a single `annotations[0]` entry collecting every
region. `confidence < 0.5` flips the result into Label Studio’s
`predictions` slot rather than `annotations`.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.label_studio.load(source, , rate=24000, asset_id=None, attribution=None, \*\*\_kwargs)

Load a Label Studio JSON export into a `MemoryStore`.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path, bytes, or JSON string. Accepts both an array of
    tasks and a single task dict.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Quantization rate.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override the resolved asset for every annotation.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override per-annotation attribution.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)
