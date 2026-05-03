"""Tests for lacing.model — Annotation envelope, references, provenance."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from lacing.model import (
    Annotation,
    AnnotationRef,
    MediaRef,
    NodeRef,
    Provenance,
)
from lacing.time import RationalTime, TimeInterval


def _interval() -> TimeInterval:
    return TimeInterval(RationalTime(0), RationalTime(24000))


def _provenance() -> Provenance:
    return Provenance(
        was_generated_by="user:thor",
        was_attributed_to="thor",
        generated_at_time=RationalTime(0),
    )


def _media_ref(interval: TimeInterval | None = None) -> MediaRef:
    return MediaRef(asset_id="blake3:abc123", interval=interval or _interval())


class TestMediaRef:
    def test_construction(self):
        r = _media_ref()
        assert r.kind == "media"
        assert r.asset_id == "blake3:abc123"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            MediaRef(asset_id="x", interval=_interval(), bogus=1)  # type: ignore[call-arg]

    def test_frozen(self):
        r = _media_ref()
        with pytest.raises(ValidationError):
            r.asset_id = "blake3:def"  # type: ignore[misc]

    def test_round_trip(self):
        r = _media_ref()
        d = r.model_dump()
        r2 = MediaRef.model_validate(d)
        assert r2 == r


class TestNodeRef:
    def test_construction(self):
        r = NodeRef(scene_path="/scene/track1", interval=_interval())
        assert r.kind == "node"


class TestAnnotationRef:
    def test_construction(self):
        target = uuid4()
        r = AnnotationRef(target_id=target)
        assert r.kind == "annotation"
        assert r.target_id == target
        assert r.interval is None

    def test_with_interval(self):
        r = AnnotationRef(target_id=uuid4(), interval=_interval())
        assert r.interval == _interval()


class TestProvenance:
    def test_construction(self):
        p = _provenance()
        assert p.activity == "create"
        assert p.was_derived_from == []

    def test_with_derived_from(self):
        upstream = [uuid4(), uuid4()]
        p = Provenance(
            was_generated_by="processor:forced-aligner",
            was_attributed_to="agent:mfa@v3",
            was_derived_from=upstream,
            generated_at_time=RationalTime(0),
            activity="derive",
        )
        assert p.was_derived_from == upstream
        assert p.activity == "derive"


class TestAnnotation:
    def _make(self, **overrides) -> Annotation:
        defaults = {
            "id": uuid4(),
            "tier": "words",
            "reference": _media_ref(),
            "body": {"text": "hello"},
            "body_schema_uri": "annot://schema/word/v1",
            "provenance": _provenance(),
        }
        defaults.update(overrides)
        return Annotation(**defaults)

    def test_construction(self):
        a = self._make()
        assert a.tier == "words"
        assert a.body == {"text": "hello"}

    def test_interval_property_proxies_reference(self):
        a = self._make()
        assert a.interval == _interval()

    def test_interval_none_for_annotation_ref_without_interval(self):
        a = self._make(reference=AnnotationRef(target_id=uuid4()))
        assert a.interval is None

    def test_invalid_schema_uri_rejected(self):
        with pytest.raises(ValidationError):
            self._make(body_schema_uri="not-a-uri")

    def test_schema_uri_pattern(self):
        # accepts kebab-case names with vN suffix
        self._make(body_schema_uri="annot://schema/named-entity/v2")
        with pytest.raises(ValidationError):
            self._make(body_schema_uri="annot://schema/named-entity/v")
        with pytest.raises(ValidationError):
            self._make(body_schema_uri="annot://schema/Bad_Name/v1")

    def test_confidence_bounds(self):
        self._make(confidence=0.0)
        self._make(confidence=1.0)
        with pytest.raises(ValidationError):
            self._make(confidence=-0.1)
        with pytest.raises(ValidationError):
            self._make(confidence=1.1)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            self._make(bogus="x")

    def test_frozen(self):
        a = self._make()
        with pytest.raises(ValidationError):
            a.tier = "phonemes"  # type: ignore[misc]

    def test_round_trip_through_dump_validate(self):
        a = self._make()
        d = a.model_dump()
        a2 = Annotation.model_validate(d)
        assert a2 == a

    def test_discriminated_union_picks_media(self):
        d = {
            "id": str(uuid4()),
            "tier": "words",
            "reference": {
                "kind": "media",
                "asset_id": "blake3:x",
                "interval": _interval().to_wire(),
            },
            "body": {},
            "body_schema_uri": "annot://schema/word/v1",
            "provenance": {
                "was_generated_by": "user:thor",
                "was_attributed_to": "thor",
                "was_derived_from": [],
                "generated_at_time": RationalTime(0).to_wire(),
                "activity": "create",
            },
        }
        a = Annotation.model_validate(d)
        assert isinstance(a.reference, MediaRef)
