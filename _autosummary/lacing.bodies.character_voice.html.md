# lacing.bodies.character_voice

Body schema for per-character voice profiles — the shared voice vocabulary.

URI: `annot://schema/character-voice/v1`

A character should sound the same in every line, with a chosen accent and
default emotional register — and “the way voice usually fails isn’t the
voice itself, it’s its delivery of the lines”. This body is where a
production pins that: one profile per character, read by whichever package
synthesizes a line.

Promoted here from reelee (lacing#10): the schema first shipped inside the
application layer, which meant nw and an — the packages the profile exists
to keep consistent ACROSS — could not read it without a dependency cycle.
lacing is the federation’s shared vocabulary layer; this module is the
issue’s own “Where it lives” section, finally honoured. The promotion is a
strict SUPERSET of the shipped shape: every field reelee wrote keeps its
name, type and default, so every stored body validates unchanged (no
migration), and reelee’s module becomes a re-export of this one.

What the promotion adds (the three groups the shipped subset dropped):

- `provider_voice_ids` — the per-provider map (“elevenlabs” → one id,
  “minimax” → another), so a profile survives a provider switch instead of
  being one provider’s id wearing a generic field name. `voice_id` stays
  as the primary/default id (and what every stored body already has).
- `default_emotion` — the register a character speaks in unless a line
  overrides it.
- `reference_sample_artifact_id` — a content-addressed clone sample
  (64-hex lacing `AssetId`; representable since lacing#14), for
  voice-cloning providers.

The ElevenLabs-flavoured knobs (`stability` / `similarity_boost` /
`style` / `speed` / `delivery`) stay — they are what the shipped
bodies carry and what braidio’s synthesis path reads — documented as
provider-generic 0-1 intents that a provider adapter maps or ignores.

### Classes

| [`CharacterVoiceBodyV1`](#lacing.bodies.character_voice.CharacterVoiceBodyV1)(\*\*data)   | Body of a character-voice annotation — one character's voice profile.   |
|-----------------------------------------------------------------------------------|-------------------------------------------------------------------------|

### *class* lacing.bodies.character_voice.CharacterVoiceBodyV1(\*\*data)

Bases: `BaseModel`

Body of a character-voice annotation — one character’s voice profile.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
