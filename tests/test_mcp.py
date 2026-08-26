"""Tests for the MCP server.

We don't spin up a real MCP transport — we exercise tools via FastMCP's
``call_tool`` API, which is what the SDK uses internally to dispatch a
JSON-RPC ``tools/call`` request to the registered Python function.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from lacing.adapters import eaf, textgrid, web_annotation, webvtt
from lacing.oplog import InMemoryOpLog, replay
from lacing.server.operations import (
    DFLT_REVIEW_TIER,
    add_annotation_from_payload,
    get_annotation,
    query_annotations,
)
from lacing.server.mcp import _require_mcp, build_mcp_server
from lacing.store import MemoryStore
from lacing.tier import Tier

# Skip on what these tests actually need -- a usable FastMCP -- not on whether
# the `mcp` distribution is importable. Those came apart in mcp 2.0, which
# dropped the FastMCP it used to vendor: `importorskip("mcp")` still passed, so
# every test here errored at fixture setup instead of skipping.
try:
    _require_mcp()
except ImportError as exc:  # pragma: no cover - depends on the environment
    pytest.skip(f"no FastMCP implementation available: {exc}", allow_module_level=True)


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


def _structured_of(result: Any) -> tuple[bool, Any]:
    """Pull the structured payload out of a ``call_tool`` result.

    Returns ``(found, payload)`` so that a legitimately ``None`` payload is not
    confused with "this shape carries no structured content".

    The shape depends on which SDK answered :func:`_require_mcp`:

    - ``fastmcp`` (>=3) returns a ``ToolResult`` with ``.structured_content``
    - the ``mcp`` SDK (<2) returns a ``(content_parts, structured_dict)`` tuple

    Preferring structured content over the text parts matters: the text path is
    lossy (everything arrives as ``str`` and has to be guessed back through
    ``json.loads``), whereas structured content preserves the Python types the
    tool actually returned.
    """
    if hasattr(result, "structured_content"):  # fastmcp >= 3
        return True, result.structured_content
    if isinstance(result, tuple) and len(result) == 2:  # mcp < 2
        return True, result[1]
    return False, None


async def _call(server, name: str, args: dict | None = None) -> Any:
    """Call an MCP tool by name and return the parsed result.

    Both supported SDKs wrap a non-dict return under a ``'result'`` key, which
    is unwrapped here so tests assert on what the tool returned rather than on
    the transport's packaging.
    """
    result = await server.call_tool(name, args or {})

    found, structured = _structured_of(result)
    if found:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured

    # Last resort for an SDK shape we don't know: parse the first text part.
    parts = getattr(result, "content", result)
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


AI_PROVENANCE = {
    "was_generated_by": "agent:flux@9f2c1d",
    "was_attributed_to": "acme-labs",
    "was_derived_from": [],
    "generated_at_time": {"v": 1, "r": 1},
    "activity": "infer",
}
"""An annotation an agent produced. The two strings are what lacing#18
destroyed, so the guards below assert on them verbatim."""


_TIMELINE_DUMPERS = {
    "webvtt": webvtt.dump,
    "textgrid": textgrid.dump,
    "web_annotation": web_annotation.dump,
}
"""Adapters that serialize only *records* placed on a media timeline. A
review is a verdict, not a moment, so none of these may change when one is
recorded. ``eaf`` is deliberately absent: it also serializes the tier
*list*, so it legitimately gains an empty ``<TIER>`` -- checked separately
below, where the assertion is about annotations rather than bytes."""


def _without_reviews(store):
    """A copy of ``store`` with the review tier and its annotations removed.

    The baseline every export assertion compares against, so the comparison
    isolates the *review's* contribution rather than the whole operation's."""
    stripped = MemoryStore()
    for tier in store.tiers():
        if tier.name != DFLT_REVIEW_TIER:
            stripped.add_tier(tier)
    for ann in store.all():
        if ann.tier != DFLT_REVIEW_TIER:
            stripped.add(ann)
    return stripped


def _add_ai_suggestion(store, oplog, *, confidence: float = 0.3):
    """Put an AI-generated annotation in the store, provenance and all.

    Not via the ``add_annotation`` MCP tool: that tool synthesises
    ``server:lacing`` provenance, so a test built on it could not tell a
    preserved agent tag from a regenerated one.
    """
    return add_annotation_from_payload(
        store,
        oplog,
        tier="words",
        reference={
            "kind": "media",
            "asset_id": "sha256:deadbeef",
            "interval": {"start": {"v": 0, "r": 1000}, "end": {"v": 500, "r": 1000}},
        },
        body={"text": "maybe"},
        body_schema_uri="annot://schema/word/v1",
        provenance=AI_PROVENANCE,
        confidence=confidence,
    )


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
        assert result["annotation"]["confidence"] == 1.0
        assert result["review"]["provenance"]["was_attributed_to"] == "thor"

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
        assert result["annotation"]["confidence"] == 0.0
        assert result["review"]["body"]["decision"] == "rejected"

    async def test_review_records_the_review_time_not_tick_zero(self, server):
        """lacing#18 Bug B: ``generated_at_time`` must be when the review
        happened. It used to be ``RationalTime.zero()`` — every review at
        tick 0, and older-than-everything to any consumer ordering by it."""
        from lacing.time import RationalTime

        before = RationalTime.now().to_seconds()
        created = await _call(server, "add_annotation", _add_args())

        result = await _call(
            server,
            "accept_ai_suggestion",
            {"annotation_id": created["id"], "accept": True, "actor": "thor"},
        )

        wire = result["review"]["provenance"]["generated_at_time"]
        reviewed_at = wire["v"] / wire["r"]
        assert reviewed_at >= before > 0

    async def test_accept_preserves_the_original_ai_provenance(
        self, server, store, oplog
    ):
        """lacing#18 Bug A: reviewing must not rewrite who generated the
        annotation. The agent tag and its attribution are asserted as
        strings, recovered from the store *after* the review — a
        non-emptiness check would have passed against the old code too."""
        suggestion = _add_ai_suggestion(store, oplog)

        await _call(
            server,
            "accept_ai_suggestion",
            {"annotation_id": str(suggestion.id), "accept": True, "actor": "thor"},
        )

        recovered = get_annotation(store, suggestion.id)
        assert recovered is not None
        assert recovered.id == suggestion.id
        assert recovered.confidence == 1.0
        assert recovered.provenance.was_generated_by == "agent:flux@9f2c1d"
        assert recovered.provenance.was_attributed_to == "acme-labs"
        assert recovered.provenance.activity == "infer"

    async def test_the_review_is_its_own_attributed_standoff_record(
        self, server, store, oplog
    ):
        """The human edit is attributed — on its own annotation, pointing
        at the one it judged, on a tier of its own so it never turns up in
        a query for the content it reviewed."""
        suggestion = _add_ai_suggestion(store, oplog)

        result = await _call(
            server,
            "accept_ai_suggestion",
            {"annotation_id": str(suggestion.id), "accept": True, "actor": "thor"},
        )

        review = result["review"]
        assert review["tier"] == DFLT_REVIEW_TIER
        assert review["body_schema_uri"] == "annot://schema/review/v1"
        assert review["body"]["review_kind"] == "approval"
        assert review["body"]["decision"] == "accepted"
        assert review["body"]["target_annotation_ids"] == [str(suggestion.id)]
        assert review["reference"]["kind"] == "annotation"
        assert review["reference"]["target_id"] == str(suggestion.id)
        assert review["provenance"]["was_generated_by"] == "user:thor"
        assert review["provenance"]["was_attributed_to"] == "thor"
        assert review["provenance"]["was_derived_from"] == [str(suggestion.id)]

        # The reviewed tier still holds exactly the one annotation.
        words = await _call(server, "query_annotations", {"tier": "words"})
        assert [a["id"] for a in words] == [str(suggestion.id)]

    async def test_the_review_is_durable_not_just_returned(self, server, store, oplog):
        """The returned payload is a *view*; the audit record is what is in
        the store, on a registered tier, in the op-log.

        Asserting on ``result["review"]`` alone leaves all three unguarded:
        the function can fabricate a review, hand it to the caller and
        persist nothing, and every other test here still passes. Each
        assertion below is red under exactly one deletion — ``store.add``,
        the ``add_tier`` block, the review's ``oplog.append``.
        """
        suggestion = _add_ai_suggestion(store, oplog)

        result = await _call(
            server,
            "accept_ai_suggestion",
            {"annotation_id": str(suggestion.id), "accept": True, "actor": "thor"},
        )
        review_id = UUID(result["review"]["id"])

        # 1. Persisted in the store, not merely returned.
        stored = get_annotation(store, review_id)
        assert stored is not None
        assert stored.tier == DFLT_REVIEW_TIER
        assert stored.body["decision"] == "accepted"
        assert stored.provenance.was_attributed_to == "thor"

        # 2. The review tier is registered, so tier-driven consumers
        #    (``list_tiers``, the EAF/TextGrid exporters) can see it exists.
        assert store.get_tier(DFLT_REVIEW_TIER) is not None
        tiers = await _call(server, "list_tiers")
        assert DFLT_REVIEW_TIER in [t["name"] for t in tiers]

        # 3. In the op-log, so ``replay`` / ``state_at`` reconstruct it.
        #    Without this the attribution silently vanishes from every
        #    time-travel surface.
        logged = [(e.operation, e.target_id) for e in oplog.entries()]
        assert ("add_annotation", str(review_id)) in logged
        assert ("add_tier", DFLT_REVIEW_TIER) in logged
        rebuilt = replay(oplog)
        replayed = get_annotation(rebuilt, review_id)
        assert replayed is not None
        assert replayed.provenance.was_generated_by == "user:thor"
        assert rebuilt.get_tier(DFLT_REVIEW_TIER) is not None

    async def test_the_review_has_no_place_on_the_media_timeline(
        self, server, store, oplog
    ):
        """A verdict about a whole annotation is timeless.

        ``AnnotationRef.interval`` means "a sub-interval of the target".
        Filling it with the target's own interval put the review at the
        reviewed annotation's exact timestamps, so an untiered interval
        query returned it next to the content it judges and every
        interval-driven adapter emitted a blank record there — a duplicate
        empty WebVTT cue, a phantom TextGrid tier, a Web-Annotation item
        targeting ``web-annotation:unspecified``.
        """
        suggestion = _add_ai_suggestion(store, oplog)
        assert suggestion.interval is not None

        await _call(
            server,
            "accept_ai_suggestion",
            {"annotation_id": str(suggestion.id), "accept": True, "actor": "thor"},
        )

        # The reference names the target and nothing else.
        stored_reviews = [a for a in store.all() if a.tier == DFLT_REVIEW_TIER]
        assert len(stored_reviews) == 1
        assert stored_reviews[0].reference.interval is None
        assert stored_reviews[0].interval is None

        # An untiered interval query over the reviewed span returns the
        # content only -- this is the query mode the MCP tool defaults to.
        hits = query_annotations(store, start_seconds=0.0, end_seconds=0.5)
        assert [a.tier for a in hits] == ["words"]

        # Exports contribute nothing for the review. Compared against the
        # same store with the review stripped out, NOT against a snapshot
        # taken before the accept -- the accept legitimately moves
        # ``confidence``, and an adapter that starts exporting that should
        # not redden this guard for an unrelated reason.
        without = _without_reviews(store)
        for name, dump in _TIMELINE_DUMPERS.items():
            assert dump(store) == dump(without), f"{name} gained a record"

        # EAF is the one format that also serializes the *tier list*, so
        # registering ``review`` shows up there. That is a declaration, not
        # a record: an empty <TIER>, and not one new <ANNOTATION>.
        eaf_with, eaf_without = eaf.dump(store), eaf.dump(without)
        assert eaf_with.count(b"<ANNOTATION>") == eaf_without.count(b"<ANNOTATION>")
        assert b'<TIER TIER_ID="review" LINGUISTIC_TYPE_REF="default-lt" />' in eaf_with

    async def test_missing_annotation_returns_none(self, server):
        result = await _call(
            server,
            "accept_ai_suggestion",
            {"annotation_id": str(uuid4()), "accept": True},
        )
        assert result is None or result == "null" or result == ""


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
