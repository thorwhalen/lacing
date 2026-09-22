# lacing.adapters.eaf

ELAN EAF adapter (Max Planck Institute’s annotation tool format).

EAF is the canonical format for tier-hierarchy annotation. Every Phase 0
adapter modeled flat tiers; this is the first that exercises lacing’s
stereotype constraint model end-to-end (TIME_SUBDIVISION, INCLUDED_IN,
SYMBOLIC_SUBDIVISION, SYMBOLIC_ASSOCIATION). See ANN-DOC §B and OSS-DOC
tier-2.4.

## Mapping

EAF                                    ↔ lacing
`TIER_ID`                            ↔ `Tier.name`
`PARENT_REF`                         ↔ `Tier.parent`
`LINGUISTIC_TYPE_REF` + `CONSTRAINTS` ↔ `Tier.stereotype`
`ALIGNABLE_ANNOTATION`               ↔ `Annotation` with `MediaRef`
`ANNOTATION_VALUE`                   ↔ `body['text']`
`MEDIA_DESCRIPTOR / MEDIA_URL`       ↔ `MediaRef.asset_id` (when present)

## Time

EAF stores ALL times as integer milliseconds (the format requires it).
We map directly to `RationalTime(ms, rate=1000)` — exact, no floats.
Pass `rate=` to re-quantize to a different project rate (must be
exact; raises `LossyTimeConversionError` otherwise).

## Lossy on dump

- ELAN provenance is at the document level (`AUTHOR`, `DATE`); per-
  annotation provenance and confidence are dropped.
- `REF_ANNOTATION` (annotations referencing parent annotations rather
  than time slots) is **not yet supported**; the loader emits
  `ALIGNABLE_ANNOTATION` data only. Round-trip of REF annotations is
  Phase 2 work.
- `CV_REF` controlled vocabularies are not preserved.
- The ELAN `default` empty tier and `default-lt` linguistic type
  (auto-created by pympi) are filtered out on load if they have no
  annotations.

Spec: [https://www.mpi.nl/tools/elan/EAFv3.0.xsd](https://www.mpi.nl/tools/elan/EAFv3.0.xsd)

### Functions

| [`dump`](#lacing.adapters.eaf.dump)(store[, target, pretty, media_url])   | Write annotations as an ELAN EAF file.      |
|---------------------------------------------------------------------------------------------|---------------------------------------------|
| [`load`](#lacing.adapters.eaf.load)(source, \*[, rate, asset_id, ...])    | Load an ELAN EAF file into a `MemoryStore`. |

### lacing.adapters.eaf.dump(store, target=None, , pretty=True, media_url=None, \*\*\_kwargs)

Write annotations as an ELAN EAF file.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Only annotations with `MediaRef` and a
    non-None interval are exported.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. None = return bytes.
  * **pretty** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Pretty-print XML (default True).
  * **media_url** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional `MEDIA_URL` for `MEDIA_DESCRIPTOR`. If
    None and the store has annotations, use the first MediaRef’s
    `asset_id`.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.eaf.load(source, , rate=24000, asset_id=None, attribution='anonymous', drop_default_tier=True, \*\*\_kwargs)

Load an ELAN EAF file into a `MemoryStore`.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path or bytes containing EAF XML.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Quantization rate (default `DEFAULT_RATE`). EAF times are
    milliseconds; conversions must be exact.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override media reference. None = use the first
    `MEDIA_DESCRIPTOR/MEDIA_URL` from the EAF, or the default.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to` value.
  * **drop_default_tier** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True (default), filter out the empty
    `default` tier auto-created by pympi.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)
