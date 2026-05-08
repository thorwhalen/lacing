"""Tests for lacing.artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lacing import (
    Artifact,
    MediaRef,
    Provenance,
    TimeInterval,
    hash_bytes,
    hash_file,
)


def test_hash_bytes_deterministic():
    a = hash_bytes(b"hello world")
    b = hash_bytes(b"hello world")
    assert a == b
    assert len(a) == 64
    assert all(c in "0123456789abcdef" for c in a)


def test_hash_file_matches_hash_bytes(tmp_path: Path):
    data = b"some content here"
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    assert hash_file(p) == hash_bytes(data)


def test_from_path_roundtrip(tmp_path: Path):
    p = tmp_path / "audio.wav"
    p.write_bytes(b"RIFF....fake-wav-bytes")
    art = Artifact.from_path(
        p,
        kind="audio",
        was_generated_by="user:test",
        was_attributed_to="user:test",
        duration_s=2.5,
        mime="audio/wav",
    )
    assert art.kind == "audio"
    assert art.path == p
    assert art.bytes_size == p.stat().st_size
    assert art.duration_s == 2.5
    assert art.mime == "audio/wav"
    assert art.url is None
    # Round-trip via JSON.
    restored = Artifact.model_validate_json(art.model_dump_json())
    assert restored == art


def test_from_bytes_no_path():
    data = b"png-bytes-here"
    art = Artifact.from_bytes(
        data,
        kind="image",
        was_generated_by="agent:flux@v1",
        was_attributed_to="user:test",
        url="https://example.com/img.png",
    )
    assert art.bytes_size == len(data)
    assert art.path is None
    assert art.url == "https://example.com/img.png"
    assert art.asset_id == hash_bytes(data)


def test_artifact_is_frozen():
    art = Artifact.from_bytes(
        b"x", kind="binary",
        was_generated_by="t", was_attributed_to="t",
    )
    with pytest.raises(Exception):  # pydantic ValidationError on frozen model
        art.kind = "image"  # type: ignore[misc]


def test_asset_id_validates_format():
    # Pydantic enforces the SHA-256 hex pattern.
    with pytest.raises(Exception):
        Artifact(
            asset_id="not-a-hex",
            kind="image",
            bytes_size=1,
            provenance=Provenance(
                was_generated_by="t",
                was_attributed_to="t",
                generated_at_time=__import__("lacing.time", fromlist=["RationalTime"]).RationalTime.from_fraction(
                    __import__("fractions").Fraction(0), rate=24000
                ),
            ),
        )


def test_to_media_ref_uses_asset_id():
    data = b"some image bytes"
    art = Artifact.from_bytes(
        data, kind="image",
        was_generated_by="t", was_attributed_to="t",
    )
    ref = art.to_media_ref(TimeInterval.from_seconds(0, 1))
    assert isinstance(ref, MediaRef)
    assert ref.asset_id == art.asset_id


def test_provenance_chain():
    """An artifact derived from another artifact records the lineage."""
    parent = Artifact.from_bytes(
        b"parent", kind="image",
        was_generated_by="agent:flux", was_attributed_to="user:t",
    )
    # Re-purpose a deterministic pseudo-id for the parent (in real use,
    # was_derived_from holds annotation UUIDs; for artifact lineage we'd
    # typically attach derivation through a lacing.Annotation, but the
    # field accepts any list of UUIDs and the test exercises that
    # the field round-trips).
    import uuid
    parent_uuid = uuid.uuid4()
    child = Artifact.from_bytes(
        b"derived",
        kind="image",
        was_generated_by="agent:flux-kontext",
        was_attributed_to="user:t",
        was_derived_from=(parent_uuid,),
        activity="derive",
    )
    assert child.provenance.was_derived_from == [parent_uuid]
    assert child.provenance.activity == "derive"
    # Parent is independent.
    assert parent.provenance.was_derived_from == []


def test_top_level_imports_work():
    """The point of putting Artifact in lacing is that producers import it from lacing."""
    from lacing import Artifact as A1
    from lacing.artifact import Artifact as A2
    assert A1 is A2
