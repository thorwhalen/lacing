# lacing.artifact_store

Artifact store — a metadata catalog and a blob store behind one facade.

An [`Artifact`](lacing.artifact.md#lacing.artifact.Artifact) describes a generated file; this module
*persists* artifacts. It is the storage layer that `reelee` (and any other
producer) builds on so artifacts survive a process restart and are reachable
from another machine — not just from the browser tab that generated them.

## Design

The store keeps **three concerns separate** (see
`misc/docs/Artifact Store Architecture — design notes.md`):

- **Data organization** — artifacts are *physically flat*: a **catalog**
  (`id -> record`) holds metadata, a **blob store** (`content_hash ->
  bytes`) holds the heavy bytes. Neither key encodes ownership or grouping.
- **Infrastructure mapping** — [`ArtifactStore`](#lacing.artifact_store.ArtifactStore) is a thin *facade* that
  composes two **injected** key-value stores. The backing stores are ordinary
  `MutableMapping` objects, so the backend swaps (in-memory -> filesystem ->
  object store) by dependency injection, with no change to callers.
- **Access calculus** — deliberately *absent here*. [`ArtifactStore`](#lacing.artifact_store.ArtifactStore) is
  an unprivileged primitive that checks nothing; a caller that needs access
  control wraps it in a permission-enforcing facade of its own.

Identity is an **explicit string key**, not assumed to be the content hash:
artifacts often get a stable id *before* their bytes exist (and hence before
they can be hashed). The catalog is therefore generic over the record type and
keyed by whatever id the caller chooses; the content hash, when known, is just
a field on the record and the key of the blob store.

Consistency: there is no transaction spanning the two stores, so `save()`
writes the **blob first, then the catalog row**. Because blobs are
content-addressed the blob write is idempotent; a crash in between leaves at
worst an unreferenced (orphan) blob — never a catalog row pointing at missing
bytes.

### Examples

```pycon
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
```

### Classes

| [`ArtifactStore`](#lacing.artifact_store.ArtifactStore)(catalog[, blobs])   | Facade over an artifact `catalog` and an optional `blobs` store.   |
|------------------------------------------------------------------------------------|--------------------------------------------------------------------|

### *class* lacing.artifact_store.ArtifactStore(catalog, blobs=None)

Bases: [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

Facade over an artifact `catalog` and an optional `blobs` store.

The object *is* a `MutableMapping[str, record]` over the catalog —
`store[artifact_id]`, iteration, `len`, `get`, `clear` and the
rest of the mapping surface all act on artifact **metadata records**. The
heavier byte operations ([`put_blob()`](#lacing.artifact_store.ArtifactStore.put_blob), [`get_blob()`](#lacing.artifact_store.ArtifactStore.get_blob),
[`has_blob()`](#lacing.artifact_store.ArtifactStore.has_blob)) are rich methods that are deliberately *not* squeezed
into the mapping protocol.

* **Parameters:**
  * **catalog** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), `BaseModel`]) – Injected `id -> record` store. Records are pydantic models
    (`lacing.Artifact` by default, but any `BaseModel` works — the
    store does not inspect the record’s shape).
  * **blobs** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Injected `content_hash -> bytes` store, or `None` for a
    catalog-only store (Stage-1 metadata persistence). Blob methods
    raise / no-op when it is `None`.

Construct one with [`in_memory()`](#lacing.artifact_store.ArtifactStore.in_memory) or [`from_directory()`](#lacing.artifact_store.ArtifactStore.from_directory) rather than
wiring the backing stores by hand, unless you are injecting a custom
backend.

#### blob_location(content_hash)

Resolve the cheapest *servable* location for a blob — without
reading its bytes. The capability the HTTP layer probes to serve a
blob the most efficient way, generalizing [`blob_path()`](#lacing.artifact_store.ArtifactStore.blob_path) so
filesystem / S3 / R2 backends all answer one probe:

- **object-store** backends (S3/R2) that expose a presigned-URL
  capability — a `url_for(content_hash)` callable — return a \*\*URL
  string\*\*, so the caller can 302-redirect and let the object store
  serve the bytes (and HTTP `Range`) directly, off the app process;
- **filesystem** backends return a local **Path** (see
  [`blob_path()`](#lacing.artifact_store.ArtifactStore.blob_path)) so the caller hands the OS the file (Range free);
- everything else (plain `dict`, or a missing blob) returns
  `None` — the cue to fall back to [`iter_blob()`](#lacing.artifact_store.ArtifactStore.iter_blob) streaming.

Callers treat `None` as “stream it”, not as an error.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### blob_path(content_hash)

Return the local filesystem path of the blob, or `None`.

The store’s blob backend is opaque (any `MutableMapping`), but some
backends — notably the filesystem-backed `dol.Files` produced by
[`from_directory()`](#lacing.artifact_store.ArtifactStore.from_directory) — store each blob as one file under a known
root directory. This method exposes that path *when available*, so a
caller (e.g. a FastAPI route serving video) can hand the OS the file
descriptor and let it answer HTTP `Range` requests directly. It
returns `None` for:

- blob stores without a `rootdir` attribute (e.g. plain `dict`,
  object-store backends — callers should fall back to
  [`iter_blob()`](#lacing.artifact_store.ArtifactStore.iter_blob));
- blobs that are not present.
- a `content_hash` that does not resolve to a path *inside*
  `rootdir` (path traversal, e.g. `"../../etc/passwd"` or an
  absolute path, or a same-named symlink pointing outside the
  store) — refused rather than served (lacing#50).

Callers must treat `None` as the cue to use the streaming read
path, not as an error. This check covers only the *read* side of
this store’s own path join; a consumer’s record model is still
responsible for validating any key (e.g. an artifact `id`) it
hands to a separate write path such as `dol.Files`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### count_refs(content_hash)

How many catalog records point at `content_hash` (a blob).

The reference count that a garbage collector needs: a blob is safe to
delete only when **no** catalog record still names its content hash.
Content-addressed blobs are deduplicated, so two artifacts can share
one blob — deleting the blob the moment one of them goes away would
orphan the other.

This is the *probe* half of a capability pair (mirroring
[`blob_location()`](#lacing.artifact_store.ArtifactStore.blob_location) probing a blob store for `url_for`): a catalog
backend that can answer the count cheaply — the SQL catalog from
[`from_sql()`](#lacing.artifact_store.ArtifactStore.from_sql), via an indexed `content_hash` column — exposes a
`refcount_by_content_hash` callable, and this method uses it so the
count is **one indexed query, not a full catalog scan**. Any other
catalog (dict, `Files`) falls back to scanning every record. The
facade is unchanged either way; only the speed differs.

* **Parameters:**
  **content_hash** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The blob’s content hash (`Artifact.asset_id`).
* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)
* **Returns:**
  The number of catalog records whose content hash equals
  `content_hash`.

#### *classmethod* from_aws(bucket_name, uri, \*, record_type=<class 'lacing.artifact.Artifact'>, collection_name='artifact_catalog', prefix=None, s3_kwargs=None, sql_kwargs=None)

The production pairing: **S3-compatible blobs + SQL catalog**.

A thin convenience over [`from_s3()`](#lacing.artifact_store.ArtifactStore.from_s3) (blobs) and [`from_sql()`](#lacing.artifact_store.ArtifactStore.from_sql)
(catalog) so the common cloud deployment is one call. The blob store is
an `S3Store` (AWS S3 / Cloudflare R2 / MinIO / Supabase); the catalog
is the durable, queryable SQL table — Postgres in production, SQLite for
a smoke test. Vendor specifics live only in the two kwargs dicts.

* **Parameters:**
  * **bucket_name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Object-store bucket for the content-addressed blobs.
  * **uri** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – SQLAlchemy URI for the catalog (`postgresql://…` in prod).
  * **record_type** ([`type`](https://docs.python.org/3/builtins/functions.html#type)[`BaseModel`]) – Pydantic model the catalog (de)serializes.
  * **collection_name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – SQL table name for the catalog.
  * **prefix** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional key prefix within the bucket.
  * **s3_kwargs** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Extra kwargs forwarded to [`from_s3()`](#lacing.artifact_store.ArtifactStore.from_s3) (credentials,
    `endpoint_url` for R2/MinIO/Supabase, `region_name`, …).
  * **sql_kwargs** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Extra kwargs forwarded to [`from_sql()`](#lacing.artifact_store.ArtifactStore.from_sql)
    (`content_hash_of`, SQLAlchemy engine kwargs, …).
* **Return type:**
  [`ArtifactStore`](#lacing.artifact_store.ArtifactStore)

#### *classmethod* from_directory(root, \*, record_type=<class 'lacing.artifact.Artifact'>)

An ArtifactStore persisted under `root`.

Lays out two subdirectories: `catalog/` (one `<id>.json` file per
record) and `blobs/` (one file per content hash). Both are `dol`
filesystem stores, so the same facade works unchanged over any other
`dol` backend (object storage, etc.) when injected directly.

* **Parameters:**
  * **root** ([`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Directory to hold the store. Created if missing.
  * **record_type** ([`type`](https://docs.python.org/3/builtins/functions.html#type)[`BaseModel`]) – The pydantic model the catalog deserializes JSON into.
    Defaults to [`Artifact`](lacing.artifact.md#lacing.artifact.Artifact); callers with
    their own record schema pass their model here.
* **Return type:**
  [`ArtifactStore`](#lacing.artifact_store.ArtifactStore)

#### *classmethod* from_s3(bucket_name, , catalog=None, prefix=None, \*\*s3_kwargs)

An ArtifactStore with **blobs in an S3-compatible object store**
(AWS S3 / Cloudflare R2 / MinIO / Supabase) via `s3dol`.

Content-addressed blobs are a natural fit for object storage: flat,
immutable, dedup-friendly, forever-cacheable keys. [`blob_location()`](#lacing.artifact_store.ArtifactStore.blob_location)
returns a presigned GET URL (via s3dol’s `url_for`) so a serving layer
can 302-redirect and let the store deliver the bytes (and HTTP `Range`)
directly, off the app process.

The blob and catalog backends are independent by design: the catalog
defaults to an in-memory dict here — swap in a durable catalog (e.g. a
Postgres-backed `MutableMapping`) for production.

* **Parameters:**
  * **bucket_name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The object-store bucket.
  * **catalog** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), `BaseModel`] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The `id -> record` catalog `MutableMapping`. Defaults
    to `{}` (in-memory).
  * **prefix** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional key prefix within the bucket (e.g. `"blobs"`).
  * **\*\*s3_kwargs** – Forwarded to `s3dol.s3_store` — `endpoint_url`
    (set for R2 / MinIO / Supabase), `region_name`, `profile`,
    `credentials`, `preset`, `anon`, `on_missing_bucket`.
    The pre-v1 spellings (`aws_access_key_id` /
    `aws_secret_access_key` / `aws_session_token` /
    `profile_name` / `make_bucket`) are still accepted and
    translated, with a `DeprecationWarning`.
* **Return type:**
  [`ArtifactStore`](#lacing.artifact_store.ArtifactStore)

Requires `s3dol>=1` (and `boto3`) — imported lazily so the
dependency is only needed when this constructor is used.

#### *classmethod* from_sql(uri, \*, blobs=None, record_type=<class 'lacing.artifact.Artifact'>, collection_name='artifact_catalog', content_hash_of=None, \*\*db_kwargs)

An ArtifactStore with a **SQL-backed catalog** (durable, queryable)
via `sqldol` — the SQL counterpart of [`from_s3()`](#lacing.artifact_store.ArtifactStore.from_s3)’s object store.

The catalog row schema is deliberately minimal and **vendor-neutral**:
one `TEXT` column holds the record serialized exactly as
[`from_directory()`](#lacing.artifact_store.ArtifactStore.from_directory) serializes it (`record.model_dump_json` out,
`record_type.model_validate_json` in), and one indexed `content_hash`
column carries the record’s blob hash so the GC reference count
([`count_refs()`](#lacing.artifact_store.ArtifactStore.count_refs)) is a single indexed query rather than a full scan.

Because the connection is just a SQLAlchemy URI, the *same* code runs
on SQLite for tests and on Postgres in production — that is the whole
point of the facade. Pick the backend with the `uri` alone:

```default
ArtifactStore.from_sql("sqlite:///artifacts.db")          # local / tests
ArtifactStore.from_sql("postgresql://u:p@host:5432/db")   # production
```

The catalog and blob backends are independent: pass `blobs` to pair a
SQL catalog with any blob store (e.g. `from_s3`’s `S3Store`), or
leave it `None` for a catalog-only store (Stage-1 metadata
persistence; see [`from_aws()`](#lacing.artifact_store.ArtifactStore.from_aws) for the common S3 + SQL pairing).

* **Parameters:**
  * **uri** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – SQLAlchemy connection URI (`sqlite:///…` or
    `postgresql://…`). The single knob that selects the vendor.
  * **blobs** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional `content_hash -> bytes` blob store. `None` for a
    catalog-only store.
  * **record_type** ([`type`](https://docs.python.org/3/builtins/functions.html#type)[`BaseModel`]) – The pydantic model the catalog deserializes JSON into.
    Defaults to [`Artifact`](lacing.artifact.md#lacing.artifact.Artifact); callers with
    their own record schema pass their model here.
  * **collection_name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The SQL table name for the catalog.
  * **content_hash_of** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[`BaseModel`], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – How to read a record’s blob hash for the indexed
    `content_hash` column. Defaults to `asset_id` (the canonical
    Artifact field), then `content_hash`. Pass a callable for a
    record whose hash lives elsewhere; records without a hash store
    an empty string.
  * **\*\*db_kwargs** – Forwarded to `sqldol.SQLAlchemyStore` /
    SQLAlchemy’s `create_engine` (e.g. `connect_args`,
    `pool_size`).
* **Return type:**
  [`ArtifactStore`](#lacing.artifact_store.ArtifactStore)

Requires `sqldol` (and `SQLAlchemy`) — imported lazily so the
dependency is only needed when this constructor is used.

#### get_blob(content_hash)

Return the bytes for `content_hash`, or `None` if absent.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### has_blob(content_hash)

Whether the blob store holds `content_hash`.

`False` for a key that a filesystem-backed store would resolve
outside its `rootdir` — see `_escapes_blob_root()`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### *classmethod* in_memory()

An ArtifactStore backed entirely by in-memory dicts.

For tests, scratch work, and as the trivial reference backend. Nothing
persists across processes.

* **Return type:**
  [`ArtifactStore`](#lacing.artifact_store.ArtifactStore)

#### index()

Return the whole catalog as a plain dict (e.g. for UI hydration).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), `BaseModel`]

#### iter_blob(content_hash, , chunk_size=65536)

Yield the blob’s bytes in `chunk_size` chunks.

The streaming counterpart to [`get_blob()`](#lacing.artifact_store.ArtifactStore.get_blob) — what an HTTP response
body iterates over when serving a large blob without holding it all
in process memory. The default implementation reads the whole blob
via [`get_blob()`](#lacing.artifact_store.ArtifactStore.get_blob) and re-chunks it; a filesystem-backed store can
be swapped for a true streaming reader without changing this API.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – no blob exists for `content_hash`.
* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

#### put_blob(data)

Store `data` content-addressed; return its content hash.

Idempotent: identical bytes always map to the same hash and overwrite
an identical blob. Delegates to [`put_blob_stream()`](#lacing.artifact_store.ArtifactStore.put_blob_stream) so there is
exactly one write path — and therefore one atomicity story
(lacing#25).

* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – no blob store is configured.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### put_blob_stream(chunks)

Stream `chunks` content-addressed; return their SHA-256 hash.

The streaming-friendly counterpart to [`put_blob()`](#lacing.artifact_store.ArtifactStore.put_blob) — callers hand
in an iterable (e.g. `requests.Response.iter_content`) instead of
materializing the whole bytestring upfront. The hash is computed on
the fly.

When the blob store is filesystem-backed (exposes `rootdir`, as the
default directory store does), the bytes spool straight to a
same-directory tempfile and are renamed into place with
`os.replace` once the hash is known (lacing#25). Consequences a
caller may rely on:

- **peak memory is one chunk**, not 2× the payload — 100 MB videos
  flow through without a 200 MB spike;
- **a partial blob is never observable under its content address** —
  the name a reader could find only exists after the rename, which is
  atomic on POSIX and on Windows for same-directory renames — so
  `has_blob(h) == True` really does mean the full bytes are there;
- a failed or abandoned stream leaves nothing behind (the tempfile is
  unlinked).

Backends without a `rootdir` (plain `dict`, object-store
mappings) fall back to buffering the payload and assigning it whole —
their `__setitem__` is the atomicity story there.

* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – no blob store is configured.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### save(artifact_id, record, , data=None)

Persist one artifact, optionally with its bytes.

Writes the blob (if `data` is given) **before** the catalog row, so a
crash never leaves the catalog pointing at missing bytes. Idempotent on
`artifact_id` — and, for the blob, on content — so retries are safe.

* **Parameters:**
  * **artifact_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The stable string id this artifact is filed under.
  * **record** (`BaseModel`) – The metadata record to store in the catalog.
  * **data** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional raw bytes. When given, they are stored
    content-addressed and the content hash is returned; the caller
    is responsible for also recording that hash on `record`.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
* **Returns:**
  The blob’s content hash if `data` was written, else `None`.
* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – `data` was given but no blob store is configured.
