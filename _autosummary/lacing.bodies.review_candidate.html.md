# lacing.bodies.review_candidate

Body schema for review *candidates* — “this needs a human’s eyes”.

URI: `annot://schema/review-candidate/v1`

A review-candidate is what an automated processor emits when it flags an
annotation as worth a human look — today,
[`lacing.processors.low_confidence_review()`](lacing.processors.html.md#lacing.processors.low_confidence_review) flagging low-confidence
rows. It is deliberately NOT a [`ReviewBodyV1`](lacing.bodies.review.html.md#lacing.bodies.review.ReviewBodyV1):

- a review is a structured **note or verdict** (a continuity observation,
  an approval carrying a `decision`) written *about* work;
- a candidate is a **pointer into a queue** — “look at this one, and here
  is why it was flagged” — with no message, no status lifecycle, and no
  verdict. Reviewing a candidate *produces* a review; the candidate is the
  input, not an early draft of the output.

The two lived under one URI for a while, and the processor’s rows failed
validation against the model registered for that URI in five ways at once
(lacing#37). One URI per body shape is the contract `body_schema_uri`
exists to keep; giving the candidate its own name is the whole fix — no
stored `review/v1` body changes shape, so no migration.

The tier split mirrors the body split, stated here because it is easy to
read as an accident: candidates land on `"for-review"` (the processor’s
default) while human/agent reviews land on `"review"`
(`operations.DFLT_REVIEW_TIER`). Candidates queue; reviews record.

### Classes

| [`ReviewCandidateBodyV1`](#lacing.bodies.review_candidate.ReviewCandidateBodyV1)(\*\*data)   | Body of a review-candidate annotation.   |
|------------------------------------------------------------------------------------|------------------------------------------|

### *class* lacing.bodies.review_candidate.ReviewCandidateBodyV1(\*\*data)

Bases: `BaseModel`

Body of a review-candidate annotation.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
