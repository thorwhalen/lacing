"""Optional Arq integration — queue processors through Redis.

This module imports :mod:`arq` only when needed, so it's safe to import
even without ``[arq]`` installed. The actual ``WorkerSettings`` class is
constructed lazily by :func:`build_worker_settings`.

Usage::

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

For testing and small-scale work, prefer :func:`lacing.processors.run_sync`
— it runs the same registered processor in the current event loop with
no Redis needed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _require_arq():
    try:
        import arq
    except ImportError as exc:  # pragma: no cover  — covered by extra-missing
        raise ImportError(
            "Arq integration requires the arq package. Install with: "
            "pip install 'lacing[arq]'  (or directly: pip install arq)"
        ) from exc
    return arq


def build_worker_settings(
    *,
    store_factory: Callable[[], Any],
    oplog_factory: Callable[[], Any],
    redis_settings: Any | None = None,
) -> type:
    """Build an Arq ``WorkerSettings`` class with lacing processors registered.

    Args:
        store_factory: Zero-arg callable returning a fresh
            ``IntervalAnnotationStore`` (per-job; processors mutate it).
        oplog_factory: Zero-arg callable returning a fresh ``OpLog``.
        redis_settings: Optional ``arq.connections.RedisSettings``.

    Returns:
        A class suitable for ``arq.run_worker(...)``.
    """
    arq = _require_arq()

    if redis_settings is None:
        from arq.connections import RedisSettings

        redis_settings = RedisSettings()

    async def run_processor(ctx: dict, processor_name: str, **kwargs):
        """Arq job: run a registered processor by name."""
        from lacing.processors import run_async

        store = store_factory()
        oplog = oplog_factory()
        try:
            return await run_async(processor_name, store=store, oplog=oplog, **kwargs)
        finally:
            for resource in (store, oplog):
                close = getattr(resource, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:  # pragma: no cover
                        pass

    class WorkerSettings:
        """Arq ``WorkerSettings`` with lacing processors wired in.

        Override at instantiation time by setting class attributes; that's
        the standard Arq pattern.
        """

        functions = [run_processor]
        redis_settings = None  # filled in below

    WorkerSettings.redis_settings = redis_settings
    return WorkerSettings


__all__ = ["build_worker_settings"]
