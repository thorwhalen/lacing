"""Body schemas for named-entity (NER) annotations.

URIs:
    annot://schema/named-entity/v1   -- type + text
    annot://schema/named-entity/v2   -- entity_type + text + optional confidence (additive)

A v1 -> v2 migration is registered to demonstrate the pattern.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from lacing.schema import register_body_schema, register_migration


class NamedEntityBodyV1(BaseModel):
    """Original NER body. ``type`` is the entity tag (PER, ORG, LOC, ...)."""

    model_config = {"frozen": True, "extra": "forbid"}

    type: str = Field(..., description="Entity type code (e.g., PER, ORG, LOC).")
    text: str = Field(..., description="Surface form of the entity mention.")


class NamedEntityBodyV2(BaseModel):
    """v2 renames ``type`` -> ``entity_type`` and adds optional ``confidence``.

    The rename makes v2 incompatible with v1, so we register a migration.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    entity_type: str = Field(
        ..., description="Entity type code (e.g., PER, ORG, LOC)."
    )
    text: str = Field(..., description="Surface form of the entity mention.")
    confidence: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Optional [0, 1] confidence — for soft labels and AI annotations.",
    )


register_body_schema("annot://schema/named-entity/v1", NamedEntityBodyV1)
register_body_schema("annot://schema/named-entity/v2", NamedEntityBodyV2)


@register_migration(
    schema_name="named-entity",
    from_version=1,
    to_version=2,
)
def _v1_to_v2(body: dict) -> dict:
    """Rename `type` -> `entity_type`; leave confidence unset."""
    out = {k: v for k, v in body.items() if k != "type"}
    out["entity_type"] = body["type"]
    return out
