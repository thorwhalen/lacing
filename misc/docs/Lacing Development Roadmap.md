# Lacing Development Roadmap

> Working plan for what the `lacing` package should develop.
> Synthesized from the four design docs in this folder; each section
> cross-references the source doc(s) so agents can drill in for detail.

## Companion design docs in this folder

Two of these were authored after-the-fact during the build:

- **[Phase 2 Findings — What Stuck and What Drifted](./Phase%202%20Findings%20%E2%80%94%20What%20Stuck%20and%20What%20Drifted.md)** —
  the calls I made that the original four design docs didn't anticipate
  (`int8range` over `tstzrange`, `RationalTime` boundary tricks, processor
  idempotence, FastMCP test ergonomics, wads-CI auto-bump rebase pattern,
  ...). Read this before assuming the design docs are still complete.
- **[Phase 3 Frontend Plan](./Phase%203%20Frontend%20Plan.md)** — the
  WHAT for Phase 3, applying zodal (storage / API / UI abstractions)
  and wrapex (command-dispatch architecture). Hand-off-ready.

The four originals below are the authoritative source of *why* behind
every decision. Read the relevant one before making non-trivial design changes.

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

### Externally validated (2026-08-03)

An 18-deliverable survey of node-graph systems for generative media (the
video_gen research programme — briefs A–G on the design space, H–O on
ComfyUI at source; held in a private research repo, entry point
`data/groups/video_gen/docs/reelee_comfyui_decisions_and_rationale.md`,
evidence under `data/groups/video_gen/docs/research/`) checked this North
Star against every comparable system it could read at source. **The core
bet holds, and the survey sharpens it.**

- **No generative canvas has time at all.** ComfyUI, ElevenLabs Flows,
  Runway Workflows, Adobe Firefly Graph, Weave, Krea Nodes, Flora and
  Higgsfield Canvas all evaluate the graph exactly once; a video is an
  opaque blob emitted by one node; there is no `t`, and a parameter cannot
  be animated. Confirmed without exception.
- **DCC compositors have `f(t)`, not intervals.** Nuke propagates an
  `OutputContext` (frame, view, proxy scale) *upstream* — "time belongs in
  the demand, not in the graph." Houdini and Blender treat frame as global
  scene state with explicit cache barriers. That is a **sampling** model.
- **Fusion and Notch ship editable per-node time extents** — so "nobody has
  intervals" would be too strong. They are *extents*, not *relations*.
- **Nothing anywhere has an interval algebra.** No Allen relations, no
  "this beat *meets* that beat", no alignment as a queryable predicate.

**The sharpened claim: the differentiator is the RELATIONAL layer, not
intervals as such.** `lacing/allen.py` plus the store surface declared at
`lacing/store/base.py:66-98` — `intersects` / `during` / `contains` /
`overlaps` / `meets` / `starts` / `finishes` / `equals` / `relate` — is the
part no surveyed system has. A sampling model answers "what is the value at
*t*"; it cannot answer "which beats overlap this scene", "does this
voiceover finish before this cut", or "which annotations are contained in
this shot" without a scan.

Two consequences for how we build:

1. Keep Phase 5's **first-class Allen's interval algebra** at the top of the
   differentiator list, and treat the relational query surface — not the
   `TimeInterval` type — as the thing to polish and document first.
2. **Do not let the annotation tier and an execution tier borrow each
   other's time model.** The annotation tier owns intervals and relations.
   An execution tier (`nw`, `falaw`) should adopt Nuke's model: the interval
   travels on the *demand* that materialises a work item, never baked into
   the transform — so changing a time range does not edit the graph.

*Source: brief G `GAP-TIME` (`data/groups/video_gen/docs/research/G_synthesis_and_gap_analysis.md`).*

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

### Rejected alternative for #1: `decimal.Decimal`

`Decimal` is sometimes proposed as an alternative to `RationalTime` because it
also avoids float drift. It is rejected for three reasons:

1. **Sample-rate ratios are not terminating decimals.** `1001/24000`
   (one frame at 23.976 fps), `1/44100` (one audio sample at 44.1 kHz), and
   `1/3` (a third of a beat) all have infinite decimal expansions and cannot
   be represented exactly by `Decimal`. `Fraction(1001, 24000)` is exact.
2. **OTIO compatibility.** Every video editor and DCC the user might import
   from or export to (Avid, Resolve, Premiere, ffmpeg via OTIO) speaks
   `RationalTime` natively. Adopting `Decimal` would force a translation
   layer in every adapter and re-introduce the rounding-at-boundaries class
   of bug that `RationalTime` exists to prevent.
3. **No win on the Python side.** `fractions.Fraction` is in the standard
   library, exact under all four arithmetic operations, and has the same
   ergonomics as `Decimal` for the operations that matter here
   (comparison, addition, subtraction, scaling).

This entry exists so future contributors don't re-litigate the question.
The answer is `RationalTime`.

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
- CLI (`cw`): `lacing convert`, `lacing query`, `lacing validate`, `lacing list-formats`. ✓
- **ELAN EAF adapter** — first adapter to exercise the tier hierarchy with stereotypes (TIME_SUBDIVISION, INCLUDED_IN, SYMBOLIC_SUBDIVISION, SYMBOLIC_ASSOCIATION). ✓
- **Postgres backend** with `int8range` + GiST + per-tier `EXCLUDE` (optional via `pip install 'lacing[postgres]'`). Tested via `pytest-postgresql` sandbox — no live server needed for CI. ✓
- **`schema.py`** — body-schema registry, validation, JSON Schema export, and forward migrations. Seed bodies (`word`, `named-entity` with v1→v2 migration) under `lacing/bodies/`. ✓
- **JAMS adapter** — JSON Annotated Music Specification. Each namespace maps to a tier; observation values preserved verbatim. ✓

**Remaining:**
- Label Studio JSON, OTIO adapters.

> **Note on the int8range vs tstzrange decision.** BACK-DOC §4.2 leaned
> toward `tstzrange`, but lacing's time model is rational ticks at a
> project-wide rate, not wall-clock time. `int8range` over integer ticks
> avoids inventing a fake epoch and uses the same `&&` / `<@` / `@>` /
> `-|-` operators. The project rate is stored in `meta` and enforced on
> insert; opening with a different rate raises `PgSchemaMismatchError`.

> **Correction — "forward migrations" above is body-schema-only.** The
> `schema.py` ✓ covers `register_migration` / `migrate`
> (`lacing/schema.py:231`, `:261`), whose registry is keyed
> `(schema_name, from_version)` and whose callables are `dict -> dict` over
> annotation **bodies** (`lacing/schema.py:224`). There is **no migration
> path for the envelope or the on-disk store.** `Annotation`, `Provenance`
> and `Artifact` carry no version field at all, and `SqliteStore` /
> `PgStore` hold a `SCHEMA_VERSION` in `meta` that they *check and refuse
> on mismatch* (`lacing/store/sqlite.py:62`, `:167-170`;
> `lacing/store/postgres.py:89`, `:370-373`). `lacing/store/sqlite.py:22-23`
> documents an upgrade-function registry that does not exist, and Postgres
> is already at `SCHEMA_VERSION = 2` with no v1→v2 path in the tree — a v1
> database, if any exists, is unopenable rather than upgradable. Any change
> to the envelope (Phase 6) needs that ladder built first.

### Phase 2 — Server (2–3 weeks)
*Sources: BACK-DOC §3, §4.6, §4.7, §6.*

**Done:**
- FastAPI app factory + store-agnostic dependency injection. ✓
- REST CRUD for annotations + tiers (with discriminated reference union). ✓
- ETag-based optimistic concurrency on PATCH (BLAKE2b content hash; `If-Match` required; wildcard `*` accepted). ✓
- Allen-relation list filters: `?start&end&rate&relation=intersects|during|...`. ✓
- Import/export endpoints proxying every registered adapter (`POST /import?format=...`, `GET /export?format=...`). ✓
- Schema introspection (`/schemas`, `/schemas/{uri}` returns JSON Schema). ✓
- Health + meta endpoints. ✓
- **Op-log + time-travel** (`lacing/oplog.py`, `GET /oplog`, `GET /state-at?clock=N`). Every server mutation records a Lamport-clock-stamped entry; `state-at` replays the log into a fresh store. The "killer debug feature" from BACK-DOC §4.7. ✓

- **MCP server** (`lacing.server.mcp.build_mcp_server`) — 10 tools matching the REST surface in agent-friendly seconds-based API. ✓
- **Processor registry** (`lacing/processors.py`) with `register_processor` decorator, `run_sync` / `run_async` runners, and two built-ins (`low_confidence_review`, `detect_density_change_points`). Optional **Arq integration** via `lacing/worker.py` under `[arq]` extra (Redis required only for Arq mode; sync execution works without it). ✓

- **OpenTelemetry instrumentation** (`lacing/otel.py`) — `get_tracer`, `maybe_span`, `traced` decorator, and `instrument_app(app)` ASGI middleware that tags every request span with `lacing.clock` (the Lamport clock from the op-log). All helpers degrade to no-ops when OpenTelemetry isn't installed; opt-in via `pip install 'lacing[otel]'`. ✓

**Phase 2 is complete.** All BACK-DOC §3-4.7 items are in.

**Deferred** (not in scope):
- Yjs/Hocuspocus collab. ETags + LWW until two real users actually conflict.

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

### Phase 6 — Provenance completeness & content addressing (generative pipelines)
*Sources: the video_gen research programme, held in a private research repo
— brief B (`EVAL-CACHEKEY`, `EVAL-EARLY-CUTOFF`), brief C (`FMT-ONNX-2`,
`FMT-F-KEEPALL`, §10.1), brief G (`GAP-PROVENANCE`, `GAP-EARLY-CUTOFF`,
`GAP-CONTRACT-CACHE`, §4.4), brief O §4.6 and §5; decisions of record §6
and §9. Unlike the companion docs listed at the top of this file, these are
not in this folder; paths are
`data/groups/video_gen/docs/research/<BRIEF>.md`.*

lacing is the annotation SSOT for the video_gen federation (`nw`, `falaw`,
`reelee`, `braidio`, `artful`). That survey found **provenance completeness
is the strongest confirmed gap in the whole field** — and that one of its
breakdown modes is structural and ours:

> `Provenance.was_derived_from` is typed `list[UUID]`
> (`lacing/model.py:86`), while a `lacing.Artifact` is identified by a
> 64-char hex `asset_id` (`lacing/artifact.py:117-123`). **Artifact-to-
> artifact lineage is unrepresentable and is always empty — at exactly the
> tier where the expensive things live.**

This phase is what lacing owes the rest of the federation. It gates
downstream content-addressed early cutoff (`falaw`'s cache key,
`nw.stale_after`), which the survey rates the single highest-value item in
its whole build order: without it, a re-run producing byte-identical output
still invalidates every downstream node, and a 200-shot fan-out is the
difference between free and several hundred dollars.

In dependency order:

1. **A store-schema migration ladder** (`lacing/store/`). `SCHEMA_VERSION`
   exists and *refuses* on mismatch; it does not upgrade, and no registry
   exists. Prerequisite for (2).
2. **Artifact-to-artifact lineage** — the `Provenance.was_derived_from`
   design pass plus migration. This falls under the on-disk-format
   exception to the federation's no-compat-shims rule: real data lives on
   the live server, so it needs a genuine migration, not a rename.
3. **`annotation_value_digest`** — a digest over an annotation's *value*
   (`tier`, `reference`, `body`, `body_schema_uri`, `confidence`),
   excluding `id` and `provenance`. Deliberately distinct from
   `annotation_etag` (`lacing/server/etag.py:19`), which digests the whole
   annotation and is correct for optimistic concurrency and wrong for this.
   One function; unlocks early cutoff for every downstream consumer, and
   depends on nothing else in this phase.
4. **Provenance completions** — a `CacheResolution` activity (three briefs
   independently concluded that a cache hit is a provenance event), a
   `ParameterSet` / `parameters_digest`, port-name-as-`prov:Role` on
   derivation edges, and a `provider_probe_digest` for silent model drift.
   **Silent model drift is unsolved by every format, system and provider
   surveyed** — shipping the canary-probe digest would make lacing the only
   system in that survey able to detect a vendor swapping a model under a
   stable name.
5. **Registry identity discipline** — versioned adapter and body-schema
   identity, an explicitly-settable default version (not `max()`), and no
   silent replacement on re-registration. Copy InvokeAI's
   `@invocation(type, …, version, …)` contract (Apache-2.0); ComfyUI has no
   opset-style versioning at all and is the anti-pattern here.

**Deliberately out of scope:** anything that makes lacing know an execution
backend exists. lacing stays the annotation SSOT; the execution tier is
`nw` + `falaw`, and the survey's central architectural ruling is that
nothing above the execution façade may name a backend.

---

## Stack summary

| Layer | Choice | Source |
|---|---|---|
| Time | `fractions.Fraction` + `RationalTime` (OTIO parity) | OSS-DOC OTIO |
| Core data | Pydantic v2, single envelope | BACK-DOC §2.1 |
| In-memory index | `intervaltree` (Apache-2.0) | ANN-DOC §C |
| Embedded DB | SQLite + R*Tree → `.annot` | BACK-DOC §3.1 |
| Server DB | Postgres 15 + `int8range` + GiST (see Phase 1 note) | BACK-DOC §4.2 |
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
