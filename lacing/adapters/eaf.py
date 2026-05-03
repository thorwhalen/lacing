"""ELAN EAF adapter (Max Planck Institute's annotation tool format).

EAF is the canonical format for tier-hierarchy annotation. Every Phase 0
adapter modeled flat tiers; this is the first that exercises lacing's
stereotype constraint model end-to-end (TIME_SUBDIVISION, INCLUDED_IN,
SYMBOLIC_SUBDIVISION, SYMBOLIC_ASSOCIATION). See ANN-DOC §B and OSS-DOC
tier-2.4.

Mapping
-------
EAF                                    ↔ lacing
``TIER_ID``                            ↔ ``Tier.name``
``PARENT_REF``                         ↔ ``Tier.parent``
``LINGUISTIC_TYPE_REF`` + ``CONSTRAINTS`` ↔ ``Tier.stereotype``
``ALIGNABLE_ANNOTATION``               ↔ ``Annotation`` with ``MediaRef``
``ANNOTATION_VALUE``                   ↔ ``body['text']``
``MEDIA_DESCRIPTOR / MEDIA_URL``       ↔ ``MediaRef.asset_id`` (when present)

Time
----
EAF stores ALL times as integer milliseconds (the format requires it).
We map directly to ``RationalTime(ms, rate=1000)`` — exact, no floats.
Pass ``rate=`` to re-quantize to a different project rate (must be
exact; raises ``LossyTimeConversionError`` otherwise).

Lossy on dump
-------------
- ELAN provenance is at the document level (``AUTHOR``, ``DATE``); per-
  annotation provenance and confidence are dropped.
- ``REF_ANNOTATION`` (annotations referencing parent annotations rather
  than time slots) is **not yet supported**; the loader emits
  ``ALIGNABLE_ANNOTATION`` data only. Round-trip of REF annotations is
  Phase 2 work.
- ``CV_REF`` controlled vocabularies are not preserved.
- The ELAN ``default`` empty tier and ``default-lt`` linguistic type
  (auto-created by pympi) are filtered out on load if they have no
  annotations.

Spec: https://www.mpi.nl/tools/elan/EAFv3.0.xsd
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
from lacing.tier import Tier, TierStereotype
from lacing.time import DEFAULT_RATE, RationalTime, TimeInterval

if TYPE_CHECKING:
    from pympi import Eaf as _PympiEaf


ADAPTER_NAME = "eaf"
BODY_SCHEMA_URI = "annot://schema/eaf-label/v1"
DEFAULT_ASSET_ID = "eaf:unspecified"


# Constraint string in EAF ↔ TierStereotype enum value
_CONSTRAINT_TO_STEREOTYPE: dict[str, TierStereotype] = {
    "Time_Subdivision": TierStereotype.TIME_SUBDIVISION,
    "Included_In": TierStereotype.INCLUDED_IN,
    "Symbolic_Subdivision": TierStereotype.SYMBOLIC_SUBDIVISION,
    "Symbolic_Association": TierStereotype.SYMBOLIC_ASSOCIATION,
}
_STEREOTYPE_TO_CONSTRAINT: dict[TierStereotype, str] = {
    v: k for k, v in _CONSTRAINT_TO_STEREOTYPE.items()
}


class _MissingPympi(ImportError):
    """Raised when pympi-ling is not installed."""


def _require_pympi():
    try:
        from pympi import Eaf
    except ImportError as exc:
        raise _MissingPympi(
            "The 'eaf' adapter requires pympi-ling. Install with: "
            "pip install 'lacing[eaf]'  (or directly: pip install pympi-ling)"
        ) from exc
    return Eaf


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str | None = None,
    attribution: str = "anonymous",
    drop_default_tier: bool = True,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Load an ELAN EAF file into a ``MemoryStore``.

    Args:
        source: Path or bytes containing EAF XML.
        rate: Quantization rate (default ``DEFAULT_RATE``). EAF times are
            milliseconds; conversions must be exact.
        asset_id: Override media reference. None = use the first
            ``MEDIA_DESCRIPTOR/MEDIA_URL`` from the EAF, or the default.
        attribution: ``Provenance.was_attributed_to`` value.
        drop_default_tier: If True (default), filter out the empty
            ``default`` tier auto-created by pympi.
    """
    Eaf = _require_pympi()
    eaf = _open_eaf(source, Eaf)

    resolved_asset = asset_id or _first_media_url(eaf) or DEFAULT_ASSET_ID

    store = MemoryStore()
    now = RationalTime.zero(rate)

    # Build tiers: figure out stereotype from each tier's linguistic type.
    tier_to_stereotype: dict[str, TierStereotype] = {}
    for tier_name in eaf.get_tier_names():
        params = eaf.get_parameters_for_tier(tier_name)
        ling_id = params.get("LINGUISTIC_TYPE_REF")
        stereotype = TierStereotype.NONE
        if ling_id:
            ling_params = _safe_get_ling_params(eaf, ling_id)
            constraint = (ling_params or {}).get("CONSTRAINTS")
            if constraint in _CONSTRAINT_TO_STEREOTYPE:
                stereotype = _CONSTRAINT_TO_STEREOTYPE[constraint]
        tier_to_stereotype[tier_name] = stereotype

    for tier_name in eaf.get_tier_names():
        params = eaf.get_parameters_for_tier(tier_name)
        parent = params.get("PARENT_REF")
        annotations = eaf.get_annotation_data_for_tier(tier_name) or []

        if drop_default_tier and tier_name == "default" and not annotations:
            continue

        stereotype = tier_to_stereotype[tier_name]
        # ELAN allows a parent-less tier to declare a non-time constraint
        # at the linguistic type. Our model rejects that, so coerce to NONE.
        if parent is None and stereotype != TierStereotype.NONE:
            stereotype = TierStereotype.NONE

        tier_metadata: dict[str, Any] = {}
        if (p := params.get("PARTICIPANT")):
            tier_metadata["participant"] = p
        if (loc := params.get("DEFAULT_LOCALE")):
            tier_metadata["locale"] = loc
        if (ann := params.get("ANNOTATOR")):
            tier_metadata["annotator"] = ann

        store.add_tier(
            Tier(
                tier_name,
                stereotype=stereotype,
                parent=parent,
                metadata=tier_metadata,
            )
        )

        for entry in annotations:
            # Each entry is (start_ms, end_ms, value) for ALIGNABLE,
            # or (start_ms, end_ms, value, ref_id) for REF on some pympi versions.
            start_ms = entry[0]
            end_ms = entry[1]
            value = entry[2] if len(entry) > 2 else ""
            interval = TimeInterval(
                RationalTime.from_seconds(_ms_to_seconds_str(start_ms), rate=rate),
                RationalTime.from_seconds(_ms_to_seconds_str(end_ms), rate=rate),
            )
            store.add(
                Annotation(
                    id=uuid4(),
                    tier=tier_name,
                    reference=MediaRef(asset_id=resolved_asset, interval=interval),
                    body={"text": value},
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


def _open_eaf(source: str | bytes | os.PathLike, Eaf_cls) -> "_PympiEaf":
    if isinstance(source, (bytes, bytearray)):
        with tempfile.NamedTemporaryFile(
            "wb", suffix=".eaf", delete=False
        ) as f:
            f.write(source)
            tmp_path = f.name
        try:
            return Eaf_cls(tmp_path, suppress_version_warning=True)
        finally:
            os.unlink(tmp_path)
    return Eaf_cls(os.fspath(source), suppress_version_warning=True)


def _first_media_url(eaf: "_PympiEaf") -> str | None:
    """Pull the first linked media URL out of the EAF, if any."""
    descriptors = getattr(eaf, "media_descriptors", None) or []
    for d in descriptors:
        url = d.get("MEDIA_URL") or d.get("RELATIVE_MEDIA_URL")
        if url:
            return url
    return None


def _safe_get_ling_params(eaf: "_PympiEaf", ling_id: str) -> dict | None:
    """Look up a linguistic type's params; tolerant to missing types."""
    try:
        return eaf.get_parameters_for_linguistic_type(ling_id)
    except KeyError:
        return None


def _ms_to_seconds_str(ms: int | float) -> str:
    """Convert integer milliseconds to an exact seconds string.

    pympi annotations are nominally ``int`` but some files have stored
    floats; round (after asserting exactness) to recover the integer.
    """
    if isinstance(ms, float):
        if not ms.is_integer():
            raise ValueError(f"EAF time {ms!r} is not an integer millisecond")
        ms = int(ms)
    # Format as "{int}/1000" via decimal — Fraction(str) is exact.
    if ms >= 0:
        whole, frac = divmod(ms, 1000)
        return f"{whole}.{frac:03d}"
    whole, frac = divmod(-ms, 1000)
    return f"-{whole}.{frac:03d}"


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    pretty: bool = True,
    media_url: str | None = None,
    **_kwargs: Any,
) -> bytes | None:
    """Write annotations as an ELAN EAF file.

    Args:
        store: Source store. Only annotations with ``MediaRef`` and a
            non-None interval are exported.
        target: Output path. None = return bytes.
        pretty: Pretty-print XML (default True).
        media_url: Optional ``MEDIA_URL`` for ``MEDIA_DESCRIPTOR``. If
            None and the store has annotations, use the first MediaRef's
            ``asset_id``.
    """
    Eaf = _require_pympi()

    eaf = Eaf(suppress_version_warning=True)
    # pympi auto-creates a "default" tier; remove it so we don't pollute the file.
    if "default" in eaf.get_tier_names():
        eaf.remove_tier("default")

    annotations = list(_all_with_intervals(store))

    # Resolve media URL.
    chosen_media: str | None = media_url
    if chosen_media is None:
        for a in annotations:
            ref = a.reference
            if hasattr(ref, "asset_id") and ref.asset_id:
                chosen_media = ref.asset_id
                break
    if chosen_media:
        eaf.add_linked_file(chosen_media, mimetype="audio/x-wav")

    # Group annotations by tier, building tiers in dependency order so
    # parents are created before children (ELAN requires this).
    annotations_by_tier: dict[str, list[Annotation]] = {}
    for a in annotations:
        annotations_by_tier.setdefault(a.tier, []).append(a)

    declared_tiers: list[Tier] = list(_collect_tiers(store))
    referenced_tier_names = {a.tier for a in annotations}
    declared_names = {t.name for t in declared_tiers}
    for name in referenced_tier_names - declared_names:
        declared_tiers.append(Tier(name))  # NONE stereotype, no parent

    for tier in _topo_sort_tiers(declared_tiers):
        ling_id = _linguistic_type_for_tier(tier)
        if ling_id not in eaf.get_linguistic_type_names():
            constraint = _STEREOTYPE_TO_CONSTRAINT.get(tier.stereotype)
            eaf.add_linguistic_type(
                ling_id,
                constraints=constraint,
                timealignable=True,
            )
        eaf.add_tier(
            tier.name,
            ling=ling_id,
            parent=tier.parent,
            part=tier.metadata.get("participant"),
            locale=tier.metadata.get("locale"),
            ann=tier.metadata.get("annotator"),
        )

    # Add annotations now that all tiers exist.
    for a in annotations:
        iv = a.interval
        assert iv is not None  # filtered upstream
        start_ms = _seconds_to_ms_int(iv.start)
        end_ms = _seconds_to_ms_int(iv.end)
        text = a.body.get("text", "") if isinstance(a.body, dict) else ""
        if start_ms == end_ms:
            # ELAN doesn't support zero-length alignable annotations; widen
            # by 1 ms to make a valid interval. Document as a known lossy edge.
            end_ms = start_ms + 1
        eaf.add_annotation(a.tier, start_ms, end_ms, str(text))

    if target is None:
        with tempfile.NamedTemporaryFile(
            suffix=".eaf", delete=False
        ) as f:
            tmp_path = f.name
        try:
            eaf.to_file(tmp_path, pretty=pretty)
            return Path(tmp_path).read_bytes()
        finally:
            os.unlink(tmp_path)

    eaf.to_file(os.fspath(target), pretty=pretty)
    return None


def _seconds_to_ms_int(t: RationalTime) -> int:
    """Convert a RationalTime to an integer ms; raises if not exact."""
    f = t.to_fraction() * 1000
    if f.denominator != 1:
        raise ValueError(
            f"RationalTime {t!r} cannot be expressed as integer milliseconds"
        )
    return int(f)


def _collect_tiers(store: IntervalAnnotationStore) -> list[Tier]:
    tiers_iter = getattr(store, "tiers", None)
    if callable(tiers_iter):
        return list(tiers_iter())
    return []


def _topo_sort_tiers(tiers: list[Tier]) -> list[Tier]:
    """Return tiers in dependency order (parents before children).

    Cycles or missing parents fall back to the input order — pympi will
    raise its own error if the parent is missing.
    """
    by_name = {t.name: t for t in tiers}
    visited: set[str] = set()
    out: list[Tier] = []

    def visit(t: Tier) -> None:
        if t.name in visited:
            return
        if t.parent and t.parent in by_name and t.parent not in visited:
            visit(by_name[t.parent])
        visited.add(t.name)
        out.append(t)

    for t in tiers:
        visit(t)
    return out


def _linguistic_type_for_tier(tier: Tier) -> str:
    """Pick a linguistic type id for a tier when emitting EAF.

    We use one linguistic type per (stereotype) so multiple tiers with
    the same shape share a type — keeps the EAF file compact and readable.
    """
    if tier.stereotype == TierStereotype.NONE:
        return "default-lt"
    return f"lt_{tier.stereotype.value.lower()}"


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
    extensions=(".eaf",),
    media_types=("application/x-eaf+xml",),
    body_schema_uris=(BODY_SCHEMA_URI,),
    description=(
        "ELAN EAF (Max Planck Institute). Maps the four ELAN tier "
        "stereotypes verbatim. Lossy: drops per-annotation provenance, "
        "confidence, REF_ANNOTATION (Phase 2), and controlled vocabularies."
    ),
)
