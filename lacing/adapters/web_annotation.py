"""W3C Web Annotation Data Model adapter (JSON-LD).

W3C Web Annotation is the closest thing to a universal annotation standard
[ANN-DOC §A]. Each annotation is a JSON-LD object with ``body``, ``target``,
``creator``, ``created``, and a ``motivation``.

We map W3C annotations onto lacing's envelope as follows:

    target.source                   -> MediaRef.asset_id
    target.selector (FragmentSelector with t=...) -> MediaRef.interval (or point)
    body                            -> Annotation.body['body'] (passthrough)
    motivation                      -> Annotation.body['motivation']
    creator (string or dict)        -> Provenance.was_attributed_to
    created (xsd:dateTime ISO 8601) -> preserved in body['created'] as string
                                       (cannot be exact in RationalTime)
    Annotation.tier                 -> body['tier'] OR mapped from motivation

We support the **Media Fragment URI** time selector ``#t=<start>,<end>`` per
W3C Media Fragments spec (https://www.w3.org/TR/media-frags/). Times are
parsed as decimal seconds via ``Fraction(str)``.

Lossy fields:
    - W3C ``created`` is xsd:dateTime — kept as a string in the body, not
      mapped to ``Provenance.generated_at_time``.
    - Multi-target annotations: only the first target is honored.
    - Selectors other than FragmentSelector with ``t=`` and TextQuoteSelector
      are preserved verbatim in body['selector'] but not interpreted.

Spec: https://www.w3.org/TR/annotation-model/
"""

from __future__ import annotations

import json
import os
import re
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from lacing.adapters import register_adapter
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


ADAPTER_NAME = "web_annotation"
BODY_SCHEMA_URI = "annot://schema/web-annotation/v1"
DEFAULT_RATE = 1000
DEFAULT_TIER_NAME = "annotations"
DEFAULT_ASSET_ID = "web-annotation:unspecified"

CONTEXT = "http://www.w3.org/ns/anno.jsonld"


_TIME_FRAGMENT_RE = re.compile(r"#t=([\d.]+)(?:,([\d.]+))?")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_time_fragment(
    selector_value: str, rate: int
) -> TimeInterval | None:
    """Parse a Media Fragment time selector value like ``t=1.5,3.0`` or ``t=2``.

    Tolerates leading ``#`` (URL fragment) and ``npt:`` prefix on the value.
    """
    s = selector_value.strip()
    if s.startswith("#"):
        s = s[1:]
    if s.startswith("t="):
        s = s[2:]
    if s.startswith("npt:"):
        s = s[4:]
    parts = s.split(",")
    if len(parts) == 1:
        t = RationalTime.from_seconds(Fraction(parts[0]), rate=rate)
        return TimeInterval.point(t)
    if len(parts) == 2:
        start = RationalTime.from_seconds(Fraction(parts[0]), rate=rate)
        end = RationalTime.from_seconds(Fraction(parts[1]), rate=rate)
        return TimeInterval(start, end)
    return None


def _format_time_fragment(interval: TimeInterval) -> str:
    """Format a ``TimeInterval`` as a Media Fragment time selector value."""
    start = interval.start.to_fraction()
    end = interval.end.to_fraction()
    if interval.is_point:
        return f"t={_fmt_seconds(start)}"
    return f"t={_fmt_seconds(start)},{_fmt_seconds(end)}"


def _fmt_seconds(f: Fraction) -> str:
    """Format a fraction of seconds as a decimal string, no trailing zeros."""
    if f.denominator == 1:
        return str(int(f))
    # Use enough decimals to be exact: if denominator is a power of 2*5,
    # the decimal terminates. Else fall back to a 6-decimal approximation.
    s = f"{float(f):.6f}".rstrip("0").rstrip(".")
    return s


def _extract_target_info(target: Any, rate: int) -> tuple[str, TimeInterval | None, dict | None]:
    """Pull ``(source, interval, raw_selector)`` out of a W3C target.

    ``target`` may be a string (URL — interval is None) or a dict.
    """
    if isinstance(target, str):
        # URL with optional fragment
        m = _TIME_FRAGMENT_RE.search(target)
        if m:
            base = target[: m.start()]
            iv = _parse_time_fragment(target[m.start():], rate)
            return base, iv, None
        return target, None, None

    if not isinstance(target, dict):
        return DEFAULT_ASSET_ID, None, None

    source = target.get("source") or target.get("id") or DEFAULT_ASSET_ID
    if isinstance(source, dict):
        source = source.get("id", DEFAULT_ASSET_ID)

    selector = target.get("selector")
    raw_selector = None
    iv: TimeInterval | None = None

    if isinstance(selector, dict):
        sel_type = selector.get("type")
        sel_value = selector.get("value", "")
        if sel_type in ("FragmentSelector", "MediaFragmentSelector") and sel_value:
            iv = _parse_time_fragment(sel_value, rate)
        else:
            raw_selector = selector
    elif isinstance(selector, list):
        # Pick the first FragmentSelector; preserve the rest.
        remaining: list = []
        for s in selector:
            if isinstance(s, dict) and s.get("type") in (
                "FragmentSelector",
                "MediaFragmentSelector",
            ) and iv is None:
                iv = _parse_time_fragment(s.get("value", ""), rate)
            else:
                remaining.append(s)
        if remaining:
            raw_selector = remaining

    return str(source), iv, raw_selector


def _extract_creator(creator: Any) -> str:
    if creator is None:
        return "anonymous"
    if isinstance(creator, str):
        return creator
    if isinstance(creator, dict):
        return creator.get("id") or creator.get("name") or "anonymous"
    return "anonymous"


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str | None = None,
    tier: str = DEFAULT_TIER_NAME,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Load a W3C Web Annotation document into a ``MemoryStore``.

    Accepts a single annotation, an AnnotationCollection/AnnotationPage
    (``items``), or a JSON list at the top level.

    Args:
        source: Path, bytes, or JSON string.
        rate: Quantization rate.
        asset_id: Override target source for all annotations. None = use
            each annotation's own ``target.source``.
        tier: Tier name to assign annotations that have no explicit
            ``body['tier']`` value.
    """
    data = _load_json(source)

    items: list[dict]
    if isinstance(data, dict):
        if "items" in data and isinstance(data["items"], list):
            items = data["items"]
        elif data.get("type") in ("Annotation", ["Annotation"]):
            items = [data]
        else:
            items = [data]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"unsupported W3C document shape: {type(data).__name__}")

    store = MemoryStore()
    seen_tiers: set[str] = set()
    now = RationalTime.zero(rate)

    for item in items:
        target_source, interval, raw_selector = _extract_target_info(
            item.get("target"), rate=rate
        )
        if asset_id is not None:
            target_source = asset_id
        if interval is None:
            # Skip annotations without a time fragment — Phase 0 is time-based.
            # Future: support text-based selectors via NodeRef.
            continue

        body_value = item.get("body")
        motivation = item.get("motivation")
        ann_id = _coerce_uuid(item.get("id"))
        creator = _extract_creator(item.get("creator"))
        created = item.get("created")  # ISO 8601 string preserved verbatim
        ann_tier = (
            (body_value.get("tier") if isinstance(body_value, dict) else None)
            or item.get("tier")
            or tier
        )

        if ann_tier not in seen_tiers:
            store.add_tier(Tier(ann_tier))
            seen_tiers.add(ann_tier)

        body: dict[str, Any] = {"body": body_value, "motivation": motivation}
        if created is not None:
            body["created"] = created
        if raw_selector is not None:
            body["selector"] = raw_selector

        store.add(
            Annotation(
                id=ann_id,
                tier=ann_tier,
                reference=MediaRef(asset_id=target_source, interval=interval),
                body=body,
                body_schema_uri=BODY_SCHEMA_URI,
                provenance=Provenance(
                    was_generated_by=f"adapter:{ADAPTER_NAME}",
                    was_attributed_to=creator,
                    generated_at_time=now,
                    activity="import",
                ),
            )
        )

    return store


def _load_json(source: str | bytes | os.PathLike) -> Any:
    if isinstance(source, (bytes, bytearray)):
        return json.loads(bytes(source).decode("utf-8"))
    if not isinstance(source, str) and isinstance(source, os.PathLike):
        return json.loads(Path(os.fspath(source)).read_text(encoding="utf-8"))
    s = str(source)
    stripped = s.lstrip()
    if stripped.startswith(("{", "[")):
        return json.loads(s)
    p = Path(s)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return json.loads(s)


def _coerce_uuid(value: Any) -> UUID:
    """Try to coerce an id value to UUID; if it fails, fall back to ``uuid4()``.

    W3C ids are URIs, not UUIDs, so most real-world docs will fall through.
    """
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return uuid4()
    return uuid4()


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    as_collection: bool = True,
    pretty: bool = True,
    **_kwargs: Any,
) -> bytes | None:
    """Serialize ``store`` as W3C Web Annotation JSON-LD.

    Args:
        store: Source store. Only annotations with a ``MediaRef`` interval
            are exported.
        target: Output path. None = return bytes.
        as_collection: If True, wrap output as an ``AnnotationCollection``
            with an ``items`` array. If False and the store has a single
            annotation, emit it bare.
        pretty: Pretty-print with 2-space indent.
    """
    items: list[dict] = []
    for ann in _all_with_intervals(store):
        items.append(_annotation_to_jsonld(ann))

    if not as_collection and len(items) == 1:
        out_obj: Any = items[0]
    else:
        out_obj = {
            "@context": CONTEXT,
            "type": "AnnotationCollection",
            "total": len(items),
            "items": items,
        }

    indent = 2 if pretty else None
    blob = json.dumps(out_obj, indent=indent, ensure_ascii=False).encode("utf-8")

    if target is None:
        return blob
    Path(os.fspath(target)).write_bytes(blob)
    return None


def _annotation_to_jsonld(ann: Annotation) -> dict:
    body = ann.body if isinstance(ann.body, dict) else {}
    interval = ann.interval

    if interval is None:  # pragma: no cover  — _all_with_intervals filters
        raise RuntimeError("annotation has no interval — should have been filtered")

    asset_id = (
        ann.reference.asset_id  # type: ignore[union-attr]
        if hasattr(ann.reference, "asset_id")
        else DEFAULT_ASSET_ID
    )

    target_obj: dict[str, Any] = {
        "source": asset_id,
        "selector": {
            "type": "FragmentSelector",
            "conformsTo": "http://www.w3.org/TR/media-frags/",
            "value": _format_time_fragment(interval),
        },
    }

    out: dict[str, Any] = {
        "@context": CONTEXT,
        "id": f"urn:uuid:{ann.id}",
        "type": "Annotation",
        "target": target_obj,
    }

    if body.get("body") is not None:
        out["body"] = body["body"]
    if body.get("motivation") is not None:
        out["motivation"] = body["motivation"]
    if body.get("created") is not None:
        out["created"] = body["created"]
    if body.get("selector") is not None:
        # Merge preserved-but-uninterpreted selectors back in
        existing = out["target"]["selector"]
        out["target"]["selector"] = [existing] + (
            body["selector"] if isinstance(body["selector"], list) else [body["selector"]]
        )

    out["creator"] = ann.provenance.was_attributed_to

    # Always emit the lacing tier so round-trips preserve it.
    out["tier"] = ann.tier

    return out


def _all_with_intervals(store: IntervalAnnotationStore):
    iter_all = getattr(store, "all", None)
    if callable(iter_all):
        for a in iter_all():
            if a.interval is not None:
                yield a
        return
    for key in store:  # type: ignore[attr-defined]
        for a in store[key]:  # type: ignore[index]
            if a.interval is not None:
                yield a


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


register_adapter(
    name=ADAPTER_NAME,
    load=load,
    dump=dump,
    extensions=(".jsonld", ".json"),
    media_types=("application/ld+json",),
    body_schema_uris=(BODY_SCHEMA_URI,),
    description=(
        "W3C Web Annotation Data Model (JSON-LD). Supports media-fragment time "
        "selectors. Lossy: created is preserved as ISO string only, "
        "non-fragment selectors preserved verbatim but not interpreted."
    ),
)
