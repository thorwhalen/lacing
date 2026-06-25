"""Tests for the ``reference-lock/v1`` body schema.

Covers: registration under the canonical URI, validation through the
public registry, the one-image / set duality, project- vs scene-scope
invariants, the advisory-by-default gating (empty ``hard_gates``),
``hard_gates ⊆ checklist`` and ``primary ∈ locked`` invariants, the
``primary`` convenience, frozen / extra-forbid behaviour, and JSON
Schema export.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lacing.bodies.reference_lock import (
    REFERENCE_LOCK_BODY_SCHEMA_URI,
    ReferenceLockBodyV1,
)
from lacing import schema as lacing_schema


def _valid(**overrides):
    kwargs = dict(subject_kind="character", subject_id="char:alex", locked_artifact_ids=("art:1",))
    kwargs.update(overrides)
    return ReferenceLockBodyV1(**kwargs)


# --- registration -----------------------------------------------------------


def test_registered_under_canonical_uri():
    import lacing.bodies  # noqa: F401  ensures registration ran

    assert REFERENCE_LOCK_BODY_SCHEMA_URI == "annot://schema/reference-lock/v1"
    assert lacing_schema.is_registered(REFERENCE_LOCK_BODY_SCHEMA_URI)
    assert lacing_schema.get_body_schema(REFERENCE_LOCK_BODY_SCHEMA_URI) is ReferenceLockBodyV1


def test_uri_parses():
    assert lacing_schema.parse_uri(REFERENCE_LOCK_BODY_SCHEMA_URI) == ("reference-lock", 1)


def test_validate_through_registry():
    body = {"subject_kind": "character", "subject_id": "char:alex", "locked_artifact_ids": ["art:1"]}
    out = lacing_schema.validate(body, REFERENCE_LOCK_BODY_SCHEMA_URI)
    assert isinstance(out, ReferenceLockBodyV1)


# --- one image OR a set -----------------------------------------------------


def test_single_locked_image():
    lock = _valid(locked_artifact_ids=("art:headshot",))
    assert lock.primary == "art:headshot"


def test_locked_set_with_primary():
    lock = _valid(
        locked_artifact_ids=("art:front", "art:threequarter", "art:fullbody"),
        primary_artifact_id="art:threequarter",
    )
    assert lock.primary == "art:threequarter"


def test_primary_defaults_to_first():
    lock = _valid(locked_artifact_ids=("art:a", "art:b"))
    assert lock.primary == "art:a"


def test_empty_locked_set_rejected():
    with pytest.raises(ValidationError):
        _valid(locked_artifact_ids=())


def test_primary_must_be_in_locked_set():
    with pytest.raises(ValidationError):
        _valid(locked_artifact_ids=("art:a",), primary_artifact_id="art:not-there")


# --- scope invariants -------------------------------------------------------


def test_project_scope_is_default():
    assert _valid().scope == "project"


def test_scene_scope_requires_ref():
    with pytest.raises(ValidationError):
        _valid(scope="scene")
    ok = _valid(scope="scene", scope_ref="scene:flashback-3")
    assert ok.scope_ref == "scene:flashback-3"


def test_project_scope_forbids_ref():
    with pytest.raises(ValidationError):
        _valid(scope="project", scope_ref="scene:x")


# --- gating: advisory by default --------------------------------------------


def test_hard_gates_empty_by_default():
    assert _valid().hard_gates == ()


def test_hard_gates_must_subset_checklist():
    with pytest.raises(ValidationError):
        _valid(checklist=("face",), hard_gates=("architecture",))
    ok = _valid(checklist=("face", "architecture"), hard_gates=("face",))
    assert ok.hard_gates == ("face",)


def test_min_similarity_bounds():
    assert _valid(min_similarity=0.0).min_similarity == 0.0
    assert _valid(min_similarity=1.0).min_similarity == 1.0
    for bad in (-0.01, 1.01):
        with pytest.raises(ValidationError):
            _valid(min_similarity=bad)


# --- envelope behaviour -----------------------------------------------------


def test_frozen():
    lock = _valid()
    with pytest.raises(ValidationError):
        lock.subject_id = "char:other"


def test_extra_forbidden():
    with pytest.raises(ValidationError):
        _valid(unexpected_field=123)


def test_supersession_field_roundtrips():
    lock = _valid(supersedes="lock:prev", notes="green flat cap present")
    dumped = lock.model_dump()
    assert dumped["supersedes"] == "lock:prev"
    assert ReferenceLockBodyV1(**dumped) == lock


def test_json_schema_export():
    js = lacing_schema.json_schema(REFERENCE_LOCK_BODY_SCHEMA_URI)
    assert js["type"] == "object"
    props = js["properties"]
    for required_field in ("subject_kind", "subject_id", "locked_artifact_ids"):
        assert required_field in props
