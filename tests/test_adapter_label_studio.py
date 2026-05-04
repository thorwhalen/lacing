"""Tests for the Label Studio JSON adapter."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from lacing.adapters import find_adapter, get_adapter
from lacing.adapters import label_studio as adapter_module  # noqa: F401  registers
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


SAMPLE_TASK: dict = {
    "id": 1,
    "data": {"audio": "https://example.org/clip.wav"},
    "annotations": [
        {
            "id": 100,
            "completed_by": "thor",
            "result": [
                {
                    "id": "r1",
                    "type": "labels",
                    "value": {"start": 0.0, "end": 1.5, "labels": ["Speech"]},
                    "from_name": "labels",
                    "to_name": "audio",
                },
                {
                    "id": "r2",
                    "type": "labels",
                    "value": {"start": 1.5, "end": 3.0, "labels": ["Music"]},
                    "from_name": "labels",
                    "to_name": "audio",
                },
            ],
        }
    ],
    "predictions": [
        {
            "id": 200,
            "model_version": "v1",
            "result": [
                {
                    "id": "p1",
                    "type": "labels",
                    "value": {"start": 4.0, "end": 5.0, "labels": ["Music"]},
                    "score": 0.7,
                    "from_name": "labels",
                    "to_name": "audio",
                }
            ],
        }
    ],
}


def _make_store_for_dump() -> MemoryStore:
    s = MemoryStore()
    s.add_tier(Tier("labels"))
    rate = 1000

    def _ann(start_ms: int, end_ms: int, label: str, *, confidence: float | None = None) -> Annotation:
        return Annotation(
            id=uuid4(),
            tier="labels",
            reference=MediaRef(
                asset_id="https://example.org/clip.wav",
                interval=TimeInterval(
                    RationalTime(start_ms, rate), RationalTime(end_ms, rate)
                ),
            ),
            body={
                "labels": [label],
                "ls_id": None,
                "ls_type": "labels",
                "from_name": "labels",
                "to_name": "audio",
            },
            body_schema_uri="annot://schema/label-studio-region/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="thor",
                generated_at_time=RationalTime.zero(rate),
            ),
            confidence=confidence,
        )

    s.add(_ann(0, 1500, "Speech"))
    s.add(_ann(1500, 3000, "Music"))
    return s


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        spec = get_adapter("label_studio")
        assert spec.name == "label_studio"

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".labelstudio.json") is not None


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_single_task_dict(self):
        store = adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)
        # 2 annotations + 1 prediction
        assert len(list(store.all())) == 3

    def test_load_array_of_tasks(self):
        store = adapter_module.load(json.dumps([SAMPLE_TASK]), rate=1000)
        assert len(list(store.all())) == 3

    def test_load_from_bytes(self):
        store = adapter_module.load(json.dumps(SAMPLE_TASK).encode("utf-8"), rate=1000)
        assert len(list(store.all())) == 3

    def test_load_from_path(self, tmp_path):
        path = tmp_path / "task.labelstudio.json"
        path.write_text(json.dumps(SAMPLE_TASK), encoding="utf-8")
        store = adapter_module.load(path, rate=1000)
        assert len(list(store.all())) == 3

    def test_creates_tier_from_from_name(self):
        store = adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)
        names = {t.name for t in store.tiers()}
        assert "labels" in names

    def test_intervals(self):
        store = adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)
        regions = sorted(
            store.by_tier("labels"),
            key=lambda a: a.interval.start.to_fraction(),
        )
        assert len(regions) == 3
        assert regions[0].interval.start.value == 0
        assert regions[0].interval.end.value == 1500
        assert regions[0].body["labels"] == ["Speech"]

    def test_asset_id_from_data_audio(self):
        store = adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)
        a = next(store.all())
        assert a.reference.asset_id == "https://example.org/clip.wav"

    def test_asset_id_override(self):
        store = adapter_module.load(
            json.dumps(SAMPLE_TASK), rate=1000, asset_id="blake3:hash"
        )
        a = next(store.all())
        assert a.reference.asset_id == "blake3:hash"

    def test_attribution_from_completed_by(self):
        store = adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)
        # Find an annotation (not prediction) — they came from the human path.
        ann = next(
            a
            for a in store.all()
            if a.provenance.activity == "import"
        )
        assert ann.provenance.was_attributed_to == "thor"

    def test_prediction_has_confidence(self):
        store = adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)
        predictions = [
            a
            for a in store.all()
            if a.body.get("is_prediction") is True
        ]
        assert len(predictions) == 1
        assert predictions[0].confidence == 0.7

    def test_prediction_provenance(self):
        store = adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)
        prediction = next(
            a for a in store.all() if a.body.get("is_prediction") is True
        )
        assert prediction.provenance.was_generated_by == "agent:label-studio"
        assert prediction.provenance.activity == "infer"


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


class TestDump:
    def test_dump_returns_bytes(self):
        store = _make_store_for_dump()
        blob = adapter_module.dump(store)
        assert isinstance(blob, bytes)
        data = json.loads(blob)
        assert isinstance(data, list)
        assert data[0]["data"]["audio"] == "https://example.org/clip.wav"

    def test_dump_to_path(self, tmp_path):
        store = _make_store_for_dump()
        out = tmp_path / "out.labelstudio.json"
        result = adapter_module.dump(store, out)
        assert result is None
        assert out.exists()

    def test_dump_groups_by_asset(self):
        s = _make_store_for_dump()
        # Add another asset's annotation.
        s.add(
            Annotation(
                id=uuid4(),
                tier="labels",
                reference=MediaRef(
                    asset_id="https://example.org/other.wav",
                    interval=TimeInterval(
                        RationalTime(0, 1000), RationalTime(500, 1000)
                    ),
                ),
                body={"labels": ["Other"], "ls_id": None, "ls_type": "labels", "from_name": "labels", "to_name": "audio"},
                body_schema_uri="annot://schema/label-studio-region/v1",
                provenance=Provenance(
                    was_generated_by="user:test",
                    was_attributed_to="thor",
                    generated_at_time=RationalTime.zero(1000),
                ),
            )
        )
        data = json.loads(adapter_module.dump(s))
        assert len(data) == 2

    def test_low_confidence_lands_in_predictions(self):
        s = _make_store_for_dump()
        # Add a low-confidence annotation
        s.add(
            Annotation(
                id=uuid4(),
                tier="labels",
                reference=MediaRef(
                    asset_id="https://example.org/clip.wav",
                    interval=TimeInterval(
                        RationalTime(4000, 1000), RationalTime(5000, 1000)
                    ),
                ),
                body={"labels": ["Maybe"], "ls_id": None, "ls_type": "labels", "from_name": "labels", "to_name": "audio"},
                body_schema_uri="annot://schema/label-studio-region/v1",
                provenance=Provenance(
                    was_generated_by="agent:test",
                    was_attributed_to="agent",
                    generated_at_time=RationalTime.zero(1000),
                ),
                confidence=0.3,
            )
        )
        data = json.loads(adapter_module.dump(s))
        task = data[0]
        assert "predictions" in task
        assert len(task["predictions"][0]["result"]) == 1
        assert task["predictions"][0]["result"][0]["score"] == 0.3


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_roundtrip(self, tmp_path):
        original = adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)
        blob = adapter_module.dump(original)
        loaded = adapter_module.load(blob, rate=1000)
        # Same number of annotations.
        assert len(list(loaded.all())) == len(list(original.all()))
        # Same labels.
        original_labels = sorted(
            tuple(a.body["labels"]) if isinstance(a.body["labels"], list) else (a.body["labels"],)
            for a in original.all()
        )
        loaded_labels = sorted(
            tuple(a.body["labels"]) if isinstance(a.body["labels"], list) else (a.body["labels"],)
            for a in loaded.all()
        )
        assert original_labels == loaded_labels


# ---------------------------------------------------------------------------
# top-level dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_load_via_format(self, tmp_path):
        from lacing.adapters import load as top_load

        path = tmp_path / "x.labelstudio.json"
        path.write_text(json.dumps(SAMPLE_TASK), encoding="utf-8")
        store = top_load(path, format="label_studio", rate=1000)
        assert len(list(store.all())) == 3
