"""Op-log + time-travel endpoints.

    GET   /oplog                 list entries (filterable by clock range)
    GET   /oplog/latest-clock    integer current clock value
    GET   /state-at?clock=N      replay log up to clock N and return a snapshot

The ``state-at`` endpoint is the killer-debug feature called out in
BACK-DOC §4.7: it lets you reproduce the system's state at any past
clock value, useful for incident response and "what did this look like
before X?" debugging.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from lacing.oplog import replay
from lacing.server.deps import get_oplog


router = APIRouter(tags=["oplog"])


@router.get("/oplog/latest-clock")
def latest_clock(oplog=Depends(get_oplog)) -> dict[str, int]:
    """Return the highest clock value currently in the op-log."""
    return {"clock": oplog.latest_clock()}


@router.get("/oplog")
def list_oplog(
    from_clock: int | None = Query(
        None, ge=1, description="Inclusive lower bound on clock."
    ),
    until_clock: int | None = Query(
        None, ge=1, description="Inclusive upper bound on clock."
    ),
    limit: int = Query(1000, ge=1, le=100_000),
    oplog=Depends(get_oplog),
) -> list[dict[str, Any]]:
    """List op-log entries, oldest first, optionally bounded by clock."""
    out: list[dict[str, Any]] = []
    for entry in oplog.entries(from_clock=from_clock, until_clock=until_clock):
        if len(out) >= limit:
            break
        out.append(entry.to_dict())
    return out


@router.get("/state-at")
def state_at(
    clock: int = Query(
        ..., ge=0, description="Replay up to (and including) this clock."
    ),
    oplog=Depends(get_oplog),
) -> dict[str, Any]:
    """Replay the op-log up to ``clock`` and return a JSON snapshot.

    The result has the shape::

        {
          "at_clock": <int>,
          "tiers": [...],
          "annotations": [...],
        }

    Stores referenced by ``add_tier`` whose parent isn't yet present, or
    annotations whose tier isn't yet declared, are silently dropped during
    replay (see :func:`lacing.oplog.replay`).
    """
    if clock > oplog.latest_clock():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"clock {clock} is beyond the latest clock {oplog.latest_clock()}",
        )

    snapshot = replay(oplog, until_clock=clock)
    tiers = [
        {
            "name": t.name,
            "stereotype": t.stereotype.value,
            "parent": t.parent,
            "metadata": t.metadata,
        }
        for t in snapshot.tiers()
    ]
    annotations = [a.model_dump(mode="json") for a in snapshot.all()]
    return {
        "at_clock": clock,
        "tiers": tiers,
        "annotations": annotations,
    }
