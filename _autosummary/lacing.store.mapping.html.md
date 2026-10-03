# lacing.store.mapping

`MappingStore` — an `IntervalAnnotationStore` persisted to any `MutableMapping`.

Where [`SqliteStore`](lacing.store.sqlite.html.md#lacing.store.sqlite.SqliteStore) owns a file, `MappingStore`
owns nothing: the caller injects the persistence as a `MutableMapping` (a
plain `dict`, a `dol` `JsonFiles` / `Files` store, an application’s
“mall” entry, an S3-backed mapping, …). An app that already keeps its data
in mappings can hand one to lacing as its annotation graph, so there is no
second persistence path beside the one it already has.

## Layout inside the mapping

* **One key per annotation**: `str(annotation.id)` (a UUID string) ->
  `annotation.model_dump(mode="json")`, the same JSON shape every other
  lacing surface (server, MCP, op-log) uses for an `Annotation`.
* **Tiers under one reserved key** (`tiers_key`, default
  `"__lacing_tiers__"`): `{"tiers": [<Tier.to_wire()>, ...]}`. The key
  can never collide with an annotation key because a UUID string is exactly
  36 characters of hex and hyphens.

The mapping holds **JSON-ready dicts** by default. That is what a plain
`dict` and `dol`’s `JsonFiles` both want (`JsonFiles` does the
`json.dumps` itself). For a mapping that stores `bytes` or `str` (a raw
`Files` store, a blob bucket), pass `codec=JSON_BYTES_CODEC` or
`JSON_STR_CODEC`, or your own [`MappingCodec`](#lacing.store.mapping.MappingCodec).

The interval index is [`MemoryStore`](lacing.store.memory.html.md#lacing.store.memory.MemoryStore)’s: the whole
mapping is loaded into it on construction and every mutation is written
through to the mapping *first* and applied to the index only if that write
succeeded. All Allen-relation queries are the in-memory ones; there is no
re-implementation here.

## Lifecycle

`close()` is a harmless no-op that leaves the store usable (write-through
means there is nothing to flush, and the mapping is not ours to close).

## Concurrency

**Single writer, no locking.** Unlike `SqliteStore` there is no cross-process
lock: the index is a snapshot taken at construction, so a second
`MappingStore` over the same mapping (in this or another process) does not
see the first one’s later writes, and two writers can overwrite each other’s
tier registry. Serialise writers yourself, or open one store per process
lifetime. Keys foreign to the layout (anything that is neither a UUID string
nor `tiers_key`) make construction raise rather than be silently skipped, so
point the store at a mapping (or a sub-mapping) dedicated to it.

### Module Attributes

| [`DICT_CODEC`](#lacing.store.mapping.DICT_CODEC)       | Store the JSON-ready dict itself (`dict`, dol `JsonFiles`).        |
|-------------------------------------------------------------------|--------------------------------------------------------------------|
| [`JSON_BYTES_CODEC`](#lacing.store.mapping.JSON_BYTES_CODEC) | Store UTF-8 JSON `bytes` (a raw dol `Files` store, a blob bucket). |
| [`JSON_STR_CODEC`](#lacing.store.mapping.JSON_STR_CODEC)   | Store JSON `str`.                                                  |

### Classes

| [`MappingCodec`](#lacing.store.mapping.MappingCodec)(encode, decode)                  | How a JSON-ready `dict` is turned into what the mapping stores, and back.   |
|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`MappingStore`](#lacing.store.mapping.MappingStore)(mapping, \*[, codec, tiers_key]) | An `IntervalAnnotationStore` persisted to an injected `MutableMapping`.     |

### lacing.store.mapping.DICT_CODEC *= (<function <lambda>>, <function <lambda>>)*

Store the JSON-ready dict itself (`dict`, dol `JsonFiles`). The default.

### lacing.store.mapping.JSON_BYTES_CODEC *= (<function <lambda>>, <function <lambda>>)*

Store UTF-8 JSON `bytes` (a raw dol `Files` store, a blob bucket).

### lacing.store.mapping.JSON_STR_CODEC *= (<function dumps>, <function <lambda>>)*

Store JSON `str`.

### *class* lacing.store.mapping.MappingCodec(encode, decode)

Bases: [`NamedTuple`](https://docs.python.org/3/library/typing.html#typing.NamedTuple)

How a JSON-ready `dict` is turned into what the mapping stores, and back.

#### decode *: [Callable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[Any](https://docs.python.org/3/library/typing.html#typing.Any)], [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)]*

Alias for field number 1

#### encode *: [Callable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[dict](https://docs.python.org/3/builtins/stdtypes.html#dict)], [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

Alias for field number 0

### *class* lacing.store.mapping.MappingStore(mapping, \*, codec=(<function <lambda>>, <function <lambda>>), tiers_key='_\_lacing_tiers_\_')

Bases: [`MemoryStore`](lacing.store.memory.html.md#lacing.store.memory.MemoryStore)

An `IntervalAnnotationStore` persisted to an injected `MutableMapping`.

```pycon
>>> from lacing.store import MappingStore
>>> backing = {}
>>> store = MappingStore(backing)
>>> len(backing)  # nothing written until something is added
0
```

Reopening over the same mapping sees the same annotations and tiers.

Raises `ValueError` on a duplicate annotation id (as `SqliteStore`
does) and when an annotation is assigned under a key that is not its own
interval; both would otherwise not survive a reload.

#### close()

No-op. Writes go through immediately and the mapping is the caller’s.

Present so code that calls `store.close()` after each use (as it does
for `SqliteStore`) can treat both alike; the store stays usable.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
