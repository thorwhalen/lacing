"""Annotation endpoints.

    POST   /annotations                 create
    GET    /annotations                 list (filter by tier + time window + relation)
    GET    /annotations/{id}            get one (returns ETag header)
    PATCH  /annotations/{id}            partial update (requires If-Match)
    DELETE /annotations/{id}            remove
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from lacing.allen import AllenRelation
from lacing.model import (
    Annotation,
    AnnotationRef,
    MediaRef,
    NodeRef,
    Provenance,
    Reference,
)
from lacing.server.deps import get_oplog, get_store
from lacing.server.etag import annotation_etag, matches, parse_if_match
from lacing.time import RationalTime, TimeInterval


router = APIRouter(prefix="/annotations", tags=["annotations"])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class AnnotationIn(BaseModel):
    """Wire-format incoming annotation. ``id`` and ``provenance`` are optional;
    server fills them in if missing.
    """

    model_config = {"extra": "forbid"}

    id: UUID | None = None
    tier: str
    reference: dict[str, Any] = Field(
        ..., description="Discriminated reference (kind: media|node|annotation)."
    )
    body: dict[str, Any]
    body_schema_uri: str
    provenance: dict[str, Any] | None = None
    confidence: float | None = None


def _build_reference(payload: dict[str, Any]) -> Reference:
    kind = payload.get("kind")
    if kind == "media":
        return MediaRef.model_validate(payload)
    if kind == "node":
        return NodeRef.model_validate(payload)
    if kind == "annotation":
        return AnnotationRef.model_validate(payload)
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail=f"reference.kind must be media|node|annotation, got {kind!r}",
    )


def _default_provenance(creator: str = "anonymous") -> Provenance:
    return Provenance(
        was_generated_by="server:lacing",
        was_attributed_to=creator,
        generated_at_time=RationalTime.zero(),
        activity="create",
    )


def _build_annotation(payload: AnnotationIn) -> Annotation:
    reference = _build_reference(payload.reference)
    if payload.provenance is None:
        provenance = _default_provenance()
    else:
        provenance = Provenance.model_validate(payload.provenance)

    return Annotation(
        id=payload.id or uuid4(),
        tier=payload.tier,
        reference=reference,
        body=payload.body,
        body_schema_uri=payload.body_schema_uri,
        provenance=provenance,
        confidence=payload.confidence,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _find(store: Any, annotation_id: UUID) -> Annotation:
    iter_all = getattr(store, "all", None)
    if not callable(iter_all):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="store does not expose .all()")
    for ann in iter_all():
        if ann.id == annotation_id:
            return ann
    raise HTTPException(status.HTTP_404_NOT_FOUND,
                        detail=f"annotation {annotation_id} not found")


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
def create_annotation(
    payload: AnnotationIn,
    response: Response,
    store=Depends(get_store),
    oplog=Depends(get_oplog),
) -> dict[str, Any]:
    annotation = _build_annotation(payload)
    store.add(annotation)
    clock = oplog.append(
        "add_annotation",
        target_id=str(annotation.id),
        payload={"annotation": annotation.model_dump(mode="json")},
        actor=annotation.provenance.was_attributed_to,
    )
    response.headers["ETag"] = annotation_etag(annotation)
    response.headers["X-Lacing-Clock"] = str(clock)
    return annotation.model_dump(mode="json")


@router.get("/{annotation_id}")
def get_annotation(
    annotation_id: UUID,
    response: Response,
    store=Depends(get_store),
) -> dict[str, Any]:
    annotation = _find(store, annotation_id)
    response.headers["ETag"] = annotation_etag(annotation)
    return annotation.model_dump(mode="json")


@router.delete("/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_annotation(
    annotation_id: UUID,
    store=Depends(get_store),
    oplog=Depends(get_oplog),
) -> Response:
    removed = store.remove(annotation_id)
    if removed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=f"annotation {annotation_id} not found")
    clock = oplog.append(
        "remove_annotation",
        target_id=str(annotation_id),
        payload={},
        actor=removed.provenance.was_attributed_to,
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.headers["X-Lacing-Clock"] = str(clock)
    return response


@router.get("")
def list_annotations(
    store=Depends(get_store),
    tier: str | None = Query(None, description="Filter by tier name."),
    start: float | None = Query(
        None, description="Window start (seconds); requires `end`."
    ),
    end: float | None = Query(
        None, description="Window end (seconds); requires `start`."
    ),
    relation: str = Query(
        "intersects",
        description="Allen relation: intersects, during, contains, overlaps, "
        "meets, starts, finishes, equals.",
    ),
    rate: int = Query(24000, description="Quantization rate for window seconds."),
    limit: int = Query(1000, ge=1, le=10000),
) -> list[dict[str, Any]]:
    """List annotations, optionally filtered by tier and time window."""
    iter_all = getattr(store, "all", None)
    if not callable(iter_all):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="store does not expose .all()")

    iter_anns = iter_all()
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="`start` and `end` must be given together",
            )
        try:
            window = TimeInterval(
                RationalTime.from_seconds(str(start), rate=rate),
                RationalTime.from_seconds(str(end), rate=rate),
            )
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        method = getattr(store, relation, None)
        if method is None or not callable(method):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"unknown relation {relation!r}. Try one of: "
                       f"{', '.join(r.name.lower() for r in AllenRelation)}",
            )
        iter_anns = method(window)

    if tier is not None:
        iter_anns = (a for a in iter_anns if a.tier == tier)

    results: list[dict[str, Any]] = []
    for ann in iter_anns:
        if len(results) >= limit:
            break
        results.append(ann.model_dump(mode="json"))
    return results


class AnnotationPatch(BaseModel):
    """Partial update payload."""

    model_config = {"extra": "forbid"}

    tier: str | None = None
    body: dict[str, Any] | None = None
    body_schema_uri: str | None = None
    confidence: float | None = None


@router.patch("/{annotation_id}")
def update_annotation(
    annotation_id: UUID,
    patch: AnnotationPatch,
    response: Response,
    if_match: str | None = Header(None, alias="If-Match"),
    store=Depends(get_store),
    oplog=Depends(get_oplog),
) -> dict[str, Any]:
    """Partial update with optimistic concurrency.

    Requires an ``If-Match`` header carrying the current ETag (or ``*``).
    Returns 412 Precondition Failed on mismatch.
    """
    current = _find(store, annotation_id)
    current_etag = annotation_etag(current)

    try:
        target = parse_if_match(if_match)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if target is None:
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED,
            detail="If-Match header is required for PATCH",
        )
    if not matches(current_etag, target):
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail=f"ETag mismatch: have {current_etag}, requested If-Match {target!r}",
        )

    updates: dict[str, Any] = {}
    if patch.tier is not None:
        updates["tier"] = patch.tier
    if patch.body is not None:
        updates["body"] = patch.body
    if patch.body_schema_uri is not None:
        updates["body_schema_uri"] = patch.body_schema_uri
    if patch.confidence is not None:
        updates["confidence"] = patch.confidence

    updated = current.model_copy(update=updates)
    store.remove(current.id)
    store.add(updated)

    clock = oplog.append(
        "update_annotation",
        target_id=str(updated.id),
        payload={"annotation": updated.model_dump(mode="json")},
        actor=updated.provenance.was_attributed_to,
    )
    response.headers["ETag"] = annotation_etag(updated)
    response.headers["X-Lacing-Clock"] = str(clock)
    return updated.model_dump(mode="json")
