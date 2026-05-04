"""Label Studio JSON adapter.

Label Studio is a popular labeling tool whose canonical export shape is
a JSON array of *tasks*, each with one or more *annotations* containing
typed *results*. We focus on time-interval results (the ``Audio``,
``Video``, and ``TimeSeries`` labeling controls) since lacing is an
interval-annotation system.

Mapping
-------
Label Studio                                ↔ lacing
``data.audio`` / ``data.video`` / ``data.url`` ↔ ``MediaRef.asset_id``
``result.from_name``                        ↔ ``Tier.name``
``result.value.{start, end}`` (seconds)     ↔ ``MediaRef.interval``
``result.value.labels`` (list of strings)   ↔ ``body['labels']``
``annotation.completed_by`` (or ``user``)   ↔ ``Provenance.was_attributed_to``
``result.origin`` ("prediction"/...)        → ``confidence`` heuristic
``result.id``                               → preserved in body
``result.type``                             → preserved in body

Lossy on dump
-------------
- Per-result Label Studio metadata (``image_rotation``,
  ``original_width``, etc.) is dropped — they're irrelevant for time
  intervals.
- Predictions vs annotations distinction is collapsed: lacing tracks
  AI vs human via ``confidence`` and ``provenance.was_generated_by``,
  and we set Label Studio's ``origin`` to ``manual`` on dump.
- Multi-annotator support: only one annotation per task is emitted on
  dump (the first), since lacing's per-annotation provenance fits
  Label Studio's per-task ``annotations`` list awkwardly.

Spec: https://labelstud.io/guide/export.html
"""

from __future__ import annotations

import json
import os
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

from lacing.adapters import register_adapter
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import IntervalAnnotationStore, MemoryStore
from lacing.tier import Tier
from lacing.time import DEFAULT_RATE, RationalTime, TimeInterval


ADAPTER_NAME = "label_studio"
BODY_SCHEMA_URI = "annot://schema/label-studio-region/v1"
DEFAULT_ASSET_ID = "label-studio:unspecified"


def _to_rational(seconds: float | int | str, rate: int) -> RationalTime:
    """Boundary conversion: float/int/str seconds → exact RationalTime."""
    if isinstance(seconds, str):
        f = Fraction(seconds)
    elif isinstance(seconds, int) and not isinstance(seconds, bool):
        f = Fraction(seconds)
    else:
        f = Fraction(repr(float(seconds)))
    return RationalTime.from_seconds(f, rate=rate)


def _resolve_asset_id(task: dict[str, Any], override: str | None) -> str:
    if override is not None:
        return override
    data = task.get("data") or {}
    if isinstance(data, dict):
        for key in ("audio", "video", "url", "text", "image"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    task_id = task.get("id")
    if task_id is not None:
        return f"label-studio:task:{task_id}"
    return DEFAULT_ASSET_ID


def _attribution(annotation: dict[str, Any], default: str = "anonymous") -> str:
    for key in ("completed_by", "user"):
        value = annotation.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            email = value.get("email") or value.get("username")
            if email:
                return str(email)
    return default


def _is_time_value(value: dict[str, Any]) -> bool:
    return (
        isinstance(value, dict)
        and "start" in value
        and "end" in value
        and isinstance(value["start"], (int, float, str))
        and isinstance(value["end"], (int, float, str))
    )


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str | None = None,
    attribution: str | None = None,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Load a Label Studio JSON export into a ``MemoryStore``.

    Args:
        source: Path, bytes, or JSON string. Accepts both an array of
            tasks and a single task dict.
        rate: Quantization rate.
        asset_id: Override the resolved asset for every annotation.
        attribution: Override per-annotation attribution.
    """
    data = _load_json(source)

    if isinstance(data, dict):
        tasks = [data]
    elif isinstance(data, list):
        tasks = data
    else:
        raise ValueError(
            f"unsupported Label Studio document shape: {type(data).__name__}"
        )

    store = MemoryStore()
    seen_tiers: set[str] = set()
    now = RationalTime.zero(rate)

    for task in tasks:
        if not isinstance(task, dict):
            continue
        resolved_asset = _resolve_asset_id(task, asset_id)

        for ls_ann in task.get("annotations", []) or []:
            if not isinstance(ls_ann, dict):
                continue
            ann_attribution = attribution or _attribution(ls_ann)

            for result in ls_ann.get("result", []) or []:
                if not isinstance(result, dict):
                    continue
                value = result.get("value")
                if not _is_time_value(value):
                    continue

                tier_name = (
                    result.get("from_name")
                    or result.get("type")
                    or "label-studio"
                )
                if tier_name not in seen_tiers:
                    store.add_tier(Tier(tier_name))
                    seen_tiers.add(tier_name)

                start = _to_rational(value["start"], rate)
                end = _to_rational(value["end"], rate)
                interval = TimeInterval(start, end)

                labels = value.get("labels")
                if labels is None:
                    labels = value.get("text")  # for textareas

                body: dict[str, Any] = {
                    "labels": list(labels) if isinstance(labels, list) else labels,
                    "ls_id": result.get("id"),
                    "ls_type": result.get("type"),
                    "from_name": result.get("from_name"),
                    "to_name": result.get("to_name"),
                }
                # Preserve any extra fields under a value passthrough.
                extra_value = {
                    k: v
                    for k, v in value.items()
                    if k not in ("start", "end", "labels", "text")
                }
                if extra_value:
                    body["extra_value"] = extra_value

                # AI predictions land in `predictions` (not `annotations`)
                # but if present here with origin "prediction" we treat
                # confidence default as 0.5 (uncertain) — best-effort.
                origin = result.get("origin")
                confidence = None
                if origin == "prediction":
                    score = result.get("score")
                    if isinstance(score, (int, float)) and 0 <= score <= 1:
                        confidence = float(score)
                    else:
                        confidence = 0.5

                store.add(
                    Annotation(
                        id=uuid4(),
                        tier=tier_name,
                        reference=MediaRef(
                            asset_id=resolved_asset, interval=interval
                        ),
                        body=body,
                        body_schema_uri=BODY_SCHEMA_URI,
                        provenance=Provenance(
                            was_generated_by=f"adapter:{ADAPTER_NAME}",
                            was_attributed_to=ann_attribution,
                            generated_at_time=now,
                            activity="import",
                        ),
                        confidence=confidence,
                    )
                )

        # Predictions live in a sibling list with same shape.
        for prediction in task.get("predictions", []) or []:
            if not isinstance(prediction, dict):
                continue
            ann_attribution = attribution or _attribution(prediction, default="agent:label-studio")

            for result in prediction.get("result", []) or []:
                if not isinstance(result, dict):
                    continue
                value = result.get("value")
                if not _is_time_value(value):
                    continue

                tier_name = (
                    result.get("from_name") or result.get("type") or "label-studio"
                )
                if tier_name not in seen_tiers:
                    store.add_tier(Tier(tier_name))
                    seen_tiers.add(tier_name)

                start = _to_rational(value["start"], rate)
                end = _to_rational(value["end"], rate)
                interval = TimeInterval(start, end)

                score = result.get("score")
                confidence = (
                    float(score)
                    if isinstance(score, (int, float)) and 0 <= score <= 1
                    else 0.5
                )

                labels = value.get("labels") or value.get("text")
                store.add(
                    Annotation(
                        id=uuid4(),
                        tier=tier_name,
                        reference=MediaRef(
                            asset_id=resolved_asset, interval=interval
                        ),
                        body={
                            "labels": list(labels) if isinstance(labels, list) else labels,
                            "ls_id": result.get("id"),
                            "ls_type": result.get("type"),
                            "from_name": result.get("from_name"),
                            "to_name": result.get("to_name"),
                            "is_prediction": True,
                        },
                        body_schema_uri=BODY_SCHEMA_URI,
                        provenance=Provenance(
                            was_generated_by="agent:label-studio",
                            was_attributed_to=ann_attribution,
                            generated_at_time=now,
                            activity="infer",
                        ),
                        confidence=confidence,
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


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    pretty: bool = True,
    **_kwargs: Any,
) -> bytes | None:
    """Serialize ``store`` as a Label Studio JSON export.

    Annotations are grouped by ``MediaRef.asset_id`` — each asset becomes
    one task with a single ``annotations[0]`` entry collecting every
    region. ``confidence < 0.5`` flips the result into Label Studio's
    ``predictions`` slot rather than ``annotations``.
    """
    by_asset: dict[str, list[Annotation]] = {}
    for ann in _all_with_intervals(store):
        if not isinstance(ann.reference, MediaRef):
            continue
        by_asset.setdefault(ann.reference.asset_id, []).append(ann)

    tasks: list[dict[str, Any]] = []
    for task_idx, (asset, anns) in enumerate(sorted(by_asset.items()), start=1):
        annotation_results: list[dict[str, Any]] = []
        prediction_results: list[dict[str, Any]] = []
        attribution = "anonymous"

        for ann in anns:
            iv = ann.interval
            assert iv is not None
            body = ann.body if isinstance(ann.body, dict) else {}
            attribution = ann.provenance.was_attributed_to

            labels = body.get("labels")
            value: dict[str, Any] = {
                "start": float(iv.start.to_fraction()),
                "end": float(iv.end.to_fraction()),
            }
            if isinstance(labels, list):
                value["labels"] = labels
            elif isinstance(labels, str):
                value["text"] = [labels]

            extra = body.get("extra_value")
            if isinstance(extra, dict):
                value.update(extra)

            result: dict[str, Any] = {
                "id": body.get("ls_id") or str(ann.id),
                "type": body.get("ls_type") or "labels",
                "value": value,
                "from_name": body.get("from_name") or ann.tier,
                "to_name": body.get("to_name") or "audio",
            }

            is_prediction = body.get("is_prediction") is True or (
                ann.confidence is not None and ann.confidence < 0.5
            )
            if is_prediction:
                if ann.confidence is not None:
                    result["score"] = ann.confidence
                prediction_results.append(result)
            else:
                annotation_results.append(result)

        task: dict[str, Any] = {
            "id": task_idx,
            "data": {"audio": asset},
        }
        if annotation_results:
            task["annotations"] = [
                {
                    "id": task_idx,
                    "completed_by": attribution,
                    "result": annotation_results,
                }
            ]
        if prediction_results:
            task["predictions"] = [
                {
                    "id": task_idx,
                    "model_version": "lacing",
                    "result": prediction_results,
                }
            ]
        tasks.append(task)

    indent = 2 if pretty else None
    blob = json.dumps(tasks, indent=indent, ensure_ascii=False).encode("utf-8")

    if target is None:
        return blob
    Path(os.fspath(target)).write_bytes(blob)
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
    extensions=(".labelstudio.json",),
    media_types=("application/x-label-studio+json",),
    body_schema_uris=(BODY_SCHEMA_URI,),
    description=(
        "Label Studio JSON export (audio/video/timeseries time regions). "
        "Maps from_name to tier; preserves labels, ls_id, ls_type, "
        "from_name, to_name. Predictions land with confidence < 0.5."
    ),
)
