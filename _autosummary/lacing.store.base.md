# lacing.store.base

`IntervalAnnotationStore` — the headline Pythonic API.

A `MutableMapping[TimeInterval, list[Annotation]]` facade with methods
named after Allen’s relations. See ANN-DOC §C (“a natural design target”)
and BACK-DOC §4.1.

The facade hides the index. Phase 0 ships `MemoryStore` over
`intervaltree`. Phase 1 adds SQLite + R\*Tree (`.annot`) and PostgreSQL

+ `tstzrange` GiST. The mapping interface is the same in all three.

### Classes

| [`IntervalAnnotationStore`](#lacing.store.base.IntervalAnnotationStore)(\*args, \*\*kwargs)   | Protocol for any interval-keyed annotation store.   |
|------------------------------------------------------------------------------------------------|-----------------------------------------------------|

### *class* lacing.store.base.IntervalAnnotationStore(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Protocol for any interval-keyed annotation store.

Conceptually a `MutableMapping[TimeInterval, list[Annotation]]`: keys
are `TimeInterval`; values are lists because multiple annotations can
share an interval (different tiers, multiple annotators, soft labels).

We use `Protocol` rather than inheriting from `MutableMapping` so
backends (in-memory, SQLite, Postgres) can structurally conform without
forcing a single class hierarchy. The mapping methods below match the
`MutableMapping` ABC; concrete backends like `MemoryStore`
implement the full interface.

#### add(annotation)

Append `annotation` to the list at its reference interval.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### all()

Iterate every annotation in the store, order unspecified.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### at_tier(tier_name, query)

Annotations on `tier_name` that intersect `query`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### by_tier(tier_name)

All annotations on `tier_name`, regardless of interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### contains(query)

Annotations whose interval strictly contains `query` (Allen `di`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### during(query)

Annotations whose interval is strictly inside `query` (Allen `d`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### equals(query)

Allen `=`: identical interval.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### extend(annotations)

Add many; equivalent to repeated `.add` but adapters can optimize.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### finishes(query)

Allen `f`: later start, same end.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### intersects(query)

Annotations whose interval shares any time with `query`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### meets(query)

Allen `m`: `a.end == q.start`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### overlaps(query)

Strict Allen `o`: `a.start < q.start < a.end < q.end`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### relate(query, relations)

Annotations whose interval has any of the named `relations` to `query`.

Generic dispatch — useful when relations are computed at runtime.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### remove(annotation_id)

Remove and return the annotation with this id, or None if absent.

* **Return type:**
  [`Annotation`](lacing.model.md#lacing.model.Annotation) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### starts(query)

Allen `s`: same start, earlier end.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Annotation`](lacing.model.md#lacing.model.Annotation)]

#### tiers()

Registered tiers. Annotations may reference tiers not yet registered;
callers decide whether that’s an error.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Tier`](lacing.tier.md#lacing.tier.Tier)]
