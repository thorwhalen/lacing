# lacing.worker

Optional Arq integration — queue processors through Redis.

This module imports `arq` only when needed, so it’s safe to import
even without `[arq]` installed. The actual `WorkerSettings` class is
constructed lazily by [`build_worker_settings()`](#lacing.worker.build_worker_settings).

Usage:

```default
# In a worker process — assumes Redis is running.
import asyncio
from lacing.worker import build_worker_settings
from arq import run_worker

settings = build_worker_settings(
    store_factory=lambda: SqliteStore("project.annot", check_same_thread=False),
    oplog_factory=lambda: SqliteOpLog("project.annot.oplog", check_same_thread=False),
)
run_worker(settings)

# In your app — enqueue a processor:
from arq.connections import create_pool, RedisSettings

redis = await create_pool(RedisSettings())
await redis.enqueue_job(
    "run_processor",
    "low_confidence_review",
    threshold=0.4,
)
```

For testing and small-scale work, prefer [`lacing.processors.run_sync()`](lacing.processors.md#lacing.processors.run_sync)
— it runs the same registered processor in the current event loop with
no Redis needed.

### Functions

| [`build_worker_settings`](#lacing.worker.build_worker_settings)(\*, store_factory, ...)   | Build an Arq `WorkerSettings` class with lacing processors registered.   |
|--------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|

### lacing.worker.build_worker_settings(, store_factory, oplog_factory, redis_settings=None)

Build an Arq `WorkerSettings` class with lacing processors registered.

* **Parameters:**
  * **store_factory** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – Zero-arg callable returning a fresh
    `IntervalAnnotationStore` (per-job; processors mutate it).
  * **oplog_factory** ([`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – Zero-arg callable returning a fresh `OpLog`.
  * **redis_settings** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Optional `arq.connections.RedisSettings`.
* **Return type:**
  [`type`](https://docs.python.org/3/builtins/functions.html#type)
* **Returns:**
  A class suitable for `arq.run_worker(...)`.
