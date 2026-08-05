"""Content digests over an annotation's *value* — the freshness primitive.

lacing has **three** digests and they answer **three different questions**.
Collapsing any two of them is a silent correctness bug, so the boundary is
spelled out here and cross-referenced from the other two:

- :func:`lacing.hash_bytes` / :func:`lacing.hash_file` — SHA-256 over an
  **artifact's bytes**. Answers *"are these two files the same file?"*. This
  is the ``Artifact.asset_id`` contract (:mod:`lacing.artifact`).
- :func:`lacing.server.etag.annotation_etag` — BLAKE2b-128 over the **whole
  annotation**, ``id`` and ``provenance`` included. Answers *"has this record
  been touched since I read it?"*. This is the ``If-Match`` / HTTP 412
  optimistic-concurrency primitive, and it is *deliberately* unstable across
  regenerations.
- :func:`annotation_value_digest` (this module) — SHA-256 over an annotation's
  **value**, ``id`` and ``provenance`` excluded. Answers *"did the answer
  actually change?"*. This is the freshness / early-cutoff primitive.

A regeneration that produces byte-identical content mints a fresh ``uuid4``
``id`` and a fresh ``provenance.generated_at_time``, so ``annotation_etag``
changes while ``annotation_value_digest`` does not. That difference is the
entire point: it lets a downstream freshness check key on *upstream output
values* rather than on *upstream keys*, and stop propagating invalidation
when nothing actually changed.

Why this lives in core and not under ``lacing/server/``
--------------------------------------------------------
``annotation_etag`` sits at ``lacing/server/etag.py``. Its own imports are
cheap, but importing any submodule of ``lacing.server`` executes
``lacing/server/__init__.py``, which imports the FastAPI app. The value
digest is consumed by the *execution* tier (``nw``, ``falaw``), which must
not drag a web framework in. This module therefore has **no runtime imports
beyond the standard library** — the :class:`~lacing.model.Annotation` import
is type-checking only.

The inclusion boundary — and why each call was made
----------------------------------------------------
Getting this boundary wrong is a silent wrong-cache-**hit**, not a miss, so
each field is justified rather than assumed.

**Included** (:data:`VALUE_FIELDS`):

- ``body`` — it *is* the annotation's value. Trivially included.
- ``body_schema_uri`` — the same ``dict`` means different things under
  different schemas, and a schema-version bump is a semantic change even when
  the payload bytes are unchanged. Excluding it would let a ``.../v1`` body
  satisfy a ``.../v2`` consumer's cache lookup.
- ``tier`` — the tier is part of what the annotation asserts (which layer of
  the analysis this claim belongs to), and lacing's tier stereotypes impose
  structural constraints. Two identical bodies on different tiers are
  different claims.
- ``reference`` — what the annotation is *about*: the asset and the interval.
  Re-timing an annotation changes its value. This is the one genuinely
  contested call (see below); it is included here and excluded from
  :func:`annotation_body_digest`, so the consumer chooses rather than guesses.
- ``confidence`` — a soft label whose confidence moved is a changed assertion.
  Downstream thresholding consumes it directly.

**Excluded**:

- ``id`` — a fresh ``uuid4`` on every regeneration. Including it makes the
  digest change unconditionally, which is exactly the ``annotation_etag``
  behaviour this function exists to avoid.
- ``provenance`` — ``generated_at_time`` changes on every run, and
  ``was_generated_by`` / ``was_derived_from`` describe *how* the value was
  reached, not *what* it is. Two byte-identical answers produced by different
  activities are the same answer. (If a consumer needs to invalidate on a
  changed producer, that belongs in its **cache key** — which is keyed on
  inputs — not in the **value digest**, which addresses the output.)

Rule of thumb, stated once: *key the cache on inputs; address the value by
content; record both in the trace.* A system with only the first cannot cut
off early.

``reference``: two functions, not a boolean
--------------------------------------------
Whether ``reference`` belongs in a value digest is genuinely
consumer-dependent. A :class:`~lacing.model.MediaRef` carries an
``interval``, so re-timing busts every downstream digest — **correct** when
downstream consumes the timing (an animatic, a cut list), **wasteful** when
it consumes only the body (a caption translation). Rather than a boolean flag
or a wrong guess that needs migrating later, this module ships both:

- :func:`annotation_value_digest` — the full value, ``reference`` included.
  **The default.** Use it unless you can state why timing is irrelevant.
- :func:`annotation_body_digest` — ``{body, body_schema_uri}`` only.

They are domain-separated (see :data:`VALUE_DIGEST_SCHEME`), so the two can
never collide even on an annotation whose payloads coincide.

Stability guarantees, and their limits
---------------------------------------
The digest is stable **across processes**, **across dict insertion order**
(``sort_keys=True`` canonicalises recursively) and **across a store
round-trip** (memory → ``.annot`` → memory).

Two limits, both of which fail in the *conservative* direction — a spurious
cache **miss**, never a wrong **hit**:

1. The digest is over the canonical JSON *serialisation*, and
   :class:`~lacing.time.RationalTime` serialises as ``{"v": …, "r": …}``.
   ``RationalTime(1, 24)`` and ``RationalTime(2, 48)`` compare **equal** but
   serialise differently, so a rate change re-times the digest even when the
   instant is unchanged. (``annotation_etag`` has the same property.)
2. A ``body`` carrying a non-JSON Python value is outside the ``body``
   contract (bodies are validated against JSON Schema). A ``set`` serialises
   to a list in an order that is not stable across processes; a type pydantic
   cannot serialise at all raises ``PydanticSerializationError`` rather than
   digesting a ``repr`` that embeds a memory address.

Changing :data:`VALUE_FIELDS` or the canonicalisation is a **breaking cache
invalidation event** for every consumer: every digest changes at once. Bump
the scheme string when you do it, so the change is legible in a trace.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from lacing.model import Annotation


__all__ = [
    "annotation_value_digest",
    "annotation_body_digest",
    "VALUE_FIELDS",
    "BODY_FIELDS",
    "VALUE_DIGEST_SCHEME",
    "BODY_DIGEST_SCHEME",
]


VALUE_FIELDS: tuple[str, ...] = (
    "body",
    "body_schema_uri",
    "confidence",
    "reference",
    "tier",
)
"""Annotation fields that constitute its *value*. See the module docstring for
why each is in, and why ``id`` and ``provenance`` are out."""

BODY_FIELDS: tuple[str, ...] = ("body", "body_schema_uri")
"""The narrower payload for :func:`annotation_body_digest` — no ``reference``,
so re-timing does not bust the digest."""

VALUE_DIGEST_SCHEME = "lacing/annotation-value-digest/v1"
"""Domain-separation tag mixed into :func:`annotation_value_digest`."""

BODY_DIGEST_SCHEME = "lacing/annotation-body-digest/v1"
"""Domain-separation tag mixed into :func:`annotation_body_digest`."""


def annotation_value_digest(annotation: "Annotation") -> str:
    """Return the SHA-256 hex digest of ``annotation``'s value.

    Covers ``body``, ``body_schema_uri``, ``tier``, ``reference`` and
    ``confidence``. Excludes ``id`` and ``provenance``, so a regeneration that
    produces identical content produces an identical digest.

    Use this for freshness and early cutoff. For optimistic concurrency use
    :func:`lacing.server.etag.annotation_etag` instead — two digests, two
    jobs, and neither substitutes for the other.

    >>> from uuid import uuid4
    >>> from lacing import Annotation, MediaRef, Provenance
    >>> from lacing import RationalTime, TimeInterval
    >>> def make(**kw):
    ...     base = dict(
    ...         id=uuid4(),
    ...         tier="words",
    ...         reference=MediaRef(
    ...             asset_id="sha256:abc",
    ...             interval=TimeInterval(RationalTime(0), RationalTime(24000)),
    ...         ),
    ...         body={"text": "hello"},
    ...         body_schema_uri="annot://schema/word/v1",
    ...         provenance=Provenance(
    ...             was_generated_by="agent:m@1",
    ...             was_attributed_to="thor",
    ...             generated_at_time=RationalTime(0),
    ...         ),
    ...     )
    ...     base.update(kw)
    ...     return Annotation(**base)

    A regeneration — new ``id``, new timestamp, same content — digests the same:

    >>> a = make()
    >>> b = make(provenance=Provenance(
    ...     was_generated_by="agent:m@1",
    ...     was_attributed_to="thor",
    ...     generated_at_time=RationalTime(999),
    ... ))
    >>> annotation_value_digest(a) == annotation_value_digest(b)
    True

    A changed body does not:

    >>> annotation_value_digest(make(body={"text": "goodbye"})) == (
    ...     annotation_value_digest(a)
    ... )
    False
    """
    return _digest(VALUE_DIGEST_SCHEME, _payload(annotation, VALUE_FIELDS))


def annotation_body_digest(annotation: "Annotation") -> str:
    """Return the SHA-256 hex digest of ``{body, body_schema_uri}`` only.

    The narrow sibling of :func:`annotation_value_digest`, for consumers that
    demonstrably do **not** depend on *when* or *what* the annotation points
    at — only on what it says. Re-timing an annotation leaves this digest
    unchanged, which is a correctness bug if the consumer actually reads the
    interval. Prefer :func:`annotation_value_digest` unless you can state why
    timing is irrelevant to the downstream computation.

    >>> from uuid import uuid4
    >>> from lacing import Annotation, MediaRef, Provenance
    >>> from lacing import RationalTime, TimeInterval
    >>> def make(interval):
    ...     return Annotation(
    ...         id=uuid4(),
    ...         tier="words",
    ...         reference=MediaRef(asset_id="sha256:abc", interval=interval),
    ...         body={"text": "hello"},
    ...         body_schema_uri="annot://schema/word/v1",
    ...         provenance=Provenance(
    ...             was_generated_by="agent:m@1",
    ...             was_attributed_to="thor",
    ...             generated_at_time=RationalTime(0),
    ...         ),
    ...     )
    >>> early = make(TimeInterval(RationalTime(0), RationalTime(24000)))
    >>> late = make(TimeInterval(RationalTime(24000), RationalTime(48000)))
    >>> annotation_body_digest(early) == annotation_body_digest(late)
    True
    >>> annotation_value_digest(early) == annotation_value_digest(late)
    False
    """
    return _digest(BODY_DIGEST_SCHEME, _payload(annotation, BODY_FIELDS))


# --- internals ---------------------------------------------------------------


def _payload(annotation: "Annotation", fields: Sequence[str]) -> dict[str, Any]:
    """Project ``annotation``'s JSON-mode dump onto ``fields``.

    Dumping the whole model once and projecting is deliberate: it routes every
    field through pydantic's JSON serializer, so ``RationalTime`` reaches the
    canonicaliser in its ``{v, r}`` wire form and non-string ``body`` keys are
    coerced to strings (``json.dumps(sort_keys=True)`` raises on mixed key
    types). Hand-assembling the payload from raw attributes reintroduces both
    hazards.
    """
    dumped = annotation.model_dump(mode="json")
    return {field: dumped[field] for field in fields}


def _digest(scheme: str, payload: dict[str, Any]) -> str:
    """SHA-256 hex over ``scheme`` plus the canonical JSON of ``payload``.

    ``sort_keys=True`` canonicalises dict ordering recursively, which is what
    makes the digest independent of insertion order and stable across
    processes. ``scheme`` is a domain-separation tag: without it, two digest
    functions in this module whose payloads happened to coincide would return
    the same hex for different questions.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{scheme}\n{canonical}".encode("utf-8")).hexdigest()
