"""MCP (Model Context Protocol) server — agents as first-class clients.

Per BACK-DOC §3.3, agents should be able to drive lacing through the
same surface humans use. This module exposes lacing's mutation +
query operations as MCP tools, on top of the same store + op-log used
by the REST layer.

The MCP server is **separate from the FastAPI app** — it runs as its
own process. Construct one with :func:`build_mcp_server` and start it
with::

    server = build_mcp_server(store, oplog)
    server.run()  # stdio transport by default

For tests, use ``server._mcp_server.call_tool(name, args)`` (the FastMCP
internal API) — see ``tests/test_mcp.py``.

Tools exposed (all call into ``lacing.server.operations``):

    add_annotation(tier, asset_id, start_seconds, end_seconds, body,
                   body_schema_uri, ...)   -> the new annotation
    query_annotations(tier, start_seconds, end_seconds, relation,
                      rate, limit)         -> list of annotations
    get_annotation(annotation_id)          -> one or None
    delete_annotation(annotation_id)       -> bool
    accept_ai_suggestion(annotation_id, accept)  -> updated annotation
    add_tier(name, stereotype, parent, metadata)  -> the new tier
    list_tiers()                           -> list of tier dicts
    list_formats()                         -> registered adapters
    latest_clock()                         -> int
    state_at(clock)                        -> {tiers, annotations}

Optional dependency: install with ``pip install 'lacing[mcp]'``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from lacing.adapters import registered as registered_adapters
from lacing.oplog import replay
from lacing.server.operations import (
    accept_ai_suggestion as _accept_ai_suggestion,
    add_annotation_from_seconds,
    add_tier as _add_tier,
    get_annotation as _get_annotation,
    list_tiers as _list_tiers,
    query_annotations as _query_annotations,
    remove_annotation,
)


def _require_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover  — the [mcp] extra
        raise ImportError(
            "MCP server requires the mcp SDK. Install with: "
            "pip install 'lacing[mcp]'  (or directly: pip install mcp)"
        ) from exc
    return FastMCP


def build_mcp_server(
    store: Any,
    oplog: Any,
    *,
    name: str = "lacing",
    instructions: str | None = None,
):
    """Build a FastMCP server with lacing's tools registered.

    Args:
        store: An ``IntervalAnnotationStore`` (memory, sqlite, postgres).
        oplog: An ``OpLog`` (memory or sqlite).
        name: Server name advertised over MCP.
        instructions: Optional natural-language hint shown to clients.

    Returns:
        A ``FastMCP`` instance. Call ``.run()`` to start it (stdio by default).

    Side effect: importing built-in body schemas via ``lacing.bodies``
    so ``body_schema_uri`` validation works for the seed schemas.
    """
    FastMCP = _require_mcp()
    import lacing.bodies  # noqa: F401  — registers built-in body schemas

    server = FastMCP(
        name=name,
        instructions=instructions or _DEFAULT_INSTRUCTIONS,
    )

    # ------ tiers ------------------------------------------------------

    @server.tool()
    def add_tier(
        name: str,
        stereotype: str = "NONE",
        parent: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor: str = "anonymous",
    ) -> dict[str, Any]:
        """Create or update a tier."""
        tier = _add_tier(
            store,
            oplog,
            name=name,
            stereotype=stereotype,
            parent=parent,
            metadata=metadata or {},
            actor=actor,
        )
        return {
            "name": tier.name,
            "stereotype": tier.stereotype.value,
            "parent": tier.parent,
            "metadata": tier.metadata,
        }

    @server.tool()
    def list_tiers() -> list[dict[str, Any]]:
        """List every tier in the store."""
        return [
            {
                "name": t.name,
                "stereotype": t.stereotype.value,
                "parent": t.parent,
                "metadata": t.metadata,
            }
            for t in _list_tiers(store)
        ]

    # ------ annotations ------------------------------------------------

    @server.tool()
    def add_annotation(
        tier: str,
        asset_id: str,
        start_seconds: float,
        end_seconds: float,
        body: dict[str, Any],
        body_schema_uri: str = "annot://schema/word/v1",
        rate: int = 1000,
        confidence: float | None = None,
        actor: str = "anonymous",
    ) -> dict[str, Any]:
        """Create one annotation. Returns the created annotation as JSON."""
        annotation = add_annotation_from_seconds(
            store,
            oplog,
            tier=tier,
            asset_id=asset_id,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            body=body,
            body_schema_uri=body_schema_uri,
            rate=rate,
            confidence=confidence,
            actor=actor,
        )
        return annotation.model_dump(mode="json")

    @server.tool()
    def query_annotations(
        tier: str | None = None,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        relation: str = "intersects",
        rate: int = 1000,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Search annotations by tier and/or time window via Allen relations."""
        results = _query_annotations(
            store,
            tier=tier,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            relation=relation,
            rate=rate,
            limit=limit,
        )
        return [a.model_dump(mode="json") for a in results]

    @server.tool()
    def get_annotation(annotation_id: str) -> dict[str, Any] | None:
        """Fetch a single annotation by id, or None."""
        ann = _get_annotation(store, UUID(annotation_id))
        return None if ann is None else ann.model_dump(mode="json")

    @server.tool()
    def delete_annotation(annotation_id: str, actor: str = "anonymous") -> bool:
        """Remove an annotation. Returns True if it existed, False otherwise."""
        removed = remove_annotation(store, oplog, UUID(annotation_id), actor=actor)
        return removed is not None

    @server.tool()
    def accept_ai_suggestion(
        annotation_id: str,
        accept: bool = True,
        actor: str = "anonymous",
    ) -> dict[str, Any] | None:
        """Mark an AI-generated annotation as reviewed (accepted or rejected).

        Sets confidence to 1.0 / 0.0 and rewrites provenance to
        ``user:<actor>`` while preserving the original AI provenance via
        ``was_derived_from``.
        """
        updated = _accept_ai_suggestion(
            store,
            oplog,
            UUID(annotation_id),
            accept=accept,
            actor=actor,
        )
        return None if updated is None else updated.model_dump(mode="json")

    # ------ adapters / introspection ----------------------------------

    @server.tool()
    def list_formats() -> list[dict[str, Any]]:
        """List every registered I/O adapter (textgrid, webvtt, jams, ...)."""
        return [
            {
                "name": spec.name,
                "extensions": list(spec.extensions),
                "media_types": list(spec.media_types),
                "body_schema_uris": list(spec.body_schema_uris),
                "description": spec.description,
            }
            for spec in registered_adapters()
        ]

    # ------ time-travel -----------------------------------------------

    @server.tool()
    def latest_clock() -> int:
        """Highest Lamport clock currently in the op-log."""
        return oplog.latest_clock()

    @server.tool()
    def state_at(clock: int) -> dict[str, Any]:
        """Replay the op-log to ``clock`` and return a JSON snapshot."""
        snapshot = replay(oplog, until_clock=clock)
        return {
            "at_clock": clock,
            "tiers": [
                {
                    "name": t.name,
                    "stereotype": t.stereotype.value,
                    "parent": t.parent,
                    "metadata": t.metadata,
                }
                for t in snapshot.tiers()
            ],
            "annotations": [a.model_dump(mode="json") for a in snapshot.all()],
        }

    return server


_DEFAULT_INSTRUCTIONS = """\
This MCP server exposes the lacing interval-annotation system.

Times are seconds (use floats); pass `rate` to control quantization.
Allen-relation queries: intersects, during, contains, overlaps, meets,
starts, started_by, finishes, finished_by, before, after, equals,
overlapped_by, met_by.

Tools mutate a shared store and append to a per-server op-log; use
`latest_clock()` and `state_at(clock=N)` for time-travel debug.
"""
