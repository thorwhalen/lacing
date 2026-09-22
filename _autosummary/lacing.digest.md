# lacing.digest

Content digests over an annotation’s *value* — the freshness primitive.

lacing has **three** digests and they answer **three different questions**.
Collapsing any two of them is a silent correctness bug, so the boundary is
spelled out here and cross-referenced from the other two:

- [`lacing.hash_bytes()`](lacing.md#lacing.hash_bytes) / [`lacing.hash_file()`](lacing.md#lacing.hash_file) — SHA-256 over an
  **artifact’s bytes**. Answers  *“are these two files the same file?”*. This
  is the `Artifact.asset_id` contract ([`lacing.artifact`](lacing.artifact.md#module-lacing.artifact)).
- `lacing.server.etag.annotation_etag()` — BLAKE2b-128 over the \*\*whole
  annotation\*\*, `id` and `provenance` included. Answers  *“has this record
  been touched since I read it?”*. This is the `If-Match` / HTTP 412
  optimistic-concurrency primitive, and it is *deliberately* unstable across
  regenerations.
- [`annotation_value_digest()`](#lacing.digest.annotation_value_digest) (this module) — SHA-256 over an annotation’s
  **value**, `id` and `provenance` excluded. Answers  *“did the answer
  actually change?”*. This is the freshness / early-cutoff primitive.

A regeneration that produces byte-identical content mints a fresh `uuid4`
`id` and a fresh `provenance.generated_at_time`, so `annotation_etag`
changes while `annotation_value_digest` does not. That difference is the
entire point: it lets a downstream freshness check key on \*upstream output
values\* rather than on *upstream keys*, and stop propagating invalidation
when nothing actually changed.

## Why this lives in core and not under `lacing/server/`

`annotation_etag` sits at `lacing/server/etag.py`. Its own imports are
cheap, but importing any submodule of `lacing.server` executes
`lacing/server/__init__.py`, which imports the FastAPI app. The value
digest is consumed by the *execution* tier (`nw`, `falaw`), which must
not drag a web framework in. This module therefore has \*\*no runtime imports
beyond the standard library\*\* — the [`Annotation`](lacing.model.md#lacing.model.Annotation) import
is type-checking only.

## The inclusion boundary — and why each call was made

Getting this boundary wrong is a silent wrong-cache-**hit**, not a miss, so
each field is justified rather than assumed.

**Included** ([`VALUE_FIELDS`](#lacing.digest.VALUE_FIELDS)):

- `body` — it *is* the annotation’s value. Trivially included.
- `body_schema_uri` — the same `dict` means different things under
  different schemas, and a schema-version bump is a semantic change even when
  the payload bytes are unchanged. Excluding it would let a `.../v1` body
  satisfy a `.../v2` consumer’s cache lookup.
- `tier` — the tier is part of what the annotation asserts (which layer of
  the analysis this claim belongs to), and lacing’s tier stereotypes impose
  structural constraints. Two identical bodies on different tiers are
  different claims.
- `reference` — what the annotation is *about*: the asset and the interval.
  Re-timing an annotation changes its value. This is the one genuinely
  contested call (see below); it is included here and excluded from
  [`annotation_body_digest()`](#lacing.digest.annotation_body_digest), so the consumer chooses rather than guesses.
- `confidence` — a soft label whose confidence moved is a changed assertion.
  Downstream thresholding consumes it directly.

**Excluded**:

- `id` — a fresh `uuid4` on every regeneration. Including it makes the
  digest change unconditionally, which is exactly the `annotation_etag`
  behaviour this function exists to avoid.
- `provenance` — `generated_at_time` changes on every run, and
  `was_generated_by` / `was_derived_from` describe *how* the value was
  reached, not *what* it is. Two byte-identical answers produced by different
  activities are the same answer. (If a consumer needs to invalidate on a
  changed producer, that belongs in its **cache key** — which is keyed on
  inputs — not in the **value digest**, which addresses the output.)

Rule of thumb, stated once: \*key the cache on inputs; address the value by
content; record both in the trace.\* A system with only the first cannot cut
off early.

## `reference`: two functions, not a boolean

Whether `reference` belongs in a value digest is genuinely
consumer-dependent. A [`MediaRef`](lacing.model.md#lacing.model.MediaRef) carries an
`interval`, so re-timing busts every downstream digest — **correct** when
downstream consumes the timing (an animatic, a cut list), **wasteful** when
it consumes only the body (a caption translation). Rather than a boolean flag
or a wrong guess that needs migrating later, this module ships both:

- [`annotation_value_digest()`](#lacing.digest.annotation_value_digest) — the full value, `reference` included.
  **The default.** Use it unless you can state why the rest is irrelevant.
- [`annotation_body_digest()`](#lacing.digest.annotation_body_digest) — `{body, body_schema_uri}` only.

\*\*Be precise about what the narrow one drops, because “re-timing” undersells
it.\*\* `annotation_body_digest` drops the *entire* `reference` — the asset
identity as well as the interval — plus `tier` and `confidence`. Two
annotations carrying the same body over **different assets** digest alike
under it. Reach for it only when the consumer depends on nothing but what the
annotation *says*.

They are domain-separated (see [`VALUE_DIGEST_SCHEME`](#lacing.digest.VALUE_DIGEST_SCHEME)), so the two can
never collide even on an annotation whose payloads coincide.

## Stability guarantees, and their limits

The digest is stable **across processes**, **across dict insertion order**
(`sort_keys=True` canonicalises recursively) and \*\*across a store
round-trip\*\* (memory → `.annot` → memory).

## The safety claim, stated precisely

\*\*For a body that honours the `body` contract — i.e. contains only JSON
types, which is what validating against JSON Schema means — this digest never
returns a wrong cache *hit*.\*\* Two annotations with different values never
digest alike. It can return a spurious *miss*; that only costs a recompute.

That claim is bounded by the contract, and it is worth knowing exactly where
the boundary is, because an unbounded version of it would be false:

1. \*\*Non-`str` mapping keys raise\*\* [`NonStringBodyKeyError`](#lacing.digest.NonStringBodyKeyError).
   `model_dump(mode="json")` coerces keys to strings, so a body like
   `{1: "a", "1": "b"}` collapses to `{"1": "b"}` — an entire entry is
   annihilated, and two bodies differing only in the annihilated entry would
   digest **alike**. That is a wrong hit, so it is refused rather than
   documented. Such a body is already broken data: it does not survive a
   round-trip through any lacing store either (JSON object keys are strings).
2. **Python container types that JSON cannot distinguish digest alike** —
   `(1, 2)` and `[1, 2]` both serialise to `[1, 2]`. This is *not* a
   wrong hit within the contract: as JSON they are the same value, and a
   contract-honouring body cannot contain a tuple. A `set` additionally
   serialises in an order not stable across processes (a spurious miss), and
   a type pydantic cannot serialise at all raises
   `PydanticSerializationError` rather than digesting a `repr` that embeds
   a memory address.
3. **Equal-but-differently-serialised rationals digest differently.**
   [`RationalTime`](lacing.time.md#lacing.time.RationalTime) serialises as `{"v": …, "r": …}`, so
   > `RationalTime(1, 24)` and `RationalTime(2, 48)` compare **equal** but
   > digest differently — a rate change moves the digest even when the instant
   > is unchanged. This is a spurious *miss*. (`annotation_etag` has the same
   > property.)

Changing [`VALUE_FIELDS`](#lacing.digest.VALUE_FIELDS) or the canonicalisation is a \*\*breaking cache
invalidation event\*\* for every consumer: every digest changes at once. Bump
the scheme string when you do it, so the change is legible in a trace.

### Module Attributes

| [`VALUE_FIELDS`](#lacing.digest.VALUE_FIELDS)        | Annotation fields that constitute its *value*.                                                               |
|----------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| [`BODY_FIELDS`](#lacing.digest.BODY_FIELDS)         | The narrower payload for [`annotation_body_digest()`](#lacing.digest.annotation_body_digest).          |
| [`VALUE_DIGEST_SCHEME`](#lacing.digest.VALUE_DIGEST_SCHEME) | Domain-separation tag mixed into [`annotation_value_digest()`](#lacing.digest.annotation_value_digest). |
| [`BODY_DIGEST_SCHEME`](#lacing.digest.BODY_DIGEST_SCHEME)  | Domain-separation tag mixed into [`annotation_body_digest()`](#lacing.digest.annotation_body_digest).  |

### Functions

| [`annotation_value_digest`](#lacing.digest.annotation_value_digest)(annotation)   | Return the SHA-256 hex digest of `annotation`'s value.           |
|----------------------------------------------------------------------------------------|------------------------------------------------------------------|
| [`annotation_body_digest`](#lacing.digest.annotation_body_digest)(annotation)    | Return the SHA-256 hex digest of `{body, body_schema_uri}` only. |

### Exceptions

| [`NonStringBodyKeyError`](#lacing.digest.NonStringBodyKeyError)   | An annotation `body` contains a mapping key that is not a `str`.   |
|--------------------------------------------------------------------------|--------------------------------------------------------------------|

### lacing.digest.BODY_DIGEST_SCHEME *= 'lacing/annotation-body-digest/v1'*

Domain-separation tag mixed into [`annotation_body_digest()`](#lacing.digest.annotation_body_digest).

### lacing.digest.BODY_FIELDS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('body', 'body_schema_uri')*

The narrower payload for [`annotation_body_digest()`](#lacing.digest.annotation_body_digest).

Note what this drops, which is more than timing: the **entire** `reference`
(*which asset* / *which node* / *which annotation*, not just *when*), plus
`tier` and `confidence`. Two annotations over different assets digest
alike here.

### *exception* lacing.digest.NonStringBodyKeyError

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

### lacing.digest.VALUE_DIGEST_SCHEME *= 'lacing/annotation-value-digest/v1'*

Domain-separation tag mixed into [`annotation_value_digest()`](#lacing.digest.annotation_value_digest).

### lacing.digest.VALUE_FIELDS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('body', 'body_schema_uri', 'confidence', 'reference', 'tier')*

Annotation fields that constitute its *value*. See the module docstring for
why each is in, and why `id` and `provenance` are out.

### lacing.digest.annotation_body_digest(annotation)

Return the SHA-256 hex digest of `{body, body_schema_uri}` only.

The narrow sibling of [`annotation_value_digest()`](#lacing.digest.annotation_value_digest). It drops the
**entire** `reference` — *which asset* / *which node* / \*which
annotation\*, not merely *when* — plus `tier` and `confidence`. So the
same caption over two **different assets** digests identically here, as
does the same body asserted on two different tiers or at two different
confidences.

That is a correctness bug in any consumer that reads any of those. Reach
for it only when the consumer demonstrably depends on nothing but what the
annotation *says*; prefer [`annotation_value_digest()`](#lacing.digest.annotation_value_digest) otherwise.

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

### lacing.digest.annotation_value_digest(annotation)

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
