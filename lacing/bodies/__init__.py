"""Built-in body schemas.

Each module in this package defines one body schema (Pydantic v2 model)
and registers it under an ``annot://schema/<name>/v<major>`` URI.

These are the seed schemas users can reach for; they're not authoritative
beyond demonstrating the pattern. Custom packages should register their
own under their own names.

Importing this package registers every built-in body schema.
"""

from lacing.bodies import (  # noqa: F401  registers
    character_voice,
    continuity_violation,
    named_entity,
    reference_lock,
    review,
    review_candidate,
    word,
)

__all__ = [
    "character_voice",
    "continuity_violation",
    "named_entity",
    "reference_lock",
    "review",
    "review_candidate",
    "word",
]
