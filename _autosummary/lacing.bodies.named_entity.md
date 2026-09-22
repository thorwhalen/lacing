# lacing.bodies.named_entity

Body schemas for named-entity (NER) annotations.

URIs:

```default
annot://schema/named-entity/v1   -- type + text
annot://schema/named-entity/v2   -- entity_type + text + optional confidence (additive)
```

A v1 -> v2 migration is registered to demonstrate the pattern.

### Classes

| [`NamedEntityBodyV1`](#lacing.bodies.named_entity.NamedEntityBodyV1)(\*\*data)   | Original NER body.                                                 |
|--------------------------------------------------------------------------------|--------------------------------------------------------------------|
| [`NamedEntityBodyV2`](#lacing.bodies.named_entity.NamedEntityBodyV2)(\*\*data)   | v2 renames `type` -> `entity_type` and adds optional `confidence`. |

### *class* lacing.bodies.named_entity.NamedEntityBodyV1(\*\*data)

Bases: `BaseModel`

Original NER body. `type` is the entity tag (PER, ORG, LOC, …).

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* lacing.bodies.named_entity.NamedEntityBodyV2(\*\*data)

Bases: `BaseModel`

v2 renames `type` -> `entity_type` and adds optional `confidence`.

The rename makes v2 incompatible with v1, so we register a migration.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
