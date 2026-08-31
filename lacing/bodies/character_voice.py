"""Body schema for per-character voice profiles — the shared voice vocabulary.

URI: ``annot://schema/character-voice/v1``

A character should sound the same in every line, with a chosen accent and
default emotional register — and "the way voice usually fails isn't the
voice itself, it's its delivery of the lines". This body is where a
production pins that: one profile per character, read by whichever package
synthesizes a line.

Promoted here from reelee (lacing#10): the schema first shipped inside the
application layer, which meant nw and an — the packages the profile exists
to keep consistent ACROSS — could not read it without a dependency cycle.
lacing is the federation's shared vocabulary layer; this module is the
issue's own "Where it lives" section, finally honoured. The promotion is a
strict SUPERSET of the shipped shape: every field reelee wrote keeps its
name, type and default, so every stored body validates unchanged (no
migration), and reelee's module becomes a re-export of this one.

What the promotion adds (the three groups the shipped subset dropped):

- ``provider_voice_ids`` — the per-provider map ("elevenlabs" → one id,
  "minimax" → another), so a profile survives a provider switch instead of
  being one provider's id wearing a generic field name. ``voice_id`` stays
  as the primary/default id (and what every stored body already has).
- ``default_emotion`` — the register a character speaks in unless a line
  overrides it.
- ``reference_sample_artifact_id`` — a content-addressed clone sample
  (64-hex lacing ``AssetId``; representable since lacing#14), for
  voice-cloning providers.

The ElevenLabs-flavoured knobs (``stability`` / ``similarity_boost`` /
``style`` / ``speed`` / ``delivery``) stay — they are what the shipped
bodies carry and what braidio's synthesis path reads — documented as
provider-generic 0-1 intents that a provider adapter maps or ignores.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from lacing.schema import register_body_schema


CHARACTER_VOICE_BODY_SCHEMA_URI = "annot://schema/character-voice/v1"
CHARACTER_VOICE_TIER = "character-voice"


class CharacterVoiceBodyV1(BaseModel):
    """Body of a character-voice annotation — one character's voice profile."""

    model_config = {"frozen": True, "extra": "forbid"}

    character_ref: str = Field(
        ...,
        description=(
            "The character this voice belongs to — the ``name`` (or id) of a "
            "``character-ref/v1`` annotation. Dialogue speakers are matched "
            "against this to resolve which voice speaks a line."
        ),
    )
    voice_id: str = Field(
        ...,
        description=(
            "The primary TTS voice identifier (provider-specific). The one "
            "field a profile must have; ``provider_voice_ids`` carries "
            "alternates for other providers."
        ),
    )
    provider_voice_ids: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-provider voice ids, keyed by provider slug (``'elevenlabs'``, "
            "``'minimax'``, ...). A synthesis path looks its provider up here "
            "first and falls back to ``voice_id`` — which is what lets a "
            "production switch providers without recasting every character."
        ),
    )
    model_id: Optional[str] = Field(
        None,
        description=(
            "TTS model id (e.g. ``eleven_v3`` for expressive dialogue). "
            "None uses the synthesis path's default for the call's register."
        ),
    )
    delivery: Optional[str] = Field(
        None,
        description=(
            "Name of a delivery preset (e.g. ``V3_NATURAL``) to seed the "
            "voice settings; the individual knobs below override it."
        ),
    )
    default_emotion: str = Field(
        "",
        description=(
            "The emotional register this character speaks in unless a line "
            "overrides it (``'warm'``, ``'clipped'``, ``'deadpan'`` — free "
            "text a synthesis path may map to provider controls or fold "
            "into a prompt)."
        ),
    )
    stability: Optional[float] = Field(
        None,
        description="Voice-setting intent (0-1): lower = more expressive/variable.",
    )
    similarity_boost: Optional[float] = Field(
        None, description="Voice-setting intent (0-1): adherence to the source voice."
    )
    style: Optional[float] = Field(
        None, description="Voice-setting intent (0-1): style exaggeration (0.0 = off)."
    )
    speed: Optional[float] = Field(
        None, description="Voice-setting intent: speaking-rate multiplier."
    )
    accent: Optional[str] = Field(
        None,
        description=(
            "Human-readable accent label. Shown in pickers; a synthesis path "
            "MAY fold it into prompt-style controls where the provider has "
            "them."
        ),
    )
    reference_sample_artifact_id: Optional[str] = Field(
        None,
        description=(
            "Content-addressed id (64-hex lacing ``AssetId``) of a stored "
            "voice sample, for cloning providers. An id, not a URL — the "
            "sample must survive re-uploads byte-identically."
        ),
    )
    display_name: Optional[str] = Field(
        None,
        description="Human label for this voice in a picker; defaults to the character name.",
    )
    notes: str = Field(
        "",
        description="Free-form notes about the voice choice (direction, casting rationale).",
    )


register_body_schema(CHARACTER_VOICE_BODY_SCHEMA_URI, CharacterVoiceBodyV1)
