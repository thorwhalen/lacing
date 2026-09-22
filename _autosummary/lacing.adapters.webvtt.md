# lacing.adapters.webvtt

WebVTT (W3C TimedText) adapter.

WebVTT is a flat caption format: one stream of cues, no tier hierarchy.
Cues have a start time, an end time, optional id and settings, and a payload
(text with limited inline markup).

We map cues to a single tier named `cues` (override with `tier=`).
Each cue becomes one `Annotation` whose body holds:

> {“text”: str, “id”: str | None, “settings”: dict[str, str]}

Lossy fields on dump:
: Provenance, confidence, schema URIs, and tier metadata are dropped.
  Only the text, id (if present), and settings are emitted.

Time discipline:
: WebVTT timestamps are `HH:MM:SS.mmm` or `MM:SS.mmm` (with milliseconds).
  Parsing goes through string fractions to avoid float ingestion. Default
  rate is 1000 (millisecond precision); override with `rate=` if your
  project uses a different canonical rate.

Spec: [https://www.w3.org/TR/webvtt1/](https://www.w3.org/TR/webvtt1/)

### Functions

| [`dump`](#lacing.adapters.webvtt.dump)(store[, target, tier])             | Write annotations as WebVTT.                              |
|------------------------------------------------------------------------------------------|-----------------------------------------------------------|
| [`load`](#lacing.adapters.webvtt.load)(source, \*[, rate, asset_id, ...]) | Parse a WebVTT file or string/bytes into a `MemoryStore`. |

### lacing.adapters.webvtt.dump(store, target=None, , tier=None, \*\*\_kwargs)

Write annotations as WebVTT.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Only annotations from `tier` (default: all
    tiers) with a `MediaRef` interval are emitted, sorted by start.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. If None, returns bytes (UTF-8).
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Restrict export to this tier. None = export all annotations.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.webvtt.load(source, , rate=1000, asset_id='webvtt:unspecified', attribution='anonymous', tier='cues', \*\*\_kwargs)

Parse a WebVTT file or string/bytes into a `MemoryStore`.

* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)
