# lacing.store.memory

In-memory annotation store backed by an interval tree.

Uses `intervaltree` (Apache-2.0). Annotations whose reference is not a
`MediaRef` (i.e., they have no time interval) are kept in a separate
list — they can still be enumerated via `all()` / `by_tier` but
won’t appear in interval queries.

### Classes

| [`MemoryStore`](#lacing.store.memory.MemoryStore)()   | `IntervalAnnotationStore` implementation over `intervaltree`.   |
|------------------------------------------------------------------|-----------------------------------------------------------------|

### *class* lacing.store.memory.MemoryStore

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`IntervalAnnotationStore` implementation over `intervaltree`.

Conforms to the protocol in `lacing.store.base`. We don’t formally
inherit from `IntervalAnnotationStore` because it’s a `Protocol`
with method bodies — structural typing is enough.
