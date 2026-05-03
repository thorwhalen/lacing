"""JAMS (JSON Annotated Music Specification) adapter.

JAMS is the standard MIR (Music Information Retrieval) annotation format.
Each ``Annotation`` carries a *namespace* (``chord``, ``beat``, ``key``,
``segment_open``, ``tag_open``, ...) that defines the type of its
observations. We map JAMS namespaces to lacing **tiers**, observations to
``Annotation`` rows, and each observation's typed ``value`` into the lacing
body envelope.

Mapping
-------
JAMS                                ↔ lacing
``Annotation.namespace``            ↔ ``Tier.name``
``Observation.time, .duration``     ↔ ``MediaRef.interval`` (half-open)
``Observation.value``               ↔ ``body['value']`` (namespace-typed)
``Observation.confidence``          ↔ ``Annotation.confidence``
``annotation_metadata.annotator``   ↔ ``Provenance.was_attributed_to``
``file_metadata.identifiers/title`` ↔ ``MediaRef.asset_id``

Body schema
-----------
We use a single generic body schema URI:

    annot://schema/jams-observation/v1

with shape ``{"value": <namespace-typed>, "namespace": <str>}``. Registering
namespace-specific Pydantic body schemas (one per JAMS namespace) is left to
downstream packages — JAMS namespaces are extensible and we don't want the
adapter to impose a fixed catalog.

Time
----
JAMS times are float seconds. We convert at the parse boundary via
``Fraction(repr(...))`` to recover exact rational values. Default rate is
``DEFAULT_RATE`` (24000); pass ``rate=`` to use a different project rate.
``LossyTimeConversionError`` is raised if any observation can't be exactly
represented.

Lossy on dump
-------------
- Per-annotation provenance beyond ``annotator`` (``was_derived_from``,
  ``was_generated_by``, ``activity``) is dropped — JAMS has no
  corresponding fields.
- ``body['note']`` and other extra body fields are dropped: only
  ``body['value']`` round-trips.
- File-level ``identifiers`` and ``title`` are populated from the first
  annotation's ``MediaRef.asset_id`` if available.

Spec: https://jams.readthedocs.io/
"""

from __future__ import annotations

import os
import tempfile
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
    import jams as _jams_lib


ADAPTER_NAME = "jams"
BODY_SCHEMA_URI = "annot://schema/jams-observation/v1"
DEFAULT_ASSET_ID = "jams:unspecified"


class _MissingJams(ImportError):
    """Raised when ``jams`` is not installed."""


def _require_jams():
    try:
        import jams
    except ImportError as exc:
        raise _MissingJams(
            "The 'jams' adapter requires the jams package. Install with: "
            "pip install 'lacing[jams]'  (or directly: pip install jams)"
        ) from exc
    return jams


def _to_rational(seconds: float | int, rate: int) -> RationalTime:
    """Boundary conversion: float seconds → exact RationalTime via Fraction(repr)."""
    if isinstance(seconds, int) and not isinstance(seconds, bool):
        f = Fraction(seconds)
    else:
        f = Fraction(repr(float(seconds)))
    return RationalTime.from_seconds(f, rate=rate)


def _resolve_asset_id(jams_obj: "_jams_lib.JAMS", override: str | None) -> str:
    """Pick an asset_id from JAMS file_metadata identifiers/title, or fall back."""
    if override is not None:
        return override
    identifiers = getattr(jams_obj.file_metadata, "identifiers", None) or {}
    if isinstance(identifiers, dict):
        for key in ("musicbrainz", "slug", "track_id", "id"):
            if key in identifiers and identifiers[key]:
                return f"jams:{key}:{identifiers[key]}"
    title = getattr(jams_obj.file_metadata, "title", "") or ""
    if title:
        return f"jams:title:{title}"
    return DEFAULT_ASSET_ID


def _annotator_name(annotation: "_jams_lib.Annotation") -> str:
    """Pick a human-readable annotator name from JAMS metadata.

    JAMS round-trips ``annotator`` and ``curator`` as ``JObject`` instances
    (custom dict-attr hybrid), not plain dicts, so we read by attribute
    *and* dict access.
    """
    md = annotation.annotation_metadata
    for field in ("annotator", "curator"):
        obj = getattr(md, field, None)
        if obj is None:
            continue
        # JObject supports both dict-style get() and attribute access.
        name = None
        if hasattr(obj, "get"):
            try:
                name = obj.get("name")
            except (TypeError, AttributeError):
                name = None
        if not name:
            name = getattr(obj, "name", None)
        if name:
            return str(name)
    return "anonymous"


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
    """Load a JAMS file or bytes into a ``MemoryStore``.

    Args:
        source: Path or bytes containing JAMS JSON.
        rate: Quantization rate.
        asset_id: Override media reference. None = derive from
            ``file_metadata.identifiers`` or ``title``.
        attribution: Override per-annotation attribution. None = use each
            annotation's own annotator/curator.
    """
    jams = _require_jams()
    jams_obj = _open_jams(source, jams)
    resolved_asset = _resolve_asset_id(jams_obj, asset_id)

    store = MemoryStore()
    now = RationalTime.zero(rate)

    seen_namespaces: set[str] = set()
    for annotation in jams_obj.annotations:
        namespace = annotation.namespace
        if namespace not in seen_namespaces:
            store.add_tier(Tier(namespace))
            seen_namespaces.add(namespace)

        ann_attribution = attribution or _annotator_name(annotation)

        for obs in annotation.data:
            start = _to_rational(obs.time, rate)
            duration = _to_rational(obs.duration, rate)
            interval = TimeInterval(start, start + duration.to_fraction())

            confidence = obs.confidence
            if confidence is not None:
                # Clamp into [0, 1] — some JAMS files use raw scores; we
                # only expose conformant confidence values.
                if not (0.0 <= float(confidence) <= 1.0):
                    confidence = None
                else:
                    confidence = float(confidence)

            store.add(
                Annotation(
                    id=uuid4(),
                    tier=namespace,
                    reference=MediaRef(
                        asset_id=resolved_asset,
                        interval=interval,
                    ),
                    body={"value": obs.value, "namespace": namespace},
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

    return store


def _open_jams(source: str | bytes | os.PathLike, jams_lib) -> "_jams_lib.JAMS":
    if isinstance(source, (bytes, bytearray)):
        with tempfile.NamedTemporaryFile(
            "wb", suffix=".jams", delete=False
        ) as f:
            f.write(source)
            tmp_path = f.name
        try:
            return jams_lib.load(tmp_path, validate=False)
        finally:
            os.unlink(tmp_path)
    if isinstance(source, str):
        # Tolerate inline JSON strings vs paths.
        s = source.lstrip()
        if s.startswith("{"):
            with tempfile.NamedTemporaryFile(
                "w", suffix=".jams", delete=False, encoding="utf-8"
            ) as f:
                f.write(source)
                tmp_path = f.name
            try:
                return jams_lib.load(tmp_path, validate=False)
            finally:
                os.unlink(tmp_path)
    return jams_lib.load(os.fspath(source), validate=False)


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    title: str = "",
    artist: str = "",
    duration: float | None = None,
    **_kwargs: Any,
) -> bytes | None:
    """Serialize ``store`` as a JAMS file.

    Args:
        store: Source store. Only annotations with a ``MediaRef`` interval
            and a ``body['value']`` are exported.
        target: Output path. None = return bytes.
        title: ``file_metadata.title`` value.
        artist: ``file_metadata.artist`` value.
        duration: ``file_metadata.duration`` (seconds). If None, computed
            as the maximum end-time across all annotations.
    """
    jams = _require_jams()

    annotations = list(_all_with_intervals(store))

    if duration is None:
        max_end = 0.0
        for a in annotations:
            iv = a.interval
            if iv is not None:
                end_s = float(iv.end.to_fraction())
                if end_s > max_end:
                    max_end = end_s
        duration = max_end if max_end > 0 else 1.0

    jams_obj = jams.JAMS()
    jams_obj.file_metadata.duration = float(duration)
    if title:
        jams_obj.file_metadata.title = title
    if artist:
        jams_obj.file_metadata.artist = artist

    # Group annotations by tier (= JAMS namespace).
    by_namespace: dict[str, list[Annotation]] = {}
    for a in annotations:
        by_namespace.setdefault(a.tier, []).append(a)

    for namespace, anns in by_namespace.items():
        try:
            jams_ann = jams.Annotation(namespace=namespace, duration=duration)
        except Exception:
            # Unknown namespace — JAMS rejects validation. Fall back to
            # the closest stable namespace so the file is still writable.
            jams_ann = jams.Annotation(namespace="tag_open", duration=duration)

        # Pick first attribution for the annotator field.
        if anns:
            jams_ann.annotation_metadata.annotator = {
                "name": anns[0].provenance.was_attributed_to,
            }

        for a in anns:
            iv = a.interval
            assert iv is not None
            value = a.body.get("value") if isinstance(a.body, dict) else a.body
            jams_ann.append(
                time=float(iv.start.to_fraction()),
                duration=float(iv.duration.to_fraction()),
                value=value,
                confidence=a.confidence,
            )

        jams_obj.annotations.append(jams_ann)

    # JAMS validates on save by default; namespaces that aren't recognized
    # would raise. Disable strict validation — interop is more important
    # than catalog compliance for round-tripping arbitrary tiers.
    if target is None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".jams", delete=False, encoding="utf-8"
        ) as f:
            tmp_path = f.name
        try:
            jams_obj.save(tmp_path, strict=False)
            return Path(tmp_path).read_bytes()
        finally:
            os.unlink(tmp_path)

    jams_obj.save(os.fspath(target), strict=False)
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
    extensions=(".jams",),
    media_types=("application/vnd.jams+json",),
    body_schema_uris=(BODY_SCHEMA_URI,),
    description=(
        "JAMS (JSON Annotated Music Specification) — MIR annotation format. "
        "Maps namespaces to tiers; observations become annotations whose "
        "body['value'] preserves the namespace-typed value verbatim."
    ),
)
