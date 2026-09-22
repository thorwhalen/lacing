# lacing.bodies

Built-in body schemas.

Each module in this package defines one body schema (Pydantic v2 model)
and registers it under an `annot://schema/<name>/v<major>` URI.

These are the seed schemas users can reach for; they’re not authoritative
beyond demonstrating the pattern. Custom packages should register their
own under their own names.

Importing this package registers every built-in body schema.

### Modules

| [`character_voice`](lacing.bodies.character_voice.md#module-lacing.bodies.character_voice)           | Body schema for per-character voice profiles — the shared voice vocabulary.     |
|-----------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`continuity_violation`](lacing.bodies.continuity_violation.md#module-lacing.bodies.continuity_violation) | Body schema for continuity violations — generic, cross-media.                   |
| [`named_entity`](lacing.bodies.named_entity.md#module-lacing.bodies.named_entity)                 | Body schemas for named-entity (NER) annotations.                                |
| [`reference_lock`](lacing.bodies.reference_lock.md#module-lacing.bodies.reference_lock)             | Body schema for a *locked reference* — a first-class “this is canonical”.       |
| [`review`](lacing.bodies.review.md#module-lacing.bodies.review)                             | Body schema for review notes — the edit-loop's communication channel.           |
| [`review_candidate`](lacing.bodies.review_candidate.md#module-lacing.bodies.review_candidate)         | Body schema for review *candidates* — "this needs a human's eyes".              |
| [`word`](lacing.bodies.word.md#module-lacing.bodies.word)                                 | Body schema for word-level annotations (e.g., transcription, forced alignment). |
