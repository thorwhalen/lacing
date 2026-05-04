---
name: lacing-architecture
description: Use when starting any non-trivial work on the lacing package — adding modules, designing APIs, choosing dependencies, planning a new feature, or making architectural decisions. Triggers on tasks like "implement X in lacing", "design the Y component", "add support for Z format", "where should this code go", or any edit under lacing/, lacing-server/, or lacing-ui/. Loads the ten non-negotiables, the package decomposition, and pointers to the design docs.
---

# Lacing Architecture Primer

`lacing` is a **standoff, interval-keyed annotation system** with a Python
backend and a TypeScript/React frontend sharing one schema-versioned model.

## Always read first

1. **[misc/docs/Lacing Development Roadmap.md](../../../misc/docs/Lacing%20Development%20Roadmap.md)** — phased plan, cross-referenced to design docs.
2. The four design docs in [misc/docs/](../../../misc/docs/):
   - **ANN-DOC** — `Annotation systems - formats, algorithms, architectures, and tooling.md`
   - **BACK-DOC** — `Backend Architecture for Time-Interval Annotation Systems.md`
   - **FRONT-DOC** — `Frontend UI for Multitrack Time-Interval Annotation Editors.md`
   - **OSS-DOC** — `Open-Source Codebase Deep-Dive ...md`

If the roadmap and a design doc disagree, **the design doc wins** — fix the roadmap.

## The ten non-negotiables

| # | Rule | Source |
|---|------|--------|
| 1 | **Time is `RationalTime(value: int, rate: int)`.** Never floats anywhere — wire, storage, UI. Wire as `{v, r}`; Python `fractions.Fraction`; TS `bigint` pair. | OSS-DOC OTIO; BACK-DOC §2.1 |
| 2 | **Standoff annotations only.** Source media immutable; annotations reference by `(asset_id, interval)`. | ANN-DOC §C |
| 3 | **One `Annotation` envelope, typed body.** Single shape, `body: dict` validated by `body_schema_uri` (semver). No polymorphic class hierarchy. | BACK-DOC §2.1 |
| 4 | **Indexes:** `intervaltree` in memory; PostgreSQL `tstzrange` + GiST when persistent; SQLite + R*Tree for `.annot` files. | ANN-DOC §C; BACK-DOC §3.1, §4.2 |
| 5 | **Public API is a `MutableMapping[TimeInterval, list[Annotation]]` facade** with Allen-relation methods (`intersects`, `during`, `meets`, …). Implemented as a `Protocol` (Python 3.12 forbids `Protocol` inheriting from a non-Protocol ABC); concrete backends like `MemoryStore` implement the full mapping interface structurally. | ANN-DOC §C; BACK-DOC §4.1 |
| 6 | **ELAN tier stereotypes verbatim:** `NONE`, `TIME_SUBDIVISION`, `INCLUDED_IN`, `SYMBOLIC_SUBDIVISION`, `SYMBOLIC_ASSOCIATION`. | ANN-DOC §C; OSS-DOC tier-2.4 |
| 7 | **Adapter pattern for I/O.** Core never imports a format module. Every format is a registered plugin. | ANN-DOC §C ("non-negotiable") |
| 8 | **PROV-O provenance inline on every annotation.** `was_generated_by`, `was_derived_from`, `was_attributed_to`, `generated_at_time`. AI annotations carry `agent:<model>@<hash>`. | ANN-DOC §C; BACK-DOC §4.5 |
| 9 | **Pydantic v2 → JSON Schema → Zod codegen.** One SoT, two languages. Use `datamodel-code-generator` + `json-schema-to-zod`. | BACK-DOC §6 |
| 10 | **License hygiene: MIT/BSD/Apache only.** No LGPL, GPL, AGPL, BSL. Banned: `portion`, `praat-parselmouth`, `aeneas`, Peaks.js, Etro, `@theatre/studio`, Remotion. | ANN-DOC §E; FRONT-DOC §1.8; OSS-DOC tier-3 |

## Package layout

`lacing` (this repo) is the **core lib only** — no server, no UI, no infra.
Server and UI live in sibling repos so the data model can be adopted alone.

```
lacing/                    ← THIS REPO: core library
├── lacing/
│   ├── time.py           RationalTime, TimeInterval
│   ├── model.py          Annotation, Reference, Provenance
│   ├── tier.py           Tier + 5 ELAN stereotypes
│   ├── allen.py          13 Allen relations + composition
│   ├── store/
│   │   ├── base.py       IntervalAnnotationStore facade
│   │   ├── memory.py     intervaltree-backed (Phase 0, done)
│   │   ├── sqlite.py     .annot file format + persistent backend (Phase 1, done)
│   │   └── postgres.py   int8range + GiST + per-tier EXCLUDE (Phase 1, done)
│   ├── adapters/         plugin-registered I/O
│   │   ├── textgrid.py        Praat (Phase 0, done)
│   │   ├── webvtt.py          captions (Phase 0, done)
│   │   ├── web_annotation.py  W3C JSON-LD (Phase 0, done)
│   │   ├── annot.py           .annot SQLite (Phase 1, done)
│   │   ├── eaf.py             ELAN EAF (Phase 1, done)
│   │   └── jams.py            JAMS / MIR (Phase 1, done)
│   ├── cli.py            argh-based CLI (Phase 1, done)
│   ├── quality.py        IAA: kappa, Krippendorff α, IoU, DER (Phase 0, done)
│   ├── schema.py         body_schema registry + JSON Schema export + migrations (Phase 1, done)
│   ├── bodies/           built-in body schemas (word, named-entity)
│   └── server/           FastAPI HTTP server (Phase 2, partial — REST CRUD + ETag + import/export)
└── misc/docs/            design docs + roadmap

lacing-server/  ← sibling repo (FastAPI + Arq + MCP + Yjs bridge)
lacing-ui/      ← sibling repo (React + zustand + wavesurfer + dnd-timeline)
```

## Phase awareness

When asked to implement something, identify which phase from the roadmap:

- **Phase 0** — Core: time, model, store, Allen relations, three adapters (TextGrid, WebVTT, W3C), quality metrics. **Done.**
- **Phase 1** — Persistence (SQLite/Postgres) + more adapters + CLI. **Mostly done:** `SqliteStore` + `.annot` file format adapter, ELAN EAF adapter, JAMS adapter (MIR), `PostgresStore` with `int8range`/GiST/per-tier EXCLUDE, `schema.py` (body-schema registry + JSON Schema export + migrations) with seed bodies under `lacing/bodies/`, and `lacing` CLI (`convert`, `query`, `validate`, `list-formats`) are in. **Remaining:** more adapters (Label Studio JSON, OTIO, CoNLL, brat, SubRip, TTML, CSV).
- **Phase 2** — FastAPI server + Arq workers + MCP + OpenTelemetry. **Partially done:** REST CRUD + ETag-based optimistic concurrency + import/export + schema introspection + op-log + `/state-at` time-travel + **MCP server (10 tools — agents as first-class clients)** + **processor registry (`lacing/processors.py`) with built-in `low_confidence_review` and `detect_density_change_points`, plus optional Arq integration (`lacing/worker.py`)** are in. **Remaining:** OpenTelemetry instrumentation hooks.
- **Phase 3** — Frontend MVP (waveform + dialogue tier + viseme tier + monitor + inspector).
- **Phase 4** — Yjs awareness, then full collab; WebCodecs; tier view.
- **Phase 5** — Differentiators (full Allen API, soft labels, generator timing, MCP-native).

If a request leapfrogs phases (e.g. "let's add Yjs collab" while Phase 1 isn't done), surface that and confirm before proceeding.

## Module sizing rules

- Helper used by ONE function → inner function.
- Helper within SAME module → `_` prefix.
- Helper used across modules → no prefix.
- Prefer functional style; OOP only for facades/orchestrators.
- Keyword-only after the 3rd argument; from the 2nd if it improves readability.
- No magic numbers — externalize as kwargs with smart defaults.

## When in doubt

- If a decision touches **time or intervals**, also load `lacing-time-and-intervals`.
- If you're **adding/modifying a format adapter**, load `lacing-adapter-authoring`.
- If you're **changing the data model or schemas**, load `lacing-schema-codegen`.
- If you're choosing a **dependency**, run the license through the rule-10 banlist before adding.
- If you're tempted to add a custom interval CRDT — don't. BACK-DOC §4.4 explicitly says compose Yjs primitives, custom code count = zero.
