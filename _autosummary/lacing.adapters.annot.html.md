# lacing.adapters.annot

`.annot` portable file format adapter.

The `.annot` file is a SQLite database with the schema defined in
`lacing.store.sqlite`. It’s the recommended portable handoff and archive
format (BACK-DOC §3.1: “SQLite-as-app-format” — Git-trackable,
email-attachable, single-file).

Unlike text-based adapters (TextGrid, WebVTT, JSON-LD), this one is
non-lossy: the full annotation envelope, references, body, body schema URI,
provenance, and confidence all round-trip exactly.

When loading, returns an in-memory `MemoryStore` for compatibility with
the rest of the adapter API. To open an `.annot` file as a *persistent*
store you can mutate, use `SqliteStore(path)` directly:

```pycon
>>> from lacing.store import SqliteStore
>>> store = SqliteStore("project.annot")  # writes go straight to disk
```

### Functions

| [`dump`](#lacing.adapters.annot.dump)(store[, target, overwrite])        | Write `store` as an `.annot` SQLite file.   |
|------------------------------------------------------------------------------------------|---------------------------------------------|
| [`load`](#lacing.adapters.annot.load)(source, \*[, persistent, migrate]) | Open an `.annot` file.                      |

### lacing.adapters.annot.dump(store, target=None, , overwrite=True, \*\*\_kwargs)

Write `store` as an `.annot` SQLite file.

* **Parameters:**
  * **store** ([`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)) – Source store. Can be any IntervalAnnotationStore.
  * **target** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Output path. None = return bytes.
  * **overwrite** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True (default), replace any existing file at `target`.
    If False and the file exists, raise `FileExistsError`.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.adapters.annot.load(source, , persistent=False, migrate=False, \*\*\_kwargs)

Open an `.annot` file.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path to an `.annot` file. Bytes input is supported by
    writing to a temp file first.
  * **persistent** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, return an open `SqliteStore` (writes go to
    the file). If False (default), return a `MemoryStore` snapshot.
  * **migrate** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Opt-in to upgrading a file written at an older store
    `schema_version` on open (see [`lacing.store.migrations`](lacing.store.migrations.html.md#module-lacing.store.migrations)).
    A stale file otherwise refuses with
    [`SchemaMismatchError`](lacing.store.sqlite.html.md#lacing.store.sqlite.SchemaMismatchError) — same
    contract as `SqliteStore`. For **bytes** input the copy in
    the temp file is migrated regardless: it is not the caller’s
    file, and refusing to read bytes that cannot be re-pointed at
    the migration CLI would be a dead end.
* **Return type:**
  [`IntervalAnnotationStore`](lacing.store.base.html.md#lacing.store.base.IntervalAnnotationStore)
* **Returns:**
  `MemoryStore` (default) or `SqliteStore` (if `persistent=True`).
