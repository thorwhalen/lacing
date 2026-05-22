# Artifact Store Architecture — design notes

*Extraction for lacing developers. Distilled from a 6-part storage-architecture
research series (May 2026) into the parts that bear on **lacing's role**: the
content-addressed artifact store. Treat as inspiration, not a spec — the binding
plan lives in `reelee`.*

---

## Why this concerns lacing

`reelee` needs **backend persistence for generated media artifacts** (images,
video, later audio from fal.ai). Today those artifact objects live only in the
browser. Closing that gap needs a real artifact store — and lacing already owns
the artifact **model**, so it is the natural home for the artifact **store** too.

### What lacing has today

`lacing/artifact.py` — `Artifact`: a frozen Pydantic model.
- `asset_id` — SHA-256 hex of the bytes (the content hash; 64-char).
- `kind` — `image | video | audio | json | text | binary`.
- `path` / `url` — local path and/or remote URL (both optional).
- `bytes_size`, `duration_s`, `mime`, `cost_usd`, `producer_call_id`.
- `provenance` — W3C PROV-O fields (`was_generated_by`, `was_derived_from`, …).
- `Artifact.from_path` / `from_bytes`; `to_media_ref(interval)`; `hash_bytes`,
  `hash_file`.

`Artifact` lives in lacing *on purpose*: every producer (falaw, artful, nw,
mixing) must be able to say "I produced a file" without a wrong-direction
dependency. **The same argument applies to the artifact store** — a generic,
content-addressed store belongs in lacing, not in any one producer or app.

### The gap

`Artifact` is the **metadata model only**. There is no:
- **blob store** — somewhere the bytes physically live, keyed by `asset_id`;
- **catalog** — an index of which artifacts exist and where their bytes are;
- **resolver** — `resolve(asset_id) → bytes | path | url`;
- **garbage collection** — reclaiming unreferenced bytes.

The existing doc *Backend Architecture for Time-Interval Annotation Systems*
§4.3 Q16 already sketches an `assets` table mapping `asset_id → (url, path)`.
These notes turn that sketch into a concrete shape.

---

## The three separable concerns

Any storage system that grows access control is really **three problems**, and
the discipline is keeping them apart (skills: `access-calculus`,
`infrastructure-mapping`, `data-organization`):

1. **Access calculus** — *who may do what* — a pure function.
2. **Infrastructure mapping** — *where* enforcement happens; the facades.
3. **Data organization** — *how* bytes are laid out and keyed.

lacing owns mostly **(3)** and the storage-facing half of **(2)**: a clean,
injectable artifact store. It should **not** bake in access logic — the artifact
store stays an *unprivileged primitive*; `reelee` wraps it with the policy seam.

**Cardinal rule:** never let the storage layout become the permission model.
Artifact bytes keyed flat by `asset_id`; "who can see what" is a *separate*
index. `asset_id` is a content hash — perfectly flat and immutable. Lean into it.

---

## Recommended shape: a content-addressed `ArtifactStore`

Physically flat, logically a graph (the **git** model). Three pieces, each a
`dol` `Mapping` facade so the backend is swappable by dependency injection:

```
ArtifactStore  (facade — domain verbs: save / get / resolve / list / delete)
  ├── blobs    : MutableMapping[asset_id, bytes]      # the heavy bytes
  ├── catalog  : MutableMapping[asset_id, Artifact]   # the metadata index (SSOT)
  └── edges    : (optional) artifact-to-artifact relationships — the DAG
```

- **blobs** — keyed by `asset_id` (= content hash). Content addressing buys
  **dedup**, **immutability** (the key *is* the checksum), **idempotent
  crash-safe writes**, and **forever-cacheable URLs**. Adapter ladder, all behind
  the same `MutableMapping`: in-memory → filesystem (`dol` dir store) → S3/R2
  object store. The user's `dol` is exactly the tool for this ladder.
- **catalog** — keyed by `asset_id`, value an `Artifact` record. SSOT for *what
  exists and where*. Start as a `dol` JSON store or lacing's `SqliteStore`;
  graduate to Postgres if query load demands. **Back it up as critical infra** —
  lose the catalog and the blobs are unidentifiable bytes.
- **edges** — provenance/derivation links. `Artifact.provenance` already carries
  `was_derived_from`; an explicit edges store makes the artifact DAG queryable.

### Identity vs representation vs naming — keep them apart

- **Identity** — `asset_id`. Stable, opaque-to-the-domain, immutable.
- **Representation** — the actual bytes; one logical artifact may have several
  (master + proxy + thumbnail + waveform), each its own content-addressed blob.
- **Naming** — human labels / groupings live in *annotations and edges*, never
  in the blob key.

A folder path welds all three into one mutable string — which is why every
interesting operation becomes a migration. Hold them separately.

### Heavy-media specifics

- **Whole-file hashing, not content-defined chunking.** Compressed video/audio
  re-encodes the whole bitstream on any edit → chunk dedup ≈ 1:1 while metadata
  explodes. Hash the whole file (SHA-256 today; BLAKE3 is a future option).
- **Representations** — precompute cheap derivatives (thumbnail, waveform,
  low-res proxy) on ingest; compute exotic formats on demand.
- **Byte-range reads** — the store's blob interface should forward HTTP `Range`
  so video players seek without downloading the whole file. This is a
  *rich-method* operation — do not torture it into `store[key]`; let a
  rich-method blob object own it alongside the KV repo.

---

## Cross-store consistency (dual write)

No transaction spans the catalog and the blob store. Two failure modes:
- *blob written, catalog not* → **orphan blob** (storage leak — tolerable).
- *catalog written, blob not* → **dangling pointer** (reads break — dangerous).

Because blobs are **content-addressed and immutable**, the write is naturally
idempotent, so the safe ordering is simple: **write the blob first, then commit
the catalog row.** A crash before the commit leaves only an orphan blob; there
is **zero dangling-pointer risk** because the catalog has no record yet. No
outbox needed for the immutable-blob path. A periodic reconciliation job sweeps
orphans after a grace period.

## Garbage collection

Content-addressed blobs are *shared* (dedup) — never hard-delete a blob just
because one reference dropped. Soft-delete; reclaim with reference counting plus
a periodic mark-and-sweep, and **never sweep a blob younger than ~24–48h** (the
grace period defeats the race where a sweep deletes a just-uploaded blob). GC is
a planned background subsystem, not an afterthought.

---

## Dependency-injection seam (open-closed)

The `ArtifactStore` facade depends on **injected** `blobs` / `catalog` stores —
never constructs them. This is what lets reelee ship the simple case first
(in-memory or local filesystem, single user) and the complex case later (object
store, multi-tenant) **with no refactor of the facade or its callers**.

```python
ArtifactStore(blobs=in_memory_store, catalog=in_memory_store)      # tests
ArtifactStore(blobs=filesystem_blobs, catalog=sqlite_catalog)      # local v1
ArtifactStore(blobs=s3_blobs, catalog=postgres_catalog)            # scaled
```

---

## Open decision (resolve in the reelee plan)

**Where does the generic `ArtifactStore` live — lacing or reelee?**
Recommendation: the **facade + the in-memory/filesystem adapters in lacing**
(reusable, no app coupling, same rationale as `Artifact` itself); **deployment
wiring** (which backend, data directories, HTTP routes) **in reelee**. If the
store turns out to need lacing-specific schema coupling, revisit. The reelee
backend remains the place that *wraps* the store with the access-control seam.

*These notes are a living document — refine them as the artifact store is built.*
