# lacing

A standoff, interval-keyed annotation system. Pythonic core: a
`MutableMapping[TimeInterval, list[Annotation]]` facade with rational time,
ELAN-style tier stereotypes, and Allen's interval algebra. Designed for
time-based media (audio, video, speech, music) but generalizes to any 1-D
interval domain.

> **Status:** Phase 0–2 complete. Core data model, in-memory + SQLite +
> Postgres stores, **eight round-trip adapters** (Praat TextGrid, WebVTT,
> W3C Web Annotation, `.annot` SQLite, ELAN EAF, JAMS, Label Studio JSON,
> OpenTimelineIO), body-schema registry + JSON Schema export + migrations,
> inter-annotator agreement metrics, a `lacing` CLI, a **FastAPI HTTP
> server** (REST CRUD + ETag + import/export + schemas + op-log +
> `/state-at` time-travel), an **MCP server** (10 tools, agents as
> first-class clients), a **processor registry** (`low_confidence_review`,
> `detect_density_change_points`) with optional **Arq** integration, and
> opt-in **OpenTelemetry** instrumentation. Frontend is on the roadmap
> (see `misc/docs/Lacing Development Roadmap.md`).

## Install

```bash
pip install lacing                # core only
pip install 'lacing[textgrid]'    # + Praat TextGrid support (praatio)
pip install 'lacing[eaf]'         # + ELAN EAF support (pympi-ling)
pip install 'lacing[jams]'        # + JAMS (MIR annotation) support
pip install 'lacing[postgres]'    # + PostgresStore (psycopg + GiST + EXCLUDE)
pip install 'lacing[server]'      # + FastAPI HTTP server
pip install 'lacing[mcp]'         # + MCP server (agents as first-class clients)
pip install 'lacing[arq]'         # + Arq background workers (Redis-backed)
pip install 'lacing[otio]'        # + OpenTimelineIO adapter
pip install 'lacing[otel]'        # + OpenTelemetry instrumentation
```

## 30-second tour

```python
from lacing.adapters import textgrid, webvtt, web_annotation  # registers each
from lacing.adapters import load, dump

# Load a Praat TextGrid → an in-memory store keyed by interval
store = load("speech.TextGrid", rate=1000)

# Query overlaps using Allen's relations
from lacing.time import RationalTime, TimeInterval

window = TimeInterval(RationalTime(500, 1000), RationalTime(1500, 1000))

for ann in store.intersects(window):
    print(ann.tier, ann.body["text"])

for ann in store.during(window):  # strictly inside the window
    ...

# Save out as WebVTT
dump(store, "speech.vtt", format="webvtt")

# Or as W3C Web Annotation JSON-LD
dump(store, "speech.jsonld", format="web_annotation")
```

## Track facades — opinionated bundles of tiers

Some tier shapes recur often enough to deserve a friendly builder.
`lacing.tracks.subtitle` is the first: a `(sections, lines, words)`
trio over one audio asset, with float-second times and the
`Annotation` / `MediaRef` / `Provenance` plumbing hidden:

```python
from lacing import MemoryStore
from lacing.tracks.subtitle import SubtitleBuilder, SubtitleTrack

store = MemoryStore()
with SubtitleBuilder(store, asset_id="song/audio.mp3") as b:
    b.section("intro", 0.0, 12.5)
    b.section("verse_1", 12.5, 35.0)
    b.line(
        "I came down to the river",
        12.5,
        16.2,
        section="verse_1",
        line_index=0,
        words=[
            ("I", 12.5, 12.7),
            ("came", 12.7, 13.0, 0.95),  # optional confidence
            ("down", 13.0, 13.3),
        ],
    )

track = SubtitleTrack(store, asset_id="song/audio.mp3")
track.lines_in(15.0, 17.0)  # lines overlapping the window
track.words_in(12.5, 13.5)  # words overlapping the window
track.sections_covering(20.0)  # sections containing this instant
```

The facade reuses `at_tier` / `by_tier` under the hood; anything you
can build with it could also be hand-built with the raw API. Body
schema URIs are conventional (`annot://schema/song-section/v1`,
`lyric-line/v1`, `word/v1`) — pass `register_subtitle_schemas()` once
if you want Pydantic body validation.

## What's in the core

```
lacing/
├── time.py          RationalTime + TimeInterval — rational, half-open, never float
├── model.py         Annotation envelope + Reference union + Provenance (PROV-O subset)
├── tier.py          Tier + 5 ELAN tier stereotypes + constraint validator
├── allen.py         13 Allen relations + intersects + relate + composition
├── digest.py        annotation_value_digest — content digest for freshness / early cutoff
├── store/
│   ├── base.py      IntervalAnnotationStore (MutableMapping facade)
│   ├── memory.py    MemoryStore over `intervaltree`
│   ├── sqlite.py    SqliteStore — persistent backend + .annot file format
│   └── postgres.py  PostgresStore — int8range + GiST + per-tier EXCLUDE
├── adapters/
│   ├── textgrid.py        Praat .TextGrid (interval + point tiers)
│   ├── webvtt.py          .vtt subtitles/captions
│   ├── web_annotation.py  W3C Web Annotation Data Model (JSON-LD)
│   ├── annot.py           .annot SQLite portable file format (lossless)
│   ├── eaf.py             ELAN EAF (4 stereotypes verbatim)
│   └── jams.py            JAMS (Music Information Retrieval) — namespaces → tiers
├── cli.py           `lacing` CLI: convert, query, validate, list-formats
├── quality.py       Cohen's κ, Krippendorff's α, interval IoU, boundary IoU
├── schema.py        Body schema registry + JSON Schema export + migrations
├── bodies/          Built-in body schemas (word, named-entity, ...)
└── server/          FastAPI HTTP server (Phase 2)
    ├── app.py           create_app(); ready-to-run `app` for uvicorn
    ├── deps.py          dependency-injection (store factory)
    ├── etag.py          ETag computation + If-Match parsing
    └── routers/         REST endpoints: annotations, tiers, adapters, meta
```

## Design rules in one breath

1. **Time is rational** — `RationalTime(value: int, rate: int)`. Wire format `{v, r}`. Never floats.
2. **Standoff** — annotations reference media by `(asset_id, interval)`; source is immutable.
3. **One envelope, typed body** — `Annotation.body: dict` validated by `body_schema_uri` (semver).
4. **Allen's algebra is the public predicate API** — never write ad-hoc overlap checks.
5. **ELAN tier stereotypes verbatim** — `NONE`, `TIME_SUBDIVISION`, `INCLUDED_IN`, `SYMBOLIC_SUBDIVISION`, `SYMBOLIC_ASSOCIATION`.
6. **PROV-O provenance inline on every annotation** — `was_generated_by`, `was_attributed_to`, `was_derived_from`, `generated_at_time`.
7. **MIT/BSD/Apache licenses only.**

The full reasoning lives in [`misc/docs/`](misc/docs/) — four design docs
covering annotation systems generally, backend architecture, frontend UI,
and an OSS deep-dive of what to build on. The synthesized plan is in
[`misc/docs/Lacing Development Roadmap.md`](misc/docs/Lacing%20Development%20Roadmap.md).

## Concrete recipes

### Build annotations programmatically

```python
from uuid import uuid4
from lacing import (
    Annotation,
    MediaRef,
    MemoryStore,
    Provenance,
    RationalTime,
    TimeInterval,
    Tier,
)

store = MemoryStore()
store.add_tier(Tier("words"))

store.add(
    Annotation(
        id=uuid4(),
        tier="words",
        reference=MediaRef(
            asset_id="blake3:abc123",
            interval=TimeInterval.from_seconds("0.0", "0.5", rate=1000),
        ),
        body={"text": "hello"},
        body_schema_uri="annot://schema/word/v1",
        provenance=Provenance(
            was_generated_by="user:thor",
            was_attributed_to="thor",
            generated_at_time=RationalTime.zero(1000),
        ),
    )
)
```

### Query with Allen's relations

```python
from lacing.allen import AllenRelation
from lacing.time import RationalTime, TimeInterval

w = TimeInterval(RationalTime(0, 1000), RationalTime(500, 1000))

list(store.intersects(w))  # any overlap
list(store.during(w))  # strictly inside w
list(store.contains(w))  # strictly contains w
list(store.relate(w, [AllenRelation.MEETS]))  # ends at w.start
```

### Persist annotations

```python
from lacing.store import SqliteStore

# Open or create a .annot file (SQLite under the hood)
store = SqliteStore("project.annot")
store.add_tier(...)
store.add(...)  # writes go straight to disk
store.set_meta("project", "demo")

# Same MutableMapping + Allen-relation interface as MemoryStore
for ann in store.intersects(window):
    ...
store.close()
```

The `.annot` file is the recommended portable handoff format — single-file
SQLite, Git-trackable, lossless round-trip with `MemoryStore`.

For multi-user / production scale, the same facade is available over
PostgreSQL:

```python
from lacing.store import PostgresStore
from lacing.tier import Tier

store = PostgresStore("postgresql://localhost/myproject", rate=1000)

# Per-tier non-overlap is enforced declaratively by the database — try to
# add an overlapping annotation in this tier and Postgres rejects the insert.
store.add_tier(Tier("speakers"), enforce_no_overlap=True)
```

The Postgres backend uses `int8range` + GiST (sub-millisecond overlap
queries at million-row scale) and exposes the same Allen-relation
methods. Times are normalized to a project-wide rate stored in `meta`.

### CLI

After `pip install -e .` the `lacing` command is on your PATH:

```bash
lacing list-formats                                          # show registered adapters
lacing convert speech.TextGrid speech.annot                  # convert between formats
lacing query speech.annot --start 1.0 --end 5.0 --rate 1000  # JSON-lines
lacing validate speech.annot                                 # parse + summary
```

### Body schemas, validation, migrations

Every annotation has a `body: dict` validated against the schema named by
its `body_schema_uri` (e.g., `annot://schema/named-entity/v2`). Register
your own with a Pydantic v2 model:

```python
from pydantic import BaseModel, Field
from lacing.schema import register_body_schema, register_migration, validate, migrate


class WordBodyV1(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}
    text: str = Field(...)
    speaker: str | None = None


register_body_schema("annot://schema/word/v1", WordBodyV1)

# Validate at runtime:
validate({"text": "hello"}, "annot://schema/word/v1")


# Register a forward migration v1 -> v2:
@register_migration(schema_name="word", from_version=1, to_version=2)
def _v1_to_v2(body: dict) -> dict:
    return {**body, "lemma": None}


# Migrate stored data:
migrated = migrate(
    {"text": "ran"}, from_uri="annot://schema/word/v1", to_uri="annot://schema/word/v2"
)
```

Export every registered schema to JSON Schema (the upstream for downstream
Zod codegen):

```python
from lacing.schema import export_json_schemas

export_json_schemas("./schema/")  # writes <name>/v<N>.json + index.json
```

Built-in body schemas live under `lacing/bodies/` (`word`, `named-entity`).
They register themselves on import.

### Run the HTTP server

```bash
pip install 'lacing[server]'
uvicorn lacing.server:app --reload
```

By default the server starts with an in-memory `SqliteStore`. Wire your
own backend (e.g., a `PostgresStore` or an `.annot` file) via FastAPI's
dependency-override:

```python
from lacing.server import create_app
from lacing.server.deps import get_store
from lacing.store import SqliteStore

store = SqliteStore("project.annot", check_same_thread=False)
app = create_app()
app.dependency_overrides[get_store] = lambda: store
```

The REST surface (Phase 2.0):

```
GET    /health
GET    /tiers                              list
POST   /tiers                              create or update
GET    /tiers/{name}                       get one
POST   /annotations                        create (returns ETag)
GET    /annotations                        list with optional ?tier&start&end&relation&rate
GET    /annotations/{id}                   get one (returns ETag)
PATCH  /annotations/{id}                   partial update; If-Match required
DELETE /annotations/{id}
POST   /import?format=webvtt               upload a file in any registered format
GET    /export?format=eaf                  dump store as a file
GET    /formats                            list registered adapters
GET    /schemas                            list registered body_schema_uris
GET    /schemas/{uri}                      JSON Schema for a URI
GET    /meta, PUT /meta/{key}              key/value metadata
GET    /oplog                              list mutations (filterable by clock)
GET    /oplog/latest-clock                 current Lamport clock value
GET    /state-at?clock=N                   replay log to clock N → snapshot
```

Every mutation gets a Lamport clock returned in the `X-Lacing-Clock`
response header. The op-log + `/state-at` endpoint give you full
time-travel debug — pick any past clock value and reconstruct exactly
what the system saw.

### MCP server — agents as first-class clients

```python
from lacing.oplog import InMemoryOpLog
from lacing.server.mcp import build_mcp_server
from lacing.store import SqliteStore

store = SqliteStore("project.annot", check_same_thread=False)
oplog = InMemoryOpLog()
server = build_mcp_server(store, oplog)
server.run()  # stdio transport by default
```

Tools registered (all take seconds — no need to construct rational-time
wire dicts): `add_annotation`, `query_annotations`, `get_annotation`,
`delete_annotation`, `accept_ai_suggestion`, `add_tier`, `list_tiers`,
`list_formats`, `latest_clock`, `state_at`. The MCP server shares the
same `store` + `oplog` as the FastAPI app, so a human edit via REST and
an agent edit via MCP land in the same op-log with the same Lamport
clock.

### Freshness — "did the answer actually change?"

lacing has **three** digests answering three different questions. Picking the
wrong one is a silent correctness bug, so they are named apart:

| Digest | Over | Question |
|---|---|---|
| `hash_bytes` / `hash_file` | an artifact's **bytes** | *are these two files the same file?* (`Artifact.asset_id`) |
| `lacing.server.etag.annotation_etag` | the **whole** annotation | *has this record been touched since I read it?* (`If-Match` / 412) |
| `annotation_value_digest` | an annotation's **value** | *did the answer actually change?* (freshness / early cutoff) |

A regeneration mints a fresh `id` and a fresh `provenance.generated_at_time`,
so `annotation_etag` changes even when the content is byte-identical. The value
digest excludes both — which is what lets a downstream freshness check key on
*upstream output values* rather than *upstream keys*, and stop propagating
invalidation when nothing actually changed.

```python
from lacing import annotation_value_digest, annotation_body_digest

# Same content, regenerated: same value digest, different id + timestamp.
assert annotation_value_digest(original) == annotation_value_digest(regenerated)

# Included in the value: body, body_schema_uri, tier, reference, confidence.
# Excluded: id, provenance.

# The narrow sibling — {body, body_schema_uri} only. It drops the ENTIRE
# reference (which asset, not just when) plus tier and confidence, so the same
# body over two DIFFERENT assets digests alike. Use it only when the consumer
# depends on nothing but what the annotation says.
assert annotation_body_digest(over_interview) == annotation_body_digest(over_broadcast)
```

A `body` must contain only JSON types. A non-`str` mapping key raises
`NonStringBodyKeyError` rather than digesting: JSON object keys are strings, so
`{1: "a", "1": "b"}` would collapse to `{"1": "b"}` and silently lose an entry
— two different annotations digesting alike. Within that contract the digest
never returns a wrong cache *hit*; it can return a spurious miss, which only
costs a recompute.

`lacing/digest.py` justifies each inclusion/exclusion in its docstring; read it
before changing the boundary, because changing it invalidates every consumer's
cache at once.

### Inter-annotator agreement

```python
from lacing.quality import cohen_kappa, krippendorff_alpha, boundary_iou

# Two annotators on a categorical task
kappa = cohen_kappa(["A", "B", "A", "B"], ["A", "A", "A", "B"])

# Three annotators with missing data
alpha = krippendorff_alpha(
    [
        ["A", "B", None, "C"],
        ["A", "B", "B", "C"],
        ["A", "A", "B", "C"],
    ]
)

# Compare two segmentations
score = boundary_iou(
    [a.interval for a in store_a.by_tier("speakers")],
    [a.interval for a in store_b.by_tier("speakers")],
)
```

## License

MIT.
