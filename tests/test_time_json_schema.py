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
        """The envelope's reference union carries TimeInterval, transitively."""
        schema = Annotation.model_json_schema()
        assert "TimeInterval" in str(schema)


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
