"""Background processors — pluggable jobs that run against a store + op-log.

A *processor* is a registered async function that:

1. Takes an ``IntervalAnnotationStore``, an ``OpLog``, and processor-specific
   keyword arguments.
2. Either mutates the store (recording op-log entries) or returns a result
   (or both).

Two execution modes ship:

- **Synchronous** via :func:`run_sync` — runs in the current event loop.
  Always available; no Redis or other infra. Use this from tests, CLIs,
  and scripts.
- **Async via Arq** — see ``lacing.worker`` (optional). The same
  processor can be queued through Redis when scale demands it.

Per BACK-DOC §6: Arq is preferred over Celery (lighter, async-native).
But the *processor pattern itself* is independent of Arq — most users
will never need Redis.

Example built-ins:

- :func:`low_confidence_review` — flag annotations whose confidence is
  below a threshold by adding a parallel ``for-review`` tier annotation.
- :func:`detect_density_change_points` — emit point markers wherever the
  annotation density changes more than ``min_delta`` over a sliding
  window.

Register your own with :func:`register_processor`.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from lacing.model import Annotation, MediaRef, Provenance
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


_PROCESSORS: dict[str, Callable[..., Awaitable[Any]]] = {}


class ProcessorError(RuntimeError):
    """Raised when a registered processor's invocation fails."""


def register_processor(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
):
    """Register a processor under ``name`` (defaults to the function name).

    The function may be sync or async; we wrap sync funcs to a coroutine.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        registered_name = name or func.__name__
        if inspect.iscoroutinefunction(func):
            wrapped = func
        else:

            async def wrapped(*args, **kwargs):  # type: ignore[no-redef]
                return func(*args, **kwargs)

        _PROCESSORS[registered_name] = wrapped
        return func  # return the original so type info is preserved

    if func is not None:
        return decorator(func)
    return decorator


def get_processor(name: str) -> Callable[..., Awaitable[Any]]:
    if name not in _PROCESSORS:
        raise KeyError(
            f"no processor registered as {name!r}; known: {sorted(_PROCESSORS)}"
        )
    return _PROCESSORS[name]


def registered_processors() -> list[str]:
    """Names of every registered processor, sorted."""
    return sorted(_PROCESSORS)


def clear_processors() -> None:
    """Drop every registered processor. For tests."""
    _PROCESSORS.clear()


# ---------------------------------------------------------------------------
# runners
# ---------------------------------------------------------------------------


def run_sync(
    name: str,
    *,
    store: Any,
    oplog: Any,
    **kwargs: Any,
) -> Any:
    """Run a processor synchronously and return its result.

    If the processor is async, we call it via ``asyncio.run`` (when no
    loop is running) or schedule and wait on it (when a loop is already
    active). Most callers from sync code want the former.
    """
    processor = get_processor(name)
    coroutine = processor(store=store, oplog=oplog, **kwargs)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        try:
            return asyncio.run(coroutine)
        except Exception as exc:
            raise ProcessorError(f"processor {name!r} failed: {exc}") from exc

    # A loop is already running — caller is in async context. Schedule
    # and use a future. This branch is mostly a courtesy; sync callers
    # don't typically hit it.
    future = asyncio.run_coroutine_threadsafe(coroutine, loop)
    return future.result()


async def run_async(
    name: str,
    *,
    store: Any,
    oplog: Any,
    **kwargs: Any,
) -> Any:
    """Run a processor in the current event loop. For async callers."""
    processor = get_processor(name)
    return await processor(store=store, oplog=oplog, **kwargs)


# ---------------------------------------------------------------------------
# built-in processors
# ---------------------------------------------------------------------------


@register_processor(name="low_confidence_review")
async def low_confidence_review(
    *,
    store: Any,
    oplog: Any,
    threshold: float = 0.5,
    review_tier: str = "for-review",
    actor: str = "processor:low_confidence_review",
) -> dict[str, Any]:
    """Flag low-confidence annotations by mirroring them onto a review tier.

    Args:
        store: The annotation store to scan + mutate.
        oplog: Where to record the new annotations.
        threshold: Confidence below this triggers a review entry. ``None``
            confidences are skipped (treated as full-confidence, since the
            user didn't supply one).
        review_tier: Name of the tier to write review entries onto. Created
            if missing.
        actor: Provenance ``was_attributed_to`` for review entries.

    Returns:
        ``{"flagged": <count>, "review_tier": <name>}``.
    """
    if store.get_tier(review_tier) is None:
        review_tier_obj = Tier(review_tier)
        store.add_tier(review_tier_obj)
        oplog.append(
            "add_tier",
            target_id=review_tier,
            payload={
                "name": review_tier,
                "stereotype": "NONE",
                "parent": None,
                "metadata": {},
            },
            actor=actor,
        )

    iter_all = getattr(store, "all", None)
    if not callable(iter_all):
        raise ProcessorError("store does not expose .all()")

    # Idempotence: collect source ids that already have review entries
    # so a re-run doesn't duplicate them.
    already_reviewed: set[str] = set()
    for ann in iter_all():
        if ann.tier == review_tier:
            source = ann.body.get("source_id") if isinstance(ann.body, dict) else None
            if source:
                already_reviewed.add(str(source))

    flagged = 0
    for ann in list(iter_all()):
        if ann.tier == review_tier:
            continue  # don't recurse on our own output
        if str(ann.id) in already_reviewed:
            continue  # already flagged on a previous run
        if ann.confidence is None:
            continue
        if ann.confidence >= threshold:
            continue
        iv = ann.interval
        if iv is None:
            continue

        ref = ann.reference
        asset_id = getattr(ref, "asset_id", None)
        if asset_id is None:
            # Only ``MediaRef`` annotations carry a stable asset_id.
            continue

        review_ann = Annotation(
            id=uuid4(),
            tier=review_tier,
            reference=MediaRef(asset_id=asset_id, interval=iv),
            body={
                "reason": "low_confidence",
                "source_id": str(ann.id),
                "source_confidence": ann.confidence,
                "source_tier": ann.tier,
            },
            body_schema_uri="annot://schema/review/v1",
            provenance=Provenance(
                was_generated_by=actor,
                was_attributed_to=actor,
                was_derived_from=[ann.id],
                generated_at_time=RationalTime.zero(),
                activity="derive",
            ),
        )
        store.add(review_ann)
        oplog.append(
            "add_annotation",
            target_id=str(review_ann.id),
            payload={"annotation": review_ann.model_dump(mode="json")},
            actor=actor,
        )
        flagged += 1

    return {"flagged": flagged, "review_tier": review_tier}


@register_processor(name="detect_density_change_points")
async def detect_density_change_points(
    *,
    store: Any,
    oplog: Any,
    asset_id: str | None = None,
    bucket_seconds: float = 1.0,
    min_delta: int = 3,
    rate: int = 1000,
    target_tier: str = "density-change-points",
    actor: str = "processor:detect_density_change_points",
) -> dict[str, Any]:
    """Emit point markers wherever annotation density changes sharply.

    Buckets all annotations by ``floor(start_seconds / bucket_seconds)``
    and emits a point marker on ``target_tier`` for each bucket boundary
    where the count differs from the previous bucket by at least
    ``min_delta``. Lightweight stand-in for a real CPD algorithm — the
    architecture is what matters.

    Args:
        store: Source store.
        oplog: Where to record emitted markers.
        asset_id: If set, only consider annotations on this asset.
            ``None`` = consider all media-referenced annotations.
        bucket_seconds: Bucket width.
        min_delta: Minimum |Δ count| to emit a marker.
        rate: Quantization rate for the new point intervals.
        target_tier: Output tier; created if missing.
        actor: Provenance attribution.

    Returns:
        ``{"markers": <count>, "target_tier": <name>}``.
    """
    if bucket_seconds <= 0:
        raise ProcessorError(f"bucket_seconds must be positive, got {bucket_seconds!r}")

    if store.get_tier(target_tier) is None:
        store.add_tier(Tier(target_tier))
        oplog.append(
            "add_tier",
            target_id=target_tier,
            payload={
                "name": target_tier,
                "stereotype": "NONE",
                "parent": None,
                "metadata": {},
            },
            actor=actor,
        )

    iter_all = getattr(store, "all", None)
    if not callable(iter_all):
        raise ProcessorError("store does not expose .all()")

    counts: dict[int, int] = {}
    for ann in iter_all():
        if ann.tier == target_tier:
            continue
        ref = ann.reference
        asset = getattr(ref, "asset_id", None)
        if asset is None:
            continue
        if asset_id is not None and asset != asset_id:
            continue
        iv = ann.interval
        if iv is None:
            continue
        start_s = float(iv.start.to_fraction())
        bucket = int(start_s // bucket_seconds)
        counts[bucket] = counts.get(bucket, 0) + 1

    if not counts:
        return {"markers": 0, "target_tier": target_tier}

    sorted_buckets = sorted(counts)
    emitted = 0
    asset_for_marker = asset_id or "density-change-points:any"

    prev_count = 0
    for bucket in range(sorted_buckets[0], sorted_buckets[-1] + 1):
        cur_count = counts.get(bucket, 0)
        if abs(cur_count - prev_count) >= min_delta and bucket != sorted_buckets[0]:
            t_seconds = bucket * bucket_seconds
            t = RationalTime.from_seconds(str(t_seconds), rate=rate)
            marker = Annotation(
                id=uuid4(),
                tier=target_tier,
                reference=MediaRef(
                    asset_id=asset_for_marker,
                    interval=TimeInterval.point(t),
                ),
                body={
                    "delta": cur_count - prev_count,
                    "bucket_seconds": bucket_seconds,
                },
                body_schema_uri="annot://schema/density-change-point/v1",
                provenance=Provenance(
                    was_generated_by=actor,
                    was_attributed_to=actor,
                    generated_at_time=RationalTime.zero(),
                    activity="derive",
                ),
            )
            store.add(marker)
            oplog.append(
                "add_annotation",
                target_id=str(marker.id),
                payload={"annotation": marker.model_dump(mode="json")},
                actor=actor,
            )
            emitted += 1
        prev_count = cur_count

    return {"markers": emitted, "target_tier": target_tier}
