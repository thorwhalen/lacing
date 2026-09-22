"""Tests for lacing.artifact_store."""

from __future__ import annotations

import os
import threading
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


# -- blob reads: containment (lacing#50) --------------------------------------
#
# ``from_directory(root)`` keeps blobs in ``root / "blobs"``, so an escaping
# key must climb out of *that* directory. Each test first asserts the secret
# is genuinely reachable by the raw join (``_reachable``), so a test cannot
# pass vacuously by pointing at a file that does not exist.


def _store_and_secret(tmp_path: Path):
    store = ArtifactStore.from_directory(tmp_path / "artifacts")
    blob_dir = Path(store.blobs.rootdir)
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"do not serve me")
    return store, blob_dir, secret


def _reachable(blob_dir: Path, key: str) -> bool:
    return (blob_dir / key).is_file()


def _assert_refused_everywhere(store: ArtifactStore, key: str):
    assert store.blob_path(key) is None
    assert store.has_blob(key) is False
    assert store.get_blob(key) is None
    assert store.blob_location(key) is None
    with pytest.raises(KeyError):
        b"".join(store.iter_blob(key))


def test_blob_reads_refuse_relative_traversal(tmp_path: Path):
    store, blob_dir, _ = _store_and_secret(tmp_path)
    key = "../../secret.txt"
    assert _reachable(blob_dir, key)
    _assert_refused_everywhere(store, key)


def test_blob_reads_refuse_absolute_path(tmp_path: Path):
    store, blob_dir, secret = _store_and_secret(tmp_path)
    key = str(secret)
    assert _reachable(blob_dir, key)
    _assert_refused_everywhere(store, key)


def test_blob_reads_refuse_symlink_escaping_root(tmp_path: Path):
    store, blob_dir, secret = _store_and_secret(tmp_path)
    key = "0" * 64
    (blob_dir / key).symlink_to(secret)
    assert _reachable(blob_dir, key)
    _assert_refused_everywhere(store, key)


def test_blob_reads_refuse_sibling_dir_sharing_the_root_prefix(tmp_path: Path):
    # ``<root>-evil`` string-prefix-matches ``<root>`` but is not inside it.
    store, blob_dir, _ = _store_and_secret(tmp_path)
    evil = blob_dir.parent / (blob_dir.name + "-evil")
    evil.mkdir()
    (evil / "x").write_bytes(b"evil")
    key = f"../{evil.name}/x"
    assert _reachable(blob_dir, key)
    _assert_refused_everywhere(store, key)


@pytest.mark.parametrize("key", ["", ".", "..", "a\x00b"])
def test_blob_reads_refuse_degenerate_keys_without_raising(tmp_path: Path, key):
    store, _, _ = _store_and_secret(tmp_path)
    _assert_refused_everywhere(store, key)


def test_blob_reads_still_serve_legitimate_blob(tmp_path: Path):
    store, _, _ = _store_and_secret(tmp_path)
    data = b"legit-bytes"
    content_hash = store.put_blob(data)
    path = store.blob_path(content_hash)
    assert path is not None and path.read_bytes() == data
    assert store.has_blob(content_hash)
    assert store.get_blob(content_hash) == data
    assert b"".join(store.iter_blob(content_hash)) == data
    assert store.blob_location(content_hash) == path


def test_blob_reads_serve_nested_and_in_root_symlinked_keys(tmp_path: Path):
    # Containment must not break keys that stay inside the root: a nested key
    # (an injected backend that shards by prefix) and an in-root symlink.
    store, blob_dir, _ = _store_and_secret(tmp_path)
    (blob_dir / "ab").mkdir()
    (blob_dir / "ab" / "cdef").write_bytes(b"nested")
    (blob_dir / "alias").symlink_to(blob_dir / "ab" / "cdef")
    for key in ("ab/cdef", "ab/../ab/cdef", "alias"):
        assert store.has_blob(key), key
        assert store.get_blob(key) == b"nested", key
        assert store.blob_path(key) == (blob_dir / "ab" / "cdef").resolve(), key


def test_blob_reads_on_dict_backend_are_not_filtered(tmp_path: Path):
    # No rootdir, no filesystem to escape: keys are opaque and pass through.
    store = ArtifactStore(catalog={}, blobs={"../odd": b"x"})
    assert store.has_blob("../odd")
    assert store.get_blob("../odd") == b"x"


# -- blob reads: check-then-open race (lacing#50, second round) ---------------
#
# The containment check resolves the key; the read then opens it. An attacker
# who can write into the blob directory can swap the checked entry for a
# symlink in between. These tests hit that window deterministically: they
# wrap the check so the swap happens right after it has passed.

_needs_openat = pytest.mark.skipif(
    not (getattr(os, "O_NOFOLLOW", 0) and os.open in os.supports_dir_fd),
    reason="no openat/O_NOFOLLOW on this OS (Windows): the race window stays open",
)


def _swap_after_check(monkeypatch, swap):
    from lacing import artifact_store

    real_check = artifact_store._resolve_within

    def check_then_swap(rootdir, key):
        resolved = real_check(rootdir, key)
        swap()
        return resolved

    monkeypatch.setattr(artifact_store, "_resolve_within", check_then_swap)


@_needs_openat
def test_blob_reads_refuse_symlink_swapped_in_after_the_check(
    tmp_path: Path, monkeypatch
):
    store, blob_dir, secret = _store_and_secret(tmp_path)
    key = "ab" * 32
    (blob_dir / key).write_bytes(b"benign")

    def swap():
        link = blob_dir / ".swap"
        if not link.is_symlink():
            link.symlink_to(secret)
        os.replace(link, blob_dir / key)

    _swap_after_check(monkeypatch, swap)
    assert _reachable(blob_dir, key)  # the raw join now leads to the secret
    _assert_refused_everywhere(store, key)


@_needs_openat
def test_blob_reads_refuse_directory_swapped_for_symlink_after_the_check(
    tmp_path: Path, monkeypatch
):
    store, blob_dir, secret = _store_and_secret(tmp_path)
    (blob_dir / "ab").mkdir()
    (blob_dir / "ab" / "secret.txt").write_bytes(b"benign")

    def swap():
        if not (blob_dir / "ab").is_symlink():
            (blob_dir / "ab").rename(blob_dir / ".ab-old")
            (blob_dir / "ab").symlink_to(secret.parent, target_is_directory=True)

    _swap_after_check(monkeypatch, swap)
    key = "ab/secret.txt"
    _assert_refused_everywhere(store, key)
    assert _reachable(blob_dir, key)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs on this OS")
def test_blob_reads_refuse_fifo_without_blocking(tmp_path: Path):
    # Opening a FIFO for reading blocks until a writer appears; a FIFO planted
    # under a blob's name must read as absent, not hang the server.
    store, blob_dir, _ = _store_and_secret(tmp_path)
    key = "cd" * 32
    os.mkfifo(blob_dir / key)
    done = threading.Event()

    def read_all():
        _assert_refused_everywhere(store, key)
        done.set()

    threading.Thread(target=read_all, daemon=True).start()
    assert done.wait(timeout=10), "blob read blocked on a FIFO"


def test_blob_reads_refuse_directory_key(tmp_path: Path):
    store, blob_dir, _ = _store_and_secret(tmp_path)
    (blob_dir / "somedir").mkdir()
    _assert_refused_everywhere(store, "somedir")


def test_blob_reads_serve_through_a_symlinked_root(tmp_path: Path):
    # The store's own directory may itself be a symlink (e.g. a mounted volume).
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "linked").symlink_to(real, target_is_directory=True)
    store = ArtifactStore.from_directory(tmp_path / "linked")
    content_hash = store.put_blob(b"via-link")
    assert store.has_blob(content_hash)
    assert store.get_blob(content_hash) == b"via-link"
    assert store.blob_path(content_hash).read_bytes() == b"via-link"


# -- blob_location: the generalized servable-location probe -------------------


def test_blob_location_returns_path_for_filesystem_backend(tmp_path: Path):
    store = ArtifactStore.from_directory(tmp_path / "artifacts")
    content_hash = store.put_blob(b"on-disk")
    location = store.blob_location(content_hash)
    assert isinstance(location, Path)
    assert location.read_bytes() == b"on-disk"


def test_blob_location_returns_none_for_in_memory_and_missing():
    store = ArtifactStore.in_memory()
    content_hash = store.put_blob(b"x")
    assert store.blob_location(content_hash) is None  # dict: no path, no url
    assert store.blob_location("0" * 64) is None  # missing blob


def test_blob_location_returns_presigned_url_when_backend_supports_it():
    """An object-store backend exposing ``url_for(key)`` → a URL string the
    HTTP layer 302-redirects to (S3/R2 presigned-URL serving path)."""

    class _S3ish(dict):
        def url_for(self, key: str) -> str:
            return f"https://bucket.example/{key}?sig=abc"

    store = ArtifactStore(catalog={}, blobs=_S3ish())
    content_hash = store.put_blob(b"video-bytes")
    location = store.blob_location(content_hash)
    assert location == f"https://bucket.example/{content_hash}?sig=abc"
    # A missing blob still returns None even with url_for present.
    assert store.blob_location("0" * 64) is None


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


class TestStreamingBlobWrites:
    """lacing#25: spool + hash-while-streaming + atomic rename."""

    def test_streaming_peaks_at_chunk_size_not_twice_the_payload(self, tmp_path):
        import tracemalloc

        store = ArtifactStore.from_directory(tmp_path / "store")
        payload_mb = 8
        chunk = b"x" * 1024

        tracemalloc.start()
        content_hash = store.put_blob_stream(
            chunk for _ in range(payload_mb * 1024)
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert store.get_blob(content_hash) is not None
        # The buffered implementation peaked at ~2x payload (16 MB here);
        # spooling must stay well under half the payload.
        assert peak < payload_mb * 1024 * 1024 / 2

    def test_no_partial_blob_is_ever_observable_under_a_content_address(
        self, tmp_path
    ):
        import re

        blob_dir = tmp_path / "store" / "blobs"
        store = ArtifactStore.from_directory(tmp_path / "store")
        observed: list[list[str]] = []

        def chunks():
            for i in range(3):
                yield f"part-{i}".encode()
                if blob_dir.exists():
                    observed.append(
                        [
                            p.name
                            for p in blob_dir.iterdir()
                            if re.fullmatch(r"[0-9a-f]{64}", p.name)
                        ]
                    )

        content_hash = store.put_blob_stream(chunks())

        assert all(names == [] for names in observed)  # nothing mid-write
        assert store.has_blob(content_hash)
        leftovers = [p for p in blob_dir.iterdir() if p.name.endswith(".part")]
        assert leftovers == []

    def test_a_failed_stream_leaves_nothing_behind(self, tmp_path):
        blob_dir = tmp_path / "store" / "blobs"
        store = ArtifactStore.from_directory(tmp_path / "store")

        def explodes():
            yield b"some bytes"
            raise RuntimeError("upstream died mid-download")

        with pytest.raises(RuntimeError, match="mid-download"):
            store.put_blob_stream(explodes())

        assert list(blob_dir.iterdir()) == [] if blob_dir.exists() else True

    def test_put_blob_rides_the_same_atomic_path(self, tmp_path):
        store = ArtifactStore.from_directory(tmp_path / "store")

        content_hash = store.put_blob(b"tiny")

        assert store.get_blob(content_hash) == b"tiny"
        assert store.blob_path(content_hash).exists()

    def test_the_in_memory_fallback_still_round_trips(self):
        store = ArtifactStore.in_memory()

        content_hash = store.put_blob_stream((b"a", b"b", b"c"))

        assert store.get_blob(content_hash) == b"abc"
