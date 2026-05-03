"""PostgreSQL-backed annotation store using ``int8range`` + GiST.

Maps lacing's interval model to Postgres native range types (BACK-DOC §4.2):

============== =====================================================
Allen relation Postgres operator (int8range / tstzrange)
============== =====================================================
overlaps (any) ``a && b``      — any kind of intersection
during         ``a <@ b``      — a contained in b (strict variant: see code)
contains       ``a @> b``      — a contains b (strict variant: see code)
meets / met_by ``a -|- b``     — adjacent (touching but not overlapping)
equals         ``a = b``
before         ``a << b``
after          ``a >> b``
strict overlap ``a && b AND lower(a) < lower(b) AND upper(a) < upper(b)``
============== =====================================================

We store intervals as ``int8range(start_value, end_value, '[)')`` — half-open,
matching lacing's ``TimeInterval`` semantics — at a **project-wide rate**
recorded in ``meta``. All inserts must be at that rate; re-quantizing happens
on insert if necessary.

GiST index on the range column gives sub-millisecond overlap queries at
million-row scale. Optional ``EXCLUDE USING GIST`` constraints are added
**per tier** for stereotypes like ``TIME_SUBDIVISION`` that forbid overlap.

Schema versioning lives in ``meta``; mismatched versions raise on open.

Status: Phase 1. Tested via ``pytest-postgresql`` sandbox (no live server
needed for development).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from lacing.allen import (
    PREDICATE_BY_RELATION,
    AllenRelation,
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
from lacing.time import LossyTimeConversionError, RationalTime, TimeInterval


SCHEMA_VERSION = 1
"""Current schema version stored in the ``meta`` table."""


_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiers (
    name        TEXT PRIMARY KEY,
    stereotype  TEXT NOT NULL,
    parent      TEXT REFERENCES tiers(name) ON DELETE RESTRICT,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    enforce_no_overlap BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS annotations (
    id              UUID PRIMARY KEY,
    tier            TEXT NOT NULL REFERENCES tiers(name) ON DELETE RESTRICT,
    ref_kind        TEXT NOT NULL CHECK (ref_kind IN ('media', 'node', 'annotation')),
    asset_id        TEXT,
    scene_path      TEXT,
    target_id       UUID,
    span            INT8RANGE,                 -- NULL only when ref has no interval
    body            JSONB NOT NULL,
    body_schema_uri TEXT NOT NULL,
    prov_was_generated_by   TEXT NOT NULL,
    prov_was_attributed_to  TEXT NOT NULL,
    prov_was_derived_from   JSONB NOT NULL DEFAULT '[]'::jsonb,
    prov_generated_at_value BIGINT NOT NULL,
    prov_generated_at_rate  INTEGER NOT NULL,
    prov_activity           TEXT NOT NULL,
    confidence              REAL
);

-- GiST spatial index over the range column for sub-ms overlap queries.
CREATE INDEX IF NOT EXISTS idx_ann_span_gist ON annotations USING GIST (span);
CREATE INDEX IF NOT EXISTS idx_ann_tier      ON annotations (tier);
CREATE INDEX IF NOT EXISTS idx_ann_asset     ON annotations (asset_id);
"""


# Per-tier non-overlap constraint (added on demand when a tier is registered
# with enforce_no_overlap=True). Constraint name is unique per tier.
_PER_TIER_EXCLUSION_DDL = """
ALTER TABLE annotations
    ADD CONSTRAINT no_overlap_in_{tier_id}
    EXCLUDE USING GIST (span WITH &&)
    WHERE (tier = {tier_lit})
"""


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class PgSchemaMismatchError(RuntimeError):
    """Raised on opening a database whose schema_version differs."""


class TierOverlapError(RuntimeError):
    """Raised when an insert would violate a per-tier no-overlap constraint."""


class RateMismatchError(LossyTimeConversionError):
    """Raised when an annotation's interval cannot be represented at the project rate."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _require_psycopg():
    try:
        import psycopg
        from psycopg import sql
        from psycopg.types.range import Range
    except ImportError as exc:  # pragma: no cover  — covered by extra missing
        raise ImportError(
            "PostgresStore requires psycopg. Install with: "
            "pip install 'lacing[postgres]'  (or directly: pip install 'psycopg[binary]')"
        ) from exc
    return psycopg, sql, Range


def _safe_tier_id(name: str) -> str:
    """Build a constraint-name-safe identifier from a tier name."""
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch.lower())
        else:
            out.append("_")
    return "".join(out)[:50] or "tier"


# ---------------------------------------------------------------------------
# PostgresStore
# ---------------------------------------------------------------------------


class PostgresStore:
    """PostgreSQL-backed ``IntervalAnnotationStore``.

    Args:
        connection_string: A psycopg-compatible URL or kwargs dict.
        rate: Project-wide rate. Set on first init; a re-open with a
            different rate raises ``PgSchemaMismatchError``.
        autocommit: If True (default), we run individual statements in
            their own transaction. Set to False when batching via
            :meth:`extend` (it manages its own BEGIN/COMMIT).
    """

    def __init__(
        self,
        connection_string: str | dict,
        *,
        rate: int = 24000,
        autocommit: bool = True,
    ) -> None:
        psycopg, _sql, _range = _require_psycopg()
        self._psycopg = psycopg
        self._sql = _sql
        self._Range = _range

        if isinstance(connection_string, dict):
            self._conn = psycopg.connect(**connection_string, autocommit=autocommit)
        else:
            self._conn = psycopg.connect(connection_string, autocommit=autocommit)

        self._init_schema(rate)

    # --- schema --------------------------------------------------------

    def _init_schema(self, rate: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_DDL)
            row = cur.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO meta (key, value) VALUES (%s, %s)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                cur.execute(
                    "INSERT INTO meta (key, value) VALUES (%s, %s)",
                    ("rate", str(rate)),
                )
                self._rate = rate
            else:
                got_version = int(row[0])
                if got_version != SCHEMA_VERSION:
                    raise PgSchemaMismatchError(
                        f"database has schema_version={got_version}, "
                        f"this build expects {SCHEMA_VERSION}."
                    )
                row = cur.execute(
                    "SELECT value FROM meta WHERE key = 'rate'"
                ).fetchone()
                stored_rate = int(row[0]) if row else rate
                if rate != stored_rate:
                    raise PgSchemaMismatchError(
                        f"database has rate={stored_rate}, opened with rate={rate}. "
                        f"Re-quantize the data or open with the original rate."
                    )
                self._rate = stored_rate

    @property
    def rate(self) -> int:
        return self._rate

    @property
    def schema_version(self) -> int:
        return SCHEMA_VERSION

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PostgresStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- meta ----------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._conn.cursor() as cur:
            row = cur.execute(
                "SELECT value FROM meta WHERE key = %s", (key,)
            ).fetchone()
            return None if row is None else row[0]

    def set_meta(self, key: str, value: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meta (key, value) VALUES (%s, %s) "
                "ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )

    # --- tier registry ------------------------------------------------

    def add_tier(self, tier: Tier, *, enforce_no_overlap: bool = False) -> None:
        """Add or update a tier.

        Args:
            tier: Tier definition.
            enforce_no_overlap: If True, install a per-tier ``EXCLUDE USING
                GIST`` constraint forbidding overlapping annotations within
                this tier. Required for proper TIME_SUBDIVISION enforcement.
                Cannot be toggled after the tier has annotations.
        """
        psycopg = self._psycopg
        sql = self._sql

        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tiers (name, stereotype, parent, metadata, enforce_no_overlap) "
                "VALUES (%s, %s, %s, %s::jsonb, %s) "
                "ON CONFLICT(name) DO UPDATE SET "
                "  stereotype = EXCLUDED.stereotype, "
                "  parent     = EXCLUDED.parent, "
                "  metadata   = EXCLUDED.metadata, "
                "  enforce_no_overlap = EXCLUDED.enforce_no_overlap",
                (
                    tier.name,
                    tier.stereotype.value,
                    tier.parent,
                    json.dumps(tier.metadata),
                    enforce_no_overlap,
                ),
            )

            constraint_name = f"no_overlap_in_{_safe_tier_id(tier.name)}"
            existing = cur.execute(
                "SELECT 1 FROM pg_constraint WHERE conname = %s",
                (constraint_name,),
            ).fetchone()

            if enforce_no_overlap and not existing:
                # Install the partial EXCLUDE constraint.
                stmt = sql.SQL(
                    "ALTER TABLE annotations "
                    "ADD CONSTRAINT {name} EXCLUDE USING GIST (span WITH &&) "
                    "WHERE (tier = {tier_lit})"
                ).format(
                    name=sql.Identifier(constraint_name),
                    tier_lit=sql.Literal(tier.name),
                )
                cur.execute(stmt)
            elif not enforce_no_overlap and existing:
                stmt = sql.SQL("ALTER TABLE annotations DROP CONSTRAINT {name}").format(
                    name=sql.Identifier(constraint_name),
                )
                cur.execute(stmt)

    def get_tier(self, name: str) -> Tier | None:
        with self._conn.cursor() as cur:
            row = cur.execute(
                "SELECT name, stereotype, parent, metadata FROM tiers WHERE name = %s",
                (name,),
            ).fetchone()
            return None if row is None else _row_to_tier(row)

    def tiers(self) -> Iterator[Tier]:
        with self._conn.cursor() as cur:
            rows = cur.execute(
                "SELECT name, stereotype, parent, metadata FROM tiers ORDER BY name"
            ).fetchall()
        return iter([_row_to_tier(r) for r in rows])

    def is_no_overlap_enforced(self, tier_name: str) -> bool:
        with self._conn.cursor() as cur:
            row = cur.execute(
                "SELECT enforce_no_overlap FROM tiers WHERE name = %s",
                (tier_name,),
            ).fetchone()
            return bool(row[0]) if row else False

    # --- annotation CRUD ---------------------------------------------

    def add(self, annotation: Annotation) -> None:
        try:
            self._do_add(annotation)
        except self._psycopg.errors.ExclusionViolation as exc:
            raise TierOverlapError(
                f"annotation {annotation.id} would overlap an existing one in tier "
                f"{annotation.tier!r} (per-tier EXCLUDE constraint is active)"
            ) from exc

    def _do_add(self, annotation: Annotation) -> None:
        cols, values = self._annotation_to_row(annotation)
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO annotations ({', '.join(cols)}) "
                f"VALUES ({', '.join('%s' for _ in cols)})",
                values,
            )

    def remove(self, annotation_id: UUID) -> Annotation | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM annotations WHERE id = %s", (annotation_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
            ann = self._row_to_annotation(dict(zip(cols, row)))
            cur.execute("DELETE FROM annotations WHERE id = %s", (annotation_id,))
        return ann

    def all(self) -> Iterator[Annotation]:
        with self._conn.cursor() as cur:
            rows = cur.execute("SELECT * FROM annotations").fetchall()
            cols = [d.name for d in cur.description]
        for row in rows:
            yield self._row_to_annotation(dict(zip(cols, row)))

    def __len__(self) -> int:
        # Number of distinct interval keys; matches MutableMapping facade.
        with self._conn.cursor() as cur:
            row = cur.execute(
                "SELECT COUNT(DISTINCT span) FROM annotations "
                "WHERE ref_kind = 'media' AND span IS NOT NULL"
            ).fetchone()
            return int(row[0])

    def __iter__(self) -> Iterator[TimeInterval]:
        with self._conn.cursor() as cur:
            rows = cur.execute(
                "SELECT span FROM ("
                "  SELECT DISTINCT span FROM annotations "
                "  WHERE ref_kind = 'media' AND span IS NOT NULL"
                ") AS d "
                "ORDER BY lower(span), upper(span)"
            ).fetchall()
        for (span,) in rows:
            yield self._span_to_interval(span)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, TimeInterval):
            return False
        span = self._interval_to_span(key)
        with self._conn.cursor() as cur:
            row = cur.execute(
                "SELECT 1 FROM annotations WHERE span = %s LIMIT 1", (span,)
            ).fetchone()
        return row is not None

    def __getitem__(self, key: TimeInterval) -> list[Annotation]:
        span = self._interval_to_span(key)
        with self._conn.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM annotations WHERE span = %s", (span,)
            ).fetchall()
            cols = [d.name for d in cur.description] if cur.description else []
        if not rows:
            raise KeyError(key)
        return [self._row_to_annotation(dict(zip(cols, r))) for r in rows]

    def __setitem__(self, key: TimeInterval, value: list[Annotation]) -> None:
        span = self._interval_to_span(key)
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM annotations WHERE span = %s", (span,))
        for ann in value:
            self.add(ann)

    def __delitem__(self, key: TimeInterval) -> None:
        if key not in self:
            raise KeyError(key)
        self[key] = []

    # --- Allen-relation queries ---------------------------------------

    def intersects(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._query_with_op("&&", query)

    def during(self, query: TimeInterval) -> Iterator[Annotation]:
        # Strict: a's span is strictly inside q (Allen 'd' excludes shared
        # endpoints). We pre-filter with `<@` then re-check exact rationals.
        return self._candidates_filtered("<@", query, AllenRelation.DURING)

    def contains(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._candidates_filtered("@>", query, AllenRelation.CONTAINS)

    def overlaps(self, query: TimeInterval) -> Iterator[Annotation]:
        # Strict Allen 'o': pre-filter with `&&`, re-check rationals.
        return self._candidates_filtered("&&", query, AllenRelation.OVERLAPS)

    def meets(self, query: TimeInterval) -> Iterator[Annotation]:
        # `-|-` matches both meets and met_by; rational predicate disambiguates.
        return self._candidates_filtered("-|-", query, AllenRelation.MEETS)

    def starts(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._candidates_filtered("&&", query, AllenRelation.STARTS)

    def finishes(self, query: TimeInterval) -> Iterator[Annotation]:
        return self._candidates_filtered("&&", query, AllenRelation.FINISHES)

    def equals(self, query: TimeInterval) -> Iterator[Annotation]:
        # Range equality matches Allen '=' exactly.
        return self._query_with_op("=", query)

    def relate(
        self, query: TimeInterval, relations: Iterable[AllenRelation]
    ) -> Iterator[Annotation]:
        rels = set(relations)
        # Pick the broadest pre-filter that covers all requested relations.
        if rels <= {AllenRelation.BEFORE, AllenRelation.AFTER}:
            for ann in self._scan_filtered(rels, query):
                yield ann
            return
        # Fall back to a candidate scan over `&&` ∪ `-|-` (covers all overlap +
        # touching cases), then exact rationals.
        for ann in self._touching_candidates(query):
            iv = ann.interval
            if iv is None:
                continue
            for r in rels:
                if PREDICATE_BY_RELATION[r](iv, query):
                    yield ann
                    break

    def _query_with_op(self, op: str, query: TimeInterval) -> Iterator[Annotation]:
        span = self._interval_to_span(query)
        with self._conn.cursor() as cur:
            sql_text = f"SELECT * FROM annotations WHERE span {op} %s"
            rows = cur.execute(sql_text, (span,)).fetchall()
            cols = [d.name for d in cur.description] if cur.description else []
        for row in rows:
            yield self._row_to_annotation(dict(zip(cols, row)))

    def _candidates_filtered(
        self, op: str, query: TimeInterval, relation: AllenRelation
    ) -> Iterator[Annotation]:
        predicate = PREDICATE_BY_RELATION[relation]
        for ann in self._query_with_op(op, query):
            iv = ann.interval
            if iv is not None and predicate(iv, query):
                yield ann

    def _scan_filtered(
        self, relations: set[AllenRelation], query: TimeInterval
    ) -> Iterator[Annotation]:
        for ann in self.all():
            iv = ann.interval
            if iv is None:
                continue
            for r in relations:
                if PREDICATE_BY_RELATION[r](iv, query):
                    yield ann
                    break

    def _touching_candidates(self, query: TimeInterval) -> Iterator[Annotation]:
        span = self._interval_to_span(query)
        with self._conn.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM annotations WHERE (span && %s) OR (span -|- %s)",
                (span, span),
            ).fetchall()
            cols = [d.name for d in cur.description] if cur.description else []
        for row in rows:
            yield self._row_to_annotation(dict(zip(cols, row)))

    # --- tier filters ------------------------------------------------

    def by_tier(self, tier_name: str) -> Iterator[Annotation]:
        with self._conn.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM annotations WHERE tier = %s", (tier_name,)
            ).fetchall()
            cols = [d.name for d in cur.description] if cur.description else []
        for row in rows:
            yield self._row_to_annotation(dict(zip(cols, row)))

    def at_tier(self, tier_name: str, query: TimeInterval) -> Iterator[Annotation]:
        for ann in self.intersects(query):
            if ann.tier == tier_name:
                yield ann

    # --- bulk -------------------------------------------------------

    def extend(self, annotations: Iterable[Annotation]) -> None:
        with self._transaction():
            for ann in annotations:
                self._do_add(ann)

    @contextmanager
    def _transaction(self):
        conn = self._conn
        was_autocommit = conn.autocommit
        if was_autocommit:
            conn.autocommit = False
        try:
            yield
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if was_autocommit:
                conn.autocommit = True

    # --- repr -------------------------------------------------------

    def __repr__(self) -> str:
        try:
            with self._conn.cursor() as cur:
                n_anns = cur.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
                n_tiers = cur.execute("SELECT COUNT(*) FROM tiers").fetchone()[0]
        except Exception:  # pragma: no cover  — closed connection
            return f"PostgresStore(<closed>)"
        return (
            f"PostgresStore({n_anns} annotations, {n_tiers} tiers, rate={self._rate})"
        )

    # --- conversion helpers -----------------------------------------

    def _interval_to_span(self, iv: TimeInterval):
        start = self._normalize_value(iv.start)
        end = self._normalize_value(iv.end)
        return self._Range(start, end, "[)")

    def _normalize_value(self, t: RationalTime) -> int:
        """Convert a RationalTime to integer ticks at the project rate."""
        if t.rate == self._rate:
            return t.value
        # Use to_rate which raises on lossy conversion
        try:
            return t.to_rate(self._rate).value
        except LossyTimeConversionError as exc:
            raise RateMismatchError(
                f"RationalTime {t!r} cannot be expressed at project rate "
                f"{self._rate} without loss"
            ) from exc

    def _span_to_interval(self, span) -> TimeInterval:
        return TimeInterval(
            RationalTime(span.lower, self._rate),
            RationalTime(span.upper, self._rate),
        )

    def _annotation_to_row(
        self, ann: Annotation
    ) -> tuple[tuple[str, ...], tuple[Any, ...]]:
        ref = ann.reference
        ref_kind: str
        asset_id: str | None = None
        scene_path: str | None = None
        target_id: UUID | None = None

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
            target_id = ref.target_id
            iv = ref.interval
        else:  # pragma: no cover  — discriminated union
            raise TypeError(f"unknown reference kind: {type(ref).__name__}")

        span = self._interval_to_span(iv) if iv is not None else None

        cols = (
            "id",
            "tier",
            "ref_kind",
            "asset_id",
            "scene_path",
            "target_id",
            "span",
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
        # Re-quantize generated_at to project rate too if needed.
        gen_at = ann.provenance.generated_at_time
        if gen_at.rate != self._rate:
            try:
                gen_at = gen_at.to_rate(self._rate)
            except LossyTimeConversionError:
                # Provenance time is informational; fall back to storing as-is.
                pass

        values = (
            ann.id,
            ann.tier,
            ref_kind,
            asset_id,
            scene_path,
            target_id,
            span,
            self._psycopg.types.json.Jsonb(ann.body),
            ann.body_schema_uri,
            ann.provenance.was_generated_by,
            ann.provenance.was_attributed_to,
            self._psycopg.types.json.Jsonb(
                [str(u) for u in ann.provenance.was_derived_from]
            ),
            gen_at.value,
            gen_at.rate,
            ann.provenance.activity,
            ann.confidence,
        )
        return cols, values

    def _row_to_annotation(self, row: dict) -> Annotation:
        span = row["span"]
        if span is not None:
            interval: TimeInterval | None = self._span_to_interval(span)
        else:
            interval = None

        ref: Reference
        kind = row["ref_kind"]
        if kind == "media":
            assert interval is not None
            ref = MediaRef(asset_id=row["asset_id"], interval=interval)
        elif kind == "node":
            assert interval is not None
            ref = NodeRef(scene_path=row["scene_path"], interval=interval)
        elif kind == "annotation":
            ref = AnnotationRef(target_id=row["target_id"], interval=interval)
        else:  # pragma: no cover
            raise RuntimeError(f"unknown ref_kind: {kind!r}")

        provenance = Provenance(
            was_generated_by=row["prov_was_generated_by"],
            was_attributed_to=row["prov_was_attributed_to"],
            was_derived_from=[UUID(u) for u in row["prov_was_derived_from"]],
            generated_at_time=RationalTime(
                row["prov_generated_at_value"], row["prov_generated_at_rate"]
            ),
            activity=row["prov_activity"],
        )

        return Annotation(
            id=row["id"],
            tier=row["tier"],
            reference=ref,
            body=row["body"],
            body_schema_uri=row["body_schema_uri"],
            provenance=provenance,
            confidence=row["confidence"],
        )


def _row_to_tier(row) -> Tier:
    name, stereotype, parent, metadata = row[0], row[1], row[2], row[3]
    return Tier(
        name,
        stereotype=TierStereotype(stereotype),
        parent=parent,
        metadata=metadata if isinstance(metadata, dict) else json.loads(metadata),
    )


# ---------------------------------------------------------------------------
# convenience
# ---------------------------------------------------------------------------


def from_memory(
    memory_store, connection_string: str | dict, *, rate: int = 24000
) -> PostgresStore:
    """Replicate an in-memory store into a Postgres database."""
    pg = PostgresStore(connection_string, rate=rate)
    for tier in memory_store.tiers():
        pg.add_tier(tier)
    pg.extend(memory_store.all())
    return pg


def to_memory(pg_store: PostgresStore):
    """Snapshot a ``PostgresStore`` into a ``MemoryStore``."""
    from lacing.store.memory import MemoryStore

    mem = MemoryStore()
    for tier in pg_store.tiers():
        mem.add_tier(tier)
    mem.extend(pg_store.all())
    return mem
