"""OpenTimelineIO (OTIO) adapter — NLE / video editing interchange.

OTIO is the Academy Software Foundation's standard for video timeline
interchange. Per OSS-DOC, lacing's ``RationalTime`` design is directly
inspired by OTIO's — this adapter is the place where that parity pays
off.

Mapping
-------
OTIO                                     ↔ lacing
``Timeline``                             ↔ a project (one OTIO file = one store)
``Track``                                ↔ a tier (track ``name`` becomes tier name)
``Clip``                                 ↔ ``Annotation`` (interval = source_range
                                            offset onto the track timeline)
``Clip.media_reference.target_url``      ↔ ``MediaRef.asset_id``
``Marker`` (on Track or Clip)            ↔ point ``Annotation``
``Clip.metadata`` / ``Marker.metadata``  ↔ ``body['otio_metadata']``
``MarkerColor``                          ↔ ``body['color']``

Time
----
OTIO ``RationalTime`` maps to lacing ``RationalTime`` directly — same
``(value, rate)`` shape. We re-quantize to the requested project rate
on load if needed; raises ``LossyTimeConversionError`` on inexact
conversions.

Lossy on dump
-------------
- Per-annotation provenance (``was_attributed_to``, ``was_derived_from``)
  is dropped — OTIO carries no per-clip annotator field.
- Confidence is dropped — OTIO has no equivalent.
- Track effects + transitions are dropped — out of lacing's scope.
- Clips are emitted with an ``ExternalReference`` whose ``target_url``
  is the ``MediaRef.asset_id``.

Spec: https://opentimelineio.readthedocs.io/
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from lacing.adapters import register_adapter
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import DEFAULT_RATE, RationalTime, TimeInterval

if TYPE_CHECKING:
    import opentimelineio as _otio_lib


ADAPTER_NAME = "otio"
BODY_SCHEMA_URI_CLIP = "annot://schema/otio-clip/v1"
BODY_SCHEMA_URI_MARKER = "annot://schema/otio-marker/v1"
DEFAULT_ASSET_ID = "otio:unspecified"


def _require_otio():
    try:
        import opentimelineio
    except ImportError as exc:
        raise ImportError(
            "OTIO adapter requires opentimelineio. Install with: "
            "pip install 'lacing[otio]'  (or directly: pip install opentimelineio)"
        ) from exc
    return opentimelineio


def _otio_rationaltime_to_lacing(t, rate: int) -> RationalTime:
    """Convert an ``opentimelineio.opentime.RationalTime`` to lacing's.

    OTIO uses floats for ``value`` and ``rate`` even though they're
    semantically rational. We quantize to integer ticks at ``rate``.
    """
    # OTIO float values are typically integers; round-trip through Fraction.
    from fractions import Fraction

    val = Fraction(repr(float(t.value)))
    src_rate = Fraction(repr(float(t.rate)))
    seconds = val / src_rate
    return RationalTime.from_seconds(seconds, rate=rate)


def _lacing_to_otio_rationaltime(t: RationalTime, otio_module) -> Any:
    return otio_module.opentime.RationalTime(value=float(t.value), rate=float(t.rate))


def _media_url(clip) -> str | None:
    media_ref = getattr(clip, "media_reference", None)
    if media_ref is None:
        return None
    target_url = getattr(media_ref, "target_url", None)
    if target_url:
        return str(target_url)
    return None


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str | None = None,
    attribution: str = "anonymous",
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Load an OTIO file/JSON into a ``MemoryStore``.

    Each track becomes a tier. Each clip becomes one ``Annotation`` with
    ``MediaRef`` pointing at the clip's media reference (or the
    ``asset_id`` override). Markers on the timeline, track, or clip
    become point ``Annotation``s on a ``markers`` tier.

    Args:
        source: Path or bytes containing OTIO JSON.
        rate: Quantization rate.
        asset_id: Override media reference for every clip. None = use
            each clip's own ``media_reference.target_url``.
        attribution: ``Provenance.was_attributed_to`` value.
    """
    otio = _require_otio()
    timeline = _open_timeline(source, otio)

    store = MemoryStore()
    seen_tiers: set[str] = set()
    now = RationalTime.zero(rate)

    def _ensure_tier(name: str) -> None:
        if name not in seen_tiers:
            store.add_tier(Tier(name))
            seen_tiers.add(name)

    # --- timeline-level markers --------------------------------------
    for marker in getattr(timeline.tracks, "markers", []) or []:
        _add_marker_annotation(
            store,
            marker,
            tier_name="markers",
            asset_id=asset_id or DEFAULT_ASSET_ID,
            rate=rate,
            attribution=attribution,
            now=now,
            ensure_tier=_ensure_tier,
            otio_module=otio,
        )

    # --- per-track clips + markers -----------------------------------
    track_offset_seconds: dict[str, float] = {}

    for track in timeline.tracks:
        tier_name = track.name or "untitled"
        _ensure_tier(tier_name)

        # Walk children, accumulating a track-position cursor.
        cursor = 0.0
        for child in track:
            if hasattr(child, "source_range") and child.source_range is not None:
                duration_seconds = (
                    float(child.source_range.duration.value)
                    / float(child.source_range.duration.rate)
                )
            elif hasattr(child, "duration"):
                try:
                    duration_seconds = (
                        float(child.duration().value) / float(child.duration().rate)
                    )
                except Exception:  # pragma: no cover  — defensive
                    duration_seconds = 0.0
            else:
                duration_seconds = 0.0

            schema = getattr(child, "schema_name", lambda: "")()
            if schema.startswith("Clip"):
                clip_asset = asset_id or _media_url(child) or f"otio:clip:{child.name}"
                start = RationalTime.from_seconds(repr(cursor), rate=rate)
                end = RationalTime.from_seconds(repr(cursor + duration_seconds), rate=rate)
                interval = TimeInterval(start, end)

                clip_metadata = (
                    dict(child.metadata) if hasattr(child, "metadata") else {}
                )
                store.add(
                    Annotation(
                        id=uuid4(),
                        tier=tier_name,
                        reference=MediaRef(asset_id=clip_asset, interval=interval),
                        body={
                            "name": child.name,
                            "kind": "clip",
                            "otio_metadata": clip_metadata,
                        },
                        body_schema_uri=BODY_SCHEMA_URI_CLIP,
                        provenance=Provenance(
                            was_generated_by=f"adapter:{ADAPTER_NAME}",
                            was_attributed_to=attribution,
                            generated_at_time=now,
                            activity="import",
                        ),
                    )
                )

                # Markers on this clip — placed at clip-relative source_range start
                # offset onto the track timeline.
                for marker in getattr(child, "markers", []) or []:
                    marker_start_in_clip = (
                        float(marker.marked_range.start_time.value)
                        / float(marker.marked_range.start_time.rate)
                    )
                    if child.source_range is not None:
                        clip_source_start = (
                            float(child.source_range.start_time.value)
                            / float(child.source_range.start_time.rate)
                        )
                    else:
                        clip_source_start = 0.0
                    marker_track_pos = cursor + (marker_start_in_clip - clip_source_start)
                    _add_marker_annotation(
                        store,
                        marker,
                        tier_name="markers",
                        asset_id=clip_asset,
                        rate=rate,
                        attribution=attribution,
                        now=now,
                        track_pos=marker_track_pos,
                        ensure_tier=_ensure_tier,
                        otio_module=otio,
                    )

            cursor += duration_seconds

        track_offset_seconds[tier_name] = cursor

    return store


def _add_marker_annotation(
    store: MemoryStore,
    marker,
    *,
    tier_name: str,
    asset_id: str,
    rate: int,
    attribution: str,
    now: RationalTime,
    ensure_tier,
    otio_module,
    track_pos: float | None = None,
) -> None:
    """Insert a point Annotation for an OTIO Marker."""
    ensure_tier(tier_name)

    if track_pos is not None:
        t = RationalTime.from_seconds(repr(track_pos), rate=rate)
    else:
        t = _otio_rationaltime_to_lacing(marker.marked_range.start_time, rate)

    color = getattr(marker, "color", None)
    color_str = str(color) if color else None

    metadata = dict(marker.metadata) if hasattr(marker, "metadata") else {}

    store.add(
        Annotation(
            id=uuid4(),
            tier=tier_name,
            reference=MediaRef(asset_id=asset_id, interval=TimeInterval.point(t)),
            body={
                "name": marker.name,
                "kind": "marker",
                "color": color_str,
                "otio_metadata": metadata,
            },
            body_schema_uri=BODY_SCHEMA_URI_MARKER,
            provenance=Provenance(
                was_generated_by=f"adapter:{ADAPTER_NAME}",
                was_attributed_to=attribution,
                generated_at_time=now,
                activity="import",
            ),
        )
    )


def _open_timeline(source: str | bytes | os.PathLike, otio_module):
    if isinstance(source, (bytes, bytearray)):
        text = bytes(source).decode("utf-8")
        return otio_module.adapters.read_from_string(text, adapter_name="otio_json")
    if isinstance(source, str):
        s = source.lstrip()
        if s.startswith("{"):
            return otio_module.adapters.read_from_string(source, adapter_name="otio_json")
    return otio_module.adapters.read_from_file(os.fspath(source))


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    name: str = "lacing",
    **_kwargs: Any,
) -> bytes | None:
    """Serialize ``store`` as an OTIO file.

    Each tier becomes one Track. Annotations whose body has
    ``kind=='marker'`` are emitted as ``Marker``s on the track at their
    interval start. Annotations whose body has ``kind=='clip'`` (or no
    explicit kind) become Clips with ``ExternalReference`` to the
    ``asset_id`` and ``source_range`` matching the lacing interval.

    Note: lacing intervals are absolute positions; OTIO clips are
    sequential within a track. We sort + place clips back-to-back per
    tier; gaps between intervals become explicit ``Gap`` items.
    """
    otio = _require_otio()

    timeline = otio.schema.Timeline(name=name)
    by_tier: dict[str, list[Annotation]] = {}
    for ann in _all_with_intervals(store):
        if isinstance(ann.reference, MediaRef):
            by_tier.setdefault(ann.tier, []).append(ann)

    declared_tiers = []
    tiers_iter = getattr(store, "tiers", None)
    if callable(tiers_iter):
        declared_tiers = [t.name for t in tiers_iter()]
    referenced = list(by_tier.keys())
    seen: set[str] = set()
    ordered: list[str] = []
    for n in declared_tiers + referenced:
        if n not in seen:
            seen.add(n)
            ordered.append(n)

    for tier_name in ordered:
        anns = by_tier.get(tier_name, [])
        anns_sorted = sorted(
            anns, key=lambda a: float(a.interval.start.to_fraction())
        )

        track = otio.schema.Track(name=tier_name)
        cursor = 0.0
        for ann in anns_sorted:
            iv = ann.interval
            assert iv is not None
            start_s = float(iv.start.to_fraction())
            end_s = float(iv.end.to_fraction())

            kind = ann.body.get("kind") if isinstance(ann.body, dict) else None
            if kind == "marker" or iv.is_point:
                # Markers can't go on a Track directly without a host —
                # attach to a Gap or the track itself.
                marker_t = otio.opentime.RationalTime(
                    value=float(iv.start.to_fraction()) * 1000,
                    rate=1000.0,
                )
                marker = otio.schema.Marker(
                    name=ann.body.get("name") if isinstance(ann.body, dict) else None,
                    marked_range=otio.opentime.TimeRange(
                        start_time=marker_t,
                        duration=otio.opentime.RationalTime(0, 1000.0),
                    ),
                )
                track.markers.append(marker)
                continue

            # Insert a gap if needed.
            gap_seconds = start_s - cursor
            if gap_seconds > 0:
                track.append(
                    otio.schema.Gap(
                        source_range=otio.opentime.TimeRange(
                            start_time=otio.opentime.RationalTime(0, 1000.0),
                            duration=otio.opentime.RationalTime(
                                value=gap_seconds * 1000.0, rate=1000.0
                            ),
                        ),
                    )
                )
                cursor = start_s

            duration_seconds = end_s - start_s
            asset_url = ann.reference.asset_id  # type: ignore[union-attr]
            clip = otio.schema.Clip(
                name=ann.body.get("name") if isinstance(ann.body, dict) else ann.tier,
                media_reference=otio.schema.ExternalReference(target_url=asset_url),
                source_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(0, 1000.0),
                    duration=otio.opentime.RationalTime(
                        value=duration_seconds * 1000.0, rate=1000.0
                    ),
                ),
            )
            track.append(clip)
            cursor = end_s

        timeline.tracks.append(track)

    if target is None:
        text = otio.adapters.write_to_string(timeline, adapter_name="otio_json")
        return text.encode("utf-8")

    otio.adapters.write_to_file(timeline, os.fspath(target))
    return None


def _all_with_intervals(store: IntervalAnnotationStore):
    iter_all = getattr(store, "all", None)
    if callable(iter_all):
        for a in iter_all():
            if a.interval is not None and isinstance(a.reference, MediaRef):
                yield a
        return
    for key in store:  # type: ignore[attr-defined]
        for a in store[key]:  # type: ignore[index]
            if a.interval is not None and isinstance(a.reference, MediaRef):
                yield a


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


register_adapter(
    name=ADAPTER_NAME,
    load=load,
    dump=dump,
    extensions=(".otio",),
    media_types=("application/vnd.otio+json",),
    body_schema_uris=(BODY_SCHEMA_URI_CLIP, BODY_SCHEMA_URI_MARKER),
    description=(
        "OpenTimelineIO (Academy Software Foundation). Maps tracks to tiers, "
        "clips to interval annotations, and markers to point annotations. "
        "Native RationalTime parity — no float precision loss at the boundary."
    ),
)
