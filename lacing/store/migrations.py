"""Store-level schema migrations — the on-disk counterpart of the body ladder.

:mod:`lacing.schema` migrates annotation *bodies* (``dict -> dict``, keyed
``(schema_name, from_version)``). This module is the same mental model one
level down: it migrates the *store* — table layout, column rewrites, the
``meta.schema_version`` stamp — keyed ``(store_kind, from_version)``.

The split matters because the two ladders move different things:

- a body migration rewrites one annotation's payload and can run anywhere;
- a store migration receives an **open connection** and performs DDL, row
  rewrites, and the version stamp for a whole database, atomically.

Contract (mirrors :func:`lacing.schema.register_migration`):

- steps are single-step only (``to_version == from_version + 1``); chains
  compose by repeated lookup;
- re-registering a ``(store_kind, from_version)`` pair replaces the previous
  entry — convenient in tests, intentional for hot-reload;
- an upgrade function receives the open connection and must leave the store
  readable at ``to_version``, **including writing the new version into the
  ``meta`` table**.

What the runner guarantees around each step (all verified *inside* the
step's transaction, so any breach rolls the whole step back):

- the version is re-read **under the write lock** before the step runs — a
  concurrent migrator that already applied the step is detected and the
  step skipped, never double-applied (multi-process servers open the same
  ``.annot`` file);
- the step stamped the version it claims to reach;
- ``PRAGMA foreign_key_check`` is clean, and the ``annotations_rtree``
  index agrees with the ``annotations`` table (see
  :func:`rebuild_annotations_rtree`).

Rules for step authors (sqlite):

- **Never call ``conn.executescript``, ``COMMIT`` or ``ROLLBACK``** inside a
  step — ``executescript`` implicitly commits the wrapper's transaction,
  destroying atomicity. The runner detects a step that ended its
  transaction and fails loudly.
- Foreign-key enforcement is pinned **OFF** during migration (sqlite cannot
  rebuild tables under FK enforcement); ``PRAGMA foreign_key_check`` before
  commit is the compensating guarantee.
- A table rebuild (``CREATE new`` → copy → ``DROP old`` → ``RENAME``) must
  **preserve rowids** — ``INSERT INTO new (rowid, ...) SELECT rowid, ...
  FROM old`` — because ``annotations_rtree`` keys on them; rebuild the
  index with :func:`rebuild_annotations_rtree` afterwards.

Backends own their runners (transaction idiom differs per driver):
:func:`migrate_annot_file` here for SQLite ``.annot`` files; a Postgres
runner joins it with the first registered ``"postgres"`` step. Migration is
**opt-in** — ``SqliteStore(path, migrate=True)`` or ``lacing migrate <path>``
— because silently rewriting a file on open is worse than refusing
(lacing#15).
"""

from __future__ import annotations

import contextlib
import math
import os
import sqlite3
from collections.abc import Callable
from typing import Any


# Maps (store_kind, from_version) -> (to_version, callable(connection) -> None).
# Single-step hops only; chains compose by repeated lookup — the exact
# contract of lacing.schema._MIGRATION_REGISTRY, one level down.
_STORE_MIGRATION_REGISTRY: dict[tuple[str, int], tuple[int, Callable[[Any], None]]] = {}

SQLITE_KIND = "sqlite"
"""``store_kind`` of the SQLite / ``.annot`` backend."""

POSTGRES_KIND = "postgres"
"""``store_kind`` of the Postgres backend."""

SQLITE_MIGRATION_BUSY_TIMEOUT_MS = 30_000
"""How long a migrating connection waits on another writer's lock.

Generous on purpose: when several workers race to open the same ``.annot``
with ``migrate=True``, the losers should wait for the winner and then skip
the already-applied steps, not fail at sqlite's 5s default."""


class StoreMigrationError(RuntimeError):
    """Raised when a store migration step is missing or fails."""


def register_store_migration(
    *,
    store_kind: str,
    from_version: int,
    to_version: int,
):
    """Register a forward store migration from ``from_version`` to ``to_version``.

    The decorated function takes the backend's open connection and must
    perform every change of the step — DDL, row rewrites, and the
    ``meta.schema_version`` write. Steps must be one version at a time
    (``to_version == from_version + 1``); the runner chains them.

    Step authors: read the module docstring's rules — no ``executescript``
    / ``COMMIT`` / ``ROLLBACK`` inside a step, preserve rowids on table
    rebuilds, and rebuild the interval index with
    :func:`rebuild_annotations_rtree` if the ``annotations`` table was
    rebuilt.

    Re-registering the same ``(store_kind, from_version)`` pair replaces the
    previous entry.
    """
    if to_version != from_version + 1:
        raise ValueError(
            f"store migrations must be single-step: from_version={from_version}, "
            f"to_version={to_version}; chains compose by repeated lookup."
        )
    if from_version < 1:
        raise ValueError(f"from_version must be >= 1, got {from_version}")

    def decorator(func: Callable[[Any], None]) -> Callable[[Any], None]:
        _STORE_MIGRATION_REGISTRY[(store_kind, from_version)] = (to_version, func)
        return func

    return decorator


def reachable_versions(store_kind: str, from_version: int) -> tuple[int, ...]:
    """Versions reachable from ``from_version`` by chaining registered steps.

    Ascending, excluding ``from_version`` itself. Empty when no step leaves
    ``from_version`` — which is what a refusal message should say out loud
    instead of the bare "run a migration" it used to say.
    """
    out: list[int] = []
    current = from_version
    while (step := _STORE_MIGRATION_REGISTRY.get((store_kind, current))) is not None:
        current = step[0]
        out.append(current)
    return tuple(out)


def _run_steps(
    conn,
    *,
    store_kind: str,
    from_version: int,
    to_version: int,
    run_step: Callable[[Any, int, int, Callable[[Any], None]], int],
) -> int:
    """Chain registered steps from ``from_version`` up to ``to_version``.

    Backend-neutral core: ``run_step(conn, from_v, to_v, func)`` owns the
    backend's whole per-step discipline (lock, under-lock version re-check,
    step execution, in-transaction verification, commit) and returns the
    version the store is now at — ``to_v`` when it applied the step, or the
    version it found under the lock when a concurrent migrator had already
    advanced it (the loop then reassesses instead of double-applying).
    """
    if from_version > to_version:
        raise StoreMigrationError(
            f"{store_kind} store is at schema_version={from_version}, newer than "
            f"the requested v{to_version}; only forward migrations are supported."
        )
    current = from_version
    while current < to_version:
        step = _STORE_MIGRATION_REGISTRY.get((store_kind, current))
        if step is None:
            raise StoreMigrationError(
                f"no store migration registered for {store_kind} "
                f"v{current} -> v{current + 1}"
            )
        next_version, func = step
        try:
            reached = run_step(conn, current, next_version, func)
        except StoreMigrationError:
            raise
        except Exception as exc:
            raise StoreMigrationError(
                f"store migration {store_kind} v{current} -> v{next_version} "
                f"failed: {exc}"
            ) from exc
        if reached == current:
            raise StoreMigrationError(
                f"store migration {store_kind} v{current} -> v{next_version} "
                "made no progress."
            )
        current = reached
    return current


# ---------------------------------------------------------------------------
# SQLite runner
# ---------------------------------------------------------------------------


def _sqlite_read_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise StoreMigrationError(
            f"cannot read meta.schema_version — not a lacing .annot file? ({exc})"
        ) from exc
    if row is None:
        raise StoreMigrationError(
            "no schema_version row in meta — not a lacing .annot file?"
        )
    return int(row[0])


def _sqlite_prepare(conn: sqlite3.Connection) -> None:
    """Pin the migration connection's pragmas.

    ``foreign_keys = OFF`` explicitly (sqlite's per-connection default, but
    the ladder *relies* on it — table rebuilds are impossible under FK
    enforcement — so it is pinned, not assumed; ``foreign_key_check`` before
    each commit is the compensating guarantee). PRAGMA toggles inside a
    step's transaction are no-ops, so this is the only place it can be set.
    """
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_MIGRATION_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = OFF")


def _sqlite_run_step(
    conn: sqlite3.Connection,
    from_version: int,
    to_version: int,
    func: Callable[[sqlite3.Connection], None],
) -> int:
    """One step under ``BEGIN IMMEDIATE``, fully verified before COMMIT."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        found = _sqlite_read_version(conn)
        if found != from_version:
            # A concurrent migrator won the race while we waited for the
            # lock; whatever it did is committed truth — reassess, don't
            # re-apply.
            conn.execute("ROLLBACK")
            return found
        func(conn)
        if not conn.in_transaction:
            raise StoreMigrationError(
                f"store migration {SQLITE_KIND} v{from_version} -> "
                f"v{to_version}: the step ended its own transaction — "
                "conn.executescript (which implicitly commits) and explicit "
                "COMMIT/ROLLBACK are forbidden inside steps; whatever ran "
                "before the break is already committed."
            )
        stamped = _sqlite_read_version(conn)
        if stamped != to_version:
            raise StoreMigrationError(
                f"store migration {SQLITE_KIND} v{from_version} -> "
                f"v{to_version} completed without stamping "
                f"meta.schema_version (found {stamped}); the step function "
                "must write it. Rolled back."
            )
        _sqlite_verify_integrity(conn, from_version=from_version, to_version=to_version)
        conn.execute("COMMIT")
        return to_version
    except BaseException:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("ROLLBACK")
        raise


def _sqlite_verify_integrity(
    conn: sqlite3.Connection, *, from_version: int, to_version: int
) -> None:
    """In-transaction sanity gates a defective step cannot slip past.

    Runs before the step's COMMIT so a violation rolls the step back.
    """
    head = f"store migration {SQLITE_KIND} v{from_version} -> v{to_version}"
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        sample = [tuple(v) for v in violations[:5]]
        raise StoreMigrationError(
            f"{head}: foreign_key_check found {len(violations)} violation(s), "
            f"e.g. {sample}. Rolled back."
        )
    if _sqlite_has_table(conn, "annotations") and _sqlite_has_table(
        conn, "annotations_rtree"
    ):
        orphaned = conn.execute(
            "SELECT count(*) FROM annotations_rtree r WHERE NOT EXISTS "
            "(SELECT 1 FROM annotations a WHERE a.rowid = r.rowid)"
        ).fetchone()[0]
        unindexed = conn.execute(
            "SELECT count(*) FROM annotations a WHERE a.start_value IS NOT NULL "
            "AND NOT EXISTS "
            "(SELECT 1 FROM annotations_rtree r WHERE r.rowid = a.rowid)"
        ).fetchone()[0]
        if orphaned or unindexed:
            raise StoreMigrationError(
                f"{head}: annotations_rtree is out of sync ({orphaned} "
                f"orphaned index row(s), {unindexed} unindexed "
                "annotation(s)). Table rebuilds must preserve rowids "
                "(INSERT INTO new (rowid, ...) SELECT rowid, ... FROM old) "
                "and re-index via rebuild_annotations_rtree(conn). "
                "Rolled back."
            )


def _sqlite_has_table(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (name,),
        ).fetchone()
        is not None
    )


def rebuild_annotations_rtree(conn: sqlite3.Connection) -> int:
    """Rebuild the interval index from the ``annotations`` table, in place.

    For use *inside* a migration step after a table rebuild. Reproduces the
    store's ULP-widening contract (bounds widened by one float ULP so
    float→exact-bound comparisons never drop hits — see
    :mod:`lacing.store.sqlite`). Returns the number of rows indexed.
    """
    conn.execute("DELETE FROM annotations_rtree")
    indexed = 0
    rows = conn.execute(
        "SELECT rowid, start_value, start_rate, end_value, end_rate "
        "FROM annotations WHERE start_value IS NOT NULL"
    ).fetchall()
    for rowid, start_value, start_rate, end_value, end_rate in rows:
        start_s = start_value / start_rate
        end_s = end_value / end_rate
        conn.execute(
            "INSERT INTO annotations_rtree (rowid, start_seconds, end_seconds) "
            "VALUES (?, ?, ?)",
            (
                rowid,
                math.nextafter(start_s, -math.inf),
                math.nextafter(end_s, math.inf),
            ),
        )
        indexed += 1
    return indexed


def migrate_annot_file(
    path: str | os.PathLike,
    *,
    to_version: int | None = None,
) -> tuple[int, int]:
    """Migrate a ``.annot`` file in place, returning ``(from, to)`` versions.

    ``to_version`` defaults to the current build's
    :data:`lacing.store.sqlite.SCHEMA_VERSION`. Already-current files are a
    no-op (``from == to``). Each step runs in its own ``BEGIN IMMEDIATE``
    transaction with the version re-checked under the lock, so concurrent
    migrators converge and an interrupted chain resumes from the last
    version that completed (idempotent).

    Raises :class:`StoreMigrationError` when the file does not exist, is
    not a ``.annot`` file, a step is missing, fails, or breaks one of the
    runner's in-transaction guarantees.
    """
    from lacing.store.sqlite import SCHEMA_VERSION

    if not os.path.exists(path):
        # Connecting would CREATE an empty junk database at the typo'd path.
        raise StoreMigrationError(f"no such file: {os.fspath(path)}")
    target = SCHEMA_VERSION if to_version is None else int(to_version)
    conn = sqlite3.connect(os.fspath(path), isolation_level=None)
    try:
        _sqlite_prepare(conn)
        found = _sqlite_read_version(conn)
        reached = _run_steps(
            conn,
            store_kind=SQLITE_KIND,
            from_version=found,
            to_version=target,
            run_step=_sqlite_run_step,
        )
        return found, reached
    finally:
        conn.close()


def migrate_sqlite_connection(conn: sqlite3.Connection, *, to_version: int) -> int:
    """Run the SQLite ladder on an already-open connection.

    The hook :class:`~lacing.store.sqlite.SqliteStore` uses for its
    ``migrate=True`` opt-in; external callers with a file path want
    :func:`migrate_annot_file`.
    """
    _sqlite_prepare(conn)
    return _run_steps(
        conn,
        store_kind=SQLITE_KIND,
        from_version=_sqlite_read_version(conn),
        to_version=to_version,
        run_step=_sqlite_run_step,
    )
