"""FastAPI server for lacing.

Importing this package exposes a ready-to-run ``app`` instance::

    uvicorn lacing.server:app --reload

For tests and production overrides, use :func:`create_app`::

    from lacing.server import create_app
    from lacing.server.deps import get_store

    app = create_app()
    app.dependency_overrides[get_store] = lambda: my_store

See ``misc/docs/Backend Architecture for Time-Interval Annotation Systems.md``
§3 for the architectural rationale.
"""

from lacing.server.app import app, create_app

__all__ = ["app", "create_app"]
