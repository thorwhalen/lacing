"""Backend operations shared between REST and MCP layers.

This module contains the *business logic* of the server (build an
``Annotation`` from a flat dict, replay the op-log, etc.) without any
HTTP plumbing. Both the FastAPI routers (under ``lacing/server/routers/``)
and the MCP tools (under ``lacing/server/mcp.py``) call into here so the
two surfaces stay in lockstep.

By convention every public function takes ``store`` and ``oplog`` as
positional args — making the data flow explicit and testable without a
running server.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from lacing.allen import AllenRelation
from lacing.model import (
    Annotation,
    AnnotationRef,
    MediaRef,
    NodeRef,
    Provenance,
    Reference,
)
from lacing.tier import Tier, TierStereotype
from lacing.time import RationalTime, TimeInterval


# ---------------------------------------------------------------------------
# tiers
# ---------------------------------------------------------------------------


def add_tier(
    store: Any,
    oplog: Any,
    *,
    name: str,
    stereotype: str | TierStereotype = TierStereotype.NONE,
    parent: str | None = None,
    metadata: dict[str, Any] | None = None,
    actor: str = "anonymous",
) -> Tier:
    """Add or update a tier; record an ``add_tier`` op-log entry."""
    if isinstance(stereotype, str):
        stereotype = TierStereotype(stereotype)
    tier = Tier(
        name,
        stereotype=stereotype,
        parent=parent,
        metadata=metadata or {},
    )
    store.add_tier(tier)
    oplog.append(
        "add_tier",
        target_id=tier.name,
        payload={
            "name": tier.name,
            "stereotype": tier.stereotype.value,
            "parent": tier.parent,
            "metadata": tier.metadata,
        },
        actor=actor,
    )
    return tier


def list_tiers(store: Any) -> list[Tier]:
    return list(store.tiers())


def get_tier(store: Any, name: str) -> Tier | None:
    return store.get_tier(name)


# ---------------------------------------------------------------------------
# annotations
# ---------------------------------------------------------------------------


def _build_reference(payload: dict[str, Any]) -> Reference:
    kind = payload.get("kind")
    if kind == "media":
        return MediaRef.model_validate(payload)
    if kind == "node":
        return NodeRef.model_validate(payload)
    if kind == "annotation":
        return AnnotationRef.model_validate(payload)
    raise ValueError(f"reference.kind must be media|node|annotation, got {kind!r}")


def _default_provenance(creator: str = "anonymous") -> Provenance:
    return Provenance(
        was_generated_by="server:lacing",
        was_attributed_to=creator,
        generated_at_time=RationalTime.zero(),
        activity="create",
    )


def add_annotation_from_payload(
    store: Any,
    oplog: Any,
    *,
    tier: str,
    reference: dict[str, Any],
    body: dict[str, Any],
    body_schema_uri: str,
    annotation_id: UUID | None = None,
    provenance: dict[str, Any] | None = None,
    confidence: float | None = None,
    actor: str = "anonymous",
) -> Annotation:
    """Build an ``Annotation`` from a flat dict payload, add to store + op-log."""
    ref = _build_reference(reference)
    if provenance is None:
        prov = _default_provenance(actor)
    else:
        prov = Provenance.model_validate(provenance)

    annotation = Annotation(
        id=annotation_id or uuid4(),
        tier=tier,
        reference=ref,
        body=body,
        body_schema_uri=body_schema_uri,
        provenance=prov,
        confidence=confidence,
    )
    store.add(annotation)
    oplog.append(
        "add_annotation",
        target_id=str(annotation.id),
        payload={"annotation": annotation.model_dump(mode="json")},
        actor=annotation.provenance.was_attributed_to,
    )
    return annotation


def add_annotation_from_seconds(
    store: Any,
    oplog: Any,
    *,
    tier: str,
    asset_id: str,
    start_seconds: float | str,
    end_seconds: float | str,
    body: dict[str, Any],
    body_schema_uri: str,
    rate: int = 1000,
    confidence: float | None = None,
    actor: str = "anonymous",
) -> Annotation:
    """MCP-friendly: build an annotation from flat seconds floats.

    The interval is built via ``RationalTime.from_seconds(str(...), rate=rate)``
    — strings preserve precision, floats are forwarded to ``Fraction(repr())``
    by ``from_seconds``.
    """
    interval = TimeInterval(
        RationalTime.from_seconds(str(start_seconds), rate=rate),
        RationalTime.from_seconds(str(end_seconds), rate=rate),
    )
    reference = {
        "kind": "media",
        "asset_id": asset_id,
        "interval": {
            "start": interval.start.to_wire(),
            "end": interval.end.to_wire(),
        },
    }
    return add_annotation_from_payload(
        store,
        oplog,
        tier=tier,
        reference=reference,
        body=body,
        body_schema_uri=body_schema_uri,
        confidence=confidence,
        actor=actor,
    )


def get_annotation(store: Any, annotation_id: UUID) -> Annotation | None:
    iter_all = getattr(store, "all", None)
    if not callable(iter_all):
        return None
    for ann in iter_all():
        if ann.id == annotation_id:
            return ann
    return None


def remove_annotation(
    store: Any, oplog: Any, annotation_id: UUID, *, actor: str = "anonymous"
) -> Annotation | None:
    removed = store.remove(annotation_id)
    if removed is None:
        return None
    oplog.append(
        "remove_annotation",
        target_id=str(annotation_id),
        payload={},
        actor=actor,
    )
    return removed


def update_annotation(
    store: Any,
    oplog: Any,
    annotation_id: UUID,
    *,
    updates: dict[str, Any],
    actor: str = "anonymous",
) -> Annotation | None:
    """Replace the annotation's mutable fields and re-record."""
    current = get_annotation(store, annotation_id)
    if current is None:
        return None
    updated = current.model_copy(update=updates)
    store.remove(current.id)
    store.add(updated)
    oplog.append(
        "update_annotation",
        target_id=str(updated.id),
        payload={"annotation": updated.model_dump(mode="json")},
        actor=actor,
    )
    return updated


def query_annotations(
    store: Any,
    *,
    tier: str | None = None,
    start_seconds: float | str | None = None,
    end_seconds: float | str | None = None,
    relation: str = "intersects",
    rate: int = 1000,
    limit: int = 1000,
) -> list[Annotation]:
    """Filter annotations by tier and/or time window via Allen relations."""
    iter_all = getattr(store, "all", None)
    if not callable(iter_all):
        return []

    iter_anns = iter_all()
    if start_seconds is not None or end_seconds is not None:
        if start_seconds is None or end_seconds is None:
            raise ValueError("`start_seconds` and `end_seconds` must be given together")
        window = TimeInterval(
            RationalTime.from_seconds(str(start_seconds), rate=rate),
            RationalTime.from_seconds(str(end_seconds), rate=rate),
        )
        method = getattr(store, relation, None)
        if method is None or not callable(method):
            raise ValueError(
                f"unknown relation {relation!r}; expected one of: "
                f"{', '.join(r.name.lower() for r in AllenRelation)}"
            )
        iter_anns = method(window)

    results: list[Annotation] = []
    for ann in iter_anns:
        if tier is not None and ann.tier != tier:
            continue
        if len(results) >= limit:
            break
        results.append(ann)
    return results


# ---------------------------------------------------------------------------
# AI suggestion review (per BACK-DOC §3.3 example)
# ---------------------------------------------------------------------------


def accept_ai_suggestion(
    store: Any,
    oplog: Any,
    annotation_id: UUID,
    *,
    accept: bool = True,
    actor: str = "anonymous",
) -> Annotation | None:
    """Mark an AI-generated annotation as reviewed.

    Sets confidence to 1.0 (accepted) or 0.0 (rejected) and rewrites the
    provenance ``was_generated_by`` to ``user:<actor>``. The original
    AI provenance is preserved by appending it to ``was_derived_from``
    so the audit chain stays intact.
    """
    current = get_annotation(store, annotation_id)
    if current is None:
        return None

    new_confidence = 1.0 if accept else 0.0
    derived = list(current.provenance.was_derived_from)
    new_provenance = Provenance(
        was_generated_by=f"user:{actor}",
        was_attributed_to=actor,
        was_derived_from=derived,
        generated_at_time=RationalTime.zero(),
        activity="derive",
    )
    updated = current.model_copy(
        update={"confidence": new_confidence, "provenance": new_provenance}
    )
    store.remove(current.id)
    store.add(updated)
    oplog.append(
        "update_annotation",
        target_id=str(updated.id),
        payload={"annotation": updated.model_dump(mode="json")},
        actor=actor,
    )
    return updated
