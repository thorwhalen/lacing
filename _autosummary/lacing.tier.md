# lacing.tier

Tiers and the five ELAN stereotypes.

A tier is a named layer of annotations. Stereotypes constrain how a tier
relates to its parent. We adopt ELAN’s five stereotypes verbatim — see
ANN-DOC §C and OSS-DOC tier-2.4.

### Functions

| [`validate_tier_constraint`](#lacing.tier.validate_tier_constraint)(parent, child, ...)   | Check that `child_intervals` satisfy `child.stereotype` against `parent_intervals`.   |
|-------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|

### Classes

| [`Tier`](#lacing.tier.Tier)(name, \*[, stereotype, parent, metadata])   | A named annotation layer with optional parent and stereotype.   |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| [`TierStereotype`](#lacing.tier.TierStereotype)(\*values)                         | Constraints on how a child tier relates to its parent tier.     |

### *class* lacing.tier.Tier(name, , stereotype=TierStereotype.NONE, parent=None, metadata=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A named annotation layer with optional parent and stereotype.

Tiers are pure metadata; they don’t own annotations. The store is keyed
by interval, not by tier — annotations carry their tier name as a field.
This matches ELAN’s TIME_ORDER indirection (see ANN-DOC §C).

### *class* lacing.tier.TierStereotype(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Constraints on how a child tier relates to its parent tier.

Names match ELAN exactly so EAF round-trips are trivial.

#### INCLUDED_IN *= 'INCLUDED_IN'*

Children lie within the parent but gaps between siblings are allowed.

#### NONE *= 'NONE'*

No parent constraint. Top-level tier.

#### SYMBOLIC_ASSOCIATION *= 'SYMBOLIC_ASSOCIATION'*

One-to-one association with parent; child shares parent’s interval exactly.

#### SYMBOLIC_SUBDIVISION *= 'SYMBOLIC_SUBDIVISION'*

Ordered subdivision; children share parent’s interval as a sequence (no times).

#### TIME_SUBDIVISION *= 'TIME_SUBDIVISION'*

Children fully partition the parent’s interval (no gaps, no overlap).

### lacing.tier.validate_tier_constraint(parent, child, parent_intervals, child_intervals)

Check that `child_intervals` satisfy `child.stereotype` against `parent_intervals`.

Returns a list of violation messages (empty list = valid). Pure function;
callers decide whether to raise, log, or surface in UI.

Lives here rather than on `Tier` so the constraint logic is testable
in isolation and reusable from server validators and UI plugins alike.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
