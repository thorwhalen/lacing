"""High-level "track-shaped" facades on top of ``lacing``.

A ``track`` is an opinionated bundle of tiers that shows up in the wild
together. ``subtitle`` is the canonical example: ``sections``,
``lines``, ``words`` over one audio asset, with a builder that hides
the ``Annotation`` / ``MediaRef`` / ``Provenance`` plumbing and a
query layer that takes ``float`` seconds instead of ``RationalTime``.

These facades sit *on top of* the core store/tier/annotation API —
they don't introduce new storage. Anything you can build with a
track facade can be built with the raw API; the facade just makes
the common case ergonomic and consistent.
"""

from lacing.tracks.subtitle import (
    BUILT_IN_BODY_SCHEMAS,
    SubtitleBuilder,
    SubtitleTrack,
    register_subtitle_schemas,
)

__all__ = [
    "BUILT_IN_BODY_SCHEMAS",
    "SubtitleBuilder",
    "SubtitleTrack",
    "register_subtitle_schemas",
]
