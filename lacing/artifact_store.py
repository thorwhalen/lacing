"""Artifact store — a metadata catalog and a blob store behind one facade.

An :class:`~lacing.artifact.Artifact` describes a generated file; this module
*persists* artifacts. It is the storage layer that ``reelee`` (and any other
producer) builds on so artifacts survive a process restart and are reachable
from another machine — not just from the browser tab that generated them.

Design
------

The store keeps **three concerns separate** (see
``misc/docs/Artifact Store Architecture — design notes.md``):

- **Data organization** — artifacts are *physically flat*: a **catalog**
  (``id -> record``) holds metadata, a **blob store** (``content_hash ->
  bytes``) holds the heavy bytes. Neither key encodes ownership or grouping.
- **Infrastructure mapping** — :class:`ArtifactStore` is a thin *facade* that
  composes two **injected** key-value stores. The backing stores are ordinary
  ``MutableMapping`` objects, so the backend swaps (in-memory -> filesystem ->
  object store) by dependency injection, with no change to callers.
- **Access calculus** — deliberately *absent here*. :class:`ArtifactStore` is
  an unprivileged primitive that checks nothing; a caller that needs access
  control wraps it in a permission-enforcing facade of its own.

Identity is an **explicit string key**, not assumed to be the content hash:
artifacts often get a stable id *before* their bytes exist (and hence before
they can be hashed). The catalog is therefore generic over the record type and
keyed by whatever id the caller chooses; the content hash, when known, is just
a field on the record and the key of the blob store.

Consistency: there is no transaction spanning the two stores, so :meth:`save`
writes the **blob first, then the catalog row**. Because blobs are
content-addressed the blob write is idempotent; a crash in between leaves at
worst an unreferenced (orphan) blob — never a catalog row pointing at missing
bytes.

Examples
--------

>>> from lacing import Artifact
>>> store = ArtifactStore.in_memory()
>>> art = Artifact.from_bytes(
...     b"fake-png-bytes", kind="image",
...     was_generated_by="agent:flux", was_attributed_to="user:thor",
... )
>>> _ = store.save(art.asset_id, art)
>>> store[art.asset_id].kind
'image'
>>> art.asset_id in store
True
>>> len(store)
1
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from dol import Files, filt_iter, wrap_kvs

from lacing.artifact import Artifact, hash_bytes

__all__ = ["ArtifactStore"]


@dataclass(eq=False)
class ArtifactStore(MutableMapping):
    """Facade over an artifact ``catalog`` and an optional ``blobs`` store.

    The object *is* a ``MutableMapping[str, record]`` over the catalog —
    ``store[artifact_id]``, iteration, ``len``, ``get``, ``clear`` and the
    rest of the mapping surface all act on artifact **metadata records**. The
    heavier byte operations (:meth:`put_blob`, :meth:`get_blob`,
    :meth:`has_blob`) are rich methods that are deliberately *not* squeezed
    into the mapping protocol.

    Args:
        catalog: Injected ``id -> record`` store. Records are pydantic models
            (``lacing.Artifact`` by default, but any ``BaseModel`` works — the
            store does not inspect the record's shape).
        blobs: Injected ``content_hash -> bytes`` store, or ``None`` for a
            catalog-only store (Stage-1 metadata persistence). Blob methods
            raise / no-op when it is ``None``.

    Construct one with :meth:`in_memory` or :meth:`from_directory` rather than
    wiring the backing stores by hand, unless you are injecting a custom
    backend.
    """

    catalog: MutableMapping[str, BaseModel]
    blobs: MutableMapping[str, bytes] | None = None

    # -- catalog: the MutableMapping surface (artifact_id -> record) --------

    def __getitem__(self, artifact_id: str) -> BaseModel:
        return self.catalog[artifact_id]

    def __setitem__(self, artifact_id: str, record: BaseModel) -> None:
        self.catalog[artifact_id] = record

    def __delitem__(self, artifact_id: str) -> None:
        del self.catalog[artifact_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self.catalog)

    def __len__(self) -> int:
        return len(self.catalog)

    # -- domain verbs ------------------------------------------------------

    def save(
        self, artifact_id: str, record: BaseModel, *, data: bytes | None = None
    ) -> str | None:
        """Persist one artifact, optionally with its bytes.

        Writes the blob (if ``data`` is given) **before** the catalog row, so a
        crash never leaves the catalog pointing at missing bytes. Idempotent on
        ``artifact_id`` — and, for the blob, on content — so retries are safe.

        Args:
            artifact_id: The stable string id this artifact is filed under.
            record: The metadata record to store in the catalog.
            data: Optional raw bytes. When given, they are stored
                content-addressed and the content hash is returned; the caller
                is responsible for also recording that hash on ``record``.

        Returns:
            The blob's content hash if ``data`` was written, else ``None``.

        Raises:
            RuntimeError: ``data`` was given but no blob store is configured.
        """
        content_hash: str | None = None
        if data is not None:
            if self.blobs is None:
                raise RuntimeError(
                    "ArtifactStore.save received blob bytes but has no blob "
                    "store configured. Construct it with .in_memory() or "
                    ".from_directory(), or inject a `blobs` store."
                )
            content_hash = hash_bytes(data)
            self.blobs[content_hash] = data  # content-addressed -> idempotent
        self.catalog[artifact_id] = record
        return content_hash

    def index(self) -> dict[str, BaseModel]:
        """Return the whole catalog as a plain dict (e.g. for UI hydration)."""
        return dict(self.catalog)

    # -- blobs: rich byte methods ------------------------------------------

    def put_blob(self, data: bytes) -> str:
        """Store ``data`` content-addressed; return its content hash.

        Idempotent: identical bytes always map to the same hash and overwrite
        an identical blob.

        Raises:
            RuntimeError: no blob store is configured.
        """
        if self.blobs is None:
            raise RuntimeError("ArtifactStore has no blob store configured.")
        content_hash = hash_bytes(data)
        self.blobs[content_hash] = data
        return content_hash

    def get_blob(self, content_hash: str) -> bytes | None:
        """Return the bytes for ``content_hash``, or ``None`` if absent."""
        if self.blobs is None:
            return None
        try:
            return self.blobs[content_hash]
        except KeyError:
            return None

    def has_blob(self, content_hash: str) -> bool:
        """Whether the blob store holds ``content_hash``."""
        return self.blobs is not None and content_hash in self.blobs

    # -- constructors ------------------------------------------------------

    @classmethod
    def in_memory(cls) -> ArtifactStore:
        """An ArtifactStore backed entirely by in-memory dicts.

        For tests, scratch work, and as the trivial reference backend. Nothing
        persists across processes.
        """
        return cls(catalog={}, blobs={})

    @classmethod
    def from_directory(
        cls, root: Path | str, *, record_type: type[BaseModel] = Artifact
    ) -> ArtifactStore:
        """An ArtifactStore persisted under ``root``.

        Lays out two subdirectories: ``catalog/`` (one ``<id>.json`` file per
        record) and ``blobs/`` (one file per content hash). Both are ``dol``
        filesystem stores, so the same facade works unchanged over any other
        ``dol`` backend (object storage, etc.) when injected directly.

        Args:
            root: Directory to hold the store. Created if missing.
            record_type: The pydantic model the catalog deserializes JSON into.
                Defaults to :class:`~lacing.artifact.Artifact`; callers with
                their own record schema pass their model here.
        """
        root = Path(root)
        catalog_dir = root / "catalog"
        blob_dir = root / "blobs"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        blob_dir.mkdir(parents=True, exist_ok=True)

        catalog = wrap_kvs(
            filt_iter(Files(str(catalog_dir)), filt=lambda k: k.endswith(".json")),
            id_of_key=lambda artifact_id: f"{artifact_id}.json",
            key_of_id=lambda filename: (
                filename[:-5] if filename.endswith(".json") else filename
            ),
            data_of_obj=lambda record: record.model_dump_json(indent=2).encode("utf-8"),
            obj_of_data=lambda raw: record_type.model_validate_json(raw),
        )
        blobs = Files(str(blob_dir))
        return cls(catalog=catalog, blobs=blobs)
