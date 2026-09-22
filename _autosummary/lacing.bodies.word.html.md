# lacing.bodies.word

Body schema for word-level annotations (e.g., transcription, forced alignment).

URI: `annot://schema/word/v1`

### Classes

| [`WordBodyV1`](#lacing.bodies.word.WordBodyV1)(\*\*data)   | A single word annotation.   |
|-------------------------------------------------------------------------|-----------------------------|

### *class* lacing.bodies.word.WordBodyV1(\*\*data)

Bases: `BaseModel`

A single word annotation.

The `text` is the surface form as it appears in the source media.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
