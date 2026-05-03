"""Tests for the W3C Web Annotation JSON-LD adapter."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from lacing.adapters import find_adapter, get_adapter
from lacing.adapters import web_annotation as adapter_module  # noqa: F401  registers
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


SINGLE_ANNOTATION = {
    "@context": "http://www.w3.org/ns/anno.jsonld",
    "id": "urn:uuid:11111111-1111-1111-1111-111111111111",
    "type": "Annotation",
    "motivation": "describing",
    "body": {"type": "TextualBody", "value": "A speaker", "format": "text/plain"},
    "target": {
        "source": "http://example.org/audio.mp3",
        "selector": {
            "type": "FragmentSelector",
            "conformsTo": "http://www.w3.org/TR/media-frags/",
            "value": "t=1.0,2.5",
        },
    },
    "creator": "user:thor",
    "created": "2026-05-03T12:00:00Z",
}


COLLECTION = {
    "@context": "http://www.w3.org/ns/anno.jsonld",
    "type": "AnnotationCollection",
    "total": 2,
    "items": [
        {
            "id": "urn:uuid:22222222-2222-2222-2222-222222222222",
            "type": "Annotation",
            "body": {"value": "first"},
            "target": {
                "source": "http://example.org/x.mp3",
                "selector": {
                    "type": "FragmentSelector",
                    "value": "t=0.0,1.0",
                },
            },
        },
        {
            "id": "urn:uuid:33333333-3333-3333-3333-333333333333",
            "type": "Annotation",
            "body": {"value": "second"},
            "target": {
                "source": "http://example.org/x.mp3",
                "selector": {
                    "type": "FragmentSelector",
                    "value": "t=1.0,2.0",
                },
            },
        },
    ],
}


def _ann(start_ms: int, end_ms: int, motivation: str = "describing", *, tier: str = "annotations") -> Annotation:
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(
            asset_id="http://example.org/audio.mp3",
            interval=TimeInterval(
                RationalTime(start_ms, 1000),
                RationalTime(end_ms, 1000),
            ),
        ),
        body={
            "body": {"type": "TextualBody", "value": "hello"},
            "motivation": motivation,
        },
        body_schema_uri="annot://schema/web-annotation/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="thor",
            generated_at_time=RationalTime.zero(1000),
        ),
    )


# --- registry --------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("web_annotation")
        assert spec.name == "web_annotation"

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".jsonld") is not None

    def test_lookup_by_media_type(self):
        assert find_adapter(media_type="application/ld+json") is not None


# --- time fragment helpers -------------------------------------------------


class TestTimeFragment:
    def test_parse_range(self):
        iv = adapter_module._parse_time_fragment("t=1.5,3.0", rate=1000)
        assert iv is not None
        assert iv.start.value == 1500
        assert iv.end.value == 3000

    def test_parse_point(self):
        iv = adapter_module._parse_time_fragment("t=2", rate=1000)
        assert iv is not None
        assert iv.is_point
        assert iv.start.value == 2000

    def test_parse_with_npt_prefix(self):
        iv = adapter_module._parse_time_fragment("t=npt:0.5,1.5", rate=1000)
        assert iv is not None
        assert iv.start.value == 500

    def test_format_range(self):
        iv = TimeInterval(RationalTime(1500, 1000), RationalTime(3000, 1000))
        assert adapter_module._format_time_fragment(iv) == "t=1.5,3"

    def test_format_point(self):
        iv = TimeInterval.point(RationalTime(2000, 1000))
        assert adapter_module._format_time_fragment(iv) == "t=2"


# --- load ------------------------------------------------------------------


class TestLoad:
    def test_load_single_from_dict_string(self):
        store = adapter_module.load(json.dumps(SINGLE_ANNOTATION))
        anns = list(store.all())
        assert len(anns) == 1

    def test_load_single_from_bytes(self):
        store = adapter_module.load(json.dumps(SINGLE_ANNOTATION).encode("utf-8"))
        assert len(list(store.all())) == 1

    def test_load_single_from_path(self, tmp_path):
        path = tmp_path / "single.jsonld"
        path.write_text(json.dumps(SINGLE_ANNOTATION), encoding="utf-8")
        store = adapter_module.load(path)
        assert len(list(store.all())) == 1

    def test_load_collection(self):
        store = adapter_module.load(json.dumps(COLLECTION))
        assert len(list(store.all())) == 2

    def test_load_list(self):
        store = adapter_module.load(json.dumps(COLLECTION["items"]))
        assert len(list(store.all())) == 2

    def test_target_source_preserved(self):
        store = adapter_module.load(json.dumps(SINGLE_ANNOTATION))
        a = next(store.all())
        assert a.reference.asset_id == "http://example.org/audio.mp3"

    def test_interval_parsed(self):
        store = adapter_module.load(json.dumps(SINGLE_ANNOTATION))
        a = next(store.all())
        assert a.interval.start.value == 1000
        assert a.interval.end.value == 2500

    def test_motivation_preserved(self):
        store = adapter_module.load(json.dumps(SINGLE_ANNOTATION))
        a = next(store.all())
        assert a.body["motivation"] == "describing"

    def test_body_preserved_verbatim(self):
        store = adapter_module.load(json.dumps(SINGLE_ANNOTATION))
        a = next(store.all())
        assert a.body["body"] == SINGLE_ANNOTATION["body"]

    def test_creator_into_provenance(self):
        store = adapter_module.load(json.dumps(SINGLE_ANNOTATION))
        a = next(store.all())
        assert a.provenance.was_attributed_to == "user:thor"
        assert a.provenance.was_generated_by == "adapter:web_annotation"

    def test_creator_dict(self):
        annot = dict(SINGLE_ANNOTATION)
        annot["creator"] = {"id": "user:42", "name": "X", "type": "Person"}
        store = adapter_module.load(json.dumps(annot))
        a = next(store.all())
        assert a.provenance.was_attributed_to == "user:42"

    def test_created_string_preserved(self):
        store = adapter_module.load(json.dumps(SINGLE_ANNOTATION))
        a = next(store.all())
        assert a.body["created"] == "2026-05-03T12:00:00Z"

    def test_id_uuid_coerced(self):
        store = adapter_module.load(json.dumps(SINGLE_ANNOTATION))
        a = next(store.all())
        assert str(a.id) == "11111111-1111-1111-1111-111111111111"

    def test_non_uuid_id_falls_back(self):
        annot = dict(SINGLE_ANNOTATION)
        annot["id"] = "https://example.org/anno/123"
        store = adapter_module.load(json.dumps(annot))
        a = next(store.all())
        # Just confirm it didn't crash and produced *some* UUID
        assert isinstance(a.id, type(uuid4()))

    def test_skips_annotations_without_time_fragment(self):
        annot = {
            "@context": "http://www.w3.org/ns/anno.jsonld",
            "type": "Annotation",
            "body": {"value": "x"},
            "target": "http://example.org/no-fragment",
        }
        store = adapter_module.load(json.dumps(annot))
        assert len(list(store.all())) == 0

    def test_target_string_with_fragment(self):
        annot = {
            "@context": "http://www.w3.org/ns/anno.jsonld",
            "type": "Annotation",
            "body": {"value": "x"},
            "target": "http://example.org/clip.mp4#t=1.0,2.0",
        }
        store = adapter_module.load(json.dumps(annot))
        a = next(store.all())
        assert a.reference.asset_id == "http://example.org/clip.mp4"
        assert a.interval.start.value == 1000
        assert a.interval.end.value == 2000

    def test_asset_id_override(self):
        store = adapter_module.load(
            json.dumps(SINGLE_ANNOTATION), asset_id="blake3:hash"
        )
        a = next(store.all())
        assert a.reference.asset_id == "blake3:hash"


# --- dump ------------------------------------------------------------------


class TestDump:
    def test_dump_returns_bytes(self):
        s = MemoryStore()
        s.add(_ann(1000, 2500))
        blob = adapter_module.dump(s)
        assert isinstance(blob, bytes)

    def test_dump_collection_shape(self):
        s = MemoryStore()
        s.add(_ann(0, 1000))
        s.add(_ann(1000, 2000))
        d = json.loads(adapter_module.dump(s))
        assert d["type"] == "AnnotationCollection"
        assert len(d["items"]) == 2
        assert d["total"] == 2

    def test_dump_includes_fragment_selector(self):
        s = MemoryStore()
        s.add(_ann(1500, 3000))
        d = json.loads(adapter_module.dump(s))
        sel = d["items"][0]["target"]["selector"]
        assert sel["type"] == "FragmentSelector"
        assert sel["value"] == "t=1.5,3"

    def test_dump_to_path(self, tmp_path):
        s = MemoryStore()
        s.add(_ann(0, 1000))
        out = tmp_path / "out.jsonld"
        result = adapter_module.dump(s, out)
        assert result is None
        assert out.exists()

    def test_dump_bare_when_single_and_not_collection(self):
        s = MemoryStore()
        s.add(_ann(0, 1000))
        d = json.loads(adapter_module.dump(s, as_collection=False))
        assert d["type"] == "Annotation"

    def test_dump_preserves_motivation(self):
        s = MemoryStore()
        s.add(_ann(0, 1000, motivation="commenting"))
        d = json.loads(adapter_module.dump(s))
        assert d["items"][0]["motivation"] == "commenting"

    def test_dump_preserves_creator(self):
        s = MemoryStore()
        s.add(_ann(0, 1000))
        d = json.loads(adapter_module.dump(s))
        assert d["items"][0]["creator"] == "thor"

    def test_dump_preserves_tier(self):
        s = MemoryStore()
        s.add(_ann(0, 1000, tier="speakers"))
        d = json.loads(adapter_module.dump(s))
        assert d["items"][0]["tier"] == "speakers"


# --- round trip ------------------------------------------------------------


class TestRoundTrip:
    def test_roundtrip_single(self):
        original = adapter_module.load(json.dumps(SINGLE_ANNOTATION))
        blob = adapter_module.dump(original)
        loaded = adapter_module.load(blob)
        assert len(list(loaded.all())) == 1

        a_orig = next(original.all())
        a_loaded = next(loaded.all())
        assert a_orig.interval == a_loaded.interval
        assert a_orig.reference.asset_id == a_loaded.reference.asset_id
        assert a_orig.body["motivation"] == a_loaded.body["motivation"]
        assert a_orig.tier == a_loaded.tier

    def test_roundtrip_collection(self):
        original = adapter_module.load(json.dumps(COLLECTION))
        blob = adapter_module.dump(original)
        loaded = adapter_module.load(blob)

        original_pairs = sorted(
            (a.interval.start.value, a.interval.end.value) for a in original.all()
        )
        loaded_pairs = sorted(
            (a.interval.start.value, a.interval.end.value) for a in loaded.all()
        )
        assert loaded_pairs == original_pairs
