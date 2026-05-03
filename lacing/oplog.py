"""Operation log for time-travel debug + audit.

The op-log is an append-only sequence of mutations applied to a store.
Each entry carries a monotonically increasing **Lamport clock**, the
operation name (``add_annotation``, ``remove_annotation``, ``add_tier``,
…), the target id, a JSON payload sufficient to **replay** the
operation against a fresh store, plus actor / timestamp metadata.

Together with a fresh empty store, the op-log is enough to reconstruct
the state of the system at any past clock value — the "killer debug
feature" called out in BACK-DOC §4.7.

Two implementations ship with Phase 2:

- :class:`InMemoryOpLog` — for tests, dev, ephemeral runs.
- :class:`SqliteOpLog` — persistent table on top of any SQLite database
  (intended to live in the same ``.annot`` file as the store).

Use :func:`replay` to rebuild a store at a given clock.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time as _time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# entry shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpLogEntry:
    """One row of the op-log."""

    clock: int
    """Monotonic Lamport clock starting at 1. Strictly increasing per log."""

    operation: str
    """One of: ``add_annotation``, ``remove_annotation``, ``update_annotation``,
    ``add_tier``, ``set_meta``, ``import_batch``."""

    target_id: str | None
    """Annotation id, tier name, meta key, or None for batch ops."""

    payload: dict[str, Any]
    """JSON-serializable payload sufficient to replay the operation."""

    actor: str = "anonymous"
    """``user:<handle>`` or ``agent:<model>@<hash>`` or ``adapter:<format>``."""

    received_at: float = field(default_factory=lambda: _time.time())
    """Wall-clock time the operation was received (seconds since epoch)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "clock": self.clock,
            "operation": self.operation,
            "target_id": self.target_id,
            "payload": self.payload,
            "actor": self.actor,
            "received_at": self.received_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OpLogEntry":
        return cls(
            clock=int(d["clock"]),
            operation=str(d["operation"]),
            target_id=d.get("target_id"),
            payload=d.get("payload") or {},
            actor=str(d.get("actor", "anonymous")),
            received_at=float(d.get("received_at", 0.0)),
        )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class OpLog(Protocol):
    """Append-only log of mutations.

    Implementations must guarantee that the clock returned by
    :meth:`append` is strictly greater than every previously-returned
    clock value across the lifetime of the log.
    """

    def append(
        self,
        operation: str,
        *,
        target_id: str | None = None,
        payload: dict[str, Any] | None = None,
        actor: str = "anonymous",
    ) -> int:
        """Append an entry; return its assigned clock."""

    def entries(
        self,
        *,
        until_clock: int | None = None,
        from_clock: int | None = None,
    ) -> Iterator[OpLogEntry]:
        """Iterate entries, optionally bounded by clock range (inclusive)."""

    def latest_clock(self) -> int:
        """Highest clock currently in the log; 0 if empty."""

    def __len__(self) -> int: ...


# ---------------------------------------------------------------------------
# in-memory
# ---------------------------------------------------------------------------


class InMemoryOpLog:
    """Simple list-backed op-log. Thread-safe via an RLock."""

    def __init__(self) -> None:
        self._entries: list[OpLogEntry] = []
        self._lock = threading.RLock()

    def append(
        self,
        operation: str,
        *,
        target_id: str | None = None,
        payload: dict[str, Any] | None = None,
        actor: str = "anonymous",
    ) -> int:
        with self._lock:
            clock = len(self._entries) + 1
            self._entries.append(
                OpLogEntry(
                    clock=clock,
                    operation=operation,
                    target_id=target_id,
                    payload=payload or {},
                    actor=actor,
                )
            )
            return clock

    def entries(
        self,
        *,
        until_clock: int | None = None,
        from_clock: int | None = None,
    ) -> Iterator[OpLogEntry]:
        with self._lock:
            snapshot = list(self._entries)
        for e in snapshot:
            if from_clock is not None and e.clock < from_clock:
                continue
            if until_clock is not None and e.clock > until_clock:
                break
            yield e

    def latest_clock(self) -> int:
        with self._lock:
            return self._entries[-1].clock if self._entries else 0

    def __len__(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# sqlite-backed
# ---------------------------------------------------------------------------


_OPLOG_DDL = """
CREATE TABLE IF NOT EXISTS oplog (
    clock        INTEGER PRIMARY KEY AUTOINCREMENT,
    operation    TEXT NOT NULL,
    target_id    TEXT,
    payload      TEXT NOT NULL DEFAULT '{}',
    actor        TEXT NOT NULL DEFAULT 'anonymous',
    received_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oplog_target ON oplog(target_id);
"""


class SqliteOpLog:
    """Op-log backed by a SQLite table.

    Designed to share a database file with ``SqliteStore`` so the store
    snapshot + the op-log live together and survive a single
    ``cp project.annot project.backup`` step.
    """

    def __init__(
        self,
        path: str,
        *,
        check_same_thread: bool = True,
    ) -> None:
        self._conn = sqlite3.connect(
            path,
            check_same_thread=check_same_thread,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_OPLOG_DDL)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def append(
        self,
        operation: str,
        *,
        target_id: str | None = None,
        payload: dict[str, Any] | None = None,
        actor: str = "anonymous",
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO oplog (operation, target_id, payload, actor, received_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    operation,
                    target_id,
                    json.dumps(payload or {}),
                    actor,
                    _time.time(),
                ),
            )
            return int(cur.lastrowid)

    def entries(
        self,
        *,
        until_clock: int | None = None,
        from_clock: int | None = None,
    ) -> Iterator[OpLogEntry]:
        sql = "SELECT * FROM oplog"
        clauses: list[str] = []
        params: list[Any] = []
        if from_clock is not None:
            clauses.append("clock >= ?")
            params.append(from_clock)
        if until_clock is not None:
            clauses.append("clock <= ?")
            params.append(until_clock)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY clock"

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        for row in rows:
            yield OpLogEntry(
                clock=int(row["clock"]),
                operation=str(row["operation"]),
                target_id=row["target_id"],
                payload=json.loads(row["payload"]),
                actor=str(row["actor"]),
                received_at=float(row["received_at"]),
            )

    def latest_clock(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(clock) AS c FROM oplog"
            ).fetchone()
        return int(row["c"]) if row and row["c"] is not None else 0

    def __len__(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM oplog").fetchone()
        return int(row["n"])


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


def replay(
    log: OpLog,
    *,
    until_clock: int | None = None,
    target_factory=None,
) -> Any:
    """Rebuild a store by replaying ``log`` up to (and including) ``until_clock``.

    Args:
        log: Source op-log.
        until_clock: Stop at this clock (inclusive). None = replay all.
        target_factory: Zero-arg callable returning a fresh empty store.
            Defaults to ``MemoryStore``. Pass a ``SqliteStore`` factory to
            replay into a persistent file.

    Returns:
        The rebuilt store. Operations whose payload references unknown
        body schemas or tier parents are still applied; the caller is
        responsible for any post-replay validation.
    """
    if target_factory is None:
        from lacing.store.memory import MemoryStore

        target_factory = MemoryStore
    store = target_factory()

    for entry in log.entries(until_clock=until_clock):
        _apply(store, entry)

    return store


def _apply(store: Any, entry: OpLogEntry) -> None:
    """Apply one entry to ``store``. Best-effort: unknown ops are skipped."""
    op = entry.operation
    payload = entry.payload

    if op == "add_tier":
        from lacing.tier import Tier, TierStereotype

        tier = Tier(
            payload["name"],
            stereotype=TierStereotype(payload.get("stereotype", "NONE")),
            parent=payload.get("parent"),
            metadata=payload.get("metadata") or {},
        )
        store.add_tier(tier)

    elif op == "add_annotation":
        from lacing.model import Annotation

        annotation = Annotation.model_validate(payload["annotation"])
        store.add(annotation)

    elif op == "remove_annotation":
        from uuid import UUID

        target = entry.target_id
        if target is not None:
            store.remove(UUID(target))

    elif op == "update_annotation":
        from lacing.model import Annotation
        from uuid import UUID

        ann_id = entry.target_id
        if ann_id is not None:
            store.remove(UUID(ann_id))
        annotation = Annotation.model_validate(payload["annotation"])
        store.add(annotation)

    elif op == "set_meta":
        set_fn = getattr(store, "set_meta", None)
        if callable(set_fn):
            set_fn(entry.target_id, payload["value"])

    # Unknown ops are ignored by replay; the entry is still in the log.


def has_entries(log: OpLog) -> bool:
    return log.latest_clock() > 0
