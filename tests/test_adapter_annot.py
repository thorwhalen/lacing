"""Tests for the ``.annot`` portable file format adapter."""

from __future__ import annotations

from uuid import uuid4

import pytest

from lacing.adapters import find_adapter, get_adapter
from lacing.adapters import annot as adapter_module  # noqa: F401  registers
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore, SqliteStore
from lacing.tier import Tier, TierStereotype
from lacing.time import RationalTime, TimeInterval


def _ti(s: int, e: int) -> TimeInterval:
    return TimeInterval(RationalTime(s), RationalTime(e))


def _ann(interval: TimeInterval, *, tier: str = "words", text: str = "x", confidence: float | None = None) -> Annotation:
    return Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(asset_id="blake3:test", interval=interval),
        body={"text": text},
        body_schema_uri="annot://schema/word/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime(0),
        ),
        confidence=confidence,
    )


def _populated_memory_store() -> MemoryStore:
    s = MemoryStore()
    s.add_tier(Tier("words"))
    s.add_tier(
        Tier("phonemes", stereotype=TierStereotype.TIME_SUBDIVISION, parent="words")
    )
    s.add(_ann(_ti(0, 100), tier="words", text="hello"))
    s.add(_ann(_ti(0, 50), tier="phonemes", text="he"))
    s.add(_ann(_ti(50, 100), tier="phonemes", text="llo"))
    s.add(_ann(_ti(100, 200), tier="words", text="world", confidence=0.85))
    return s


# --- registry --------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        assert get_adapter("annot").name == "annot"

    def test_lookup_by_extension(self):
        assert find_adapter(extension=".annot") is not None


# --- dump + load round-trip -----------------------------------------------


class TestRoundTrip:
    def test_to_path_and_back(self, tmp_path):
        original = _populated_memory_store()
        path = tmp_path / "rt.annot"
        adapter_module.dump(original, path)
        loaded = adapter_module.load(path)

        original_anns = sorted(
            (a.tier, a.body["text"], a.interval.start.value, a.interval.end.value, a.confidence)
            for a in original.all()
        )
        loaded_anns = sorted(
            (a.tier, a.body["text"], a.interval.start.value, a.interval.end.value, a.confidence)
            for a in loaded.all()
        )
        assert original_anns == loaded_anns

    def test_to_bytes_and_back(self):
        original = _populated_memory_store()
        blob = adapter_module.dump(original)
        assert isinstance(blob, bytes)
        # SQLite files start with this magic header.
        assert blob[:16].rstrip(b"\x00").startswith(b"SQLite format 3")
        loaded = adapter_module.load(blob)
        assert len(list(loaded.all())) == len(list(original.all()))

    def test_tier_metadata_preserved(self, tmp_path):
        original = MemoryStore()
        original.add_tier(Tier("words", metadata={"lang": "en"}))
        original.add(_ann(_ti(0, 10), tier="words"))
        path = tmp_path / "tier.annot"
        adapter_module.dump(original, path)

        loaded = adapter_module.load(path)
        loaded_tier = loaded.get_tier("words")
        assert loaded_tier is not None
        assert loaded_tier.metadata == {"lang": "en"}

    def test_tier_stereotype_preserved(self, tmp_path):
        original = MemoryStore()
        original.add_tier(Tier("words"))
        original.add_tier(
            Tier("phonemes", stereotype=TierStereotype.TIME_SUBDIVISION, parent="words")
        )
        path = tmp_path / "stereo.annot"
        adapter_module.dump(original, path)

        loaded = adapter_module.load(path)
        ph = loaded.get_tier("phonemes")
        assert ph is not None
        assert ph.stereotype == TierStereotype.TIME_SUBDIVISION
        assert ph.parent == "words"


# --- non-overwrite behavior ------------------------------------------------


class TestOverwrite:
    def test_overwrite_default_replaces(self, tmp_path):
        path = tmp_path / "x.annot"
        adapter_module.dump(_populated_memory_store(), path)
        # Second dump must succeed by default
        adapter_module.dump(_populated_memory_store(), path)
        assert path.exists()

    def test_overwrite_false_raises(self, tmp_path):
        path = tmp_path / "x.annot"
        adapter_module.dump(_populated_memory_store(), path)
        with pytest.raises(FileExistsError):
            adapter_module.dump(_populated_memory_store(), path, overwrite=False)


# --- persistent vs snapshot mode ------------------------------------------


class TestPersistentMode:
    def test_default_returns_memory_store(self, tmp_path):
        path = tmp_path / "snap.annot"
        adapter_module.dump(_populated_memory_store(), path)
        loaded = adapter_module.load(path)
        assert isinstance(loaded, MemoryStore)

    def test_persistent_returns_sqlite_store(self, tmp_path):
        path = tmp_path / "live.annot"
        adapter_module.dump(_populated_memory_store(), path)
        loaded = adapter_module.load(path, persistent=True)
        try:
            assert isinstance(loaded, SqliteStore)
            # Mutating goes straight to disk.
            loaded.add(_ann(_ti(500, 600), tier="words", text="new"))
        finally:
            loaded.close()

        # Reopen and confirm the new annotation is there.
        again = adapter_module.load(path)
        texts = {a.body["text"] for a in again.all()}
        assert "new" in texts


# --- copy-fast path when source is already SqliteStore --------------------


class TestSqliteSourceFastPath:
    def test_copies_file(self, tmp_path):
        src_path = tmp_path / "src.annot"
        src = SqliteStore(src_path)
        try:
            src.add_tier(Tier("words"))
            src.add(_ann(_ti(0, 100), tier="words"))
        finally:
            src.close()

        # Reopen, dump to a new path.
        src = SqliteStore(src_path)
        try:
            dst_path = tmp_path / "dst.annot"
            adapter_module.dump(src, dst_path)
        finally:
            src.close()

        assert dst_path.exists()
        loaded = adapter_module.load(dst_path)
        assert len(list(loaded.all())) == 1


class TestV1FileHandling:
    """The adapter honors the store's migration contract (lacing#14 review)."""

    def _v1_file(self, tmp_path):
        import sqlite3

        path = tmp_path / "old.annot"
        store = SqliteStore(path)
        store.add_tier(Tier("words"))
        store.add(_ann(_ti(0, 10), tier="words", text="hi"))
        store.close()
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
        return path

    def test_a_v1_path_refuses_without_the_opt_in_and_loads_with_it(self, tmp_path):
        from lacing.store import SchemaMismatchError

        path = self._v1_file(tmp_path)
        adapter = get_adapter("annot")

        with pytest.raises(SchemaMismatchError):
            adapter.load(str(path))

        loaded = adapter.load(str(path), migrate=True)
        assert len(list(loaded.all())) == 1

    def test_v1_bytes_load_migrates_the_temp_copy(self, tmp_path):
        """Bytes are not the caller's file: refusing them would be a dead
        end (no path to point `lacing migrate` at), so the temp copy is
        migrated unconditionally."""
        path = self._v1_file(tmp_path)
        payload = path.read_bytes()

        loaded = get_adapter("annot").load(payload)

        assert len(list(loaded.all())) == 1
