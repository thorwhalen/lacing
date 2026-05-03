"""Tests for ``lacing.schema``.

Covers URI parsing, registry, validation, JSON Schema export, and
migrations. Built-in body schemas under ``lacing.bodies`` are imported
indirectly to verify the public registry surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from lacing import schema as lacing_schema
from lacing.schema import (
    BodySchemaError,
    MigrationError,
    UnknownBodySchemaError,
    export_json_schemas,
    get_body_schema,
    is_registered,
    json_schema,
    latest_version,
    make_uri,
    migrate,
    migrate_to_latest,
    parse_uri,
    register_body_schema,
    register_migration,
    registered_uris,
    validate,
)


@pytest.fixture(autouse=True)
def isolated_registry():
    """Snapshot + restore the global registry around each test.

    Forces ``lacing.bodies`` import first so the built-in schemas are in
    the snapshot — otherwise, depending on test order, they could be
    cleared by a prior test's snapshot restoration.
    """
    import lacing.bodies  # noqa: F401  ensures built-ins are registered

    body_snap = dict(lacing_schema._BODY_REGISTRY)
    mig_snap = dict(lacing_schema._MIGRATION_REGISTRY)
    try:
        yield
    finally:
        lacing_schema._BODY_REGISTRY.clear()
        lacing_schema._BODY_REGISTRY.update(body_snap)
        lacing_schema._MIGRATION_REGISTRY.clear()
        lacing_schema._MIGRATION_REGISTRY.update(mig_snap)


# ---------------------------------------------------------------------------
# Sample body schemas (test-local — never collide with built-ins)
# ---------------------------------------------------------------------------


class _DummyV1(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}
    text: str
    confidence: float | None = None


class _DummyV2(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}
    text: str
    confidence: float | None = None
    speaker: str | None = None


# ---------------------------------------------------------------------------
# URI parsing
# ---------------------------------------------------------------------------


class TestUri:
    def test_parse_valid(self):
        assert parse_uri("annot://schema/word/v1") == ("word", 1)
        assert parse_uri("annot://schema/named-entity/v42") == ("named-entity", 42)

    def test_parse_invalid_shape(self):
        for bad in [
            "annot://schema/bad",
            "annot://schema/bad/v",
            "annot://schema/Bad/v1",   # uppercase rejected
            "annot://schema/bad_name/v1",  # underscore rejected
            "annot://schema/bad/V1",   # capital V rejected
            "https://example/schema/word/v1",
        ]:
            with pytest.raises(ValueError):
                parse_uri(bad)

    def test_make_uri(self):
        assert make_uri("word", 1) == "annot://schema/word/v1"
        assert make_uri("named-entity", 3) == "annot://schema/named-entity/v3"

    def test_make_uri_rejects_invalid_name(self):
        with pytest.raises(ValueError):
            make_uri("Bad", 1)
        with pytest.raises(ValueError):
            make_uri("bad_name", 1)

    def test_make_uri_rejects_zero_or_negative_version(self):
        with pytest.raises(ValueError):
            make_uri("word", 0)
        with pytest.raises(ValueError):
            make_uri("word", -1)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_and_get(self):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        assert get_body_schema("annot://schema/dummy/v1") is _DummyV1

    def test_register_returns_model(self):
        result = register_body_schema("annot://schema/dummy/v1", _DummyV1)
        assert result is _DummyV1

    def test_register_invalid_uri(self):
        with pytest.raises(ValueError):
            register_body_schema("not-a-uri", _DummyV1)

    def test_register_non_basemodel_rejected(self):
        class NotABaseModel:
            pass

        with pytest.raises(TypeError):
            register_body_schema("annot://schema/dummy/v1", NotABaseModel)

    def test_get_unknown_raises(self):
        with pytest.raises(UnknownBodySchemaError):
            get_body_schema("annot://schema/never/v1")

    def test_is_registered(self):
        assert not is_registered("annot://schema/dummy/v1")
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        assert is_registered("annot://schema/dummy/v1")

    def test_registered_uris_sorted(self):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        register_body_schema("annot://schema/dummy/v2", _DummyV2)
        uris = registered_uris()
        assert "annot://schema/dummy/v1" in uris
        assert "annot://schema/dummy/v2" in uris
        assert uris == sorted(uris)

    def test_re_registration_replaces(self):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        register_body_schema("annot://schema/dummy/v1", _DummyV2)
        # Last wins.
        assert get_body_schema("annot://schema/dummy/v1") is _DummyV2


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_body(self):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        result = validate({"text": "hi"}, "annot://schema/dummy/v1")
        assert isinstance(result, _DummyV1)
        assert result.text == "hi"

    def test_invalid_body_raises(self):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        with pytest.raises(BodySchemaError):
            validate({"text": 123}, "annot://schema/dummy/v1")  # text must be str

    def test_extra_field_rejected(self):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        with pytest.raises(BodySchemaError):
            validate({"text": "hi", "bogus": True}, "annot://schema/dummy/v1")

    def test_unknown_uri_raises(self):
        with pytest.raises(UnknownBodySchemaError):
            validate({"text": "hi"}, "annot://schema/never/v1")


# ---------------------------------------------------------------------------
# JSON Schema export
# ---------------------------------------------------------------------------


class TestJsonSchemaExport:
    def test_json_schema_returns_dict(self):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        schema = json_schema("annot://schema/dummy/v1")
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "text" in schema["properties"]

    def test_json_schema_unknown_raises(self):
        with pytest.raises(UnknownBodySchemaError):
            json_schema("annot://schema/missing/v1")

    def test_export_writes_files(self, tmp_path):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        register_body_schema("annot://schema/dummy/v2", _DummyV2)

        written = export_json_schemas(tmp_path)
        # The two we just added must be in the result; built-ins are too.
        assert (tmp_path / "dummy" / "v1.json") in written
        assert (tmp_path / "dummy" / "v2.json") in written

        v1_path = tmp_path / "dummy" / "v1.json"
        v2_path = tmp_path / "dummy" / "v2.json"
        assert v1_path.exists()
        assert v2_path.exists()

        v1_data = json.loads(v1_path.read_text())
        assert "text" in v1_data["properties"]

        v2_data = json.loads(v2_path.read_text())
        assert "speaker" in v2_data["properties"]

    def test_export_writes_index(self, tmp_path):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        export_json_schemas(tmp_path)
        index = json.loads((tmp_path / "index.json").read_text())
        assert "annot://schema/dummy/v1" in index
        entry = index["annot://schema/dummy/v1"]
        assert entry["name"] == "dummy"
        assert entry["version"] == "1"
        assert entry["path"] == "dummy/v1.json"

    def test_export_overwrite_default(self, tmp_path):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        export_json_schemas(tmp_path)
        # Second run should succeed (default overwrite=True).
        export_json_schemas(tmp_path)

    def test_export_overwrite_false_raises(self, tmp_path):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        export_json_schemas(tmp_path)
        with pytest.raises(FileExistsError):
            export_json_schemas(tmp_path, overwrite=False)

    def test_export_skip_meta(self, tmp_path):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        export_json_schemas(tmp_path, include_meta=False)
        assert not (tmp_path / "index.json").exists()


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


class TestMigrations:
    def _setup_dummy(self):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        register_body_schema("annot://schema/dummy/v2", _DummyV2)

        @register_migration(schema_name="dummy", from_version=1, to_version=2)
        def _v1_to_v2(body: dict) -> dict:
            return {**body, "speaker": None}

        return _v1_to_v2

    def test_register_and_apply_single_step(self):
        self._setup_dummy()
        out = migrate(
            {"text": "hi", "confidence": 0.9},
            from_uri="annot://schema/dummy/v1",
            to_uri="annot://schema/dummy/v2",
        )
        assert out == {"text": "hi", "confidence": 0.9, "speaker": None}

    def test_no_op_same_version(self):
        self._setup_dummy()
        out = migrate(
            {"text": "hi"},
            from_uri="annot://schema/dummy/v1",
            to_uri="annot://schema/dummy/v1",
        )
        assert out == {"text": "hi"}
        # Defensive copy
        out["text"] = "modified"
        assert out["text"] == "modified"

    def test_backwards_rejected(self):
        self._setup_dummy()
        with pytest.raises(MigrationError):
            migrate(
                {"text": "hi"},
                from_uri="annot://schema/dummy/v2",
                to_uri="annot://schema/dummy/v1",
            )

    def test_cross_schema_rejected(self):
        self._setup_dummy()
        register_body_schema("annot://schema/other/v1", _DummyV1)
        with pytest.raises(MigrationError):
            migrate(
                {"text": "hi"},
                from_uri="annot://schema/dummy/v1",
                to_uri="annot://schema/other/v1",
            )

    def test_missing_step_raises(self):
        # v1 + v3 registered, no migrations.
        register_body_schema("annot://schema/sparse/v1", _DummyV1)
        register_body_schema("annot://schema/sparse/v3", _DummyV2)
        with pytest.raises(MigrationError):
            migrate(
                {"text": "hi"},
                from_uri="annot://schema/sparse/v1",
                to_uri="annot://schema/sparse/v3",
            )

    def test_register_rejects_non_consecutive(self):
        with pytest.raises(ValueError):
            register_migration(
                schema_name="dummy", from_version=1, to_version=3
            )

    def test_chain_of_migrations(self):
        # Build a v1 -> v2 -> v3 chain
        register_body_schema("annot://schema/chain/v1", _DummyV1)
        register_body_schema("annot://schema/chain/v2", _DummyV2)
        register_body_schema("annot://schema/chain/v3", _DummyV2)

        @register_migration(schema_name="chain", from_version=1, to_version=2)
        def _step1(body: dict) -> dict:
            return {**body, "step1": True}

        @register_migration(schema_name="chain", from_version=2, to_version=3)
        def _step2(body: dict) -> dict:
            return {**body, "step2": True}

        out = migrate(
            {"text": "hi"},
            from_uri="annot://schema/chain/v1",
            to_uri="annot://schema/chain/v3",
        )
        assert out == {"text": "hi", "step1": True, "step2": True}

    def test_migration_function_failure_wraps(self):
        register_body_schema("annot://schema/dummy/v1", _DummyV1)
        register_body_schema("annot://schema/dummy/v2", _DummyV2)

        @register_migration(schema_name="dummy", from_version=1, to_version=2)
        def _broken(body: dict) -> dict:
            raise RuntimeError("boom")

        with pytest.raises(MigrationError, match="boom"):
            migrate(
                {"text": "hi"},
                from_uri="annot://schema/dummy/v1",
                to_uri="annot://schema/dummy/v2",
            )

    def test_migrate_to_latest(self):
        self._setup_dummy()
        out, target = migrate_to_latest(
            {"text": "hi"}, from_uri="annot://schema/dummy/v1"
        )
        assert target == "annot://schema/dummy/v2"
        assert out["speaker"] is None


class TestLatestVersion:
    def test_with_registered_versions(self):
        register_body_schema("annot://schema/foo/v1", _DummyV1)
        register_body_schema("annot://schema/foo/v3", _DummyV2)
        register_body_schema("annot://schema/foo/v2", _DummyV1)
        assert latest_version("foo") == 3

    def test_no_versions_returns_none(self):
        assert latest_version("never-registered") is None


# ---------------------------------------------------------------------------
# Built-in bodies
# ---------------------------------------------------------------------------


class TestBuiltinBodies:
    """Importing ``lacing.bodies`` should self-register the built-ins."""

    def test_word_v1_registered(self):
        import lacing.bodies  # noqa: F401  registers
        from lacing.bodies.word import WordBodyV1

        assert get_body_schema("annot://schema/word/v1") is WordBodyV1
        validated = validate({"text": "hello"}, "annot://schema/word/v1")
        assert validated.text == "hello"

    def test_named_entity_v1_and_v2_registered(self):
        import lacing.bodies  # noqa: F401  registers

        assert is_registered("annot://schema/named-entity/v1")
        assert is_registered("annot://schema/named-entity/v2")

    def test_named_entity_migration_v1_to_v2(self):
        import lacing.bodies  # noqa: F401  registers

        out = migrate(
            {"type": "PER", "text": "Alice"},
            from_uri="annot://schema/named-entity/v1",
            to_uri="annot://schema/named-entity/v2",
        )
        assert out == {"entity_type": "PER", "text": "Alice"}
        # And v2 validates the migrated body.
        validate(out, "annot://schema/named-entity/v2")
