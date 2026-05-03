"""I/O adapter registry.

The core never imports a format module. Each adapter registers itself by
calling :func:`register_adapter` at import time. Users opt in by importing
the adapter module:

    from lacing.adapters import textgrid  # noqa: F401  — registers itself

Or by using the convenience top-level loaders that look up by extension or
``media_type``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lacing.store import IntervalAnnotationStore


LoadFn = Callable[..., IntervalAnnotationStore]
DumpFn = Callable[..., bytes | None]


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    """Registered adapter for one format."""

    name: str
    extensions: tuple[str, ...]
    media_types: tuple[str, ...]
    load: LoadFn
    dump: DumpFn
    body_schema_uris: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""


_REGISTRY: dict[str, AdapterSpec] = {}


def register_adapter(
    *,
    name: str,
    load: LoadFn,
    dump: DumpFn,
    extensions: tuple[str, ...] = (),
    media_types: tuple[str, ...] = (),
    body_schema_uris: tuple[str, ...] = (),
    description: str = "",
) -> AdapterSpec:
    """Register an adapter. Idempotent: re-registering the same name replaces."""
    spec = AdapterSpec(
        name=name,
        extensions=tuple(e.lower() for e in extensions),
        media_types=tuple(media_types),
        load=load,
        dump=dump,
        body_schema_uris=tuple(body_schema_uris),
        description=description,
    )
    _REGISTRY[name] = spec
    return spec


def get_adapter(name: str) -> AdapterSpec:
    """Look up an adapter by name. Raises ``KeyError`` if missing."""
    return _REGISTRY[name]


def find_adapter(
    *, extension: str | None = None, media_type: str | None = None
) -> AdapterSpec | None:
    """Find an adapter by extension (case-insensitive) or media type."""
    if extension is not None:
        ext = extension.lower()
        if not ext.startswith("."):
            ext = "." + ext
        for spec in _REGISTRY.values():
            if ext in spec.extensions:
                return spec
    if media_type is not None:
        for spec in _REGISTRY.values():
            if media_type in spec.media_types:
                return spec
    return None


def registered() -> list[AdapterSpec]:
    """All currently registered adapters (in registration order)."""
    return list(_REGISTRY.values())


def load(
    source: str | bytes | os.PathLike,
    *,
    format: str | None = None,
    **kwargs: Any,
) -> IntervalAnnotationStore:
    """Convenience: dispatch ``source`` to the right adapter.

    If ``format`` is given, looks up by name. Otherwise, if ``source`` is a
    path, infers from extension. Raises ``ValueError`` if it can't pick.
    """
    spec = _resolve_adapter(source, format)
    return spec.load(source, **kwargs)


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    format: str,
    **kwargs: Any,
) -> bytes | None:
    """Convenience: serialize ``store`` via the named adapter."""
    spec = get_adapter(format)
    return spec.dump(store, target, **kwargs)


def _resolve_adapter(source: Any, format: str | None) -> AdapterSpec:
    if format is not None:
        return get_adapter(format)
    if isinstance(source, (str, os.PathLike)) and not isinstance(source, bytes):
        ext = os.path.splitext(os.fspath(source))[1]
        if ext:
            spec = find_adapter(extension=ext)
            if spec is not None:
                return spec
    raise ValueError(
        "Cannot infer adapter: pass `format=<name>` or use a recognized extension."
    )
