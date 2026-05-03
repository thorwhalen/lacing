"""Body schema for word-level annotations (e.g., transcription, forced alignment).

URI: ``annot://schema/word/v1``
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from lacing.schema import register_body_schema


class WordBodyV1(BaseModel):
    """A single word annotation.

    The ``text`` is the surface form as it appears in the source media.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    text: str = Field(..., description="Surface form of the word.")
    speaker: str | None = Field(None, description="Optional speaker identifier.")


register_body_schema("annot://schema/word/v1", WordBodyV1)
