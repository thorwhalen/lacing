# Phase 3 Frontend Plan

> Synthesis: FRONT-DOC + OSS-DOC's frontend tier-rankings + the user's
> requirement to use **zodal** for storage/API/UI and **wrapex**'s
> command-dispatch architecture where it fits.
>
> Read `Frontend UI for Multitrack Time-Interval Annotation Editors.md`
> for the WHY behind every UX decision; this doc is the WHAT.

---

## North star (one sentence)

`lacing-ui` is a React/TS app where every user action is a
`wrapex`-registered command, every collection of annotations / tiers /
projects is a `zodal` collection backed by a `DataProvider`, and the
multitrack timeline body is a custom Canvas-rendered component sitting
on top of `wavesurfer.js v7` for audio.

The minimum useful editor (per FRONT-DOC §10) is **audio waveform +
dialogue tier + viseme tier + program monitor + inspector**. Everything
else in the FRONT-DOC roadmap is post-MVP.

---

## Architectural anchors (non-negotiable)

The user explicitly named these:

1. **`zodal` for frontend storage, API, and UI interface abstractions.**
   - Storage: `DataProvider<T>` from `@zodal/store` is the API contract.
   - UI: `@zodal/ui` generators (`toColumnDefs`, `toFormConfig`,
     `toFilterConfig`) + `createShadcnRegistry()` for the inspector,
     forms, and lists.
   - Schemas: every domain entity is a `defineCollection(zodSchema)`.
2. **`wrapex` command-dispatch where it fits.**
   - Every user action (`apply filter`, `create annotation`, `accept AI
     suggestion`, `export selection`, `switch backend`, `run inference`,
     `undo`, `redo`) is a `defineCommand({ id, label, schema, execute })`.
   - One `createRegistry()` per app instance; `evaluateWhen`,
     `contextProvider`, and `middleware` plumbed at construction time.
   - Wire the registry to a Ctrl-K palette first, then keybindings,
     then MCP/AI later (the lacing backend already speaks MCP).

These anchors **replace** several specific FRONT-DOC recommendations:

| FRONT-DOC said | We use instead | Why |
|---|---|---|
| zustand stores by hand for `domainStore`, `uiStore`, `viewStore` | `createCollectionStore()` from `@zodal/ui` for domain; bare zustand for `uiStore` + `viewStore` | Schema-driven; same shape as backend |
| Hand-written REST client | `zodal-store-supabase` style adapter against the lacing FastAPI server | Same `DataProvider<T>` contract |
| Auto-generated Inspector via `react-hook-form` + `@hookform/resolvers/zod` + custom schema-walker | `@zodal/ui` `toFormConfig` + `createShadcnRegistry()` form renderers | Same idea, already implemented |
| `react-hotkeys-hook` for keymap | wrapex commands' `keybinding` field, dispatched through `registry.execute` | Surface-agnostic |
| Custom command system for undo/redo (`zundo`) | wrapex middleware that records inverses; `zundo` only inside the timeline-drag ephemeral store | Domain undo flows through commands |

Things FRONT-DOC said that we **keep**:

- Time as integer microseconds at the UI layer; `RationalTime` `{v, r}`
  at the wire boundary.
- Render policy: DOM for headers/sparse, Canvas for waveforms/dense,
  WebGL only when measured.
- ARIA grid pattern, color-blind safe palette, `prefers-reduced-motion`.
- Universal NLE keymap: JKL, spacebar, I/O, B blade, R range.
- Borrowed deps: `wavesurfer.js v7 + Regions`, `dnd-timeline`,
  `TanStack Virtual`.

Things FRONT-DOC said that we **drop or defer**:

- `@theatre/core` integration. Lovely architecture, but it adds a
  large vendored dependency for a benefit we don't yet have a real
  use case for. Defer to Phase 5 if we want generator-based timing.
- Yjs presence/collab for v1. The lacing backend op-log + ETags
  cover the conflict cases. Add Yjs awareness when there's a real
  two-user conflict in production.
- WebCodecs frame-accurate scrubbing. Use HTML `<video>` until
  scrubbing precision is the bottleneck.

---

## Stack

### Tooling

- **Vite + React 18 + TypeScript (strict).**
- **Package manager:** the user's preference (probably `pnpm` if
  monorepo, otherwise `npm`). Check `~/.claude/CLAUDE.md` for global
  preferences before assuming.
- **Lint/format:** Biome (one-tool replacement for ESLint+Prettier).
- **Tests:** Vitest + React Testing Library. Use Playwright for one
  smoke E2E test (the "minimum useful editor" flow).

### Runtime deps (the must-haves)

- `@zodal/core`, `@zodal/store`, `@zodal/ui`, `zodal-ui-shadcn`
- `command-wrapex` (the npm runtime)
- `zod`, `zustand`, `immer`, `zundo`
- `react-hook-form`, `@hookform/resolvers/zod`
- `wavesurfer.js@^7`, `dnd-timeline`, `@tanstack/react-virtual`
- `shadcn/ui` (vendored components, not an npm dep)
- `lucide-react` (icons; ships with shadcn)

### Notably absent

- `@theatre/core` / `@theatre/dataverse`
- `yjs`, `y-protocols`
- `react-timeline-editor`, `vis-timeline`, `peaks.js`
- ffmpeg.wasm (until export demands it)

### License audit (FRONT-DOC §1.8 banlist)

- ❌ Etro (GPL-3.0)
- ❌ `@theatre/studio` (AGPL-3.0)
- ❌ Peaks.js (LGPL)
- ❌ audioMotion-analyzer (AGPL)
- ❌ Remotion (BSL)

---

## Repository layout

Two options, both legitimate:

**Option A — sibling repo (`lacing-ui`).** Cleaner separation,
independent release cadence, same pattern as the proposed `lacing-server`
split in the architecture skill. Best if Phase 3 will live and breathe
on its own.

**Option B — monorepo with `apps/ui/` under the existing `lacing/`.**
Tighter feedback loop with the Python server; one `git pull` covers
everything. Best if Phase 3 will be co-developed with backend tweaks.

Recommendation: **Option A** (sibling repo), because:
- The lacing core, server, MCP, and adapters have all moved at high
  velocity in the past 2 days; a sibling repo decouples npm tooling
  from Python tooling and CI.
- Matches the `lacing-server/` and `lacing-ui/` decomposition the
  architecture skill already mentions.

Inside `lacing-ui/`:

```
lacing-ui/
├── src/
│   ├── domain/                 zodal collections + Zod schemas
│   │   ├── annotation.ts       defineCollection(annotationSchema)
│   │   ├── tier.ts             defineCollection(tierSchema)
│   │   ├── project.ts          defineCollection(projectSchema)
│   │   └── time.ts             RationalTime <-> microseconds helpers
│   ├── store/                  zodal DataProviders
│   │   ├── lacing-rest.ts      DataProvider talking to FastAPI
│   │   ├── lacing-mcp.ts       (later) DataProvider talking to MCP
│   │   └── factories.ts        configurable provider selection
│   ├── commands/               wrapex commands
│   │   ├── registry.ts         createRegistry(...) + middleware
│   │   ├── annotations.ts      add, update, delete, accept_ai
│   │   ├── tiers.ts            create, rename, delete
│   │   ├── timeline.ts         seek, zoom, snap, ripple, blade
│   │   ├── transport.ts        play, pause, jkl
│   │   ├── selection.ts        select, multi-select, range
│   │   ├── io.ts               import, export, switch backend
│   │   └── index.ts            registerAll(commands)
│   ├── ui/
│   │   ├── shell/              app chrome (toolbar, status bar, tabs)
│   │   ├── timeline/           multitrack body (Canvas)
│   │   ├── monitor/            video/audio program monitor
│   │   ├── inspector/          @zodal/ui-driven schema forms
│   │   ├── palette/            Ctrl-K command palette over wrapex registry
│   │   └── theme/              shadcn primitives + tokens
│   ├── waveform/               wavesurfer.js wrapper
│   ├── stores/                 zustand stores (uiStore, viewStore)
│   ├── hooks/                  small composables
│   ├── types/                  generated Zod from JSON Schema
│   │   └── generated/          (output of json-schema-to-zod)
│   └── App.tsx
├── tests/
├── vite.config.ts
├── package.json
└── README.md
```

---

## Domain modeling with zodal

### Zod schemas mirror Pydantic source-of-truth

Per `lacing-schema-codegen` skill: Pydantic v2 is the SoT. Run
`lacing.schema.export_json_schemas("./schema/")` in the Python repo,
then `json-schema-to-zod` over the output to produce
`src/types/generated/*.ts`. Commit both sides.

For the envelope-level types (`RationalTime`, `TimeInterval`,
`Reference`, `Provenance`), hand-write the Zod schemas to match
`lacing.model` exactly — they don't change often, and we want explicit
control over the wire boundary.

### `defineCollection` per entity

```typescript
// src/domain/annotation.ts
import { z } from "zod";
import { defineCollection } from "@zodal/core";
import { ReferenceSchema, ProvenanceSchema } from "@/types/generated";

export const annotationSchema = z.object({
  id: z.string().uuid(),
  tier: z.string(),
  reference: ReferenceSchema,
  body: z.record(z.unknown()),
  body_schema_uri: z.string(),
  provenance: ProvenanceSchema,
  confidence: z.number().min(0).max(1).nullable().optional(),
});

export const annotationCollection = defineCollection(annotationSchema);
```

zodal infers column defs, form configs, filter configs from this. The
inspector form is generated by `toFormConfig(annotationCollection)`
+ `createShadcnRegistry()`.

### `lacing-rest` DataProvider

A thin adapter implementing `DataProvider<Annotation>` over
`fetch('/annotations')`. The lacing FastAPI server already exposes:

- `GET /annotations?tier&start&end&relation&rate&limit` → list
- `POST /annotations` → create (returns ETag)
- `GET /annotations/{id}` → one (returns ETag)
- `PATCH /annotations/{id}` (If-Match) → update
- `DELETE /annotations/{id}` → remove

That maps directly to `getList`, `create`, `getOne`, `update`, `delete`
on the `DataProvider`. The Allen-relation filters become custom filter
operators in zodal's `FilterExpression`.

### `lacing-mcp` DataProvider (later)

If we want the same UI to work over MCP (e.g., for AI-driven editing
sessions), wrap the MCP tools in a second adapter. Same `DataProvider<T>`
contract, different transport.

---

## Command architecture with wrapex

### Registry construction

```typescript
// src/commands/registry.ts
import { createRegistry, createDefaultMiddleware } from "command-wrapex";

export const registry = createRegistry({
  middleware: [
    ...createDefaultMiddleware(), // validation, error boundary, logging
    createTelemetryMiddleware({ /* OTel later */ }),
  ],
  evaluateWhen: ({ when, ctx }) => evaluateWhenClause(when, ctx),
  contextProvider: () => ({
    dataProvider: getActiveDataProvider(),
    annotationStore: useAnnotationStore.getState(),
    selection: useUiStore.getState().selection,
  }),
});
```

### Command per user action

```typescript
// src/commands/annotations.ts
defineCommand({
  id: "lacing.annotations.create",
  label: "Create annotation",
  category: "Annotations",
  schema: annotationCreateSchema,
  metadata: { riskLevel: "low", idempotent: false },
  execute: async (params, ctx) => {
    const created = await ctx.dataProvider.create(params);
    ctx.annotationStore.upsert(created);
    return { success: true, data: created };
  },
});

defineCommand({
  id: "lacing.annotations.acceptAi",
  label: "Accept AI suggestion",
  category: "AI",
  schema: z.object({ id: z.string().uuid() }),
  keybinding: "Mod+Shift+A",
  when: "selection.kind === 'annotation' && selection.confidence < 1",
  metadata: { riskLevel: "low", idempotent: true, requiresConfirmation: false },
  execute: async ({ id }, ctx) => {
    // Hits the same operations module the FastAPI + MCP layers use.
    const updated = await ctx.dataProvider.update(id, {
      confidence: 1.0,
      provenance: { /* ... */ },
    });
    return { success: true, data: updated };
  },
});
```

### Surfaces

- **Ctrl+K palette** — list `registry.listAvailable()` filtered by user
  query; on enter, `registry.execute(id, params)`.
- **Keybindings** — register all commands with non-empty `keybinding`
  in a global `useKeyboardShortcuts` hook.
- **AI / MCP** (later) — `registry.listDescriptors(toPortableSchema)`
  produces JSON Schema for tool registration.
- **Tests** — `registry.execute(id, params, { surface: "test" })` is
  enough to drive most state transitions.

### Undo/redo

wrapex doesn't ship inverses. Two-tier approach:

- **Domain undo** through the command registry: every mutation
  command emits an inverse command in its result; a custom
  `undoStore` (zustand) keeps a stack of `(forward, inverse)` pairs;
  `Mod+Z` runs `registry.execute(inverse.id, inverse.params)`.
- **Drag-in-progress undo** through `zundo` on the ephemeral
  `uiStore` — only the *final* drag commits to the domain store via
  a command.

This matches FRONT-DOC §6.2's "drag-in-progress is UI; the drag
*result* is domain" rule.

---

## Phase 3 milestones

### Phase 3.0 — Project skeleton (1 day)

- Vite + React + TS strict; Biome configured; vitest + RTL working.
- shadcn/ui initialized; theme tokens for dark mode + reduced motion.
- One placeholder route renders "lacing".
- CI: GitHub Actions running `npm run lint && npm run typecheck && npm run test`.

### Phase 3.1 — Codegen + domain (1–2 days)

- `npm run codegen` script that:
  1. Calls into the Python repo via subprocess (or fetches a checked-in JSON dump): `python -m lacing.schema.export ./schema-export/`.
  2. Runs `json-schema-to-zod` over `./schema-export/`.
  3. Writes `src/types/generated/*.ts`.
- Hand-written Zod schemas for envelope types (`RationalTime`,
  `TimeInterval`, `MediaRef`, `Provenance`).
- `defineCollection` for `Annotation`, `Tier`, `Project`.

### Phase 3.2 — DataProvider + MSW dev fixture (2 days)

- `lacingRestProvider({ baseUrl, fetch })` implementing `DataProvider<T>`
  for each entity collection.
- Mock Service Worker (`msw`) intercepts `/annotations`, `/tiers`, etc.
  during dev and tests with a fake in-memory store. This lets the UI
  develop against realistic responses without requiring a running
  Python server.
- TanStack Query (or zodal's own caching layer if it ships one) over
  the provider for caching + invalidation.

### Phase 3.3 — Command registry + palette (2 days)

- `createRegistry` with default middleware.
- ~30 commands covering annotations, tiers, transport, selection.
- Ctrl+K palette UI: input → fuzzy search over `registry.listVisible()`
  → execute on enter. shadcn `Command` component is the right primitive.
- `useKeyboardShortcuts(registry)` hook that wires `keybinding` fields
  into a global listener.

### Phase 3.4 — Inspector + tier list (2–3 days)

- Inspector panel: when a single annotation is selected, render its
  body via `toFormConfig(annotationCollection)` +
  `createShadcnRegistry()`. Edits dispatch `lacing.annotations.update`.
- Tier list: `toColumnDefs(tierCollection)` over a left sidebar.
  Each row is a tier; clicking it scrolls/highlights its lane.

### Phase 3.5 — Audio waveform + program monitor (3 days)

- Wavesurfer wrapper component: lazy-loads, registers regions for
  every annotation in the visible window, dispatches
  `lacing.transport.seek` on click.
- Program monitor: HTML `<audio>` (or `<video>` for video projects)
  driven by the playhead store.
- JKL transport commands.

### Phase 3.6 — Multitrack timeline body (4–5 days)

- Canvas-rendered tracks via `dnd-timeline` for layout +
  `@tanstack/react-virtual` for vertical virtualization.
- One row per tier; annotations render as rectangles with shadcn
  styling + Okabe-Ito color scheme.
- Drag-to-resize, drag-to-move, blade (`B` / `Mod+B`), ripple (`Shift`
  modifier on drag), lift/extract (`Delete`) — all dispatched as
  commands.
- Magnetic playhead, snap targets per FRONT-DOC §1.

### Phase 3.7 — Polish + the minimum useful editor (1 week)

- ARIA grid pattern.
- Auto-save (every 5 seconds, batched commands).
- Theming.
- Open/save `.annot` files via `import` / `export` REST endpoints.
- One Playwright smoke test that loads a sample, makes one annotation,
  edits it, exports it.

**Total estimate: 3–4 weeks part-time** for Phases 3.0–3.7.

Anything beyond (Yjs collab, WebCodecs, ELAN tier view, `@theatre/core`)
is post-MVP and goes in `Phase 4 / 5 ideas` not this plan.

---

## What the next session should do first

1. Create `lacing-ui` as a sibling repo (or under the user's preferred
   directory).
2. Decide: real Python server, MSW mock, or both? (Probably both —
   MSW for unit tests, real server for dev runs.)
3. Pin the wrapex + zodal versions in `package.json` to whatever
   `npm view command-wrapex version` and `npm view @zodal/core version`
   say at start of the session.
4. Implement Phase 3.0 + 3.1 + 3.2 in order. Stop and confirm with
   the user before Phase 3.3 — by then enough is in place that the
   architectural shape is visible.

---

## Reference

- **FRONT-DOC** for the WHY behind every UX decision.
- **OSS-DOC** for what to borrow vs. avoid in the JS ecosystem.
- **`Phase 2 Findings — What Stuck and What Drifted.md`** for the
  backend's actual shape (not just what the doc said it would be).
- **`lacing-architecture` skill** for the ten non-negotiables.
- **`lacing-schema-codegen` skill** for the codegen pipeline (which
  this Phase 3 is the downstream consumer of).
- **`zodal-ecosystem` skill** at `~/.claude/skills/zodal-ecosystem/SKILL.md`.
- **wrapex SKILL** at `/Users/thorwhalen/Dropbox/py/proj/t/wrapex/SKILL.md`.
