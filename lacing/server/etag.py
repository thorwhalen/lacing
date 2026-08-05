"""ETag computation and ``If-Match`` validation.

We use a stable ``Annotation``-content hash as the ETag (BLAKE2b of the
canonical JSON dump). On mutation, callers must send ``If-Match: "<etag>"``;
mismatch yields HTTP 412 Precondition Failed.

This is the optimistic-concurrency primitive recommended in BACK-DOC §3.3.

**Not** the freshness digest — do not collapse the two. ``annotation_etag``
covers the *whole* annotation including ``id`` (a fresh ``uuid4`` on every
regeneration) and ``provenance.generated_at_time``, so it changes on every
run even when the content is byte-identical. That is exactly right for
``If-Match`` / HTTP 412 and exactly wrong for early cutoff. The freshness
digest is :func:`lacing.annotation_value_digest` in :mod:`lacing.digest`,
which lives in core precisely because importing anything under
``lacing.server`` pulls in FastAPI. Two digests, two jobs; neither
substitutes for the other.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from lacing.model import Annotation


def annotation_etag(annotation: Annotation) -> str:
    """Compute a stable content-based ETag for ``annotation``.

    Uses ``Annotation.model_dump(mode='json')`` so embedded ``RationalTime``
    values serialize via their wire form. Result is a quoted hex digest,
    matching RFC 7232 (``ETag: "..."`` syntax).
    """
    payload = annotation.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.blake2b(canonical.encode("utf-8"), digest_size=16).hexdigest()
    return f'"{digest}"'


def parse_if_match(header_value: str | None) -> str | None:
    """Strip ``W/`` weak prefix and split comma-separated values.

    Returns the first ETag in the list, or None if the header is missing.
    A wildcard ``*`` is returned as-is (per RFC 7232 §3.1).
    Raises ``ValueError`` on a malformed header.
    """
    if not header_value:
        return None
    # Take the first ETag; spec allows a list. We don't support W/ weak ETags.
    first = header_value.split(",", 1)[0].strip()
    if first == "*":
        return "*"
    if first.startswith("W/"):
        first = first[2:]
    if not (first.startswith('"') and first.endswith('"')):
        raise ValueError(f"malformed If-Match header value: {header_value!r}")
    return first


def matches(etag: str, if_match: str | None) -> bool:
    """Strict comparison of an ETag against an ``If-Match`` candidate.

    A wildcard ``*`` matches any ETag (per RFC 7232 §3.1).
    """
    if if_match is None:
        return False
    if if_match == "*":
        return True
    return etag == if_match
