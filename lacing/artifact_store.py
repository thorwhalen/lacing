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

import hashlib
from collections.abc import Callable, Iterable, Iterator, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from dol import Files, filt_iter, wrap_kvs

from lacing.artifact import Artifact, hash_bytes


#: Pre-v1 ``s3dol.store.S3Store`` kwarg names -> their ``s3dol.s3_store``
#: equivalents. Kept so callers of :meth:`ArtifactStore.from_s3` that still
#: spell credentials the old way keep working (with a DeprecationWarning)
#: rather than getting an opaque TypeError from a signature they never saw.
_S3DOL_LEGACY_KWARGS = {
    "profile_name": "profile",
    "path": "prefix",
}


def _s3_kwargs_to_v1(s3_kwargs: dict) -> dict:
    """Translate pre-v1 s3dol kwargs to the v1 ``s3_store`` signature.

    s3dol v1 takes credentials as one ``credentials=`` value (normalised to a
    picklable spec, so the store survives a process hop) rather than three
    loose ``aws_*`` kwargs, and replaces the ``make_bucket`` tri-state with
    ``on_missing_bucket``.

    >>> _s3_kwargs_to_v1({'endpoint_url': 'https://x', 'region_name': 'eu-west-1'})
    {'endpoint_url': 'https://x', 'region_name': 'eu-west-1'}
    """
    import warnings

    kwargs = dict(s3_kwargs)
    deprecated = []

    access = kwargs.pop("aws_access_key_id", None)
    secret = kwargs.pop("aws_secret_access_key", None)
    token = kwargs.pop("aws_session_token", None)
    if access or secret or token:
        deprecated.append("aws_access_key_id/aws_secret_access_key/aws_session_token")
        if not (access and secret):
            raise TypeError(
                "from_s3 needs both aws_access_key_id and aws_secret_access_key "
                "(a token alone is not a credential). Better: pass s3dol v1's "
                "credentials=(key, secret) or credentials='<profile-name>'."
            )
        kwargs["credentials"] = (access, secret, token) if token else (access, secret)

    if "make_bucket" in kwargs:
        deprecated.append("make_bucket")
        # v0 tri-state -> v1 policy. Note v1's default never probes and never
        # creates, so a missing bucket surfaces on first use rather than being
        # silently minted from a typo.
        kwargs["on_missing_bucket"] = {
            True: "create",
            False: "raise",
            None: "assume",
        }[kwargs.pop("make_bucket")]

    for old, new in _S3DOL_LEGACY_KWARGS.items():
        if old in kwargs:
            deprecated.append(old)
            kwargs[new] = kwargs.pop(old)

    if deprecated:
        warnings.warn(
            f"from_s3 received pre-v1 s3dol kwarg(s): {', '.join(deprecated)}. "
            f"They were translated to the s3dol>=1 signature "
            f"(credentials=/profile=/prefix=/on_missing_bucket=); pass those "
            f"directly instead. Translation will be removed in a future lacing.",
            DeprecationWarning,
            stacklevel=3,
        )
    return kwargs

__all__ = ["ArtifactStore"]


def _mk_sql_refcount(sql_store) -> Callable[[str], int]:
    """Build a ``content_hash -> row count`` query over a ``sqldol`` store.

    Reaches through the ``sqldol.SQLAlchemyStore`` to its persister's ORM
    session and counts rows whose indexed ``content_hash`` column matches —
    one query, not a scan. Used by :meth:`ArtifactStore.from_sql` to wire the
    GC reference-count capability that :meth:`ArtifactStore.count_refs` probes
    for. Works identically on SQLite and Postgres (plain SQLAlchemy).
    """
    from sqlalchemy import func

    persister = sql_store.store  # the SQLAlchemyPersister behind the dol Store
    table = persister.table.__table__

    def refcount(content_hash: str) -> int:
        return (
            persister.session.query(func.count())
            .filter(table.c.content_hash == content_hash)
            .scalar()
        )

    return refcount


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

    def put_blob_stream(self, chunks: Iterable[bytes]) -> str:
        """Stream ``chunks`` content-addressed; return their SHA-256 hash.

        The streaming-friendly counterpart to :meth:`put_blob` — callers hand
        in an iterable (e.g. ``requests.Response.iter_content``) instead of
        materializing the whole bytestring upfront. The hash is computed on
        the fly. The default implementation still buffers the bytes in the
        store's own memory before writing; that is adequate for files up to a
        few hundred megabytes. A future filesystem-aware optimization
        (write-to-tempfile + atomic rename) is an internal change that does
        not touch this API.

        Raises:
            RuntimeError: no blob store is configured.
        """
        if self.blobs is None:
            raise RuntimeError("ArtifactStore has no blob store configured.")
        hasher = hashlib.sha256()
        buf = bytearray()
        for chunk in chunks:
            hasher.update(chunk)
            buf.extend(chunk)
        content_hash = hasher.hexdigest()
        self.blobs[content_hash] = bytes(buf)
        return content_hash

    def get_blob(self, content_hash: str) -> bytes | None:
        """Return the bytes for ``content_hash``, or ``None`` if absent."""
        if self.blobs is None:
            return None
        try:
            return self.blobs[content_hash]
        except KeyError:
            return None

    def iter_blob(
        self, content_hash: str, *, chunk_size: int = 1 << 16
    ) -> Iterator[bytes]:
        """Yield the blob's bytes in ``chunk_size`` chunks.

        The streaming counterpart to :meth:`get_blob` — what an HTTP response
        body iterates over when serving a large blob without holding it all
        in process memory. The default implementation reads the whole blob
        via :meth:`get_blob` and re-chunks it; a filesystem-backed store can
        be swapped for a true streaming reader without changing this API.

        Raises:
            KeyError: no blob exists for ``content_hash``.
        """
        data = self.get_blob(content_hash)
        if data is None:
            raise KeyError(content_hash)
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]

    def blob_path(self, content_hash: str) -> Path | None:
        """Return the local filesystem path of the blob, or ``None``.

        The store's blob backend is opaque (any ``MutableMapping``), but some
        backends — notably the filesystem-backed ``dol.Files`` produced by
        :meth:`from_directory` — store each blob as one file under a known
        root directory. This method exposes that path *when available*, so a
        caller (e.g. a FastAPI route serving video) can hand the OS the file
        descriptor and let it answer HTTP ``Range`` requests directly. It
        returns ``None`` for:

        - blob stores without a ``rootdir`` attribute (e.g. plain ``dict``,
          object-store backends — callers should fall back to
          :meth:`iter_blob`);
        - blobs that are not present.

        Callers must treat ``None`` as the cue to use the streaming read
        path, not as an error.
        """
        if self.blobs is None:
            return None
        rootdir = getattr(self.blobs, "rootdir", None)
        if rootdir is None:
            return None
        path = Path(rootdir) / content_hash
        return path if path.is_file() else None

    def has_blob(self, content_hash: str) -> bool:
        """Whether the blob store holds ``content_hash``."""
        return self.blobs is not None and content_hash in self.blobs

    def blob_location(self, content_hash: str) -> "str | Path | None":
        """Resolve the cheapest *servable* location for a blob — without
        reading its bytes. The capability the HTTP layer probes to serve a
        blob the most efficient way, generalizing :meth:`blob_path` so
        filesystem / S3 / R2 backends all answer one probe:

        - **object-store** backends (S3/R2) that expose a presigned-URL
          capability — a ``url_for(content_hash)`` callable — return a **URL
          string**, so the caller can 302-redirect and let the object store
          serve the bytes (and HTTP ``Range``) directly, off the app process;
        - **filesystem** backends return a local **Path** (see
          :meth:`blob_path`) so the caller hands the OS the file (Range free);
        - everything else (plain ``dict``, or a missing blob) returns
          ``None`` — the cue to fall back to :meth:`iter_blob` streaming.

        Callers treat ``None`` as "stream it", not as an error.
        """
        if self.blobs is None or content_hash not in self.blobs:
            return None
        url_for = getattr(self.blobs, "url_for", None)
        if callable(url_for):
            try:
                url = url_for(content_hash)
            except Exception as error:
                # A backend may *refuse* to sign rather than sign wrongly —
                # s3dol>=1 does exactly that when its store has been wrapped
                # by a key codec, because the URL could then address a
                # different object. "No safe URL" is not an error here, it is
                # the documented cue to stream; but it should not pass in
                # silence, since streaming through the app is the expensive
                # path this method exists to avoid.
                import warnings

                warnings.warn(
                    f"{type(self.blobs).__name__}.url_for refused to sign "
                    f"({type(error).__name__}: {error}); falling back to "
                    f"streaming. Serving stays correct, just slower.",
                    stacklevel=2,
                )
                url = None
            if url:
                return url
        return self.blob_path(content_hash)

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

    def count_refs(self, content_hash: str) -> int:
        """How many catalog records point at ``content_hash`` (a blob).

        The reference count that a garbage collector needs: a blob is safe to
        delete only when **no** catalog record still names its content hash.
        Content-addressed blobs are deduplicated, so two artifacts can share
        one blob — deleting the blob the moment one of them goes away would
        orphan the other.

        This is the *probe* half of a capability pair (mirroring
        :meth:`blob_location` probing a blob store for ``url_for``): a catalog
        backend that can answer the count cheaply — the SQL catalog from
        :meth:`from_sql`, via an indexed ``content_hash`` column — exposes a
        ``refcount_by_content_hash`` callable, and this method uses it so the
        count is **one indexed query, not a full catalog scan**. Any other
        catalog (dict, ``Files``) falls back to scanning every record. The
        facade is unchanged either way; only the speed differs.

        Args:
            content_hash: The blob's content hash (``Artifact.asset_id``).

        Returns:
            The number of catalog records whose content hash equals
            ``content_hash``.
        """
        fast = getattr(self.catalog, "refcount_by_content_hash", None)
        if callable(fast):
            return fast(content_hash)
        # Fallback: scan every record. Reads the content hash off whichever of
        # the conventional fields the record carries (``asset_id`` first — the
        # canonical Artifact field — then ``content_hash``).
        count = 0
        for record in self.catalog.values():
            rec_hash = getattr(record, "asset_id", None) or getattr(
                record, "content_hash", None
            )
            if rec_hash == content_hash:
                count += 1
        return count

    @classmethod
    def from_s3(
        cls,
        bucket_name: str,
        *,
        catalog: "MutableMapping[str, BaseModel] | None" = None,
        prefix: str | None = None,
        **s3_kwargs,
    ) -> ArtifactStore:
        """An ArtifactStore with **blobs in an S3-compatible object store**
        (AWS S3 / Cloudflare R2 / MinIO / Supabase) via ``s3dol``.

        Content-addressed blobs are a natural fit for object storage: flat,
        immutable, dedup-friendly, forever-cacheable keys. :meth:`blob_location`
        returns a presigned GET URL (via s3dol's ``url_for``) so a serving layer
        can 302-redirect and let the store deliver the bytes (and HTTP ``Range``)
        directly, off the app process.

        The blob and catalog backends are independent by design: the catalog
        defaults to an in-memory dict here — swap in a durable catalog (e.g. a
        Postgres-backed ``MutableMapping``) for production.

        Args:
            bucket_name: The object-store bucket.
            catalog: The ``id -> record`` catalog ``MutableMapping``. Defaults
                to ``{}`` (in-memory).
            prefix: Optional key prefix within the bucket (e.g. ``"blobs"``).
            **s3_kwargs: Forwarded to ``s3dol.s3_store`` — ``endpoint_url``
                (set for R2 / MinIO / Supabase), ``region_name``, ``profile``,
                ``credentials``, ``preset``, ``anon``, ``on_missing_bucket``.
                The pre-v1 spellings (``aws_access_key_id`` /
                ``aws_secret_access_key`` / ``aws_session_token`` /
                ``profile_name`` / ``make_bucket``) are still accepted and
                translated, with a ``DeprecationWarning``.

        Requires ``s3dol>=1`` (and ``boto3``) — imported lazily so the
        dependency is only needed when this constructor is used.
        """
        from s3dol import s3_store

        blobs = s3_store(bucket_name, prefix=prefix or "", **_s3_kwargs_to_v1(s3_kwargs))
        return cls(catalog={} if catalog is None else catalog, blobs=blobs)

    @classmethod
    def from_sql(
        cls,
        uri: str,
        *,
        blobs: "MutableMapping[str, bytes] | None" = None,
        record_type: type[BaseModel] = Artifact,
        collection_name: str = "artifact_catalog",
        content_hash_of: "Callable[[BaseModel], str | None] | None" = None,
        **db_kwargs,
    ) -> ArtifactStore:
        """An ArtifactStore with a **SQL-backed catalog** (durable, queryable)
        via ``sqldol`` — the SQL counterpart of :meth:`from_s3`'s object store.

        The catalog row schema is deliberately minimal and **vendor-neutral**:
        one ``TEXT`` column holds the record serialized exactly as
        :meth:`from_directory` serializes it (``record.model_dump_json`` out,
        ``record_type.model_validate_json`` in), and one indexed ``content_hash``
        column carries the record's blob hash so the GC reference count
        (:meth:`count_refs`) is a single indexed query rather than a full scan.

        Because the connection is just a SQLAlchemy URI, the *same* code runs
        on SQLite for tests and on Postgres in production — that is the whole
        point of the facade. Pick the backend with the ``uri`` alone::

            ArtifactStore.from_sql("sqlite:///artifacts.db")          # local / tests
            ArtifactStore.from_sql("postgresql://u:p@host:5432/db")   # production

        The catalog and blob backends are independent: pass ``blobs`` to pair a
        SQL catalog with any blob store (e.g. ``from_s3``'s ``S3Store``), or
        leave it ``None`` for a catalog-only store (Stage-1 metadata
        persistence; see :meth:`from_aws` for the common S3 + SQL pairing).

        Args:
            uri: SQLAlchemy connection URI (``sqlite:///…`` or
                ``postgresql://…``). The single knob that selects the vendor.
            blobs: Optional ``content_hash -> bytes`` blob store. ``None`` for a
                catalog-only store.
            record_type: The pydantic model the catalog deserializes JSON into.
                Defaults to :class:`~lacing.artifact.Artifact`; callers with
                their own record schema pass their model here.
            collection_name: The SQL table name for the catalog.
            content_hash_of: How to read a record's blob hash for the indexed
                ``content_hash`` column. Defaults to ``asset_id`` (the canonical
                Artifact field), then ``content_hash``. Pass a callable for a
                record whose hash lives elsewhere; records without a hash store
                an empty string.
            **db_kwargs: Forwarded to ``sqldol.SQLAlchemyStore`` /
                SQLAlchemy's ``create_engine`` (e.g. ``connect_args``,
                ``pool_size``).

        Requires ``sqldol`` (and ``SQLAlchemy``) — imported lazily so the
        dependency is only needed when this constructor is used.
        """
        from sqldol import SQLAlchemyStore
        from sqldol.sql_base import SQLAlchemyPersister

        if content_hash_of is None:

            def content_hash_of(record: BaseModel) -> str | None:
                return getattr(record, "asset_id", None) or getattr(
                    record, "content_hash", None
                )

        raw = SQLAlchemyStore(
            uri=uri,
            collection_name=collection_name,
            key_fields={"artifact_id": SQLAlchemyPersister.TYPE_STRING},
            data_fields={
                "record_json": SQLAlchemyPersister.TYPE_TEXT,
                "content_hash": SQLAlchemyPersister.TYPE_STRING,
            },
            **db_kwargs,
        )

        def _key_of_id(row_or_key):
            # ``wrap_kvs`` hands this the key dict on writes and the ORM row on
            # iteration (sqldol's ``__iter__`` yields rows, not keys).
            if isinstance(row_or_key, dict):
                return row_or_key["artifact_id"]
            return row_or_key.artifact_id

        catalog = wrap_kvs(
            raw,
            id_of_key=lambda artifact_id: {"artifact_id": artifact_id},
            key_of_id=_key_of_id,
            data_of_obj=lambda record: {
                "record_json": record.model_dump_json(),
                "content_hash": content_hash_of(record) or "",
            },
            obj_of_data=lambda row: record_type.model_validate_json(row.record_json),
        )
        # Attach the GC reference-count capability so ``count_refs`` resolves it
        # to a single indexed query (the probe pattern; see ``count_refs``).
        catalog.refcount_by_content_hash = _mk_sql_refcount(raw)
        return cls(catalog=catalog, blobs=blobs)

    @classmethod
    def from_aws(
        cls,
        bucket_name: str,
        uri: str,
        *,
        record_type: type[BaseModel] = Artifact,
        collection_name: str = "artifact_catalog",
        prefix: str | None = None,
        s3_kwargs: "dict | None" = None,
        sql_kwargs: "dict | None" = None,
    ) -> ArtifactStore:
        """The production pairing: **S3-compatible blobs + SQL catalog**.

        A thin convenience over :meth:`from_s3` (blobs) and :meth:`from_sql`
        (catalog) so the common cloud deployment is one call. The blob store is
        an ``S3Store`` (AWS S3 / Cloudflare R2 / MinIO / Supabase); the catalog
        is the durable, queryable SQL table — Postgres in production, SQLite for
        a smoke test. Vendor specifics live only in the two kwargs dicts.

        Args:
            bucket_name: Object-store bucket for the content-addressed blobs.
            uri: SQLAlchemy URI for the catalog (``postgresql://…`` in prod).
            record_type: Pydantic model the catalog (de)serializes.
            collection_name: SQL table name for the catalog.
            prefix: Optional key prefix within the bucket.
            s3_kwargs: Extra kwargs forwarded to :meth:`from_s3` (credentials,
                ``endpoint_url`` for R2/MinIO/Supabase, ``region_name``, …).
            sql_kwargs: Extra kwargs forwarded to :meth:`from_sql`
                (``content_hash_of``, SQLAlchemy engine kwargs, …).
        """
        s3_store = cls.from_s3(bucket_name, prefix=prefix, **(s3_kwargs or {}))
        return cls.from_sql(
            uri,
            blobs=s3_store.blobs,
            record_type=record_type,
            collection_name=collection_name,
            **(sql_kwargs or {}),
        )
