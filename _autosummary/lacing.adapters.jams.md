# lacing.adapters.jams

JAMS (JSON Annotated Music Specification) adapter.

JAMS is the standard MIR (Music Information Retrieval) annotation format.
Each `Annotation` carries a *namespace* (`chord`, `beat`, `key`,
`segment_open`, `tag_open`, …) that defines the type of its
observations. We map JAMS namespaces to lacing **tiers**, observations to
`Annotation` rows, and each observation’s typed `value` into the lacing
body envelope.

## Mapping

JAMS                                ↔ lacing
`Annotation.namespace`            ↔ `Tier.name`
`Observation.time, .duration`     ↔ `MediaRef.interval` (half-open)
`Observation.value`               ↔ `body['value']` (namespace-typed)
`Observation.confidence`          ↔ `Annotation.confidence`
`annotation_metadata.annotator`   ↔ `Provenance.was_attributed_to`
`file_metadata.identifiers/title` ↔ `MediaRef.asset_id`

## Body schema

We use a single generic body schema URI:

> annot://schema/jams-observation/v1

with shape `{"value": <namespace-typed>, "namespace": <str>}`. Registering
namespace-specific Pydantic body schemas (one per JAMS namespace) is left to
downstream packages — JAMS namespaces are extensible and we don’t want the
adapter to impose a fixed catalog.

## Time

JAMS times are float seconds. We convert at the parse boundary via
`Fraction(repr(...))` to recover exact rational values. Default rate is
`DEFAULT_RATE` (24000); pass `rate=` to use a different project rate.
`LossyTimeConversionError` is raised if any observation can’t be exactly
represented.

## Lossy on dump

- Per-annotation provenance beyond `annotator` (`was_derived_from`,
  `was_generated_by`, `activity`) is dropped — JAMS has no
  corresponding fields.
- `body['note']` and other extra body fields are dropped: only
  `body['value']` round-trips.
- File-level `identifiers` and `title` are populated from the first
  annotation’s `MediaRef.asset_id` if available.

Spec: [https://jams.readthedocs.io/](https://jams.readthedocs.io/)

### Functions

| [`dump`](#lacing.adapters.jams.dump)(store[, target, title, artist, duration])   | Serialize `store` as a JAMS file.               |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------|
| [`load`](#lacing.adapters.jams.load)(source, \*[, rate, asset_id, attribution])  | Load a JAMS file or bytes into a `MemoryStore`. |

### lacing.adapters.jams.dump(store, target=None, , title='', artist='', duration=None, \*\*\_kwargs)

Serialize `store` as a JAMS file.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Only annotations with a `MediaRef` interval
    and a `body['value']` are exported.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. None = return bytes.
  * **title** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `file_metadata.title` value.
  * **artist** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `file_metadata.artist` value.
  * **duration** ([`float`](https://docs.python.org/3/builtins/functions.html#float) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – `file_metadata.duration` (seconds). If None, computed
    as the maximum end-time across all annotations.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.jams.load(source, , rate=24000, asset_id=None, attribution=None, \*\*\_kwargs)

Load a JAMS file or bytes into a `MemoryStore`.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path or bytes containing JAMS JSON.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Quantization rate.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override media reference. None = derive from
    `file_metadata.identifiers` or `title`.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override per-annotation attribution. None = use each
    annotation’s own annotator/curator.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)
