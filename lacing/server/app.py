"""FastAPI app factory.

The server is **store-agnostic**: it accepts any ``IntervalAnnotationStore``
via dependency injection. The default store is an in-memory
``SqliteStore``; production callers should override
``app.dependency_overrides[get_store]``.

Example::

    from lacing.server import create_app
    from lacing.server.deps import get_store
    from lacing.store import SqliteStore

    store = SqliteStore("/var/lib/lacing/project.annot")
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store

Run with uvicorn::

    uvicorn lacing.server:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

from lacing.server import awareness
from lacing.server.routers import adapters, annotations, meta, oplog, tiers


def create_app(*, title: str = "lacing", version: str = "0.1.0") -> FastAPI:
    """Construct a configured FastAPI app.

    Mounts every Phase 2 router and ensures Phase 0/1 adapters are
    registered. The returned app has no global state beyond its routers
    and the dependency-injected store.
    """
    # Side-effect import: registers built-in body schemas at startup
    # so /schemas + validation endpoints work out of the box.
    import lacing.bodies  # noqa: F401

    # Eagerly register adapters so /import + /export and /formats are
    # populated on first request (instead of lazily on the first POST).
    adapters.ensure_adapters_registered()

    app = FastAPI(title=title, version=version)
    app.include_router(meta.router)
    app.include_router(tiers.router)
    app.include_router(annotations.router)
    app.include_router(adapters.router)
    app.include_router(oplog.router)
    app.include_router(awareness.router)
    return app


# Importing ``lacing.server`` exposes a ready-to-run app for ``uvicorn
# lacing.server:app``. Tests should use ``create_app()`` to get a fresh
# instance with isolated state.
app = create_app()
