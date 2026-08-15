"""SQLite-backed annotation store and the ``.annot`` portable file format.

A ``SqliteStore`` is both:

1. A persistent backend implementing the ``IntervalAnnotationStore``
   protocol over a single SQLite file.
2. The on-disk shape of the ``.annot`` portable handoff format
   (BACK-DOC §3.1: "SQLite-as-app-format" — Git-trackable,
   email-attachable, single-file).

Design notes:

- The integer pair ``(start_value, start_rate)`` and ``(end_value, end_rate)``
  are the **source of truth** for time. Rational arithmetic stays exact.
- The R*Tree index uses ``REAL`` (float seconds) because SQLite's R*Tree
  requires it. We treat R*Tree results as a **pre-filter** and re-check
  boundary cases against the integer-pair columns. Any annotation whose
  rational seconds matches the query's bounds exactly will still be
  filtered correctly because we widen the R*Tree query by one ULP.
- Tier hierarchy is enforced via FK; stereotype validation is the
  application's job (see ``lacing.tier.validate_tier_constraint``).
- ``schema_version`` lives in the ``meta`` table; migrations register
  upgrade functions keyed on the from-version in
  :mod:`lacing.store.migrations` (the store-level counterpart of the
  body ladder in :mod:`lacing.schema`). Opening a stale file refuses
  unless asked to migrate (``SqliteStore(path, migrate=True)`` or
  ``lacing migrate <path>``), and refuses *before* touching the file.

See ``lacing-architecture`` (Phase 1) and BACK-DOC §3.1 for the why.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time as _time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

from lacing.allen import (
    PREDICATE_BY_RELATION,
    AllenRelation,
    intersects as _intersects,
)
from lacing.allen import (
    after as _after,
    before as _before,
)
from lacing.model import (
    Annotation,
    AnnotationRef,
    MediaRef,
    NodeRef,
    Provenance,
    Reference,
)
from lacing.tier import Tier, TierStereotype
from lacing.time import RationalTime, TimeInterval


SCHEMA_VERSION = 2
"""Current ``.annot`` schema version. Increment + register a migration
(:func:`lacing.store.migrations.register_store_migration`, with
``store_kind="sqlite"``) when making a breaking change to the table
layout.

v2 (lacing#14, defect D5): ``prov_was_derived_from`` may contain 64-hex
artifact ``asset_id`` strings alongside annotation UUIDs. The table layout
and every existing row are unchanged — the bump exists because **pre-v2
builds eagerly ``UUID()``-parse the column on read** and crash on the
first asset id, so they must refuse v2 files instead of opening them and
failing row-by-row. The v1→v2 migration step is accordingly stamp-only
(see :mod:`lacing.store.migrations`)."""


_DDL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiers (
    name        TEXT PRIMARY KEY,
    stereotype  TEXT NOT NULL,
    parent      TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (parent) REFERENCES tiers(name)
);

CREATE TABLE IF NOT EXISTS annotations (
    id              TEXT PRIMARY KEY,
    tier            TEXT NOT NULL,
    ref_kind        TEXT NOT NULL CHECK(ref_kind IN ('media', 'node', 'annotation')),
    asset_id        TEXT,
    scene_path      TEXT,
    target_id       TEXT,
    start_value     INTEGER,
    start_rate      INTEGER,
    end_value       INTEGER,
    end_rate        INTEGER,
    start_seconds   REAL,
    end_seconds     REAL,
    body            TEXT NOT NULL,
    body_schema_uri TEXT NOT NULL,
    prov_was_generated_by   TEXT NOT NULL,
    prov_was_attributed_to  TEXT NOT NULL,
    prov_was_derived_from   TEXT NOT NULL DEFAULT '[]',
    prov_generated_at_value INTEGER NOT NULL,
    prov_generated_at_rate  INTEGER NOT NULL,
    prov_activity           TEXT NOT NULL,
    confidence              REAL,
    FOREIGN KEY (tier) REFERENCES tiers(name)
);

CREATE INDEX IF NOT EXISTS idx_ann_tier ON annotations(tier);
CREATE INDEX IF NOT EXISTS idx_ann_asset ON annotations(asset_id);

CREATE VIRTUAL TABLE IF NOT EXISTS annotations_rtree USING rtree(
    rowid,
    start_seconds,
    end_seconds
);
"""


class SqliteStore:
    """SQLite-backed ``IntervalAnnotationStore``.

    Args:
        path: Path to the ``.annot`` file. Use ``":memory:"`` for an
            ephemeral in-memory database.
        check_same_thread: Forwarded to ``sqlite3.connect``. We hold a
            single connection guarded by a lock; pass ``False`` when
            sharing across threads.
        migrate: Opt-in to upgrading a file written at an older
            ``schema_version`` on open, via the ladder in
            :mod:`lacing.store.migrations`. Off by default — silently
            rewriting someone's file on open is worse than refusing.
            Every open-time schema failure — refusal *or* failed migration
            — raises :class:`SchemaMismatchError`; a failed migration
            chains the ladder's ``StoreMigrationError`` as its cause.
    """

    def __init__(
        self,
        path: str | os.PathLike,
        *,
        check_same_thread: bool = True,
        migrate: bool = False,
    ) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            os.fspath(path),
            check_same_thread=check_same_thread,
            isolation_level=None,  # autocommit; we use explicit transactions
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema(migrate=migrate)

    # --- low-level ------------------------------------------------------

    def _init_schema(self, *, migrate: bool = False) -> None:
        with self._lock:
            cur = self._conn.cursor()
            # Version check FIRST: the current build's DDL must not touch a
            # file stamped with another version — refusing after mutating
            # would leave a v1 file with v2 tables in it.
            got = self._stamped_schema_version(cur)
            if got is not None and got != SCHEMA_VERSION:
                if migrate and got < SCHEMA_VERSION:
                    from lacing.store.migrations import (
                        StoreMigrationError,
                        migrate_sqlite_connection,
                    )

                    try:
                        migrate_sqlite_connection(self._conn, to_version=SCHEMA_VERSION)
                    except StoreMigrationError as exc:
                        # Open-time failures keep the documented type; the
                        # ladder's diagnosis rides along as the cause.
                        raise SchemaMismatchError(
                            f"file has schema_version={got} and migrating it "
                            f"to {SCHEMA_VERSION} failed: {exc}"
                        ) from exc
                    # A concurrent migrator (possibly a different build) may
                    # have carried the file elsewhere — trust only a re-read.
                    got = self._stamped_schema_version(cur)
                    if got != SCHEMA_VERSION:
                        raise SchemaMismatchError(_schema_mismatch_message(got))
                else:
                    raise SchemaMismatchError(_schema_mismatch_message(got))
            cur.executescript(_DDL)
            if got is None:
                cur.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                cur.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?)",
                    ("created_at", str(int(_time.time()))),
                )

    @staticmethod
    def _stamped_schema_version(cur: sqlite3.Cursor) -> int | None:
        """The file's recorded ``schema_version``, or ``None`` for a fresh file.

        Read without running any DDL: a missing ``meta`` table (fresh or
        pre-lacing file) reads as ``None`` and gets the current schema.
        """
        has_meta = cur.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
        ).fetchone()
        if has_meta is None:
            return None
        row = cur.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        return None if row is None else int(row["value"])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "SqliteStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- meta -----------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else row["value"]

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    @property
    def schema_version(self) -> int:
        v = self.get_meta("schema_version")
        return SCHEMA_VERSION if v is None else int(v)

    @property
    def path(self) -> str | os.PathLike:
        return self._path

    # --- tier registry --------------------------------------------------

    def add_tier(self, tier: Tier) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO tiers (name, stereotype, parent, metadata) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "    stereotype = excluded.stereotype, "
                "    parent     = excluded.parent, "
                "    metadata   = excluded.metadata",
                (
                    tier.name,
                    tier.stereotype.value,
                    tier.parent,
                    json.dumps(tier.metadata),
                ),
            )

    def get_tier(self, name: str) -> Tier | None:
        row = self._conn.execute(
            "SELECT name, stereotype, parent, metadata FROM tiers WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_tier(row)

    def tiers(self) -> Iterator[Tier]:
        rows = self._conn.execute(
            "SELECT name, stereotype, parent, metadata FROM tiers"
        ).fetchall()
        return iter([_row_to_tier(r) for r in rows])

    # --- annotation CRUD -----------------------------------------------

    def add(self, annotation: Annotation) -> None:
        cols, values = _annotation_to_row(annotation)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                f"INSERT INTO annotations ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                values,
            )
            iv = annotation.interval
            if iv is not None:
                rowid = cur.lastrowid
                start_s = float(iv.start.to_fraction())
                end_s = float(iv.end.to_fraction())
                # Widen by one ULP so float→exact-bound comparisons don't drop hits.
                cur.execute(
                    "INSERT INTO annotations_rtree (rowid, start_seconds, end_seconds) "
                    "VALUES (?, ?, ?)",
                    (
                        rowid,
                        math.nextafter(start_s, -math.inf),
                        math.nextafter(end_s, math.inf),
                    ),
                )

    def remove(self, annotation_id: UUID) -> Annotation | None:
        ann = self._fetch_one(annotation_id)
        if ann is None:
            return None
        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute(
                "SELECT rowid FROM annotations WHERE id = ?", (str(annotation_id),)
            ).fetchone()
            if row is not None:
                cur.execute(
                    "DELETE FROM annotations_rtree WHERE rowid = ?", (row["rowid"],)
                )
            cur.execute("DELETE FROM annotations WHERE id = ?", (str(annotation_id),))
        return ann

    def _fetch_one(self, annotation_id: UUID) -> Annotation | None:
        row = self._conn.execute(
            "SELECT * FROM annotations WHERE id = ?", (str(annotation_id),)
        ).fetchone()
        return None if row is None else _row_to_annotation(row)

    def all(self) -> Iterator[Annotation]:
        for row in self._conn.execute("SELECT * FROM annotations"):
            yield _row_to_annotation(row)

    def __len__(self) -> int:
        # __len__ matches the MutableMapping facade: number of distinct
        # interval keys in the store, not number of annotations.
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM ("
            "  SELECT DISTINCT start_value, start_rate, end_value, end_rate "
            "  FROM annotations "
            "  WHERE ref_kind = 'media'"
            ")"
        ).fetchone()
        return row["n"]

    def __iter__(self) -> Iterator[TimeInterval]:
        for row in self._conn.execute(
            "SELECT DISTINCT start_value, start_rate, end_value, end_rate "
            "FROM annotations "
            "WHERE ref_kind = 'media' "
            "ORDER BY start_seconds, end_seconds"
        ):
            yield TimeInterval(
                RationalTime(row["start_value"], row["start_rate"]),
                RationalTime(row["end_value"], row["end_rate"]),
            )

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, TimeInterval):
            return False
        row = self._conn.execute(
            "SELECT 1 FROM annotations WHERE "
            "  start_value = ? AND start_rate = ? AND end_value = ? AND end_rate = ? "
            "LIMIT 1",
            (key.start.value, key.start.rate, key.end.value, key.end.rate),
        ).fetchone()
        return row is not None

    def __getitem__(self, key: TimeInterval) -> list[Annotation]:
        rows = self._conn.execute(
            "SELECT * FROM annotations WHERE "
            "  start_value = ? AND start_rate = ? AND end_value = ? AND end_rate = ?",
            (key.start.value, key.start.rate, key.end.value, key.end.rate),
        ).fetchall()
        if not rows:
            raise KeyError(key)
        return [_row_to_annotation(r) for r in rows]

    def __setitem__(self, key: TimeInterval, value: list[Annotation]) -> None:
        with self._lock:
            cur = self._conn.cursor()
            # Find existing rowids at this key and clear them.
            existing = cur.execute(
                "SELECT rowid FROM annotations WHERE "
                "  start_value = ? AND start_rate = ? AND end_value = ? AND end_rate = ?",
                (key.start.value, key.start.rate, key.end.value, key.end.rate),
            ).fetchall()
            for row in existing:
                cur.execute(
                    "DELETE FROM annotations_rtree WHERE rowid = ?", (row["rowid"],)
                )
            cur.execute(
                "DELETE FROM annotations WHERE "
                "  start_value = ? AND start_rate = ? AND end_value = ? AND end_rate = ?",
                (key.start.value, key.start.rate, key.end.value, key.end.rate),
            )
        for ann in value:
            self.add(ann)

    def __delitem__(self, key: TimeInterval) -> None:
        if key not in self:
            raise KeyError(key)
        self[key] = []

    # --- Allen-relation queries ----------------------------------------

    def intersects(self, query: TimeInterval) -> Iterator[Annotation]:
        # R*Tree pre-filter: rows whose [start, end] overlaps query interval.
        return self._candidates_filtered(query, _intersects)

    def during(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._candidates_filtered(
            query, PREDICATE_BY_RELATION[AllenRelation.DURING]
        )

    def contains(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._candidates_filtered(
            query, PREDICATE_BY_RELATION[AllenRelation.CONTAINS]
        )

    def overlaps(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._candidates_filtered(
            query, PREDICATE_BY_RELATION[AllenRelation.OVERLAPS]
        )

    def meets(self, query: TimeInterval) -> Iterator[Annotation]:
        # meets(a, q): a.end == q.start. R*Tree won't help — scan all.
        return self._scan_filtered(PREDICATE_BY_RELATION[AllenRelation.MEETS], query)

    def starts(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._candidates_filtered(
            query, PREDICATE_BY_RELATION[AllenRelation.STARTS]
        )

    def finishes(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._candidates_filtered(
            query, PREDICATE_BY_RELATION[AllenRelation.FINISHES]
        )

    def equals(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._candidates_filtered(
            query, PREDICATE_BY_RELATION[AllenRelation.EQUALS]
        )

    def relate(
        self, query: TimeInterval, relations: Iterable[AllenRelation]
    ) -> Iterator[Annotation]:
        rels = set(relations)
        # If only "before" or "after" relations are requested, R*Tree is a
        # net loss; for everything else it pays.
        if rels <= {AllenRelation.BEFORE, AllenRelation.AFTER}:
            yield from self._scan_filtered(
                lambda iv, q: any(PREDICATE_BY_RELATION[r](iv, q) for r in rels),
                query,
            )
            return
        for ann in self._candidates(query):
            iv = ann.interval
            if iv is None:
                continue
            for r in rels:
                if PREDICATE_BY_RELATION[r](iv, query):
                    yield ann
                    break

    # --- tier filters --------------------------------------------------

    def by_tier(self, tier_name: str) -> Iterator[Annotation]:
        for row in self._conn.execute(
            "SELECT * FROM annotations WHERE tier = ?", (tier_name,)
        ):
            yield _row_to_annotation(row)

    def at_tier(self, tier_name: str, query: TimeInterval) -> Iterator[Annotation]:
        for ann in self.intersects(query):
            if ann.tier == tier_name:
                yield ann

    # --- bulk ----------------------------------------------------------

    def extend(self, annotations: Iterable[Annotation]) -> None:
        # Batch insert inside a single transaction for throughput.
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            try:
                for ann in annotations:
                    cols, values = _annotation_to_row(ann)
                    cur.execute(
                        f"INSERT INTO annotations ({', '.join(cols)}) "
                        f"VALUES ({', '.join('?' for _ in cols)})",
                        values,
                    )
                    iv = ann.interval
                    if iv is not None:
                        rowid = cur.lastrowid
                        start_s = float(iv.start.to_fraction())
                        end_s = float(iv.end.to_fraction())
                        cur.execute(
                            "INSERT INTO annotations_rtree (rowid, start_seconds, end_seconds) "
                            "VALUES (?, ?, ?)",
                            (
                                rowid,
                                math.nextafter(start_s, -math.inf),
                                math.nextafter(end_s, math.inf),
                            ),
                        )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise

    # --- candidate filtering ------------------------------------------

    def _candidates(self, query: TimeInterval) -> Iterator[Annotation]:
        """R*Tree pre-filter: yield annotations whose float bounding box
        overlaps the query (widened by one ULP either side).

        Caller re-checks with exact rational predicates.
        """
        q_start = float(query.start.to_fraction())
        q_end = float(query.end.to_fraction())
        # We want any rect whose [start, end] overlaps [q_start, q_end] —
        # plus the boundary cases that ULP-widening might still miss. Use
        # a slightly wider query to be safe.
        widened_start = math.nextafter(q_start, -math.inf)
        widened_end = math.nextafter(q_end, math.inf)
        sql = (
            "SELECT a.* FROM annotations a "
            "JOIN annotations_rtree r ON a.rowid = r.rowid "
            "WHERE r.start_seconds <= ? AND r.end_seconds >= ?"
        )
        for row in self._conn.execute(sql, (widened_end, widened_start)):
            yield _row_to_annotation(row)

    def _candidates_filtered(
        self, query: TimeInterval, predicate
    ) -> Iterator[Annotation]:
        for ann in self._candidates(query):
            iv = ann.interval
            if iv is not None and predicate(iv, query):
                yield ann

    def _scan_filtered(self, predicate, query: TimeInterval) -> Iterator[Annotation]:
        for ann in self.all():
            iv = ann.interval
            if iv is not None and predicate(iv, query):
                yield ann

    # --- repr ---------------------------------------------------------

    def __repr__(self) -> str:
        try:
            n_anns = self._conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[
                0
            ]
            n_tiers = self._conn.execute("SELECT COUNT(*) FROM tiers").fetchone()[0]
        except sqlite3.Error:
            return f"SqliteStore({self._path!r}, <closed>)"
        return f"SqliteStore({self._path!r}, {n_anns} annotations, {n_tiers} tiers)"


# ---------------------------------------------------------------------------
# row <-> annotation conversion
# ---------------------------------------------------------------------------


_ANN_COLUMNS = (
    "id",
    "tier",
    "ref_kind",
    "asset_id",
    "scene_path",
    "target_id",
    "start_value",
    "start_rate",
    "end_value",
    "end_rate",
    "start_seconds",
    "end_seconds",
    "body",
    "body_schema_uri",
    "prov_was_generated_by",
    "prov_was_attributed_to",
    "prov_was_derived_from",
    "prov_generated_at_value",
    "prov_generated_at_rate",
    "prov_activity",
    "confidence",
)


def _annotation_to_row(ann: Annotation) -> tuple[tuple[str, ...], tuple[Any, ...]]:
    ref = ann.reference
    ref_kind: str
    asset_id: str | None = None
    scene_path: str | None = None
    target_id: str | None = None
    start_value: int | None = None
    start_rate: int | None = None
    end_value: int | None = None
    end_rate: int | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None

    if isinstance(ref, MediaRef):
        ref_kind = "media"
        asset_id = ref.asset_id
        iv = ref.interval
    elif isinstance(ref, NodeRef):
        ref_kind = "node"
        scene_path = ref.scene_path
        iv = ref.interval
    elif isinstance(ref, AnnotationRef):
        ref_kind = "annotation"
        target_id = str(ref.target_id)
        iv = ref.interval
    else:  # pragma: no cover  — discriminated union covers all cases
        raise TypeError(f"unknown reference kind: {type(ref).__name__}")

    if iv is not None:
        start_value = iv.start.value
        start_rate = iv.start.rate
        end_value = iv.end.value
        end_rate = iv.end.rate
        start_seconds = float(iv.start.to_fraction())
        end_seconds = float(iv.end.to_fraction())

    values = (
        str(ann.id),
        ann.tier,
        ref_kind,
        asset_id,
        scene_path,
        target_id,
        start_value,
        start_rate,
        end_value,
        end_rate,
        start_seconds,
        end_seconds,
        json.dumps(ann.body),
        ann.body_schema_uri,
        ann.provenance.was_generated_by,
        ann.provenance.was_attributed_to,
        json.dumps([str(u) for u in ann.provenance.was_derived_from]),
        ann.provenance.generated_at_time.value,
        ann.provenance.generated_at_time.rate,
        ann.provenance.activity,
        ann.confidence,
    )
    return _ANN_COLUMNS, values


def _row_to_annotation(row: sqlite3.Row) -> Annotation:
    interval: TimeInterval | None
    if row["start_value"] is not None:
        interval = TimeInterval(
            RationalTime(row["start_value"], row["start_rate"]),
            RationalTime(row["end_value"], row["end_rate"]),
        )
    else:
        interval = None

    ref: Reference
    kind = row["ref_kind"]
    if kind == "media":
        if interval is None:
            raise _RowDecodeError("media ref row has no interval columns set")
        ref = MediaRef(asset_id=row["asset_id"], interval=interval)
    elif kind == "node":
        if interval is None:
            raise _RowDecodeError("node ref row has no interval columns set")
        ref = NodeRef(scene_path=row["scene_path"], interval=interval)
    elif kind == "annotation":
        ref = AnnotationRef(
            target_id=UUID(row["target_id"]),
            interval=interval,
        )
    else:  # pragma: no cover  — CHECK constraint blocks other values
        raise _RowDecodeError(f"unknown ref_kind: {kind!r}")

    provenance = Provenance(
        was_generated_by=row["prov_was_generated_by"],
        was_attributed_to=row["prov_was_attributed_to"],
        # Raw strings: the Provenance union (UUID | AssetId) discriminates.
        # An eager UUID() here is exactly what pre-v2 builds did — and why
        # v2 exists (they crash on the first asset id; see SCHEMA_VERSION).
        was_derived_from=json.loads(row["prov_was_derived_from"]),
        generated_at_time=RationalTime(
            row["prov_generated_at_value"], row["prov_generated_at_rate"]
        ),
        activity=row["prov_activity"],
    )

    return Annotation(
        id=UUID(row["id"]),
        tier=row["tier"],
        reference=ref,
        body=json.loads(row["body"]),
        body_schema_uri=row["body_schema_uri"],
        provenance=provenance,
        confidence=row["confidence"],
    )


def _row_to_tier(row: sqlite3.Row) -> Tier:
    return Tier(
        row["name"],
        stereotype=TierStereotype(row["stereotype"]),
        parent=row["parent"],
        metadata=json.loads(row["metadata"]),
    )


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class SchemaMismatchError(RuntimeError):
    """Raised when opening a ``.annot`` file with an incompatible schema."""


def _schema_mismatch_message(got: int) -> str:
    """The actionable half of a schema refusal: what to do about it.

    Names the versions actually reachable from the one found on disk, so
    "run a migration" stops being an instruction with no referent
    (lacing#15).
    """
    from lacing.store.migrations import SQLITE_KIND, reachable_versions

    head = f"file has schema_version={got}, this build expects {SCHEMA_VERSION}."
    if got > SCHEMA_VERSION:
        return (
            f"{head} The file is newer than this build — upgrade lacing to "
            "open it (store migrations are forward-only)."
        )
    reachable = reachable_versions(SQLITE_KIND, got)
    if SCHEMA_VERSION in reachable:
        return (
            f"{head} A migration path exists (v{got} -> v{SCHEMA_VERSION}): "
            "reopen with SqliteStore(path, migrate=True), or run "
            "`lacing migrate <path>`."
        )
    reachable_note = (
        f" (registered steps only reach: {', '.join(f'v{v}' for v in reachable)})"
        if reachable
        else ""
    )
    return (
        f"{head} No registered migration reaches v{SCHEMA_VERSION} from "
        f"v{got}{reachable_note} — this build cannot upgrade the file."
    )


class _RowDecodeError(RuntimeError):
    """Internal: a row violated the schema invariants."""


# ---------------------------------------------------------------------------
# convenience: convert between memory and sqlite stores
# ---------------------------------------------------------------------------


def from_memory(memory_store, target: str | os.PathLike) -> SqliteStore:
    """Persist an in-memory store to a new ``.annot`` file."""
    Path(os.fspath(target)).unlink(missing_ok=True)
    sqlite_store = SqliteStore(target)
    for tier in memory_store.tiers():
        sqlite_store.add_tier(tier)
    sqlite_store.extend(memory_store.all())
    return sqlite_store


def to_memory(sqlite_store: SqliteStore):
    """Load a ``.annot`` file fully into a ``MemoryStore``."""
    from lacing.store.memory import MemoryStore

    mem = MemoryStore()
    for tier in sqlite_store.tiers():
        mem.add_tier(tier)
    mem.extend(sqlite_store.all())
    return mem
