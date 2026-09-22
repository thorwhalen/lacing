# lacing.bodies.continuity_violation

Body schema for continuity violations — generic, cross-media.

URI: `annot://schema/continuity-violation/v1`

A *continuity violation* is a typed claim about a relationship between
two or more annotations: “panels 5 and 6 cross the 180° axis”, “the
character drift between panel 3 and panel 4 exceeds the embed-distance
threshold”, “object detection finds a prop in panel 7 absent from
panel 8.”

The schema is intentionally generic. Specific rule families live in
their producing packages — reelee defines axis_180, character_drift,
prop_hallucination, etc. via dedicated Transforms — but the *envelope*
that carries the result is generic enough to live in lacing.

Violations attach as `review/v1` annotations whose `review_kind ==
"continuity"` (see [`lacing.bodies.review`](lacing.bodies.review.md#module-lacing.bodies.review)).

Reference: `reelee/docs/Narrative to Storyboard.md` §6.5, §8.1.

### Module Attributes

| [`SuggestedAction`](#lacing.bodies.continuity_violation.SuggestedAction)   | Coarse action the edit-loop UI offers in response.   |
|--------------------------------------------------------------------|------------------------------------------------------|

### Classes

| [`ContinuityViolationBodyV1`](#lacing.bodies.continuity_violation.ContinuityViolationBodyV1)(\*\*data)   | Body of a continuity-violation annotation.   |
|----------------------------------------------------------------------------------------|----------------------------------------------|

### *class* lacing.bodies.continuity_violation.ContinuityViolationBodyV1(\*\*data)

Bases: `BaseModel`

Body of a continuity-violation annotation.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### lacing.bodies.continuity_violation.SuggestedAction

Coarse action the edit-loop UI offers in response. Producing
Transforms pick one; the FE wires each to a button + acture command.

alias of [`Literal`](https://docs.python.org/3/library/typing.html#typing.Literal)[‘regen_panel’, ‘regen_with_ref’, ‘manual_edit’, ‘accept’]
