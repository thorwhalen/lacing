"""Body schema registry, JSON Schema export, and migrations.

Every annotation's ``body`` is validated against the schema named by its
``body_schema_uri`` (semver: ``annot://schema/<name>/v<major>``). This
module implements:

- :func:`register_body_schema` — register a Pydantic v2 model for a schema URI.
- :func:`validate` — validate an annotation's body dict against its schema.
- :func:`json_schema` — get the JSON Schema for a registered URI.
- :func:`export_json_schemas` — write all JSON Schema artifacts to disk
  (under ``lacing/schema/<name>/v<N>.json`` by default), the upstream
  for ``json-schema-to-zod`` codegen.
- :func:`register_migration` — register a forward migration from version
  N to N+1 of a body schema.
- :func:`migrate` — upgrade a body dict (or whole annotation) through
  registered migrations.

See the ``lacing-schema-codegen`` skill and BACK-DOC §4.5.

Usage example::

    from pydantic import BaseModel, Field
    from lacing.schema import register_body_schema, register_migration

    class WordBodyV1(BaseModel):
        model_config = {"frozen": True, "extra": "forbid"}
        text: str = Field(..., description="The word's surface form.")

    register_body_schema("annot://schema/word/v1", WordBodyV1)

    class WordBodyV2(BaseModel):
        model_config = {"frozen": True, "extra": "forbid"}
        text: str = Field(..., description="The word's surface form.")
        normalized: str | None = Field(None, description="Normalized form.")

    register_body_schema("annot://schema/word/v2", WordBodyV2)

    @register_migration(schema_name="word", from_version=1, to_version=2)
    def v1_to_v2(body: dict) -> dict:
        return {**body, "normalized": None}
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError


# ---------------------------------------------------------------------------
# URI parsing
# ---------------------------------------------------------------------------


_URI_RE = re.compile(r"^annot://schema/([a-z0-9-]+)/v(\d+)$")


def parse_uri(uri: str) -> tuple[str, int]:
    """Split ``annot://schema/<name>/v<major>`` into ``(name, major)``.

    Raises ``ValueError`` on malformed input.
    """
    m = _URI_RE.match(uri)
    if m is None:
        raise ValueError(
            f"invalid body_schema_uri {uri!r}; "
            "expected ``annot://schema/<name>/v<major>``"
        )
    return m.group(1), int(m.group(2))


def make_uri(name: str, version: int) -> str:
    """Build a ``body_schema_uri`` from a name and major version."""
    if not re.match(r"^[a-z0-9-]+$", name):
        raise ValueError(
            f"schema name {name!r} must be kebab-case (lowercase + digits + hyphens)"
        )
    if version < 1:
        raise ValueError(f"version must be >= 1, got {version}")
    return f"annot://schema/{name}/v{version}"


# ---------------------------------------------------------------------------
# body schema registry
# ---------------------------------------------------------------------------


# uri -> Pydantic model class
_BODY_REGISTRY: dict[str, type[BaseModel]] = {}


class BodySchemaError(ValueError):
    """Raised when a body fails validation against its registered schema."""


class UnknownBodySchemaError(KeyError):
    """Raised when an annotation's body_schema_uri has no registered model."""


def register_body_schema(uri: str, model: type[BaseModel]) -> type[BaseModel]:
    """Register ``model`` as the validator for ``uri``. Returns ``model``."""
    parse_uri(uri)  # validate URI shape; raises on malformed
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise TypeError(
            f"register_body_schema expects a Pydantic v2 BaseModel subclass; "
            f"got {model!r}"
        )
    _BODY_REGISTRY[uri] = model
    return model


def get_body_schema(uri: str) -> type[BaseModel]:
    """Look up the registered Pydantic model for ``uri``."""
    if uri not in _BODY_REGISTRY:
        raise UnknownBodySchemaError(uri)
    return _BODY_REGISTRY[uri]


def is_registered(uri: str) -> bool:
    return uri in _BODY_REGISTRY


def registered_uris() -> list[str]:
    """All currently registered ``body_schema_uri`` values, sorted."""
    return sorted(_BODY_REGISTRY)


def clear_registry() -> None:
    """Drop every registered body schema and migration. For tests / repls."""
    _BODY_REGISTRY.clear()
    _MIGRATION_REGISTRY.clear()


def validate(body: dict, uri: str) -> BaseModel:
    """Validate ``body`` against the schema registered for ``uri``.

    Returns the parsed Pydantic instance. Raises :class:`BodySchemaError`
    on validation failure (wrapping the underlying ``pydantic.ValidationError``)
    or :class:`UnknownBodySchemaError` if the URI isn't registered.
    """
    model = get_body_schema(uri)
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        raise BodySchemaError(f"body failed validation against {uri}:\n{exc}") from exc


# ---------------------------------------------------------------------------
# JSON Schema export
# ---------------------------------------------------------------------------


def json_schema(uri: str) -> dict:
    """Return the JSON Schema for the body model registered at ``uri``.

    Pydantic's ``model_json_schema()`` output, unmodified.
    """
    return get_body_schema(uri).model_json_schema()


def export_json_schemas(
    target_dir: str | Path,
    *,
    overwrite: bool = True,
    include_meta: bool = True,
) -> list[Path]:
    """Write every registered schema as JSON files under ``target_dir``.

    Layout: ``<target_dir>/<name>/v<N>.json``. Returns the list of paths
    written, in registration order.

    Args:
        target_dir: Output directory. Created if missing.
        overwrite: If False, refuse to write a file that already exists.
        include_meta: If True, also write a ``<target_dir>/index.json``
            mapping every URI to its file path and the Pydantic model's
            qualified name (helps the codegen pipeline).
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    index: dict[str, dict[str, str]] = {}

    for uri in registered_uris():
        name, version = parse_uri(uri)
        out_dir = target / name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"v{version}.json"
        if out_path.exists() and not overwrite:
            raise FileExistsError(out_path)

        schema = json_schema(uri)
        out_path.write_text(json.dumps(schema, indent=2, sort_keys=False) + "\n")
        written.append(out_path)

        model = get_body_schema(uri)
        index[uri] = {
            "name": name,
            "version": str(version),
            "path": str(out_path.relative_to(target)),
            "model": f"{model.__module__}.{model.__qualname__}",
        }

    if include_meta:
        index_path = target / "index.json"
        index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
        written.append(index_path)

    return written


# ---------------------------------------------------------------------------
# migrations
# ---------------------------------------------------------------------------


# Maps (schema_name, from_version) -> (to_version, callable(body) -> body).
# We restrict to from→from+1 hops; chains of migrations compose by repeated lookup.
_MIGRATION_REGISTRY: dict[tuple[str, int], tuple[int, Callable[[dict], dict]]] = {}


class MigrationError(RuntimeError):
    """Raised when a migration step is missing or fails."""


def register_migration(
    *,
    schema_name: str,
    from_version: int,
    to_version: int,
):
    """Register a forward migration from ``v<from_version>`` to ``v<to_version>``.

    Decorated function takes a body ``dict`` and returns a new body ``dict``.
    Migrations must be one major-version step at a time
    (``to_version == from_version + 1``).

    Re-registering the same ``(schema_name, from_version)`` pair replaces
    the previous entry — convenient in tests, intentional for hot-reload.
    """
    if to_version != from_version + 1:
        raise ValueError(
            f"migrations must be single-step: from_version={from_version}, "
            f"to_version={to_version}; chain via repeated migrate() calls."
        )
    if from_version < 1:
        raise ValueError(f"from_version must be >= 1, got {from_version}")

    def decorator(func: Callable[[dict], dict]) -> Callable[[dict], dict]:
        _MIGRATION_REGISTRY[(schema_name, from_version)] = (to_version, func)
        return func

    return decorator


def migrate(body: dict, *, from_uri: str, to_uri: str) -> dict:
    """Migrate ``body`` from ``from_uri`` to ``to_uri`` via registered steps.

    Composes single-step migrations. Raises :class:`MigrationError` if any
    step is missing.
    """
    from_name, from_v = parse_uri(from_uri)
    to_name, to_v = parse_uri(to_uri)
    if from_name != to_name:
        raise MigrationError(
            f"cannot migrate across schemas: {from_name!r} -> {to_name!r}"
        )
    if from_v == to_v:
        return dict(body)
    if from_v > to_v:
        raise MigrationError(
            f"only forward migrations are supported "
            f"(from v{from_v} to v{to_v} is backwards)"
        )

    current = dict(body)
    current_v = from_v
    while current_v < to_v:
        step = _MIGRATION_REGISTRY.get((from_name, current_v))
        if step is None:
            raise MigrationError(
                f"no migration registered for {from_name} v{current_v} -> "
                f"v{current_v + 1}"
            )
        next_v, func = step
        try:
            current = func(current)
        except Exception as exc:
            raise MigrationError(
                f"migration {from_name} v{current_v} -> v{next_v} failed: {exc}"
            ) from exc
        current_v = next_v
    return current


def latest_version(schema_name: str) -> int | None:
    """Highest registered major version for ``schema_name``, or None."""
    versions = [
        parse_uri(uri)[1] for uri in _BODY_REGISTRY if parse_uri(uri)[0] == schema_name
    ]
    return max(versions) if versions else None


def migrate_to_latest(body: dict, *, from_uri: str) -> tuple[dict, str]:
    """Convenience: migrate to the highest registered version of the schema.

    Returns ``(migrated_body, target_uri)``.
    """
    from_name, _ = parse_uri(from_uri)
    latest = latest_version(from_name)
    if latest is None:
        raise UnknownBodySchemaError(f"no schema registered with name {from_name!r}")
    target_uri = make_uri(from_name, latest)
    return migrate(body, from_uri=from_uri, to_uri=target_uri), target_uri
