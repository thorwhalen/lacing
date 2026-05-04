"""Tests for the MCP server.

We don't spin up a real MCP transport — we exercise tools via FastMCP's
``call_tool`` API, which is what the SDK uses internally to dispatch a
JSON-RPC ``tools/call`` request to the registered Python function.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

pytest.importorskip("mcp")


from lacing.oplog import InMemoryOpLog  # noqa: E402
from lacing.server.mcp import build_mcp_server  # noqa: E402
from lacing.store import MemoryStore  # noqa: E402
from lacing.tier import Tier  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    s = MemoryStore()
    s.add_tier(Tier("words"))
    return s


@pytest.fixture
def oplog():
    return InMemoryOpLog()


@pytest.fixture
def server(store, oplog):
    return build_mcp_server(store, oplog)


async def _call(server, name: str, args: dict | None = None) -> Any:
    """Call an MCP tool by name and return the parsed result.

    FastMCP's ``call_tool`` returns ``(content_parts, structured_dict)``.
    We use the structured-dict path: it preserves Python types directly
    and wraps non-dict returns under a ``'result'`` key.
    """
    result = await server.call_tool(name, args or {})
    if isinstance(result, tuple) and len(result) == 2:
        _parts, structured = result
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured
    # Fallback for older SDK shapes: parse the first text content part.
    parts = result
    if hasattr(parts, "content"):
        parts = parts.content
    if not parts:
        return None
    text = parts[0].text if hasattr(parts[0], "text") else str(parts[0])
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


# ---------------------------------------------------------------------------
# tools registration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestToolDiscovery:
    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_lists_expected_tools(self, server):
        tools = await server.list_tools()
        names = {t.name for t in tools}
        expected = {
            "add_tier",
            "list_tiers",
            "add_annotation",
            "query_annotations",
            "get_annotation",
            "delete_annotation",
            "accept_ai_suggestion",
            "list_formats",
            "latest_clock",
            "state_at",
        }
        assert expected <= names


# ---------------------------------------------------------------------------
# tier tools
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestTierTools:
    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_list_tiers_initial(self, server):
        tiers = await _call(server, "list_tiers")
        assert any(t["name"] == "words" for t in tiers)

    async def test_add_tier(self, server, store):
        result = await _call(
            server,
            "add_tier",
            {
                "name": "phon",
                "stereotype": "TIME_SUBDIVISION",
                "parent": "words",
            },
        )
        assert result["name"] == "phon"
        assert result["stereotype"] == "TIME_SUBDIVISION"
        assert store.get_tier("phon") is not None

    async def test_add_tier_records_oplog(self, server, oplog):
        await _call(server, "add_tier", {"name": "extra"})
        assert oplog.latest_clock() == 1


# ---------------------------------------------------------------------------
# annotation tools
# ---------------------------------------------------------------------------


def _add_args(text: str = "hello", start: float = 0.0, end: float = 1.0) -> dict:
    return {
        "tier": "words",
        "asset_id": "x",
        "start_seconds": start,
        "end_seconds": end,
        "body": {"text": text},
        "body_schema_uri": "annot://schema/word/v1",
        "rate": 1000,
    }


@pytest.mark.anyio
class TestAnnotationTools:
    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_add_annotation(self, server, store):
        result = await _call(server, "add_annotation", _add_args())
        assert result["tier"] == "words"
        assert result["body"]["text"] == "hello"
        # Confirm it landed in the store.
        assert len(list(store.all())) == 1

    async def test_add_uses_seconds(self, server, store):
        await _call(server, "add_annotation", _add_args(start=0.5, end=1.5))
        ann = next(store.all())
        # Default rate is 1000 -> 500 ticks per half-second
        assert ann.interval.start.value == 500
        assert ann.interval.end.value == 1500

    async def test_query_all(self, server):
        for s, e, t in [(0.0, 1.0, "a"), (1.0, 2.0, "b"), (5.0, 6.0, "c")]:
            await _call(server, "add_annotation", _add_args(t, s, e))
        out = await _call(server, "query_annotations")
        assert len(out) == 3

    async def test_query_window_intersects(self, server):
        for s, e, t in [(0.0, 1.0, "a"), (1.0, 2.0, "b"), (5.0, 6.0, "c")]:
            await _call(server, "add_annotation", _add_args(t, s, e))
        out = await _call(
            server,
            "query_annotations",
            {"start_seconds": 0.5, "end_seconds": 1.5, "rate": 1000},
        )
        # [0,1) and [1,2) both intersect [0.5, 1.5)
        assert len(out) == 2

    async def test_query_filter_by_tier(self, server, store):
        store.add_tier(Tier("phon"))
        await _call(server, "add_annotation", _add_args("a"))
        args = _add_args("p")
        args["tier"] = "phon"
        await _call(server, "add_annotation", args)

        out = await _call(server, "query_annotations", {"tier": "phon"})
        assert len(out) == 1
        assert out[0]["tier"] == "phon"

    async def test_get_annotation(self, server):
        created = await _call(server, "add_annotation", _add_args())
        ann_id = created["id"]
        fetched = await _call(server, "get_annotation", {"annotation_id": ann_id})
        assert fetched is not None
        assert fetched["id"] == ann_id

    async def test_get_annotation_missing(self, server):
        result = await _call(
            server, "get_annotation", {"annotation_id": str(uuid4())}
        )
        # FastMCP wraps None returns; just confirm it's not a real annotation.
        assert result is None or result == "null" or result == ""

    async def test_delete_annotation(self, server, store):
        created = await _call(server, "add_annotation", _add_args())
        ann_id = created["id"]
        result = await _call(server, "delete_annotation", {"annotation_id": ann_id})
        assert result is True
        assert len(list(store.all())) == 0

    async def test_delete_missing_returns_false(self, server):
        result = await _call(
            server, "delete_annotation", {"annotation_id": str(uuid4())}
        )
        assert result is False


# ---------------------------------------------------------------------------
# AI suggestion review
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestAiSuggestion:
    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_accept_sets_confidence_to_one(self, server, store):
        # Create an annotation with low confidence (simulating an AI suggestion).
        args = _add_args()
        args["confidence"] = 0.3
        created = await _call(server, "add_annotation", args)
        ann_id = created["id"]

        result = await _call(
            server,
            "accept_ai_suggestion",
            {"annotation_id": ann_id, "accept": True, "actor": "thor"},
        )
        assert result["confidence"] == 1.0
        assert result["provenance"]["was_attributed_to"] == "thor"

    async def test_reject_sets_confidence_to_zero(self, server):
        args = _add_args()
        args["confidence"] = 0.7
        created = await _call(server, "add_annotation", args)
        ann_id = created["id"]
        result = await _call(
            server,
            "accept_ai_suggestion",
            {"annotation_id": ann_id, "accept": False, "actor": "thor"},
        )
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# time-travel tools
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestTimeTravel:
    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_latest_clock_starts_at_zero(self, server):
        clock = await _call(server, "latest_clock")
        assert clock == 0

    async def test_clock_increments_on_writes(self, server):
        await _call(server, "add_annotation", _add_args())
        clock = await _call(server, "latest_clock")
        assert clock == 1

    async def test_state_at_intermediate(self, server):
        # 1: add tier
        await _call(server, "add_tier", {"name": "phon"})
        # 2: add ann
        await _call(server, "add_annotation", _add_args("first"))
        # 3: add another
        created2 = await _call(server, "add_annotation", _add_args("second", 1.0, 2.0))
        # 4: delete second
        await _call(server, "delete_annotation", {"annotation_id": created2["id"]})

        snap3 = await _call(server, "state_at", {"clock": 3})
        texts3 = sorted(a["body"]["text"] for a in snap3["annotations"])
        assert texts3 == ["first", "second"]

        snap4 = await _call(server, "state_at", {"clock": 4})
        texts4 = [a["body"]["text"] for a in snap4["annotations"]]
        assert texts4 == ["first"]


# ---------------------------------------------------------------------------
# adapter introspection
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestAdapterIntrospection:
    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_list_formats(self, server):
        # Adapter modules need to be imported for them to register.
        import lacing.adapters.webvtt  # noqa: F401  registers

        formats = await _call(server, "list_formats")
        names = {f["name"] for f in formats}
        assert "webvtt" in names
