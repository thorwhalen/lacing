"""``MappingStore`` — an ``IntervalAnnotationStore`` persisted to any ``MutableMapping``.

Where :class:`~lacing.store.sqlite.SqliteStore` owns a file, ``MappingStore``
owns nothing: the caller injects the persistence as a ``MutableMapping`` (a
plain ``dict``, a ``dol`` ``JsonFiles`` / ``Files`` store, an application's
"mall" entry, an S3-backed mapping, ...). An app that already keeps its data
in mappings can hand one to lacing as its annotation graph, so there is no
second persistence path beside the one it already has.

Layout inside the mapping
-------------------------
* **One key per annotation**: ``str(annotation.id)`` (a UUID string) ->
  ``annotation.model_dump(mode="json")``, the same JSON shape every other
  lacing surface (server, MCP, op-log) uses for an ``Annotation``.
* **Tiers under one reserved key** (``tiers_key``, default
  ``"__lacing_tiers__"``): ``{"tiers": [<Tier.to_wire()>, ...]}``. The key
  can never collide with an annotation key because a UUID string is exactly
  36 characters of hex and hyphens.

The mapping holds **JSON-ready dicts** by default. That is what a plain
``dict`` and ``dol``'s ``JsonFiles`` both want (``JsonFiles`` does the
``json.dumps`` itself). For a mapping that stores ``bytes`` or ``str`` (a raw
``Files`` store, a blob bucket), pass ``codec=JSON_BYTES_CODEC`` or
``JSON_STR_CODEC``, or your own :class:`MappingCodec`.

The interval index is :class:`~lacing.store.memory.MemoryStore`'s: the whole
mapping is loaded into it on construction and every mutation is written
through to the mapping *first* and applied to the index only if that write
succeeded. All Allen-relation queries are the in-memory ones; there is no
re-implementation here.

Lifecycle
---------
``close()`` is a harmless no-op that leaves the store usable (write-through
means there is nothing to flush, and the mapping is not ours to close).

Concurrency
-----------
**Single writer, no locking.** Unlike ``SqliteStore`` there is no cross-process
lock: the index is a snapshot taken at construction, so a second
``MappingStore`` over the same mapping (in this or another process) does not
see the first one's later writes, and two writers can overwrite each other's
tier registry. Serialise writers yourself, or open one store per process
lifetime. Keys foreign to the layout (anything that is neither a UUID string
nor ``tiers_key``) make construction raise rather than be silently skipped, so
point the store at a mapping (or a sub-mapping) dedicated to it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, MutableMapping
from typing import Any, NamedTuple
from uuid import UUID

from lacing.model import Annotation
from lacing.store.memory import MemoryStore
from lacing.store.memory import _key as _bucket_key
from lacing.tier import Tier
from lacing.time import TimeInterval

DEFAULT_TIERS_KEY = "__lacing_tiers__"


class MappingCodec(NamedTuple):
    """How a JSON-ready ``dict`` is turned into what the mapping stores, and back."""

    encode: Callable[[dict], Any]
    decode: Callable[[Any], dict]


DICT_CODEC = MappingCodec(encode=lambda d: d, decode=lambda v: v)
"""Store the JSON-ready dict itself (``dict``, dol ``JsonFiles``). The default."""

JSON_BYTES_CODEC = MappingCodec(
    encode=lambda d: json.dumps(d).encode("utf-8"),
    decode=lambda v: json.loads(bytes(v).decode("utf-8")),
)
"""Store UTF-8 JSON ``bytes`` (a raw dol ``Files`` store, a blob bucket)."""

JSON_STR_CODEC = MappingCodec(
    encode=json.dumps,
    decode=lambda v: json.loads(v if isinstance(v, str) else bytes(v).decode("utf-8")),
)
"""Store JSON ``str``."""


def _is_annotation_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    try:
        return str(UUID(key)) == key
    except ValueError:
        return False


class MappingStore(MemoryStore):
    """An ``IntervalAnnotationStore`` persisted to an injected ``MutableMapping``.

    >>> from lacing.store import MappingStore
    >>> backing = {}
    >>> store = MappingStore(backing)
    >>> len(backing)  # nothing written until something is added
    0

    Reopening over the same mapping sees the same annotations and tiers.

    Raises ``ValueError`` on a duplicate annotation id (as ``SqliteStore``
    does) and when an annotation is assigned under a key that is not its own
    interval; both would otherwise not survive a reload.
    """

    def __init__(
        self,
        mapping: MutableMapping,
        *,
        codec: MappingCodec = DICT_CODEC,
        tiers_key: str = DEFAULT_TIERS_KEY,
    ) -> None:
        if _is_annotation_key(tiers_key):
            raise ValueError(
                f"tiers_key {tiers_key!r} looks like an annotation id; "
                "choose a key that is not a UUID string"
            )
        super().__init__()
        self._mapping = mapping
        self._codec = codec
        self._tiers_key = tiers_key
        self._ids: set[UUID] = set()
        self._load()

    # --- loading --------------------------------------------------------------

    def _load(self) -> None:
        for key in list(self._mapping):
            if key == self._tiers_key:
                for wire in self._codec.decode(self._mapping[key]).get("tiers", ()):
                    super().add_tier(Tier.from_wire(wire))
            elif _is_annotation_key(key):
                ann = Annotation.model_validate(self._codec.decode(self._mapping[key]))
                self._ids.add(ann.id)
                super().add(ann)
            else:
                raise ValueError(
                    f"MappingStore found foreign key {key!r} in the mapping: it is "
                    f"neither an annotation id nor the tiers key {self._tiers_key!r}. "
                    "Give the store a mapping (or sub-mapping) dedicated to it."
                )

    # --- write-through helpers ------------------------------------------------

    def _put(self, annotation: Annotation) -> None:
        self._mapping[str(annotation.id)] = self._codec.encode(
            annotation.model_dump(mode="json")
        )

    def _put_tiers(self, tiers: Iterable[Tier]) -> None:
        payload = {"tiers": [t.to_wire() for t in tiers]}
        self._mapping[self._tiers_key] = self._codec.encode(payload)

    # --- MutableMapping interface ---------------------------------------------

    def __setitem__(self, key: TimeInterval, value: list[Annotation]) -> None:
        value = list(value)
        for ann in value:
            if ann.interval != key:
                raise ValueError(
                    f"annotation {ann.id} has interval {ann.interval}, "
                    f"not the key {key}; it would not survive a reload"
                )
        new_ids = {a.id for a in value}
        if len(new_ids) != len(value):
            raise ValueError("duplicate annotation ids in value")
        old = self._buckets.get(_bucket_key(key), [])
        old_ids = {a.id for a in old}
        clash = (new_ids & self._ids) - old_ids
        if clash:
            raise ValueError(f"annotation id(s) already in the store: {sorted(map(str, clash))}")
        for ann in value:
            self._put(ann)
        for gone in old_ids - new_ids:
            del self._mapping[str(gone)]
        self._ids -= old_ids - new_ids
        self._ids |= new_ids
        super().__setitem__(key, value)

    def __delitem__(self, key: TimeInterval) -> None:
        bucket = self._buckets.get(_bucket_key(key))
        if bucket is None:
            raise KeyError(key)
        ids = [a.id for a in bucket]
        for i in ids:
            del self._mapping[str(i)]
        self._ids.difference_update(ids)
        super().__delitem__(key)

    # --- annotation-level -----------------------------------------------------

    def add(self, annotation: Annotation) -> None:
        if annotation.id in self._ids:
            raise ValueError(f"annotation id {annotation.id} already in the store")
        self._put(annotation)
        self._ids.add(annotation.id)
        super().add(annotation)

    def remove(self, annotation_id: UUID) -> Annotation | None:
        if annotation_id not in self._ids:
            return None
        del self._mapping[str(annotation_id)]
        self._ids.discard(annotation_id)
        return super().remove(annotation_id)

    # --- tier registry --------------------------------------------------------

    def add_tier(self, tier: Tier) -> None:
        merged = {t.name: t for t in self.tiers()}
        merged[tier.name] = tier
        self._put_tiers(merged.values())
        super().add_tier(tier)

    # --- lifecycle --------------------------------------------------------------

    def close(self) -> None:
        """No-op. Writes go through immediately and the mapping is the caller's.

        Present so code that calls ``store.close()`` after each use (as it does
        for ``SqliteStore``) can treat both alike; the store stays usable.
        """

    # --- misc -------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"MappingStore(<{len(self)} keys, {len(self._ids)} annotations, "
            f"over {type(self._mapping).__name__}>)"
        )

