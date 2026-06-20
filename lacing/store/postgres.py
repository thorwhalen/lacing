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
matching lacing's ``TimeInterval`` semantics — at a **per-(owner, project)
rate** recorded in the ``projects`` table. All inserts must be at that rate;
re-quantizing happens on insert if necessary.

GiST index on the range column gives sub-millisecond overlap queries at
million-row scale. Optional ``EXCLUDE USING GIST`` constraints are added
**per tier** for stereotypes like ``TIME_SUBDIVISION`` that forbid overlap.

Multi-tenancy (Phase 4, reelee#177)
-----------------------------------

Multiple logical stores (one per nw/reelee project) coexist in a single
Postgres database via **tenant columns on shared tables** (the decision in
``reelee/docs/storage_migration_plan.md`` §"Postgres tenancy"): every
``annotations`` and ``tiers`` row carries an ``owner_id`` and a ``project_id``,
and every query is scoped by ``(owner_id, project_id)``. A ``PostgresStore``
instance is bound to one ``(owner_id, project_id)`` at construction and behaves
exactly like a single-tenant store; two stores with different project ids over
the same database never see each other's rows.

``owner_id`` is a forward seam for the multi-tenant access layer (reelee#174):
the column is carried and scoped now, but its *enforcement* (the policy
decision point) is deferred — today every store defaults ``owner_id="default"``.

The per-tier ``EXCLUDE USING GIST`` no-overlap constraint is likewise scoped by
``(owner_id, project_id, tier)`` so one project's non-overlap rule cannot block
another project's annotations.

Connection pooling (Phase 4)
----------------------------

``nw``'s :class:`~nw.graph.ProjectGraph` opens and closes the store per
operation. That is fine for a SQLite file but pathological for a network DB, so
this module keeps a process-wide :class:`psycopg_pool.ConnectionPool` per
connection string (see :func:`get_pool`); a ``PostgresStore`` borrows a
connection from the pool for its lifetime and returns it on ``close()`` instead
of opening a fresh TCP/auth round-trip each time. When ``psycopg_pool`` is not
installed (or a caller passes ``use_pool=False``) we fall back to a dedicated
long-lived connection.

Schema versioning lives in ``meta``; mismatched versions raise on open.

Status: Phase 4. Tested via ``pytest-postgresql`` sandbox (no live server
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


SCHEMA_VERSION = 2
"""Current schema version stored in the ``meta`` table.

v2 (Phase 4, reelee#177) added tenant columns (``owner_id`` / ``project_id``)
to ``tiers`` and ``annotations``, and a per-``(owner, project)`` ``projects``
table holding the rate (was a single ``meta`` row in v1).
"""

DEFAULT_OWNER_ID = "default"
"""Owner placeholder until the multi-tenant access layer (reelee#174) lands.

The ``owner_id`` column is carried and scoped now; its enforcement is deferred.
"""

DEFAULT_PROJECT_ID = "default"
"""Project placeholder for single-project / legacy use."""


_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per logical store: the per-(owner, project) project-wide rate.
CREATE TABLE IF NOT EXISTS projects (
    owner_id    TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    rate        INTEGER NOT NULL,
    PRIMARY KEY (owner_id, project_id)
);

CREATE TABLE IF NOT EXISTS tiers (
    owner_id    TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    stereotype  TEXT NOT NULL,
    parent      TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    enforce_no_overlap BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (owner_id, project_id, name),
    FOREIGN KEY (owner_id, project_id, parent)
        REFERENCES tiers(owner_id, project_id, name) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS annotations (
    id              UUID PRIMARY KEY,
    owner_id        TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    tier            TEXT NOT NULL,
    ref_kind        TEXT NOT NULL CHECK (ref_kind IN ('media', 'node', 'annotation')),
    asset_id        TEXT,
    scene_path      TEXT,
    target_id       UUID,
    span            INT8RANGE,                 -- NULL only when ref has no interval
    -- Integer endpoints at the project rate are the lossless source of truth
    -- for time (mirrors SqliteStore). `span` is the GiST-indexed *query*
    -- column; Postgres canonicalizes a half-open point [n, n) to the empty
    -- range and loses its position, so point/zero-width intervals are
    -- reconstructed from these columns, never from `span`.
    start_value     BIGINT,
    end_value       BIGINT,
    body            JSONB NOT NULL,
    body_schema_uri TEXT NOT NULL,
    prov_was_generated_by   TEXT NOT NULL,
    prov_was_attributed_to  TEXT NOT NULL,
    prov_was_derived_from   JSONB NOT NULL DEFAULT '[]'::jsonb,
    prov_generated_at_value BIGINT NOT NULL,
    prov_generated_at_rate  INTEGER NOT NULL,
    prov_activity           TEXT NOT NULL,
    confidence              REAL,
    FOREIGN KEY (owner_id, project_id, tier)
        REFERENCES tiers(owner_id, project_id, name) ON DELETE RESTRICT
);

-- GiST spatial index over the range column for sub-ms overlap queries.
-- Tenant columns lead the btree indexes so per-project scans stay selective.
CREATE INDEX IF NOT EXISTS idx_ann_span_gist ON annotations USING GIST (span);
CREATE INDEX IF NOT EXISTS idx_ann_tenant_tier
    ON annotations (owner_id, project_id, tier);
CREATE INDEX IF NOT EXISTS idx_ann_tenant_asset
    ON annotations (owner_id, project_id, asset_id);
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
    """Build a constraint-name-safe fragment from a string.

    Used to assemble per-tenant per-tier EXCLUDE-constraint names. Lowercased,
    non-identifier characters collapsed to ``_``, length-bounded so the full
    constraint name stays within Postgres's 63-byte identifier limit.
    """
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch.lower())
        else:
            out.append("_")
    return "".join(out)[:40] or "x"


# ---------------------------------------------------------------------------
# connection pooling
# ---------------------------------------------------------------------------

# Process-wide pool registry, keyed by the connection string. ``nw`` reopens a
# store per operation, so without pooling every op pays a fresh TCP + auth
# round-trip. The pool amortizes that. Keyed by conninfo so independent stores
# over the same DB share one pool.
_POOLS: dict[str, Any] = {}


def get_pool(connection_string: str, **pool_kwargs):
    """Return a process-wide :class:`psycopg_pool.ConnectionPool` for a conninfo.

    One pool per distinct ``connection_string`` (the keying happens here, not at
    the call-site), created lazily on first request. Raises :class:`ImportError`
    if ``psycopg_pool`` is not installed — callers that want a graceful fallback
    catch it (see :class:`PostgresStore`).

    Args:
        connection_string: psycopg conninfo URL (the registry key).
        **pool_kwargs: forwarded to :class:`~psycopg_pool.ConnectionPool` on
            first creation (e.g. ``min_size``, ``max_size``); ignored on reuse.

    Returns:
        The shared pool for this conninfo.
    """
    pool = _POOLS.get(connection_string)
    if pool is None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover  — optional dep
            raise ImportError(
                "Connection pooling needs psycopg_pool. Install with: "
                "pip install 'lacing[postgres]'  (or: pip install psycopg_pool). "
                "Pass use_pool=False to use a single long-lived connection instead."
            ) from exc
        kwargs = {"min_size": 1, "max_size": 8, "open": True, **pool_kwargs}
        pool = ConnectionPool(connection_string, **kwargs)
        _POOLS[connection_string] = pool
    return pool


def close_all_pools() -> None:
    """Close every registered connection pool (test teardown / shutdown)."""
    for pool in list(_POOLS.values()):
        try:
            pool.close()
        except Exception:  # pragma: no cover  — best-effort
            pass
    _POOLS.clear()


# ---------------------------------------------------------------------------
# PostgresStore
# ---------------------------------------------------------------------------


class PostgresStore:
    """PostgreSQL-backed ``IntervalAnnotationStore``, scoped to one tenant.

    A store instance is bound to one ``(owner_id, project_id)`` pair; multiple
    instances over the same database (different project ids) coexist without
    seeing each other's annotations or tiers (see the module docstring on
    multi-tenancy). The mapping/Allen/tier surface is unchanged — the tenant
    scoping is transparent.

    Args:
        connection_string: A psycopg-compatible conninfo URL, or a kwargs dict
            (``host``/``port``/``user``/``password``/``dbname``).
        rate: Project-wide rate for *this* ``(owner, project)``. Set on first
            init for the pair; re-opening the same pair with a different rate
            raises :class:`PgSchemaMismatchError`. Different projects in the
            same DB may have different rates.
        owner_id: Tenant owner. Defaults to :data:`DEFAULT_OWNER_ID` — the
            forward seam for the access layer (reelee#174); enforcement deferred.
        project_id: Logical project key. Defaults to :data:`DEFAULT_PROJECT_ID`.
            ``nw`` passes the project's ``project_asset_id`` here.
        autocommit: If True (default), statements run in their own transaction.
        use_pool: When True (default) and the connection is given as a string,
            borrow a connection from a process-wide pool keyed by the conninfo
            (amortizes per-op connect cost; see :func:`get_pool`). Falls back to
            a dedicated connection when ``psycopg_pool`` is unavailable, when the
            connection is given as a dict, or when ``use_pool=False``.
    """

    def __init__(
        self,
        connection_string: str | dict,
        *,
        rate: int = 24000,
        owner_id: str = DEFAULT_OWNER_ID,
        project_id: str = DEFAULT_PROJECT_ID,
        autocommit: bool = True,
        use_pool: bool = True,
    ) -> None:
        psycopg, _sql, _range = _require_psycopg()
        self._psycopg = psycopg
        self._sql = _sql
        self._Range = _range
        self._owner_id = owner_id
        self._project_id = project_id

        # Normalize to a conninfo string so we can pool. A dict still works but
        # can't be a pool key, so it always takes the dedicated-connection path.
        if isinstance(connection_string, dict):
            conninfo = psycopg.conninfo.make_conninfo(**connection_string)
            poolable = False
        else:
            conninfo = connection_string
            poolable = True

        self._pool = None
        self._pooled = False
        if use_pool and poolable:
            try:
                self._pool = get_pool(conninfo)
                self._conn = self._pool.getconn()
                self._conn.autocommit = autocommit
                self._pooled = True
            except ImportError:
                # psycopg_pool not installed — fall back transparently.
                self._conn = psycopg.connect(conninfo, autocommit=autocommit)
        else:
            self._conn = psycopg.connect(conninfo, autocommit=autocommit)

        self._init_schema(rate)

    # --- schema --------------------------------------------------------

    def _init_schema(self, rate: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_DDL)
            # Global schema version (shared across all tenants in the DB).
            row = cur.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO meta (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO NOTHING",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
            else:
                got_version = int(row[0])
                if got_version != SCHEMA_VERSION:
                    raise PgSchemaMismatchError(
                        f"database has schema_version={got_version}, "
                        f"this build expects {SCHEMA_VERSION}."
                    )

            # Per-(owner, project) rate.
            row = cur.execute(
                "SELECT rate FROM projects WHERE owner_id = %s AND project_id = %s",
                (self._owner_id, self._project_id),
            ).fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO projects (owner_id, project_id, rate) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (owner_id, project_id) DO NOTHING",
                    (self._owner_id, self._project_id, rate),
                )
                self._rate = rate
            else:
                stored_rate = int(row[0])
                if rate != stored_rate:
                    raise PgSchemaMismatchError(
                        f"project ({self._owner_id!r}, {self._project_id!r}) has "
                        f"rate={stored_rate}, opened with rate={rate}. Re-quantize "
                        f"the data or open with the original rate."
                    )
                self._rate = stored_rate

    @property
    def rate(self) -> int:
        return self._rate

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def project_id(self) -> str:
        return self._project_id

    @property
    def schema_version(self) -> int:
        return SCHEMA_VERSION

    def close(self) -> None:
        if self._pooled and self._pool is not None:
            # Return the connection to the pool rather than closing the socket.
            try:
                self._pool.putconn(self._conn)
            except Exception:  # pragma: no cover  — best-effort
                self._conn.close()
        else:
            self._conn.close()

    def __enter__(self) -> "PostgresStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- meta ----------------------------------------------------------

    def _meta_key(self, key: str) -> str:
        """Namespace a user meta key by tenant so projects don't collide.

        ``schema_version`` is the one global key (set in :meth:`_init_schema`);
        all caller-set keys are stored under ``"<owner>/<project>:<key>"``.
        """
        return f"{self._owner_id}/{self._project_id}:{key}"

    def get_meta(self, key: str) -> str | None:
        with self._conn.cursor() as cur:
            row = cur.execute(
                "SELECT value FROM meta WHERE key = %s", (self._meta_key(key),)
            ).fetchone()
            if row is not None:
                return row[0]
            # schema_version is stored unscoped (DB-global); allow reading it.
            if key == "schema_version":
                gv = cur.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()
                return None if gv is None else gv[0]
            # rate moved to the projects table in v2; expose it via get_meta too.
            if key == "rate":
                return str(self._rate)
            return None

    def set_meta(self, key: str, value: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meta (key, value) VALUES (%s, %s) "
                "ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                (self._meta_key(key), value),
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
        sql = self._sql

        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tiers "
                "  (owner_id, project_id, name, stereotype, parent, metadata, "
                "   enforce_no_overlap) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s) "
                "ON CONFLICT(owner_id, project_id, name) DO UPDATE SET "
                "  stereotype = EXCLUDED.stereotype, "
                "  parent     = EXCLUDED.parent, "
                "  metadata   = EXCLUDED.metadata, "
                "  enforce_no_overlap = EXCLUDED.enforce_no_overlap",
                (
                    self._owner_id,
                    self._project_id,
                    tier.name,
                    tier.stereotype.value,
                    tier.parent,
                    json.dumps(tier.metadata),
                    enforce_no_overlap,
                ),
            )

            # Constraint name is unique per (owner, project, tier) so one
            # project's no-overlap rule never blocks another's annotations.
            constraint_name = self._exclusion_constraint_name(tier.name)
            existing = cur.execute(
                "SELECT 1 FROM pg_constraint WHERE conname = %s",
                (constraint_name,),
            ).fetchone()

            if enforce_no_overlap and not existing:
                # Partial EXCLUDE constraint scoped to this tenant + tier.
                stmt = sql.SQL(
                    "ALTER TABLE annotations "
                    "ADD CONSTRAINT {name} EXCLUDE USING GIST (span WITH &&) "
                    "WHERE (owner_id = {owner} AND project_id = {project} "
                    "       AND tier = {tier_lit})"
                ).format(
                    name=sql.Identifier(constraint_name),
                    owner=sql.Literal(self._owner_id),
                    project=sql.Literal(self._project_id),
                    tier_lit=sql.Literal(tier.name),
                )
                cur.execute(stmt)
            elif not enforce_no_overlap and existing:
                stmt = sql.SQL("ALTER TABLE annotations DROP CONSTRAINT {name}").format(
                    name=sql.Identifier(constraint_name),
                )
                cur.execute(stmt)

    def _exclusion_constraint_name(self, tier_name: str) -> str:
        """Per-(owner, project, tier) constraint name, within PG's 63-byte cap."""
        return (
            f"no_ovl_{_safe_tier_id(self._owner_id)}_"
            f"{_safe_tier_id(self._project_id)}_{_safe_tier_id(tier_name)}"
        )[:63]

    def get_tier(self, name: str) -> Tier | None:
        with self._conn.cursor() as cur:
            row = cur.execute(
                "SELECT name, stereotype, parent, metadata FROM tiers "
                "WHERE owner_id = %s AND project_id = %s AND name = %s",
                (self._owner_id, self._project_id, name),
            ).fetchone()
            return None if row is None else _row_to_tier(row)

    def tiers(self) -> Iterator[Tier]:
        with self._conn.cursor() as cur:
            rows = cur.execute(
                "SELECT name, stereotype, parent, metadata FROM tiers "
                "WHERE owner_id = %s AND project_id = %s ORDER BY name",
                (self._owner_id, self._project_id),
            ).fetchall()
        return iter([_row_to_tier(r) for r in rows])

    def is_no_overlap_enforced(self, tier_name: str) -> bool:
        with self._conn.cursor() as cur:
            row = cur.execute(
                "SELECT enforce_no_overlap FROM tiers "
                "WHERE owner_id = %s AND project_id = %s AND name = %s",
                (self._owner_id, self._project_id, tier_name),
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

    def _scope(self) -> tuple[str, tuple[str, str]]:
        """SQL ``AND``-able tenant predicate + its params.

        Every annotation query carries this so a store only ever sees rows for
        its own ``(owner_id, project_id)``.
        """
        return "owner_id = %s AND project_id = %s", (self._owner_id, self._project_id)

    def _do_add(self, annotation: Annotation) -> None:
        cols, values = self._annotation_to_row(annotation)
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO annotations ({', '.join(cols)}) "
                f"VALUES ({', '.join('%s' for _ in cols)})",
                values,
            )

    def remove(self, annotation_id: UUID) -> Annotation | None:
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM annotations WHERE id = %s AND {scope}",
                (annotation_id, *params),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
            ann = self._row_to_annotation(dict(zip(cols, row)))
            cur.execute(
                f"DELETE FROM annotations WHERE id = %s AND {scope}",
                (annotation_id, *params),
            )
        return ann

    def all(self) -> Iterator[Annotation]:
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            rows = cur.execute(
                f"SELECT * FROM annotations WHERE {scope}", params
            ).fetchall()
            cols = [d.name for d in cur.description]
        for row in rows:
            yield self._row_to_annotation(dict(zip(cols, row)))

    def __len__(self) -> int:
        # Number of distinct interval keys; matches MutableMapping facade.
        # Keyed on the integer endpoints (point intervals share an empty span,
        # so DISTINCT span would wrongly collapse them).
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            row = cur.execute(
                f"SELECT COUNT(*) FROM ("
                f"  SELECT DISTINCT start_value, end_value FROM annotations "
                f"  WHERE {scope} AND ref_kind = 'media' AND start_value IS NOT NULL"
                f") AS d",
                params,
            ).fetchone()
            return int(row[0])

    def __iter__(self) -> Iterator[TimeInterval]:
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            rows = cur.execute(
                f"SELECT DISTINCT start_value, end_value FROM annotations "
                f"WHERE {scope} AND ref_kind = 'media' AND start_value IS NOT NULL "
                f"ORDER BY start_value, end_value",
                params,
            ).fetchall()
        for start_value, end_value in rows:
            yield TimeInterval(
                RationalTime(start_value, self._rate),
                RationalTime(end_value, self._rate),
            )

    def _key_endpoints(self, key: TimeInterval) -> tuple[int, int]:
        """Integer endpoints at the project rate for an exact-key lookup.

        Used by the mapping operations, which key on the exact interval — the
        integer pair, not ``span`` (a half-open point has an empty span).
        """
        return self._normalize_value(key.start), self._normalize_value(key.end)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, TimeInterval):
            return False
        sv, ev = self._key_endpoints(key)
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            row = cur.execute(
                f"SELECT 1 FROM annotations WHERE {scope} "
                f"AND start_value = %s AND end_value = %s LIMIT 1",
                (*params, sv, ev),
            ).fetchone()
        return row is not None

    def __getitem__(self, key: TimeInterval) -> list[Annotation]:
        sv, ev = self._key_endpoints(key)
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            rows = cur.execute(
                f"SELECT * FROM annotations WHERE {scope} "
                f"AND start_value = %s AND end_value = %s",
                (*params, sv, ev),
            ).fetchall()
            cols = [d.name for d in cur.description] if cur.description else []
        if not rows:
            raise KeyError(key)
        return [self._row_to_annotation(dict(zip(cols, r))) for r in rows]

    def __setitem__(self, key: TimeInterval, value: list[Annotation]) -> None:
        sv, ev = self._key_endpoints(key)
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM annotations WHERE {scope} "
                f"AND start_value = %s AND end_value = %s",
                (*params, sv, ev),
            )
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
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            sql_text = f"SELECT * FROM annotations WHERE {scope} AND span {op} %s"
            rows = cur.execute(sql_text, (*params, span)).fetchall()
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
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            rows = cur.execute(
                f"SELECT * FROM annotations WHERE {scope} "
                f"AND ((span && %s) OR (span -|- %s))",
                (*params, span, span),
            ).fetchall()
            cols = [d.name for d in cur.description] if cur.description else []
        for row in rows:
            yield self._row_to_annotation(dict(zip(cols, row)))

    # --- tier filters ------------------------------------------------

    def by_tier(self, tier_name: str) -> Iterator[Annotation]:
        scope, params = self._scope()
        with self._conn.cursor() as cur:
            rows = cur.execute(
                f"SELECT * FROM annotations WHERE {scope} AND tier = %s",
                (*params, tier_name),
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
        scope, params = self._scope()
        try:
            with self._conn.cursor() as cur:
                n_anns = cur.execute(
                    f"SELECT COUNT(*) FROM annotations WHERE {scope}", params
                ).fetchone()[0]
                n_tiers = cur.execute(
                    f"SELECT COUNT(*) FROM tiers WHERE {scope}", params
                ).fetchone()[0]
        except Exception:  # pragma: no cover  — closed connection
            return "PostgresStore(<closed>)"
        return (
            f"PostgresStore(owner={self._owner_id!r}, project={self._project_id!r}, "
            f"{n_anns} annotations, {n_tiers} tiers, rate={self._rate})"
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
        if iv is not None:
            start_value = self._normalize_value(iv.start)
            end_value = self._normalize_value(iv.end)
        else:
            start_value = None
            end_value = None

        cols = (
            "id",
            "owner_id",
            "project_id",
            "tier",
            "ref_kind",
            "asset_id",
            "scene_path",
            "target_id",
            "span",
            "start_value",
            "end_value",
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
            self._owner_id,
            self._project_id,
            ann.tier,
            ref_kind,
            asset_id,
            scene_path,
            target_id,
            span,
            start_value,
            end_value,
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
        # Reconstruct the interval from the integer endpoints (lossless source
        # of truth), NOT from `span`: Postgres canonicalizes a half-open point
        # [n, n) to the empty range and reports lower/upper as NULL on readback.
        if row.get("start_value") is not None:
            interval: TimeInterval | None = TimeInterval(
                RationalTime(row["start_value"], self._rate),
                RationalTime(row["end_value"], self._rate),
            )
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
    memory_store,
    connection_string: str | dict,
    *,
    rate: int = 24000,
    owner_id: str = DEFAULT_OWNER_ID,
    project_id: str = DEFAULT_PROJECT_ID,
) -> PostgresStore:
    """Replicate an in-memory store into a Postgres database (one tenant)."""
    pg = PostgresStore(
        connection_string, rate=rate, owner_id=owner_id, project_id=project_id
    )
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
