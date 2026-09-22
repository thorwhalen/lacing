# lacing.bodies.reference_lock

Body schema for a *locked reference* — a first-class “this is canonical”.

URI: `annot://schema/reference-lock/v1`

A **reference lock** records the decision that one or more reference
artifacts *are* the canonical anchor for some subject — a character’s
face, a location’s architecture, a style, a prop. Once a subject is
locked, a *supervisor* can check every later generation against the
locked anchor and flag drift (the consumer in reelee runs the
identity/likeness comparison and emits `continuity-violation/v1`
annotations; this schema only carries the *decision*, not the result).

The shape is deliberately general so it fits several real workflows
without a schema bump:

- **One image or a set.** `locked_artifact_ids` holds 1..N artifacts.
  Lock a single canonical headshot, or a set (front / three-quarter /
  full-body / expression sheet). `primary_artifact_id` names the one
  to show by default.
- **Project- or scene-scoped.** `scope` is `"project"` by default
  (the character is locked for the whole piece) or `"scene"` (a
  re-lock for a flashback / costume change), in which case
  `scope_ref` names the scene/segment it applies to. Re-locks chain
  via `supersedes` (the prior lock’s annotation id).
- **Per-aspect checklist with advisory-by-default gating.**
  `checklist` is the set of aspects the supervisor compares
  (`"face"`, `"architecture"`, `"props"`, `"lighting"`,
  `"costume"`, `"palette"`, …). `hard_gates` is the subset that
  *blocks* on mismatch; it defaults to empty, so every aspect is
  **advisory** (flag, never auto-reject) — honouring the field
  observation that over-strict likeness filters waste the user’s time
  rejecting perfectly good images.

The lock is itself an annotation; *who* locked it and *when* live in
the annotation’s PROV-O provenance, not in this body.

Reference: `reelee/docs/Narrative to Storyboard.md` (reference
consistency); reelee-web epic #151, lacing #9.

### Module Attributes

| [`SubjectKind`](#lacing.bodies.reference_lock.SubjectKind)   | What the lock anchors.                                |
|----------------------------------------------------------------|-------------------------------------------------------|
| [`Scope`](#lacing.bodies.reference_lock.Scope)         | `project` — locked for the whole piece (the default). |

### Classes

| [`ReferenceLockBodyV1`](#lacing.bodies.reference_lock.ReferenceLockBodyV1)(\*\*data)   | Body of a reference-lock annotation.   |
|----------------------------------------------------------------------------------|----------------------------------------|

### *class* lacing.bodies.reference_lock.ReferenceLockBodyV1(\*\*data)

Bases: `BaseModel`

Body of a reference-lock annotation.

Records that `locked_artifact_ids` are the canonical anchor for
`subject_id` (a `subject_kind`), the aspects a supervisor should
compare (`checklist`), which of those block vs merely warn
(`hard_gates`), and the advisory identity threshold
(`min_similarity`).

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

#### *property* primary *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The artifact id to display — `primary_artifact_id` or the first locked one.

### lacing.bodies.reference_lock.Scope

`project` — locked for the whole piece (the default). `scene` —
re-locked for one scene/segment (flashback, costume change); requires
`scope_ref`.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘project’, ‘scene’]

### lacing.bodies.reference_lock.SubjectKind

What the lock anchors. `character` (a face/identity), `location`
(architecture / set), `style` (look anchor), `prop` (a recurring
object), or `other` for anything not yet enumerated.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘character’, ‘location’, ‘style’, ‘prop’, ‘other’]
