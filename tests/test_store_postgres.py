"""Tests for ``PostgresStore``.

Uses ``pytest-postgresql`` to spawn a sandbox Postgres for the test
session. Skipped if Postgres binary or pytest-postgresql isn't installed.

The fixture cycle:

- ``postgresql_proc`` (session-scoped) starts a single Postgres process.
- ``postgresql`` (function-scoped) creates a fresh database per test.
- ``postgres_store`` (function-scoped) wraps the test database in a
  ``PostgresStore`` and ensures it's closed at teardown.
"""

from __future__ import annotations

import shutil
from uuid import uuid4

import pytest

# Skip the entire module if either dep is missing.
pytest.importorskip("pytest_postgresql")
pytest.importorskip("psycopg")
if not any(shutil.which(name) for name in ("pg_ctl", "postgres")):
    pytest.skip("Postgres binary not on PATH", allow_module_level=True)


from lacing.allen import AllenRelation  # noqa: E402
from lacing.model import Annotation, AnnotationRef, MediaRef, Provenance  # noqa: E402
from lacing.store import (  # noqa: E402
    MemoryStore,
    PgSchemaMismatchError,
    PostgresStore,
    RateMismatchError,
    TierOverlapError,
)
from lacing.store.postgres import from_memory  # noqa: E402
from lacing.tier import Tier, TierStereotype  # noqa: E402
from lacing.time import RationalTime, TimeInterval  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _ti(s: int, e: int) -> TimeInterval:
    return TimeInterval(RationalTime(s), RationalTime(e))


def _ann(
    interval: TimeInterval,
    *,
    tier: str = "words",
    text: str = "x",
    confidence: float | None = None,
) -> Annotation:
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(asset_id="blake3:test", interval=interval),
        body={"text": text},
        body_schema_uri="annot://schema/word/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime(0),
        ),
        confidence=confidence,
    )


@pytest.fixture
def postgres_store(postgresql):
    """Wrap the per-test ``postgresql`` connection in a ``PostgresStore``.

    ``postgresql`` is a fixture from ``pytest-postgresql`` that yields a
    psycopg connection to a fresh database. We pull its connection params
    and hand them to ``PostgresStore``.
    """
    info = postgresql.info
    conn_kwargs = {
        "host": info.host,
        "port": info.port,
        "user": info.user,
        "password": info.password or "",
        "dbname": info.dbname,
    }
    store = PostgresStore(conn_kwargs, rate=24000)
    # Pre-load common tiers to keep tests focused on store behavior, not setup.
    for name in ("words", "phonemes", "tones", "speakers", "comments", "other"):
        store.add_tier(Tier(name))
    yield store
    store.close()


# ---------------------------------------------------------------------------
# schema + meta
# ---------------------------------------------------------------------------


class TestSchema:
    def test_initial_schema_version(self, postgres_store):
        assert postgres_store.schema_version == 2
        assert postgres_store.get_meta("schema_version") == "2"

    def test_rate_persisted(self, postgres_store):
        assert postgres_store.rate == 24000
        assert postgres_store.get_meta("rate") == "24000"

    def test_set_meta(self, postgres_store):
        postgres_store.set_meta("project", "demo")
        assert postgres_store.get_meta("project") == "demo"

    def test_rate_mismatch_on_reopen(self, postgresql):
        info = postgresql.info
        conn_kwargs = {
            "host": info.host,
            "port": info.port,
            "user": info.user,
            "password": info.password or "",
            "dbname": info.dbname,
        }
        s = PostgresStore(conn_kwargs, rate=24000)
        s.close()
        with pytest.raises(PgSchemaMismatchError):
            PostgresStore(conn_kwargs, rate=48000)


# ---------------------------------------------------------------------------
# mapping interface
# ---------------------------------------------------------------------------


class TestMapping:
    def test_empty(self, postgres_store):
        assert len(postgres_store) == 0
        assert list(postgres_store) == []

    def test_add_and_count(self, postgres_store):
        postgres_store.add(_ann(_ti(0, 10)))
        assert len(postgres_store) == 1
        assert _ti(0, 10) in postgres_store

    def test_two_at_same_interval(self, postgres_store):
        iv = _ti(0, 10)
        postgres_store.add(_ann(iv, tier="words"))
        postgres_store.add(_ann(iv, tier="phonemes"))
        assert len(postgres_store) == 1  # one key
        assert len(postgres_store[iv]) == 2

    def test_setitem_replaces(self, postgres_store):
        iv = _ti(0, 10)
        postgres_store.add(_ann(iv))
        postgres_store[iv] = [_ann(iv, tier="phonemes")]
        assert len(postgres_store[iv]) == 1
        assert postgres_store[iv][0].tier == "phonemes"

    def test_setitem_empty_drops_key(self, postgres_store):
        iv = _ti(0, 10)
        postgres_store.add(_ann(iv))
        postgres_store[iv] = []
        assert len(postgres_store) == 0

    def test_delitem(self, postgres_store):
        iv = _ti(0, 10)
        postgres_store.add(_ann(iv))
        del postgres_store[iv]
        assert len(postgres_store) == 0

    def test_delitem_missing_raises(self, postgres_store):
        with pytest.raises(KeyError):
            del postgres_store[_ti(0, 1)]

    def test_getitem_missing_raises(self, postgres_store):
        with pytest.raises(KeyError):
            postgres_store[_ti(0, 1)]

    def test_remove_by_id(self, postgres_store):
        a = _ann(_ti(0, 10))
        postgres_store.add(a)
        removed = postgres_store.remove(a.id)
        assert removed is not None and removed.id == a.id
        assert len(postgres_store) == 0

    def test_remove_missing_returns_none(self, postgres_store):
        assert postgres_store.remove(uuid4()) is None


# ---------------------------------------------------------------------------
# Allen relations
# ---------------------------------------------------------------------------


class TestAllen:
    def _populate(self, store):
        store.add(_ann(_ti(0, 10)))    # before query [30, 40)
        store.add(_ann(_ti(15, 25)))   # overlaps query
        store.add(_ann(_ti(30, 40)))   # equals query
        store.add(_ann(_ti(33, 37)))   # during query
        store.add(_ann(_ti(50, 60)))   # after query

    def test_intersects(self, postgres_store):
        self._populate(postgres_store)
        results = list(postgres_store.intersects(_ti(30, 40)))
        assert len(results) == 2

    def test_during(self, postgres_store):
        self._populate(postgres_store)
        results = list(postgres_store.during(_ti(30, 40)))
        assert len(results) == 1
        assert results[0].interval == _ti(33, 37)

    def test_contains(self, postgres_store):
        self._populate(postgres_store)
        results = list(postgres_store.contains(_ti(33, 37)))
        assert len(results) == 1

    def test_equals(self, postgres_store):
        self._populate(postgres_store)
        results = list(postgres_store.equals(_ti(30, 40)))
        assert len(results) == 1

    def test_overlaps_strict(self, postgres_store):
        self._populate(postgres_store)
        results = list(postgres_store.overlaps(_ti(20, 35)))
        assert any(r.interval == _ti(15, 25) for r in results)

    def test_meets(self, postgres_store):
        postgres_store.add(_ann(_ti(0, 10)))
        results = list(postgres_store.meets(_ti(10, 20)))
        assert len(results) == 1

    def test_intersects_does_not_match_meets(self, postgres_store):
        postgres_store.add(_ann(_ti(0, 10)))
        # `&&` on int8range with default '[)' bounds doesn't include
        # boundary-touching ranges — same semantics as lacing's half-open.
        assert list(postgres_store.intersects(_ti(10, 20))) == []

    def test_relate_multi(self, postgres_store):
        self._populate(postgres_store)
        results = list(
            postgres_store.relate(
                _ti(30, 40), {AllenRelation.DURING, AllenRelation.EQUALS}
            )
        )
        assert len(results) == 2


# ---------------------------------------------------------------------------
# rate handling
# ---------------------------------------------------------------------------


class TestRate:
    def test_normalizes_to_project_rate(self, postgres_store):
        # Insert at rate=48000; project rate is 24000.
        # value=48000 at rate 48000 == 24000 at rate 24000 == 1 second.
        a = _ann(
            TimeInterval(
                RationalTime(0, 48000),
                RationalTime(48000, 48000),
            ),
            tier="words",
        )
        postgres_store.add(a)
        loaded = next(postgres_store.all())
        # span gets stored at project rate
        assert loaded.interval.start.rate == 24000
        assert loaded.interval.end.rate == 24000
        assert loaded.interval.start.value == 0
        assert loaded.interval.end.value == 24000

    def test_rejects_lossy_rate(self, postgres_store):
        # rate=7 cannot be re-quantized to 24000 exactly for value=1.
        a = _ann(
            TimeInterval(
                RationalTime(0, 7),
                RationalTime(1, 7),
            ),
            tier="words",
        )
        with pytest.raises(RateMismatchError):
            postgres_store.add(a)


# ---------------------------------------------------------------------------
# tier registry
# ---------------------------------------------------------------------------


class TestTiers:
    def test_get_added(self, postgres_store):
        postgres_store.add_tier(Tier("custom"))
        t = postgres_store.get_tier("custom")
        assert t is not None
        assert t.name == "custom"

    def test_get_missing(self, postgres_store):
        assert postgres_store.get_tier("nope") is None

    def test_with_stereotype_and_parent(self, postgres_store):
        postgres_store.add_tier(
            Tier(
                "phon-sub",
                stereotype=TierStereotype.TIME_SUBDIVISION,
                parent="words",
            )
        )
        t = postgres_store.get_tier("phon-sub")
        assert t.stereotype == TierStereotype.TIME_SUBDIVISION
        assert t.parent == "words"

    def test_metadata_round_trip(self, postgres_store):
        postgres_store.add_tier(Tier("x", metadata={"language": "fr", "bpm": 120}))
        t = postgres_store.get_tier("x")
        assert t.metadata == {"language": "fr", "bpm": 120}

    def test_iter(self, postgres_store):
        names = {t.name for t in postgres_store.tiers()}
        # The fixture pre-loaded six.
        assert {"words", "phonemes", "tones", "speakers", "comments", "other"} <= names


# ---------------------------------------------------------------------------
# tier filters
# ---------------------------------------------------------------------------


class TestTierFilter:
    def test_by_tier(self, postgres_store):
        postgres_store.add(_ann(_ti(0, 10), tier="words"))
        postgres_store.add(_ann(_ti(0, 10), tier="phonemes"))
        postgres_store.add(_ann(_ti(20, 30), tier="words"))
        assert len(list(postgres_store.by_tier("words"))) == 2

    def test_at_tier(self, postgres_store):
        postgres_store.add(_ann(_ti(0, 10), tier="words"))
        postgres_store.add(_ann(_ti(0, 10), tier="phonemes"))
        postgres_store.add(_ann(_ti(20, 30), tier="words"))
        results = list(postgres_store.at_tier("words", _ti(0, 10)))
        assert len(results) == 1


# ---------------------------------------------------------------------------
# foreign key + check constraints
# ---------------------------------------------------------------------------


class TestConstraints:
    def test_unknown_tier_rejected(self, postgres_store):
        # add() raises ForeignKeyViolation; we let it propagate.
        with pytest.raises(Exception):
            postgres_store.add(_ann(_ti(0, 10), tier="bogus_tier"))


# ---------------------------------------------------------------------------
# the killer feature — per-tier EXCLUDE constraint
# ---------------------------------------------------------------------------


class TestExcludeConstraint:
    def test_no_overlap_enforced_when_enabled(self, postgres_store):
        # Re-add 'words' with the constraint on.
        postgres_store.add_tier(Tier("words"), enforce_no_overlap=True)
        assert postgres_store.is_no_overlap_enforced("words")

        postgres_store.add(_ann(_ti(0, 100), tier="words"))
        # Overlapping insert in the same tier must fail.
        with pytest.raises(TierOverlapError):
            postgres_store.add(_ann(_ti(50, 150), tier="words"))

    def test_no_overlap_does_not_apply_across_tiers(self, postgres_store):
        postgres_store.add_tier(Tier("words"), enforce_no_overlap=True)
        postgres_store.add_tier(Tier("phonemes"), enforce_no_overlap=True)
        postgres_store.add(_ann(_ti(0, 100), tier="words"))
        # Same span, different tier — should be fine.
        postgres_store.add(_ann(_ti(0, 100), tier="phonemes"))
        assert len(list(postgres_store.all())) == 2

    def test_meeting_intervals_allowed(self, postgres_store):
        # `&&` on '[)' ranges does NOT match touching boundaries, so meets
        # is allowed even with EXCLUDE on.
        postgres_store.add_tier(Tier("words"), enforce_no_overlap=True)
        postgres_store.add(_ann(_ti(0, 100), tier="words"))
        postgres_store.add(_ann(_ti(100, 200), tier="words"))
        assert len(list(postgres_store.all())) == 2

    def test_can_disable_after_enabling(self, postgres_store):
        postgres_store.add_tier(Tier("words"), enforce_no_overlap=True)
        postgres_store.add(_ann(_ti(0, 100), tier="words"))
        # Disabling — now overlap should be permitted.
        postgres_store.add_tier(Tier("words"), enforce_no_overlap=False)
        assert not postgres_store.is_no_overlap_enforced("words")
        postgres_store.add(_ann(_ti(50, 150), tier="words"))
        assert len(list(postgres_store.all())) == 2


# ---------------------------------------------------------------------------
# bulk + transactions
# ---------------------------------------------------------------------------


class TestBulk:
    def test_extend_inside_transaction(self, postgres_store):
        postgres_store.extend([_ann(_ti(0, 10)), _ann(_ti(20, 30))])
        assert len(postgres_store) == 2

    def test_extend_rolls_back_on_failure(self, postgres_store):
        postgres_store.add_tier(Tier("words"), enforce_no_overlap=True)
        good = [_ann(_ti(0, 10), tier="words"), _ann(_ti(20, 30), tier="words")]
        bad = [_ann(_ti(25, 35), tier="words")]  # overlaps the second 'good'
        with pytest.raises(Exception):
            postgres_store.extend(good + bad)
        # Whole batch rolled back.
        assert len(postgres_store) == 0


# ---------------------------------------------------------------------------
# annotation references
# ---------------------------------------------------------------------------


class TestReferences:
    def test_annotation_ref_with_interval(self, postgres_store):
        target = uuid4()
        a = Annotation(
            id=uuid4(),
            tier="comments",
            reference=AnnotationRef(target_id=target, interval=_ti(0, 10)),
            body={"text": "comment"},
            body_schema_uri="annot://schema/comment/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="test",
                generated_at_time=RationalTime(0),
            ),
        )
        postgres_store.add(a)
        rt = next(postgres_store.all())
        assert isinstance(rt.reference, AnnotationRef)
        assert rt.reference.target_id == target
        assert rt.reference.interval == _ti(0, 10)

    def test_annotation_ref_without_interval_is_timeless(self, postgres_store):
        a = Annotation(
            id=uuid4(),
            tier="comments",
            reference=AnnotationRef(target_id=uuid4()),
            body={"text": "doc-level"},
            body_schema_uri="annot://schema/comment/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="test",
                generated_at_time=RationalTime(0),
            ),
        )
        postgres_store.add(a)
        # Visible via .all(), not via interval queries / __len__.
        assert len(list(postgres_store.all())) == 1
        assert len(postgres_store) == 0
        assert list(postgres_store.intersects(_ti(0, 1000))) == []

    def test_confidence_round_trip(self, postgres_store):
        a = _ann(_ti(0, 10))
        a = a.model_copy(update={"confidence": 0.7})
        postgres_store.add(a)
        loaded = next(postgres_store.all())
        assert loaded.confidence == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# from_memory
# ---------------------------------------------------------------------------


class TestFromMemory:
    def test_replicate(self, postgresql):
        info = postgresql.info
        conn_kwargs = {
            "host": info.host,
            "port": info.port,
            "user": info.user,
            "password": info.password or "",
            "dbname": info.dbname,
        }
        mem = MemoryStore()
        mem.add_tier(Tier("words"))
        mem.add_tier(
            Tier("phonemes", stereotype=TierStereotype.TIME_SUBDIVISION, parent="words")
        )
        mem.add(_ann(_ti(0, 10), tier="words"))
        mem.add(_ann(_ti(0, 5), tier="phonemes"))
        mem.add(_ann(_ti(5, 10), tier="phonemes"))

        pg = from_memory(mem, conn_kwargs, rate=24000)
        try:
            assert len(list(pg.all())) == 3
            phon = pg.get_tier("phonemes")
            assert phon.stereotype == TierStereotype.TIME_SUBDIVISION
        finally:
            pg.close()


# ---------------------------------------------------------------------------
# multi-tenancy — tenant columns on shared tables (Phase 4, reelee#177)
# ---------------------------------------------------------------------------


def _conn_kwargs(postgresql) -> dict:
    info = postgresql.info
    return {
        "host": info.host,
        "port": info.port,
        "user": info.user,
        "password": info.password or "",
        "dbname": info.dbname,
    }


class TestMultiTenant:
    def test_two_projects_in_one_db_are_isolated(self, postgresql):
        """The headline guarantee: distinct project_ids share a DB but never
        see each other's annotations or tiers."""
        ck = _conn_kwargs(postgresql)
        a = PostgresStore(ck, rate=24000, project_id="proj-a")
        b = PostgresStore(ck, rate=24000, project_id="proj-b")
        try:
            a.add_tier(Tier("words"))
            b.add_tier(Tier("words"))
            a.add(_ann(_ti(0, 10), tier="words", text="from-a"))
            b.add(_ann(_ti(0, 10), tier="words", text="from-b"))
            b.add(_ann(_ti(20, 30), tier="words", text="from-b-2"))

            a_anns = list(a.all())
            b_anns = list(b.all())
            assert len(a_anns) == 1
            assert len(b_anns) == 2
            assert a_anns[0].body["text"] == "from-a"
            assert {x.body["text"] for x in b_anns} == {"from-b", "from-b-2"}

            # Interval queries are scoped too.
            assert len(list(a.intersects(_ti(0, 40)))) == 1
            assert len(list(b.intersects(_ti(0, 40)))) == 2

            # __len__ (distinct interval keys) is per-tenant.
            assert len(a) == 1
            assert len(b) == 2
        finally:
            a.close()
            b.close()

    def test_default_owner_and_project(self, postgresql):
        from lacing.store.postgres import DEFAULT_OWNER_ID, DEFAULT_PROJECT_ID

        s = PostgresStore(_conn_kwargs(postgresql), rate=24000)
        try:
            assert s.owner_id == DEFAULT_OWNER_ID
            assert s.project_id == DEFAULT_PROJECT_ID
        finally:
            s.close()

    def test_per_project_rate(self, postgresql):
        """Each (owner, project) carries its own rate; another project in the
        same DB can use a different one."""
        ck = _conn_kwargs(postgresql)
        a = PostgresStore(ck, rate=24000, project_id="proj-a")
        b = PostgresStore(ck, rate=48000, project_id="proj-b")
        try:
            assert a.rate == 24000
            assert b.rate == 48000
            assert a.get_meta("rate") == "24000"
            assert b.get_meta("rate") == "48000"
        finally:
            a.close()
            b.close()

    def test_per_project_rate_mismatch_raises(self, postgresql):
        ck = _conn_kwargs(postgresql)
        s = PostgresStore(ck, rate=24000, project_id="proj-a")
        s.close()
        with pytest.raises(PgSchemaMismatchError):
            PostgresStore(ck, rate=48000, project_id="proj-a")

    def test_owner_scoping(self, postgresql):
        """owner_id scopes alongside project_id (forward seam for #174)."""
        ck = _conn_kwargs(postgresql)
        a = PostgresStore(ck, rate=24000, owner_id="alice", project_id="p")
        b = PostgresStore(ck, rate=24000, owner_id="bob", project_id="p")
        try:
            a.add_tier(Tier("words"))
            b.add_tier(Tier("words"))
            a.add(_ann(_ti(0, 10), tier="words"))
            assert len(list(a.all())) == 1
            assert len(list(b.all())) == 0  # same project_id, different owner
        finally:
            a.close()
            b.close()

    def test_meta_is_tenant_scoped(self, postgresql):
        ck = _conn_kwargs(postgresql)
        a = PostgresStore(ck, rate=24000, project_id="proj-a")
        b = PostgresStore(ck, rate=24000, project_id="proj-b")
        try:
            a.set_meta("title", "Project A")
            b.set_meta("title", "Project B")
            assert a.get_meta("title") == "Project A"
            assert b.get_meta("title") == "Project B"
        finally:
            a.close()
            b.close()

    def test_no_overlap_constraint_is_per_project(self, postgresql):
        """One project's per-tier EXCLUDE rule must not block another's
        identical-span insert. proj-a enforces no-overlap on 'words'; proj-b
        does not — so the span that proj-a rejects is accepted by proj-b."""
        ck = _conn_kwargs(postgresql)
        a = PostgresStore(ck, rate=24000, project_id="proj-a")
        b = PostgresStore(ck, rate=24000, project_id="proj-b")
        try:
            a.add_tier(Tier("words"), enforce_no_overlap=True)
            b.add_tier(Tier("words"))  # no constraint in proj-b
            a.add(_ann(_ti(0, 100), tier="words"))
            # Overlap in proj-a is forbidden by its per-tenant EXCLUDE...
            with pytest.raises(TierOverlapError):
                a.add(_ann(_ti(50, 150), tier="words"))
            # ...but proj-b can freely add overlapping spans of the same tier.
            b.add(_ann(_ti(0, 100), tier="words"))
            b.add(_ann(_ti(50, 150), tier="words"))
            assert len(list(b.all())) == 2
        finally:
            a.close()
            b.close()

    def test_remove_is_tenant_scoped(self, postgresql):
        ck = _conn_kwargs(postgresql)
        a = PostgresStore(ck, rate=24000, project_id="proj-a")
        b = PostgresStore(ck, rate=24000, project_id="proj-b")
        try:
            a.add_tier(Tier("words"))
            b.add_tier(Tier("words"))
            ann = _ann(_ti(0, 10), tier="words")
            a.add(ann)
            # b cannot remove a's annotation by id.
            assert b.remove(ann.id) is None
            assert len(list(a.all())) == 1
            # a can.
            assert a.remove(ann.id) is not None
        finally:
            a.close()
            b.close()


# ---------------------------------------------------------------------------
# connection pooling
# ---------------------------------------------------------------------------


class TestPooling:
    def test_pool_reuse_across_reopens(self, postgresql):
        """A string conninfo with pooling reuses one pool across open/close
        cycles (the nw per-op pattern)."""
        pytest.importorskip("psycopg_pool")
        from lacing.store.postgres import close_all_pools, get_pool
        import psycopg

        conninfo = psycopg.conninfo.make_conninfo(**_conn_kwargs(postgresql))
        try:
            s1 = PostgresStore(conninfo, rate=24000, use_pool=True)
            assert s1._pooled is True
            pool = get_pool(conninfo)
            s1.add_tier(Tier("words"))
            s1.add(_ann(_ti(0, 10), tier="words"))
            s1.close()  # returns the conn to the pool, does not close it

            # Reopen: same pool object, data persists.
            s2 = PostgresStore(conninfo, rate=24000, use_pool=True)
            assert get_pool(conninfo) is pool
            assert len(list(s2.all())) == 1
            s2.close()
        finally:
            close_all_pools()

    def test_no_pool_path_still_works(self, postgresql):
        """use_pool=False falls back to a dedicated connection."""
        conninfo = __import__("psycopg").conninfo.make_conninfo(
            **_conn_kwargs(postgresql)
        )
        s = PostgresStore(conninfo, rate=24000, use_pool=False)
        try:
            assert s._pooled is False
            s.add_tier(Tier("words"))
            s.add(_ann(_ti(0, 10), tier="words"))
            assert len(list(s.all())) == 1
        finally:
            s.close()
