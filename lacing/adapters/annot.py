"""``.annot`` portable file format adapter.

The ``.annot`` file is a SQLite database with the schema defined in
``lacing.store.sqlite``. It's the recommended portable handoff and archive
format (BACK-DOC §3.1: "SQLite-as-app-format" — Git-trackable,
email-attachable, single-file).

Unlike text-based adapters (TextGrid, WebVTT, JSON-LD), this one is
non-lossy: the full annotation envelope, references, body, body schema URI,
provenance, and confidence all round-trip exactly.

When loading, returns an in-memory ``MemoryStore`` for compatibility with
the rest of the adapter API. To open an ``.annot`` file as a *persistent*
store you can mutate, use ``SqliteStore(path)`` directly:

    >>> from lacing.store import SqliteStore
    >>> store = SqliteStore("project.annot")  # writes go straight to disk
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from lacing.adapters import register_adapter
from lacing.store import IntervalAnnotationStore, MemoryStore, SqliteStore
from lacing.store.sqlite import from_memory, to_memory


ADAPTER_NAME = "annot"
DEFAULT_BODY_SCHEMA_URIS = ()  # the .annot format preserves whatever URIs are in the data


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(
    source: str | bytes | os.PathLike,
    *,
    persistent: bool = False,
    **_kwargs: Any,
) -> IntervalAnnotationStore:
    """Open an ``.annot`` file.

    Args:
        source: Path to an ``.annot`` file. Bytes input is supported by
            writing to a temp file first.
        persistent: If True, return an open ``SqliteStore`` (writes go to
            the file). If False (default), return a ``MemoryStore`` snapshot.

    Returns:
        ``MemoryStore`` (default) or ``SqliteStore`` (if ``persistent=True``).
    """
    if isinstance(source, (bytes, bytearray)):
        with tempfile.NamedTemporaryFile(
            suffix=".annot", delete=False
        ) as f:
            f.write(source)
            tmp_path = f.name
        try:
            sqlite_store = SqliteStore(tmp_path)
            mem = to_memory(sqlite_store)
            sqlite_store.close()
            return mem
        finally:
            if not persistent:
                os.unlink(tmp_path)

    path = os.fspath(source)
    if persistent:
        return SqliteStore(path)

    sqlite_store = SqliteStore(path)
    try:
        return to_memory(sqlite_store)
    finally:
        sqlite_store.close()


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    *,
    overwrite: bool = True,
    **_kwargs: Any,
) -> bytes | None:
    """Write ``store`` as an ``.annot`` SQLite file.

    Args:
        store: Source store. Can be any IntervalAnnotationStore.
        target: Output path. None = return bytes.
        overwrite: If True (default), replace any existing file at ``target``.
            If False and the file exists, raise ``FileExistsError``.
    """
    if target is None:
        with tempfile.NamedTemporaryFile(suffix=".annot", delete=False) as f:
            tmp_path = f.name
        try:
            sqlite_store = _build_at(store, tmp_path)
            sqlite_store.close()
            return Path(tmp_path).read_bytes()
        finally:
            os.unlink(tmp_path)

    target_path = Path(os.fspath(target))
    if target_path.exists():
        if not overwrite:
            raise FileExistsError(target_path)
        target_path.unlink()
    sqlite_store = _build_at(store, target_path)
    sqlite_store.close()
    return None


def _build_at(store: IntervalAnnotationStore, path) -> SqliteStore:
    """Materialize ``store`` as a fresh SqliteStore at ``path``.

    If ``store`` is already a ``SqliteStore``, copy the underlying file
    instead of re-inserting row by row — same content, faster and bit-exact.
    """
    if isinstance(store, SqliteStore):
        # Copy the file to the target location.
        src = os.fspath(store.path)
        if src == ":memory:":
            # In-memory source — fall through to row-by-row.
            return from_memory(_to_memory_like(store), path)
        shutil.copyfile(src, os.fspath(path))
        return SqliteStore(path)
    return from_memory(_to_memory_like(store), path)


def _to_memory_like(store: IntervalAnnotationStore):
    """Coerce any store to something with ``.tiers()`` and ``.all()``.

    ``MemoryStore`` and ``SqliteStore`` both already have these. This is a
    forward-compatibility shim for backends that don't expose ``all`` directly.
    """
    if hasattr(store, "all") and hasattr(store, "tiers"):
        return store
    # Fallback: build a transient MemoryStore.
    mem = MemoryStore()
    if hasattr(store, "tiers"):
        for t in store.tiers():  # type: ignore[attr-defined]
            mem.add_tier(t)
    for key in store:  # type: ignore[attr-defined]
        for ann in store[key]:  # type: ignore[index]
            mem.add(ann)
    return mem


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


register_adapter(
    name=ADAPTER_NAME,
    load=load,
    dump=dump,
    extensions=(".annot",),
    media_types=("application/x-lacing-annot",),
    body_schema_uris=DEFAULT_BODY_SCHEMA_URIS,
    description=(
        "Lacing's portable .annot SQLite file format. Lossless round-trip; "
        "preserves the full annotation envelope, provenance, and tier hierarchy."
    ),
)
