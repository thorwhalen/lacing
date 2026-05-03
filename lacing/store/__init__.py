"""Interval-keyed annotation stores.

Public surface: ``IntervalAnnotationStore`` (the facade) and the in-memory
implementation ``MemoryStore``. SQLite and Postgres backends arrive in Phase 1.
"""

from lacing.store.base import IntervalAnnotationStore
from lacing.store.memory import MemoryStore

__all__ = ["IntervalAnnotationStore", "MemoryStore"]
