# lacing.artifact

Content-addressed artifact references.

An [`Artifact`](#lacing.artifact.Artifact) is a generated file (or remote URL) with provenance.
Anything that *produces* media — a fal.ai call, a `ffmpeg` compose, a
storyboard PDF render, an audio synthesis — returns an `Artifact`.
Anything that *references* an artifact temporally does so via
`MediaRef(asset_id=artifact.asset_id, interval=…)`.

This type lives in lacing (not in falaw or any single producer) because:

- It reuses [`lacing.Provenance`](lacing.md#lacing.Provenance) and [`lacing.MediaRef`](lacing.md#lacing.MediaRef). The
  `asset_id` *is* the content hash that `MediaRef` already documents.
- Multiple producers (falaw, an, nw, artful, mixing) need to express
  “I produced a file.” Putting `Artifact` in any one of them forces a
  wrong-direction dependency from the others.
- The provenance chain (`was_derived_from`, `was_generated_by`) is the
  same shape for an annotation and an artifact. Reusing it unifies lineage.

## Hashing

`asset_id` is the SHA-256 hex digest of the artifact’s bytes. SHA-256 is
in the stdlib, deterministic, and compatible with the
`MediaRef.asset_id` documentation (“BLAKE3 / SHA-256”). Producers may use
BLAKE3 if they prefer; the consumer treats `asset_id` opaquely.

### Examples

```pycon
>>> from pathlib import Path
>>> from lacing.artifact import Artifact, hash_file
>>> # Create one from a path:
>>> import tempfile
>>> with tempfile.NamedTemporaryFile("wb", suffix=".bin", delete=False) as f:
...     _ = f.write(b"hello world")
...     p = Path(f.name)
>>> a = Artifact.from_path(p, kind="text", was_generated_by="test:doctest",
...                        was_attributed_to="user:thor")
>>> a.kind
'text'
>>> a.bytes_size
11
>>> len(a.asset_id) == 64  # SHA-256 hex
True
>>> a.path == p
True
```

An artifact that was *acquired* rather than made carries a [`Rights`](#lacing.artifact.Rights)
record (`None` means “we made this”, not “unknown”):

```pycon
>>> from lacing.artifact import Rights
>>> a = Artifact.from_bytes(b"png", kind="image", was_generated_by="fetch:openverse",
...     was_attributed_to="user:thor",
...     rights=Rights(provider="openverse", license="by-sa", author="Ada"))
>>> a.rights.license
'by-sa'
>>> Artifact.from_bytes(b"x", kind="text", was_generated_by="t",
...     was_attributed_to="u").rights is None
True
```

Round-trip through JSON:

```pycon
>>> import json
>>> data = a.model_dump_json()
>>> b = Artifact.model_validate_json(data)
>>> b.asset_id == a.asset_id
True
```

### Module Attributes

| [`ArtifactKind`](#lacing.artifact.ArtifactKind)   | Coarse mime-class.   |
|-----------------------------------------------------------------|----------------------|

### Functions

| [`hash_bytes`](#lacing.artifact.hash_bytes)(data)                  | Return the canonical `asset_id` (SHA-256 hex) for `data`.             |
|------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`hash_file`](#lacing.artifact.hash_file)(path, \*[, chunk_size]) | Return the canonical `asset_id` (SHA-256 hex) for the file at `path`. |

### Classes

| [`Artifact`](#lacing.artifact.Artifact)(\*\*data)   | A content-addressed generated file with provenance.              |
|-----------------------------------------------------------------------|------------------------------------------------------------------|
| [`Rights`](#lacing.artifact.Rights)(\*\*data)     | Who owns the bytes of an *acquired* artifact, and on what terms. |

### *class* lacing.artifact.Artifact(\*\*data)

Bases: `BaseModel`

A content-addressed generated file with provenance.

`asset_id` is the SHA-256 hex digest of the artifact’s bytes. Two
artifacts with the same `asset_id` are byte-identical regardless of
where they live — so caches keyed on `asset_id` are safe across
machines and re-runs.

`provenance` reuses [`lacing.Provenance`](lacing.md#lacing.Provenance) so the lineage chain
(`was_derived_from`, `was_generated_by`) is the same for artifacts
and annotations. An annotation referencing an artifact does so via
`MediaRef(asset_id=artifact.asset_id, …)`.

#### *classmethod* from_bytes(data, , kind, was_generated_by, was_attributed_to, path=None, url=None, was_derived_from=(), activity='create', generated_at_time=None, duration_s=None, mime=None, cost_usd=None, producer_call_id=None, rights=None)

Create an Artifact from in-memory bytes.

* **Return type:**
  [`Artifact`](#lacing.artifact.Artifact)

#### *classmethod* from_path(path, , kind, was_generated_by, was_attributed_to, was_derived_from=(), activity='create', generated_at_time=None, duration_s=None, mime=None, cost_usd=None, producer_call_id=None, rights=None)

Create an Artifact from a local file. Hashes the file’s bytes.

* **Return type:**
  [`Artifact`](#lacing.artifact.Artifact)

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

#### to_media_ref(interval)

Return a [`lacing.MediaRef`](lacing.md#lacing.MediaRef) pointing at this artifact.

Use this to attach an annotation to a region of the artifact:
`MediaRef(asset_id=artifact.asset_id, interval=…)`.

* **Return type:**
  MediaRef

### lacing.artifact.ArtifactKind

Coarse mime-class. Producers should pick the closest match; consumers
should switch on this *before* falling back to `mime`/`path.suffix`.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘image’, ‘video’, ‘audio’, ‘json’, ‘text’, ‘binary’]

### *class* lacing.artifact.Rights(\*\*data)

Bases: `BaseModel`

Who owns the bytes of an *acquired* artifact, and on what terms.

The fields a Creative-Commons-family licence needs to discharge its
attribution duty (title, author, source, licence: “TASL”), named
literal-for-literal after the two records the federation already keeps —
`illustration.ImageResult` and `an.ir.assets.AssetSource` — so both map
onto this one without a rename table (`provider`, `id`, `license`,
`license_url`, `attribution`, `source_page_url`, `author`,
`author_url`, `cacheable`).

Semantics worth the trap they avoid:

- **\`\`Artifact.rights is None\`\` means “we made this”**, not “unknown”. An
  acquired artifact whose terms nobody recorded is a `Rights` with only
  `provider` set.
- **\`\`license is None\`\` means UNKNOWN, never unencumbered.** Free of
  obligations is stated, e.g. `license="cc0-1.0"`.
- **\`\`cacheable is None\`\` means not stated**; `False` forbids keeping the
  bytes, `True` permits it.
- `license` is an SPDX id (`"CC-BY-4.0"`) or a provider’s own code
  (`"by-sa"`); lacing records it verbatim and never classifies it
  (classification lives with the consumer, e.g. `an`’s licence classes).
- The record describes **this artifact’s own bytes**. A render that embeds
  a third-party image carries no `Rights` of its own; its obligations
  travel through `provenance.was_derived_from` and are rolled up by the
  consumer. `rights is None` on a derivative is *not* a clearance.

`provider` is required, so an empty `Rights()` cannot exist: an
artifact either has no record (we made it) or says where it came from.
Text fields are `None` or non-blank; a blank string is refused.

Caveat: an artifact catalog is keyed by `asset_id` (the content hash), so
two records for the *same bytes* are one row and the last write wins. A
rights-less record written after an acquired one with identical bytes
replaces it, rights included. Writers that re-record bytes they already
hold must carry the existing `rights` forward.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### lacing.artifact.hash_bytes(data)

Return the canonical `asset_id` (SHA-256 hex) for `data`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> hash_bytes(b"hello world")[:8]
'b94d27b9'
```

### lacing.artifact.hash_file(path, , chunk_size=1048576)

Return the canonical `asset_id` (SHA-256 hex) for the file at `path`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
