"""S3 blob-backend tests for ``ArtifactStore.from_s3``, mocked with moto.

A separate file so the ``moto`` importorskip gates only these (not the whole
suite). Exercises the object-store path: content-addressed blob roundtrip, the
presigned-URL ``blob_location`` (the serving 302 path), and the dual-write save.
"""

import pytest

pytest.importorskip("moto")
from moto import mock_aws

from lacing import Artifact, ArtifactStore


@pytest.fixture(autouse=True)
def _isolate_aws_env(monkeypatch):
    """Hermetic moto: clear any leaked endpoint/profile + pin fake creds so
    ``@mock_aws`` always intercepts regardless of ambient AWS config."""
    for var in ("AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def _store(**kw):
    return ArtifactStore.from_s3(
        "artifacts-bucket",
        make_bucket=True,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        region_name="us-east-1",
        **kw,
    )


def _artifact(data: bytes) -> Artifact:
    return Artifact.from_bytes(
        data,
        kind="image",
        was_generated_by="agent:test",
        was_attributed_to="user:test",
    )


@mock_aws
def test_from_s3_blob_roundtrip_is_content_addressed():
    store = _store()
    ch = store.put_blob(b"png-bytes")
    assert store.has_blob(ch)
    assert store.get_blob(ch) == b"png-bytes"
    # re-PUT of identical content is idempotent (same content hash)
    assert store.put_blob(b"png-bytes") == ch


@mock_aws
def test_from_s3_blob_location_returns_presigned_url():
    store = _store()
    ch = store.put_blob(b"video-bytes")
    loc = store.blob_location(ch)
    assert isinstance(loc, str)
    assert "artifacts-bucket" in loc and "Signature" in loc
    # object store → no local path
    assert store.blob_path(ch) is None


@mock_aws
def test_from_s3_blob_location_none_for_missing():
    store = _store()
    # Write once so the bucket exists. Needed since s3dol>=1: make_bucket=True
    # maps to on_missing_bucket='create', which *recovers* (attempt -> create
    # -> retry once) rather than probing-and-creating at construction — no I/O
    # in a constructor. Reading from a not-yet-created bucket therefore raises
    # BucketNotFound instead of quietly reporting the blob missing, which is
    # the point: "your bucket does not exist" is a configuration error, not a
    # cache miss. (s3dol v0 swallowed every listing/head error as "absent".)
    store.put_blob(b"anything")
    assert store.blob_location("0" * 64) is None


@mock_aws
def test_from_s3_read_before_any_write_surfaces_the_missing_bucket():
    """The flip side, pinned: a missing bucket is loud, not a silent miss."""
    import s3dol

    store = _store()
    with pytest.raises(s3dol.BucketNotFound):
        store.blob_location("0" * 64)


@mock_aws
def test_from_s3_save_dual_writes_blob_then_catalog():
    store = _store()
    data = b"the-actual-image-bytes"
    art = _artifact(data)
    ch = store.save(art.asset_id, art, data=data)
    assert store.get_blob(ch) == data
    assert store[art.asset_id] == art


@mock_aws
def test_from_s3_honors_key_prefix():
    store = _store(prefix="blobs")
    ch = store.put_blob(b"x")
    # round-trips through the prefix and the presigned URL points at it
    assert store.get_blob(ch) == b"x"
    assert "blobs" in store.blob_location(ch)
