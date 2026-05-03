# Annotation systems: formats, algorithms, architectures, and tooling

**Every annotation is a `(reference, metadata)` pair.** This deceptively simple formulation underpins systems as diverse as linguistic corpus annotation, ML data labeling, audio diarization, video editing timelines, and animation authoring. This report provides an architect's survey of the annotation landscape across two primary use cases — time-based/sequence-based data annotation and structured animation — while covering the cross-cutting concerns of formats, data structures, algorithms, design patterns, and tooling in Python and JavaScript/TypeScript. The goal is to inform the design of composable, interval-centric annotation systems built on standoff architecture, Mapping interfaces, and DAG-based pipelines.

The field converges on a few deep principles: standoff separation of annotations from data, interval-based temporal references, graph-structured annotation models, and adapter-based I/O for format interoperability. Where the two use cases diverge is in their relationship to time — sequence annotation deals in absolute time (seconds, samples, frames), while animation annotation deals in relative time (durations, ordering, containment). Allen's Interval Algebra bridges both worlds.

---

## A. Formal models and standards anchor the entire field

### W3C Web Annotation Data Model

The W3C Web Annotation Data Model [1], a W3C Recommendation since February 2017, is the closest thing to a universal annotation standard. It defines an Annotation as a connection between a **Body** (the annotation content) and a **Target** (the annotated resource), serialized as JSON-LD. The model is inherently standoff — annotations live separately from documents and are reunited at render time.

The target selection vocabulary is rich. Nine selector types address different media: **TextQuoteSelector** (exact text plus surrounding context for resilient anchoring), **TextPositionSelector** (character offsets), **FragmentSelector** (wraps Media Fragment URIs like `#t=10,20` for audio/video time ranges), **CssSelector** and **XPathSelector** (DOM elements), **DataPositionSelector** (byte ranges for binary data), **SvgSelector** (SVG shapes overlaid on resources), **RangeSelector** (spans between two selectors), and selector **refinement chains** via `refinedBy`. The **13 motivation types** (bookmarking, classifying, commenting, describing, editing, highlighting, identifying, linking, moderating, questioning, replying, tagging, assessing) form an extensible vocabulary. The companion Web Annotation Protocol provides RESTful CRUD based on Linked Data Platform.

For time-based annotation, FragmentSelector with Media Fragments (`#t=start,end`) handles audio/video ranges. For animation, CssSelector and SvgSelector can target animated elements. The model's limitation is that it lacks native temporal reasoning — it can *describe* time ranges but cannot express Allen's relations between annotations. Adoption is strong: Hypothes.is, Annotorious, and the entire IIIF (International Image Interoperability Framework) ecosystem use Web Annotation natively [2].

### Annotation Graphs and LAF/GrAF

Bird and Liberman's **Annotation Graph** formalism [3] (2001) provides the foundational theoretical model. An AG is a labeled, directed acyclic graph over a timeline: **nodes are time points** (optionally anchored to absolute timestamps), and **arcs are labeled intervals** carrying typed key-value records. Multiple annotation tiers are simply different arc types sharing the same node set. This model handles overlapping annotations, multi-tier hierarchies, and partial temporal ordering naturally.

The ISO **Linguistic Annotation Framework** (LAF, ISO 24612) [4] operationalized these ideas into a three-layer architecture: user annotation format → pivot format (GrAF, a graph-based XML interchange) → standardized data categories. GrAF extends AGs with **feature structures** (typed attribute-value matrices conforming to ISO 24610) attached to graph nodes and edges, plus a standoff mechanism where segmentation and annotation layers are stored in separate files. The MASC corpus and LAF-Fabric tool demonstrate practical use at scale.

For the animation use case, the AG model maps cleanly: keyframes become time-anchored nodes, interpolation segments become arcs labeled with easing functions and property values, and multiple animation tracks become distinct arc types.

### Apache UIMA CAS

Apache UIMA's Common Analysis System [5] brings enterprise-grade type system engineering to annotation. Its single-inheritance type hierarchy (rooted at `uima.cas.TOP`) with feature structures enables rich annotation modeling. The built-in `Annotation` type uses `begin`/`end` integer offsets, and the **Subject of Analysis (SofA)** concept allows multiple "views" of the same data (e.g., original text, detagged HTML, audio, translation) within a single CAS. Annotation indexes provide sorted access (by begin ascending, end descending, type priority). The Python bridge `dkpro-cassis` (Apache-2.0) enables pure-Python CAS manipulation with XMI and JSON serialization. UIMA's strength is its **pipeline architecture** — analysis engines chain together, each adding annotations to the shared CAS. Its weakness is Java-centricity and complexity for simple use cases.

### Allen's Interval Algebra

Allen's 13 temporal relations [6] — **before, after, meets, met-by, overlaps, overlapped-by, starts, started-by, during, contains, finishes, finished-by, equals** — form a complete, mutually exclusive, jointly exhaustive qualitative calculus over intervals. The **composition table** (13×13 = 169 entries) enables constraint propagation: given `a(r₁)b` and `b(r₂)c`, the possible relations between `a` and `c` can be computed. Path consistency runs in **O(n³)** per iteration. General satisfiability is NP-complete, but the **ORD-Horn** tractable subalgebra (which contains all 13 basic relations) admits sound and complete path consistency.

For time-based annotation, Allen's algebra formalizes queries like "find all annotations that *overlap* this segment" or "annotations that *start during* this other annotation." For animation, it describes timing constraints: a fade-in *meets* a hold, which *meets* a fade-out; a sound effect plays *during* a visual transition. Python implementations include `qualreas` (JSON-defined algebras), `pyintervals`, and `QSRlib` [7].

---

## B. Domain-specific formats span audio, text, vision, and animation

### Audio and music annotation formats

**JAMS** (JSON Annotated Music Specification, ISC license) [8] provides a clean JSON schema for music annotations. Each JAMS file contains `file_metadata`, a `sandbox` for arbitrary data, and an `annotations` array where each Annotation has a `namespace` (beat, chord, key, melody, onset, pitch, segment, tag, tempo), `annotation_metadata` (curator, data source, version), and a `data` array of Observations — each an `(time, duration, value, confidence)` tuple. JAMS natively supports **multi-annotator** data through multiple Annotation objects sharing a namespace.

**Praat TextGrid** [9] is the workhorse of phonetics. A TextGrid contains ordered tiers — **IntervalTiers** (contiguous, non-overlapping intervals covering the full time domain, each with `xmin`, `xmax`, `text`) and **PointTiers** (isolated time points with labels). The key constraint: IntervalTier intervals are **adjacency-complete** — every moment belongs to exactly one interval, forcing explicit empty intervals. This simplifies many queries but limits expressiveness.

**ELAN EAF** (XML) [10] from the Max Planck Institute is the richest linguistic annotation format. Its distinctive feature is the **TIME_ORDER** — a global pool of TIME_SLOT elements (millisecond resolution) referenced by annotations via `TIME_SLOT_REF1`/`REF2`. Tiers form parent-child hierarchies constrained by five **stereotypes**: None (independent), Time Subdivision (contiguous subdivisions of parent), Included In (within parent with gaps), Symbolic Subdivision (ordered units without timing), and Symbolic Association (1:1 with parent). This enables annotations like utterance → words → morphemes with formally enforced structural integrity.

### Subtitle and caption formats

**SubRip (.srt)** is the simplest: sequential numbered blocks with `HH:MM:SS,mmm --> HH:MM:SS,mmm` timestamps and plain text. No formal specification exists, but near-universal tool support makes it the lowest common denominator. **WebVTT** (W3C) [11] extends this with CSS styling via `::cue`, named regions for spatial positioning, voice tags (`<v Speaker>`), and karaoke timestamps. **TTML** (W3C Recommendation) [12] is the XML heavyweight — used by Netflix, broadcast TV, and MPEG CMAF — with parallel/sequential time containers, rich styling, and profile variants (IMSC1, EBU-TT-D, SMPTE-TT).

### NLP annotation formats

**brat standoff** [13] uses paired `.txt`/`.ann` files. The `.ann` format is elegant: `T1\tPerson 0 5\tJapan` (text-bound entity with character offsets), `R1\tLocated Arg1:T1 Arg2:T2` (relation), `E1\tAttack:T3 Target:T1` (event), `A1\tNegation T1` (attribute), plus normalizations and equivalences. It supports discontinuous spans via semicolon-separated offset pairs.

**CoNLL-U** [14] is the tab-separated columnar format underlying Universal Dependencies (200+ treebanks, 100+ languages): ID, FORM, LEMMA, UPOS, XPOS, FEATS, HEAD, DEPREL, DEPS, MISC. **IOB/BIO tagging** encodes span annotations as token-level labels: the dominant BIO (IOB2) scheme uses `B-TYPE` at span start, `I-TYPE` for continuation, and `O` outside. The BILOU/IOBES variant adds `L`-ast and `U`-nit tags, yielding better boundary precision in some studies [15].

**Hugging Face Datasets** [16] uses `ClassLabel` (integer-encoded with name mapping), `Sequence(ClassLabel(...))` for token-level annotations, and Apache Arrow backing for efficient storage. This is the de facto ML consumption format.

### Computer vision annotation formats

**Label Studio** [17] stores annotations as JSON with `data` (source reference), `annotations` (human labels), and `predictions` (model outputs). Each result has `from_name`/`to_name` linking control tags to data tags — a polymorphic pattern supporting text, image, audio, video, and time series. **CVAT** [18] uses XML with `<image>` elements containing `<box>`, `<polygon>`, `<polyline>` etc., and `<track>` elements for video with keyframe interpolation attributes (`outside`, `occluded`, `keyframe`). **VIA** (VGG Image Annotator, BSD-2) [19] uses JSON keyed by `filename+size` with region shapes and user-defined attributes; VIA 3.x extends to audio/video temporal segments.

### Lottie animation format

**Lottie** [20] is a JSON schema for vector animation exported from After Effects via the Bodymovin plugin. The top-level object defines `fr` (frame rate), `ip`/`op` (in/out points), `w`/`h` (dimensions), `assets` (precompositions, images), and `layers`. Layer types include Shape (4), Solid (1), Image (2), Null (3), Precomp (0), and Text (5). Each layer carries transform properties (anchor, position, scale, rotation, opacity) that can be **static or animated**.

Animated properties use keyframe arrays where each keyframe has `t` (frame), `s` (start value), and Bezier easing handles `o`/`i` (outgoing/incoming tangents with x=time, y=value). Hold keyframes use `h: 1`. This keyframe model — value + timing + interpolation per property — is the canonical animation annotation pattern. Lottie's compact JSON (typically 2–20KB) and cross-platform renderers (lottie-web, lottie-ios, lottie-android) make it the dominant web animation interchange format.

---

## C. Design patterns for annotation system architecture

### Standoff annotation and the interval tree core

**Standoff annotation** — storing annotations separately from source data, referencing via offsets — is the architectural foundation. Every system examined uses it: brat (character offsets), ELAN (time slot references), W3C Web Annotation (URI + selectors), Praat (time ranges). The advantages are clear: overlapping annotations become trivial, multiple annotators work independently, and source data remains immutable. The primary challenge is **offset invalidation** when source data changes. W3C Web Annotation addresses this with multiple fallback selectors (quote + position + range); STAM (Stand-off Text Annotation Model) adds text validation extensions [21].

The **interval tree** is the essential data structure. A balanced BST augmented with maximum endpoint values in each subtree, it answers the fundamental query — "find all annotations overlapping `[t1, t2]`" — in **O(log n + k)** time. The Python `intervaltree` library (Apache-2.0) [22] provides a clean API: `tree[point]` for stabbing queries, `tree[begin:end]` for overlap queries, plus `merge_overlaps()`, `chop()`, and `slice()`. For multi-dimensional indexing (channel × time), **R-trees** (via the `rtree` library wrapping `libspatialindex`) handle queries like "find annotations by Speaker A between 10s and 30s."

**Segment trees** complement interval trees for different query patterns: they excel at aggregate queries over fixed ranges (count overlapping annotations at each point, sum values) with **lazy propagation** for efficient range updates. Use interval trees for "which annotations overlap this range?" and segment trees for "how many annotations exist at each millisecond in this range?"

### Multi-tier architecture and the Mapping interface

Multi-tier architectures organize annotations into parallel layers sharing a timeline. ELAN's five stereotypes enforce structural invariants between parent and child tiers. Praat uses independent flat tiers. The general pattern: each tier is an independent annotation collection backed by its own interval tree, with optional cross-tier constraints.

The **Mapping/MutableMapping interface** is the Pythonic API surface for interval annotation stores. The `portion` library's `IntervalDict` maps intervals to values:

```python
import portion as P
store = P.IntervalDict()
store[P.closed(0.0, 2.5)] = {"label": "speech", "speaker": "A"}
store[1.5]  # → {"label": "speech", "speaker": "A"}
```

This directly implements the `(reference, metadata)` pair pattern where keys are intervals and values are annotation data. A caveat: `IntervalDict` enforces **disjoint keys** (overlapping assignments overwrite), so for overlapping annotations, `intervaltree` (which supports overlaps natively but doesn't implement MutableMapping) is more appropriate. Bridging these — a MutableMapping backed by an interval tree — is a natural design target [23].

### Collaboration, undo/redo, and schema evolution

**CRDTs** (Conflict-free Replicated Data Types) enable offline-first collaborative annotation. **Yjs** (MIT, JavaScript) uses the YATA CRDT with shared types (Y.Map, Y.Array, Y.Text) and bindings for major editors. **Automerge** (MIT, Rust+JS) uses RGA with columnar encoding. For annotation collections, OR-Set handles concurrent add/remove; for sequential annotation data, RGA/YATA handle concurrent insertions. The key challenge is representing concurrent interval boundary modifications, which requires custom CRDT semantics beyond what standard libraries provide [24].

**Undo/redo** is best served by the **Command pattern** for annotation systems (each operation encapsulated with `execute()`/`undo()` methods). For provenance-critical systems, **event sourcing** stores all changes as an immutable log — current state is derived by replaying events from the last snapshot. This naturally provides audit trails answering "who moved this boundary, when, and why?"

**Schema evolution** requires versioned annotation schemas, default values for new fields, additive-only changes as a default policy, and migration strategies (eager, lazy, or view-based). The W3C PROV model [25] provides formal provenance vocabulary (`wasGeneratedBy`, `wasAttributedTo`, `wasDerivedFrom`), while the PAV ontology adds practical terms like `pav:authoredBy` and `pav:version`.

### Plugin/adapter I/O and observer patterns

The **adapter pattern** handles multi-format I/O — each format (brat, ELAN, TextGrid, WebVTT, JAMS) gets a reader/writer implementing a common `Protocol` interface. Label Studio demonstrates this at scale with `label-studio-converter` mapping its internal JSON to COCO, VOC, YOLO, CoNLL, and more. OpenTimelineIO's adapter system is the gold standard: a plugin architecture where each adapter reads/writes a specific format (CMX 3600 EDL, FCP XML, AAF) into a shared core model.

**Observer/pub-sub** patterns propagate annotation changes (create, modify, delete) to UI renderers, persistence layers, derived annotation engines, and validation systems. Event-driven architectures using reactive patterns (RxPY in Python, signals in JS frameworks) enable clean separation between annotation model and consumers.

---

## D. Algorithms for temporal annotation

### Change-point detection and segmentation

**PELT** (Pruned Exact Linear Time) [26] achieves globally optimal segmentation with O(n) average complexity via a dynamic programming pruning rule. The Python `ruptures` library provides PELT, Binary Segmentation, Bottom-Up, and Window-based algorithms with cost functions (L1, L2, RBF, AR). These produce automatic **pre-annotations** — suggested segment boundaries for human review. Studies show pre-annotation can make annotation **10× more efficient** when combined with active learning [27].

### Inter-annotator agreement

**Cohen's kappa** (pairwise, two annotators) and **Krippendorff's alpha** (multiple annotators, handles missing data, multiple data types including interval) are the standard metrics. For temporal/interval annotations, specialized measures include **boundary agreement** with collar tolerance (e.g., ±250ms), **IoU** (Intersection over Union), and **Diarization Error Rate** (DER = false alarm + missed detection + speaker confusion). The `pyannote.metrics` library [28] provides DER, JER (Jaccard Error Rate, which weights speakers equally), and detailed error analysis. Threshold guidance: **α > 0.8** is reliable, **0.67–0.8** is tentative, **< 0.67** warrants discarding or revising guidelines [29].

### Active learning and annotation merging

**Uncertainty sampling** selects examples where model confidence is lowest (least confidence, margin, or entropy). Prodigy's `textcat.teach` implements this with a model-in-the-loop that updates during annotation. Studies show uncertainty sampling can require only **20% of labels** compared to random sampling for equivalent accuracy [30].

For merging multi-annotator data, **majority voting** is simplest but ignores annotator reliability. The **Dawid-Skene model** [31] assigns each annotator a confusion matrix estimated via EM, consistently outperforming majority voting. **MACE** [32] (Multi-Annotator Competence Estimation) uses variational inference to model annotator competence. For interval annotations, combining Dawid-Skene with HMM-based sequence modeling (HMM-Crowd) handles both annotator reliability and sequential structure.

### Forced alignment

Forced alignment maps transcripts to audio via acoustic models + Viterbi decoding, producing time-aligned annotations at word and phoneme level. **Montreal Forced Aligner** (MFA, MIT license) [33] is the state of the art: Kaldi-based GMM-HMM with pretrained models for dozens of languages, outputting Praat TextGrids with **~25.8ms mean absolute error** at word level. **NeMo Forced Aligner** (Apache-2.0, NVIDIA) uses CTC-based alignment for 14+ languages.

---

## E. Python libraries for annotation systems

### Interval and temporal data structures

| Library | License | Key Feature | Best For |
|---------|---------|-------------|----------|
| `pandas` IntervalIndex | BSD-3 | `pd.Interval`, `IntervalIndex.overlaps()`, `pd.cut()` | Tabular annotation data with interval indices |
| `portion` | **LGPLv3** ⚠️ | `IntervalDict`, set operations (∪, ∩, complement) | Interval arithmetic, dict-like annotation stores |
| `intervaltree` | Apache-2.0 | Balanced BST, O(log n + k) queries, `merge_overlaps()` | Overlapping interval queries, temporal annotation indexing |

The `portion` library provides the richest interval arithmetic (atomic intervals, automatic simplification, `IntervalDict` with `combine()` for merging) but carries an **LGPLv3** license — acceptable for most uses but requires awareness of copyleft obligations. The `intervaltree` library (Apache-2.0) is the preferred choice for systems requiring overlapping interval support.

### Audio, music, and speech annotation

**pyannote.core** (MIT) [34] provides the most annotation-native data model: `Segment(start, end)` with intersection/union/gap operations, `Timeline` (ordered set of segments), and `Annotation` mapping `(segment, track_name) → label`. It supports direct Jupyter visualization and is the core of the pyannote speaker diarization ecosystem.

**jams** (ISC) provides the JAMS Python API with namespace validation, temporal slicing (`Annotation.trim()`), and mir_eval integration. **mir_eval** (MIT) [35] provides transparent evaluation metrics for onset detection, beat tracking, chord estimation, segment boundary detection, and more — all interval-based.

**pympi** (MIT) handles ELAN EAF and Praat TextGrid reading/writing with methods like `get_annotation_data_between_times()` and `create_gaps_and_overlaps_tier()`. **praatio** (MIT) is the most feature-rich TextGrid library, supporting all Praat formats (long, short, binary, JSON). **audformat** (MIT) from audEERING structures annotations in pandas DataFrames with `MultiIndex(file, start, end)`.

For forced alignment, **Montreal Forced Aligner** (MIT) is actively maintained (v3.3.9) with pretrained models for many languages. Note: **praat-parselmouth** (GPLv3+) and **aeneas** (AGPL v3) have restrictive copyleft licenses.

### NLP and text annotation

**spaCy** (MIT) [36] provides the richest in-memory text annotation model: `Doc` → `Token` (with `.pos_`, `.dep_`, `.ent_type_`, `.ent_iob_`) → `Span` (with `.label_`, `.start_char`, `.end_char`) → `SpanGroup` (named groups of potentially overlapping spans). Custom attributes via `set_extension()` enable domain-specific annotation properties.

**Argilla** (Apache-2.0) [37] is the most actively maintained open-source annotation platform, integrating with Hugging Face transformers and providing Python SDK for programmatic annotation management. **doccano** (MIT) and **brat** (MIT) provide lighter-weight alternatives.

### Computer vision annotation

**supervision** (Roboflow, MIT) [38] provides the unified `Detections` class with `.xyxy`, `.mask`, `.class_id`, `.confidence`, and connectors from every major model framework. **CVAT SDK** (MIT, v2.59.1) and **Label Studio SDK** (Apache-2.0, v2.0.19) provide programmatic annotation management with multi-format export.

---

## F. JavaScript/TypeScript libraries for annotation

### Audio waveform and annotation

**Wavesurfer.js** (BSD-3-Clause, v7.12.4) [39] is the leading audio annotation library — a full TypeScript rewrite (v7) using Shadow DOM. The **Regions plugin** creates clickable, draggable, resizable time-range overlays on waveforms, directly implementing interval annotations. Additional plugins: Timeline, Spectrogram, Envelope, Hover, Record, Minimap.

**Peaks.js** (BBC, LGPL-3.0) [40] offers pre-computed waveform support via the `audiowaveform` tool, making it better for long-form audio. It provides `segments` (time ranges) and `points` (single timestamps) with custom Konva.js-based marker rendering. The LGPL license is more restrictive than Wavesurfer's BSD.

### Timeline and track editors

**vis-timeline** (Apache-2.0/MIT dual license) [41] provides interactive timeline visualization with items, groups/lanes, drag-and-drop editing, and auto-scaling from milliseconds to years. For animation-style keyframe editing, **animation-timeline-js** (MIT, v2.3.5) provides a standalone canvas-based keyframe timeline control, and **@xzdarcy/react-timeline-editor** (MIT) provides a React-based track/action editor suitable for video editor-style UIs.

### Animation and rendering

**Lottie-web** (MIT, v5.13.0) [42] renders Lottie animations with SVG/Canvas/HTML renderers. Its API provides `playSegments([start, end])` for frame-range playback and marker support for named time positions. **PixiJS** (MIT, v8.16.0) provides the fastest 2D WebGL/WebGPU rendering for annotation overlays. **Three.js** (MIT, r183) offers `AnimationClip`/`AnimationMixer`/`KeyframeTrack` for 3D animation with per-property keyframe tracks. **Fabric.js** (MIT, v7.2.0) provides an interactive canvas object model with JSON serialization — ideal for image annotation. **Konva.js** (MIT, v10.2.0) provides a Stage→Layer→Shape hierarchy with React bindings via `react-konva`.

**GSAP** (GreenSock Standard License — free for all uses since Webflow acquisition, but not MIT/BSD) [43] provides the most powerful animation timeline API: `gsap.timeline()` with labels, `seek()`, `progress()`, and ScrollTrigger integration.

### Annotation-specific libraries

**Annotorious** (BSD-3, v3.x) [44] is the premier image annotation library with native W3C Web Annotation output, drawing tools (rectangle, polygon, freehand, circle), OpenSeadragon integration for deep-zoom/IIIF, and React bindings. **Hypothesis client** (BSD-2) implements W3C Web Annotation with robust text anchoring. **Label Studio frontend** (Apache-2.0) provides embeddable React annotation components for text, image, audio, video, and time series.

**Motion Canvas** (MIT, v3.17.2) [45] deserves special attention for the animation use case. Its generator-based timeline model uses `yield*` for sequencing: `yield* circle().position.x(300, 1)` animates a property, `yield* all(anim1(), anim2())` runs parallel animations, and `yield* waitUntil('event')` bridges code-defined timing with editor-defined markers. The **signals** system provides reactive state management for animation properties.

---

## G. Architecture case studies reveal recurring patterns

### Label Studio's polymorphic annotation model

Label Studio (Apache-2.0) [46] achieves multi-modal annotation through a key architectural decision: **XML labeling templates** define the annotation interface, while a **unified JSON result format** captures all annotation types. The `from_name`/`to_name` linking pattern associates control tags with data tags, enabling the same backend to handle text NER, image bounding boxes, audio segmentation, and time-series labeling. The ML backend integration shares the same JSON schema for predictions and human annotations, enabling seamless human-in-the-loop workflows.

### ELAN's TIME_SLOT indirection

ELAN's most significant design decision is the **TIME_SLOT** indirection layer [10]. Rather than embedding timestamps directly in annotations, annotations reference named time slots that are defined in a global TIME_ORDER section. This enables multiple annotations across different tiers to share the same temporal anchor points, and allows time references to be updated in one place. The five tier stereotypes (None, Time Subdivision, Symbolic Subdivision, Symbolic Association, Included In) create a type system for parent-child tier relationships, enforcing structural invariants that prevent inconsistencies.

### Video editing and animation timeline models

**MLT** (the framework underlying Kdenlive and Shotcut) uses a recursive composition model: **everything is a producer**. A Producer generates frames; a Playlist sequences producers; a Multitrack parallelizes tracks; a **Tractor** combines multitrack with filters and transitions. This uniform interface enables arbitrary nesting — a powerful pattern for complex annotation hierarchies [47].

**Unity Timeline** separates structure from scene references through track binding: each track targets a specific GameObject. **SignalTrack** provides event dispatch at specific frames, decoupling timeline events from game logic. **Godot AnimationPlayer** offers five track types — Property, Method Call, Bezier, Audio Playback, and Animation Playback — making the animation system a general-purpose sequencer where method call tracks turn into annotation-like event triggers.

**Manim** uses imperative sequential timing (`self.play(FadeIn(circle), run_time=2)` followed by `self.wait()`), while **Motion Canvas** uses generator coroutines (`yield*` to sequence, `yield` to advance a frame). Motion Canvas's `waitUntil('event')` pattern — where named events bridge code-defined animations with editor-defined timing — is particularly relevant for annotation systems that need both programmatic and interactive timeline control.

---

## H. Interchange formats for timelines and animation

### OpenTimelineIO is the editorial timeline standard

**OpenTimelineIO** (OTIO, Apache-2.0, Pixar/ASWF) [48] provides the most complete open interchange model for editorial timelines. Its hierarchy — Timeline → Stack → Track → Clip/Gap/Transition — maps directly to NLE concepts. **Markers** can attach to any item (not just tracks) with `marked_range` (position + duration) relative to the parent's time frame. The critical innovation is **RationalTime** (`value/rate`) — time as rational numbers with explicit frame rates, eliminating floating-point accumulation errors. The adapter plugin system handles format conversion to CMX 3600 EDL, FCP XML, AAF, and more.

### 3D animation interchange: glTF and USD

**glTF 2.0** (Khronos, open standard) [49] separates "what to animate" from "how to interpolate" via **channels** (target node + property path) and **samplers** (timestamp accessor + value accessor + interpolation type). Three interpolation modes — `STEP` (hold), `LINEAR` (lerp/slerp), `CUBICSPLINE` (Hermite with in/out tangents) — cover most runtime needs.

**USD** (Pixar, Apache-2.0) [50] provides the most powerful composition model. **Any attribute can have time samples** — a dictionary mapping time → value with default linear interpolation. The **layer composition system** (LIVRPS: Local, Inherits, VariantSets, References, Payloads, Specializes) enables non-destructive multi-artist collaboration. Time offsets and scales on composition arcs allow time remapping without modifying source data. This "strongest opinion wins" paradigm, where layers override like Photoshop, is a fundamentally different approach to annotation merging.

### Music and audio interchange

**MIDI** [51] models events as annotations: Note On/Off, Control Change, Markers, Tempo maps — all on a **tick-based** timeline (delta-time + ticks per quarter note). The separation of tick time from real time (via tempo maps) allows tempo changes without re-quantizing. **MusicXML** [52] separates **appearance** (notation, `<direction>` elements with dynamics, tempo markings) from **sound** (`<sound>` elements with MIDI-compatible playback hints) — the same annotation concept has both visual and playback representations. **EDL** (CMX 3600) [53] persists after 50+ years through radical simplicity: ASCII text with event number, reel, track, edit type, and four SMPTE timecodes.

---

## I. Best practices and common pitfalls

### What goes wrong in annotation system design

The most common architectural mistake is **mixing annotations with source data** — inline XML tags break character offsets, prevent overlapping annotations, and couple annotation schema to document structure. The second is **not planning for schema evolution**: annotation schemas inevitably change (adding confidence scores, new label types, annotator metadata). Design for additive-only schema changes, version all schemas, provide default values for new fields, and choose migration strategies (eager, lazy, or view-based) early [54].

Other critical pitfalls include ignoring annotation provenance (always store who, when, what, why), tight coupling between annotation model and display (separate data model from presentation), and using floating-point time representation (use rational time or integer milliseconds/ticks to avoid accumulation errors).

### Quality assurance and handling disagreement

The most impactful QA investment is **guideline quality** — research shows improving labeling instructions delivers better results than adding QA layers (study of 57,648 annotations from 924 annotators) [55]. Iterative pilot rounds with 2–3 annotators, explicit edge case documentation, and regular calibration sessions reduce disagreement at the source. Gold standard items interleaved at 5–10% in production queues enable ongoing monitoring.

The NLP community increasingly recognizes that **disagreement is signal, not noise** [56]. For subjective tasks (sentiment, toxicity, ambiguity), collapsing to single labels is epistemically wrong. **Soft labels** — probability distributions over labels rather than hard assignments — yield models with **32% lower KL divergence** to annotation distributions and **61% stronger correlation** between model entropy and annotation entropy [57]. Collins et al. demonstrated that 6 annotators providing soft labels equal **51 annotators** providing hard labels on CIFAR-10H [58]. The practical recommendation: preserve annotator disagreement as a feature, train on label distributions, and use multi-annotator models.

### Scalability patterns

For storage, separate annotation storage from source data. Flat files (JSON, JSONL) work for small projects and enable version control; PostgreSQL with GiST indexes handles interval queries efficiently at scale; for large media, store source on S3/GCS with annotation metadata in a database. **Interval tree indexing** is essential for temporal annotations — for 10M intervals, the tree uses ~400–600MB but enables logarithmic queries versus linear scans. Lazy loading and pagination prevent memory issues with large annotation sets.

---

## Conclusion

Several insights emerge from this cross-cutting survey that should inform annotation system architecture:

**Rational time eliminates an entire class of bugs.** OpenTimelineIO's `RationalTime`, MIDI's tick+PPQN, and ELAN's integer milliseconds all avoid floating-point accumulation. Any new annotation system should represent time as rational numbers or integer ticks, never as bare floats.

**The adapter pattern is non-negotiable.** The diversity of formats (30+ covered in this report) means annotation systems must separate their core model from I/O. OpenTimelineIO and Label Studio both demonstrate clean adapter architectures. The internal representation should be format-agnostic interval-based data; adapters handle the translation.

**Allen's Interval Algebra bridges the two use cases.** For time-based annotation, Allen's relations formalize overlap queries and constraint checking. For animation, they formalize timing relationships between clips, keyframes, and events. Implementing even a subset of Allen's algebra on top of interval stores adds powerful temporal reasoning.

**Generator-based timing models suit animation annotation.** Motion Canvas's `yield*` pattern — where code execution flow defines the timeline — is more composable and maintainable than keyframe-centric models for programmatic animation. The `waitUntil('event')` bridge between code and editor timing deserves adoption.

**The `(reference, metadata)` pair scales to every domain examined.** From brat's `(char_offset_range, entity_type)` to MIDI's `(tick, note_event)` to Lottie's `(frame, property_value)` to USD's `(time_sample, attribute_value)`, every format is a specialization of this core abstraction. A Mapping interface where keys are intervals and values are annotation data provides the most Pythonic API surface for this universal pattern.

---

## References

[1] R. Sanderson, P. Ciccarese, B. Young, "Web Annotation Data Model," W3C Recommendation, 23 Feb 2017. https://www.w3.org/TR/annotation-model/

[2] Hypothes.is. "Hypothesis — The Internet, peer reviewed." https://hypothes.is/

[3] S. Bird and M. Liberman, "A Formal Framework for Linguistic Annotation," *Speech Communication*, vol. 33, no. 1-2, pp. 23-60, 2001.

[4] N. Ide and L. Romary, "International Standard for a Linguistic Annotation Framework," *Natural Language Engineering*, vol. 10, no. 3-4, pp. 211-225, 2004. ISO 24612:2012.

[5] Apache UIMA. https://uima.apache.org/

[6] J. F. Allen, "Maintaining Knowledge about Temporal Intervals," *Communications of the ACM*, vol. 26, no. 11, pp. 832-843, Nov. 1983.

[7] qualreas — Qualitative Reasoning library. https://github.com/alreich/qualreas

[8] E. J. Humphrey et al., "JAMS: A JSON Annotated Music Specification for Reproducible MIR Research," *Proc. ISMIR*, 2014. https://github.com/marl/jams

[9] P. Boersma and D. Weenink, "Praat: doing phonetics by computer." https://www.praat.org/

[10] ELAN — The Language Archive, Max Planck Institute for Psycholinguistics. https://archive.mpi.nl/tla/elan

[11] "WebVTT: The Web Video Text Tracks Format," W3C. https://www.w3.org/TR/webvtt1/

[12] "Timed Text Markup Language 2 (TTML2)," W3C Recommendation. https://www.w3.org/TR/ttml2/

[13] P. Stenetorp et al., "brat: a Web-based Tool for NLP-Assisted Text Annotation," *Proc. EACL Demonstrations*, 2012. https://brat.nlplab.org/

[14] Universal Dependencies. CoNLL-U Format. https://universaldependencies.org/format.html

[15] L. Ratinov and D. Roth, "Design Challenges and Misconceptions in Named Entity Recognition," *Proc. CoNLL*, 2009.

[16] Hugging Face Datasets. https://huggingface.co/docs/datasets/

[17] Label Studio. https://labelstud.io/ — License: Apache-2.0.

[18] CVAT — Computer Vision Annotation Tool. https://github.com/cvat-ai/cvat — License: MIT.

[19] A. Dutta and A. Zisserman, "The VIA Annotation Software for Images, Audio and Video," *Proc. ACM Multimedia*, 2019.

[20] Lottie Animation Format. https://lottiefiles.github.io/lottie-docs/

[21] STAM — Stand-off Text Annotation Model. https://github.com/annotation/stam

[22] intervaltree — Python interval tree library. https://github.com/chaimleib/intervaltree — License: Apache-2.0.

[23] portion — Python interval arithmetic. https://github.com/AlexandreDecan/portion — License: LGPLv3.

[24] Yjs — CRDT framework. https://github.com/yjs/yjs — License: MIT.

[25] "PROV-O: The PROV Ontology," W3C Recommendation, 30 Apr 2013. https://www.w3.org/TR/prov-o/

[26] R. Killick, P. Fearnhead, and I. A. Eckley, "Optimal Detection of Changepoints With a Linear Computational Cost," *JASA*, vol. 107, no. 500, pp. 1590-1598, 2012.

[27] ruptures — Change point detection in Python. https://github.com/deepcharles/ruptures

[28] H. Bredin, "pyannote.metrics: A Toolkit for Reproducible Evaluation, Diagnostic, and Error Analysis of Speaker Diarization Systems," *Proc. Interspeech*, 2017.

[29] K. Krippendorff, *Content Analysis: An Introduction to its Methodology*, 4th ed., SAGE, 2018.

[30] V. Raj and F. Bach, "Convergence of Uncertainty Sampling for Active Learning," *Proc. ICML*, 2022.

[31] A. P. Dawid and A. M. Skene, "Maximum Likelihood Estimation of Observer Error-Rates Using the EM Algorithm," *Applied Statistics*, vol. 28, no. 1, pp. 20-28, 1979.

[32] D. Hovy et al., "Learning Whom to Trust with MACE," *Proc. NAACL-HLT*, 2013.

[33] M. McAuliffe et al., "Montreal Forced Aligner: Trainable Text-Speech Alignment Using Kaldi," *Proc. Interspeech*, 2017. https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner — License: MIT.

[34] pyannote.core. https://github.com/pyannote/pyannote-core — License: MIT.

[35] C. Raffel et al., "mir_eval: A Transparent Implementation of Common MIR Metrics," *Proc. ISMIR*, 2014. https://github.com/craffel/mir_eval — License: MIT.

[36] spaCy — Industrial-strength NLP. https://spacy.io/ — License: MIT.

[37] Argilla. https://github.com/argilla-io/argilla — License: Apache-2.0.

[38] supervision — Roboflow. https://github.com/roboflow/supervision — License: MIT.

[39] Wavesurfer.js. https://wavesurfer-js.org/ — License: BSD-3-Clause.

[40] Peaks.js — BBC. https://github.com/bbc/peaks.js — License: LGPL-3.0.

[41] vis-timeline. https://github.com/visjs/vis-timeline — License: Apache-2.0/MIT dual.

[42] lottie-web. https://github.com/airbnb/lottie-web — License: MIT.

[43] GSAP. https://gsap.com/ — License: GreenSock Standard (free for all uses).

[44] Annotorious. https://annotorious.dev/ — License: BSD-3-Clause.

[45] Motion Canvas. https://motioncanvas.io/ — License: MIT.

[46] Label Studio architecture. https://labelstud.io/guide/

[47] MLT Framework. https://www.mltframework.org/

[48] OpenTimelineIO. https://github.com/AcademySoftwareFoundation/OpenTimelineIO — License: Apache-2.0.

[49] glTF 2.0 Specification — Animations. https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#animations

[50] USD — Universal Scene Description. https://openusd.org/ — License: Apache-2.0.

[51] MIDI Manufacturers Association, "Standard MIDI Files Specification."

[52] MusicXML. https://www.w3.org/2021/06/musicxml40/

[53] CMX 3600 Edit Decision List format.

[54] R. Aroyo and C. Welty, "Truth Is a Lie: Crowd Truth and the Seven Myths of Human Annotation," *AI Magazine*, vol. 36, no. 1, 2015.

[55] Study cited in Label Studio documentation on annotation quality.

[56] S. Uma et al., "Learning from Disagreement: A Survey," *JAIR*, vol. 72, pp. 1385-1470, 2021.

[57] S. Singh et al., "Soft Label Training for Annotation Uncertainty," 2025.

[58] E. Collins et al., "Eliciting and Learning with Soft Labels from Every Annotator," *Proc. HCOMP*, 2022.