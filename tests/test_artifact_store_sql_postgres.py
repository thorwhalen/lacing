"""Real-Postgres validation of ``ArtifactStore.from_sql``.

The SQLite suite (``test_artifact_store_sql.py``) covers the catalog contract;
this file proves the *same* ``from_sql`` code runs unchanged against real
Postgres — the vendor-neutrality claim that makes Phase 2 production-ready.

Gated exactly like ``test_store_postgres.py``: ``pytest-postgresql`` spawns a
sandbox Postgres, and the whole module skips if Postgres (or the deps) aren't
present. The ``postgresql`` fixture yields a connection to a fresh database; we
build a ``postgresql://`` URI from its connection params and hand it to
``from_sql`` — exactly what a production deployment passes.
"""

from __future__ import annotations

import shutil

import pytest

pytest.importorskip("pytest_postgresql")
pytest.importorskip("psycopg")
pytest.importorskip("sqldol")
if not any(shutil.which(name) for name in ("pg_ctl", "postgres")):
    pytest.skip("Postgres binary not on PATH", allow_module_level=True)

from pydantic import BaseModel  # noqa: E402

from lacing import Artifact, ArtifactStore, hash_bytes  # noqa: E402


def _pg_uri(postgresql) -> str:
    """Build a SQLAlchemy ``postgresql://`` URI from the pytest fixture's conn.

    Uses the ``psycopg`` (v3) driver — that is what lacing's postgres extra
    installs and what ``test_store_postgres.py`` relies on.
    """
    info = postgresql.info
    pwd = info.password or ""
    return (
        f"postgresql+psycopg://{info.user}:{pwd}@{info.host}:{info.port}/{info.dbname}"
    )


def _artifact(data: bytes = b"png-bytes", kind: str = "image") -> Artifact:
    return Artifact.from_bytes(
        data,
        kind=kind,
        was_generated_by="agent:test",
        was_attributed_to="user:test",
    )


@pytest.fixture
def pg_store(postgresql):
    return ArtifactStore.from_sql(_pg_uri(postgresql))


def test_pg_catalog_round_trip(pg_store):
    art = _artifact()
    pg_store.save(art.asset_id, art)
    assert pg_store[art.asset_id] == art
    assert art.asset_id in pg_store
    assert set(pg_store) == {art.asset_id}
    assert len(pg_store) == 1


def test_pg_catalog_delete(pg_store):
    art = _artifact()
    pg_store.save(art.asset_id, art)
    del pg_store[art.asset_id]
    assert art.asset_id not in pg_store
    assert len(pg_store) == 0


def test_pg_count_refs_dedup(pg_store):
    a, b = _artifact(b"one"), _artifact(b"two")
    pg_store.save(a.asset_id, a)
    pg_store.save(b.asset_id, b)
    assert pg_store.count_refs(a.asset_id) == 1
    assert pg_store.count_refs("0" * 64) == 0


def test_pg_count_refs_shared_blob(postgresql):
    class _Rec(BaseModel):
        id: str
        content_hash: str

    store = ArtifactStore.from_sql(_pg_uri(postgresql), record_type=_Rec)
    store.save("id-1", _Rec(id="id-1", content_hash="deadbeef"))
    store.save("id-2", _Rec(id="id-2", content_hash="deadbeef"))
    assert store.count_refs("deadbeef") == 2


def test_pg_catalog_with_injected_blobs_dual_writes(postgresql):
    blobs: dict[str, bytes] = {}
    store = ArtifactStore.from_sql(_pg_uri(postgresql), blobs=blobs)
    art = _artifact(b"video", kind="video")
    data = b"the-actual-video-bytes"
    content_hash = store.save(art.asset_id, art, data=data)
    assert content_hash == hash_bytes(data)
    assert store.get_blob(content_hash) == data
    assert store[art.asset_id] == art


def test_pg_persists_across_reopen(postgresql):
    uri = _pg_uri(postgresql)
    store = ArtifactStore.from_sql(uri)
    art = _artifact(b"persist-me")
    store.save(art.asset_id, art)

    reopened = ArtifactStore.from_sql(uri)
    assert len(reopened) == 1
    assert reopened[art.asset_id] == art
