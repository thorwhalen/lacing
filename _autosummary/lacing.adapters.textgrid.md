# lacing.adapters.textgrid

Praat TextGrid adapter.

Praat TextGrids have two tier types: `IntervalTier` (ranges) and
`PointTier` (instants — Praat’s own `TextTier`). lacing maps both to a
single `Annotation` envelope; point annotations use a zero-length
`TimeInterval` (`start == end`). See ANN-DOC §B and the
`lacing-adapter-authoring` skill.

Lossy fields:
: Praat has no provenance, no schema URIs, and no confidence. On load we
  synthesize provenance with `was_generated_by="adapter:textgrid"`.
  On dump we drop everything but `tier`, `interval` (or point), and
  `body['text']` (or the raw `body` repr if no `text` key).

Time discipline:
: Praat stores times as ASCII decimal strings — these can be exact at
  common rates. We convert through `Fraction(str)` to avoid float
  ingestion. Default rate is `DEFAULT_RATE` (24000); pass `rate=` to
  override.

Tier stereotype mapping:
: ELAN tier stereotypes have no Praat equivalent. Every loaded tier gets
  stereotype `NONE`. On dump, only the `tier` *name* is preserved.

### Functions

| [`dump`](#lacing.adapters.textgrid.dump)(store[, target, format, include_empty])   | Write a `IntervalAnnotationStore` as a Praat TextGrid.   |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------|
| [`load`](#lacing.adapters.textgrid.load)(source, \*[, rate, asset_id, ...])        | Load a TextGrid file or bytes into a `MemoryStore`.      |

### lacing.adapters.textgrid.dump(store, target=None, , format='long_textgrid', include_empty=True, \*\*\_kwargs)

Write a `IntervalAnnotationStore` as a Praat TextGrid.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Only annotations with a `MediaRef` interval
    are exported; timeless (`AnnotationRef` without sub-interval)
    annotations are silently dropped.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. If None, returns bytes.
  * **format** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – One of praatio’s formats: `"long_textgrid"`,
    `"short_textgrid"`, `"json"`.
  * **include_empty** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether to emit empty-label intervals on point tiers.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.textgrid.load(source, , rate=24000, asset_id='textgrid:unspecified', attribution='anonymous', include_empty=True, \*\*\_kwargs)

Load a TextGrid file or bytes into a `MemoryStore`.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path or bytes containing TextGrid content.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Quantization rate for converted times.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `MediaRef.asset_id` to attach to every annotation.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to` value.
  * **include_empty** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If False, drop intervals/points with empty labels.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)
