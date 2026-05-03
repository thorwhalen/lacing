"""Annotation envelope, references, and provenance.

One envelope, typed body. The ``body: dict`` is validated by the schema at
``body_schema_uri`` (semver). No polymorphic class hierarchy. See BACK-DOC §2.1
and ``.claude/skills/lacing-schema-codegen/SKILL.md``.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from lacing.time import RationalTime, TimeInterval


# --- References --------------------------------------------------------------
# A Reference points an annotation at *what* it annotates. Three flavors:
# media (a region of an external asset), node (a path into a scene graph),
# annotation (annotating another annotation — for review/discussion threads).


class MediaRef(BaseModel):
    """Reference to a region of a content-addressed media asset."""

    model_config = {"frozen": True, "extra": "forbid"}

    kind: Literal["media"] = "media"
    asset_id: str = Field(
        ..., description="Content hash (BLAKE3 / SHA-256) of the source asset."
    )
    interval: TimeInterval = Field(..., description="Region within the asset.")


class NodeRef(BaseModel):
    """Reference to a node in a structured scene/document graph."""

    model_config = {"frozen": True, "extra": "forbid"}

    kind: Literal["node"] = "node"
    scene_path: str = Field(
        ..., description="Slash-separated path identifying the node."
    )
    interval: TimeInterval = Field(
        ..., description="Region within the node's local time."
    )


class AnnotationRef(BaseModel):
    """Reference to another annotation (for discussion threads, review, derivations)."""

    model_config = {"frozen": True, "extra": "forbid"}

    kind: Literal["annotation"] = "annotation"
    target_id: UUID = Field(..., description="ID of the target annotation.")
    interval: TimeInterval | None = Field(
        None,
        description="Optional sub-interval of the target (e.g., commenting on part of it).",
    )


Reference = Annotated[MediaRef | NodeRef | AnnotationRef, Field(discriminator="kind")]
"""Discriminated union on ``kind``."""


# --- Provenance --------------------------------------------------------------
# Inline on every annotation. Subset of W3C PROV-O. See ANN-DOC §C, BACK-DOC §4.5.


class Provenance(BaseModel):
    """W3C PROV-O subset, embedded inline on every annotation."""

    model_config = {"frozen": True, "extra": "forbid"}

    was_generated_by: str = Field(
        ...,
        description=(
            "Activity identifier. Conventions: ``user:<handle>``, "
            "``agent:<model>@<hash>``, ``adapter:<format>``, ``processor:<name>``."
        ),
    )
    was_attributed_to: str = Field(
        ..., description="Responsible party (user, org, or agent)."
    )
    was_derived_from: list[UUID] = Field(
        default_factory=list,
        description="Upstream annotation IDs this one is derived from.",
    )
    generated_at_time: RationalTime = Field(
        ..., description="When the annotation was generated."
    )
    activity: str = Field(
        "create",
        description="One of: ``create``, ``import``, ``derive``, ``migrate``, ``infer``.",
    )


# --- Annotation envelope -----------------------------------------------------


class Annotation(BaseModel):
    """The single annotation envelope. ``body`` is typed by ``body_schema_uri``."""

    model_config = {"frozen": True, "extra": "forbid"}

    id: UUID = Field(..., description="Stable identifier.")
    tier: str = Field(..., description="Name of the tier this annotation belongs to.")
    reference: Reference = Field(..., description="What this annotation annotates.")
    body: dict = Field(
        ..., description="Domain-specific payload, validated by body_schema_uri."
    )
    body_schema_uri: str = Field(
        ...,
        pattern=r"^annot://schema/[a-z0-9-]+/v\d+$",
        description="e.g., ``annot://schema/named-entity/v1``",
    )
    provenance: Provenance = Field(
        ..., description="Who/when/why this annotation was created."
    )
    confidence: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Optional [0,1] confidence — for soft labels and AI-generated annotations.",
    )

    @property
    def interval(self) -> TimeInterval | None:
        """Convenience: the reference's interval, if any."""
        return self.reference.interval
