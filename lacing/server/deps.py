"""Dependency-injection helpers for the FastAPI server.

The server is **store-agnostic**: it accepts any ``IntervalAnnotationStore``
implementation via FastAPI's dependency-injection. The default
:func:`default_store_factory` builds a ``SqliteStore(":memory:")`` for
zero-config dev mode; production callers should override
``get_store`` via FastAPI's ``app.dependency_overrides``.

Example::

    from lacing.server import create_app
    from lacing.server.deps import get_store, get_oplog
    from lacing.store import SqliteStore
    from lacing.oplog import InMemoryOpLog

    store = SqliteStore("/var/lib/lacing/project.annot")
    oplog = InMemoryOpLog()
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_oplog] = lambda: oplog

This pattern lets the same server code run on top of ``MemoryStore``,
``SqliteStore`` (single-file ``.annot``), or ``PostgresStore``
(multi-user) without any per-route changes.
"""

from __future__ import annotations

from typing import Any


# A module-level singleton holds the active store for the lifetime of the app.
# Production overrides this via FastAPI's ``app.dependency_overrides``.
_active_store: Any = None
_active_oplog: Any = None


def default_store_factory() -> Any:
    """Build a fresh in-memory ``SqliteStore`` for dev / zero-config mode.

    Note ``check_same_thread=False``: FastAPI runs sync endpoints on a
    worker threadpool, so the same SQLite connection has to be reachable
    from multiple threads. Production callers wiring their own
    ``SqliteStore`` should pass the same flag.
    """
    from lacing.store import SqliteStore

    return SqliteStore(":memory:", check_same_thread=False)


def default_oplog_factory() -> Any:
    """Build a fresh in-memory op-log."""
    from lacing.oplog import InMemoryOpLog

    return InMemoryOpLog()


def get_store() -> Any:
    """FastAPI dependency: return the active ``IntervalAnnotationStore``.

    Override via ``app.dependency_overrides[get_store] = lambda: my_store``.
    The default factory builds an in-memory ``SqliteStore`` once per app.
    """
    global _active_store
    if _active_store is None:
        _active_store = default_store_factory()
    return _active_store


def get_oplog() -> Any:
    """FastAPI dependency: return the active op-log.

    Override via ``app.dependency_overrides[get_oplog] = lambda: my_oplog``.
    The default factory builds an :class:`InMemoryOpLog` once per app.
    """
    global _active_oplog
    if _active_oplog is None:
        _active_oplog = default_oplog_factory()
    return _active_oplog


def reset_default_store() -> None:
    """Drop the cached default store so the next ``get_store()`` rebuilds it.

    For tests; do not use in production.
    """
    global _active_store
    if _active_store is not None and hasattr(_active_store, "close"):
        try:
            _active_store.close()
        except Exception:
            pass
    _active_store = None


def reset_default_oplog() -> None:
    """Drop the cached default op-log; the next ``get_oplog()`` rebuilds it."""
    global _active_oplog
    if _active_oplog is not None and hasattr(_active_oplog, "close"):
        try:
            _active_oplog.close()
        except Exception:
            pass
    _active_oplog = None
