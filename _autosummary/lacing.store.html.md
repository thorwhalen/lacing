# lacing.store

Interval-keyed annotation stores.

Public surface: `IntervalAnnotationStore` (the facade), `MemoryStore`,
`SqliteStore` (the `.annot` on-disk format), the optional
`PostgresStore`, and the store-schema migration ladder
([`lacing.store.migrations`](lacing.store.migrations.html.md#module-lacing.store.migrations)).

### Functions

| [`register_store_migration`](#lacing.store.register_store_migration)(\*, store_kind, ...)   | Register a forward store migration from `from_version` to `to_version`.   |
|--------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`migrate_annot_file`](#lacing.store.migrate_annot_file)(path, \*[, to_version])      | Migrate a `.annot` file in place, returning `(from, to)` versions.        |
| [`reachable_versions`](#lacing.store.reachable_versions)(store_kind, from_version)    | Versions reachable from `from_version` by chaining registered steps.      |
| [`rebuild_annotations_rtree`](#lacing.store.rebuild_annotations_rtree)(conn)                 | Rebuild the interval index from the `annotations` table, in place.        |
| [`get_pool`](#lacing.store.get_pool)(connection_string, \*\*pool_kwargs)    | Return a process-wide `psycopg_pool.ConnectionPool` for a conninfo.       |
| [`close_all_pools`](#lacing.store.close_all_pools)()                               | Close every registered connection pool (test teardown / shutdown).        |

### Classes

| [`IntervalAnnotationStore`](#lacing.store.IntervalAnnotationStore)(\*args, \*\*kwargs)       | Protocol for any interval-keyed annotation store.                  |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------|
| [`MemoryStore`](#lacing.store.MemoryStore)()                                     | `IntervalAnnotationStore` implementation over `intervaltree`.      |
| [`SqliteStore`](#lacing.store.SqliteStore)(path, \*[, check_same_thread, ...])   | SQLite-backed `IntervalAnnotationStore`.                           |
| [`PostgresStore`](#lacing.store.PostgresStore)(connection_string, \*[, rate, ...]) | PostgreSQL-backed `IntervalAnnotationStore`, scoped to one tenant. |

### Exceptions

| [`SchemaMismatchError`](#lacing.store.SchemaMismatchError)   | Raised when opening a `.annot` file with an incompatible schema.                |
|------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`StoreMigrationError`](#lacing.store.StoreMigrationError)   | Raised when a store migration step is missing or fails.                         |
| [`PgSchemaMismatchError`](#lacing.store.PgSchemaMismatchError) | Raised on opening a database whose schema_version differs.                      |
| [`TierOverlapError`](#lacing.store.TierOverlapError)      | Raised when an insert would violate a per-tier no-overlap constraint.           |
| [`RateMismatchError`](#lacing.store.RateMismatchError)     | Raised when an annotation's interval cannot be represented at the project rate. |

### *class* lacing.store.IntervalAnnotationStore(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Protocol for any interval-keyed annotation store.

Conceptually a `MutableMapping[TimeInterval, list[Annotation]]`: keys
are `TimeInterval`; values are lists because multiple annotations can
share an interval (different tiers, multiple annotators, soft labels).

We use `Protocol` rather than inheriting from `MutableMapping` so
backends (in-memory, SQLite, Postgres) can structurally conform without
forcing a single class hierarchy. The mapping methods below match the
`MutableMapping` ABC; concrete backends like [`MemoryStore`](#lacing.store.MemoryStore)
implement the full interface.

#### add(annotation)

Append `annotation` to the list at its reference interval.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### all()

Iterate every annotation in the store, order unspecified.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### at_tier(tier_name, query)

Annotations on `tier_name` that intersect `query`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### by_tier(tier_name)

All annotations on `tier_name`, regardless of interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### contains(query)

Annotations whose interval strictly contains `query` (Allen `di`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### during(query)

Annotations whose interval is strictly inside `query` (Allen `d`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### equals(query)

Allen `=`: identical interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### extend(annotations)

Add many; equivalent to repeated `.add` but adapters can optimize.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### finishes(query)

Allen `f`: later start, same end.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### intersects(query)

Annotations whose interval shares any time with `query`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### meets(query)

Allen `m`: `a.end == q.start`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### overlaps(query)

Strict Allen `o`: `a.start < q.start < a.end < q.end`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### relate(query, relations)

Annotations whose interval has any of the named `relations` to `query`.

Generic dispatch — useful when relations are computed at runtime.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### remove(annotation_id)

Remove and return the annotation with this id, or None if absent.

* **Return type:**
  [`Annotation`](lacing.model.html.md#lacing.model.Annotation) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### starts(query)

Allen `s`: same start, earlier end.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### tiers()

Registered tiers. Annotations may reference tiers not yet registered;
callers decide whether that’s an error.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Tier`](lacing.tier.html.md#lacing.tier.Tier)]

### *class* lacing.store.MemoryStore

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`IntervalAnnotationStore` implementation over `intervaltree`.

Conforms to the protocol in `lacing.store.base`. We don’t formally
inherit from `IntervalAnnotationStore` because it’s a `Protocol`
with method bodies — structural typing is enough.

### *exception* lacing.store.PgSchemaMismatchError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised on opening a database whose schema_version differs.

### *class* lacing.store.PostgresStore(connection_string, , rate=24000, owner_id='default', project_id='default', autocommit=True, use_pool=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

PostgreSQL-backed `IntervalAnnotationStore`, scoped to one tenant.

A store instance is bound to one `(owner_id, project_id)` pair; multiple
instances over the same database (different project ids) coexist without
seeing each other’s annotations or tiers (see the module docstring on
multi-tenancy). The mapping/Allen/tier surface is unchanged — the tenant
scoping is transparent.

* **Parameters:**
  * **connection_string** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – A psycopg-compatible conninfo URL, or a kwargs dict
    (`host`/`port`/`user`/`password`/`dbname`).
  * **rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Project-wide rate for *this* `(owner, project)`. Set on first
    init for the pair; re-opening the same pair with a different rate
    raises [`PgSchemaMismatchError`](#lacing.store.PgSchemaMismatchError). Different projects in the
    same DB may have different rates.
  * **owner_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Tenant owner. Defaults to `DEFAULT_OWNER_ID` — the
    forward seam for the access layer (reelee#174); enforcement deferred.
  * **project_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Logical project key. Defaults to `DEFAULT_PROJECT_ID`.
    `nw` passes the project’s `project_asset_id` here.
  * **autocommit** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True (default), statements run in their own transaction.
  * **use_pool** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True (default) and the connection is given as a string,
    borrow a connection from a process-wide pool keyed by the conninfo
    (amortizes per-op connect cost; see [`get_pool()`](#lacing.store.get_pool)). Falls back to
    a dedicated connection when `psycopg_pool` is unavailable, when the
    connection is given as a dict, or when `use_pool=False`.

#### add_tier(tier, , enforce_no_overlap=False)

Add or update a tier.

* **Parameters:**
  * **tier** ([`Tier`](lacing.tier.html.md#lacing.tier.Tier)) – Tier definition.
  * **enforce_no_overlap** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, install a per-tier `EXCLUDE USING
    GIST` constraint forbidding overlapping annotations within
    this tier. Required for proper TIME_SUBDIVISION enforcement.
    Cannot be toggled after the tier has annotations.
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *exception* lacing.store.RateMismatchError

Bases: [`LossyTimeConversionError`](lacing.time.html.md#lacing.time.LossyTimeConversionError)

Raised when an annotation’s interval cannot be represented at the project rate.

### *exception* lacing.store.SchemaMismatchError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when opening a `.annot` file with an incompatible schema.

### *class* lacing.store.SqliteStore(path, , check_same_thread=True, migrate=False)

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
    [`lacing.store.migrations`](lacing.store.migrations.html.md#module-lacing.store.migrations). Off by default — silently
    rewriting someone’s file on open is worse than refusing.
    Every open-time schema failure — refusal *or* failed migration
    — raises [`SchemaMismatchError`](#lacing.store.SchemaMismatchError); a failed migration
    chains the ladder’s `StoreMigrationError` as its cause.

### *exception* lacing.store.StoreMigrationError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when a store migration step is missing or fails.

### *exception* lacing.store.TierOverlapError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when an insert would violate a per-tier no-overlap constraint.

### lacing.store.close_all_pools()

Close every registered connection pool (test teardown / shutdown).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.store.get_pool(connection_string, \*\*pool_kwargs)

Return a process-wide `psycopg_pool.ConnectionPool` for a conninfo.

One pool per distinct `connection_string` (the keying happens here, not at
the call-site), created lazily on first request. Raises [`ImportError`](https://docs.python.org/3/builtins/exceptions.html#ImportError)
if `psycopg_pool` is not installed — callers that want a graceful fallback
catch it (see [`PostgresStore`](#lacing.store.PostgresStore)).

* **Parameters:**
  * **connection_string** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – psycopg conninfo URL (the registry key).
  * **\*\*pool_kwargs** – forwarded to `ConnectionPool` on
    first creation (e.g. `min_size`, `max_size`); ignored on reuse.
* **Returns:**
  The shared pool for this conninfo.

### lacing.store.migrate_annot_file(path, , to_version=None)

Migrate a `.annot` file in place, returning `(from, to)` versions.

`to_version` defaults to the current build’s
[`lacing.store.sqlite.SCHEMA_VERSION`](lacing.store.sqlite.html.md#lacing.store.sqlite.SCHEMA_VERSION). Already-current files are a
no-op (`from == to`). Each step runs in its own `BEGIN IMMEDIATE`
transaction with the version re-checked under the lock, so concurrent
migrators converge and an interrupted chain resumes from the last
version that completed (idempotent).

Raises [`StoreMigrationError`](#lacing.store.StoreMigrationError) when the file does not exist, is
not a `.annot` file, a step is missing, fails, or breaks one of the
runner’s in-transaction guarantees.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### lacing.store.reachable_versions(store_kind, from_version)

Versions reachable from `from_version` by chaining registered steps.

Ascending, excluding `from_version` itself. Empty when no step leaves
`from_version` — which is what a refusal message should say out loud
instead of the bare “run a migration” it used to say.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### lacing.store.rebuild_annotations_rtree(conn)

Rebuild the interval index from the `annotations` table, in place.

For use *inside* a migration step after a table rebuild. Reproduces the
store’s ULP-widening contract (bounds widened by one float ULP so
float→exact-bound comparisons never drop hits — see
[`lacing.store.sqlite`](lacing.store.sqlite.html.md#module-lacing.store.sqlite)). Returns the number of rows indexed.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### lacing.store.register_store_migration(, store_kind, from_version, to_version)

Register a forward store migration from `from_version` to `to_version`.

The decorated function takes the backend’s open connection and must
perform every change of the step — DDL, row rewrites, and the
`meta.schema_version` write. Steps must be one version at a time
(`to_version == from_version + 1`); the runner chains them.

Step authors: read the module docstring’s rules — no `executescript`
/ `COMMIT` / `ROLLBACK` inside a step, preserve rowids on table
rebuilds, and rebuild the interval index with
[`rebuild_annotations_rtree()`](#lacing.store.rebuild_annotations_rtree) if the `annotations` table was
rebuilt.

Re-registering the same `(store_kind, from_version)` pair replaces the
previous entry.

### Modules

| [`base`](lacing.store.base.html.md#module-lacing.store.base)             | `IntervalAnnotationStore` — the headline Pythonic API.                      |
|--------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`memory`](lacing.store.memory.html.md#module-lacing.store.memory)         | In-memory annotation store backed by an interval tree.                      |
| [`migrations`](lacing.store.migrations.html.md#module-lacing.store.migrations) | Store-level schema migrations — the on-disk counterpart of the body ladder. |
| [`postgres`](lacing.store.postgres.html.md#module-lacing.store.postgres)     | PostgreSQL-backed annotation store using `int8range` + GiST.                |
| [`sqlite`](lacing.store.sqlite.html.md#module-lacing.store.sqlite)         | SQLite-backed annotation store and the `.annot` portable file format.       |
