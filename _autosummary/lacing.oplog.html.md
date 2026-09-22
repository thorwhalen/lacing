# lacing.oplog

Operation log for time-travel debug + audit.

The op-log is an append-only sequence of mutations applied to a store.
Each entry carries a monotonically increasing **Lamport clock**, the
operation name (`add_annotation`, `remove_annotation`, `add_tier`,
…), the target id, a JSON payload sufficient to **replay** the
operation against a fresh store, plus actor / timestamp metadata.

Together with a fresh empty store, the op-log is enough to reconstruct
the state of the system at any past clock value — the “killer debug
feature” called out in BACK-DOC §4.7.

Two implementations ship with Phase 2:

- [`InMemoryOpLog`](#lacing.oplog.InMemoryOpLog) — for tests, dev, ephemeral runs.
- [`SqliteOpLog`](#lacing.oplog.SqliteOpLog) — persistent table on top of any SQLite database
  (intended to live in the same `.annot` file as the store).

Use [`replay()`](#lacing.oplog.replay) to rebuild a store at a given clock.

### Functions

| `has_entries`(log)                                                                              |                                                                         |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`replay`](#lacing.oplog.replay)(log, \*[, until_clock, target_factory]) | Rebuild a store by replaying `log` up to (and including) `until_clock`. |

### Classes

| [`InMemoryOpLog`](#lacing.oplog.InMemoryOpLog)()                                  | Simple list-backed op-log.       |
|---------------------------------------------------------------------------------------------------|----------------------------------|
| [`OpLog`](#lacing.oplog.OpLog)(\*args, \*\*kwargs)                        | Append-only log of mutations.    |
| [`OpLogEntry`](#lacing.oplog.OpLogEntry)(clock, operation, target_id, payload) | One row of the op-log.           |
| [`SqliteOpLog`](#lacing.oplog.SqliteOpLog)(path, \*[, check_same_thread])       | Op-log backed by a SQLite table. |

### *class* lacing.oplog.InMemoryOpLog

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Simple list-backed op-log. Thread-safe via an RLock.

### *class* lacing.oplog.OpLog(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Append-only log of mutations.

Implementations must guarantee that the clock returned by
[`append()`](#lacing.oplog.OpLog.append) is strictly greater than every previously-returned
clock value across the lifetime of the log.

#### append(operation, , target_id=None, payload=None, actor='anonymous')

Append an entry; return its assigned clock.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### entries(, until_clock=None, from_clock=None)

Iterate entries, optionally bounded by clock range (inclusive).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`OpLogEntry`](#lacing.oplog.OpLogEntry)]

#### latest_clock()

Highest clock currently in the log; 0 if empty.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### *class* lacing.oplog.OpLogEntry(clock, operation, target_id, payload, actor='anonymous', received_at=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One row of the op-log.

#### actor *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`user:<handle>` or `agent:<model>@<hash>` or `adapter:<format>`.

#### clock *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Monotonic Lamport clock starting at 1. Strictly increasing per log.

#### operation *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`add_annotation`, `remove_annotation`, `update_annotation`,
`add_tier`, `set_meta`, `import_batch`.

* **Type:**
  One of

#### payload *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

JSON-serializable payload sufficient to replay the operation.

#### received_at *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Wall-clock time the operation was received (seconds since epoch).

#### target_id *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)*

Annotation id, tier name, meta key, or None for batch ops.

### *class* lacing.oplog.SqliteOpLog(path, , check_same_thread=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Op-log backed by a SQLite table.

Designed to share a database file with `SqliteStore` so the store
snapshot + the op-log live together and survive a single
`cp project.annot project.backup` step.

### lacing.oplog.replay(log, , until_clock=None, target_factory=None)

Rebuild a store by replaying `log` up to (and including) `until_clock`.

* **Parameters:**
  * **log** ([`OpLog`](#lacing.oplog.OpLog)) – Source op-log.
  * **until_clock** ([`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Stop at this clock (inclusive). None = replay all.
  * **target_factory** – Zero-arg callable returning a fresh empty store.
    Defaults to `MemoryStore`. Pass a `SqliteStore` factory to
    replay into a persistent file.
* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)
* **Returns:**
  The rebuilt store. Operations whose payload references unknown
  body schemas or tier parents are still applied; the caller is
  responsible for any post-replay validation.
