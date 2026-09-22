# lacing

lacing — interval annotation system.

Standoff, interval-keyed annotations with rational time, ELAN tier
stereotypes, Allen’s interval algebra, and a `MutableMapping` facade.

Quick start:

```pycon
>>> from lacing import RationalTime, TimeInterval, Annotation, MemoryStore
>>> # Load a TextGrid, query overlaps, save as WebVTT — see misc/docs/.
```

Read `CLAUDE.md` and `misc/docs/Lacing Development Roadmap.md` for the
full story. `.claude/skills/` contains the rules.

### Functions

| [`hash_bytes`](#lacing.hash_bytes)(data)                                  | Return the canonical `asset_id` (SHA-256 hex) for `data`.               |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`hash_file`](#lacing.hash_file)(path, \*[, chunk_size])                 | Return the canonical `asset_id` (SHA-256 hex) for the file at `path`.   |
| [`annotation_value_digest`](#lacing.annotation_value_digest)(annotation)               | Return the SHA-256 hex digest of `annotation`'s value.                  |
| [`annotation_body_digest`](#lacing.annotation_body_digest)(annotation)                | Return the SHA-256 hex digest of `{body, body_schema_uri}` only.        |
| [`register_store_migration`](#lacing.register_store_migration)(\*, store_kind, ...)     | Register a forward store migration from `from_version` to `to_version`. |
| [`migrate_annot_file`](#lacing.migrate_annot_file)(path, \*[, to_version])        | Migrate a `.annot` file in place, returning `(from, to)` versions.      |
| [`replay_oplog`](#lacing.replay_oplog)(log, \*[, until_clock, ...])         | Rebuild a store by replaying `log` up to (and including) `until_clock`. |
| [`register_processor`](#lacing.register_processor)([func, name])                  | Register a processor under `name` (defaults to the function name).      |
| [`registered_processors`](#lacing.registered_processors)()                           | Names of every registered processor, sorted.                            |
| [`run_processor_async`](#lacing.run_processor_async)(name, \*, store, oplog, ...)  | Run a processor in the current event loop.                              |
| [`run_processor_sync`](#lacing.run_processor_sync)(name, \*, store, oplog, ...)   | Run a processor synchronously and return its result.                    |
| [`get_tracer`](#lacing.get_tracer)([name, version])                       | Return a tracer or a no-op fallback.                                    |
| [`maybe_span`](#lacing.maybe_span)(tracer, name, \*\*attributes)          | Open a span on `tracer`, attaching `attributes` if supported.           |
| [`traced`](#lacing.traced)(tracer[, span_name, record_args])          | Decorator: wrap a function in a span on `tracer`.                       |
| [`instrument_otel`](#lacing.instrument_otel)(app, \*[, tracer_name])           | Add OpenTelemetry instrumentation to a FastAPI app.                     |
| [`is_otel_active`](#lacing.is_otel_active)()                                  | Quick check: is OTel installed AND a TracerProvider configured?         |
| [`cohen_kappa`](#lacing.cohen_kappa)(a, b)                                 | Cohen's kappa for two annotators on a categorical label.                |
| [`krippendorff_alpha`](#lacing.krippendorff_alpha)(annotations, \*[, distance])   | Krippendorff's α across any number of annotators.                       |
| [`interval_iou`](#lacing.interval_iou)(a, b)                                | Intersection-over-Union for two time intervals.                         |
| [`boundary_iou`](#lacing.boundary_iou)(a, b)                                | Mean IoU between two sets of intervals via greedy best-match.           |
| [`register_body_schema`](#lacing.register_body_schema)(uri, model)                  | Register `model` as the validator for `uri`.                            |
| [`register_migration`](#lacing.register_migration)(\*, schema_name, ...)          | Register a forward migration from `v<from_version>` to `v<to_version>`. |
| [`json_schema`](#lacing.json_schema)(uri)                                  | Return the JSON Schema for the body model registered at `uri`.          |
| [`export_json_schemas`](#lacing.export_json_schemas)(target_dir, \*[, ...])        | Write every registered schema as JSON files under `target_dir`.         |
| [`render_artifact_exhibit`](#lacing.render_artifact_exhibit)(annotations, \*, out_dir) | Render an annotation graph as a human-readable artifact exhibit.        |
| [`migrate`](#lacing.migrate)(body, \*, from_uri, to_uri)               | Migrate `body` from `from_uri` to `to_uri` via registered steps.        |
| [`validate_body`](#lacing.validate_body)(body, uri)                          | Validate `body` against the schema registered for `uri`.                |

### Classes

| [`RationalTime`](#lacing.RationalTime)(value[, rate])                      | A point in time as `value / rate` seconds.                                     |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`TimeInterval`](#lacing.TimeInterval)(start, end)                         | A half-open interval `[start, end)`.                                           |
| [`Tier`](#lacing.Tier)(name, \*[, stereotype, parent, metadata])   | A named annotation layer with optional parent and stereotype.                  |
| [`TierStereotype`](#lacing.TierStereotype)(\*values)                         | Constraints on how a child tier relates to its parent tier.                    |
| [`Annotation`](#lacing.Annotation)(\*\*data)                             | The single annotation envelope.                                                |
| [`MediaRef`](#lacing.MediaRef)(\*\*data)                               | Reference to a region of a content-addressed media asset.                      |
| [`NodeRef`](#lacing.NodeRef)(\*\*data)                                | Reference to a node in a structured scene/document graph.                      |
| [`AnnotationRef`](#lacing.AnnotationRef)(\*\*data)                          | Reference to another annotation (for discussion threads, review, derivations). |
| [`Provenance`](#lacing.Provenance)(\*\*data)                             | W3C PROV-O subset, embedded inline on every annotation.                        |
| [`Artifact`](#lacing.Artifact)(\*\*data)                               | A content-addressed generated file with provenance.                            |
| [`ArtifactStore`](#lacing.ArtifactStore)(catalog[, blobs])                  | Facade over an artifact `catalog` and an optional `blobs` store.               |
| [`AllenRelation`](#lacing.AllenRelation)(\*values)                          | The thirteen Allen relations.                                                  |
| [`IntervalAnnotationStore`](#lacing.IntervalAnnotationStore)(\*args, \*\*kwargs)      | Protocol for any interval-keyed annotation store.                              |
| [`MemoryStore`](#lacing.MemoryStore)()                                    | `IntervalAnnotationStore` implementation over `intervaltree`.                  |
| [`SqliteStore`](#lacing.SqliteStore)(path, \*[, check_same_thread, ...])  | SQLite-backed `IntervalAnnotationStore`.                                       |
| [`OpLog`](#lacing.OpLog)(\*args, \*\*kwargs)                        | Append-only log of mutations.                                                  |
| [`OpLogEntry`](#lacing.OpLogEntry)(clock, operation, target_id, payload) | One row of the op-log.                                                         |
| [`InMemoryOpLog`](#lacing.InMemoryOpLog)()                                  | Simple list-backed op-log.                                                     |
| [`SqliteOpLog`](#lacing.SqliteOpLog)(path, \*[, check_same_thread])       | Op-log backed by a SQLite table.                                               |

### Exceptions

| [`LossyTimeConversionError`](#lacing.LossyTimeConversionError)   | Raised when a rate or seconds conversion would lose precision.           |
|-----------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`NonStringBodyKeyError`](#lacing.NonStringBodyKeyError)      | An annotation `body` contains a mapping key that is not a `str`.         |
| [`SchemaMismatchError`](#lacing.SchemaMismatchError)        | Raised when opening a `.annot` file with an incompatible schema.         |
| [`StoreMigrationError`](#lacing.StoreMigrationError)        | Raised when a store migration step is missing or fails.                  |
| [`ProcessorError`](#lacing.ProcessorError)             | Raised when a registered processor's invocation fails.                   |
| [`BodySchemaError`](#lacing.BodySchemaError)            | Raised when a body fails validation against its registered schema.       |
| [`EmptySchemaRegistryError`](#lacing.EmptySchemaRegistryError)   | Raised when an export would write an empty registry over real artifacts. |
| [`UnknownBodySchemaError`](#lacing.UnknownBodySchemaError)     | Raised when an annotation's body_schema_uri has no registered model.     |
| [`MigrationError`](#lacing.MigrationError)             | Raised when a migration step is missing or fails.                        |

### *class* lacing.AllenRelation(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

The thirteen Allen relations.

Symbols match Allen (1983); inverse pairs end in `i`.

#### inverse()

The inverse relation.

* **Return type:**
  [`AllenRelation`](lacing.allen.html.md#lacing.allen.AllenRelation)

### *class* lacing.Annotation(\*\*data)

Bases: `BaseModel`

The single annotation envelope. `body` is typed by `body_schema_uri`.

#### *property* interval *: [TimeInterval](lacing.time.html.md#lacing.time.TimeInterval) | [None](https://docs.python.org/3/builtins/constants.html#None)*

the reference’s interval, if any.

* **Type:**
  Convenience

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.AnnotationRef(\*\*data)

Bases: `BaseModel`

Reference to another annotation (for discussion threads, review, derivations).

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.Artifact(\*\*data)

Bases: `BaseModel`

A content-addressed generated file with provenance.

`asset_id` is the SHA-256 hex digest of the artifact’s bytes. Two
artifacts with the same `asset_id` are byte-identical regardless of
where they live — so caches keyed on `asset_id` are safe across
machines and re-runs.

`provenance` reuses [`lacing.Provenance`](#lacing.Provenance) so the lineage chain
(`was_derived_from`, `was_generated_by`) is the same for artifacts
and annotations. An annotation referencing an artifact does so via
`MediaRef(asset_id=artifact.asset_id, …)`.

#### *classmethod* from_bytes(data, , kind, was_generated_by, was_attributed_to, path=None, url=None, was_derived_from=(), activity='create', generated_at_time=None, duration_s=None, mime=None, cost_usd=None, producer_call_id=None)

Create an Artifact from in-memory bytes.

* **Return type:**
  [`Artifact`](lacing.artifact.html.md#lacing.artifact.Artifact)

#### *classmethod* from_path(path, , kind, was_generated_by, was_attributed_to, was_derived_from=(), activity='create', generated_at_time=None, duration_s=None, mime=None, cost_usd=None, producer_call_id=None)

Create an Artifact from a local file. Hashes the file’s bytes.

* **Return type:**
  [`Artifact`](lacing.artifact.html.md#lacing.artifact.Artifact)

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

#### to_media_ref(interval)

Return a [`lacing.MediaRef`](#lacing.MediaRef) pointing at this artifact.

Use this to attach an annotation to a region of the artifact:
`MediaRef(asset_id=artifact.asset_id, interval=…)`.

* **Return type:**
  MediaRef

### *class* lacing.ArtifactStore(catalog, blobs=None)

Bases: [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

Facade over an artifact `catalog` and an optional `blobs` store.

The object *is* a `MutableMapping[str, record]` over the catalog —
`store[artifact_id]`, iteration, `len`, `get`, `clear` and the
rest of the mapping surface all act on artifact **metadata records**. The
heavier byte operations ([`put_blob()`](#lacing.ArtifactStore.put_blob), [`get_blob()`](#lacing.ArtifactStore.get_blob),
[`has_blob()`](#lacing.ArtifactStore.has_blob)) are rich methods that are deliberately *not* squeezed
into the mapping protocol.

* **Parameters:**
  * **catalog** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), `BaseModel`]) – Injected `id -> record` store. Records are pydantic models
    (`lacing.Artifact` by default, but any `BaseModel` works — the
    store does not inspect the record’s shape).
  * **blobs** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Injected `content_hash -> bytes` store, or `None` for a
    catalog-only store (Stage-1 metadata persistence). Blob methods
    raise / no-op when it is `None`. This is the *raw* backend:
    on a filesystem backend its own `del` and iteration do no
    containment check, so go through [`delete_blob()`](#lacing.ArtifactStore.delete_blob) and
    [`iter_blobs()`](#lacing.ArtifactStore.iter_blobs) (and the read methods) rather than touching
    `store.blobs` directly (lacing#55).

Construct one with [`in_memory()`](#lacing.ArtifactStore.in_memory) or [`from_directory()`](#lacing.ArtifactStore.from_directory) rather than
wiring the backing stores by hand, unless you are injecting a custom
backend.

#### blob_location(content_hash)

Resolve the cheapest *servable* location for a blob — without
reading its bytes. The capability the HTTP layer probes to serve a
blob the most efficient way, generalizing [`blob_path()`](#lacing.ArtifactStore.blob_path) so
filesystem / S3 / R2 backends all answer one probe:

- **object-store** backends (S3/R2) that expose a presigned-URL
  capability — a `url_for(content_hash)` callable — return a \*\*URL
  string\*\*, so the caller can 302-redirect and let the object store
  serve the bytes (and HTTP `Range`) directly, off the app process;
- **filesystem** backends return a local **Path** (see
  [`blob_path()`](#lacing.ArtifactStore.blob_path)) so the caller hands the OS the file (Range free);
- everything else (plain `dict`, or a missing blob) returns
  `None` — the cue to fall back to [`iter_blob()`](#lacing.ArtifactStore.iter_blob) streaming.

Callers treat `None` as “stream it”, not as an error.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### blob_path(content_hash)

Return the local filesystem path of the blob, or `None`.

The store’s blob backend is opaque (any `MutableMapping`), but some
backends — notably the filesystem-backed `dol.Files` produced by
[`from_directory()`](#lacing.ArtifactStore.from_directory) — store each blob as one file under a known
root directory. This method exposes that path *when available*, so a
caller (e.g. a FastAPI route serving video) can hand the OS the file
descriptor and let it answer HTTP `Range` requests directly. It
returns `None` for:

- blob stores without a `rootdir` attribute (e.g. plain `dict`,
  object-store backends — callers should fall back to
  [`iter_blob()`](#lacing.ArtifactStore.iter_blob));
- blobs that are not present.
- a `content_hash` that does not resolve to a path *inside*
  `rootdir` (path traversal, e.g. `"../../etc/passwd"` or an
  absolute path, or a same-named symlink pointing outside the
  store) — refused rather than served (lacing#50).

Callers must treat `None` as the cue to use the streaming read
path, not as an error. Deleting and listing blobs have contained
counterparts too ([`delete_blob()`](#lacing.ArtifactStore.delete_blob), [`iter_blobs()`](#lacing.ArtifactStore.iter_blobs)), and the
[`from_directory()`](#lacing.ArtifactStore.from_directory) catalog confines artifact ids the same way
(lacing#55).

The containment check is *point-in-time*: the returned path is the
fully resolved, symlink-free location of a regular file that was
inside `rootdir` when checked. The caller opens it later, by name,
so if untrusted parties can write into `rootdir` itself, open it
with `O_NOFOLLOW` — or serve via [`iter_blob()`](#lacing.ArtifactStore.iter_blob), which reads
through a descriptor and has no such window.

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
[`blob_location()`](#lacing.ArtifactStore.blob_location) probing a blob store for `url_for`): a catalog
backend that can answer the count cheaply — the SQL catalog from
[`from_sql()`](#lacing.ArtifactStore.from_sql), via an indexed `content_hash` column — exposes a
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

#### delete_blob(content_hash)

Delete the blob `content_hash`; `KeyError` if there is none.

The contained counterpart of `del store.blobs[content_hash]`
(lacing#55). On a filesystem-backed store (one exposing `rootdir`)
a key is deleted only if [`has_blob()`](#lacing.ArtifactStore.has_blob) would say it exists — a
regular file that resolves inside `rootdir` (see
`_ContainedDirStore`, the same gate the catalog of
[`from_directory()`](#lacing.ArtifactStore.from_directory) uses). A key that escapes (`..`, an absolute path, a
NUL, a symlink pointing outside) raises `KeyError` exactly like a
missing blob, as does any key with a `..` segment, and nothing
outside the root is touched. The deletion itself is delegated to the
backend’s own `__delitem__` on the key as given (normalised), so the
backend’s delete policy (e.g. `dol.Files` moving files to the
trash) is unchanged, and deleting an in-root symlink removes the
link, never the blob it points at.

The check is point-in-time, like [`blob_path()`](#lacing.ArtifactStore.blob_path): a party that can
write into `rootdir` and swap a *directory* component of a nested
key for a symlink between the check and the delete can still redirect
it. Flat content-hash keys, which is all this store writes, have no
such component.

Backends without a `rootdir` (`dict`, object stores) have no
filesystem to escape; the key passes through to their `del`.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – no such blob, the key escapes the root, or no blob store
      is configured.
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *classmethod* from_aws(bucket_name, uri, \*, record_type=<class 'lacing.artifact.Artifact'>, collection_name='artifact_catalog', prefix=None, s3_kwargs=None, sql_kwargs=None)

The production pairing: **S3-compatible blobs + SQL catalog**.

A thin convenience over [`from_s3()`](#lacing.ArtifactStore.from_s3) (blobs) and [`from_sql()`](#lacing.ArtifactStore.from_sql)
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
  * **s3_kwargs** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Extra kwargs forwarded to [`from_s3()`](#lacing.ArtifactStore.from_s3) (credentials,
    `endpoint_url` for R2/MinIO/Supabase, `region_name`, …).
  * **sql_kwargs** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Extra kwargs forwarded to [`from_sql()`](#lacing.ArtifactStore.from_sql)
    (`content_hash_of`, SQLAlchemy engine kwargs, …).
* **Return type:**
  [`ArtifactStore`](lacing.artifact_store.html.md#lacing.artifact_store.ArtifactStore)

#### *classmethod* from_directory(root, \*, record_type=<class 'lacing.artifact.Artifact'>)

An ArtifactStore persisted under `root`.

Lays out two subdirectories: `catalog/` (one `<id>.json` file per
record) and `blobs/` (one file per content hash). Both are `dol`
filesystem stores, so the same facade works unchanged over any other
`dol` backend (object storage, etc.) when injected directly.

Artifact ids are confined to `catalog/` (lacing#55): an id whose
`<id>.json` would resolve outside it — `..` segments, an absolute
path, a NUL, or a symlink pointing out — is refused with `KeyError`
on get, save and delete, and is simply not `in` the store. Nested
ids (`"a/b"`) that stay inside keep working, and listing never
follows a symlinked directory out of `catalog/`. See
`_ContainedDirStore`.

* **Parameters:**
  * **root** ([`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Directory to hold the store. Created if missing.
  * **record_type** ([`type`](https://docs.python.org/3/builtins/functions.html#type)[`BaseModel`]) – The pydantic model the catalog deserializes JSON into.
    Defaults to [`Artifact`](lacing.artifact.html.md#lacing.artifact.Artifact); callers with
    their own record schema pass their model here.
* **Return type:**
  [`ArtifactStore`](lacing.artifact_store.html.md#lacing.artifact_store.ArtifactStore)

#### *classmethod* from_s3(bucket_name, , catalog=None, prefix=None, \*\*s3_kwargs)

An ArtifactStore with **blobs in an S3-compatible object store**
(AWS S3 / Cloudflare R2 / MinIO / Supabase) via `s3dol`.

Content-addressed blobs are a natural fit for object storage: flat,
immutable, dedup-friendly, forever-cacheable keys. [`blob_location()`](#lacing.ArtifactStore.blob_location)
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
  [`ArtifactStore`](lacing.artifact_store.html.md#lacing.artifact_store.ArtifactStore)

Requires `s3dol>=1` (and `boto3`) — imported lazily so the
dependency is only needed when this constructor is used.

#### *classmethod* from_sql(uri, \*, blobs=None, record_type=<class 'lacing.artifact.Artifact'>, collection_name='artifact_catalog', content_hash_of=None, \*\*db_kwargs)

An ArtifactStore with a **SQL-backed catalog** (durable, queryable)
via `sqldol` — the SQL counterpart of [`from_s3()`](#lacing.ArtifactStore.from_s3)’s object store.

The catalog row schema is deliberately minimal and **vendor-neutral**:
one `TEXT` column holds the record serialized exactly as
[`from_directory()`](#lacing.ArtifactStore.from_directory) serializes it (`record.model_dump_json` out,
`record_type.model_validate_json` in), and one indexed `content_hash`
column carries the record’s blob hash so the GC reference count
([`count_refs()`](#lacing.ArtifactStore.count_refs)) is a single indexed query rather than a full scan.

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
persistence; see [`from_aws()`](#lacing.ArtifactStore.from_aws) for the common S3 + SQL pairing).

* **Parameters:**
  * **uri** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – SQLAlchemy connection URI (`sqlite:///…` or
    `postgresql://…`). The single knob that selects the vendor.
  * **blobs** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional `content_hash -> bytes` blob store. `None` for a
    catalog-only store.
  * **record_type** ([`type`](https://docs.python.org/3/builtins/functions.html#type)[`BaseModel`]) – The pydantic model the catalog deserializes JSON into.
    Defaults to [`Artifact`](lacing.artifact.html.md#lacing.artifact.Artifact); callers with
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
  [`ArtifactStore`](lacing.artifact_store.html.md#lacing.artifact_store.ArtifactStore)

Requires `sqldol` (and `SQLAlchemy`) — imported lazily so the
dependency is only needed when this constructor is used.

#### get_blob(content_hash)

Return the bytes for `content_hash`, or `None` if absent.

On a filesystem-backed store (one exposing `rootdir`) the bytes are
read through `_open_within()`, never by re-opening the path by
name, so a key that would land outside `rootdir` — by `..`, an
absolute path, or a symlink, including one swapped in *after* the
containment check (lacing#50) — reads as absent.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### has_blob(content_hash)

Whether the blob store holds `content_hash`.

On a filesystem-backed store this is exactly “would [`get_blob()`](#lacing.ArtifactStore.get_blob)
return bytes”: `False` for a key that resolves outside `rootdir`
or names anything but a regular file — see `_open_within()`.
Backends without a `rootdir` (`dict`, object stores) have no
filesystem to escape, so their keys pass through unfiltered.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### *classmethod* in_memory()

An ArtifactStore backed entirely by in-memory dicts.

For tests, scratch work, and as the trivial reference backend. Nothing
persists across processes.

* **Return type:**
  [`ArtifactStore`](lacing.artifact_store.html.md#lacing.artifact_store.ArtifactStore)

#### index()

Return the whole catalog as a plain dict (e.g. for UI hydration).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), `BaseModel`]

#### iter_blob(content_hash, , chunk_size=65536)

Yield the blob’s bytes in `chunk_size` chunks.

The streaming counterpart to [`get_blob()`](#lacing.ArtifactStore.get_blob) — what an HTTP response
body iterates over when serving a large blob without holding it all
in process memory. The default implementation reads the whole blob
via [`get_blob()`](#lacing.ArtifactStore.get_blob) and re-chunks it; a filesystem-backed store can
be swapped for a true streaming reader without changing this API.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – no blob exists for `content_hash`.
* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

#### iter_blobs()

Yield the content hash (key) of every blob in the blob store.

The contained counterpart of `iter(store.blobs)` (lacing#55). On a
filesystem-backed store it yields exactly the keys [`has_blob()`](#lacing.ArtifactStore.has_blob)
accepts — regular files inside `rootdir` — and never descends into
a symlinked directory (`dol.Files` does, so its listing can yield
files that live outside the root, or loop on a symlink cycle).
Hidden entries are skipped, as `dol.Files` skips them, which also
keeps the in-flight `.blob-*.part` spool files of
[`put_blob_stream()`](#lacing.ArtifactStore.put_blob_stream) out of the listing.

Yields nothing when no blob store is configured; other backends are
iterated as they are.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### put_blob(data)

Store `data` content-addressed; return its content hash.

Idempotent: identical bytes always map to the same hash and overwrite
an identical blob. Delegates to [`put_blob_stream()`](#lacing.ArtifactStore.put_blob_stream) so there is
exactly one write path — and therefore one atomicity story
(lacing#25).

* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – no blob store is configured.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### put_blob_stream(chunks)

Stream `chunks` content-addressed; return their SHA-256 hash.

The streaming-friendly counterpart to [`put_blob()`](#lacing.ArtifactStore.put_blob) — callers hand
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

### *exception* lacing.BodySchemaError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

Raised when a body fails validation against its registered schema.

### *exception* lacing.EmptySchemaRegistryError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when an export would write an empty registry over real artifacts.

Almost always means the caller forgot `import lacing.bodies`: the
registry is populated by importing the body modules, so exporting without
that import silently truncates `index.json` to `{}` and leaves the
committed `v<N>.json` files orphaned.

### *class* lacing.InMemoryOpLog

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Simple list-backed op-log. Thread-safe via an RLock.

### *class* lacing.IntervalAnnotationStore(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Protocol for any interval-keyed annotation store.

Conceptually a `MutableMapping[TimeInterval, list[Annotation]]`: keys
are `TimeInterval`; values are lists because multiple annotations can
share an interval (different tiers, multiple annotators, soft labels).

We use `Protocol` rather than inheriting from `MutableMapping` so
backends (in-memory, SQLite, Postgres) can structurally conform without
forcing a single class hierarchy. The mapping methods below match the
`MutableMapping` ABC; concrete backends like [`MemoryStore`](#lacing.MemoryStore)
implement the full interface.

#### add(annotation)

Append `annotation` to the list at its reference interval.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### all()

Iterate every annotation in the store, order unspecified.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### at_tier(tier_name, query)

Annotations on `tier_name` that intersect `query`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### by_tier(tier_name)

All annotations on `tier_name`, regardless of interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### contains(query)

Annotations whose interval strictly contains `query` (Allen `di`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### during(query)

Annotations whose interval is strictly inside `query` (Allen `d`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### equals(query)

Allen `=`: identical interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### extend(annotations)

Add many; equivalent to repeated `.add` but adapters can optimize.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### finishes(query)

Allen `f`: later start, same end.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### intersects(query)

Annotations whose interval shares any time with `query`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### meets(query)

Allen `m`: `a.end == q.start`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### overlaps(query)

Strict Allen `o`: `a.start < q.start < a.end < q.end`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### relate(query, relations)

Annotations whose interval has any of the named `relations` to `query`.

Generic dispatch — useful when relations are computed at runtime.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### remove(annotation_id)

Remove and return the annotation with this id, or None if absent.

* **Return type:**
  [`Annotation`](lacing.model.html.md#lacing.model.Annotation) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### starts(query)

Allen `s`: same start, earlier end.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.html.md#lacing.model.Annotation)]

#### tiers()

Registered tiers. Annotations may reference tiers not yet registered;
callers decide whether that’s an error.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Tier`](lacing.tier.html.md#lacing.tier.Tier)]

### *exception* lacing.LossyTimeConversionError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

Raised when a rate or seconds conversion would lose precision.

### *class* lacing.MediaRef(\*\*data)

Bases: `BaseModel`

Reference to a region of a content-addressed media asset.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.MemoryStore

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`IntervalAnnotationStore` implementation over `intervaltree`.

Conforms to the protocol in `lacing.store.base`. We don’t formally
inherit from `IntervalAnnotationStore` because it’s a `Protocol`
with method bodies — structural typing is enough.

### *exception* lacing.MigrationError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when a migration step is missing or fails.

### *class* lacing.NodeRef(\*\*data)

Bases: `BaseModel`

Reference to a node in a structured scene/document graph.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *exception* lacing.NonStringBodyKeyError

Bases: [`TypeError`](https://docs.python.org/3/builtins/exceptions.html#TypeError)

An annotation `body` contains a mapping key that is not a `str`.

JSON object keys are strings, so `model_dump(mode="json")` coerces
non-string keys — and two distinct keys can coerce to the *same* string,
silently annihilating an entry. `{1: "a", "1": "b"}` dumps to
`{"1": "b"}`; a body differing only in the lost entry would digest
identically, which is a wrong cache **hit**.

Since lacing#24 the *envelope* refuses such a body at validation — the
producer-side fix. This error lives here rather than in `lacing.model`
because this module is deliberately import-light (stdlib only, pinned by
test) and the model can import from it, not vice versa.

### *class* lacing.OpLog(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Append-only log of mutations.

Implementations must guarantee that the clock returned by
[`append()`](#lacing.OpLog.append) is strictly greater than every previously-returned
clock value across the lifetime of the log.

#### append(operation, , target_id=None, payload=None, actor='anonymous')

Append an entry; return its assigned clock.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### entries(, until_clock=None, from_clock=None)

Iterate entries, optionally bounded by clock range (inclusive).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`OpLogEntry`](lacing.oplog.html.md#lacing.oplog.OpLogEntry)]

#### latest_clock()

Highest clock currently in the log; 0 if empty.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### *class* lacing.OpLogEntry(clock, operation, target_id, payload, actor='anonymous', received_at=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One row of the op-log.

#### actor *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`user:<handle>` or `agent:<model>@<hash>` or `adapter:<format>`.

#### clock *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Monotonic Lamport clock starting at 1. Strictly increasing per log.

#### operation *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`add_annotation`, `remove_annotation`, `update_annotation`,
`add_tier`, `set_meta`, `import_batch`.

* **Type:**
  One of

#### payload *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

JSON-serializable payload sufficient to replay the operation.

#### received_at *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Wall-clock time the operation was received (seconds since epoch).

#### target_id *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)*

Annotation id, tier name, meta key, or None for batch ops.

### *exception* lacing.ProcessorError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when a registered processor’s invocation fails.

### *class* lacing.Provenance(\*\*data)

Bases: `BaseModel`

W3C PROV-O subset, embedded inline on every annotation.

#### *property* generated_at_is_known *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

`False` when `generated_at_time` is the `UNKNOWN_GENERATED_AT` sentinel.

The one test every freshness or ordering consumer should make before
comparing `generated_at_time` values: an unknown time cannot be
ordered against a known one, and a consumer that compares anyway
reads the row as older than everything (lacing#44).

```pycon
>>> from lacing.time import RationalTime
>>> kw = dict(was_generated_by="user:x", was_attributed_to="x")
>>> Provenance(generated_at_time=RationalTime(0, 1000), **kw).generated_at_is_known
False
>>> Provenance(generated_at_time=RationalTime.now(), **kw).generated_at_is_known
True
```

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.RationalTime(value, rate=24000)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A point in time as `value / rate` seconds.

Immutable. Two `RationalTime` values with different rates compare via
their rational value, so `RationalTime(24, 24) == RationalTime(1, 1)`.

### Examples

```pycon
>>> RationalTime(24000) == RationalTime(1, 1)
True
>>> RationalTime.from_seconds("1.5", rate=2).value
3
```

#### *classmethod* from_seconds(seconds, rate=24000)

Build from seconds. Quantizes to `rate`; raises if lossy.

`seconds` may be a `str` like `"1.001"` to avoid float ingestion.

* **Return type:**
  [`RationalTime`](lacing.time.html.md#lacing.time.RationalTime)

#### *classmethod* from_seconds_lossy(seconds, , rate=24000, mode='round')

Build from seconds, quantizing to the nearest sample at `rate`.

Unlike [`from_seconds()`](#lacing.RationalTime.from_seconds) — which raises
[`LossyTimeConversionError`](#lacing.LossyTimeConversionError) when the value cannot be
represented exactly — this method always succeeds by quantizing.
`mode` selects the rounding rule:

- `"round"` — nearest sample, ties to even (default)
- `"floor"` — largest sample <= `seconds`
- `"ceil"`  — smallest sample >= `seconds`

Use this when sample-level quantization is knowingly acceptable —
the common case for user-supplied durations. Use [`from_seconds()`](#lacing.RationalTime.from_seconds)
when exactness matters and a lossy conversion should be an error.

### Examples

```pycon
>>> RationalTime.from_seconds_lossy("0.1", rate=3).value
0
>>> RationalTime.from_seconds_lossy("0.1", rate=3, mode="ceil").value
1
```

* **Return type:**
  [`RationalTime`](lacing.time.html.md#lacing.time.RationalTime)

#### *classmethod* from_wire(d)

Build from the wire form. Unknown keys are an error, not ignored.

`RATIONAL_TIME_JSON_SCHEMA` sets `additionalProperties: false` and
lacing-ui’s Zod mirror is `.strict()`; accepting extras here would
make Python the one lax end of a contract both other ends enforce, so
a `{"v": 0, "r": 1, "seconds": 0.0}` payload would round-trip through
Python and then be rejected by the frontend.

* **Return type:**
  [`RationalTime`](lacing.time.html.md#lacing.time.RationalTime)

#### *classmethod* now(rate=24000)

Wall-clock time as a [`RationalTime`](#lacing.RationalTime), quantized to `rate`.

Uses `time.time_ns()` and builds the value directly, sidestepping
the float-quantization landmine of `from_seconds(float)`. Every
producer of an annotation or artifact needs this for
`Provenance.generated_at_time` — the only value that field reads
as a *known* time. Tick 0 there is the UNKNOWN sentinel
(`lacing.model.UNKNOWN_GENERATED_AT`), never the epoch.

* **Return type:**
  [`RationalTime`](lacing.time.html.md#lacing.time.RationalTime)

#### to_rate(new_rate)

Re-express at `new_rate`. Raises `LossyTimeConversionError` on loss.

* **Return type:**
  [`RationalTime`](lacing.time.html.md#lacing.time.RationalTime)

#### to_seconds()

Float seconds — for display only. Never round-trip through this.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### *classmethod* zero(rate=24000)

Tick 0 at `rate` — the start of a media timeline.

Not a wall-clock timestamp: as a `Provenance.generated_at_time` it
is the UNKNOWN sentinel (`lacing.model.UNKNOWN_GENERATED_AT`), not
the epoch. Producers stamp [`now()`](#lacing.RationalTime.now) there.

* **Return type:**
  [`RationalTime`](lacing.time.html.md#lacing.time.RationalTime)

### *exception* lacing.SchemaMismatchError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when opening a `.annot` file with an incompatible schema.

### *class* lacing.SqliteOpLog(path, , check_same_thread=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Op-log backed by a SQLite table.

Designed to share a database file with `SqliteStore` so the store
snapshot + the op-log live together and survive a single
`cp project.annot project.backup` step.

### *class* lacing.SqliteStore(path, , check_same_thread=True, migrate=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

SQLite-backed `IntervalAnnotationStore`.

* **Parameters:**
  * **path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)) – Path to the `.annot` file. Use `":memory:"` for an
    ephemeral in-memory database.
  * **check_same_thread** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Forwarded to `sqlite3.connect`. We hold a
    single connection guarded by a lock; pass `False` when
    sharing across threads.
  * **migrate** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Opt-in to upgrading a file written at an older
    `schema_version` on open, via the ladder in
    [`lacing.store.migrations`](lacing.store.migrations.html.md#module-lacing.store.migrations). Off by default — silently
    rewriting someone’s file on open is worse than refusing.
    Every open-time schema failure — refusal *or* failed migration
    — raises [`SchemaMismatchError`](#lacing.SchemaMismatchError); a failed migration
    chains the ladder’s `StoreMigrationError` as its cause.

### *exception* lacing.StoreMigrationError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when a store migration step is missing or fails.

### *class* lacing.Tier(name, , stereotype=TierStereotype.NONE, parent=None, metadata=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A named annotation layer with optional parent and stereotype.

Tiers are pure metadata; they don’t own annotations. The store is keyed
by interval, not by tier — annotations carry their tier name as a field.
This matches ELAN’s TIME_ORDER indirection (see ANN-DOC §C).

### *class* lacing.TierStereotype(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Constraints on how a child tier relates to its parent tier.

Names match ELAN exactly so EAF round-trips are trivial.

#### INCLUDED_IN *= 'INCLUDED_IN'*

Children lie within the parent but gaps between siblings are allowed.

#### NONE *= 'NONE'*

No parent constraint. Top-level tier.

#### SYMBOLIC_ASSOCIATION *= 'SYMBOLIC_ASSOCIATION'*

One-to-one association with parent; child shares parent’s interval exactly.

#### SYMBOLIC_SUBDIVISION *= 'SYMBOLIC_SUBDIVISION'*

Ordered subdivision; children share parent’s interval as a sequence (no times).

#### TIME_SUBDIVISION *= 'TIME_SUBDIVISION'*

Children fully partition the parent’s interval (no gaps, no overlap).

### *class* lacing.TimeInterval(start, end)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A half-open interval `[start, end)`.

`start == end` is a valid point annotation, not a degenerate case.
Always `start <= end`; constructor raises `ValueError` otherwise.

#### *property* duration *: [RationalTime](lacing.time.html.md#lacing.time.RationalTime)*

`end - start` at the same rate as `start`.

#### *classmethod* from_wire(d)

Build from the wire form. See [`RationalTime.from_wire()`](#lacing.RationalTime.from_wire) on extras.

* **Return type:**
  [`TimeInterval`](lacing.time.html.md#lacing.time.TimeInterval)

### *exception* lacing.UnknownBodySchemaError

Bases: [`KeyError`](https://docs.python.org/3/builtins/exceptions.html#KeyError)

Raised when an annotation’s body_schema_uri has no registered model.

### lacing.annotation_body_digest(annotation)

Return the SHA-256 hex digest of `{body, body_schema_uri}` only.

The narrow sibling of [`annotation_value_digest()`](#lacing.annotation_value_digest). It drops the
**entire** `reference` — *which asset* / *which node* / \*which
annotation\*, not merely *when* — plus `tier` and `confidence`. So the
same caption over two **different assets** digests identically here, as
does the same body asserted on two different tiers or at two different
confidences.

That is a correctness bug in any consumer that reads any of those. Reach
for it only when the consumer demonstrably depends on nothing but what the
annotation *says*; prefer [`annotation_value_digest()`](#lacing.annotation_value_digest) otherwise.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> from uuid import uuid4
>>> from lacing import Annotation, MediaRef, Provenance
>>> from lacing import RationalTime, TimeInterval
>>> def over(asset):
...     return Annotation(
...         id=uuid4(), tier="words",
...         reference=MediaRef(
...             asset_id=asset,
...             interval=TimeInterval(RationalTime(0), RationalTime(24000)),
...         ),
...         body={"text": "hello"},
...         body_schema_uri="annot://schema/word/v1",
...         provenance=Provenance(
...             was_generated_by="agent:m@1",
...             was_attributed_to="thor",
...             generated_at_time=RationalTime.now(),
...         ),
...     )
```

Different **assets**, identical body digest — this is the footgun:

```pycon
>>> annotation_body_digest(over("sha256:interview")) == (
...     annotation_body_digest(over("sha256:broadcast"))
... )
True
>>> annotation_value_digest(over("sha256:interview")) == (
...     annotation_value_digest(over("sha256:broadcast"))
... )
False
```

```pycon
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
...             generated_at_time=RationalTime.now(),
...         ),
...     )
>>> early = make(TimeInterval(RationalTime(0), RationalTime(24000)))
>>> late = make(TimeInterval(RationalTime(24000), RationalTime(48000)))
>>> annotation_body_digest(early) == annotation_body_digest(late)
True
>>> annotation_value_digest(early) == annotation_value_digest(late)
False
```

### lacing.annotation_value_digest(annotation)

Return the SHA-256 hex digest of `annotation`’s value.

Covers `body`, `body_schema_uri`, `tier`, `reference` and
`confidence`. Excludes `id` and `provenance`, so a regeneration that
produces identical content produces an identical digest.

Use this for freshness and early cutoff. For optimistic concurrency use
`lacing.server.etag.annotation_etag()` instead — two digests, two
jobs, and neither substitutes for the other.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
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
...             generated_at_time=RationalTime.now(),
...         ),
...     )
...     base.update(kw)
...     return Annotation(**base)
```

A regeneration — new `id`, new timestamp, same content — digests the same:

```pycon
>>> a = make()
>>> b = make(provenance=Provenance(
...     was_generated_by="agent:m@1",
...     was_attributed_to="thor",
...     generated_at_time=RationalTime(999),
... ))
>>> annotation_value_digest(a) == annotation_value_digest(b)
True
```

A changed body does not:

```pycon
>>> annotation_value_digest(make(body={"text": "goodbye"})) == (
...     annotation_value_digest(a)
... )
False
```

### lacing.boundary_iou(a, b)

Mean IoU between two sets of intervals via greedy best-match.

For each interval in `a`, finds its highest-IoU match in `b` (without
replacement — once a `b` interval is matched it’s removed from the pool).
Unmatched intervals in either set contribute 0.0 to the mean.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  Mean IoU ∈ [0, 1]. Returns 0.0 if both sets are empty (defensible
  as a “no agreement to measure” baseline).

### lacing.cohen_kappa(a, b)

Cohen’s kappa for two annotators on a categorical label.

* **Parameters:**
  * **a** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable))]) – Annotator A’s labels.
  * **b** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable))]) – Annotator B’s labels (must be the same length).
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  κ ∈ [-1, 1]. 1 = perfect agreement, 0 = chance, negative = worse than chance.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If sequences differ in length or are empty.

Edge cases:
: If only one category appears across both annotators, both observed
  and expected agreement are 1.0; we return 1.0 by convention.

### lacing.export_json_schemas(target_dir, , overwrite=True, include_meta=True, allow_empty=False)

Write every registered schema as JSON files under `target_dir`.

Layout: `<target_dir>/<name>/v<N>.json`. Returns the list of paths
written, in registration order.

* **Parameters:**
  * **target_dir** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)) – Output directory. Created if missing.
  * **overwrite** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If False, refuse to write a file that already exists.
  * **include_meta** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, also write a `<target_dir>/index.json`
    mapping every URI to its file path and the Pydantic model’s
    qualified name (helps the codegen pipeline).
  * **allow_empty** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, permit an export from an empty registry. The
    default refuses, because the overwhelmingly likely cause is a
    missing `import lacing.bodies` and the write would destroy the
    committed artifacts.
* **Raises:**
  [**EmptySchemaRegistryError**](#lacing.EmptySchemaRegistryError) – Nothing is registered and `allow_empty`
      is False.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### lacing.get_tracer(name='lacing', version=None)

Return a tracer or a no-op fallback.

* **Parameters:**
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Instrumentation name (typically `__name__` of the caller’s
    module or a logical name like `"lacing.server"`).
  * **version** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional package version string.
* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)
* **Returns:**
  `opentelemetry.trace.Tracer` if OTel is installed, else a no-op
  object whose `start_as_current_span()` is a context manager
  yielding a no-op span.

### lacing.hash_bytes(data)

Return the canonical `asset_id` (SHA-256 hex) for `data`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> hash_bytes(b"hello world")[:8]
'b94d27b9'
```

### lacing.hash_file(path, , chunk_size=1048576)

Return the canonical `asset_id` (SHA-256 hex) for the file at `path`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### lacing.instrument_otel(app, , tracer_name='lacing.server')

Add OpenTelemetry instrumentation to a FastAPI app.

Wraps every request in a span; tags the span with the response’s
`X-Lacing-Clock` header value (when present) as `lacing.clock`.

No-op when OTel isn’t installed — the app is returned unchanged.

* **Parameters:**
  * **app** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – The FastAPI app (from `lacing.server.create_app()`).
  * **tracer_name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Name passed to [`get_tracer()`](#lacing.get_tracer).
* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)
* **Returns:**
  The same app, with middleware installed if OTel is available.

### lacing.interval_iou(a, b)

Intersection-over-Union for two time intervals.

Returns 1.0 if both are equal point intervals at the same instant; 0.0
if they don’t intersect (including when only one is a point).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### lacing.is_otel_active()

Quick check: is OTel installed AND a TracerProvider configured?

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### lacing.json_schema(uri)

Return the JSON Schema for the body model registered at `uri`.

Pydantic’s `model_json_schema()` output, unmodified.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### lacing.krippendorff_alpha(annotations, \*, distance=<function \_nominal_distance>)

Krippendorff’s α across any number of annotators.

* **Parameters:**
  * **annotations** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable))]]]) – A list of annotators, each a sequence of labels (one per
    unit). Use `None` for a missing annotation by that annotator on
    that unit.
  * **distance** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable)), [`TypeVar`](https://docs.python.org/3/library/typing.html#typing.TypeVar)(`T`, bound= [`Hashable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Hashable))], [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Function `(x, y) -> float` measuring disagreement between
    two label values. Default is the nominal (0/1) distance.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  α. 1.0 = perfect agreement, 0.0 = chance.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If sequences differ in length, fewer than 2 annotators
      given, or fewer than 2 paired observations exist.

### lacing.maybe_span(tracer, name, \*\*attributes)

Open a span on `tracer`, attaching `attributes` if supported.

Works with both real OTel tracers and the no-op fallback.

### lacing.migrate(body, , from_uri, to_uri)

Migrate `body` from `from_uri` to `to_uri` via registered steps.

Composes single-step migrations. Raises [`MigrationError`](#lacing.MigrationError) if any
step is missing.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### lacing.migrate_annot_file(path, , to_version=None)

Migrate a `.annot` file in place, returning `(from, to)` versions.

`to_version` defaults to the current build’s
[`lacing.store.sqlite.SCHEMA_VERSION`](lacing.store.sqlite.html.md#lacing.store.sqlite.SCHEMA_VERSION). Already-current files are a
no-op (`from == to`). Each step runs in its own `BEGIN IMMEDIATE`
transaction with the version re-checked under the lock, so concurrent
migrators converge and an interrupted chain resumes from the last
version that completed (idempotent).

Raises [`StoreMigrationError`](#lacing.StoreMigrationError) when the file does not exist, is
not a `.annot` file, a step is missing, fails, or breaks one of the
runner’s in-transaction guarantees.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### lacing.register_body_schema(uri, model)

Register `model` as the validator for `uri`. Returns `model`.

* **Return type:**
  [`type`](https://docs.python.org/3/builtins/functions.html#type)[`BaseModel`]

### lacing.register_migration(, schema_name, from_version, to_version)

Register a forward migration from `v<from_version>` to `v<to_version>`.

Decorated function takes a body `dict` and returns a new body `dict`.
Migrations must be one major-version step at a time
(`to_version == from_version + 1`).

Re-registering the same `(schema_name, from_version)` pair replaces
the previous entry — convenient in tests, intentional for hot-reload.

### lacing.register_processor(func=None, , name=None)

Register a processor under `name` (defaults to the function name).

The function may be sync or async; we wrap sync funcs to a coroutine.

### lacing.register_store_migration(, store_kind, from_version, to_version)

Register a forward store migration from `from_version` to `to_version`.

The decorated function takes the backend’s open connection and must
perform every change of the step — DDL, row rewrites, and the
`meta.schema_version` write. Steps must be one version at a time
(`to_version == from_version + 1`); the runner chains them.

Step authors: read the module docstring’s rules — no `executescript`
/ `COMMIT` / `ROLLBACK` inside a step, preserve rowids on table
rebuilds, and rebuild the interval index with
`rebuild_annotations_rtree()` if the `annotations` table was
rebuilt.

Re-registering the same `(store_kind, from_version)` pair replaces the
previous entry.

### lacing.registered_processors()

Names of every registered processor, sorted.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### lacing.render_artifact_exhibit(annotations, , out_dir, formats=('html', 'pdf', 'md'), title='Artifact exhibit', image_resolver=None)

Render an annotation graph as a human-readable artifact exhibit.

Lays every annotation out as a card — body, panel images, and
in-document hyperlinks to the artifacts it derives from / feeds
into. **HTML is authored**; the PDF and Markdown derive from it.

Panel images are written once as content-addressed sibling files
under `<out_dir>/images/` and referenced relatively, so the HTML
and Markdown stay small; the PDF embeds them and stays a single
self-contained file. The `images/` directory is created only when
the graph actually has images.

* **Parameters:**
  * **annotations** ([`Iterable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterable)) – the lacing annotations to exhibit (any iterable).
    Order is preserved — pass them chain-ordered for a document
    that reads top-to-bottom.
  * **out_dir** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)) – directory the `exhibit.{html,pdf,md}` files land in.
  * **formats** ([`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – which of `html` / `pdf` / `md` to write. The HTML
    is always built in memory (the others derive from it).
  * **title** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – document title.
  * **image_resolver** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – `image-reference → local file path` callback.
    Defaults to reading the reference’s own `path` field; a
    caller whose images live behind URLs passes a resolver that
    downloads / caches them (keeping this module media-agnostic).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]
* **Returns:**
  The written file paths.
* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – when `pdf` / `md` is requested but its optional
      converter (`weasyprint` / `dn`) is not installed — the
      message names the install command.

### lacing.replay_oplog(log, , until_clock=None, target_factory=None)

Rebuild a store by replaying `log` up to (and including) `until_clock`.

* **Parameters:**
  * **log** ([`OpLog`](lacing.oplog.html.md#lacing.oplog.OpLog)) – Source op-log.
  * **until_clock** ([`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Stop at this clock (inclusive). None = replay all.
  * **target_factory** – Zero-arg callable returning a fresh empty store.
    Defaults to `MemoryStore`. Pass a `SqliteStore` factory to
    replay into a persistent file.
* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)
* **Returns:**
  The rebuilt store. Operations whose payload references unknown
  body schemas or tier parents are still applied; the caller is
  responsible for any post-replay validation.

### *async* lacing.run_processor_async(name, , store, oplog, \*\*kwargs)

Run a processor in the current event loop. For async callers.

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### lacing.run_processor_sync(name, , store, oplog, \*\*kwargs)

Run a processor synchronously and return its result.

If the processor is async, we call it via `asyncio.run` (when no
loop is running) or schedule and wait on it (when a loop is already
active). Most callers from sync code want the former.

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### lacing.traced(tracer, span_name=None, , record_args=False)

Decorator: wrap a function in a span on `tracer`.

* **Parameters:**
  * **tracer** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – From [`get_tracer()`](#lacing.get_tracer).
  * **span_name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Override the span name. Default: `func.__qualname__`.
  * **record_args** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, attach (str-coerced) positional + keyword
    args as span attributes `arg.<n>` / `kwarg.<name>`. Off
    by default — args may contain large or sensitive data.

### lacing.validate_body(body, uri)

Validate `body` against the schema registered for `uri`.

Returns the parsed Pydantic instance. Raises [`BodySchemaError`](#lacing.BodySchemaError)
on validation failure (wrapping the underlying `pydantic.ValidationError`)
or [`UnknownBodySchemaError`](#lacing.UnknownBodySchemaError) if the URI isn’t registered.

* **Return type:**
  `BaseModel`

### Modules

| [`adapters`](lacing.adapters.html.md#module-lacing.adapters)             | I/O adapter registry.                                                     |
|----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`allen`](lacing.allen.html.md#module-lacing.allen)                   | Allen's 13 interval relations as pure predicates.                         |
| [`artifact`](lacing.artifact.html.md#module-lacing.artifact)             | Content-addressed artifact references.                                    |
| [`artifact_store`](lacing.artifact_store.html.md#module-lacing.artifact_store) | Artifact store — a metadata catalog and a blob store behind one facade.   |
| [`bodies`](lacing.bodies.html.md#module-lacing.bodies)                 | Built-in body schemas.                                                    |
| [`cli`](lacing.cli.html.md#module-lacing.cli)                       | Command-line interface for lacing.                                        |
| [`digest`](lacing.digest.html.md#module-lacing.digest)                 | Content digests over an annotation's *value* — the freshness primitive.   |
| [`exhibit`](lacing.exhibit.html.md#module-lacing.exhibit)               | Artifact exhibit — render an annotation graph as a readable document.     |
| [`model`](lacing.model.html.md#module-lacing.model)                   | Annotation envelope, references, and provenance.                          |
| [`oplog`](lacing.oplog.html.md#module-lacing.oplog)                   | Operation log for time-travel debug + audit.                              |
| [`otel`](lacing.otel.html.md#module-lacing.otel)                     | Optional OpenTelemetry instrumentation for the lacing server.             |
| [`processors`](lacing.processors.html.md#module-lacing.processors)         | Background processors — pluggable jobs that run against a store + op-log. |
| [`quality`](lacing.quality.html.md#module-lacing.quality)               | Inter-annotator agreement and boundary metrics.                           |
| [`schema`](lacing.schema.html.md#module-lacing.schema)                 | Body schema registry, JSON Schema export, and migrations.                 |
| [`store`](lacing.store.html.md#module-lacing.store)                   | Interval-keyed annotation stores.                                         |
| [`tier`](lacing.tier.html.md#module-lacing.tier)                     | Tiers and the five ELAN stereotypes.                                      |
| [`time`](lacing.time.html.md#module-lacing.time)                     | Rational time and half-open intervals — the foundations.                  |
| [`tracks`](lacing.tracks.html.md#module-lacing.tracks)                 | High-level "track-shaped" facades on top of `lacing`.                     |
| [`worker`](lacing.worker.html.md#module-lacing.worker)                 | Optional Arq integration — queue processors through Redis.                |
