# lacing.store.postgres

PostgreSQL-backed annotation store using `int8range` + GiST.

Maps lacing’s interval model to Postgres native range types (BACK-DOC §4.2):

| Allen relation   | Postgres operator (int8range / tstzrange)                   |
|------------------|-------------------------------------------------------------|
| overlaps (any)   | `a && b`      — any kind of intersection                    |
| during           | `a <@ b`      — a contained in b (strict variant: see code) |
| contains         | `a @> b`      — a contains b (strict variant: see code)     |
| meets / met_by   | `a -|- b`     — adjacent (touching but not overlapping)     |
| equals           | `a = b`                                                     |
| before           | `a << b`                                                    |
| after            | `a >> b`                                                    |
| strict overlap   | `a && b AND lower(a) < lower(b) AND upper(a) < upper(b)`    |

We store intervals as `int8range(start_value, end_value, '[)')` — half-open,
matching lacing’s `TimeInterval` semantics — at a \*\*per-(owner, project)
rate\*\* recorded in the `projects` table. All inserts must be at that rate;
re-quantizing happens on insert if necessary.

GiST index on the range column gives sub-millisecond overlap queries at
million-row scale. Optional `EXCLUDE USING GIST` constraints are added
**per tier** for stereotypes like `TIME_SUBDIVISION` that forbid overlap.

## Multi-tenancy (Phase 4, reelee#177)

Multiple logical stores (one per nw/reelee project) coexist in a single
Postgres database via **tenant columns on shared tables** (the decision in
`reelee/docs/storage_migration_plan.md` §”Postgres tenancy”): every
`annotations` and `tiers` row carries an `owner_id` and a `project_id`,
and every query is scoped by `(owner_id, project_id)`. A `PostgresStore`
instance is bound to one `(owner_id, project_id)` at construction and behaves
exactly like a single-tenant store; two stores with different project ids over
the same database never see each other’s rows.

`owner_id` is a forward seam for the multi-tenant access layer (reelee#174):
the column is carried and scoped now, but its *enforcement* (the policy
decision point) is deferred — today every store defaults `owner_id="default"`.

The per-tier `EXCLUDE USING GIST` no-overlap constraint is likewise scoped by
`(owner_id, project_id, tier)` so one project’s non-overlap rule cannot block
another project’s annotations.

## Connection pooling (Phase 4)

`nw`’s `ProjectGraph` opens and closes the store per
operation. That is fine for a SQLite file but pathological for a network DB, so
this module keeps a process-wide `psycopg_pool.ConnectionPool` per
connection string (see [`get_pool()`](#lacing.store.postgres.get_pool)); a `PostgresStore` borrows a
connection from the pool for its lifetime and returns it on `close()` instead
of opening a fresh TCP/auth round-trip each time. When `psycopg_pool` is not
installed (or a caller passes `use_pool=False`) we fall back to a dedicated
long-lived connection.

Schema versioning lives in `meta`; mismatched versions raise on open.

Status: Phase 4. Tested via `pytest-postgresql` sandbox (no live server
needed for development).

### Module Attributes

| [`SCHEMA_VERSION`](#lacing.store.postgres.SCHEMA_VERSION)     | Current schema version stored in the `meta` table.                        |
|---------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`DEFAULT_OWNER_ID`](#lacing.store.postgres.DEFAULT_OWNER_ID)   | Owner placeholder until the multi-tenant access layer (reelee#174) lands. |
| [`DEFAULT_PROJECT_ID`](#lacing.store.postgres.DEFAULT_PROJECT_ID) | Project placeholder for single-project / legacy use.                      |

### Functions

| [`close_all_pools`](#lacing.store.postgres.close_all_pools)()                                | Close every registered connection pool (test teardown / shutdown).   |
|---------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| [`from_memory`](#lacing.store.postgres.from_memory)(memory_store, connection_string, \*) | Replicate an in-memory store into a Postgres database (one tenant).  |
| [`get_pool`](#lacing.store.postgres.get_pool)(connection_string, \*\*pool_kwargs)     | Return a process-wide `psycopg_pool.ConnectionPool` for a conninfo.  |
| [`to_memory`](#lacing.store.postgres.to_memory)(pg_store)                              | Snapshot a `PostgresStore` into a `MemoryStore`.                     |

### Classes

| [`PostgresStore`](#lacing.store.postgres.PostgresStore)(connection_string, \*[, rate, ...])   | PostgreSQL-backed `IntervalAnnotationStore`, scoped to one tenant.   |
|------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|

### Exceptions

| [`PgSchemaMismatchError`](#lacing.store.postgres.PgSchemaMismatchError)   | Raised on opening a database whose schema_version differs.                      |
|--------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`RateMismatchError`](#lacing.store.postgres.RateMismatchError)       | Raised when an annotation's interval cannot be represented at the project rate. |
| [`TierOverlapError`](#lacing.store.postgres.TierOverlapError)        | Raised when an insert would violate a per-tier no-overlap constraint.           |

### lacing.store.postgres.DEFAULT_OWNER_ID *= 'default'*

Owner placeholder until the multi-tenant access layer (reelee#174) lands.

The `owner_id` column is carried and scoped now; its enforcement is deferred.

### lacing.store.postgres.DEFAULT_PROJECT_ID *= 'default'*

Project placeholder for single-project / legacy use.

### *exception* lacing.store.postgres.PgSchemaMismatchError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised on opening a database whose schema_version differs.

### *class* lacing.store.postgres.PostgresStore(connection_string, , rate=24000, owner_id='default', project_id='default', autocommit=True, use_pool=True)

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
    raises [`PgSchemaMismatchError`](#lacing.store.postgres.PgSchemaMismatchError). Different projects in the
    same DB may have different rates.
  * **owner_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Tenant owner. Defaults to [`DEFAULT_OWNER_ID`](#lacing.store.postgres.DEFAULT_OWNER_ID) — the
    forward seam for the access layer (reelee#174); enforcement deferred.
  * **project_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Logical project key. Defaults to [`DEFAULT_PROJECT_ID`](#lacing.store.postgres.DEFAULT_PROJECT_ID).
    `nw` passes the project’s `project_asset_id` here.
  * **autocommit** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True (default), statements run in their own transaction.
  * **use_pool** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – When True (default) and the connection is given as a string,
    borrow a connection from a process-wide pool keyed by the conninfo
    (amortizes per-op connect cost; see [`get_pool()`](#lacing.store.postgres.get_pool)). Falls back to
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

### *exception* lacing.store.postgres.RateMismatchError

Bases: [`LossyTimeConversionError`](lacing.time.html.md#lacing.time.LossyTimeConversionError)

Raised when an annotation’s interval cannot be represented at the project rate.

### lacing.store.postgres.SCHEMA_VERSION *= 3*

Current schema version stored in the `meta` table.

v2 (Phase 4, reelee#177) added tenant columns (`owner_id` / `project_id`)
to `tiers` and `annotations`, and a per-`(owner, project)` `projects`
table holding the rate (was a single `meta` row in v1).

v3 (lacing#14, defect D5): `prov_was_derived_from` may contain 64-hex
artifact `asset_id` strings alongside annotation UUIDs. Layout and rows
unchanged — the bump makes pre-v3 builds (whose read path eagerly
`UUID()`-parses the column) refuse rather than crash mid-read.

The migration ladder ([`lacing.store.migrations`](lacing.store.migrations.html.md#module-lacing.store.migrations),
`store_kind="postgres"`) is deliberately **empty**: no Postgres database
at any version ever held real data — the backend is config-selectable and
was never enabled in any environment; production has always been the
per-caller sqlite `.annot` layout (verified 2026-08-15, lacing#15).
Dev databases at v1/v2 are recreated, not migrated. Register steps from
v3 forward once a deployed Postgres exists.

### *exception* lacing.store.postgres.TierOverlapError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when an insert would violate a per-tier no-overlap constraint.

### lacing.store.postgres.close_all_pools()

Close every registered connection pool (test teardown / shutdown).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.store.postgres.from_memory(memory_store, connection_string, , rate=24000, owner_id='default', project_id='default')

Replicate an in-memory store into a Postgres database (one tenant).

* **Return type:**
  [`PostgresStore`](#lacing.store.postgres.PostgresStore)

### lacing.store.postgres.get_pool(connection_string, \*\*pool_kwargs)

Return a process-wide `psycopg_pool.ConnectionPool` for a conninfo.

One pool per distinct `connection_string` (the keying happens here, not at
the call-site), created lazily on first request. Raises [`ImportError`](https://docs.python.org/3/builtins/exceptions.html#ImportError)
if `psycopg_pool` is not installed — callers that want a graceful fallback
catch it (see [`PostgresStore`](#lacing.store.postgres.PostgresStore)).

* **Parameters:**
  * **connection_string** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – psycopg conninfo URL (the registry key).
  * **\*\*pool_kwargs** – forwarded to `ConnectionPool` on
    first creation (e.g. `min_size`, `max_size`); ignored on reuse.
* **Returns:**
  The shared pool for this conninfo.

### lacing.store.postgres.to_memory(pg_store)

Snapshot a `PostgresStore` into a `MemoryStore`.
