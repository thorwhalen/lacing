"""Tests for the store-schema migration ladder (lacing#15).

Most upgrade tests register a *synthetic* v1 -> v2 step (replacing the real
stamp-only D5 step — re-registration is the registry's documented test
affordance; the autouse fixture restores it) against a restamped-to-v1 file,
optionally pretending the build is newer by monkeypatching
``lacing.store.sqlite.SCHEMA_VERSION``.
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

import lacing.store.migrations as store_migrations
import lacing.store.sqlite as sqlite_module
from lacing.cli import main as cli_main
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import (
    SQLITE_KIND,
    SchemaMismatchError,
    SqliteStore,
    StoreMigrationError,
    migrate_annot_file,
    reachable_versions,
    register_store_migration,
)
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Snapshot/restore the store-migration registry around every test."""
    snap = dict(store_migrations._STORE_MIGRATION_REGISTRY)
    try:
        yield
    finally:
        store_migrations._STORE_MIGRATION_REGISTRY.clear()
        store_migrations._STORE_MIGRATION_REGISTRY.update(snap)


def _ann(start: int, end: int, *, text: str) -> Annotation:
    return Annotation(
        id=uuid4(),
        tier="words",
        reference=MediaRef(
            asset_id="blake3:test",
            interval=TimeInterval(RationalTime(start), RationalTime(end)),
        ),
        body={"text": text},
        body_schema_uri="annot://schema/word/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="test",
            generated_at_time=RationalTime(0),
        ),
    )


def _write_current_file(path) -> list[Annotation]:
    """Create a current-version ``.annot`` file with content."""
    anns = [_ann(0, 100, text="hello"), _ann(100, 200, text="world")]
    with SqliteStore(path) as store:
        store.add_tier(Tier("words"))
        store.extend(anns)
    return anns


def _write_v1_file(path) -> list[Annotation]:
    """A genuine v1 ``.annot`` file with content.

    v1 and v2 share a byte-identical layout (the D5 bump is stamp-only), so
    a v1 file is a current file restamped."""
    anns = _write_current_file(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    return anns


def _pop_real_steps() -> None:
    """Remove the real registered sqlite steps (the registry fixture restores
    them) for tests that need 'no migration path exists'."""
    store_migrations._STORE_MIGRATION_REGISTRY.pop(
        (SQLITE_KIND, 1), None
    )


def _register_v1_to_v2():
    @register_store_migration(store_kind=SQLITE_KIND, from_version=1, to_version=2)
    def _to_v2(conn):
        conn.execute("ALTER TABLE annotations ADD COLUMN migration_marker TEXT")
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")

    return _to_v2


def _register_stamp_only_v1_to_v2():
    @register_store_migration(store_kind=SQLITE_KIND, from_version=1, to_version=2)
    def _stamp(conn):
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")


def _pretend_build_expects(monkeypatch, version: int) -> None:
    monkeypatch.setattr(sqlite_module, "SCHEMA_VERSION", version)


class TestUpgradeOnOpen:
    def test_v1_file_upgrades_and_round_trips_with_every_annotation(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "a.annot"
        original = _write_v1_file(path)
        _register_v1_to_v2()
        _pretend_build_expects(monkeypatch, 2)

        with SqliteStore(path, migrate=True) as store:
            assert store.schema_version == 2
            migrated = sorted(store.all(), key=lambda a: str(a.id))

        # Full annotation equality, not counts (lacing#15 acceptance).
        assert migrated == sorted(original, key=lambda a: str(a.id))

    def test_opening_a_stale_file_without_opting_in_refuses_and_names_the_path(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _register_v1_to_v2()
        _pretend_build_expects(monkeypatch, 2)

        with pytest.raises(SchemaMismatchError) as exc:
            SqliteStore(path)
        message = str(exc.value)
        assert "migrate=True" in message
        assert "lacing migrate" in message

    def test_a_refused_open_does_not_touch_the_file(self, tmp_path, monkeypatch):
        """The old code ran the current build's DDL *before* the version
        check, so refusing still mutated the stale file. It must not."""
        path = tmp_path / "a.annot"
        original = _write_v1_file(path)
        tables_before = _table_names(path)
        _pop_real_steps()  # note: no step registered

        with pytest.raises(SchemaMismatchError) as exc:
            SqliteStore(path)
        assert "No registered migration reaches v2" in str(exc.value)

        assert _table_names(path) == tables_before
        assert _stamped_version(path) == 1
        _register_stamp_only_v1_to_v2()
        with SqliteStore(path, migrate=True) as store:
            assert store.schema_version == 2
            assert sorted(store.all(), key=lambda a: str(a.id)) == sorted(
                original, key=lambda a: str(a.id)
            )

    def test_a_file_newer_than_the_build_refuses_forward_only(self, tmp_path):
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")

        with pytest.raises(SchemaMismatchError) as exc:
            SqliteStore(path, migrate=True)
        assert "newer than this build" in str(exc.value)


class TestLadderMechanics:
    def test_already_current_store_is_a_noop(self, tmp_path):
        path = tmp_path / "a.annot"
        _write_current_file(path)

        current = sqlite_module.SCHEMA_VERSION
        assert migrate_annot_file(path) == (current, current)

    def test_migration_is_idempotent(self, tmp_path, monkeypatch):
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _register_v1_to_v2()
        _pretend_build_expects(monkeypatch, 2)

        assert migrate_annot_file(path) == (1, 2)
        assert migrate_annot_file(path) == (2, 2)

    def test_a_missing_step_raises_naming_the_step(self, tmp_path, monkeypatch):
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _register_v1_to_v2()  # 1 -> 2 exists, 2 -> 3 does not
        _pretend_build_expects(monkeypatch, 3)

        with pytest.raises(StoreMigrationError, match=r"sqlite v2 -> v3"):
            migrate_annot_file(path)
        # The chain stopped at the last completed step, resumably.
        assert _stamped_version(path) == 2

    def test_a_step_that_forgets_to_stamp_rolls_back_and_stays_repairable(
        self, tmp_path, monkeypatch
    ):
        """The stamp is verified INSIDE the step's transaction: a forgetful
        step must leave the file byte-equivalent (no committed DDL, version
        unchanged) so the fixed step can simply run again — not wedge on
        'duplicate column'."""
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _pretend_build_expects(monkeypatch, 2)

        @register_store_migration(store_kind=SQLITE_KIND, from_version=1, to_version=2)
        def _forgets(conn):
            conn.execute("ALTER TABLE annotations ADD COLUMN migration_marker TEXT")

        with pytest.raises(StoreMigrationError, match="without stamping"):
            migrate_annot_file(path)

        assert _stamped_version(path) == 1
        assert "migration_marker" not in _annotation_columns(path)

        _register_v1_to_v2()  # the corrected step
        assert migrate_annot_file(path) == (1, 2)

    def test_a_step_that_uses_executescript_fails_loudly(self, tmp_path, monkeypatch):
        """executescript implicitly commits the wrapper's transaction; the
        runner must detect the breach and name the cause instead of
        reporting a bogus rollback error."""
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _pretend_build_expects(monkeypatch, 2)

        @register_store_migration(store_kind=SQLITE_KIND, from_version=1, to_version=2)
        def _scripted(conn):
            conn.executescript(
                "ALTER TABLE annotations ADD COLUMN migration_marker TEXT;"
            )

        with pytest.raises(StoreMigrationError, match="executescript"):
            migrate_annot_file(path)

    def test_a_racing_migrator_that_already_won_is_detected_under_the_lock(
        self, tmp_path
    ):
        """The version is re-read inside BEGIN IMMEDIATE: a step whose work
        another process already committed is skipped, never re-applied
        (the multi-worker migrate-on-open scenario)."""
        from lacing.store.migrations import _sqlite_run_step

        path = tmp_path / "a.annot"
        _write_v1_file(path)
        with sqlite3.connect(path) as raw:
            raw.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")

        conn = sqlite3.connect(path, isolation_level=None)
        try:
            ran = []
            reached = _sqlite_run_step(conn, 1, 2, lambda c: ran.append(1))
        finally:
            conn.close()

        assert reached == 2
        assert ran == []  # the step body never executed

    def test_a_step_that_desyncs_the_rtree_rolls_back(self, tmp_path, monkeypatch):
        """The in-transaction integrity gate: an index row pointing nowhere
        fails the step before COMMIT."""
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _pretend_build_expects(monkeypatch, 2)

        @register_store_migration(store_kind=SQLITE_KIND, from_version=1, to_version=2)
        def _desyncs(conn):
            conn.execute(
                "INSERT INTO annotations_rtree (rowid, start_seconds, end_seconds) "
                "VALUES (999999, 0.0, 1.0)"
            )
            conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")

        with pytest.raises(StoreMigrationError, match="annotations_rtree"):
            migrate_annot_file(path)
        assert _stamped_version(path) == 1

    def test_rebuild_annotations_rtree_restores_interval_queries(
        self, tmp_path, monkeypatch
    ):
        """The helper a table-rebuilding step (lacing#14) will lean on: after
        a wiped index, rebuild + migrate leaves interval queries working."""
        from lacing.store import rebuild_annotations_rtree
        from lacing.time import RationalTime, TimeInterval

        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _pretend_build_expects(monkeypatch, 2)

        @register_store_migration(store_kind=SQLITE_KIND, from_version=1, to_version=2)
        def _rebuilds(conn):
            conn.execute("DELETE FROM annotations_rtree")
            assert rebuild_annotations_rtree(conn) == 2
            conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")

        assert migrate_annot_file(path) == (1, 2)
        with SqliteStore(path) as store:
            hits = list(
                store.intersects(TimeInterval(RationalTime(0), RationalTime(150)))
            )
        assert len(hits) == 2

    def test_a_missing_file_is_refused_without_creating_junk(self, tmp_path):
        path = tmp_path / "typo.annot"

        with pytest.raises(StoreMigrationError, match="no such file"):
            migrate_annot_file(path)
        assert not path.exists()  # connecting would have created a 0-byte DB

    def test_open_time_migration_failure_keeps_the_documented_error_type(
        self, tmp_path, monkeypatch
    ):
        """SqliteStore's contract is SchemaMismatchError on any open-time
        schema failure; the ladder's error rides along as the cause."""
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _pop_real_steps()  # no step registered

        with pytest.raises(SchemaMismatchError) as exc:
            SqliteStore(path, migrate=True)
        assert isinstance(exc.value.__cause__, StoreMigrationError)

    def test_a_failing_step_rolls_back_leaving_the_file_at_v1(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "a.annot"
        original = _write_v1_file(path)
        _pretend_build_expects(monkeypatch, 2)

        @register_store_migration(store_kind=SQLITE_KIND, from_version=1, to_version=2)
        def _explodes(conn):
            conn.execute("ALTER TABLE annotations ADD COLUMN migration_marker TEXT")
            raise RuntimeError("boom mid-step")

        with pytest.raises(StoreMigrationError, match="boom mid-step"):
            migrate_annot_file(path)

        assert _stamped_version(path) == 1  # the failed step rolled back
        _register_stamp_only_v1_to_v2()  # the corrected step
        monkeypatch.undo()
        with SqliteStore(path, migrate=True) as store:
            assert sorted(store.all(), key=lambda a: str(a.id)) == sorted(
                original, key=lambda a: str(a.id)
            )

    def test_registration_must_be_single_step(self):
        with pytest.raises(ValueError, match="single-step"):
            register_store_migration(
                store_kind=SQLITE_KIND, from_version=1, to_version=3
            )

    def test_reachable_versions_follows_the_chain(self):
        _register_v1_to_v2()

        @register_store_migration(store_kind=SQLITE_KIND, from_version=2, to_version=3)
        def _to_v3(conn):  # pragma: no cover — registry-shape test only
            pass

        assert reachable_versions(SQLITE_KIND, 1) == (2, 3)
        assert reachable_versions(SQLITE_KIND, 3) == ()
        assert reachable_versions("postgres", 2) == ()


class TestCli:
    def test_cli_migrates_a_stale_file(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _register_v1_to_v2()
        _pretend_build_expects(monkeypatch, 2)

        cli_main(["migrate", str(path)])

        assert "1 -> 2" in capsys.readouterr().out
        assert _stamped_version(path) == 2

    def test_cli_reports_the_noop(self, tmp_path, capsys):
        path = tmp_path / "a.annot"
        _write_current_file(path)

        cli_main(["migrate", str(path)])

        assert "nothing to do" in capsys.readouterr().out

    def test_cli_fails_cleanly_when_no_migration_path_exists(
        self, tmp_path, monkeypatch, capsys
    ):
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _pop_real_steps()  # no step registered

        with pytest.raises(SystemExit):
            cli_main(["migrate", str(path)])

        assert "no store migration registered" in capsys.readouterr().err

    def test_cli_refuses_a_nonexistent_file_without_creating_it(
        self, tmp_path, capsys
    ):
        path = tmp_path / "typo.annot"

        with pytest.raises(SystemExit):
            cli_main(["migrate", str(path)])

        assert "no such file" in capsys.readouterr().err
        assert not path.exists()

    def test_cli_to_version_upgrades_partway(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "a.annot"
        _write_v1_file(path)
        _register_v1_to_v2()
        _pretend_build_expects(monkeypatch, 3)

        cli_main(["migrate", str(path), "--to-version", "2"])

        assert "1 -> 2" in capsys.readouterr().out
        assert _stamped_version(path) == 2


def _table_names(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {r[0] for r in rows}


def _annotation_columns(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute("PRAGMA table_info(annotations)").fetchall()
    return {r[1] for r in rows}


def _stamped_version(path) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    return int(row[0])


class TestD5Migration:
    """The real v1→v2 step (lacing#14): stamp-only, data untouched."""

    def test_a_v1_file_upgrades_stamp_only_and_round_trips_every_annotation(
        self, tmp_path
    ):
        """The lacing#14 acceptance: a genuine v1 file (UUID-only provenance)
        opens, upgrades, and round-trips at v2 with every annotation equal.
        v1 and v2 share a byte-identical layout — only the stamp differs —
        so the file is built normally and restamped to 1."""
        path = tmp_path / "a.annot"
        original = _write_v1_file(path)
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")

        assert migrate_annot_file(path) == (1, 2)

        with SqliteStore(path) as store:
            assert store.schema_version == 2
            assert sorted(store.all(), key=lambda a: str(a.id)) == sorted(
                original, key=lambda a: str(a.id)
            )

    def test_a_v2_store_round_trips_mixed_provenance_refs(self, tmp_path):
        """The point of v2: an annotation deriving from an artifact asset_id
        AND an annotation UUID persists and reads back losslessly."""
        from lacing.model import partition_provenance_refs

        path = tmp_path / "a.annot"
        parent = _ann(0, 100, text="parent")
        asset = "e" * 64
        child = parent.model_copy(
            update={
                "id": uuid4(),
                "provenance": parent.provenance.model_copy(
                    update={"was_derived_from": [parent.id, asset]}
                )
            }
        )
        with SqliteStore(path) as store:
            store.add_tier(Tier("words"))
            store.extend([parent, child])

        with SqliteStore(path) as store:
            got = {a.id: a for a in store.all()}[child.id]

        annotation_ids, asset_ids = partition_provenance_refs(
            got.provenance.was_derived_from
        )
        assert annotation_ids == [parent.id]
        assert asset_ids == [asset]
