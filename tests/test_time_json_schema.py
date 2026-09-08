"""Tests for the JSON Schema surface of ``RationalTime`` / ``TimeInterval``.

Non-negotiable 9 (Pydantic v2 → JSON Schema → Zod, one source of truth in two
languages) only holds if every model embedding a time can actually emit a JSON
Schema. Before lacing#47 it could not: the ``__get_pydantic_core_schema__``
hooks in ``lacing.time`` installed plain validator functions with no matching
``__get_pydantic_json_schema__``, so ``Provenance.model_json_schema()`` raised
``PydanticInvalidForJsonSchema``.

These tests pin the wire shape ``{"v": int, "r": int}`` — ``integer``, never
``number`` — and check a real JSON Schema validator honours it.
"""

import jsonschema
import pytest
from pydantic import TypeAdapter, ValidationError

from lacing.model import Annotation, MediaRef, NodeRef, Provenance
from lacing.time import (
    RATIONAL_TIME_JSON_SCHEMA,
    TIME_INTERVAL_JSON_SCHEMA,
    RationalTime,
    TimeInterval,
)


EXPECTED_RATIONAL_TIME_SCHEMA = {
    "type": "object",
    "title": "RationalTime",
    "description": (
        "A point in time as v/r seconds. Both members are integers — never a "
        "float, never a JSON number with a fractional part."
    ),
    "properties": {
        "v": {"type": "integer", "description": "Tick count (may be negative)."},
        "r": {
            "type": "integer",
            "exclusiveMinimum": 0,
            "description": "Rate in ticks per second. Strictly positive.",
        },
    },
    "required": ["v", "r"],
    "additionalProperties": False,
}


class TestWireShape:
    def test_rational_time_schema_is_exactly_the_wire_shape(self):
        assert RATIONAL_TIME_JSON_SCHEMA == EXPECTED_RATIONAL_TIME_SCHEMA

    def test_type_adapter_emits_the_same_schema(self):
        assert TypeAdapter(RationalTime).json_schema() == EXPECTED_RATIONAL_TIME_SCHEMA

    def test_members_are_integers_not_numbers(self):
        props = RATIONAL_TIME_JSON_SCHEMA["properties"]
        assert props["v"]["type"] == "integer"
        assert props["r"]["type"] == "integer"

    def test_rate_must_be_positive(self):
        assert RATIONAL_TIME_JSON_SCHEMA["properties"]["r"]["exclusiveMinimum"] == 0

    def test_time_interval_schema_nests_two_rational_times(self):
        schema = TypeAdapter(TimeInterval).json_schema()
        assert schema == TIME_INTERVAL_JSON_SCHEMA
        assert schema["properties"]["start"] == EXPECTED_RATIONAL_TIME_SCHEMA
        assert schema["properties"]["end"] == EXPECTED_RATIONAL_TIME_SCHEMA
        assert schema["required"] == ["start", "end"]

    def test_schema_constants_are_not_shared_mutable_state(self):
        """Each call hands out a copy — a caller mutating one cannot poison the rest."""
        emitted = TypeAdapter(RationalTime).json_schema()
        emitted["type"] = "tampered"
        assert RATIONAL_TIME_JSON_SCHEMA["type"] == "object"


class TestEmbeddingModels:
    """Every model embedding a time must emit a JSON Schema (lacing#47)."""

    @pytest.mark.parametrize("model", [Provenance, Annotation, MediaRef, NodeRef])
    def test_model_json_schema_succeeds(self, model):
        schema = model.model_json_schema()
        assert schema["type"] == "object"

    def test_provenance_generated_at_time_is_a_rational_time(self):
        field = Provenance.model_json_schema()["properties"]["generated_at_time"]
        assert field["title"] == "RationalTime"
        assert field["properties"]["v"]["type"] == "integer"
        assert field["properties"]["r"]["type"] == "integer"

    def test_annotation_schema_reaches_the_interval(self):
        """The envelope's reference union carries TimeInterval, transitively.

        Asserted structurally rather than by substring: walk the ``$defs`` the
        Annotation schema pulls in and find the real interval object.
        """
        schema = Annotation.model_json_schema()
        intervals = [
            d
            for d in schema.get("$defs", {}).values()
            if isinstance(d, dict) and "interval" in d.get("properties", {})
        ]
        assert intervals, (
            f"no reference model carried an interval: {list(schema.get('$defs', {}))}"
        )
        for defn in intervals:
            field = defn["properties"]["interval"]
            # Optional intervals arrive as anyOf[TimeInterval, null].
            candidates = field.get("anyOf", [field])
            objects = [c for c in candidates if c.get("type") == "object"]
            assert objects, f"interval field had no object branch: {field}"
            for obj in objects:
                assert obj["title"] == "TimeInterval"
                assert (
                    obj["properties"]["start"]["properties"]["v"]["type"] == "integer"
                )


class TestJsonSchemaValidatorRoundTrip:
    """A real JSON Schema validator must honour the integer constraint."""

    def test_accepts_the_wire_form(self):
        jsonschema.validate({"v": 0, "r": 48000}, RATIONAL_TIME_JSON_SCHEMA)

    def test_rejects_a_fractional_value(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"v": 0.5, "r": 48000}, RATIONAL_TIME_JSON_SCHEMA)

    def test_rejects_a_non_positive_rate(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"v": 0, "r": 0}, RATIONAL_TIME_JSON_SCHEMA)

    def test_rejects_a_missing_member(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"v": 0}, RATIONAL_TIME_JSON_SCHEMA)

    def test_rejects_extra_members(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"v": 0, "r": 48000, "seconds": 0.0}, RATIONAL_TIME_JSON_SCHEMA
            )

    def test_validator_and_pydantic_agree_on_the_good_case(self):
        wire = {"v": 0, "r": 48000}
        jsonschema.validate(wire, RATIONAL_TIME_JSON_SCHEMA)
        assert TypeAdapter(RationalTime).validate_python(wire) == RationalTime(0, 48000)

    def test_validator_and_pydantic_agree_on_the_bad_case(self):
        wire = {"v": 0.5, "r": 48000}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(wire, RATIONAL_TIME_JSON_SCHEMA)
        with pytest.raises(ValidationError):
            TypeAdapter(RationalTime).validate_python(wire)

    def test_interval_wire_form_round_trips(self):
        interval = TimeInterval(RationalTime(0, 48000), RationalTime(48000, 48000))
        wire = interval.to_wire()
        jsonschema.validate(wire, TIME_INTERVAL_JSON_SCHEMA)
        assert TypeAdapter(TimeInterval).validate_python(wire) == interval


# Each probe is (label, payload). The schema constants are a *second* literal,
# written by hand alongside the constructor's checks rather than derived from
# them, so nothing stops the two drifting apart — relaxing `rate <= 0` to
# `rate < 0` in the constructor leaves the shape tests green. This matrix is
# what catches that: for every payload, the JSON Schema validator and Pydantic
# must reach the SAME verdict. A one-sided change breaks a row here.
RATIONAL_TIME_PROBES = [
    ("canonical", {"v": 0, "r": 48000}),
    ("negative tick", {"v": -1, "r": 48000}),
    ("rate one", {"v": 7, "r": 1}),
    ("fractional tick", {"v": 0.5, "r": 48000}),
    ("fractional rate", {"v": 0, "r": 48000.5}),
    ("zero rate", {"v": 0, "r": 0}),
    ("negative rate", {"v": 0, "r": -48000}),
    ("missing rate", {"v": 0}),
    ("missing tick", {"r": 48000}),
    ("extra key", {"v": 0, "r": 1, "x": 1}),
    ("tick as string", {"v": "0", "r": 48000}),
    ("empty", {}),
]


def _jsonschema_accepts(payload) -> bool:
    try:
        jsonschema.validate(payload, RATIONAL_TIME_JSON_SCHEMA)
    except jsonschema.ValidationError:
        return False
    return True


def _pydantic_accepts(payload) -> bool:
    try:
        TypeAdapter(RationalTime).validate_python(payload)
    except ValidationError:
        return False
    return True


class TestValidatorAgreement:
    """The two validators are independent literals; they must never disagree."""

    @pytest.mark.parametrize(
        "payload",
        [p for _, p in RATIONAL_TIME_PROBES],
        ids=[n for n, _ in RATIONAL_TIME_PROBES],
    )
    def test_jsonschema_and_pydantic_reach_the_same_verdict(self, payload):
        assert _jsonschema_accepts(payload) == _pydantic_accepts(payload)

    def test_the_matrix_exercises_both_verdicts(self):
        """A matrix that only ever accepts (or only ever rejects) proves nothing."""
        verdicts = {_jsonschema_accepts(p) for _, p in RATIONAL_TIME_PROBES}
        assert verdicts == {True, False}

    def test_extra_keys_are_rejected_by_both_ends(self):
        """from_wire used to ignore extras while the schema forbade them.

        lacing-ui's Zod mirror is ``.strict()``, so a payload Python accepted
        would have been rejected downstream — Python was the one lax end.
        """
        payload = {"v": 0, "r": 1, "x": 1}
        assert not _jsonschema_accepts(payload)
        assert not _pydantic_accepts(payload)
        with pytest.raises(ValueError, match="unexpected wire key"):
            RationalTime.from_wire(payload)

    def test_interval_extra_keys_are_rejected(self):
        wire = {"start": {"v": 0, "r": 1}, "end": {"v": 1, "r": 1}, "label": "x"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(wire, TIME_INTERVAL_JSON_SCHEMA)
        with pytest.raises(ValueError, match="unexpected wire key"):
            TimeInterval.from_wire(wire)

    def test_missing_keys_report_which(self):
        with pytest.raises(ValueError, match=r"missing wire key\(s\): \['r'\]"):
            RationalTime.from_wire({"v": 0})
