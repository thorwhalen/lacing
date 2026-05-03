"""Meta, schemas, health endpoints."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from lacing.schema import (
    UnknownBodySchemaError,
    json_schema as registered_json_schema,
    registered_uris,
)
from lacing.server.deps import get_store


router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict[str, str]:
    """Readiness probe."""
    return {"status": "ok"}


@router.get("/meta")
def get_all_meta(store=Depends(get_store)) -> dict[str, str]:
    """Return ``meta`` key/value pairs known to the store, when available.

    Stores that don't expose ``get_meta`` return an empty object.
    """
    get_meta = getattr(store, "get_meta", None)
    if get_meta is None:
        return {}
    out: dict[str, str] = {}
    # Phase 0/1 stores expose get_meta(key) but no list_meta(); we return
    # the well-known keys we care about by convention.
    for key in ("schema_version", "rate", "created_at", "project"):
        try:
            value = get_meta(key)
        except Exception:
            value = None
        if value is not None:
            out[key] = value
    return out


class MetaSet(BaseModel):
    model_config = {"extra": "forbid"}
    value: str = Field(..., description="String value to store.")


@router.put("/meta/{key}")
def set_meta(key: str, payload: MetaSet, store=Depends(get_store)) -> dict[str, str]:
    set_fn = getattr(store, "set_meta", None)
    if set_fn is None:
        raise HTTPException(
            status.HTTP_405_METHOD_NOT_ALLOWED,
            detail="this store does not expose set_meta()",
        )
    set_fn(key, payload.value)
    return {key: payload.value}


@router.get("/schemas")
def list_schemas() -> list[str]:
    """List every registered ``body_schema_uri``."""
    return registered_uris()


@router.get("/schemas/{uri:path}")
def get_schema(uri: str) -> dict[str, Any]:
    """Return the JSON Schema for a registered ``body_schema_uri``.

    The URI is path-encoded in the request; FastAPI hands it to us decoded,
    but we run ``unquote`` for safety.
    """
    decoded = unquote(uri)
    try:
        return registered_json_schema(decoded)
    except UnknownBodySchemaError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"no schema registered for {decoded!r}",
        )
