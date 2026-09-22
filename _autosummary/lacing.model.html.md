# lacing.model

Annotation envelope, references, and provenance.

One envelope, typed body. The `body: dict` is validated by the schema at
`body_schema_uri` (semver). No polymorphic class hierarchy. See BACK-DOC §2.1
and `.claude/skills/lacing-schema-codegen/SKILL.md`.

### Module Attributes

| [`Reference`](#lacing.model.Reference)            | Discriminated union on `kind`.                                                                                                                                                                   |
|-----------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`AssetId`](#lacing.model.AssetId)              | A content-addressed artifact identity — the SHA-256 of the artifact's bytes, as [`lacing.Artifact`](lacing.html.md#lacing.Artifact) enforces: **bare 64-hex only**. |
| [`ProvenanceRef`](#lacing.model.ProvenanceRef)        | an annotation `id` (UUID) or an artifact `asset_id` (64-hex SHA-256).                                                                                                                            |
| [`UNKNOWN_GENERATED_AT`](#lacing.model.UNKNOWN_GENERATED_AT) | The `generated_at_time` an annotation carries when its generation time is **unknown** — tick 0, at any rate.                                                                                     |

### Functions

| [`partition_provenance_refs`](#lacing.model.partition_provenance_refs)(refs)   | Split `was_derived_from` into `(annotation_ids, asset_ids)`.   |
|------------------------------------------------------------------------------------|----------------------------------------------------------------|

### Classes

| [`Annotation`](#lacing.model.Annotation)(\*\*data)    | The single annotation envelope.                                                |
|--------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`AnnotationRef`](#lacing.model.AnnotationRef)(\*\*data) | Reference to another annotation (for discussion threads, review, derivations). |
| [`MediaRef`](#lacing.model.MediaRef)(\*\*data)      | Reference to a region of a content-addressed media asset.                      |
| [`NodeRef`](#lacing.model.NodeRef)(\*\*data)       | Reference to a node in a structured scene/document graph.                      |
| [`Provenance`](#lacing.model.Provenance)(\*\*data)    | W3C PROV-O subset, embedded inline on every annotation.                        |

### *class* lacing.model.Annotation(\*\*data)

Bases: `BaseModel`

The single annotation envelope. `body` is typed by `body_schema_uri`.

#### *property* interval *: [TimeInterval](lacing.time.html.md#lacing.time.TimeInterval) | [None](https://docs.python.org/3/builtins/constants.html#None)*

the reference’s interval, if any.

* **Type:**
  Convenience

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.model.AnnotationRef(\*\*data)

Bases: `BaseModel`

Reference to another annotation (for discussion threads, review, derivations).

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### lacing.model.AssetId

A content-addressed artifact identity — the SHA-256 of the artifact’s
bytes, as [`lacing.Artifact`](lacing.html.md#lacing.Artifact) enforces: **bare 64-hex only**.
`MediaRef.asset_id`-style prefixed identifiers (`blake3:…`,
`sha256:…`) are a different, free-form vocabulary and are NOT
provenance refs — copying one in here is a loud `ValidationError`, by
design. Format-disjoint from a UUID string (36 hyphenated chars), so the
[`ProvenanceRef`](#lacing.model.ProvenanceRef) union is unambiguous.

alias of `Annotated`[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), FieldInfo(annotation=NoneType, required=True, metadata=[MinLen(min_length=64), MaxLen(max_length=64), \_PydanticGeneralMetadata(pattern=’^[0-9a-f]{64}$’)])]

### *class* lacing.model.MediaRef(\*\*data)

Bases: `BaseModel`

Reference to a region of a content-addressed media asset.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.model.NodeRef(\*\*data)

Bases: `BaseModel`

Reference to a node in a structured scene/document graph.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.model.Provenance(\*\*data)

Bases: `BaseModel`

W3C PROV-O subset, embedded inline on every annotation.

#### *property* generated_at_is_known *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

`False` when `generated_at_time` is the [`UNKNOWN_GENERATED_AT`](#lacing.model.UNKNOWN_GENERATED_AT) sentinel.

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

### lacing.model.ProvenanceRef

an annotation `id`
(UUID) or an artifact `asset_id` (64-hex SHA-256). Widened from bare
`list[UUID]` by lacing#14 (defect D5) so artifact-to-artifact lineage —
the tier where the expensive things live — is representable at all.
Consumers that walk lineage discriminate with
[`partition_provenance_refs()`](#lacing.model.partition_provenance_refs). Derivation *roles* (lacing#17) will
arrive as a separate additive qualification field, PROV-O-style — this
list stays the simple edge walk.

* **Type:**
  One upstream reference in `was_derived_from`

alias of [`UUID`](https://docs.python.org/3/library/uuid.html#uuid.UUID) | `Annotated`[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), FieldInfo(annotation=NoneType, required=True, metadata=[MinLen(min_length=64), MaxLen(max_length=64), \_PydanticGeneralMetadata(pattern=’^[0-9a-f]{64}$’)])]

### lacing.model.Reference

Discriminated union on `kind`.

alias of `Annotated`[[`MediaRef`](#lacing.model.MediaRef) | [`NodeRef`](#lacing.model.NodeRef) | [`AnnotationRef`](#lacing.model.AnnotationRef), FieldInfo(annotation=NoneType, required=True, discriminator=’kind’)]

### lacing.model.UNKNOWN_GENERATED_AT *: [RationalTime](lacing.time.html.md#lacing.time.RationalTime)* *= RationalTime(0, 24000)*

The `generated_at_time` an annotation carries when its generation time is
**unknown** — tick 0, at any rate.

This is a sentinel, never a timestamp. `RationalTime` is wall-clock time
in the provenance role (`RationalTime.now()`), and tick 0 is *not* “the
epoch, 1970-01-01”: no annotation was generated then. It is what a writer
stamps when it has nothing better (the REST path did so until lacing#35),
and what every row written that way still carries, since lacing does no
backfill (lacing#44). `RationalTime(0, r) == RationalTime(0, s)` for any
rates, so comparing against this constant is rate-independent.

Consumers must read it as *unknown*, and unknown resolves the safe way:
an annotation whose own generation time — or whose upstream parent’s — is
unknown is **unverifiable**, hence stale, never “the oldest thing in the
project”. Test with [`Provenance.generated_at_is_known`](#lacing.model.Provenance.generated_at_is_known); never order
a tick-0 annotation against a real timestamp.

### lacing.model.partition_provenance_refs(refs)

Split `was_derived_from` into `(annotation_ids, asset_ids)`.

The one discriminator every lineage walker needs, provided centrally so
no consumer re-derives (or half-derives) the union rule.

`refs` must come from a **validated** [`Provenance`](#lacing.model.Provenance) — the split
is by runtime type (`UUID` vs `str`), so a raw wire list that never
passed validation would land every UUID *string* in the asset bucket.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`UUID`](https://docs.python.org/3/library/uuid.html#uuid.UUID)], [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]
