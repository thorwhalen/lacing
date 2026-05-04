"""Import and export endpoints.

    POST  /import?format=<name>     upload a file in any registered format
    GET   /export?format=<name>     dump the current store

Adapters self-register on first import. The server eagerly imports the
Phase 0/1 adapter modules at app-creation time, so the registry is
already populated when the first request arrives.
"""

from __future__ import annotations

import importlib
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from lacing.server.deps import get_store


router = APIRouter(tags=["adapters"])


_PHASE_01_ADAPTERS = (
    "lacing.adapters.textgrid",
    "lacing.adapters.webvtt",
    "lacing.adapters.web_annotation",
    "lacing.adapters.annot",
    "lacing.adapters.eaf",
    "lacing.adapters.jams",
    "lacing.adapters.label_studio",
    "lacing.adapters.otio",
)


def ensure_adapters_registered() -> None:
    """Import every Phase 0/1 adapter so they self-register.

    Idempotent — Python caches imports.
    """
    for name in _PHASE_01_ADAPTERS:
        try:
            importlib.import_module(name)
        except ImportError:
            # Optional adapters (textgrid, eaf, jams) raise when their
            # backend isn't installed. Keep going — the server stays usable.
            continue


# Media types per adapter format. Used as Content-Type on /export responses.
_DEFAULT_MEDIA_TYPES: dict[str, str] = {
    "textgrid": "text/x-praat-textgrid",
    "webvtt": "text/vtt",
    "web_annotation": "application/ld+json",
    "annot": "application/x-lacing-annot",
    "eaf": "application/x-eaf+xml",
    "jams": "application/vnd.jams+json",
}


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_file(
    file: UploadFile,
    format: str = Query(..., description="Registered adapter name."),
    rate: int = Query(24000, description="Quantization rate."),
    store=Depends(get_store),
) -> dict[str, Any]:
    """Upload a file in any registered format.

    The uploaded file is parsed by the named adapter, and the resulting
    annotations + tiers are merged into the active store.
    """
    ensure_adapters_registered()
    from lacing.adapters import get_adapter

    try:
        spec = get_adapter(format)
    except KeyError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"unknown format {format!r}"
        )

    payload = await file.read()
    parsed_store = spec.load(payload, rate=rate)

    n_tiers = 0
    for tier in parsed_store.tiers():
        if store.get_tier(tier.name) is None:
            store.add_tier(tier)
            n_tiers += 1

    n_added = 0
    iter_all = getattr(parsed_store, "all", None)
    if callable(iter_all):
        for ann in iter_all():
            store.add(ann)
            n_added += 1

    return {
        "format": format,
        "annotations_added": n_added,
        "tiers_added": n_tiers,
    }


@router.get("/export")
def export_file(
    format: str = Query(..., description="Registered adapter name."),
    store=Depends(get_store),
) -> Response:
    """Dump the active store as a file in the named format."""
    ensure_adapters_registered()
    from lacing.adapters import get_adapter

    try:
        spec = get_adapter(format)
    except KeyError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"unknown format {format!r}"
        )

    blob = spec.dump(store, target=None)
    if blob is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"adapter {format!r} returned no bytes from dump()",
        )

    media_type = _DEFAULT_MEDIA_TYPES.get(format, "application/octet-stream")
    ext = spec.extensions[0] if spec.extensions else ""
    filename = f"export{ext}"
    return Response(
        content=blob,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/formats")
def list_formats() -> list[dict[str, Any]]:
    """List every registered format adapter."""
    ensure_adapters_registered()
    from lacing.adapters import registered

    return [
        {
            "name": spec.name,
            "extensions": list(spec.extensions),
            "media_types": list(spec.media_types),
            "body_schema_uris": list(spec.body_schema_uris),
            "description": spec.description,
        }
        for spec in registered()
    ]
