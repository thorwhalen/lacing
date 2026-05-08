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

from pydantic import BaseModel, Field

from lacing.model import Provenance
from lacing.time import RationalTime


ArtifactKind = Literal["image", "video", "audio", "json", "text", "binary"]
"""Coarse mime-class. Producers should pick the closest match; consumers
should switch on this *before* falling back to ``mime``/``path.suffix``."""


def _now_rt() -> RationalTime:
    """Wall-clock time as a RationalTime, quantized to DEFAULT_RATE.

    Uses ``time.time_ns()`` and constructs the Fraction directly to avoid
    the float-quantization landmine of ``RationalTime.from_seconds(float)``.
    """
    from fractions import Fraction
    import time as _time
    from lacing.time import DEFAULT_RATE
    ns = _time.time_ns()
    # ns / 1e9 seconds, exactly. Quantize to DEFAULT_RATE by rounding.
    # rate=24000 ⇒ each sample is 1/24000s = ~41666.6ns; round to nearest sample.
    samples = (ns * DEFAULT_RATE + 500_000_000) // 1_000_000_000
    return RationalTime.from_fraction(Fraction(samples, DEFAULT_RATE), rate=DEFAULT_RATE)


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
    bytes_size: int = Field(
        ..., ge=0, description="Size of the artifact in bytes."
    )
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
        description="Actual spend (not estimate) for producing this artifact, if known.",
    )
    producer_call_id: str | None = Field(
        None,
        description=(
            "Opaque producer-side call identifier — e.g. ``fal_call_id``, "
            "``mixing_op_id`` — for tracing back to the producer's event log."
        ),
    )

    # -- constructors --------------------------------------------------------

    @classmethod
    def from_path(
        cls,
        path: Path | str,
        *,
        kind: ArtifactKind,
        was_generated_by: str,
        was_attributed_to: str,
        was_derived_from: tuple = (),
        activity: str = "create",
        generated_at_time: RationalTime | None = None,
        duration_s: float | None = None,
        mime: str | None = None,
        cost_usd: float | None = None,
        producer_call_id: str | None = None,
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
        was_derived_from: tuple = (),
        activity: str = "create",
        generated_at_time: RationalTime | None = None,
        duration_s: float | None = None,
        mime: str | None = None,
        cost_usd: float | None = None,
        producer_call_id: str | None = None,
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
        )

    # -- helpers -------------------------------------------------------------

    def to_media_ref(self, interval) -> "MediaRef":
        """Return a :class:`lacing.MediaRef` pointing at this artifact.

        Use this to attach an annotation to a region of the artifact:
        ``MediaRef(asset_id=artifact.asset_id, interval=…)``.
        """
        from lacing.model import MediaRef
        return MediaRef(asset_id=self.asset_id, interval=interval)
