"""SQL catalog-backend tests for ``ArtifactStore.from_sql`` (SQLite).

A separate file so the ``sqldol`` importorskip gates only these, not the whole
suite. Exercises the SQL-backed *catalog* path: the same mapping contract the
dict / ``Files`` catalogs pass (round-trip ``save``/``__getitem__``/``__iter__``/
``__delitem__``/``__contains__``/``len``), persistence across reopen, the
content-hash reference count used by GC, the dual-write ordering with an
injected blob store, and genericity over the record type.

SQLite (in-memory and on a temp file) stands in for Postgres here: the *same*
``from_sql`` code runs against ``postgresql://`` in production — that is the
whole point of the vendor-neutral facade. The real-Postgres validation lives in
``test_artifact_store_sql_postgres.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

pytest.importorskip("sqldol")

from lacing import Artifact, ArtifactStore, hash_bytes  # noqa: E402


def _artifact(data: bytes = b"png-bytes", kind: str = "image") -> Artifact:
    return Artifact.from_bytes(
        data,
        kind=kind,
        was_generated_by="agent:test",
        was_attributed_to="user:test",
    )


# -- the same mapping contract as the dict / Files catalogs -------------------


def test_sql_catalog_save_and_get():
    store = ArtifactStore.from_sql("sqlite:///:memory:")
    art = _artifact()
    # a catalog-only save (no blob store wired) reports no content hash
    assert store.save(art.asset_id, art) is None
    assert store[art.asset_id] == art


def test_sql_catalog_mapping_surface():
    store = ArtifactStore.from_sql("sqlite:///:memory:")
    a, b = _artifact(b"one"), _artifact(b"two")
    store.save(a.asset_id, a)
    store.save(b.asset_id, b)
    assert len(store) == 2
    assert a.asset_id in store
    assert "definitely-not-a-key" not in store
    assert set(store) == {a.asset_id, b.asset_id}
    assert store.get("missing") is None
    assert store.get(a.asset_id) == a


def test_sql_catalog_setitem_and_delitem():
    store = ArtifactStore.from_sql("sqlite:///:memory:")
    a = _artifact()
    store[a.asset_id] = a  # plain mapping write
    assert store[a.asset_id] == a
    del store[a.asset_id]
    assert a.asset_id not in store
    assert len(store) == 0


def test_sql_catalog_missing_key_raises_keyerror():
    store = ArtifactStore.from_sql("sqlite:///:memory:")
    with pytest.raises(KeyError):
        _ = store["nope"]


def test_sql_catalog_save_is_idempotent_on_id():
    store = ArtifactStore.from_sql("sqlite:///:memory:")
    a = _artifact()
    store.save(a.asset_id, a)
    store.save(a.asset_id, a)
    assert len(store) == 1


def test_sql_catalog_index_returns_whole_catalog():
    store = ArtifactStore.from_sql("sqlite:///:memory:")
    a = _artifact()
    store.save(a.asset_id, a)
    assert store.index() == {a.asset_id: a}


# -- persistence across reopen (the durability point) -------------------------


def test_sql_catalog_persists_across_reopen(tmp_path: Path):
    uri = f"sqlite:///{tmp_path / 'cat.db'}"
    store = ArtifactStore.from_sql(uri)
    art = _artifact(b"persist-me")
    store.save(art.asset_id, art)

    reopened = ArtifactStore.from_sql(uri)
    assert len(reopened) == 1
    assert reopened[art.asset_id] == art


# -- content-hash reference count (the GC primitive) --------------------------


def test_sql_count_refs_is_one_per_distinct_artifact():
    store = ArtifactStore.from_sql("sqlite:///:memory:")
    a, b = _artifact(b"one"), _artifact(b"two")
    store.save(a.asset_id, a)
    store.save(b.asset_id, b)
    assert store.count_refs(a.asset_id) == 1
    assert store.count_refs(b.asset_id) == 1
    assert store.count_refs("0" * 64) == 0


def test_sql_count_refs_dedup_shared_blob():
    """Two records sharing one content hash → refcount 2 (GC must not delete
    the blob until both go away)."""

    class _Rec(BaseModel):
        id: str
        content_hash: str

    store = ArtifactStore.from_sql("sqlite:///:memory:", record_type=_Rec)
    store.save("id-1", _Rec(id="id-1", content_hash="deadbeef"))
    store.save("id-2", _Rec(id="id-2", content_hash="deadbeef"))
    store.save("id-3", _Rec(id="id-3", content_hash="cafef00d"))
    assert store.count_refs("deadbeef") == 2
    assert store.count_refs("cafef00d") == 1


def test_sql_count_refs_drops_to_zero_after_delete():
    store = ArtifactStore.from_sql("sqlite:///:memory:")
    a = _artifact()
    store.save(a.asset_id, a)
    assert store.count_refs(a.asset_id) == 1
    del store[a.asset_id]
    assert store.count_refs(a.asset_id) == 0


# -- dual-write ordering with an injected blob store --------------------------


def test_sql_catalog_with_injected_blobs_dual_writes():
    """A SQL catalog paired with an in-memory blob store still writes the blob
    first, then the catalog row (the save() ordering must hold regardless of
    catalog backend)."""
    blobs: dict[str, bytes] = {}
    store = ArtifactStore.from_sql("sqlite:///:memory:", blobs=blobs)
    art = _artifact(b"video", kind="video")
    data = b"the-actual-video-bytes"
    content_hash = store.save(art.asset_id, art, data=data)
    assert content_hash == hash_bytes(data)
    assert store.get_blob(content_hash) == data
    assert store[art.asset_id] == art


def test_sql_catalog_only_rejects_bytes():
    store = ArtifactStore.from_sql("sqlite:///:memory:")  # no blobs
    art = _artifact()
    store.save(art.asset_id, art)  # metadata-only is fine
    with pytest.raises(RuntimeError):
        store.save(art.asset_id, art, data=b"bytes")


# -- generic over the record type --------------------------------------------


def test_sql_catalog_is_generic_over_record_type(tmp_path: Path):
    class _CustomRecord(BaseModel):
        id: str
        kind: str
        url: str
        content_hash: str | None = None

    uri = f"sqlite:///{tmp_path / 'custom.db'}"
    store = ArtifactStore.from_sql(uri, record_type=_CustomRecord)
    rec = _CustomRecord(id="art-image-abc", kind="image", url="https://x/i.png")
    store.save(rec.id, rec)

    reopened = ArtifactStore.from_sql(uri, record_type=_CustomRecord)
    got = reopened[rec.id]
    assert isinstance(got, _CustomRecord)
    assert got == rec
    assert got.content_hash is None


def test_sql_catalog_custom_content_hash_extractor():
    """A record whose blob hash lives on a non-default field still feeds the
    indexed content_hash column via ``content_hash_of``."""

    class _Rec(BaseModel):
        id: str
        sha: str

    store = ArtifactStore.from_sql(
        "sqlite:///:memory:",
        record_type=_Rec,
        content_hash_of=lambda r: r.sha,
    )
    store.save("a", _Rec(id="a", sha="hhh"))
    store.save("b", _Rec(id="b", sha="hhh"))
    assert store.count_refs("hhh") == 2
