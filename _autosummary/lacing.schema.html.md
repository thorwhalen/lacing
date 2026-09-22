# lacing.schema

Body schema registry, JSON Schema export, and migrations.

Every annotation’s `body` is validated against the schema named by its
`body_schema_uri` (semver: `annot://schema/<name>/v<major>`). This
module implements:

- [`register_body_schema()`](#lacing.schema.register_body_schema) — register a Pydantic v2 model for a schema URI.
- [`validate()`](#lacing.schema.validate) — validate an annotation’s body dict against its schema.
- [`json_schema()`](#lacing.schema.json_schema) — get the JSON Schema for a registered URI.
- [`export_json_schemas()`](#lacing.schema.export_json_schemas) — write all JSON Schema artifacts to disk
  (under `lacing/schema/<name>/v<N>.json` by default), the upstream
  for `json-schema-to-zod` codegen.
- [`register_migration()`](#lacing.schema.register_migration) — register a forward migration from version
  N to N+1 of a body schema.
- [`migrate()`](#lacing.schema.migrate) — upgrade a body dict (or whole annotation) through
  registered migrations.

See the `lacing-schema-codegen` skill and BACK-DOC §4.5.

Usage example:

```default
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
```

### Functions

| [`clear_registry`](#lacing.schema.clear_registry)()                           | Drop every registered body schema and migration.                        |
|---------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`export_json_schemas`](#lacing.schema.export_json_schemas)(target_dir, \*[, ...]) | Write every registered schema as JSON files under `target_dir`.         |
| [`get_body_schema`](#lacing.schema.get_body_schema)(uri)                       | Look up the registered Pydantic model for `uri`.                        |
| `is_registered`(uri)                                                                        |                                                                         |
| [`json_schema`](#lacing.schema.json_schema)(uri)                           | Return the JSON Schema for the body model registered at `uri`.          |
| [`latest_version`](#lacing.schema.latest_version)(schema_name)                | Highest registered major version for `schema_name`, or None.            |
| [`make_uri`](#lacing.schema.make_uri)(name, version)                    | Build a `body_schema_uri` from a name and major version.                |
| [`migrate`](#lacing.schema.migrate)(body, \*, from_uri, to_uri)        | Migrate `body` from `from_uri` to `to_uri` via registered steps.        |
| [`migrate_to_latest`](#lacing.schema.migrate_to_latest)(body, \*, from_uri)      | Convenience: migrate to the highest registered version of the schema.   |
| [`parse_uri`](#lacing.schema.parse_uri)(uri)                             | Split `annot://schema/<name>/v<major>` into `(name, major)`.            |
| [`register_body_schema`](#lacing.schema.register_body_schema)(uri, model)           | Register `model` as the validator for `uri`.                            |
| [`register_migration`](#lacing.schema.register_migration)(\*, schema_name, ...)   | Register a forward migration from `v<from_version>` to `v<to_version>`. |
| [`registered_uris`](#lacing.schema.registered_uris)()                          | All currently registered `body_schema_uri` values, sorted.              |
| [`validate`](#lacing.schema.validate)(body, uri)                        | Validate `body` against the schema registered for `uri`.                |

### Exceptions

| [`BodySchemaError`](#lacing.schema.BodySchemaError)          | Raised when a body fails validation against its registered schema.       |
|---------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`EmptySchemaRegistryError`](#lacing.schema.EmptySchemaRegistryError) | Raised when an export would write an empty registry over real artifacts. |
| [`MigrationError`](#lacing.schema.MigrationError)           | Raised when a migration step is missing or fails.                        |
| [`UnknownBodySchemaError`](#lacing.schema.UnknownBodySchemaError)   | Raised when an annotation's body_schema_uri has no registered model.     |

### *exception* lacing.schema.BodySchemaError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

Raised when a body fails validation against its registered schema.

### *exception* lacing.schema.EmptySchemaRegistryError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when an export would write an empty registry over real artifacts.

Almost always means the caller forgot `import lacing.bodies`: the
registry is populated by importing the body modules, so exporting without
that import silently truncates `index.json` to `{}` and leaves the
committed `v<N>.json` files orphaned.

### *exception* lacing.schema.MigrationError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when a migration step is missing or fails.

### *exception* lacing.schema.UnknownBodySchemaError

Bases: [`KeyError`](https://docs.python.org/3/builtins/exceptions.html#KeyError)

Raised when an annotation’s body_schema_uri has no registered model.

### lacing.schema.clear_registry()

Drop every registered body schema and migration. For tests / repls.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.schema.export_json_schemas(target_dir, , overwrite=True, include_meta=True, allow_empty=False)

Write every registered schema as JSON files under `target_dir`.

Layout: `<target_dir>/<name>/v<N>.json`. Returns the list of paths
written, in registration order.

* **Parameters:**
  * **target_dir** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)) – Output directory. Created if missing.
  * **overwrite** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If False, refuse to write a file that already exists.
  * **include_meta** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, also write a `<target_dir>/index.json`
    mapping every URI to its file path and the Pydantic model’s
    qualified name (helps the codegen pipeline).
  * **allow_empty** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If True, permit an export from an empty registry. The
    default refuses, because the overwhelmingly likely cause is a
    missing `import lacing.bodies` and the write would destroy the
    committed artifacts.
* **Raises:**
  [**EmptySchemaRegistryError**](#lacing.schema.EmptySchemaRegistryError) – Nothing is registered and `allow_empty`
      is False.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### lacing.schema.get_body_schema(uri)

Look up the registered Pydantic model for `uri`.

* **Return type:**
  [`type`](https://docs.python.org/3/builtins/functions.html#type)[`BaseModel`]

### lacing.schema.json_schema(uri)

Return the JSON Schema for the body model registered at `uri`.

Pydantic’s `model_json_schema()` output, unmodified.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### lacing.schema.latest_version(schema_name)

Highest registered major version for `schema_name`, or None.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.schema.make_uri(name, version)

Build a `body_schema_uri` from a name and major version.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### lacing.schema.migrate(body, , from_uri, to_uri)

Migrate `body` from `from_uri` to `to_uri` via registered steps.

Composes single-step migrations. Raises [`MigrationError`](#lacing.schema.MigrationError) if any
step is missing.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### lacing.schema.migrate_to_latest(body, , from_uri)

Convenience: migrate to the highest registered version of the schema.

Returns `(migrated_body, target_uri)`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### lacing.schema.parse_uri(uri)

Split `annot://schema/<name>/v<major>` into `(name, major)`.

Raises `ValueError` on malformed input.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### lacing.schema.register_body_schema(uri, model)

Register `model` as the validator for `uri`. Returns `model`.

* **Return type:**
  [`type`](https://docs.python.org/3/builtins/functions.html#type)[`BaseModel`]

### lacing.schema.register_migration(, schema_name, from_version, to_version)

Register a forward migration from `v<from_version>` to `v<to_version>`.

Decorated function takes a body `dict` and returns a new body `dict`.
Migrations must be one major-version step at a time
(`to_version == from_version + 1`).

Re-registering the same `(schema_name, from_version)` pair replaces
the previous entry — convenient in tests, intentional for hot-reload.

### lacing.schema.registered_uris()

All currently registered `body_schema_uri` values, sorted.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### lacing.schema.validate(body, uri)

Validate `body` against the schema registered for `uri`.

Returns the parsed Pydantic instance. Raises [`BodySchemaError`](#lacing.schema.BodySchemaError)
on validation failure (wrapping the underlying `pydantic.ValidationError`)
or [`UnknownBodySchemaError`](#lacing.schema.UnknownBodySchemaError) if the URI isn’t registered.

* **Return type:**
  `BaseModel`
