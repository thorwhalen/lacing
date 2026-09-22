# lacing.tracks

High-level “track-shaped” facades on top of `lacing`.

A `track` is an opinionated bundle of tiers that shows up in the wild
together. `subtitle` is the canonical example: `sections`,
`lines`, `words` over one audio asset, with a builder that hides
the `Annotation` / `MediaRef` / `Provenance` plumbing and a
query layer that takes `float` seconds instead of `RationalTime`.

These facades sit *on top of* the core store/tier/annotation API —
they don’t introduce new storage. Anything you can build with a
track facade can be built with the raw API; the facade just makes
the common case ergonomic and consistent.

### Functions

| [`register_subtitle_schemas`](#lacing.tracks.register_subtitle_schemas)()   | Register permissive body validators for the subtitle URIs.   |
|--------------------------------------------------------------------------------|--------------------------------------------------------------|

### Classes

| [`SubtitleBuilder`](#lacing.tracks.SubtitleBuilder)(store, \*, asset_id[, rate, ...])   | Builder for `(sections, lines, words)` tiers over one asset.   |
|------------------------------------------------------------------------------------------------------|----------------------------------------------------------------|
| [`SubtitleTrack`](#lacing.tracks.SubtitleTrack)(store, \*, asset_id[, rate])          | Read-side facade for `(sections, lines, words)` over an asset. |

### *class* lacing.tracks.SubtitleBuilder(store, , asset_id, rate=1000, was_generated_by='lacing.tracks.subtitle', was_attributed_to='lacing', ensure_tiers=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Builder for `(sections, lines, words)` tiers over one asset.

The builder is a context manager *only as a convenience*; it has no
transactional semantics. Calling `.section()` / `.line()` /
`.word()` writes immediately, in the order given.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Any `IntervalAnnotationStore` (memory, sqlite, postgres).
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `MediaRef.asset_id` to attach every annotation
    to. Typically a path or content-hash of the audio file.
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Tick rate for time intervals. Defaults to 1000 (ms).
  * **was_generated_by** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_generated_by`. Defaults to
    `"lacing.tracks.subtitle"`.
  * **was_attributed_to** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `Provenance.was_attributed_to`.
  * **ensure_tiers** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True (default), creates the three tiers if
    they don’t exist. Pass False if your store uses different
    tier names and you’ve created them yourself.

#### add(, tier, body_schema_uri, body, start_s, end_s)

Add an annotation to `tier` with explicit schema/body.

* **Return type:**
  `_BuiltAnnotation`

#### line(text, start_s, end_s, , line_index=None, section='', words=(), extra=None)

Add a lyric line. `words` is an optional list of
`(text, start, end)` or `(text, start, end, confidence)`
tuples that will be inserted on the `words` tier.

* **Return type:**
  `_BuiltAnnotation`

#### section(label, start_s, end_s, , title='', energy='', mood='', extra=None)

Add a song section.

* **Return type:**
  `_BuiltAnnotation`

#### word(text, start_s, end_s, , line_index=None, confidence=None, extra=None)

Add one word.

* **Return type:**
  `_BuiltAnnotation`

### *class* lacing.tracks.SubtitleTrack(store, , asset_id, rate=1000)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Read-side facade for `(sections, lines, words)` over an asset.

Methods take `float` seconds; conversions to `RationalTime` are
handled internally. Returned annotations are sorted by start time.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Any `IntervalAnnotationStore`.
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – When set, query results are filtered to annotations
    whose `MediaRef.asset_id` equals this value. Pass
    `None` to ignore asset filtering (rarely what you want).
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Tick rate used to build query intervals.

#### lines_in(start_s, end_s)

Lines that overlap `[start_s, end_s]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### sections_covering(t)

Sections whose interval contains `t` (typically one).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### words_in(start_s, end_s)

Words that overlap `[start_s, end_s]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

### lacing.tracks.register_subtitle_schemas()

Register permissive body validators for the subtitle URIs.

Calling this is *optional*; the builder works fine without
registered schemas. Use it when you want body-shape errors to
surface at write time rather than later.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### Modules

| [`subtitle`](lacing.tracks.subtitle.html.md#module-lacing.tracks.subtitle)   | Subtitle / lyric / caption tracks — the (sections, lines, words) trio.   |
|-------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
