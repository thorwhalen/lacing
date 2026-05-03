"""Praat TextGrid adapter.

Praat TextGrids have two tier types: ``IntervalTier`` (ranges) and
``PointTier`` (instants — Praat's own ``TextTier``). lacing maps both to a
single ``Annotation`` envelope; point annotations use a zero-length
``TimeInterval`` (``start == end``). See ANN-DOC §B and the
``lacing-adapter-authoring`` skill.

Lossy fields:
    Praat has no provenance, no schema URIs, and no confidence. On load we
    synthesize provenance with ``was_generated_by="adapter:textgrid"``.
    On dump we drop everything but ``tier``, ``interval`` (or point), and
    ``body['text']`` (or the raw ``body`` repr if no ``text`` key).

Time discipline:
    Praat stores times as ASCII decimal strings — these can be exact at
    common rates. We convert through ``Fraction(str)`` to avoid float
    ingestion. Default rate is ``DEFAULT_RATE`` (24000); pass ``rate=`` to
    override.

Tier stereotype mapping:
    ELAN tier stereotypes have no Praat equivalent. Every loaded tier gets
    stereotype ``NONE``. On dump, only the ``tier`` *name* is preserved.
"""

from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from lacing.adapters import register_adapter
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import DEFAULT_RATE, RationalTime, TimeInterval

if TYPE_CHECKING:
    from praatio.data_classes.textgrid import Textgrid


ADAPTER_NAME = "textgrid"
BODY_SCHEMA_URI = "annot://schema/textgrid-label/v1"
DEFAULT_ASSET_ID = "textgrid:unspecified"


class _MissingPraatio(ImportError):
    """Raised when the praatio backend isn't installed."""


def _require_praatio():
    try:
        from praatio import textgrid as _tg  # noqa: F401
        from praatio.data_classes.interval_tier import IntervalTier
        from praatio.data_classes.point_tier import PointTier
        from praatio.data_classes.textgrid import Textgrid
        from praatio.utilities.constants import Interval, Point
    except ImportError as exc:
        raise _MissingPraatio(
            "The 'textgrid' adapter requires praatio. Install with: "
            "pip install 'lacing[textgrid]'  (or directly: pip install praatio)"
        ) from exc
    return {
        "Textgrid": Textgrid,
        "IntervalTier": IntervalTier,
        "PointTier": PointTier,
        "Interval": Interval,
        "Point": Point,
    }


def _to_rational(seconds: float | str, rate: int) -> RationalTime:
    """Boundary conversion: Praat's float seconds → exact RationalTime.

    Always goes through string→Fraction so float artifacts don't sneak in.
    Quantizes to ``rate``; raises ``LossyTimeConversionError`` if exact
    representation is impossible.
    """
    if isinstance(seconds, str):
        f = Fraction(seconds)
    else:
        # Float from praatio; round-trip through repr() to avoid binary
        # representation noise (Fraction(0.5) is exact; Fraction(0.1) is not).
        f = Fraction(repr(seconds))
    return RationalTime.from_seconds(f, rate=rate)


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str = DEFAULT_ASSET_ID,
    attribution: str = "anonymous",
    include_empty: bool = True,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Load a TextGrid file or bytes into a ``MemoryStore``.

    Args:
        source: Path or bytes containing TextGrid content.
        rate: Quantization rate for converted times.
        asset_id: ``MediaRef.asset_id`` to attach to every annotation.
        attribution: ``Provenance.was_attributed_to`` value.
        include_empty: If False, drop intervals/points with empty labels.
    """
    deps = _require_praatio()
    Textgrid = deps["Textgrid"]
    IntervalTier = deps["IntervalTier"]
    PointTier = deps["PointTier"]

    grid = _open_textgrid(source, Textgrid, include_empty=include_empty)

    store = MemoryStore()
    now = RationalTime.zero(rate)

    for tier_name in grid.tierNames:
        tier = grid.getTier(tier_name)
        store.add_tier(Tier(tier_name))

        if isinstance(tier, IntervalTier):
            for entry in tier.entries:
                if not include_empty and not entry.label:
                    continue
                interval = TimeInterval(
                    _to_rational(entry.start, rate),
                    _to_rational(entry.end, rate),
                )
                _add_annotation(store, interval, tier_name, entry.label, asset_id, attribution, now)
        elif isinstance(tier, PointTier):
            for entry in tier.entries:
                if not include_empty and not entry.label:
                    continue
                t = _to_rational(entry.time, rate)
                interval = TimeInterval.point(t)
                _add_annotation(store, interval, tier_name, entry.label, asset_id, attribution, now)
        else:  # pragma: no cover  — praatio has only the two tier types today
            raise NotImplementedError(f"Unknown tier type: {type(tier).__name__}")

    return store


def _open_textgrid(
    source: str | bytes | os.PathLike,
    Textgrid_cls: type["Textgrid"],
    *,
    include_empty: bool,
) -> "Textgrid":
    from praatio import textgrid as _tg

    if isinstance(source, (bytes, bytearray)):
        # praatio doesn't read bytes directly; round-trip through a temp file
        # for now. Phase 1 can replace with a string-based parser.
        import tempfile

        with tempfile.NamedTemporaryFile(
            "wb", suffix=".TextGrid", delete=False
        ) as f:
            f.write(source)
            tmp_path = f.name
        try:
            return _tg.openTextgrid(tmp_path, includeEmptyIntervals=include_empty)
        finally:
            os.unlink(tmp_path)

    return _tg.openTextgrid(os.fspath(source), includeEmptyIntervals=include_empty)


def _add_annotation(
    store: MemoryStore,
    interval: TimeInterval,
    tier_name: str,
    label: str,
    asset_id: str,
    attribution: str,
    generated_at: RationalTime,
) -> None:
    store.add(
        Annotation(
            id=uuid4(),
            tier=tier_name,
            reference=MediaRef(asset_id=asset_id, interval=interval),
            body={"text": label},
            body_schema_uri=BODY_SCHEMA_URI,
            provenance=Provenance(
                was_generated_by=f"adapter:{ADAPTER_NAME}",
                was_attributed_to=attribution,
                generated_at_time=generated_at,
                activity="import",
            ),
        )
    )


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    format: str = "long_textgrid",
    include_empty: bool = True,
    **_kwargs: Any,
) -> bytes | None:
    """Write a ``IntervalAnnotationStore`` as a Praat TextGrid.

    Args:
        store: Source store. Only annotations with a ``MediaRef`` interval
            are exported; timeless (``AnnotationRef`` without sub-interval)
            annotations are silently dropped.
        target: Output path. If None, returns bytes.
        format: One of praatio's formats: ``"long_textgrid"``,
            ``"short_textgrid"``, ``"json"``.
        include_empty: Whether to emit empty-label intervals on point tiers.
    """
    deps = _require_praatio()
    Textgrid = deps["Textgrid"]
    IntervalTier = deps["IntervalTier"]
    PointTier = deps["PointTier"]
    Interval = deps["Interval"]
    Point = deps["Point"]

    by_tier_intervals: dict[str, list] = {}
    by_tier_points: dict[str, list] = {}
    min_t = float("inf")
    max_t = float("-inf")

    for ann in _all_with_intervals(store):
        iv = ann.interval
        assert iv is not None  # invariant of _all_with_intervals
        label = _label_of(ann)

        if iv.is_point:
            t = float(iv.start.to_fraction())
            by_tier_points.setdefault(ann.tier, []).append(Point(t, label))
            min_t = min(min_t, t)
            max_t = max(max_t, t)
        else:
            start = float(iv.start.to_fraction())
            end = float(iv.end.to_fraction())
            by_tier_intervals.setdefault(ann.tier, []).append(Interval(start, end, label))
            min_t = min(min_t, start)
            max_t = max(max_t, end)

    if min_t == float("inf"):
        # Empty store — produce a minimal valid TextGrid spanning [0, 0].
        min_t = 0.0
        max_t = 0.0

    grid = Textgrid(minTimestamp=min_t, maxTimestamp=max_t)

    # Preserve store-declared tier order first; then any tier referenced by
    # annotations but not declared.
    declared = [t.name for t in store.tiers()]  # type: ignore[attr-defined]
    referenced = list(by_tier_intervals.keys()) + list(by_tier_points.keys())
    seen: set[str] = set()
    ordered: list[str] = []
    for n in declared + referenced:
        if n not in seen:
            seen.add(n)
            ordered.append(n)

    for tier_name in ordered:
        if tier_name in by_tier_intervals:
            entries = sorted(by_tier_intervals[tier_name], key=lambda x: x.start)
            grid.addTier(IntervalTier(tier_name, entries, minT=min_t, maxT=max_t))
        elif tier_name in by_tier_points:
            entries = sorted(by_tier_points[tier_name], key=lambda x: x.time)
            grid.addTier(PointTier(tier_name, entries, minT=min_t, maxT=max_t))
        # else: declared tier with no entries — skip, since praatio refuses
        # to add an empty tier without a known type.

    if target is None:
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".TextGrid", delete=False
        ) as f:
            tmp_path = f.name
        try:
            grid.save(tmp_path, format=format, includeBlankSpaces=include_empty)
            return Path(tmp_path).read_bytes()
        finally:
            os.unlink(tmp_path)

    grid.save(os.fspath(target), format=format, includeBlankSpaces=include_empty)
    return None


def _all_with_intervals(store: IntervalAnnotationStore):
    """Iterate annotations with a non-None ``MediaRef`` interval."""
    # Backends provide either .all() or are MutableMapping-shaped.
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


def _label_of(ann: Annotation) -> str:
    body = ann.body
    if isinstance(body, dict) and "text" in body:
        return str(body["text"])
    return ""


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


register_adapter(
    name=ADAPTER_NAME,
    load=load,
    dump=dump,
    extensions=(".TextGrid",),
    media_types=("text/x-praat-textgrid",),
    body_schema_uris=(BODY_SCHEMA_URI,),
    description="Praat TextGrid (interval and point tiers). Lossy: drops provenance, confidence, schema URIs.",
)
