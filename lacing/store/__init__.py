"""Interval-keyed annotation stores.

Public surface: ``IntervalAnnotationStore`` (the facade), ``MemoryStore``,
``SqliteStore`` (the ``.annot`` on-disk format), the optional
``PostgresStore``, and the store-schema migration ladder
(:mod:`lacing.store.migrations`).
"""

from lacing.store.base import IntervalAnnotationStore
from lacing.store.memory import MemoryStore
from lacing.store.migrations import (
    POSTGRES_KIND,
    SQLITE_KIND,
    StoreMigrationError,
    migrate_annot_file,
    reachable_versions,
    rebuild_annotations_rtree,
    register_store_migration,
)
from lacing.store.sqlite import SchemaMismatchError, SqliteStore

# Postgres backend is optional — psycopg may not be installed.
try:
    from lacing.store.postgres import (
        DEFAULT_OWNER_ID,
        DEFAULT_PROJECT_ID,
        PgSchemaMismatchError,
        PostgresStore,
        RateMismatchError,
        TierOverlapError,
        close_all_pools,
        get_pool,
    )

    _HAS_POSTGRES = True
except ImportError:  # pragma: no cover  — covered indirectly
    _HAS_POSTGRES = False

__all__ = [
    "IntervalAnnotationStore",
    "MemoryStore",
    "SqliteStore",
    "SchemaMismatchError",
    "register_store_migration",
    "migrate_annot_file",
    "reachable_versions",
    "rebuild_annotations_rtree",
    "StoreMigrationError",
    "SQLITE_KIND",
    "POSTGRES_KIND",
]
if _HAS_POSTGRES:
    __all__.extend(
        [
            "PostgresStore",
            "PgSchemaMismatchError",
            "TierOverlapError",
            "RateMismatchError",
            "DEFAULT_OWNER_ID",
            "DEFAULT_PROJECT_ID",
            "get_pool",
            "close_all_pools",
        ]
    )
