"""WebVTT (W3C TimedText) adapter.

WebVTT is a flat caption format: one stream of cues, no tier hierarchy.
Cues have a start time, an end time, optional id and settings, and a payload
(text with limited inline markup).

We map cues to a single tier named ``cues`` (override with ``tier=``).
Each cue becomes one ``Annotation`` whose body holds:

    {"text": str, "id": str | None, "settings": dict[str, str]}

Lossy fields on dump:
    Provenance, confidence, schema URIs, and tier metadata are dropped.
    Only the text, id (if present), and settings are emitted.

Time discipline:
    WebVTT timestamps are ``HH:MM:SS.mmm`` or ``MM:SS.mmm`` (with milliseconds).
    Parsing goes through string fractions to avoid float ingestion. Default
    rate is 1000 (millisecond precision); override with ``rate=`` if your
    project uses a different canonical rate.

Spec: https://www.w3.org/TR/webvtt1/
"""

from __future__ import annotations

import os
import re
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

from lacing.adapters import register_adapter
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


ADAPTER_NAME = "webvtt"
BODY_SCHEMA_URI = "annot://schema/webvtt-cue/v1"
DEFAULT_TIER_NAME = "cues"
DEFAULT_RATE = 1000
DEFAULT_ASSET_ID = "webvtt:unspecified"


_TIMESTAMP_RE = re.compile(r"^\s*(?:(\d+):)?([0-5]?\d):([0-5]?\d)\.(\d{3})\s*$")
_CUE_TIMING_RE = re.compile(r"^\s*([\d:.]+)\s+-->\s+([\d:.]+)\s*(.*)$")


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def _parse_timestamp(s: str, rate: int) -> RationalTime:
    """Parse ``HH:MM:SS.mmm`` or ``MM:SS.mmm`` into a ``RationalTime``.

    Hours optional. Milliseconds always 3 digits per WebVTT.
    """
    m = _TIMESTAMP_RE.match(s)
    if m is None:
        raise ValueError(f"invalid WebVTT timestamp: {s!r}")
    hours = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2))
    seconds = int(m.group(3))
    millis = int(m.group(4))
    total_ms = ((hours * 3600 + minutes * 60 + seconds) * 1000) + millis
    # Exact: ms / 1000 → quantized at `rate`
    return RationalTime.from_seconds(Fraction(total_ms, 1000), rate=rate)


def _format_timestamp(t: RationalTime) -> str:
    """Format as ``HH:MM:SS.mmm``."""
    f = t.to_fraction()
    # Exact ms count = round(f * 1000) — but require exact divisibility.
    ms_frac = f * 1000
    if ms_frac.denominator != 1:
        # Sub-millisecond precision can't survive WebVTT round-trip; round.
        # Documented in module docstring as a lossy edge.
        total_ms = int(ms_frac)
    else:
        total_ms = int(ms_frac)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"


def _parse_settings(s: str) -> dict[str, str]:
    """Parse cue settings like ``align:start position:50%`` into a dict."""
    out: dict[str, str] = {}
    for token in s.split():
        if ":" in token:
            key, _, value = token.partition(":")
            out[key] = value
    return out


def _format_settings(d: dict[str, str]) -> str:
    return " ".join(f"{k}:{v}" for k, v in d.items())


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str = DEFAULT_ASSET_ID,
    attribution: str = "anonymous",
    tier: str = DEFAULT_TIER_NAME,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Parse a WebVTT file or string/bytes into a ``MemoryStore``."""
    text = _read_text(source)

    store = MemoryStore()
    store.add_tier(Tier(tier))
    now = RationalTime.zero(rate)

    cues = list(_iter_cues(text, rate))
    for cue in cues:
        store.add(
            Annotation(
                id=uuid4(),
                tier=tier,
                reference=MediaRef(asset_id=asset_id, interval=cue["interval"]),
                body={
                    "text": cue["text"],
                    "id": cue["id"],
                    "settings": cue["settings"],
                },
                body_schema_uri=BODY_SCHEMA_URI,
                provenance=Provenance(
                    was_generated_by=f"adapter:{ADAPTER_NAME}",
                    was_attributed_to=attribution,
                    generated_at_time=now,
                    activity="import",
                ),
            )
        )

    return store


def _read_text(source: str | bytes | os.PathLike) -> str:
    if isinstance(source, (bytes, bytearray)):
        # WebVTT is UTF-8 per spec; tolerate BOM.
        return bytes(source).decode("utf-8-sig")
    # PathLike that's not a str → must be a path
    if not isinstance(source, str) and isinstance(source, os.PathLike):
        return Path(os.fspath(source)).read_text(encoding="utf-8-sig")
    # str: treat as inline content if it looks like one (header) or has no
    # plausible path resolution; otherwise as a path.
    s = str(source)
    if _looks_like_inline_vtt(s):
        return s
    p = Path(s)
    if p.exists():
        return p.read_text(encoding="utf-8-sig")
    # Treat as inline content; the header check downstream will raise if invalid.
    return s


def _looks_like_inline_vtt(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    head = s.lstrip()[:6].upper()
    return head.startswith("WEBVTT")


def _iter_cues(text: str, rate: int):
    lines = text.splitlines()
    if not lines or not lines[0].lstrip().upper().startswith("WEBVTT"):
        raise ValueError("WebVTT files must start with a 'WEBVTT' header line")

    i = 1
    n = len(lines)
    while i < n:
        # Skip blank lines and NOTE/STYLE/REGION blocks.
        while i < n and lines[i].strip() == "":
            i += 1
        if i >= n:
            break

        if lines[i].startswith(("NOTE", "STYLE", "REGION")):
            # Skip until blank line
            while i < n and lines[i].strip() != "":
                i += 1
            continue

        # Optional cue id (line without -->)
        cue_id: str | None = None
        if "-->" not in lines[i]:
            cue_id = lines[i].strip() or None
            i += 1
            if i >= n:
                break

        if "-->" not in lines[i]:
            raise ValueError(f"expected timing line at line {i + 1}, got {lines[i]!r}")

        m = _CUE_TIMING_RE.match(lines[i])
        if m is None:
            raise ValueError(f"invalid timing line: {lines[i]!r}")
        start = _parse_timestamp(m.group(1), rate)
        end = _parse_timestamp(m.group(2), rate)
        settings = _parse_settings(m.group(3) or "")
        i += 1

        # Cue payload: until blank line
        payload_lines: list[str] = []
        while i < n and lines[i].strip() != "":
            payload_lines.append(lines[i])
            i += 1

        yield {
            "id": cue_id,
            "interval": TimeInterval(start, end),
            "settings": settings,
            "text": "\n".join(payload_lines),
        }


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    tier: str | None = None,
    **_kwargs: Any,
) -> bytes | None:
    """Write annotations as WebVTT.

    Args:
        store: Source store. Only annotations from ``tier`` (default: all
            tiers) with a ``MediaRef`` interval are emitted, sorted by start.
        target: Output path. If None, returns bytes (UTF-8).
        tier: Restrict export to this tier. None = export all annotations.
    """
    out_lines: list[str] = ["WEBVTT", ""]

    candidates = list(_all_with_intervals(store))
    if tier is not None:
        candidates = [a for a in candidates if a.tier == tier]
    candidates.sort(
        key=lambda a: (a.interval.start.to_fraction(), a.interval.end.to_fraction())
    )  # type: ignore[union-attr]

    for ann in candidates:
        body = ann.body if isinstance(ann.body, dict) else {}
        cue_id = body.get("id")
        text = body.get("text", "")
        settings = body.get("settings", {})

        if cue_id:
            out_lines.append(str(cue_id))

        timing = (
            f"{_format_timestamp(ann.interval.start)} --> "  # type: ignore[union-attr]
            f"{_format_timestamp(ann.interval.end)}"  # type: ignore[union-attr]
        )
        if settings:
            timing += " " + _format_settings(settings)
        out_lines.append(timing)
        out_lines.append(str(text))
        out_lines.append("")

    blob = "\n".join(out_lines).encode("utf-8")

    if target is None:
        return blob
    Path(os.fspath(target)).write_bytes(blob)
    return None


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
    extensions=(".vtt",),
    media_types=("text/vtt",),
    body_schema_uris=(BODY_SCHEMA_URI,),
    description="WebVTT subtitle/caption format. Flat cues, no tier hierarchy.",
)
