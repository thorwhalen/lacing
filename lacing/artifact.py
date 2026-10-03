"""Content-addressed artifact references.

An :class:`Artifact` is a generated file (or remote URL) with provenance.
Anything that *produces* media — a fal.ai call, a ``ffmpeg`` compose, a
storyboard PDF render, an audio synthesis — returns an ``Artifact``.
Anything that *references* an artifact temporally does so via
``MediaRef(asset_id=artifact.asset_id, interval=…)``.

This type lives in lacing (not in falaw or any single producer) because:

- It reuses :class:`lacing.Provenance` and :class:`lacing.MediaRef`. The
  ``asset_id`` *is* the content hash that ``MediaRef`` already documents.
- Multiple producers (falaw, an, nw, artful, mixing) need to express
  "I produced a file." Putting ``Artifact`` in any one of them forces a
  wrong-direction dependency from the others.
- The provenance chain (``was_derived_from``, ``was_generated_by``) is the
  same shape for an annotation and an artifact. Reusing it unifies lineage.

Hashing
-------

``asset_id`` is the SHA-256 hex digest of the artifact's bytes. SHA-256 is
in the stdlib, deterministic, and compatible with the
``MediaRef.asset_id`` documentation ("BLAKE3 / SHA-256"). Producers may use
BLAKE3 if they prefer; the consumer treats ``asset_id`` opaquely.

Examples
--------

>>> from pathlib import Path
>>> from lacing.artifact import Artifact, hash_file
>>> # Create one from a path:
>>> import tempfile
>>> with tempfile.NamedTemporaryFile("wb", suffix=".bin", delete=False) as f:
...     _ = f.write(b"hello world")
...     p = Path(f.name)
>>> a = Artifact.from_path(p, kind="text", was_generated_by="test:doctest",
...                        was_attributed_to="user:thor")
>>> a.kind
'text'
>>> a.bytes_size
11
>>> len(a.asset_id) == 64  # SHA-256 hex
True
>>> a.path == p
True

An artifact that was *acquired* rather than made carries a :class:`Rights`
record (``None`` means "we made this", not "unknown"):

>>> from lacing.artifact import Rights
>>> a = Artifact.from_bytes(b"png", kind="image", was_generated_by="fetch:openverse",
...     was_attributed_to="user:thor",
...     rights=Rights(provider="openverse", license="by-sa", author="Ada"))
>>> a.rights.license
'by-sa'
>>> Artifact.from_bytes(b"x", kind="text", was_generated_by="t",
...     was_attributed_to="u").rights is None
True

Round-trip through JSON:

>>> import json
>>> data = a.model_dump_json()
>>> b = Artifact.model_validate_json(data)
>>> b.asset_id == a.asset_id
True
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    field_validator,
    model_serializer,
)

from lacing.model import Provenance, ProvenanceRef
from lacing.time import RationalTime


ArtifactKind = Literal["image", "video", "audio", "json", "text", "binary"]
"""Coarse mime-class. Producers should pick the closest match; consumers
should switch on this *before* falling back to ``mime``/``path.suffix``."""


def _now_rt() -> RationalTime:
    """Deprecated private alias for :meth:`RationalTime.now`.

    Kept because ``nw``, ``falaw``, and ``artful`` import this symbol. New
    code should call ``RationalTime.now()`` directly.
    """
    return RationalTime.now()


def hash_bytes(data: bytes) -> str:
    """Return the canonical ``asset_id`` (SHA-256 hex) for ``data``.

    >>> hash_bytes(b"hello world")[:8]
    'b94d27b9'
    """
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path | str, *, chunk_size: int = 1 << 20) -> str:
    """Return the canonical ``asset_id`` (SHA-256 hex) for the file at ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


class Rights(BaseModel):
    """Who owns the bytes of an *acquired* artifact, and on what terms.

    The fields a Creative-Commons-family licence needs to discharge its
    attribution duty (title, author, source, licence: "TASL"), named
    literal-for-literal after the two records the federation already keeps —
    ``illustration.ImageResult`` and ``an.ir.assets.AssetSource`` — so both map
    onto this one without a rename table (``provider``, ``id``, ``license``,
    ``license_url``, ``attribution``, ``source_page_url``, ``author``,
    ``author_url``, ``cacheable``).

    Semantics worth the trap they avoid:

    - **``Artifact.rights is None`` means "we made this"**, not "unknown". An
      acquired artifact whose terms nobody recorded is a ``Rights`` with only
      ``provider`` set.
    - **``license is None`` means UNKNOWN, never unencumbered.** Free of
      obligations is stated, e.g. ``license="cc0-1.0"``.
    - **``cacheable is None`` means not stated**; ``False`` forbids keeping the
      bytes, ``True`` permits it.
    - ``license`` is an SPDX id (``"CC-BY-4.0"``) or a provider's own code
      (``"by-sa"``); lacing records it verbatim and never classifies it
      (classification lives with the consumer, e.g. ``an``'s licence classes).
    - The record describes **this artifact's own bytes**. A render that embeds
      a third-party image carries no ``Rights`` of its own; its obligations
      travel through ``provenance.was_derived_from`` and are rolled up by the
      consumer. ``rights is None`` on a derivative is *not* a clearance.

    ``provider`` is required, so an empty ``Rights()`` cannot exist: an
    artifact either has no record (we made it) or says where it came from.
    Text fields are ``None`` or non-blank; a blank string is refused.

    Caveat: an artifact catalog is keyed by ``asset_id`` (the content hash), so
    two records for the *same bytes* are one row and the last write wins. A
    rights-less record written after an acquired one with identical bytes
    replaces it, rights included. Writers that re-record bytes they already
    hold must carry the existing ``rights`` forward.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    provider: str = Field(
        ..., min_length=1, description="Where it came from, e.g. 'openverse'."
    )
    id: str | None = Field(None, description="Provider-native identifier.")
    title: str | None = Field(
        None, description="Work title, for attribution (the T of TASL)."
    )
    license: str | None = Field(
        None,
        description=(
            "SPDX id or provider licence code, verbatim. None means UNKNOWN, "
            "not unencumbered."
        ),
    )
    license_url: str | None = Field(None, description="Canonical licence text URL.")
    attribution: str | None = Field(
        None, description="Ready-to-render attribution sentence."
    )
    source_page_url: str | None = Field(
        None, description="The page the work was found on (the S of TASL)."
    )
    author: str | None = Field(None, description="Creator or rights holder.")
    author_url: str | None = Field(None, description="Creator's profile or page.")
    cacheable: StrictBool | None = Field(
        None,
        description=(
            "May the bytes be kept/redistributed from our storage? None means "
            "not stated. Strict: a string like 'yes' is refused, not coerced."
        ),
    )

    @field_validator(
        "provider",
        "id",
        "title",
        "license",
        "license_url",
        "attribution",
        "source_page_url",
        "author",
        "author_url",
    )
    @classmethod
    def _no_blank_text(cls, value: str | None) -> str | None:
        # "" is neither "unknown" (None) nor a licence; refuse it rather than
        # let a blank string stand in for a statement nobody made.
        if value is not None and not value.strip():
            raise ValueError("must be None or non-blank text, not an empty string")
        return value


class Artifact(BaseModel):
    """A content-addressed generated file with provenance.

    ``asset_id`` is the SHA-256 hex digest of the artifact's bytes. Two
    artifacts with the same ``asset_id`` are byte-identical regardless of
    where they live — so caches keyed on ``asset_id`` are safe across
    machines and re-runs.

    ``provenance`` reuses :class:`lacing.Provenance` so the lineage chain
    (``was_derived_from``, ``was_generated_by``) is the same for artifacts
    and annotations. An annotation referencing an artifact does so via
    ``MediaRef(asset_id=artifact.asset_id, …)``.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    asset_id: str = Field(
        ...,
        description="SHA-256 hex digest of the bytes (canonical content hash).",
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    kind: ArtifactKind = Field(..., description="Coarse mime-class.")
    path: Path | None = Field(
        None,
        description="Local filesystem path, if the artifact is stored locally.",
    )
    url: str | None = Field(
        None,
        description="Remote URL (https / s3 / gs / signed) if the artifact lives remotely.",
    )
    bytes_size: int = Field(..., ge=0, description="Size of the artifact in bytes.")
    duration_s: float | None = Field(
        None, ge=0, description="Duration in seconds (for audio/video)."
    )
    mime: str | None = Field(
        None, description='Optional precise mime, e.g. "image/png", "video/mp4".'
    )
    provenance: Provenance = Field(
        ...,
        description=(
            "Who/when/why this artifact was generated. Reuses lacing.Provenance "
            "so artifact + annotation lineage chains are unified."
        ),
    )
    cost_usd: float | None = Field(
        None,
        ge=0,
        description=(
            "Spend attributed to producing this artifact, stamped by the "
            "producer from the OBSERVED run outcome (falaw stamps 0.0 for a "
            "cache hit — a known zero — and its rate-card estimate for a "
            "billed call). An estimate of billing, not a vendor receipt; "
            "None means unknown, never free."
        ),
    )
    producer_call_id: str | None = Field(
        None,
        description=(
            "Opaque producer-side call identifier — e.g. ``fal_call_id``, "
            "``mixing_op_id`` — for tracing back to the producer's event log."
        ),
    )
    rights: Rights | None = Field(
        None,
        description=(
            "Ownership and licence of an ACQUIRED artifact. None means we made "
            "it (not 'unknown'); an acquired artifact with unrecorded terms is "
            "a Rights with only ``provider``. Describes this artifact's own "
            "bytes; a derivative's obligations travel via provenance."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_absent_rights(self, handler):
        """Leave ``rights`` out of the dump when it is ``None``.

        ``Artifact`` is ``extra="forbid"`` and lives in deployed catalogs, so a
        reader built before ``rights`` existed refuses ``"rights": null`` just
        as it refuses a real record. Omitting the absent field keeps every
        artifact that has no rights byte-compatible with the pre-``rights``
        format: only an artifact that *has* a record needs a new reader.
        Validation is unaffected: a missing key and an explicit ``null`` both
        load as ``None``.
        """
        data = handler(self)
        if data.get("rights", ...) is None:
            data.pop("rights")
        return data

    # -- constructors --------------------------------------------------------

    @classmethod
    def from_path(
        cls,
        path: Path | str,
        *,
        kind: ArtifactKind,
        was_generated_by: str,
        was_attributed_to: str,
        was_derived_from: "tuple[ProvenanceRef, ...]" = (),
        activity: str = "create",
        generated_at_time: RationalTime | None = None,
        duration_s: float | None = None,
        mime: str | None = None,
        cost_usd: float | None = None,
        producer_call_id: str | None = None,
        rights: Rights | None = None,
    ) -> Artifact:
        """Create an Artifact from a local file. Hashes the file's bytes."""
        path = Path(path)
        if generated_at_time is None:
            generated_at_time = _now_rt()
        prov = Provenance(
            was_generated_by=was_generated_by,
            was_attributed_to=was_attributed_to,
            was_derived_from=list(was_derived_from),
            generated_at_time=generated_at_time,
            activity=activity,
        )
        return cls(
            asset_id=hash_file(path),
            kind=kind,
            path=path,
            url=None,
            bytes_size=path.stat().st_size,
            duration_s=duration_s,
            mime=mime,
            provenance=prov,
            cost_usd=cost_usd,
            producer_call_id=producer_call_id,
            rights=rights,
        )

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        kind: ArtifactKind,
        was_generated_by: str,
        was_attributed_to: str,
        path: Path | str | None = None,
        url: str | None = None,
        was_derived_from: "tuple[ProvenanceRef, ...]" = (),
        activity: str = "create",
        generated_at_time: RationalTime | None = None,
        duration_s: float | None = None,
        mime: str | None = None,
        cost_usd: float | None = None,
        producer_call_id: str | None = None,
        rights: Rights | None = None,
    ) -> Artifact:
        """Create an Artifact from in-memory bytes."""
        if generated_at_time is None:
            generated_at_time = _now_rt()
        prov = Provenance(
            was_generated_by=was_generated_by,
            was_attributed_to=was_attributed_to,
            was_derived_from=list(was_derived_from),
            generated_at_time=generated_at_time,
            activity=activity,
        )
        return cls(
            asset_id=hash_bytes(data),
            kind=kind,
            path=Path(path) if path is not None else None,
            url=url,
            bytes_size=len(data),
            duration_s=duration_s,
            mime=mime,
            provenance=prov,
            cost_usd=cost_usd,
            producer_call_id=producer_call_id,
            rights=rights,
        )

    # -- helpers -------------------------------------------------------------

    def to_media_ref(self, interval) -> "MediaRef":
        """Return a :class:`lacing.MediaRef` pointing at this artifact.

        Use this to attach an annotation to a region of the artifact:
        ``MediaRef(asset_id=artifact.asset_id, interval=…)``.
        """
        from lacing.model import MediaRef

        return MediaRef(asset_id=self.asset_id, interval=interval)
