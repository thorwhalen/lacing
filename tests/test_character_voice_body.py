"""``character-voice/v1`` — the shared per-character voice profile (lacing#10).

The promotion contract under test: the schema lives HERE (the issue's "no
reelee import required" acceptance criterion, previously false), it is a
strict SUPERSET of the shape reelee shipped under the same URI (every
stored body validates unchanged — no migration), and it carries the three
field groups the shipped subset dropped: the per-provider voice-id map,
the default emotional register, and the clone-sample artifact id that
lacing#14 made representable.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

import lacing.bodies  # noqa: F401  registers
from lacing.bodies.character_voice import (
    CHARACTER_VOICE_BODY_SCHEMA_URI,
    CHARACTER_VOICE_TIER,
    CharacterVoiceBodyV1,
)
from lacing.schema import get_body_schema, registered_uris


#: A body EXACTLY as reelee's pre-promotion model wrote it — the stored
#: population the superset must keep validating, field for field.
REELEE_SHAPED = {
    "character_ref": "NOEL",
    "voice_id": "ab12cd",
    "model_id": "eleven_v3",
    "delivery": "V3_NATURAL",
    "stability": 0.4,
    "similarity_boost": 0.8,
    "style": 0.1,
    "speed": 1.0,
    "accent": "Dublin",
    "display_name": "Noel",
    "notes": "warm, unhurried",
}


def test_registered_in_lacing_with_no_reelee_import():
    """The issue's most load-bearing acceptance criterion, previously false:
    importing lacing.bodies alone registers the URI."""
    assert CHARACTER_VOICE_BODY_SCHEMA_URI in registered_uris()
    model = get_body_schema(CHARACTER_VOICE_BODY_SCHEMA_URI)
    assert model.__module__ == "lacing.bodies.character_voice"


def test_every_stored_reelee_body_validates_unchanged():
    """The promotion is additive: reelee shipped bodies under this URI and
    they carry real user data — a field rename here is a migration event,
    and this pin is what makes that impossible to do by accident."""
    body = CharacterVoiceBodyV1.model_validate(REELEE_SHAPED)
    assert body.voice_id == "ab12cd"
    # The additive fields default cleanly for old bodies.
    assert body.provider_voice_ids == {}
    assert body.default_emotion == ""
    assert body.reference_sample_artifact_id is None


def test_the_three_promoted_field_groups_exist():
    body = CharacterVoiceBodyV1(
        character_ref="NOEL",
        voice_id="ab12cd",
        provider_voice_ids={"elevenlabs": "ab12cd", "minimax": "mx-9"},
        default_emotion="warm",
        reference_sample_artifact_id="c" * 64,
    )
    assert body.provider_voice_ids["minimax"] == "mx-9"
    assert body.default_emotion == "warm"
    assert len(body.reference_sample_artifact_id) == 64


def test_extra_forbid_still_refuses_hallucinated_knobs():
    with pytest.raises(ValidationError):
        CharacterVoiceBodyV1(
            character_ref="N", voice_id="v", emotional_range="wide"
        )


def test_round_trips_through_a_store_as_an_annotation():
    from lacing import Annotation, MediaRef, MemoryStore, Provenance, RationalTime, Tier
    from lacing import TierStereotype, TimeInterval

    store = MemoryStore()
    store.add_tier(Tier(name=CHARACTER_VOICE_TIER, stereotype=TierStereotype.NONE))
    ann = Annotation(
        id=uuid4(),
        tier=CHARACTER_VOICE_TIER,
        reference=MediaRef(asset_id="a" * 64, interval=TimeInterval.from_seconds(0, 0)),
        body=CharacterVoiceBodyV1(
            character_ref="NOEL", voice_id="v1", default_emotion="dry"
        ).model_dump(),
        body_schema_uri=CHARACTER_VOICE_BODY_SCHEMA_URI,
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="user:test",
            was_derived_from=[],
            generated_at_time=RationalTime.zero(),
            activity="create",
        ),
    )
    store.add(ann)
    (got,) = [a for a in store.all() if a.id == ann.id]
    assert CharacterVoiceBodyV1.model_validate(got.body).default_emotion == "dry"


def test_export_json_schemas_emits_it(tmp_path):
    from lacing import export_json_schemas

    paths = export_json_schemas(tmp_path)
    assert any("character-voice" in str(p) for p in paths)
