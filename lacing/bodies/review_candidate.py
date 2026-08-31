"""Body schema for review *candidates* — "this needs a human's eyes".

URI: ``annot://schema/review-candidate/v1``

A review-candidate is what an automated processor emits when it flags an
annotation as worth a human look — today,
:func:`lacing.processors.low_confidence_review` flagging low-confidence
rows. It is deliberately NOT a :class:`~lacing.bodies.review.ReviewBodyV1`:

- a review is a structured **note or verdict** (a continuity observation,
  an approval carrying a ``decision``) written *about* work;
- a candidate is a **pointer into a queue** — "look at this one, and here
  is why it was flagged" — with no message, no status lifecycle, and no
  verdict. Reviewing a candidate *produces* a review; the candidate is the
  input, not an early draft of the output.

The two lived under one URI for a while, and the processor's rows failed
validation against the model registered for that URI in five ways at once
(lacing#37). One URI per body shape is the contract ``body_schema_uri``
exists to keep; giving the candidate its own name is the whole fix — no
stored ``review/v1`` body changes shape, so no migration.

The tier split mirrors the body split, stated here because it is easy to
read as an accident: candidates land on ``"for-review"`` (the processor's
default) while human/agent reviews land on ``"review"``
(``operations.DFLT_REVIEW_TIER``). Candidates queue; reviews record.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from lacing.schema import register_body_schema


REVIEW_CANDIDATE_BODY_SCHEMA_URI = "annot://schema/review-candidate/v1"


class ReviewCandidateBodyV1(BaseModel):
    """Body of a review-candidate annotation."""

    model_config = {"frozen": True, "extra": "forbid"}

    reason: str = Field(
        ...,
        description=(
            "Why this was flagged — a short machine token, not prose "
            "(``'low_confidence'``). A string rather than a Literal so a "
            "custom processor can flag for its own reasons without a schema "
            "rev; renderers treat unknown reasons generically."
        ),
    )
    source_id: str = Field(
        ...,
        description="Id of the annotation being flagged for review.",
    )
    source_confidence: float | None = Field(
        None,
        description=(
            "The flagged annotation's confidence at flag time, when the "
            "reason is confidence-based. Recorded on the candidate because "
            "the source's confidence is mutable — the queue entry should say "
            "what the flagger saw."
        ),
    )
    source_tier: str = Field(
        "",
        description="Tier of the flagged annotation, for queue grouping.",
    )


register_body_schema(REVIEW_CANDIDATE_BODY_SCHEMA_URI, ReviewCandidateBodyV1)
