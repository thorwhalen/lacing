# Frontend UI for Multitrack Time-Interval Annotation Editors

**Author:** Thor Whalen — May 3, 2026

## Executive Summary

Building a frontend whose intermediate artifacts are universally shaped as time-interval annotations forces a strategic choice between two design lineages: the audiovisual NLE tradition (Premiere, Resolve, Final Cut Pro, Kdenlive, Olive, Shotcut) and the broader generic-sequence-UI tradition (ELAN, Praat, Annotorious, Label Studio, vis-timeline, MIDI piano rolls, animation curve editors, DAW arrange views). After surveying both, I conclude **neither subsumes the other**, and the cleanest approach is a single underlying model — a multi-track stack of typed, possibly hierarchical, possibly cross-linked interval annotations — surfaced through **two coordinated views** that share state but trade off density for clarity: an *NLE view* (large media-aware tracks, source/program monitors, snapping, ripple/roll/slip) and a *Tier view* (ELAN-style hierarchical lanes). Both render against the same Zustand store; both share selection, playhead, undo/redo.

The three concrete questions:

1. **Foundation:** **Wavesurfer.js v7** (BSD-3-Clause) for audio waveforms; **dnd-timeline** (MIT, headless, dnd-kit-based) plus **TanStack Virtual** (MIT) for the multitrack body; canvas via **PixiJS** (MIT) for any lane with >500 visible items; **shadcn/ui** + **Radix** for chrome; **zustand** + **immer** + **zod** for state and schema; HTML `<video>` + Web Audio API initially, layered with **WebCodecs** later. Study (do not fork) **OpenCut**, **designcombo/react-video-editor**, **xzdarcy/react-timeline-editor**; study **CVAT cvat-ui** and **annotorious v3** for annotation patterns; study **Theatre.js** for the curve-editor / inspector binding model.

2. **Patterns:** JKL transport, spacebar play/pause, I/O for in/out points; three-tool selection (arrow/select, blade `B`/`Cmd-B`, range `R`); ripple-aware editing; per-track mute/solo/lock/hide; magnetic playhead; range-based comments (Frame.io idiom); ELAN's tier-stereotype semantics (Time Subdivision, Symbolic Subdivision, Symbolic Association, Included In) for hierarchical relationships.

3. **Architecture:** Layered, schema-driven React tree: `TimelineRoot` → `TrackHeaderColumn` + `TrackContentSurface` → `Track[]` → `Lane[]` → `Item[]`; lanes registered through a typed plugin interface (`AnnotationLayerSpec<T>`) carrying a Zod schema, renderer, inspector, handlers, validators; cross-track linking expressed as references the store resolves at selector time; ephemeral UI state in zustand; durable state synced to the Python authoring layer.

---

## 1. Library and Framework Landscape

### 1.1 Audio Waveform Libraries

| Library | License | Last release | TS | Notes |
|---|---|---|---|---|
| **Wavesurfer.js v7** | BSD-3-Clause | v7.12.4, March 16 2026 | First-class | Regions, Timeline, Minimap, Hover, Spectrogram plugins; Shadow DOM with `::part()` styling |
| **Peaks.js** (BBC / chrisn on Codeberg) | LGPL-3.0 | v4.0.0-beta.2, May 13 2025 | Yes | Active dev moved to Codeberg; Konva-based canvas; zoomview/overview split |
| **audioMotion-analyzer** | AGPL-3.0-or-later | v4.5.4 (Jan 2025) / v5.0.0-alpha.1 (Jan 2026) | Yes | Visualization only — no segmentation API; AGPL is generally disqualifying |
| **web-audio-recorder-js** | MIT | Inactive since ~2018 | No | Effectively abandoned |

**Recommendation: Wavesurfer.js v7.** BSD-3-Clause license, TypeScript-first design, and the Regions plugin maps directly onto our interval-annotation primitive. Wavesurfer's docs explicitly recommend pre-decoded peaks for long files via the BBC `audiowaveform` C++ tool, which lets us push waveform pre-computation onto the Python layer.

### 1.2 Multitrack Timeline Libraries

| Library | License | Last activity | Style | Hierarchical | Virtualization | Verdict |
|---|---|---|---|---|---|---|
| **dnd-timeline** | MIT | v3.1.0 (early March 2026) | Headless React hooks on dnd-kit | via composition | TanStack Virtual example for 1000×1000 | **Best foundation** |
| **xzdarcy/react-timeline-editor** | MIT | v0.1.9 (early 2026) | Opinionated React | Limited (single-level) | Uses react-virtualized | Convenient demo; inflexible for ELAN tiers |
| **vis-timeline** | Apache-2.0 OR MIT | v8.5.0, Dec 12 2024 | Imperative DataSet | Group nesting (one-level) | Range filtering | Date-axis-centric; wrong feel for ms-precise media |
| **animation-timeline-control** | MIT | v2.4.5 (~2 yrs old) | Vanilla TS canvas | No | Canvas virtualization | Best for keyframe-style inset, not full body |
| **react-timeline-gantt** | MIT | Sporadic | React | Tasks | Yes | Date-axis-centric |
| **SVAR React Gantt** | MIT (PRO commercial) | v2.3 (2025) | React 19 + TS | Yes | Yes | Project-mgmt flavor; demo with 10K tasks |

**Recommendation: dnd-timeline + TanStack Virtual.** dnd-timeline is the only library that is explicitly headless, hook-based, and built on dnd-kit. Its README states: "🏎️ Performant: renders only when needed. All the intermediate states and animations are done using css transformations, and require 0 re-renders." Official examples include virtualization with `@tanstack/react-virtual` rendering 1000 items × 1000 rows smoothly.

### 1.3 Open-Source Web NLE Codebases to Study

| Codebase | License | Stars | Last activity | What to learn |
|---|---|---|---|---|
| **OpenCut-app/OpenCut** | MIT | ~46.2k | v0.1.0 release Feb 23 2026 | Project store layout in `apps/web/src`; Zustand patterns; OPFS + IndexedDB; WebCodecs + Rust-WASM rendering pipeline |
| **designcombo/react-video-editor** | **No license file** (Issue #29 open) | ~1.4k | Active, no tagged releases | Next.js 15 + Remotion + Radix/shadcn. **Do not fork; study only** |
| **ncounterspecialist/twick** | Sustainable Use License v1.0 | ~372 | v0.15.16, Jan 15 2026 | Excellent layered architecture: `@twick/timeline`, `@twick/canvas`, `@twick/live-player`, `@twick/browser-render` (WebCodecs + ffmpeg.wasm). License forbids redistributing as an SDK |
| **OpenTimelineIO/raven** | Apache-2.0 | ~132 | Aug 27 2025 | C++ + Dear ImGui OTIO viewer compiles to WASM via Emscripten |
| **Etro** (etro-js/etro) | GPL-3.0 | ~1.1k | Active | TS framework for programmatic editing; GPL-3.0 is non-starter for proprietary, study only |
| **Motionity** | MIT | ~4k | Sporadic | Web-based motion graphics editor; Fabric.js-based |
| **Olive Editor** (Qt, not web) | GPL-3.0 | ~8.9k | Active alpha | Reference for GPU-accelerated NLE interaction model |

### 1.4 Annotation-Specific UI Libraries

| Library | License | Reusability | Notes |
|---|---|---|---|
| **Annotorious v3** | BSD-3-Clause | High — framework-agnostic core + `@annotorious/react` | v3.4.0 May 27 2025; React 19 supported as of v3.1.0; W3C Web Annotation compliant |
| **Recogito (annotorious/recogito-js)** | BSD-3-Clause | High | Text annotation sibling |
| **Hypothesis client** | BSD-2-Clause | Moderate | Embeddable; shadow-DOM isolation; tightly coupled to Hypothesis API |
| **Label Studio Frontend** | Apache-2.0 | **Archived April 18 2024**; dev moved to `web/` workspace inside HumanSignal/label-studio | React + mobx-state-tree; XML-config-driven labeling templates |
| **CVAT (cvat-ui)** | MIT | Moderate — coupled to CVAT REST API | React + Redux + Ant Design; canvas via `cvat-canvas` |

The most important lesson from Label Studio is its declarative XML configuration: a labeling task is described by a `<View>` tree containing widgets like `<Image>`, `<RectangleLabels>`, `<Audio>`. Our equivalent: a Zod-schema plugin registry (Section 6.3).

### 1.5 DAW / MIDI / Piano-Roll Inspirations

Direct reuse is unrealistic — Ardour and LMMS are GPL-licensed Qt/native applications — but several patterns transfer:

- **Track header column with mute/solo/record-arm/lock**, vertical in a fixed-width gutter on the left. Ardour's vertical track header is the canonical layout that has appeared in every major NLE since the 1990s.
- **Ripple modes**: per Ardour, "Multiple ripple-modes make editing both simple two-mic episodes and tape-heavy features a breeze."
- **Snap with hold-to-disable**: every DAW lets you temporarily disable snap with a modifier.
- **Piano-roll-style point editing** for viseme/phoneme tracks.
- **Automation curves overlaid on tracks** for energy/confidence.

### 1.6 Animation Curve Editors

| Tool | License | Notes |
|---|---|---|
| **Theatre.js** | `@theatre/core` Apache-2.0; `@theatre/studio` AGPL-3.0 | Bifurcated license is intentional: ship core, use studio at design time |
| **Motion Canvas** | MIT | v3.18.0-alpha.0, Feb 16 2026; `ui` package is a clean Vite-served editor |
| **animation-timeline-control** | MIT | Useful as embedded curve-editor inset |
| **LottieFiles editor** | Closed | Format is open under Linux Foundation; editor is not |
| **Rive editor** | Closed; runtimes MIT | Not relevant |
| **Lottie Open Studio** | MIT | SVG-import + keyframe + bezier-easing reference |

**Study Theatre.js's split between property graph (durable model) and editor (ephemeral UI), with reactive bindings between them — a pattern this report adopts in Section 6.**

### 1.7 Generic Sequence / Gantt UIs (Pattern Inspiration)

| Tool | License | Patterns worth absorbing |
|---|---|---|
| **Bryntum** | Commercial (per-developer + OEM) | Hierarchical task rows with collapse; baseline-vs-actual overlay |
| **Frappe Gantt** | MIT | Lightweight SVG reference |
| **SVAR React Gantt** | MIT (PRO under separate license) | React 19; configurable scale units; demo with 10K tasks |
| **Syncfusion Gantt** | Commercial (community license available) | **Two-tier timeline header (top tier + bottom tier)** — exactly the right pattern |
| **dhtmlx Gantt** | GPL or commercial | Standard reference for very large task sets |
| **Mobiscroll Timeline** | Commercial | Excellent template-based progress rendering |

The single most useful pattern is the **two-tier timeline header**: top tier shows coarse units (minutes), bottom tier shows fine units (seconds), and zooming changes both consistently. Our editor needs at least three tiers because the zoom range is enormous.

### 1.8 Recommendation Matrix

| Capability | Decision | Library |
|---|---|---|
| Audio waveform + region UI | **Borrow** | Wavesurfer.js v7 |
| Multitrack timeline body | **Borrow + extend** | dnd-timeline + TanStack Virtual |
| Track header column | **Build** | shadcn/ui + Radix |
| Inspector / property panels | **Build (schema-driven)** | shadcn/ui + react-hook-form + Zod |
| Keyframe / curve editor inset | **Borrow** | animation-timeline-control |
| Image annotation (per-frame) | **Borrow** | Annotorious v3 |
| Video player | **Borrow → build** | HTML `<video>` → WebCodecs |
| Asset bin | **Build** | shadcn/ui Table + DnD |
| Cross-track linking | **Build** | Custom selectors over zustand |
| Plugin registry | **Build** | TypeScript + Zod |
| Undo/redo | **Borrow** | zundo (MIT) |
| OTIO interop | **Borrow / contribute** | OpenTimelineIO-JS-Bindings |
| State management | **Borrow** | zustand + immer |
| Schema | **Borrow** | Zod |

---

## 2. Interaction and Editing Patterns

Twenty years of NLE design have settled on an interaction vocabulary that users assume; violating it generates more friction than any new feature can offset.

### 2.1 Selection Models

Five canonical layers: single click, shift-click contiguous, Cmd/Ctrl-click toggle, marquee with modifier composition, range-time selection (FCP X's `R`). FCP X's Position tool (`P`) overrides the magnetic timeline so clips don't reflow during the next move — functionally a temporary global lock.

### 2.2 Edit Operations

The eight canonical operations and shortcuts:

| Operation | Premiere/Resolve | FCP X | Kdenlive |
|---|---|---|---|
| Ripple | (ripple trim tool) | Implicit in magnetic timeline | (resize tool) |
| Roll | Roll tool | `T` (Trim tool) | (resize neighbor) |
| Slip | Slip tool | (Trim variant) | (clip menu) |
| Slide | Slide tool | (drag with modifier) | (drag) |
| Razor / Blade | Razor / `Cmd-K` | `B` / `Cmd-B` | `S` (split) |
| Insert | `,` | `W` | (drag w/modifier) |
| Overwrite | `.` | `D` | (drag default) |
| Lift / Extract | `;` / `'` | (Delete / Shift-Delete) | (Delete / Shift-Delete) |

Three- and four-point editing (`I`/`O` for in/out, `Shift-I`/`Shift-O` for program in/out) is the highest-leverage editorial concept. Final Cut Pro's documentation describes the pattern explicitly: trim to skimmer with `Option-[` or `Option-]`.

For an annotation editor, only a subset matters: ripple (when adjusting a forced-aligned word boundary, downstream phonemes should ripple), razor (splitting a continuous interval), lift/extract (deleting an erroneous viseme).

### 2.3 Snap and Magnetism

Targets in priority order: playhead, in/out points, clip edges, markers, beat/grid. Two key choices:

- **Soft snap vs. hard snap**: NLEs universally use hard snap with a visible guide.
- **Magnetic timeline (FCP X)** vs. **classic linear (Premiere, Avid, Kdenlive)**: per FCP X docs, "Position tool... overrides the magnetic timeline. When you drag a clip, the clip doesn't spring back. Instead, a clip of black video, called a gap, is inserted between the end of the previous clip and the one you are moving."

**For an annotation editor, classic linear is the correct default**: annotations represent ground truth at specific times and should not reflow. But ripple-edit affordances are essential for cases where downstream annotations *do* need to shift — most importantly, when correcting forced-alignment offsets.

### 2.4 Trimming, Zoom, Playhead

- **Trim window** (Avid): two-up viewer with `<`/`>` for one frame, `Shift-<` / `Shift->` for ten frames.
- **J/L cuts**: the analog in our domain is a phoneme boundary leading or lagging its corresponding viseme.
- **Zoom**: mouse-wheel + Cmd around cursor; `+`/`-` around playhead; `Shift-Z` zoom-to-fit; mini-map with click-to-scroll. Linear scale only.
- **JKL transport** is universal (J reverse, K pause, L forward; double-tap for 2x; with K held, J/L scrub). Spacebar plays/pauses.

### 2.5 Marker Semantics: the Frame.io Pattern

Frame.io's documented features, ranked by what to copy:

- **Range comments**: drag a range on the playbar to attach to a duration; "Once the comment has been submitted, the range will be indicated with a green line on your timeline."
- **Threaded replies** with mark-as-complete.
- **Hashtag-tagged** searchable comments.
- **Anchored comments** attached to a specific (x, y) on the frame.
- **Internal vs. public** comments.
- **Comment markers in the NLE**: Frame.io's Premiere panel mirrors comments as timeline markers automatically when toggled on.

For an annotation editor, the lesson is that *markers are a first-class annotation type, not a sidebar feature*. Markers, range markers, chapter markers, and TODO/comment markers all live on a dedicated track and follow the same selection/editing/snapping rules.

### 2.6 Track Headers

Required affordances: type icon, editable name, mute/hide, solo, lock, arm, color swatch, height-resize handle, collapse triangle for hierarchical tier groups. Width must be globally controlled and shared across coordinated views.

### 2.7 Cross-Track Linking

This is where NLE and annotation traditions diverge most. NLEs don't formally model cross-track dependencies; they have *grouped* clips, not *derived* ones. ELAN's parent/child tier relationships are the right primitive. Visual conventions to borrow:

- **Color inheritance**: child tiers inherit parent's label color.
- **Boundary alignment guides**: when child boundary is constrained by parent, hover-highlight both.
- **Stereotype indicators** in track header.

### 2.8 Group Editing, Undo/Redo, Keyboard

- **Linked selection** (audio + video moving together) is the basic group primitive.
- **Compound clips** (FCP X) — nested timelines that act as a single clip — are the natural representation of *scenes*.
- **Command pattern** undo/redo: zustand integrates with `zundo` (MIT) for temporal middleware; 100 levels minimum; visible history panel; named action labels for devtools.
- **Bias toward non-modal shortcuts**: `Cmd-B` blade-at-playhead without entering blade mode is universally easier than modal tools.
- **`react-hotkeys-hook`** (MIT) registers shortcuts declaratively in React components.

---

## 3. Information Design and Visual Encoding

### 3.1 Many-Track Display

At 30 tracks, flat list is fine. At 100, virtualization is required (TanStack Virtual handles 1000 items × 1000 rows smoothly per the dnd-timeline virtualization example). At 1000, virtualization plus collapsible groups plus search/filter is required, and at that scale the user almost certainly wants to filter to a subset (a "layer of the day") rather than browse.

The **facet panel** pattern (filter by type, author, confidence, tag) is the right primary UI for thousand-track scales. TanStack Virtual provides rendering; a separate `selectedTracks` zustand selector returns the filtered set.

### 3.2 Hierarchical Tier Display: the ELAN Model

ELAN's four tier stereotypes (per the Max Planck Institute documentation):

- **Time Subdivision (TS)**: parent's interval subdivided on the time axis with no gaps. Example: sentence subdivided into words with explicit start/end.
- **Included In (II)**: like TS but gaps are allowed. Example: words within a sentence with silences between.
- **Symbolic Subdivision (SS)**: subdivided into named units NOT aligned to the time axis. Example: word subdivided into morphemes — ordered, no individual start/end.
- **Symbolic Association (SA)**: one-to-one correspondence with parent. Example: sentence and its free translation.

This translates directly to our domain: phonemes within a word = TS; words within an utterance with pauses = II; morphological tags = SS; speaker attribution = SA; visemes within a phoneme = TS (or SA if 1:1).

What's confusing in ELAN and should be avoided: the four stereotypes are presented without much guidance, leading to common mistakes (using SA when SS would be correct). Our editor should present a *guided creation flow* — "the new tier represents a refinement of an existing tier; pick the relationship type."

### 3.3 Heterogeneous Lane Content; Density vs. Clarity

Visual coherence requires consistent vertical metrics (every lane is a multiple of 24 px), a single shared horizontal time scale, per-lane content rendered in a clipped viewport, and consistent margin/padding.

For dense data: **never render more elements than there are pixels in the visible width.** Wavesurfer aggregates samples into peaks (min/max per bucket); flame graphs decimate to one bar per pixel; Datadog and Grafana use server-side LTTB or min/max bucketing.

### 3.4 Color, Alignment, Detail-on-Demand

A robust color system: 8–12 distinct hues for category (Okabe-Ito or IBM Design Library palettes are color-blind safe); a continuous lightness/alpha scale for confidence (NEVER red-to-green); avatars/initials for authorship. Use icons, dotted vs. solid borders, and shape redundancy in addition to color.

Hover an annotation → vertical guide line from start/end down to the bottom. Selected child annotation → subtle outline on parent. Drag boundary → snap guides labeled with their target ("snap to playhead", "snap to word boundary").

Inspector bound to selection by a single zustand selector. Hover popovers reserved for *non-edit* information.

### 3.5 Comments, Minimap, Onboarding

Treat comments as a built-in plugin: a `CommentAnnotationLayer` with all standard machinery plus an extra `Comment[]` thread property. The horizontal scrollbar should double as a minimap with a draggable viewport indicator and a "you are here" playhead. First-run onboarding shows three things in sequence: spacebar to play, drag to scrub, click to select.

---

## 4. Performance and Rendering Architecture

### 4.1 Canvas vs. SVG vs. DOM vs. WebGL

The breakeven analysis is well-documented. Per Evan Wallace (co-founder, Figma) in "Building a professional design tool on the web" (Figma Blog, December 7, 2015): they bypass HTML, SVG, and 2D canvas for their main rendering and use WebGL because "HTML and SVG contain a lot of baggage and are often much slower than the 2D canvas API due to DOM access. These are usually optimized for scrolling, not zooming, and geometry is often re-tessellated after every scale change." And: "we have our own DOM, our own compositor, our own text layout engine."

Pragmatic policy:

- **DOM (with React)** for chrome and sparse-content lanes (<500 visible items per lane).
- **Canvas** for dense-content lanes (waveforms, thumbnail strips, dense markers, curves). Wavesurfer.js v7 already does this internally.
- **WebGL (PixiJS)** as a fallback only when canvas isn't fast enough.

Start with DOM, switch a specific lane to canvas only when measurements show it's the bottleneck.

### 4.2 Virtualization

Three axes: track-list (vertical) — TanStack Virtual; item (horizontal) within visible window — interval tree on the time axis; combined 2D — render only `(track, item)` pairs in both ranges.

react-window is the older, smaller alternative; react-virtuoso has built-in dynamic-height handling. **TanStack Virtual is the right pick** because it is headless, framework-agnostic, and integrates with both dnd-timeline and arbitrary canvas overlays.

### 4.3 Frame-Accurate Scrubbing

Three tiers:

1. **Cheap**: HTML `<video>` with `requestAnimationFrame` driving `currentTime` — accept ~15 fps scrubbing precision.
2. **Medium**: pre-computed thumbnail strip displayed during scrub; only `currentTime`-seek when scrubbing pauses.
3. **Expensive**: WebCodecs decoding to a `VideoFrame` queue indexed by timestamp; render frames to canvas driven by the timeline clock.

Per Remotion docs: "WebCodecs is an API that exposes fast, optimized routines for multimedia and it is built directly into the browser - that's why it's not necessary to compile them with WebAssembly." ffmpeg.wasm is for *export* and unusual format support, not real-time decode.

The **sync problem between media and UI clocks**: during playback, media clock is source of truth; every animation frame, read `videoElement.currentTime` and update the timeline. During scrub, timeline clock is source of truth; the media element is commanded to seek.

### 4.4 Audio Waveform Pre-Rendering

For files <2 minutes, on-the-fly Web Audio decoding is fine. For longer, pre-computed peaks are essential — Wavesurfer's docs state "Since wavesurfer decodes audio entirely in the browser using Web Audio, large clips may fail to decode due to memory constraints. We recommend using pre-decoded peaks for large files." The BBC `audiowaveform` C++ tool is the standard producer; Python calls it as a subprocess; the resulting `.dat` is served alongside the audio.

### 4.5 Reactive State

zustand wins on selector ergonomics. Per Dominik Dorfmeister ("tkdodo"), "Working with Zustand" (tkdodo.eu, November 13, 2022): "While selectors are optional in Zustand, I think they should always be used... If you want to return an Object or Array from a selector, you can adjust the comparison function to use shallow comparison." This is exactly the discipline a timeline editor needs to avoid re-rendering 1000 tracks every time the playhead moves.

immer integration is the right default for nested mutations. **Where immer hurts**: hot-path mutations during drag (60 fps × many annotations) — bypass immer and write to a separate "ephemeral" store the timeline reads but the inspector doesn't.

### 4.6 Time Representation

Three options:

- **Float seconds**: simple; matches `<video>.currentTime`; floating-point drift over long durations.
- **Integer ticks (microseconds)**: no drift; cheap; safe.
- **Rational time (OTIO)**: drift-free for media-aware timelines; supports frame-rate conversion; more complex.

OTIO docs: "The RationalTime class represents a measure of time of `rt.value/rt.rate` seconds." Per OTIO Issue #190: "I had a timeline over a day long, and a couple of hours into the second day, a frame was lost, when using a double based time representation. This isn't because of insufficient resolution, it's because of frame snapping."

**Use integer microseconds at the UI layer**, with conversion to/from `RationalTime` at the serialization boundary. At 60 fps over 2 hours, microsecond ticks fit comfortably in JS `number` (safe integer up to 2⁵³).

---

## 5. Integration Concerns

### 5.1 Media Playback

For bounded local or pipeline-generated media, HTML `<video>` is the simplest start. For HLS/DASH, hls.js (Apache-2.0) or Shaka Player (Apache-2.0) wrap MSE. video.js (Apache-2.0) wraps both. react-player (MIT) is a thin React wrapper.

Multi-track audio mixing: the Web Audio API. One `<audio>` per source through `MediaElementAudioSourceNode` → `GainNode` → `AudioContext.destination`. Per-track mute/solo trivially implements as gain on the corresponding `GainNode`.

### 5.2 Asset Bin, Source/Program Monitor, Plugins, Server Sync

- Asset bin: shadcn/ui Table + DnD with hover-to-preview popover.
- Source/program: for v1, *one* viewer (program) is enough; add source monitor in v2 when three-point editing becomes frequent.
- Plugin extension: see Section 6.3.
- Server sync (frontend-facing): optimistic UI; conflict markers with side-by-side diff; presence indicators (Figma multiplayer style) are a luxury reserved for collaborative annotation.

### 5.3 Accessibility

The W3C ARIA Authoring Practices Guide treats grids as composite widgets where "some or all cells in the grid are focusable by using methods of two-dimensional navigation, such as directional arrow keys." For our timeline:

- `role="grid"` with `aria-rowcount` and `aria-colcount`.
- Each track row: `role="row"`; each annotation: `role="gridcell"`.
- Roving tabindex (one cell with `tabindex=0`, rest `-1`).
- Arrow keys move focus; Enter/Space activate.

Adrian Roselli's critique of ARIA Grid-as-anti-pattern is worth reading: the grid pattern is "useful for providing keyboard access to those contextual elements of the user interface" that appear on hover — exactly our hover-to-preview, hover-for-tooltip case.

For screen readers: announce timestamps as "1 minute 23 seconds and 12 frames" (not "00:01:23.12"). Announce annotation type and value on focus. Respect `prefers-reduced-motion`.

---

## 6. Reference Architecture

### 6.1 Component Decomposition

```
TimelineRoot                            (provides context + coordinate transforms)
├── ToolBar                              (Save, Undo, Redo, Tool selection)
├── ProgramMonitor                       (HTML <video> or WebCodecs canvas)
│   ├── PlaybackControls                 (JKL transport, scrub bar, time display)
│   └── OnFrameOverlay                   (anchored comments, bounding boxes, viseme preview)
├── TimelineSurface                      (the multitrack body)
│   ├── TimeRuler                        (two-tier header: minutes/seconds, with playhead)
│   ├── TrackHeaderColumn                (left gutter, virtualized vertically)
│   │   └── TrackHeader[]                (mute, solo, lock, hide, type icon, color, name)
│   ├── TrackContentSurface              (right pane, virtualized 2D)
│   │   └── Track[]                      (one per track, registered via plugin)
│   │       └── Lane[]                   (visual rows within a track)
│   │           └── Item[]               (annotations: clips, points, ranges, curves)
│   ├── PlayheadOverlay                  (vertical line + draggable handle, portal-rendered)
│   ├── SelectionOverlay                 (marquee rectangle, snap guides)
│   └── MinimapOverlay                   (bottom-edge compressed view)
├── InspectorPanel                       (bound to current selection via zustand selector)
│   └── SchemaForm                       (auto-generated from annotation Zod schema)
├── AssetBin                             (media library, drag-source for timeline)
└── StatusBar                            (selection summary, zoom level, time format toggle)
```

`TrackHeaderColumn` and `TrackContentSurface` share a single TanStack Virtual virtualizer keyed on track ID. `PlayheadOverlay` renders into a React portal layered above all tracks. `Item` rendering is delegated to the plugin's `Renderer` component.

### 6.2 State Decomposition

| Where | Lives | Examples |
|---|---|---|
| URL | Shareable | Project ID, zoom range, selected annotation ID |
| zustand `domainStore` | Durable | Tracks, annotations, plugin registrations |
| zustand `uiStore` | Ephemeral | Tool, hover, drag state, inspector tab |
| zustand `viewStore` | Per-view | Zoom level, scroll position, visible track list |
| React local state | Component-private | Form input drafts, popover open |
| Derived selectors | Computable | Annotations in visible range, snap targets |
| IndexedDB | Local cache | Pre-rendered waveform peaks, thumbnail cache |
| Server (Python) | Source of truth | Authoritative annotation set |

The boundary between *domain* (synced to backend) and *UI ephemeral* (never synced) is the most important architectural line. Drag-in-progress, hover, and selection are UI; the result of a drag is domain. The domain store mutates only at the *end* of a drag, not during it.

### 6.3 Plugin Interface (TypeScript Skeleton)

```ts
import { z } from 'zod';
import type { ComponentType } from 'react';

const TimePoint = z.object({ us: z.number().int().nonnegative() }); // microseconds
const TimeInterval = z.object({ start: TimePoint, end: TimePoint });
type TimeInterval = z.infer<typeof TimeInterval>;

const AnnotationBase = z.object({
  id: z.string().uuid(),
  trackId: z.string(),
  range: TimeInterval,
  refs: z.array(z.string().uuid()).default([]),
  authoredBy: z.union([
    z.object({ kind: z.literal('human'), userId: z.string() }),
    z.object({ kind: z.literal('agent'), modelId: z.string(),
               confidence: z.number().min(0).max(1) }),
    z.object({ kind: z.literal('derived'), upstream: z.array(z.string().uuid()) }),
  ]),
});

export interface AnnotationLayerSpec<T> {
  readonly typeId: string;
  readonly displayName: string;
  readonly schema: z.ZodType<T>;
  readonly stereotype?: 'TimeSubdivision' | 'IncludedIn'
                      | 'SymbolicSubdivision' | 'SymbolicAssociation';
  readonly Renderer: ComponentType<{ annotation: T; pxPerSecond: number }>;
  readonly Inspector?: ComponentType<{ annotation: T; onChange: (a: T) => void }>;
  readonly handlers?: {
    onCreate?: (range: TimeInterval, ctx: PluginContext) => T;
    onResize?: (a: T, newRange: TimeInterval, ctx: PluginContext) => T;
    onMove?: (a: T, delta: number, ctx: PluginContext) => T;
    onDelete?: (a: T, ctx: PluginContext) => void;
  };
  readonly validators?: Array<(a: T, all: ReadonlyArray<unknown>) => string | null>;
  readonly snapTargets?: (a: T) => number[];
}

const registry = new Map<string, AnnotationLayerSpec<any>>();
export function registerLayer<T>(spec: AnnotationLayerSpec<T>) {
  registry.set(spec.typeId, spec);
}
```

The Inspector defaults to a generated form derived from the Zod schema (using `@hookform/resolvers/zod` + `react-hook-form` + a small schema-walker that emits shadcn/ui form fields). This is the same idea as Label Studio's XML labeling templates, expressed in TypeScript.

### 6.4 Cross-Track Linking

Refs stored as UUIDs in `refs`. The store provides selectors:

```ts
const useResolvedRefs = (annotationId: string) =>
  useTimelineStore(useShallow((state) => {
    const a = state.annotationsById[annotationId];
    return a.refs.map((id) => state.annotationsById[id]);
  }));
```

Selecting an annotation shows refs as clickable links in the inspector; hovering highlights refs in their respective tracks.

### 6.5 Two Coordinated Views

```
┌──────────────────────────────────────────┐
│             ProgramMonitor               │
├──────────────────────────────────────────┤
│  TimeRuler                               │
├─────────┬────────────────────────────────┤
│  NLE    │  NLE timeline body             │
│ headers │  (large, media-aware)          │
├─────────┼────────────────────────────────┤
│  Tier   │  Tier timeline body            │
│ headers │  (compact, ELAN-style)         │
└─────────┴────────────────────────────────┘
```

Both bodies share the same time axis, playhead, selection, and plugin registry. NLE view shows curated tracks (media, dialogue, music) at large heights with media-aware rendering. Tier view shows everything (including derived/computed) at compact heights with ELAN hierarchy. Hover an annotation in NLE → parent tier highlights in Tier; vice versa.

This is the single most important architectural decision in this report. It resolves the NLE-vs-annotation tension by refusing to choose: the underlying model is unified (a stack of tracks with possibly hierarchical relationships and items), but the views are specialized.

---

## 7. Risk Register: Top Five Traps

1. **Drift in time representation.** Float seconds drift; frame snapping with floats compounds drift. Use integer microseconds at the model layer; convert at the I/O boundary only.

2. **Re-rendering everything on playhead motion.** Naive React + zustand re-renders every annotation every frame. Mitigation: keep playhead in a separate store with imperative subscribers (`useStore.subscribe`), not React renders; render via portal that bypasses the timeline tree; use `useShallow` on every selector returning array/object.

3. **License contamination.** Etro is GPL-3.0; @theatre/studio is AGPL-3.0; audioMotion-analyzer is AGPL-3.0. Use them only at design-time or in clearly-isolated build contexts. Wavesurfer (BSD-3-Clause), dnd-timeline (MIT), TanStack Virtual (MIT), zustand (MIT), zod (MIT), shadcn/ui (MIT), Annotorious v3 (BSD-3-Clause), Theatre.js core (Apache-2.0) form a clean permissive bundle.

4. **Building too much, too early.** Ship the minimum useful editor (audio waveform + dialogue tier + viseme tier + program monitor + inspector) first; everything else slots in via the plugin registry.

5. **Coupling state to React.** Domain logic in components or React-only hooks makes state untestable and unportable. Keep domain logic in plain TypeScript; React is *just* the renderer; zustand's `getState()` works outside React.

---

## 8. Stretch Topics

### 8.1 Weekend Prototype

Vite + React + TS; Wavesurfer.js v7; dnd-timeline + TanStack Virtual; shadcn/ui; zustand + immer + zod; HTML `<video>`; `react-hotkeys-hook`. Goal: load video, load transcript, see audio waveform aligned with word annotations, click a word to seek, drag to adjust boundaries.

### 8.2 Figma's Multiplayer Model on a Timeline

Cursors → playheads in user color. Selections → outlined annotations in user color. Edit conflicts: harder. CRDTs for ordered sequences (Yjs's `Y.Array`) work; interval edits with constraints (a child can't extend past its parent) need custom merging. Frame.io's approach — comments append-only, edits are explicit version stacks — is more pragmatic for v1. Render presence cursors via portals; keep them in a `presenceStore` separate from domain and undo stack.

### 8.3 Emerging Standards

- **OTIO web viewer**: OpenTimelineIO/raven (Apache-2.0) compiles to WASM via Emscripten. OpenTimelineIO-JS-Bindings provides experimental Emscripten bindings — partial coverage as of early 2026.
- **Web Animations API**: stable; useful for chrome animations, not for timeline scrub-driven playback.
- **WebCodecs**: stable in Chromium; Safari support improved through 2025; the right answer for frame-accurate decode/encode in the browser.
- **WebGPU**: relevant only when WebGL is the bottleneck.

### 8.4 AI-Native Annotation UX

Agent-generated annotations differ from human-authored in three ways the UI must surface:

- **Provenance**: every annotation carries an `authoredBy` field distinguishing human, agent, derived. Agent annotations rendered with subtle "AI" badge.
- **Confidence**: agent annotations have a 0..1 score visualized as alpha/stripe density. Below threshold (~0.7), dashed border + "needs review" badge.
- **Accept/reject flow**: queue panel lists low-confidence agent annotations. Accept (promotes to human-authored), reject (deletes), or edit (becomes human-authored on first edit).

The plugin interface accommodates this naturally: the `AnnotationBase.authoredBy` discriminated union is part of every annotation; renderers can branch on it.

---

## References

[1] [wavesurfer.js — GitHub repository](https://github.com/katspaugh/wavesurfer.js) — License: BSD-3-Clause — Last release: v7.12.4, March 16 2026.
[2] [wavesurfer.js documentation](https://wavesurfer.xyz/docs/) — License: BSD-3-Clause — Last updated: 2026.
[3] [Peaks.js — GitHub repository](https://github.com/bbc/peaks.js) — License: LGPL-3.0 — Last release: v4.0.0-beta.2, May 13 2025.
[4] [audioMotion-analyzer — GitHub repository](https://github.com/hvianna/audioMotion-analyzer) — License: AGPL-3.0-or-later — Last release: v4.5.4 / v5.0.0-alpha.1.
[5] [vis-timeline — GitHub repository](https://github.com/visjs/vis-timeline) — License: Apache-2.0 OR MIT — Last release: v8.5.0, December 12 2024.
[6] [dnd-timeline — GitHub repository](https://github.com/samuelarbibe/dnd-timeline) — License: MIT — Last release: dnd-timeline@3.1.0, March 2026.
[7] [@xzdarcy/react-timeline-editor — GitHub repository](https://github.com/xzdarcy/react-timeline-editor) — License: MIT — Last release: v0.1.9 (early 2026).
[8] [animation-timeline-control — GitHub repository](https://github.com/ievgennaida/animation-timeline-control) — License: MIT — Last npm publish: v2.4.5.
[9] [Theatre.js — GitHub repository](https://github.com/theatre-js/theatre) — License: core Apache-2.0; studio AGPL-3.0.
[10] [Motion Canvas — GitHub repository](https://github.com/motion-canvas/motion-canvas) — License: MIT — Last release: v3.18.0-alpha.0, February 16 2026.
[11] [Remotion](https://www.remotion.dev/) — License: Remotion source-available; commercial license for companies of 4+.
[12] [Etro — GitHub repository](https://github.com/etro-js/etro) — License: GPL-3.0.
[13] [Motionity — GitHub repository](https://github.com/alyssaxuu/motionity) — License: MIT — ~4k stars.
[14] [OpenCut — GitHub repository](https://github.com/OpenCut-app/OpenCut) — License: MIT — Last release: v0.1.0, February 23 2026.
[15] [designcombo/react-video-editor — GitHub repository](https://github.com/designcombo/react-video-editor) — License: not specified (Issue #29 open).
[16] [twick — GitHub repository](https://github.com/ncounterspecialist/twick) — License: Sustainable Use License v1.0 — Last release: v0.15.16, January 15 2026.
[17] [Annotorious v3 — GitHub repository](https://github.com/annotorious/annotorious) — License: BSD-3-Clause — Last release: v3.4.0, May 27 2025.
[18] [Hypothesis client — GitHub repository](https://github.com/hypothesis/client) — License: BSD-2-Clause.
[19] [Label Studio Frontend (archived)](https://github.com/HumanSignal/label-studio-frontend) — License: Apache-2.0 — Status: archived April 18 2024.
[20] [Label Studio — GitHub repository](https://github.com/HumanSignal/label-studio) — License: Apache-2.0.
[21] [CVAT — GitHub repository](https://github.com/cvat-ai/cvat) — License: MIT.
[22] [OpenTimelineIO — GitHub repository](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) — License: Apache-2.0 — Last release: v0.18.1, November 9 2025.
[23] [OpenTimelineIO RationalTime documentation](https://opentimelineio.readthedocs.io/en/latest/api/python/opentimelineio.opentime.html) — License: Apache-2.0.
[24] [OpenTimelineIO Issue #190: Rate should be int/int not float](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/issues/190) — License: Apache-2.0.
[25] [OpenTimelineIO/raven — GitHub repository](https://github.com/OpenTimelineIO/raven) — License: Apache-2.0 — Last activity: August 27 2025.
[26] [OpenTimelineIO-JS-Bindings — GitHub repository](https://github.com/JeanChristopheMorinPerso/OpenTimelineIO-JS-Bindings) — License: not specified.
[27] [zustand — GitHub repository](https://github.com/pmndrs/zustand) — License: MIT.
[28] [TanStack Virtual](https://tanstack.com/virtual/latest) — License: MIT.
[29] [Working with Zustand by Dominik Dorfmeister (tkdodo)](https://tkdodo.eu/blog/working-with-zustand) — Published November 13, 2022.
[30] [Final Cut Pro keyboard shortcuts — Apple Support](https://support.apple.com/guide/final-cut-pro/keyboard-shortcuts-ver90ba5929/mac).
[31] [The Final Cut Pro Timeline: Magnetic, Chaotic, and Totally Useful — MotionVFX](https://www.motionvfx.com/know-how/final-cut-pro-magnetic-timeline/).
[32] [Edit at the Speed of Thought With These Final Cut Pro Shortcuts — Frame.io blog](https://blog.frame.io/2018/09/17/fcpx-final-cut-pro-shortcuts/).
[33] [ELAN Tier documentation — Max Planck Institute](https://www.mpi.nl/corpus/html/elan/ch06s03s04.html).
[34] [ELAN Annotations chapter — Max Planck Institute](https://www.mpi.nl/corpus/html/elan/ch02.html).
[35] [Frame.io Commenting (V4)](https://help.frame.io/en/articles/9105251-commenting-on-your-media).
[36] [Frame.io Comments Panel Overview (V4)](https://help.frame.io/en/articles/9105278-comments-panel-overview).
[37] [Building a professional design tool on the web — Evan Wallace, Figma Blog (December 7, 2015)](https://www.figma.com/blog/building-a-professional-design-tool-on-the-web/).
[38] [Keeping Figma Fast — Figma Blog](https://www.figma.com/blog/keeping-figma-fast/).
[39] [SVG vs Canvas — JointJS](https://www.jointjs.com/blog/svg-versus-canvas).
[40] [ARIA: grid role — MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Roles/grid_role).
[41] [Grid pattern — W3C ARIA APG](https://www.w3.org/WAI/ARIA/apg/patterns/grid/).
[42] [Developing a Keyboard Interface — W3C ARIA APG](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/).
[43] [ARIA Grid As an Anti-Pattern — Adrian Roselli](https://adrianroselli.com/2020/07/aria-grid-as-an-anti-pattern.html).
[44] [Clearing up WebCodecs misconceptions — Remotion docs](https://www.remotion.dev/docs/webcodecs/misconceptions).
[45] [ffmpeg.wasm — GitHub repository](https://github.com/ffmpegwasm/ffmpeg.wasm) — License: wrapper MIT; FFmpeg core LGPL/GPL.
[46] [Bryntum License page](https://bryntum.com/products/license/) — License: commercial.
[47] [SVAR React Gantt v2.3 — DEV Community](https://dev.to/olga_tash/svar-react-gantt-v23-modern-project-timelines-for-react-19-e7f).
[48] [Lottie Animation Community](https://lottie.github.io/) — open standard hosted by The Linux Foundation.
[49] [Ardour](https://ardour.org/) — License: GPL-2.0+.
[50] [zundo — temporal middleware for zustand](https://github.com/charkour/zundo) — License: MIT.
[51] [react-hotkeys-hook](https://github.com/JohannesKlauss/react-hotkeys-hook) — License: MIT.
[52] [PixiJS](https://pixijs.com/) — License: MIT.
[53] [Olive Editor — GitHub repository](https://github.com/olive-editor/olive) — License: GPL-3.0 — ~8.9k stars.