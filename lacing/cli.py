"""Command-line interface for lacing.

Built with ``cw`` (argparse + signature-driven argument inference).
The entry point is ``lacing`` — see ``project.scripts`` in pyproject.toml.

Subcommands:

    lacing convert <src> <dst> [--src-format] [--dst-format] [--rate]
        Convert between any two registered formats. Inferred from
        extension; override with ``--src-format`` / ``--dst-format``.

    lacing query <path> [--tier] [--start] [--end] [--relation]
        Print annotations matching a tier and/or interval query.
        Output is JSON-lines on stdout.

    lacing validate <path> [--rate]
        Load + re-dump round-trip; print a summary. Useful for sanity
        checking files before adopting them.

    lacing migrate <path> [--to-version N]
        Upgrade a ``.annot`` file to the current store schema, in place,
        via the registered store-migration ladder. Explicit by design:
        opening a stale file never rewrites it.

    lacing list-formats
        Print every registered format adapter.

The CLI imports each Phase 0/1 adapter at startup so they self-register.
Add new adapters by editing ``_ENABLED_ADAPTERS`` in this module.

Type annotations are load-bearing here
--------------------------------------

This module has ``from __future__ import annotations``, so every annotation
below is a *string* at runtime. ``argh``, which this CLI used to be built with,
reads ``__annotations__`` raw and is therefore blind to PEP 563: under it,
``--start``, ``--end`` and ``--to-version`` all arrived as ``str`` no matter what
their annotations said, and the only defence was hand-written coercion in the
command body (which ``migrate`` had and ``query`` did not — so
``lacing query f.vtt --start abc --end 2.0`` used to get all the way into
``RationalTime`` before failing).

:data:`_CONVENTION` turns that off. ``resolve_hints=True`` makes ``cw`` resolve
annotations with :func:`typing.get_type_hints` instead of reading them raw, so
``start: float | None`` becomes ``type=float`` at argparse's ``type=`` site —
where a bad value is a clean ``usage:`` + exit 2 rather than a traceback from
somewhere in the call stack. Which means: **annotate the parameters, and do not
coerce in the body.**
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import sys
from collections.abc import Iterable
from typing import Annotated

import cw

from lacing.allen import AllenRelation


_ENABLED_ADAPTERS = (
    "lacing.adapters.textgrid",
    "lacing.adapters.webvtt",
    "lacing.adapters.web_annotation",
    "lacing.adapters.annot",
    "lacing.adapters.eaf",
    "lacing.adapters.jams",
    "lacing.adapters.label_studio",
    "lacing.adapters.otio",
)


def _ensure_adapters() -> None:
    """Import adapter modules so they register themselves.

    Idempotent — Python caches the imports.
    """
    for name in _ENABLED_ADAPTERS:
        importlib.import_module(name)


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------


def convert(
    src: str,
    dst: str,
    *,
    src_format: "str | None" = None,
    dst_format: "str | None" = None,
    rate: int = 24000,
) -> None:
    """Convert between annotation file formats.

    SRC is a path to a recognized file (or ``-`` for stdin bytes — not yet).
    DST is the output path. Formats are inferred from extensions; override
    with --src-format / --dst-format.
    """
    _ensure_adapters()
    from lacing.adapters import dump as adapter_dump
    from lacing.adapters import load as adapter_load

    store = adapter_load(src, format=src_format, rate=rate)
    if dst_format is None:
        dst_format = _infer_format_from_extension(dst)
    if dst_format is None:
        raise SystemExit(f"Cannot infer output format from {dst!r}. Pass --dst-format.")
    adapter_dump(store, dst, format=dst_format)
    print(f"Wrote {dst!r} ({dst_format})")


def _infer_format_from_extension(path: str) -> "str | None":
    from lacing.adapters import find_adapter

    import os

    ext = os.path.splitext(path)[1]
    if not ext:
        return None
    spec = find_adapter(extension=ext)
    return spec.name if spec is not None else None


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


def query(
    path: str,
    *,
    tier: "str | None" = None,
    start: "float | None" = None,
    end: "float | None" = None,
    relation: str = "intersects",
    src_format: "str | None" = None,
    rate: int = 24000,
    limit: int = 100,
) -> None:
    """Print annotations from PATH matching a tier and/or time-interval query.

    Output is JSON-lines on stdout. ``--start`` and ``--end`` are seconds.
    ``--relation`` is one of: intersects, during, contains, overlaps, meets,
    starts, finishes, equals.
    """
    _ensure_adapters()
    from lacing.adapters import load as adapter_load
    from lacing.time import RationalTime, TimeInterval

    store = adapter_load(path, format=src_format, rate=rate)

    iter_anns: Iterable
    if start is not None or end is not None:
        if start is None or end is None:
            raise SystemExit("--start and --end must be given together")
        window = TimeInterval(
            RationalTime.from_seconds(str(start), rate=rate),
            RationalTime.from_seconds(str(end), rate=rate),
        )
        method = getattr(store, relation, None)
        if method is None or not callable(method):
            raise SystemExit(
                f"unknown relation {relation!r}. "
                f"Try: intersects, during, contains, overlaps, meets, starts, finishes, equals."
            )
        iter_anns = method(window)
    else:
        iter_anns = store.all() if hasattr(store, "all") else _iter_all(store)

    if tier is not None:
        iter_anns = (a for a in iter_anns if a.tier == tier)

    n = 0
    for ann in iter_anns:
        if n >= limit:
            print(f"... (limit reached at {limit})", file=sys.stderr)
            break
        print(_ann_to_jsonline(ann))
        n += 1


def _iter_all(store):
    """Fallback when the store doesn't expose .all()."""
    for key in store:
        for a in store[key]:
            yield a


def _ann_to_jsonline(ann) -> str:
    iv = ann.interval
    start_seconds = float(iv.start.to_fraction()) if iv else None
    end_seconds = float(iv.end.to_fraction()) if iv else None
    return json.dumps(
        {
            "id": str(ann.id),
            "tier": ann.tier,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "body": ann.body,
            "schema": ann.body_schema_uri,
            "confidence": ann.confidence,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def validate(
    path: str,
    *,
    src_format: "str | None" = None,
    rate: int = 24000,
) -> None:
    """Round-trip PATH through load + dump and report a summary.

    Useful for confirming an external file is well-formed and that the
    adapter understands it.
    """
    _ensure_adapters()
    from lacing.adapters import load as adapter_load

    store = adapter_load(path, format=src_format, rate=rate)
    iter_all = getattr(store, "all", None)
    anns = list(iter_all()) if callable(iter_all) else list(_iter_all(store))
    tiers_iter = getattr(store, "tiers", None)
    tiers = list(tiers_iter()) if callable(tiers_iter) else []

    by_tier: dict[str, int] = {}
    for a in anns:
        by_tier[a.tier] = by_tier.get(a.tier, 0) + 1

    print(f"path: {path}")
    print(f"format: {src_format or _infer_format_from_extension(path) or '<unknown>'}")
    print(f"annotations: {len(anns)}")
    print(f"tiers declared: {len(tiers)}")
    if by_tier:
        print("annotations per tier:")
        for name, count in sorted(by_tier.items()):
            print(f"  {name}: {count}")


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


def migrate(
    path: str,
    *,
    to_version: "int | None" = None,
) -> None:
    """Upgrade PATH (a ``.annot`` file) to the current store schema, in place.

    Migration is explicit — opening a stale file never rewrites it — so this
    verb is the ladder's front door. Already-current files are a no-op.
    ``--to-version`` upgrades part-way (mainly useful in tests).
    """
    from lacing.store.migrations import StoreMigrationError, migrate_annot_file

    try:
        found, reached = migrate_annot_file(path, to_version=to_version)
    except StoreMigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if found == reached:
        print(f"{path}: already at schema_version={found}, nothing to do")
    else:
        print(f"{path}: migrated schema_version {found} -> {reached}")


# ---------------------------------------------------------------------------
# list-formats
# ---------------------------------------------------------------------------


def list_formats() -> None:
    """Print every registered format adapter."""
    _ensure_adapters()
    from lacing.adapters import registered

    for spec in registered():
        ext = ", ".join(spec.extensions) or "(none)"
        print(f"{spec.name:20s}  extensions: {ext}")
        if spec.description:
            print(f"{'':20s}  {spec.description}")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


#: argh's grammar, with one switch flipped: annotations are resolved rather than
#: read raw, so this module's PEP 563 string annotations actually reach argparse's
#: ``type=`` site. See "Type annotations are load-bearing here" above.
_CONVENTION = dataclasses.replace(cw.ARGH, resolve_hints=True)

_COMMANDS = [convert, query, validate, migrate, list_formats]


def mk_parser() -> argparse.ArgumentParser:
    """Build the ``lacing`` parser — a plain :class:`argparse.ArgumentParser`."""
    return cw.mk_parser(_COMMANDS, prog="lacing", convention=_CONVENTION)


def main(argv: "list[str] | None" = None) -> None:
    """Entry point for the ``lacing`` console script.

    ``cw.run`` *returns* the exit code where argh's ``dispatch`` exited by
    itself, so the ``SystemExit`` here is what makes ``lacing no-such-command``
    exit 2 rather than 0.
    """
    raise SystemExit(cw.run(mk_parser(), argv))


if __name__ == "__main__":  # pragma: no cover
    main()
