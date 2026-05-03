---
name: lacing-schema-codegen
description: Use when modifying lacing's data model, body schemas, or the Pydantic→JSON-Schema→Zod codegen pipeline. Triggers on edits to lacing/model.py, lacing/schema.py, lacing/tier.py, body_schema_uri, schema migrations, schema versioning, or anything in lacing-ui/packages/core/ that mirrors a Python type. Encodes the single-source-of-truth rule (Pydantic v2 is SoT), the additive-by-default versioning rule, the migration-registration pattern, and the codegen wiring (`datamodel-code-generator` + `json-schema-to-zod`).
---

# Lacing — Schema Codegen and Versioning

The Python `Annotation` model is the **single source of truth**. JSON Schema
is generated from it. Zod schemas are generated from the JSON Schema. The
TypeScript frontend never hand-writes types that mirror Python.

## The pipeline

```
lacing/model.py            (Pydantic v2 — single source of truth)
        │
        │  pydantic.BaseModel.model_json_schema()
        ▼
lacing/schema/<name>/v<N>.json    (JSON Schema artifacts, committed)
        │
        ├─►  Python validation: Pydantic at runtime (server boundary)
        │
        └─►  TypeScript codegen:
                json-schema-to-zod  →  lacing-ui/packages/core/zod/<name>.ts
                                       (Zod schema, committed)
                                       │
                                       └─►  z.infer<typeof S>  for TS types
```

Why **commit the generated artifacts** in JSON Schema and Zod:
- Diffs become readable in PRs.
- Frontend can build without running Python.
- Schema migrations have clear before/after.

## Where each piece lives

| Concern | Location |
|---------|----------|
| Annotation envelope (`Annotation`, `Reference`, `Provenance`) | `lacing/model.py` |
| Tier types + 5 ELAN stereotypes | `lacing/tier.py` |
| Body schemas (per-domain payloads — phoneme, viseme, named-entity, etc.) | `lacing/bodies/<name>.py` |
| Body schema registry | `lacing/schema.py` |
| JSON Schema artifacts (committed) | `lacing/schema/<name>/v<N>.json` |
| Zod artifacts (committed) | `lacing-ui/packages/core/zod/<name>.ts` |
| Migrations | `lacing/migrations/<name>/v<N>_to_v<N+1>.py` |

## body_schema_uri convention

Every annotation's `body` is validated by the schema named in `body_schema_uri`:

```
annot://schema/<name>/v<major>
```

- `name` is `kebab-case`, matches the body file: `annot://schema/named-entity/v1` ↔ `lacing/bodies/named_entity.py`.
- Only the **major** version is in the URI. Minor/patch bumps must remain backward-compatible.
- The URI is part of every annotation's wire format. Validators look up the schema by URI.

## Versioning: additive by default

**Allowed without a major bump:**
- Add an *optional* field with a sensible default.
- Add a value to a string-enum-like field — but only if consumers ignore unknown values gracefully (document this contract per body).
- Tighten a docstring or description.

**Requires a major bump + migration:**
- Remove or rename a field.
- Change a field's type.
- Make an optional field required.
- Tighten a constraint (regex, range) that would invalidate existing data.
- Change semantic meaning of an existing field.

## Migration registration

Every major bump ships a migration:

```python
# lacing/migrations/named_entity/v1_to_v2.py
from lacing.schema import register_migration

@register_migration(
    schema_name="named-entity",
    from_version=1,
    to_version=2,
)
def upgrade(body: dict) -> dict:
    """v1 used `type`; v2 renames it to `entity_type` and adds optional `confidence`."""
    return {
        **{k: v for k, v in body.items() if k != "type"},
        "entity_type": body["type"],
    }
```

- Migrations are **forward-only** by convention. If you need a downgrade, register it explicitly as a separate migration.
- Migrations run lazily on read OR eagerly during a registered batch operation. Don't write code that assumes one or the other.
- Every migration has a unit test with a v(N) sample → v(N+1) expected output.

## The Pydantic v2 patterns we use

```python
from pydantic import BaseModel, Field, model_validator

class NamedEntityBody(BaseModel):
    """Body for named-entity annotations.

    body_schema_uri: annot://schema/named-entity/v1
    """
    model_config = {"frozen": True, "extra": "forbid"}

    entity_type: str = Field(..., description="ENTITY type (PER, ORG, LOC, ...)")
    text: str = Field(..., description="Surface form")
    confidence: float | None = Field(None, ge=0.0, le=1.0)
```

- `model_config = {"frozen": True}` — annotations are immutable; replace, don't mutate.
- `"extra": "forbid"` — unknown fields are an error, not silently accepted (catches typos and stale clients).
- Use `Field(..., description=...)` — descriptions land in JSON Schema and Zod, then in the auto-generated Inspector form (FRONT-DOC §6.3).
- Prefer `| None` over `Optional[...]` (Python 3.10+).
- Validation logic via `@model_validator(mode="after")`, never side effects.

## Codegen invocation

The exact tooling (per BACK-DOC §6):

```bash
# Step 1: Pydantic → JSON Schema
python -m lacing.schema.export --out lacing/schema/

# Step 2: JSON Schema → Zod
npx json-schema-to-zod -i lacing/schema/named-entity/v1.json -o lacing-ui/packages/core/zod/named-entity.ts
```

Wire this into a single `make codegen` (or equivalent) target. Both
artifacts are committed. CI verifies they're up to date by re-running
codegen and diffing.

## The boundary between envelope and body

```
Annotation                       ← envelope: id, tier, reference, body, body_schema_uri, provenance
   └── body: dict                ← validated by the schema at body_schema_uri
       └── (NamedEntityBody, PhonemeBody, ChordBody, ...)
```

- The **envelope** is one model in `lacing/model.py`, single version, evolves rarely.
- **Bodies** are many small models in `lacing/bodies/`, each with its own version.
- Don't put domain fields in the envelope. Don't put generic fields in the body.
- If a field needs to be queryable across all annotations (e.g., `confidence`, `author`), it goes in the envelope or in `Provenance`. If it's domain-specific (`pitch_hz`, `speaker_id`), it goes in the body.

## Inspector form generation

The frontend Inspector auto-generates a form from each body's Zod schema
(FRONT-DOC §6.3) using `react-hook-form` + `@hookform/resolvers/zod`.

- Field types come from JSON Schema → Zod.
- Field labels come from the Pydantic `Field(..., description=...)`.
- This is why descriptions matter — they're not just docs, they're UX strings.

## Frontend mirrors of envelope-level types

`RationalTime`, `TimeInterval`, `Reference`, `Provenance`, the 5 tier
stereotypes — these are codegened. **Don't hand-write TS versions.** A
hand-written TS type that drifts from Python is the #1 codegen failure mode.

## Checklist before merging a model change

- [ ] Is this additive (no version bump) or breaking (major bump + migration)?
- [ ] If breaking: migration written and tested?
- [ ] `body_schema_uri` follows `annot://schema/<name>/v<major>` exactly.
- [ ] `model_config = {"frozen": True, "extra": "forbid"}` set.
- [ ] All `Field(...)` have descriptions (these become Inspector labels).
- [ ] JSON Schema regenerated and committed.
- [ ] Zod regenerated and committed.
- [ ] If envelope changed, frontend store/selectors checked for breakage.
- [ ] No envelope ↔ body field bleed (queryable cross-cutting fields stay in envelope; domain fields stay in body).

## Source pointers

- Pydantic v2 model definitions: BACK-DOC §2.1, §4.1.
- JSON-Schema-to-Zod codegen tooling: BACK-DOC §6 (`datamodel-code-generator` + `json-schema-to-zod`).
- Schema versioning + additive-only default: ANN-DOC §C "Schema versioning"; BACK-DOC §4.5.
- Inspector form auto-generation: FRONT-DOC §6.3 `AnnotationLayerSpec<T>`.
- Migration as a registered processor: BACK-DOC §4.5.
