"""Tier endpoints.

    POST   /tiers          create or update a tier
    GET    /tiers          list all
    GET    /tiers/{name}   get one
    DELETE /tiers/{name}   delete (idempotent)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from lacing.server.deps import get_store
from lacing.tier import Tier, TierStereotype


router = APIRouter(prefix="/tiers", tags=["tiers"])


class TierIn(BaseModel):
    """Body for POST /tiers."""

    model_config = {"extra": "forbid"}
    name: str = Field(..., description="Tier name (unique within the store).")
    stereotype: TierStereotype = TierStereotype.NONE
    parent: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TierOut(BaseModel):
    name: str
    stereotype: TierStereotype
    parent: str | None
    metadata: dict[str, Any]

    @classmethod
    def from_tier(cls, tier: Tier) -> "TierOut":
        return cls(
            name=tier.name,
            stereotype=tier.stereotype,
            parent=tier.parent,
            metadata=tier.metadata,
        )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TierOut)
def create_tier(payload: TierIn, store=Depends(get_store)) -> TierOut:
    tier = Tier(
        payload.name,
        stereotype=payload.stereotype,
        parent=payload.parent,
        metadata=payload.metadata,
    )
    store.add_tier(tier)
    return TierOut.from_tier(tier)


@router.get("", response_model=list[TierOut])
def list_tiers(store=Depends(get_store)) -> list[TierOut]:
    return [TierOut.from_tier(t) for t in store.tiers()]


@router.get("/{name}", response_model=TierOut)
def get_tier(name: str, store=Depends(get_store)) -> TierOut:
    tier = store.get_tier(name)
    if tier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"tier {name!r} not found")
    return TierOut.from_tier(tier)
