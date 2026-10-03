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


# --- Rights (lacing#34) -------------------------------------------------------

from lacing import Rights  # noqa: E402

# An Artifact serialised by lacing 0.0.47, before ``rights`` existed. Frozen
# here so a future change cannot silently break loading of deployed rows.
_PRE_RIGHTS_ROW = {
    "asset_id": "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
    "kind": "image",
    "path": None,
    "url": "https://example.test/a.png",
    "bytes_size": 11,
    "duration_s": None,
    "mime": "image/png",
    "provenance": {
        "was_generated_by": "user:test",
        "was_attributed_to": "user:test",
        "generated_at_time": {"v": 1000, "r": 1000},
    },
    "cost_usd": 0.0,
    "producer_call_id": "call-1",
}

_FULL_RIGHTS = dict(
    provider="openverse",
    id="abc123",
    title="Sunrise",
    license="CC-BY-SA-4.0",
    license_url="https://creativecommons.org/licenses/by-sa/4.0/",
    attribution='"Sunrise" by Ada, CC BY-SA 4.0',
    source_page_url="https://example.test/sunrise",
    author="Ada",
    author_url="https://example.test/ada",
    cacheable=True,
)


class TestRights:
    def test_pre_rights_row_loads_unchanged(self):
        a = Artifact.model_validate(_PRE_RIGHTS_ROW)
        assert a.rights is None
        assert Artifact.model_validate_json(json.dumps(_PRE_RIGHTS_ROW)).rights is None

    def test_artifact_without_rights_dumps_exactly_the_old_shape(self):
        # A pre-rights reader (extra="forbid") must still accept it.
        a = Artifact.model_validate(_PRE_RIGHTS_ROW)
        assert "rights" not in a.model_dump()
        assert "rights" not in a.model_dump(mode="json")
        assert "rights" not in json.loads(a.model_dump_json())
        assert set(json.loads(a.model_dump_json())) == set(_PRE_RIGHTS_ROW)

    def test_explicit_null_rights_loads_as_none(self):
        assert Artifact.model_validate({**_PRE_RIGHTS_ROW, "rights": None}).rights is None

    def test_full_record_round_trips_losslessly(self):
        a = Artifact.model_validate({**_PRE_RIGHTS_ROW, "rights": _FULL_RIGHTS})
        assert a.rights == Rights(**_FULL_RIGHTS)
        assert json.loads(a.model_dump_json())["rights"] == _FULL_RIGHTS
        assert Artifact.model_validate_json(a.model_dump_json()) == a

    def test_unrecorded_terms_are_distinct_from_no_record(self):
        # "acquired, terms unknown" is a Rights with only a provider;
        # "we made it" is None. They must not collapse into each other.
        unknown = Artifact.model_validate(
            {**_PRE_RIGHTS_ROW, "rights": {"provider": "openverse"}}
        )
        assert unknown.rights is not None
        assert unknown.rights.license is None
        restored = Artifact.model_validate_json(unknown.model_dump_json())
        assert restored.rights is not None and restored.rights.license is None
        assert json.loads(unknown.model_dump_json())["rights"] == {
            "provider": "openverse",
            "id": None,
            "title": None,
            "license": None,
            "license_url": None,
            "attribution": None,
            "source_page_url": None,
            "author": None,
            "author_url": None,
            "cacheable": None,
        }

    def test_empty_rights_cannot_exist(self):
        with pytest.raises(Exception):
            Rights()
        with pytest.raises(Exception):
            Rights(provider="")

    def test_unknown_field_is_refused_and_record_is_frozen(self):
        with pytest.raises(Exception):
            Rights(provider="p", licence="cc0")
        r = Rights(provider="p")
        with pytest.raises(Exception):
            r.license = "cc0"  # type: ignore[misc]

    def test_constructors_accept_rights(self, tmp_path: Path):
        r = Rights(**_FULL_RIGHTS)
        b = Artifact.from_bytes(
            b"x", kind="image", was_generated_by="t", was_attributed_to="u", rights=r
        )
        p = tmp_path / "f.png"
        p.write_bytes(b"x")
        f = Artifact.from_path(
            p, kind="image", was_generated_by="t", was_attributed_to="u", rights=r
        )
        assert b.rights == f.rights == r

    def test_rights_survive_the_artifact_store_catalog(self, tmp_path: Path):
        from lacing import ArtifactStore

        store = ArtifactStore.from_directory(tmp_path, record_type=Artifact)
        a = Artifact.from_bytes(
            b"x", kind="image", was_generated_by="t", was_attributed_to="u",
            rights=Rights(**_FULL_RIGHTS),
        )
        store[a.asset_id] = a
        reopened = ArtifactStore.from_directory(tmp_path, record_type=Artifact)
        assert reopened[a.asset_id].rights == Rights(**_FULL_RIGHTS)
