# lacing.adapters.otio

OpenTimelineIO (OTIO) adapter — NLE / video editing interchange.

OTIO is the Academy Software Foundation’s standard for video timeline
interchange. Per OSS-DOC, lacing’s `RationalTime` design is directly
inspired by OTIO’s — this adapter is the place where that parity pays
off.

## Mapping

OTIO                                     ↔ lacing
`Timeline`                             ↔ a project (one OTIO file = one store)
`Track`                                ↔ a tier (track `name` becomes tier name)
`Clip`                                 ↔ `Annotation` (interval = source_range

> offset onto the track timeline)

`Clip.media_reference.target_url`      ↔ `MediaRef.asset_id`
`Marker` (on Track or Clip)            ↔ point `Annotation`
`Clip.metadata` / `Marker.metadata`  ↔ `body['otio_metadata']`
`MarkerColor`                          ↔ `body['color']`

## Time

OTIO `RationalTime` maps to lacing `RationalTime` directly — same
`(value, rate)` shape. We re-quantize to the requested project rate
on load if needed; raises `LossyTimeConversionError` on inexact
conversions.

## Lossy on dump

- Per-annotation provenance (`was_attributed_to`, `was_derived_from`)
  is dropped — OTIO carries no per-clip annotator field.
- Confidence is dropped — OTIO has no equivalent.
- Track effects + transitions are dropped — out of lacing’s scope.
- Clips are emitted with an `ExternalReference` whose `target_url`
  is the `MediaRef.asset_id`.

Spec: [https://opentimelineio.readthedocs.io/](https://opentimelineio.readthedocs.io/)

### Functions

| [`dump`](#lacing.adapters.otio.dump)(store[, target, name])                     | Serialize `store` as an OTIO file.           |
|--------------------------------------------------------------------------------------------------|----------------------------------------------|
| [`load`](#lacing.adapters.otio.load)(source, \*[, rate, asset_id, attribution]) | Load an OTIO file/JSON into a `MemoryStore`. |

### lacing.adapters.otio.dump(store, target=None, , name='lacing', \*\*\_kwargs)

Serialize `store` as an OTIO file.

Each tier becomes one Track. Annotations whose body has
`kind=='marker'` are emitted as `Marker``s on the track at their
interval start. Annotations whose body has ``kind=='clip'` (or no
explicit kind) become Clips with `ExternalReference` to the
`asset_id` and `source_range` matching the lacing interval.

#### NOTE
lacing intervals are absolute positions; OTIO clips are
sequential within a track. We sort + place clips back-to-back per
tier; gaps between intervals become explicit `Gap` items.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.otio.load(source, , rate=24000, asset_id=None, attribution='anonymous', \*\*\_kwargs)

Load an OTIO file/JSON into a `MemoryStore`.

Each track becomes a tier. Each clip becomes one `Annotation` with
`MediaRef` pointing at the clip’s media reference (or the
`asset_id` override). Markers on the timeline, track, or clip
become point `Annotation``s on a ``markers` tier.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path or bytes containing OTIO JSON.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Quantization rate.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override media reference for every clip. None = use
    each clip’s own `media_reference.target_url`.
  * **attribution** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to` value.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)
