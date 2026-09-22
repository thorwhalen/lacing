# lacing.store.sqlite

SQLite-backed annotation store and the `.annot` portable file format.

A `SqliteStore` is both:

1. A persistent backend implementing the `IntervalAnnotationStore`
   protocol over a single SQLite file.
2. The on-disk shape of the `.annot` portable handoff format
   (BACK-DOC §3.1: “SQLite-as-app-format” — Git-trackable,
   email-attachable, single-file).

Design notes:

- The integer pair `(start_value, start_rate)` and `(end_value, end_rate)`
  are the **source of truth** for time. Rational arithmetic stays exact.
- The R\*Tree index uses `REAL` (float seconds) because SQLite’s R\*Tree
  requires it. We treat R\*Tree results as a **pre-filter** and re-check
  boundary cases against the integer-pair columns. Any annotation whose
  rational seconds matches the query’s bounds exactly will still be
  filtered correctly because we widen the R\*Tree query by one ULP.
- Tier hierarchy is enforced via FK; stereotype validation is the
  application’s job (see `lacing.tier.validate_tier_constraint`).
- `schema_version` lives in the `meta` table; migrations register
  upgrade functions keyed on the from-version in
  [`lacing.store.migrations`](lacing.store.migrations.md#module-lacing.store.migrations) (the store-level counterpart of the
  > body ladder in [`lacing.schema`](lacing.schema.md#module-lacing.schema)). Opening a stale file refuses
  > unless asked to migrate (`SqliteStore(path, migrate=True)` or
  > `lacing migrate <path>`), and refuses *before* touching the file.

See `lacing-architecture` (Phase 1) and BACK-DOC §3.1 for the why.

### Module Attributes

| [`SCHEMA_VERSION`](#lacing.store.sqlite.SCHEMA_VERSION)   | Current `.annot` schema version.   |
|-------------------------------------------------------------------|------------------------------------|

### Functions

| [`from_memory`](#lacing.store.sqlite.from_memory)(memory_store, target)   | Persist an in-memory store to a new `.annot` file.   |
|--------------------------------------------------------------------------------------|------------------------------------------------------|
| [`to_memory`](#lacing.store.sqlite.to_memory)(sqlite_store)             | Load a `.annot` file fully into a `MemoryStore`.     |

### Classes

| [`SqliteStore`](#lacing.store.sqlite.SqliteStore)(path, \*[, check_same_thread, ...])   | SQLite-backed `IntervalAnnotationStore`.   |
|----------------------------------------------------------------------------------------------------|--------------------------------------------|

### Exceptions

| [`SchemaMismatchError`](#lacing.store.sqlite.SchemaMismatchError)   | Raised when opening a `.annot` file with an incompatible schema.   |
|------------------------------------------------------------------------|--------------------------------------------------------------------|

### lacing.store.sqlite.SCHEMA_VERSION *= 2*

Current `.annot` schema version. Increment + register a migration
([`lacing.store.migrations.register_store_migration()`](lacing.store.migrations.md#lacing.store.migrations.register_store_migration), with
`store_kind="sqlite"`) when making a breaking change to the table
layout.

v2 (lacing#14, defect D5): `prov_was_derived_from` may contain 64-hex
artifact `asset_id` strings alongside annotation UUIDs. The table layout
and every existing row are unchanged — the bump exists because \*\*pre-v2
builds eagerly `UUID()`-parse the column on read\*\* and crash on the
first asset id, so they must refuse v2 files instead of opening them and
failing row-by-row. The v1→v2 migration step is accordingly stamp-only
(see [`lacing.store.migrations`](lacing.store.migrations.md#module-lacing.store.migrations)).

Operational caveat: the version gate runs at **open**. A pre-v2 build’s
already-open connection survives the stamp and keeps reading — safe until
some v2 writer mints an asset-id ref, at which point it fails as a raw
`ValueError` mid-read rather than a refusal. Restart long-lived
pre-v2 services after migrating a file they serve.

### *exception* lacing.store.sqlite.SchemaMismatchError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when opening a `.annot` file with an incompatible schema.

### *class* lacing.store.sqlite.SqliteStore(path, , check_same_thread=True, migrate=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

SQLite-backed `IntervalAnnotationStore`.

* **Parameters:**
  * **path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path to the `.annot` file. Use `":memory:"` for an
    ephemeral in-memory database.
  * **check_same_thread** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Forwarded to `sqlite3.connect`. We hold a
    single connection guarded by a lock; pass `False` when
    sharing across threads.
  * **migrate** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Opt-in to upgrading a file written at an older
    `schema_version` on open, via the ladder in
    [`lacing.store.migrations`](lacing.store.migrations.md#module-lacing.store.migrations). Off by default — silently
    rewriting someone’s file on open is worse than refusing.
    Every open-time schema failure — refusal *or* failed migration
    — raises [`SchemaMismatchError`](#lacing.store.sqlite.SchemaMismatchError); a failed migration
    chains the ladder’s `StoreMigrationError` as its cause.

### lacing.store.sqlite.from_memory(memory_store, target)

Persist an in-memory store to a new `.annot` file.

* **Return type:**
  [`SqliteStore`](#lacing.store.sqlite.SqliteStore)

### lacing.store.sqlite.to_memory(sqlite_store)

Load a `.annot` file fully into a `MemoryStore`.
