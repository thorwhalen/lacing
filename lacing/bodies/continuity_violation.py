"""Body schema for continuity violations — generic, cross-media.

URI: ``annot://schema/continuity-violation/v1``

A *continuity violation* is a typed claim about a relationship between
two or more annotations: "panels 5 and 6 cross the 180° axis", "the
character drift between panel 3 and panel 4 exceeds the embed-distance
threshold", "object detection finds a prop in panel 7 absent from
panel 8."

The schema is intentionally generic. Specific rule families live in
their producing packages — reelee defines axis_180, character_drift,
prop_hallucination, etc. via dedicated Transforms — but the *envelope*
that carries the result is generic enough to live in lacing.

Violations attach as ``review/v1`` annotations whose ``review_kind ==
"continuity"`` (see :mod:`lacing.bodies.review`).

Reference: ``reelee/docs/Narrative to Storyboard.md`` §6.5, §8.1.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from lacing.schema import register_body_schema


CONTINUITY_VIOLATION_BODY_SCHEMA_URI = "annot://schema/continuity-violation/v1"


Severity = Literal["info", "warn", "error"]


SuggestedAction = Literal[
    "regen_panel",
    "regen_with_ref",
    "manual_edit",
    "accept",
]
"""Coarse action the edit-loop UI offers in response. Producing
Transforms pick one; the FE wires each to a button + acture command."""


class ContinuityViolationBodyV1(BaseModel):
    """Body of a continuity-violation annotation."""

    model_config = {"frozen": True, "extra": "forbid"}

    rule: str = Field(
        ...,
        description=(
            "Producing-rule slug — e.g. 'axis_180', 'eyeline', "
            "'character_drift', 'environment_drift', 'prop_hallucination', "
            "'30_rule', 'costume', 'lighting', 'time_of_day', 'weather', "
            "'screen_direction'. Strings rather than Literal so new "
            "rules can be added without a schema bump."
        ),
    )
    annotation_ids: tuple[str, ...] = Field(
        ...,
        description=(
            "≥2 annotation ids the violation relates (e.g. the two "
            "panels in conflict). Order is meaningful when the rule is "
            "directional (e.g. 'character_drift' from A to B)."
        ),
    )
    severity: Severity = Field("warn", description="info / warn / error.")
    detection_method: str = Field(
        "",
        description=(
            "How the violation was detected — 'face_embed_cosine', "
            "'optical_flow_direction', 'object_detect_set_diff', etc."
        ),
    )
    detection_value: Optional[float] = Field(
        None,
        description=(
            "Numeric detection signal (e.g. cosine distance). None for "
            "boolean detections."
        ),
    )
    threshold: Optional[float] = Field(
        None,
        description=(
            "Threshold the value crossed to trigger the violation. None "
            "for boolean detections."
        ),
    )
    suggested_fix: str = Field(
        "",
        description=(
            "Human-readable fix sentence; the FE renders it in the continuity panel."
        ),
    )
    suggested_action: SuggestedAction = Field(
        "manual_edit",
        description=(
            "Coarse action recommendation. Drives which button the FE highlights."
        ),
    )
    evidence: dict = Field(
        default_factory=dict,
        description=(
            "Rule-specific evidence (e.g. eyeline vectors, bbox set "
            "diffs). Opaque to lacing; consumed by the inspector."
        ),
    )


register_body_schema(CONTINUITY_VIOLATION_BODY_SCHEMA_URI, ContinuityViolationBodyV1)
