# lacing.adapters.web_annotation

W3C Web Annotation Data Model adapter (JSON-LD).

W3C Web Annotation is the closest thing to a universal annotation standard
[ANN-DOC §A]. Each annotation is a JSON-LD object with `body`, `target`,
`creator`, `created`, and a `motivation`.

We map W3C annotations onto lacing’s envelope as follows:

> target.source                   -> MediaRef.asset_id
> target.selector (FragmentSelector with t=…) -> MediaRef.interval (or point)
> body                            -> Annotation.body[‘body’] (passthrough)
> motivation                      -> Annotation.body[‘motivation’]
> creator (string or dict)        -> Provenance.was_attributed_to
> created (xsd:dateTime ISO 8601) -> preserved in body[‘created’] as string

> > (cannot be exact in RationalTime)

> Annotation.tier                 -> body[‘tier’] OR mapped from motivation

We support the **Media Fragment URI** time selector `#t=<start>,<end>` per
W3C Media Fragments spec ([https://www.w3.org/TR/media-frags/](https://www.w3.org/TR/media-frags/)). Times are
parsed as decimal seconds via `Fraction(str)`.

Lossy fields:

> - W3C `created` is xsd:dateTime — kept as a string in the body, not
>   mapped to `Provenance.generated_at_time`.
> - Multi-target annotations: only the first target is honored.
> - Selectors other than FragmentSelector with `t=` and TextQuoteSelector
>   are preserved verbatim in body[‘selector’] but not interpreted.

Spec: [https://www.w3.org/TR/annotation-model/](https://www.w3.org/TR/annotation-model/)

### Functions

| [`dump`](#lacing.adapters.web_annotation.dump)(store[, target, as_collection, pretty])   | Serialize `store` as W3C Web Annotation JSON-LD.         |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------|
| [`load`](#lacing.adapters.web_annotation.load)(source, \*[, rate, asset_id, tier])       | Load a W3C Web Annotation document into a `MemoryStore`. |

### lacing.adapters.web_annotation.dump(store, target=None, , as_collection=True, pretty=True, \*\*\_kwargs)

Serialize `store` as W3C Web Annotation JSON-LD.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Only annotations with a `MediaRef` interval
    are exported.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. None = return bytes.
  * **as_collection** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, wrap output as an `AnnotationCollection`
    with an `items` array. If False and the store has a single
    annotation, emit it bare.
  * **pretty** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Pretty-print with 2-space indent.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.web_annotation.load(source, , rate=1000, asset_id=None, tier='annotations', \*\*\_kwargs)

Load a W3C Web Annotation document into a `MemoryStore`.

Accepts a single annotation, an AnnotationCollection/AnnotationPage
(`items`), or a JSON list at the top level.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path, bytes, or JSON string.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Quantization rate.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override target source for all annotations. None = use
    each annotation’s own `target.source`.
  * **tier** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Tier name to assign annotations that have no explicit
    `body['tier']` value.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.md#lacing.store.base.IntervalAnnotationStore)
