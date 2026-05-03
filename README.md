# lacing

A standoff, interval-keyed annotation system. Pythonic core: a
`MutableMapping[TimeInterval, list[Annotation]]` facade with rational time,
ELAN-style tier stereotypes, and Allen's interval algebra. Designed for
time-based media (audio, video, speech, music) but generalizes to any 1-D
interval domain.

> **Status:** Phase 0–1. Core data model, in-memory + SQLite stores,
> five round-trip adapters (Praat TextGrid, WebVTT, W3C Web Annotation,
> `.annot` SQLite, ELAN EAF), inter-annotator agreement metrics, and a
> `lacing` CLI (`convert`, `query`, `validate`, `list-formats`). Server
> and frontend are on the roadmap
> (see `misc/docs/Lacing Development Roadmap.md`).

## Install

```bash
pip install lacing                # core only
pip install 'lacing[textgrid]'    # + Praat TextGrid support (praatio)
pip install 'lacing[eaf]'         # + ELAN EAF support (pympi-ling)
pip install 'lacing[postgres]'    # + PostgresStore (psycopg + GiST + EXCLUDE)
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

## What's in the core

```
lacing/
├── time.py          RationalTime + TimeInterval — rational, half-open, never float
├── model.py         Annotation envelope + Reference union + Provenance (PROV-O subset)
├── tier.py          Tier + 5 ELAN tier stereotypes + constraint validator
├── allen.py         13 Allen relations + intersects + relate + composition
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
│   └── eaf.py             ELAN EAF (4 stereotypes verbatim)
├── cli.py           `lacing` CLI: convert, query, validate, list-formats
├── quality.py       Cohen's κ, Krippendorff's α, interval IoU, boundary IoU
├── schema.py        Body schema registry + JSON Schema export + migrations
└── bodies/          Built-in body schemas (word, named-entity, ...)
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
    Annotation, MediaRef, MemoryStore, Provenance,
    RationalTime, TimeInterval, Tier,
)

store = MemoryStore()
store.add_tier(Tier("words"))

store.add(Annotation(
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
))
```

### Query with Allen's relations

```python
from lacing.allen import AllenRelation
from lacing.time import RationalTime, TimeInterval

w = TimeInterval(RationalTime(0, 1000), RationalTime(500, 1000))

list(store.intersects(w))                       # any overlap
list(store.during(w))                           # strictly inside w
list(store.contains(w))                         # strictly contains w
list(store.relate(w, [AllenRelation.MEETS]))   # ends at w.start
```

### Persist annotations

```python
from lacing.store import SqliteStore

# Open or create a .annot file (SQLite under the hood)
store = SqliteStore("project.annot")
store.add_tier(...)
store.add(...)            # writes go straight to disk
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
migrated = migrate({"text": "ran"},
                   from_uri="annot://schema/word/v1",
                   to_uri="annot://schema/word/v2")
```

Export every registered schema to JSON Schema (the upstream for downstream
Zod codegen):

```python
from lacing.schema import export_json_schemas
export_json_schemas("./schema/")  # writes <name>/v<N>.json + index.json
```

Built-in body schemas live under `lacing/bodies/` (`word`, `named-entity`).
They register themselves on import.

### Inter-annotator agreement

```python
from lacing.quality import cohen_kappa, krippendorff_alpha, boundary_iou

# Two annotators on a categorical task
kappa = cohen_kappa(["A", "B", "A", "B"], ["A", "A", "A", "B"])

# Three annotators with missing data
alpha = krippendorff_alpha([
    ["A", "B", None, "C"],
    ["A", "B", "B",  "C"],
    ["A", "A", "B",  "C"],
])

# Compare two segmentations
score = boundary_iou(
    [a.interval for a in store_a.by_tier("speakers")],
    [a.interval for a in store_b.by_tier("speakers")],
)
```

## License

MIT.
