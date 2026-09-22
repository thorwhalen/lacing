# lacing.adapters

I/O adapter registry.

The core never imports a format module. Each adapter registers itself by
calling [`register_adapter()`](#lacing.adapters.register_adapter) at import time. Users opt in by importing
the adapter module:

> from lacing.adapters import textgrid  # noqa: F401  — registers itself

Or by using the convenience top-level loaders that look up by extension or
`media_type`.

### Functions

| [`dump`](#lacing.adapters.dump)(store[, target])                         | Convenience: serialize `store` via the named adapter.          |
|------------------------------------------------------------------------------------------------|----------------------------------------------------------------|
| [`find_adapter`](#lacing.adapters.find_adapter)(\*[, extension, media_type])     | Find an adapter by extension (case-insensitive) or media type. |
| [`get_adapter`](#lacing.adapters.get_adapter)(name)                             | Look up an adapter by name.                                    |
| [`load`](#lacing.adapters.load)(source, \*[, format])                    | Convenience: dispatch `source` to the right adapter.           |
| [`register_adapter`](#lacing.adapters.register_adapter)(\*, name, load, dump[, ...]) | Register an adapter.                                           |
| [`registered`](#lacing.adapters.registered)()                                  | All currently registered adapters (in registration order).     |

### Classes

| [`AdapterSpec`](#lacing.adapters.AdapterSpec)(name, extensions, media_types, ...)   | Registered adapter for one format.   |
|----------------------------------------------------------------------------------------------------|--------------------------------------|

### *class* lacing.adapters.AdapterSpec(name, extensions, media_types, load, dump, body_schema_uris=<factory>, description='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Registered adapter for one format.

### lacing.adapters.dump(store, target=None, , format, \*\*kwargs)

Convenience: serialize `store` via the named adapter.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.find_adapter(, extension=None, media_type=None)

Find an adapter by extension (case-insensitive) or media type.

* **Return type:**
  [`AdapterSpec`](#lacing.adapters.AdapterSpec) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.get_adapter(name)

Look up an adapter by name. Raises `KeyError` if missing.

* **Return type:**
  [`AdapterSpec`](#lacing.adapters.AdapterSpec)

### lacing.adapters.load(source, , format=None, \*\*kwargs)

Convenience: dispatch `source` to the right adapter.

If `format` is given, looks up by name. Otherwise, if `source` is a
path, infers from extension. Raises `ValueError` if it can’t pick.

* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)

### lacing.adapters.register_adapter(, name, load, dump, extensions=(), media_types=(), body_schema_uris=(), description='')

Register an adapter. Idempotent: re-registering the same name replaces.

* **Return type:**
  [`AdapterSpec`](#lacing.adapters.AdapterSpec)

### lacing.adapters.registered()

All currently registered adapters (in registration order).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`AdapterSpec`](#lacing.adapters.AdapterSpec)]

### Modules

| [`annot`](lacing.adapters.annot.html.md#module-lacing.adapters.annot)                   | `.annot` portable file format adapter.                            |
|-------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------|
| [`eaf`](lacing.adapters.eaf.html.md#module-lacing.adapters.eaf)                       | ELAN EAF adapter (Max Planck Institute's annotation tool format). |
| [`jams`](lacing.adapters.jams.html.md#module-lacing.adapters.jams)                     | JAMS (JSON Annotated Music Specification) adapter.                |
| [`label_studio`](lacing.adapters.label_studio.html.md#module-lacing.adapters.label_studio)     | Label Studio JSON adapter.                                        |
| [`otio`](lacing.adapters.otio.html.md#module-lacing.adapters.otio)                     | OpenTimelineIO (OTIO) adapter — NLE / video editing interchange.  |
| [`textgrid`](lacing.adapters.textgrid.html.md#module-lacing.adapters.textgrid)             | Praat TextGrid adapter.                                           |
| [`web_annotation`](lacing.adapters.web_annotation.html.md#module-lacing.adapters.web_annotation) | W3C Web Annotation Data Model adapter (JSON-LD).                  |
| [`webvtt`](lacing.adapters.webvtt.html.md#module-lacing.adapters.webvtt)                 | WebVTT (W3C TimedText) adapter.                                   |
