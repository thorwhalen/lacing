# lacing.store.migrations

Store-level schema migrations — the on-disk counterpart of the body ladder.

[`lacing.schema`](lacing.schema.md#module-lacing.schema) migrates annotation *bodies* (`dict -> dict`, keyed
`(schema_name, from_version)`). This module is the same mental model one
level down: it migrates the *store* — table layout, column rewrites, the
`meta.schema_version` stamp — keyed `(store_kind, from_version)`.

The split matters because the two ladders move different things:

- a body migration rewrites one annotation’s payload and can run anywhere;
- a store migration receives an **open connection** and performs DDL, row
  rewrites, and the version stamp for a whole database, atomically.

Contract (mirrors [`lacing.schema.register_migration()`](lacing.schema.md#lacing.schema.register_migration)):

- steps are single-step only (`to_version == from_version + 1`); chains
  compose by repeated lookup;
- re-registering a `(store_kind, from_version)` pair replaces the previous
  entry — convenient in tests, intentional for hot-reload;
- an upgrade function receives the open connection and must leave the store
  readable at `to_version`, \*\*including writing the new version into the
  `meta` table\*\*.

What the runner guarantees around each step (all verified *inside* the
step’s transaction, so any breach rolls the whole step back):

- the version is re-read **under the write lock** before the step runs — a
  concurrent migrator that already applied the step is detected and the
  step skipped, never double-applied (multi-process servers open the same
  `.annot` file);
- the step stamped the version it claims to reach;
- `PRAGMA foreign_key_check` is clean, and the `annotations_rtree`
  index agrees with the `annotations` table (see
  [`rebuild_annotations_rtree()`](#lacing.store.migrations.rebuild_annotations_rtree)).

Rules for step authors (sqlite):

- \*\*Never call `conn.executescript`, `COMMIT` or `ROLLBACK``** inside a
  step — ``executescript` implicitly commits the wrapper’s transaction,
  destroying atomicity. The runner detects a step that ended its
  transaction and fails loudly.
- Foreign-key enforcement is pinned **OFF** during migration (sqlite cannot
  rebuild tables under FK enforcement); `PRAGMA foreign_key_check` before
  commit is the compensating guarantee.
- A table rebuild (`CREATE new` → copy → `DROP old` → `RENAME`) must
  **preserve rowids** — `INSERT INTO new (rowid, ...) SELECT rowid, ...
  FROM old` — because `annotations_rtree` keys on them; rebuild the
  index with [`rebuild_annotations_rtree()`](#lacing.store.migrations.rebuild_annotations_rtree) afterwards.

Backends own their runners (transaction idiom differs per driver):
[`migrate_annot_file()`](#lacing.store.migrations.migrate_annot_file) here for SQLite `.annot` files; a Postgres
runner joins it with the first registered `"postgres"` step. Migration is
**opt-in** — `SqliteStore(path, migrate=True)` or `lacing migrate <path>`
— because silently rewriting a file on open is worse than refusing
(lacing#15).

### Module Attributes

| [`SQLITE_KIND`](#lacing.store.migrations.SQLITE_KIND)                      | `store_kind` of the SQLite / `.annot` backend.                  |
|-----------------------------------------------------------------------------------|-----------------------------------------------------------------|
| [`POSTGRES_KIND`](#lacing.store.migrations.POSTGRES_KIND)                    | `store_kind` of the Postgres backend.                           |
| [`SQLITE_MIGRATION_BUSY_TIMEOUT_MS`](#lacing.store.migrations.SQLITE_MIGRATION_BUSY_TIMEOUT_MS) | How long a migrating connection waits on another writer's lock. |

### Functions

| [`migrate_annot_file`](#lacing.store.migrations.migrate_annot_file)(path, \*[, to_version])      | Migrate a `.annot` file in place, returning `(from, to)` versions.      |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`migrate_sqlite_connection`](#lacing.store.migrations.migrate_sqlite_connection)(conn, \*, to_version) | Run the SQLite ladder on an already-open connection.                    |
| [`reachable_versions`](#lacing.store.migrations.reachable_versions)(store_kind, from_version)    | Versions reachable from `from_version` by chaining registered steps.    |
| [`rebuild_annotations_rtree`](#lacing.store.migrations.rebuild_annotations_rtree)(conn)                 | Rebuild the interval index from the `annotations` table, in place.      |
| [`register_store_migration`](#lacing.store.migrations.register_store_migration)(\*, store_kind, ...)   | Register a forward store migration from `from_version` to `to_version`. |

### Exceptions

| [`StoreMigrationError`](#lacing.store.migrations.StoreMigrationError)   | Raised when a store migration step is missing or fails.   |
|------------------------------------------------------------------------|-----------------------------------------------------------|

### lacing.store.migrations.POSTGRES_KIND *= 'postgres'*

`store_kind` of the Postgres backend.

### lacing.store.migrations.SQLITE_KIND *= 'sqlite'*

`store_kind` of the SQLite / `.annot` backend.

### lacing.store.migrations.SQLITE_MIGRATION_BUSY_TIMEOUT_MS *= 30000*

How long a migrating connection waits on another writer’s lock.

Generous on purpose: when several workers race to open the same `.annot`
with `migrate=True`, the losers should wait for the winner and then skip
the already-applied steps, not fail at sqlite’s 5s default.

### *exception* lacing.store.migrations.StoreMigrationError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when a store migration step is missing or fails.

### lacing.store.migrations.migrate_annot_file(path, , to_version=None)

Migrate a `.annot` file in place, returning `(from, to)` versions.

`to_version` defaults to the current build’s
[`lacing.store.sqlite.SCHEMA_VERSION`](lacing.store.sqlite.md#lacing.store.sqlite.SCHEMA_VERSION). Already-current files are a
no-op (`from == to`). Each step runs in its own `BEGIN IMMEDIATE`
transaction with the version re-checked under the lock, so concurrent
migrators converge and an interrupted chain resumes from the last
version that completed (idempotent).

Raises [`StoreMigrationError`](#lacing.store.migrations.StoreMigrationError) when the file does not exist, is
not a `.annot` file, a step is missing, fails, or breaks one of the
runner’s in-transaction guarantees.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### lacing.store.migrations.migrate_sqlite_connection(conn, , to_version)

Run the SQLite ladder on an already-open connection.

The hook [`SqliteStore`](lacing.store.sqlite.md#lacing.store.sqlite.SqliteStore) uses for its
`migrate=True` opt-in; external callers with a file path want
[`migrate_annot_file()`](#lacing.store.migrations.migrate_annot_file).

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### lacing.store.migrations.reachable_versions(store_kind, from_version)

Versions reachable from `from_version` by chaining registered steps.

Ascending, excluding `from_version` itself. Empty when no step leaves
`from_version` — which is what a refusal message should say out loud
instead of the bare “run a migration” it used to say.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### lacing.store.migrations.rebuild_annotations_rtree(conn)

Rebuild the interval index from the `annotations` table, in place.

For use *inside* a migration step after a table rebuild. Reproduces the
store’s ULP-widening contract (bounds widened by one float ULP so
float→exact-bound comparisons never drop hits — see
[`lacing.store.sqlite`](lacing.store.sqlite.md#module-lacing.store.sqlite)). Returns the number of rows indexed.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### lacing.store.migrations.register_store_migration(, store_kind, from_version, to_version)

Register a forward store migration from `from_version` to `to_version`.

The decorated function takes the backend’s open connection and must
perform every change of the step — DDL, row rewrites, and the
`meta.schema_version` write. Steps must be one version at a time
(`to_version == from_version + 1`); the runner chains them.

Step authors: read the module docstring’s rules — no `executescript`
/ `COMMIT` / `ROLLBACK` inside a step, preserve rowids on table
rebuilds, and rebuild the interval index with
[`rebuild_annotations_rtree()`](#lacing.store.migrations.rebuild_annotations_rtree) if the `annotations` table was
rebuilt.

Re-registering the same `(store_kind, from_version)` pair replaces the
previous entry.
