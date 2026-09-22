# lacing.bodies.review

Body schema for review notes — the edit-loop’s communication channel.

URI: `annot://schema/review/v1`

A *review* annotation is a structured note attached to one or more
artifacts (a panel, a beat, a segmentation alternate, a render result),
optionally pointing at a typed payload like a
`ContinuityViolationBodyV1`. Reviews are produced by:

- automated checkers (continuity, grammar, timing, segmentation rules)
- the edit-loop (“this caption needs a revision”)
- the orchestrator (“the user declined the cost gate at panel 12”)
- the user (“approve” / “needs revision” notes)

The body is intentionally minimal. The kind (`review_kind`) routes
the FE renderer; the payload is opaque to lacing.

An `approval` review carries a `decision` — this is the record
`lacing.server.operations.accept_ai_suggestion()` writes when a human
accepts or rejects an AI suggestion, so that the human’s edit is
attributed to the human without overwriting the agent’s provenance on the
annotation being judged (lacing#18).

#### NOTE
`decision` is **additive and optional**, so stored bodies validate
unchanged and lacing owes no migration. Downstream mirrors of this
schema are a different matter: reelee-web’s generated Zod type is
`.strict()` and its JSON Schema is `additionalProperties: false`,
so an additive field here is a *breaking* change there until the
mirror is regenerated — tracked as thorwhalen/reelee-web#234.

### References

- `reelee/docs/Narrative to Storyboard.md` §6.5–6.6.
- `reelee/docs/reelee 03 -- Human-AI Collaboration UX Patterns…` §10
  (annotation overlays).

### Module Attributes

| [`ReviewKind`](#lacing.bodies.review.ReviewKind)     | What flavor of review this is.                                      |
|-----------------------------------------------------------------|---------------------------------------------------------------------|
| [`ReviewStatus`](#lacing.bodies.review.ReviewStatus)   | Open is the initial state; the others are user / agent resolutions. |
| [`Author`](#lacing.bodies.review.Author)         | Coarse author classification.                                       |
| [`ReviewDecision`](#lacing.bodies.review.ReviewDecision) | The verdict an `approval` review carries.                           |

### Classes

| [`ReviewBodyV1`](#lacing.bodies.review.ReviewBodyV1)(\*\*data)   | Body of a review annotation.   |
|---------------------------------------------------------------------------|--------------------------------|

### lacing.bodies.review.Author

Coarse author classification. The annotation envelope’s
`was_attributed_to` carries the specific identity; this field is the
quick chip for the FE.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘human’, ‘agent’, ‘system’]

### *class* lacing.bodies.review.ReviewBodyV1(\*\*data)

Bases: `BaseModel`

Body of a review annotation.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### lacing.bodies.review.ReviewDecision

The verdict an `approval` review carries. Only `review_kind =
"approval"` reviews have one — a continuity or grammar note is an
observation, not a ruling, so `decision` stays `None` there.

Why this is a field rather than something to read off the reviewed
annotation’s `confidence`: the verdict is a fact about \*the review
event\*, and `confidence` is a mutable field on a different record that
the next write can move. Recovering “was this accepted?” by dereferencing
a live value is exactly the coupling that made lacing#18 possible.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘accepted’, ‘rejected’]

### lacing.bodies.review.ReviewKind

What flavor of review this is. Drives the FE’s renderer choice and
the producing-Transform’s routing logic.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘continuity’, ‘segmentation’, ‘prompt’, ‘grammar’, ‘timing’, ‘iconic_moment’, ‘manual’, ‘approval’]

### lacing.bodies.review.ReviewStatus

Open is the initial state; the others are user / agent resolutions.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘open’, ‘addressed’, ‘wont_fix’, ‘deferred’]
