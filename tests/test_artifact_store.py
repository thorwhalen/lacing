"""Tests for lacing.artifact_store."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from lacing import Artifact, ArtifactStore, hash_bytes


def _artifact(data: bytes = b"png-bytes", kind: str = "image") -> Artifact:
    return Artifact.from_bytes(
        data,
        kind=kind,
        was_generated_by="agent:test",
        was_attributed_to="user:test",
    )


# -- in-memory catalog --------------------------------------------------------


def test_in_memory_save_and_get():
    store = ArtifactStore.in_memory()
    art = _artifact()
    returned = store.save(art.asset_id, art)
    assert returned is None  # a catalog-only save reports no content hash
    assert store[art.asset_id] == art


def test_mapping_surface():
    store = ArtifactStore.in_memory()
    a, b = _artifact(b"one"), _artifact(b"two")
    store.save(a.asset_id, a)
    store.save(b.asset_id, b)
    assert len(store) == 2
    assert a.asset_id in store
    assert set(store) == {a.asset_id, b.asset_id}
    assert store.get("missing") is None
    assert store.get(a.asset_id) == a


def test_index_returns_whole_catalog_as_a_copy():
    store = ArtifactStore.in_memory()
    a = _artifact()
    store.save(a.asset_id, a)
    idx = store.index()
    assert idx == {a.asset_id: a}
    # index() is a snapshot copy: mutating it must not touch the store
    idx.clear()
    assert len(store) == 1


def test_save_is_idempotent_on_id():
    store = ArtifactStore.in_memory()
    a = _artifact()
    store.save(a.asset_id, a)
    store.save(a.asset_id, a)
    assert len(store) == 1


def test_delete_and_clear():
    store = ArtifactStore.in_memory()
    a = _artifact()
    store.save(a.asset_id, a)
    del store[a.asset_id]
    assert a.asset_id not in store
    store.save(a.asset_id, a)
    store.clear()
    assert len(store) == 0


def test_missing_key_raises_keyerror():
    store = ArtifactStore.in_memory()
    with pytest.raises(KeyError):
        _ = store["nope"]


# -- blobs --------------------------------------------------------------------


def test_blob_put_get_has():
    store = ArtifactStore.in_memory()
    data = b"some heavy bytes"
    content_hash = store.put_blob(data)
    assert content_hash == hash_bytes(data)
    assert store.get_blob(content_hash) == data
    assert store.has_blob(content_hash)


def test_save_with_data_writes_blob_and_catalog():
    store = ArtifactStore.in_memory()
    art = _artifact(b"video", kind="video")
    data = b"the-actual-video-bytes"
    content_hash = store.save(art.asset_id, art, data=data)
    assert content_hash == hash_bytes(data)
    assert store.get_blob(content_hash) == data
    assert store[art.asset_id] == art


def test_get_blob_missing_returns_none():
    store = ArtifactStore.in_memory()
    assert store.get_blob("0" * 64) is None
    assert store.has_blob("0" * 64) is False


# -- streaming + path access (Stage 2 heavy-media seams) ---------------------


def test_put_blob_stream_hashes_and_stores():
    store = ArtifactStore.in_memory()
    data = b"hello-streaming-world"
    chunks = [data[:5], data[5:11], data[11:]]
    content_hash = store.put_blob_stream(chunks)
    assert content_hash == hash_bytes(data)
    assert store.get_blob(content_hash) == data


def test_put_blob_stream_handles_empty():
    store = ArtifactStore.in_memory()
    content_hash = store.put_blob_stream(iter(()))
    assert content_hash == hash_bytes(b"")
    assert store.get_blob(content_hash) == b""


def test_put_blob_stream_is_idempotent_on_content():
    store = ArtifactStore.in_memory()
    data = b"identical-bytes"
    h1 = store.put_blob_stream([data])
    h2 = store.put_blob_stream([data[:7], data[7:]])
    assert h1 == h2 == hash_bytes(data)


def test_put_blob_stream_raises_without_blob_store():
    store = ArtifactStore(catalog={})
    with pytest.raises(RuntimeError):
        store.put_blob_stream([b"bytes"])


def test_iter_blob_yields_expected_chunks():
    store = ArtifactStore.in_memory()
    data = b"x" * 1000
    content_hash = store.put_blob(data)
    chunks = list(store.iter_blob(content_hash, chunk_size=300))
    # 300 + 300 + 300 + 100
    assert [len(c) for c in chunks] == [300, 300, 300, 100]
    assert b"".join(chunks) == data


def test_iter_blob_raises_keyerror_for_missing():
    store = ArtifactStore.in_memory()
    with pytest.raises(KeyError):
        list(store.iter_blob("0" * 64))


def test_iter_blob_on_catalog_only_store_raises_keyerror():
    # No blob store at all -> the hash is "missing", same surface.
    store = ArtifactStore(catalog={})
    with pytest.raises(KeyError):
        list(store.iter_blob("0" * 64))


def test_blob_path_returns_none_for_in_memory_backend():
    store = ArtifactStore.in_memory()
    data = b"in-memory-bytes"
    content_hash = store.put_blob(data)
    # dict has no rootdir -> no local path
    assert store.blob_path(content_hash) is None


def test_blob_path_returns_none_when_no_blob_store():
    store = ArtifactStore(catalog={})
    assert store.blob_path("0" * 64) is None


def test_blob_path_returns_path_for_filesystem_backend(tmp_path: Path):
    root = tmp_path / "artifacts"
    store = ArtifactStore.from_directory(root)
    data = b"on-disk-bytes"
    content_hash = store.put_blob(data)
    path = store.blob_path(content_hash)
    assert path is not None
    assert path.is_file()
    assert path.read_bytes() == data


def test_blob_path_returns_none_for_missing_blob(tmp_path: Path):
    root = tmp_path / "artifacts"
    store = ArtifactStore.from_directory(root)
    # An untouched store has the rootdir but nothing in it.
    assert store.blob_path("0" * 64) is None


# -- catalog-only store (the Stage-1 shape: no blob store) --------------------


def test_catalog_only_save_works_but_rejects_bytes():
    store = ArtifactStore(catalog={})  # blobs is None
    art = _artifact()
    store.save(art.asset_id, art)  # metadata-only save is fine
    assert store[art.asset_id] == art
    # a save carrying bytes must fail loudly, never silently drop them
    with pytest.raises(RuntimeError):
        store.save(art.asset_id, art, data=b"bytes")


def test_catalog_only_blob_methods_are_safe():
    store = ArtifactStore(catalog={})
    assert store.get_blob("0" * 64) is None
    assert store.has_blob("0" * 64) is False
    with pytest.raises(RuntimeError):
        store.put_blob(b"bytes")


# -- filesystem persistence ---------------------------------------------------


def test_from_directory_creates_layout(tmp_path: Path):
    root = tmp_path / "artifacts"
    ArtifactStore.from_directory(root)
    assert (root / "catalog").is_dir()
    assert (root / "blobs").is_dir()


def test_from_directory_persists_across_reopen(tmp_path: Path):
    root = tmp_path / "artifacts"
    store = ArtifactStore.from_directory(root)
    art = _artifact(b"persist-me")
    store.save(art.asset_id, art)

    reopened = ArtifactStore.from_directory(root)
    assert len(reopened) == 1
    assert reopened[art.asset_id] == art


def test_from_directory_blob_persists_across_reopen(tmp_path: Path):
    root = tmp_path / "artifacts"
    store = ArtifactStore.from_directory(root)
    data = b"heavy-bytes-on-disk"
    content_hash = store.put_blob(data)

    reopened = ArtifactStore.from_directory(root)
    assert reopened.get_blob(content_hash) == data


def test_from_directory_ignores_stray_non_json_files(tmp_path: Path):
    root = tmp_path / "artifacts"
    store = ArtifactStore.from_directory(root)
    art = _artifact()
    store.save(art.asset_id, art)
    # a stray file (e.g. a macOS .DS_Store) in catalog/ must not break iteration
    (root / "catalog" / ".DS_Store").write_bytes(b"junk")

    reopened = ArtifactStore.from_directory(root)
    assert set(reopened) == {art.asset_id}


# -- generic over the record type --------------------------------------------


class _CustomRecord(BaseModel):
    """A non-Artifact record, to prove the store does not assume Artifact."""

    id: str
    kind: str
    url: str
    content_hash: str | None = None


def test_store_is_generic_over_record_type(tmp_path: Path):
    """Identity is an explicit string id and the record schema is the caller's.

    This is a locked design decision: the catalog key is an opaque id (not
    assumed to be a content hash) and any pydantic model can be the record —
    so a consumer like ``reelee`` files artifacts under their own opaque ids
    with their own record schema.
    """
    root = tmp_path / "artifacts"
    store = ArtifactStore.from_directory(root, record_type=_CustomRecord)
    rec = _CustomRecord(id="art-image-abc123", kind="image", url="https://x/i.png")
    store.save(rec.id, rec)

    reopened = ArtifactStore.from_directory(root, record_type=_CustomRecord)
    got = reopened[rec.id]
    assert isinstance(got, _CustomRecord)
    assert got == rec
    assert got.content_hash is None
