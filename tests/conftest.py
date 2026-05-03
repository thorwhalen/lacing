"""Shared pytest fixtures.

The Postgres-backed store is tested via ``pytest-postgresql``, which spawns
a sandboxed PostgreSQL using the locally installed binary (no running
service required). If neither ``pytest-postgresql`` nor the Postgres
binary is available, those tests are skipped automatically.
"""

from __future__ import annotations

import shutil

import pytest


def _have_postgres_binary() -> bool:
    return any(
        shutil.which(name) is not None for name in ("pg_ctl", "postgres")
    )


def _have_pytest_postgresql() -> bool:
    try:
        import pytest_postgresql  # noqa: F401
        return True
    except ImportError:
        return False


# Auto-load the pytest-postgresql plugin only when both prerequisites are met.
# Otherwise, register a marker so tests can skip cleanly.
if _have_pytest_postgresql() and _have_postgres_binary():
    pytest_plugins = ("pytest_postgresql",)


def pytest_collection_modifyitems(config, items):  # pragma: no cover
    if _have_pytest_postgresql() and _have_postgres_binary():
        return
    # Skip any test that requests the postgres fixture.
    skip_pg = pytest.mark.skip(
        reason="postgres binary or pytest-postgresql not available",
    )
    for item in items:
        if "postgres_store" in getattr(item, "fixturenames", ()):
            item.add_marker(skip_pg)
