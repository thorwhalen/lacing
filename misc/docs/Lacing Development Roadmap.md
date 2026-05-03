# Lacing Development Roadmap

> Working plan for what the `lacing` package should develop.
> Synthesized from the four design docs in this folder; each section
> cross-references the source doc(s) so agents can drill in for detail.

## Companion design docs in this folder

The following four docs are the authoritative source of *why* behind every
decision below. Read the relevant one before making non-trivial design changes.

- **[Annotation systems — formats, algorithms, architectures, and tooling](./Annotation%20systems%20-%20formats%2C%20algorithms%2C%20architectures%2C%20and%20tooling.md)**
  ("ANN-DOC") — cross-domain survey: text, audio, video, image, animation;
  W3C Web Annotation, UIMA CAS, Annotation Graphs, ELAN tier stereotypes,
  Allen's interval algebra, interval-tree algorithms, license analysis of
  every candidate Python/JS library.
- **[Backend Architecture for Time-Interval Annotation Systems](./Backend%20Architecture%20for%20Time-Interval%20Annotation%20Systems.md)**
  ("BACK-DOC") — concrete Pydantic v2 model definitions, PostgreSQL +
  `tstzrange` + GiST recipes, FastAPI/MCP/Hocuspocus stack decision,
  CRDT-via-Yjs strategy, `.annot` SQLite handoff format, MUST-have list,
  risk register.
- **[Frontend UI for Multitrack Time-Interval Annotation Editors](./Frontend%20UI%20for%20Multitrack%20Time-Interval%20Annotation%20Editors.md)**
  ("FRONT-DOC") — component tree, render-tier policy (DOM → Canvas → WebGL),
  zustand+immer+zundo state architecture, NLE keyboard vocabulary, ARIA grid
  pattern, `AnnotationLayerSpec<T>` plugin interface, the recommendation
  matrix, MUST-have minimum editor.
- **[Open-Source Codebase Deep-Dive — What to Build On and What to Steal From](./Open-Source%20Codebase%20Deep-Dive%20for%20Timeline%20%3A%20Multitrack%20Annotation%20Editors-%20What%20to%20Build%20On%20and%20What%20to%20Steal%20From.md)**
  ("OSS-DOC") — tier-ranked verdicts on Theatre.js, OTIO, wavesurfer.js,
  Label Studio Frontend, CVAT, ELAN, Olive, Yjs, Motion Canvas, vis-timeline,
  Etro, Remotion, OpenShot, Pitivi, etc., with seam/vendoring strategy.

When this roadmap and a design doc disagree, **the design doc wins** — fix
the roadmap. The roadmap is a synthesis; the docs are the reasoning.

---

## North Star

`lacing` is a **standoff, interval-keyed annotation system** with a Python
backend and a TypeScript/React frontend, sharing one schema-versioned data
model — designed for time-based media (audio/video/speech/music) but
generalizable to any 1-D interval domain via Allen's algebra.

Shape: **OTIO-style time + ELAN-style tiers + W3C Web Annotation envelope +
a `MutableMapping[Interval, list[Annotation]]` facade**, with a frontend
that builds on **`@theatre/core` + `wavesurfer.js` + `dnd-timeline` + zustand
/ immer / zod** under a custom shadcn UI shell.

Sources: ANN-DOC §C "Standoff annotation and the interval tree core";
BACK-DOC §2.1, §4.1; FRONT-DOC §1.8 "Recommendation Matrix",
§6.1 "Component tree"; OSS-DOC "Final Synthesis".

---

## Non-negotiables (locked in by all four docs)

| # | Commitment | Primary source |
|---|---|---|
| 1 | **Time as `RationalTime(value: int, rate: int)`** — never floats. Wire as `{v, r}`; Python `fractions.Fraction`; TS `bigint` pair. | OSS-DOC OTIO section ("steal RationalTime outright"); BACK-DOC §2.1; ANN-DOC conclusion; FRONT-DOC §4.1 |
| 2 | **Standoff annotations.** Source media immutable; annotations reference by `(asset_id, interval)`. | ANN-DOC §C; BACK-DOC §2.1 |
| 3 | **One annotation envelope, typed body.** Single `Annotation` shape; `body: dict` validated by `body_schema_uri` (semver). No polymorphic class hierarchy. | BACK-DOC §2.1, §4.1; OSS-DOC anti-patterns |
| 4 | **Interval tree as in-memory index** (`intervaltree`, Apache-2.0); **PostgreSQL `tstzrange` + GiST** as persistent index. | ANN-DOC §C, §E; BACK-DOC §3.1, §4.2 |
| 5 | **Mapping facade.** `IntervalAnnotationStore(MutableMapping[TimeInterval, list[Annotation]])` exposing Allen's relations. | ANN-DOC §C ("a natural design target"); BACK-DOC §4.1 |
| 6 | **Tier stereotypes from ELAN, verbatim:** `NONE`, `TIME_SUBDIVISION`, `INCLUDED_IN`, `SYMBOLIC_SUBDIVISION`, `SYMBOLIC_ASSOCIATION`. | ANN-DOC §C; BACK-DOC §2.1; FRONT-DOC §6.3; OSS-DOC tier-2.4 |
| 7 | **Adapter pattern for I/O.** Core never imports a format; every format is a plugin. | ANN-DOC §C ("non-negotiable"); OSS-DOC OTIO `SchemaDef` manifest |
| 8 | **PROV-O provenance inline on every annotation.** `was_generated_by`, `was_derived_from`, `was_attributed_to`, `generated_at_time`. AI annotations carry `agent:<model>@<hash>`. | ANN-DOC §C; BACK-DOC §4.5 |
| 9 | **Pydantic v2 → JSON Schema → Zod codegen.** One SoT, two languages. | BACK-DOC §6 (`datamodel-code-generator` + `json-schema-to-zod`); FRONT-DOC §6.3 |
| 10 | **License hygiene: MIT/BSD/Apache only.** Avoid: `portion` (LGPL), `praat-parselmouth` (GPL), `aeneas` (AGPL), Peaks.js (LGPL), Etro (GPL), `@theatre/studio` (AGPL), Remotion (BSL). | ANN-DOC §E table; FRONT-DOC §1.8; OSS-DOC tier-3 |

---

## Package decomposition

A monorepo (or sibling repos under `lacing-*`) — recommended in BACK-DOC Q44.

```
lacing/                     ← this repo: the core library (no server, no UI)
├── lacing/
│   ├── time.py             RationalTime, TimeInterval         [BACK-DOC §2.1]
│   ├── model.py            Annotation, Reference, Provenance  [BACK-DOC §2.1]
│   ├── tier.py             Tier + 5 ELAN stereotypes          [ANN-DOC §C]
│   ├── schema.py           body_schema registry; JSON-Schema export
│   ├── allen.py            13 Allen relations + composition   [ANN-DOC §A]
│   ├── store/
│   │   ├── base.py         IntervalAnnotationStore (MutableMapping facade)
│   │   ├── memory.py       intervaltree-backed                [ANN-DOC §C]
│   │   ├── sqlite.py       .annot SQLite + R*Tree             [BACK-DOC §3.1]
│   │   └── postgres.py     tstzrange + GiST + EXCLUDE         [BACK-DOC §4.2]
│   ├── adapters/           plugin-registered I/O              [ANN-DOC §C]
│   │   ├── textgrid.py     via praatio (MIT)
│   │   ├── eaf.py          via pympi
│   │   ├── webvtt.py
│   │   ├── jams.py
│   │   ├── label_studio.py
│   │   ├── web_annotation.py   W3C JSON-LD
│   │   └── otio.py         RationalTime parity                [OSS-DOC OTIO]
│   ├── quality.py          IAA: kappa, Krippendorff α, IoU, DER  [ANN-DOC §D]
│   └── _utils.py
└── misc/docs/              this folder — design rationale

lacing-server/              ← FastAPI app (depends on lacing)  [BACK-DOC §3, §6]
├── server/
│   ├── api.py              REST CRUD, batch, exports
│   ├── ws.py               Hocuspocus / Yjs WebSocket bridge (Phase 4+)
│   ├── mcp.py              MCP tools                          [BACK-DOC §3.3]
│   ├── workers.py          Arq tasks (forced alignment, change-point)
│   ├── auth.py             stub initially
│   └── otel.py             OpenTelemetry + op-log replay      [BACK-DOC §4.7]

lacing-ui/                  ← React/TS frontend                [FRONT-DOC §6.1]
├── packages/core/          domain types + zod schemas (codegen target)
├── packages/store/         zustand: domainStore, uiStore, viewStore
├── packages/render/        TimelineRoot, TrackHeader, Track, Item, Ruler, Playhead
├── packages/plugins/       AnnotationLayerSpec<T> registry    [FRONT-DOC §6.3]
├── packages/audio/         wavesurfer.js v7 wrapper           [OSS-DOC tier-1]
└── packages/app/           shadcn shell, routing, demo project
```

`lacing` itself stays small and dependency-light. Server and UI are sibling
packages so users can adopt the data model without infra.

---

## Phased roadmap

### Phase 0 — Foundations (1–2 weeks)
**Goal: a usable Pythonic core with no server, no UI.**
*Sources: ANN-DOC §C, §D; BACK-DOC §2.1, §4.1.*

- `RationalTime`, `TimeInterval` (Pydantic v2 + `fractions.Fraction` helpers).
- `Annotation`, `Reference{Media,Node,Annotation}`, `Provenance`, `Tier`.
- `IntervalAnnotationStore` (`MutableMapping`) over `intervaltree`.
- All 13 Allen relations as pure functions on `TimeInterval`.
- Round-trip tests with ≥3 formats: Praat TextGrid, WebVTT, W3C Web Annotation JSON-LD.
- Quality metrics: kappa, Krippendorff α, boundary IoU.
- README "simple things simple": load TextGrid → query overlaps → save WebVTT in 5 lines.

### Phase 1 — Persistence & adapters (1–2 weeks)
*Sources: BACK-DOC §3.1, §4.3; ANN-DOC §C, §E.*

**Done:**
- SQLite + R*Tree → defines the `.annot` portable file format (BACK-DOC §3.1). ✓
- `.annot` adapter (lossless round-trip + `persistent=True` for live mutation). ✓
- CLI (`argh`): `lacing convert`, `lacing query`, `lacing validate`, `lacing list-formats`. ✓
- **ELAN EAF adapter** — first adapter to exercise the tier hierarchy with stereotypes (TIME_SUBDIVISION, INCLUDED_IN, SYMBOLIC_SUBDIVISION, SYMBOLIC_ASSOCIATION). ✓

**Remaining:**
- Postgres + `tstzrange` + GiST + per-tier `EXCLUDE` constraints (optional install).
- JAMS, Label Studio JSON, OTIO adapters.
- JSON Schema export per body schema; semver in `body_schema_uri`.

### Phase 2 — Server (2–3 weeks)
*Sources: BACK-DOC §3, §4.6, §4.7, §6.*

- FastAPI: REST CRUD, batch import/export, ETag-based optimistic concurrency.
- Background workers via **Arq** (avoid Celery — BACK-DOC §6).
- MCP server (`mcp[cli]`) — agents are first-class clients (BACK-DOC §3.3).
- OpenTelemetry + **op-log replay endpoint** (`GET /projects/{id}/state-at?clock=…`)
  — flagged as "killer debug feature" in BACK-DOC §4.7.
- **Defer:** Yjs/Hocuspocus collab. ETags + LWW until two real users actually conflict.

### Phase 3 — Frontend MVP (3–4 weeks)
*Sources: FRONT-DOC §1.8, §4, §6, §10.*

The "minimum useful editor" per FRONT-DOC §10: **audio waveform + dialogue
tier + viseme tier + program monitor + inspector.** Build exactly that.

- React + Vite + shadcn/ui + Radix.
- State: zustand + immer + **zundo** (100-level undo). Three stores:
  `domainStore` (synced), `uiStore` (ephemeral drag/hover), `viewStore` (zoom/scroll).
  Drag-in-progress is UI; drag *result* is domain (FRONT-DOC §6.2).
- Codegen: Pydantic → JSON Schema → Zod.
- Plugin interface `AnnotationLayerSpec<T>` (FRONT-DOC §6.3) with Zod schema →
  auto-generated Inspector form via `react-hook-form`.
- Render policy (FRONT-DOC §4.1): DOM for headers/sparse, Canvas for waveforms/dense,
  WebGL only when measured.
- Borrow: `wavesurfer.js v7 + Regions`, `dnd-timeline`, `TanStack Virtual`,
  `react-hotkeys-hook`.
- Universal NLE keymap: JKL transport, spacebar, I/O, B blade, R range,
  ripple/razor/lift (FRONT-DOC §1).
- ARIA grid pattern, color-blind safe palette, `prefers-reduced-motion` (FRONT-DOC §8).
- Time as **integer microseconds** at the UI layer; convert at the wire boundary.

### Phase 4 — Collaboration & advanced rendering (when needed, not before)
*Sources: BACK-DOC §2.2, §4.4; FRONT-DOC §8.2; OSS-DOC tier-2.6.*

- **Yjs Awareness only** for presence/cursors (low-risk).
- **Defer document-level CRDT** until a real two-user conflict occurs.
  When it does: `Y.Array` of interval `Y.Map`s with `Y.RelativePosition` anchors,
  no custom CRDT code (BACK-DOC §4.4).
- WebCodecs frame-accurate scrubbing (FRONT-DOC §4.3).
- Pre-computed waveform peaks via BBC `audiowaveform` subprocess (FRONT-DOC §9).
- ELAN-style coordinated **Tier view** alongside the NLE view
  (FRONT-DOC §6.5: "the single most important architectural decision").

### Phase 5 — Differentiators
*Where lacing can lead — gaps explicitly flagged in OSS-DOC:*

- **First-class Allen's interval algebra** in queries — OSS-DOC notes no
  surveyed editor implements all 13 relations cleanly.
- **Soft labels & annotator disagreement preserved** as a feature — Dawid-Skene
  / MACE merging on demand, never destructive (ANN-DOC §D).
- **Generator-based timing** for animation annotation (Motion Canvas-style
  `yield* tween(...)` translated to Python; ANN-DOC conclusion; OSS-DOC tier-2.7).
- **Schema-versioned bodies with registered migrations** (BACK-DOC §4.5).
- **MCP-native** — agents alongside humans, identical provenance treatment.

---

## Stack summary

| Layer | Choice | Source |
|---|---|---|
| Time | `fractions.Fraction` + `RationalTime` (OTIO parity) | OSS-DOC OTIO |
| Core data | Pydantic v2, single envelope | BACK-DOC §2.1 |
| In-memory index | `intervaltree` (Apache-2.0) | ANN-DOC §C |
| Embedded DB | SQLite + R*Tree → `.annot` | BACK-DOC §3.1 |
| Server DB | Postgres 15 + `tstzrange` + GiST | BACK-DOC §4.2 |
| Web framework | FastAPI | BACK-DOC §6 |
| Workers | Arq (Redis) | BACK-DOC §6 |
| Agent interface | `mcp[cli]` | BACK-DOC §3.3 |
| Frontend state | zustand + immer + zundo | FRONT-DOC §2 |
| Frontend forms | react-hook-form + Zod (codegen) | FRONT-DOC §6.3 |
| Audio | wavesurfer.js v7 + Regions (BSD-3) | OSS-DOC tier-1; FRONT-DOC §1.8 |
| Multitrack body | dnd-timeline + TanStack Virtual | FRONT-DOC §1.8, §3 |
| Video | HTML `<video>` → WebCodecs | FRONT-DOC §4.3 |
| Collab | Yjs Awareness now; doc-CRDT later | BACK-DOC §4.4; OSS-DOC tier-2.6 |
| Codegen | Pydantic → JSON Schema → Zod | BACK-DOC §6 |

---

## Tradeoffs flagged for the user

- **Backend complexity vs. shipping speed.** BACK-DOC prescribes a heavy stack
  (Postgres + Hocuspocus + MCP + OpenTelemetry + Arq + S3). Start with **core
  lib + SQLite + FastAPI**; add the rest when scale/collab demands it.
- **Monorepo vs. three repos.** The Python core is independently useful.
  Splitting `lacing` / `lacing-server` / `lacing-ui` allows incremental adoption
  but adds release coordination.
- **Frontend novice tax.** The user has flagged frontend novice status. ~3–4
  weeks for an MVP UI realistically doubles. Alternative: ship the Python core
  with a **Label Studio config adapter** as the first "frontend" and defer the
  custom UI to v2.
- **Theatre.js bus factor.** OSS-DOC strongly recommends `@theatre/core` but
  flags single-maintainer risk and v1.0 in private repo. Vendor `@theatre/dataverse`
  + `@theatre/core` (~18 kLOC) as mitigation.

---

## Recommended first concrete step

Ship **Phase 0 only** as `lacing` v0.1, validate the data model on a real
corpus (a TextGrid + a WebVTT) before any server or UI work. All four docs
converge on this: the model is the leverage point; everything else is replaceable.

---

## For agents working on lacing

When asked to do work on this package:

1. **Identify which phase the task belongs to** and consult the design doc
   cross-referenced for that phase.
2. **Re-read the relevant doc section** (cited above) before making
   architectural changes — the docs contain the *why*; this roadmap only
   the *what*.
3. **If the docs and roadmap disagree, the docs win.** Update the roadmap.
4. **License-check every new dependency** against ANN-DOC §E and FRONT-DOC §1.8
   before adding it. MIT/BSD/Apache only.
5. **Time is rational, never float** — every tool, parser, and adapter has to
   uphold this end-to-end.
