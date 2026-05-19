"""Body schema for review notes — the edit-loop's communication channel.

URI: ``annot://schema/review/v1``

A *review* annotation is a structured note attached to one or more
artifacts (a panel, a beat, a segmentation alternate, a render result),
optionally pointing at a typed payload like a
:class:`ContinuityViolationBodyV1`. Reviews are produced by:

- automated checkers (continuity, grammar, timing, segmentation rules)
- the edit-loop ("this caption needs a revision")
- the orchestrator ("the user declined the cost gate at panel 12")
- the user ("approve" / "needs revision" notes)

The body is intentionally minimal. The kind (``review_kind``) routes
the FE renderer; the payload is opaque to lacing.

References:
- ``reelee/docs/Narrative to Storyboard.md`` §6.5–6.6.
- ``reelee/docs/reelee 03 -- Human-AI Collaboration UX Patterns…`` §10
  (annotation overlays).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from lacing.schema import register_body_schema


REVIEW_BODY_SCHEMA_URI = "annot://schema/review/v1"


ReviewKind = Literal[
    "continuity",
    "segmentation",
    "prompt",
    "grammar",
    "timing",
    "iconic_moment",
    "manual",
    "approval",
]
"""What flavor of review this is. Drives the FE's renderer choice and
the producing-Transform's routing logic."""


ReviewStatus = Literal[
    "open",
    "addressed",
    "wont_fix",
    "deferred",
]
"""Open is the initial state; the others are user / agent resolutions."""


Author = Literal["human", "agent", "system"]
"""Coarse author classification. The annotation envelope's
``was_attributed_to`` carries the specific identity; this field is the
quick chip for the FE."""


class ReviewBodyV1(BaseModel):
    """Body of a review annotation."""

    model_config = {"frozen": True, "extra": "forbid"}

    review_kind: ReviewKind = Field(..., description="What flavor of review this is.")
    target_annotation_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description=(
            "Annotation ids this review targets. Typically one, but "
            "continuity reviews carry the same ids as the underlying "
            "ContinuityViolationBodyV1."
        ),
    )
    message: str = Field(
        "", description="Human-readable note shown in the review panel."
    )
    status: ReviewStatus = Field("open", description="Lifecycle state.")
    author: Author = Field(
        "human", description="Coarse author chip — human / agent / system."
    )
    violation_ref: Optional[str] = Field(
        None,
        description=(
            "Optional id of a ``continuity-violation/v1`` (or other typed "
            "payload) backing this review. The FE inspector follows this "
            "ref to render rule-specific evidence."
        ),
    )
    suggested_action_slug: str = Field(
        "",
        description=(
            "Optional acture command slug the FE should highlight as the "
            "default action (e.g. 'panel.regen', 'panel.editPrompt')."
        ),
    )


register_body_schema(REVIEW_BODY_SCHEMA_URI, ReviewBodyV1)
