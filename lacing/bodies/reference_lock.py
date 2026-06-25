"""Body schema for a *locked reference* — a first-class “this is canonical”.

URI: ``annot://schema/reference-lock/v1``

A **reference lock** records the decision that one or more reference
artifacts *are* the canonical anchor for some subject — a character's
face, a location's architecture, a style, a prop. Once a subject is
locked, a *supervisor* can check every later generation against the
locked anchor and flag drift (the consumer in reelee runs the
identity/likeness comparison and emits ``continuity-violation/v1``
annotations; this schema only carries the *decision*, not the result).

The shape is deliberately general so it fits several real workflows
without a schema bump:

- **One image or a set.** ``locked_artifact_ids`` holds 1..N artifacts.
  Lock a single canonical headshot, or a set (front / three-quarter /
  full-body / expression sheet). ``primary_artifact_id`` names the one
  to show by default.
- **Project- or scene-scoped.** ``scope`` is ``"project"`` by default
  (the character is locked for the whole piece) or ``"scene"`` (a
  re-lock for a flashback / costume change), in which case
  ``scope_ref`` names the scene/segment it applies to. Re-locks chain
  via ``supersedes`` (the prior lock's annotation id).
- **Per-aspect checklist with advisory-by-default gating.**
  ``checklist`` is the set of aspects the supervisor compares
  (``"face"``, ``"architecture"``, ``"props"``, ``"lighting"``,
  ``"costume"``, ``"palette"``, …). ``hard_gates`` is the subset that
  *blocks* on mismatch; it defaults to empty, so every aspect is
  **advisory** (flag, never auto-reject) — honouring the field
  observation that over-strict likeness filters waste the user's time
  rejecting perfectly good images.

The lock is itself an annotation; *who* locked it and *when* live in
the annotation's PROV-O provenance, not in this body.

Reference: ``reelee/docs/Narrative to Storyboard.md`` (reference
consistency); reelee-web epic #151, lacing #9.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from lacing.schema import register_body_schema


REFERENCE_LOCK_BODY_SCHEMA_URI = "annot://schema/reference-lock/v1"


SubjectKind = Literal["character", "location", "style", "prop", "other"]
"""What the lock anchors. ``character`` (a face/identity), ``location``
(architecture / set), ``style`` (look anchor), ``prop`` (a recurring
object), or ``other`` for anything not yet enumerated."""


Scope = Literal["project", "scene"]
"""``project`` — locked for the whole piece (the default). ``scene`` —
re-locked for one scene/segment (flashback, costume change); requires
``scope_ref``."""


class ReferenceLockBodyV1(BaseModel):
    """Body of a reference-lock annotation.

    Records that ``locked_artifact_ids`` are the canonical anchor for
    ``subject_id`` (a ``subject_kind``), the aspects a supervisor should
    compare (``checklist``), which of those block vs merely warn
    (``hard_gates``), and the advisory identity threshold
    (``min_similarity``).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    subject_kind: SubjectKind = Field(
        ...,
        description="What this lock anchors — character / location / style / prop / other.",
    )
    subject_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Id (or stable name) of the entity this lock anchors — e.g. a "
            "character-ref / location-ref annotation id."
        ),
    )
    locked_artifact_ids: tuple[str, ...] = Field(
        ...,
        min_length=1,
        description=(
            "1..N reference artifact / annotation ids that *are* the "
            "canonical anchor. One canonical image, or a set "
            "(front / three-quarter / full-body / expressions)."
        ),
    )
    primary_artifact_id: Optional[str] = Field(
        None,
        description=(
            "The representative artifact to display; must be one of "
            "``locked_artifact_ids``. Defaults to the first when omitted."
        ),
    )
    scope: Scope = Field(
        "project",
        description="Lock scope — 'project' (whole piece) or 'scene' (re-lock).",
    )
    scope_ref: Optional[str] = Field(
        None,
        description=(
            "When ``scope == 'scene'``, the scene/segment id this lock "
            "applies to. Must be None for project scope."
        ),
    )
    checklist: tuple[str, ...] = Field(
        ("face",),
        description=(
            "Aspects the supervisor compares against the anchor — e.g. "
            "'face', 'architecture', 'props', 'lighting', 'costume', "
            "'palette'. Strings (not Literal) so new aspects need no "
            "schema bump."
        ),
    )
    hard_gates: tuple[str, ...] = Field(
        (),
        description=(
            "Subset of ``checklist`` that BLOCKS on mismatch (auto-reject "
            "/ queue regen). Empty by default → every aspect is advisory "
            "(flag, never auto-block)."
        ),
    )
    min_similarity: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Advisory identity-similarity threshold in [0, 1]; a candidate "
            "scoring below this is flagged as drift. None → use the "
            "supervisor's system default."
        ),
    )
    supersedes: Optional[str] = Field(
        None,
        description=(
            "Prior reference-lock annotation id this re-lock replaces "
            "(costume change, scene re-lock). None for the first lock."
        ),
    )
    notes: str = Field(
        "",
        description=(
            "Human checklist hints the vision supervisor can use — e.g. "
            "'the green flat cap is present', 'same bar layout'."
        ),
    )
    params: dict = Field(
        default_factory=dict,
        description=(
            "Opaque per-aspect config (e.g. per-aspect thresholds). "
            "Ignored by lacing; consumed by the producing supervisor."
        ),
    )

    @model_validator(mode="after")
    def _check_invariants(self) -> "ReferenceLockBodyV1":
        if self.primary_artifact_id is not None and (
            self.primary_artifact_id not in self.locked_artifact_ids
        ):
            raise ValueError(
                "primary_artifact_id must be one of locked_artifact_ids "
                f"(got {self.primary_artifact_id!r})."
            )
        extra_gates = set(self.hard_gates) - set(self.checklist)
        if extra_gates:
            raise ValueError(
                f"hard_gates must be a subset of checklist; unknown: {sorted(extra_gates)}."
            )
        if self.scope == "scene" and not self.scope_ref:
            raise ValueError("scope_ref is required when scope == 'scene'.")
        if self.scope == "project" and self.scope_ref is not None:
            raise ValueError("scope_ref must be None when scope == 'project'.")
        return self

    @property
    def primary(self) -> str:
        """The artifact id to display — ``primary_artifact_id`` or the first locked one."""
        return self.primary_artifact_id or self.locked_artifact_ids[0]


register_body_schema(REFERENCE_LOCK_BODY_SCHEMA_URI, ReferenceLockBodyV1)
