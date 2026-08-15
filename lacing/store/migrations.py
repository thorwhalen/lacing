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
  ``meta`` table** — the runner verifies the stamp and wraps the whole step
  in one transaction, so a failed step leaves the store untouched.

Backends own their runners (transaction idiom differs per driver):
:func:`migrate_annot_file` here for SQLite ``.annot`` files; a Postgres
runner joins it with the first registered ``"postgres"`` step. Migration is
**opt-in** — ``SqliteStore(path, migrate=True)`` or ``lacing migrate <path>``
— because silently rewriting a file on open is worse than refusing
(lacing#15).
"""

from __future__ import annotations

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
    read_version: Callable[[Any], int],
    run_in_transaction: Callable[[Any, Callable[[Any], None]], None],
) -> int:
    """Chain registered steps from ``from_version`` up to ``to_version``.

    Backend-neutral core shared by the per-backend runners: each step runs
    under ``run_in_transaction`` (the backend's idiom), and its version stamp
    is verified via ``read_version`` — a step that "succeeds" without
    stamping is a defect this catches before it corrupts the chain.
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

        def _step(connection, *, _func=func) -> None:
            _func(connection)

        try:
            run_in_transaction(conn, _step)
        except StoreMigrationError:
            raise
        except Exception as exc:
            raise StoreMigrationError(
                f"store migration {store_kind} v{current} -> v{next_version} "
                f"failed: {exc}"
            ) from exc
        stamped = read_version(conn)
        if stamped != next_version:
            raise StoreMigrationError(
                f"store migration {store_kind} v{current} -> v{next_version} "
                f"completed without stamping meta.schema_version "
                f"(found {stamped}); the step function must write it."
            )
        current = next_version
    return current


# ---------------------------------------------------------------------------
# SQLite runner
# ---------------------------------------------------------------------------


def _sqlite_read_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        raise StoreMigrationError(
            "no schema_version row in meta — not a lacing .annot file?"
        )
    return int(row[0])


def _sqlite_in_transaction(conn: sqlite3.Connection, func) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        func(conn)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate_annot_file(
    path: str | os.PathLike,
    *,
    to_version: int | None = None,
) -> tuple[int, int]:
    """Migrate a ``.annot`` file in place, returning ``(from, to)`` versions.

    ``to_version`` defaults to the current build's
    :data:`lacing.store.sqlite.SCHEMA_VERSION`. Already-current files are a
    no-op (``from == to``). Each step runs in its own ``BEGIN IMMEDIATE``
    transaction, so an interrupted chain leaves the file at the last version
    that completed — re-running resumes from there (idempotent).

    Raises :class:`StoreMigrationError` when a step is missing, fails, or
    forgets to stamp the version it claims to reach.
    """
    from lacing.store.sqlite import SCHEMA_VERSION

    target = SCHEMA_VERSION if to_version is None else to_version
    conn = sqlite3.connect(os.fspath(path), isolation_level=None)
    try:
        found = _sqlite_read_version(conn)
        reached = _run_steps(
            conn,
            store_kind=SQLITE_KIND,
            from_version=found,
            to_version=target,
            read_version=_sqlite_read_version,
            run_in_transaction=_sqlite_in_transaction,
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
    return _run_steps(
        conn,
        store_kind=SQLITE_KIND,
        from_version=_sqlite_read_version(conn),
        to_version=to_version,
        read_version=_sqlite_read_version,
        run_in_transaction=_sqlite_in_transaction,
    )
