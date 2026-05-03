---
name: lacing-adapter-authoring
description: Use when adding, modifying, or reviewing an I/O format adapter for lacing — Praat TextGrid, ELAN EAF, WebVTT, JAMS, Label Studio JSON, W3C Web Annotation, OpenTimelineIO, CoNLL, brat standoff, SubRip, TTML, CSV, or any new format. Triggers on "add a … adapter", "import/export … format", "support … in lacing", "round-trip … format", or any work under lacing/adapters/. Encodes the plugin contract, the round-trip test pattern, license-checking the underlying parser, schema URI conventions, and the common pitfalls (offset invalidation, rate mismatch, lossy round-trips).
---

# Lacing — Adapter Authoring

Format support in lacing is **plugin-only**. The core never imports a format
module. Each adapter is a small, independent file in `lacing/adapters/` that
registers itself.

## The plugin contract

Every adapter exposes two functions and one registration call. The exact
signature is fixed by [lacing/adapters/__init__.py](../../../lacing/adapters/__init__.py):

```python
# lacing/adapters/<format>.py
import os
from lacing.adapters import register_adapter
from lacing.store import IntervalAnnotationStore, MemoryStore

ADAPTER_NAME = "textgrid"
BODY_SCHEMA_URI = "annot://schema/textgrid-label/v1"

def load(
    source: str | bytes | os.PathLike,
    *,
    rate: int = DEFAULT_RATE,
    asset_id: str = "...",
    attribution: str = "anonymous",
    **kwargs,
) -> IntervalAnnotationStore:
    """Parse `source` into an in-memory store."""
    ...

def dump(
    store: IntervalAnnotationStore,
    target: str | os.PathLike | None = None,
    **kwargs,
) -> bytes | None:
    """Serialize `store`. If `target` is None, return bytes; else write to target."""
    ...

register_adapter(
    name=ADAPTER_NAME,
    load=load,
    dump=dump,
    extensions=(".TextGrid",),                 # tuple, lowercased on register
    media_types=("text/x-praat-textgrid",),     # tuple
    body_schema_uris=(BODY_SCHEMA_URI,),        # tuple — adapters may emit multiple
    description="...",
)
```

Notes on the surface:
- `register_adapter` is keyword-only and returns the `AdapterSpec`.
- `body_schema_uris` is **plural / tuple** — adapters may produce multiple
  body shapes (e.g. cue + chapter schemas).
- `extensions` may be passed with or without leading dots; they're
  normalized to lowercase with leading dot in the registry.
- Use `register_adapter` (the registry, not direct imports) so users can
  swap or add formats without touching core.

## Round-trip is the acceptance test

Every adapter ships with a round-trip test:

```python
# tests/adapters/test_<format>.py
def test_roundtrip_<format>(sample_file):
    store1 = load(sample_file)
    blob = dump(store1)
    store2 = load(blob)
    assert_stores_equivalent(store1, store2)
```

`assert_stores_equivalent` compares **annotations modulo provenance
timestamps and IDs**, not byte-equality. Some formats are lossy by design
(WebVTT loses tier metadata). Document each lossy edge in the adapter
docstring with what gets dropped.

## Body schema URI

Every adapter declares one or more `body_schema_uri` values it produces.

- Format: `annot://schema/<name>/v<major>`.
- Bumps are **additive-only** by default. Breaking change → new major + a
  registered migration in `lacing/schema.py`.
- The URI travels with each annotation; the validator picks the right Zod /
  Pydantic schema by URI.

## License-check the parser before you depend on it

Before adding a parser library, check ANN-DOC §E or look up the package on
PyPI. **Never bring in:**

| Banned | Why | Use instead |
|--------|-----|-------------|
| `praat-parselmouth` | GPLv3+ | `praatio` (MIT) |
| `aeneas` | AGPL v3 | Montreal Forced Aligner (MIT) or write a thin parser |
| `portion` | LGPLv3 | `intervaltree` (Apache-2.0) |
| Peaks.js | LGPL-3.0 | wavesurfer.js v7 (BSD-3) |
| anything LGPL/GPL/AGPL/BSL | viral / commercial trap | find MIT/BSD/Apache equivalent or write a small parser |

If the only library is non-MIT/BSD/Apache, **write the parser** — most
annotation formats are XML/JSON/CSV with simple grammars (TextGrid is ~100
lines, EAF is XML).

## Time discipline at the parsing boundary

Parsers receive floats from external formats. Convert immediately:

```python
def _to_rational(seconds: float | str, rate: int = 24000) -> RationalTime:
    f = Fraction(seconds).limit_denominator(rate)
    val = int(f * rate)
    return RationalTime(value=val, rate=rate)
```

- Convert **once at the parse boundary**; everything internal is `RationalTime`.
- If the source format guarantees integer ticks (MIDI PPQN, ELAN ms), use them directly — don't go through float.
- Document the rate assumption in the adapter docstring.

## Tier mapping

Every format maps to lacing's ELAN tier stereotypes (Rule 6 in
`lacing-architecture`). When the source format has no equivalent
(WebVTT has flat tracks, no parent), pick `NONE` and document it.

| Format | Stereotype map |
|--------|----------------|
| Praat TextGrid IntervalTier | `NONE` |
| Praat TextGrid PointTier | `NONE` (point annotations) |
| ELAN EAF parent tier | `NONE` |
| ELAN EAF child with `Time_Subdivision` | `TIME_SUBDIVISION` |
| ELAN EAF `Symbolic_Subdivision` | `SYMBOLIC_SUBDIVISION` |
| ELAN EAF `Symbolic_Association` | `SYMBOLIC_ASSOCIATION` |
| ELAN EAF `Included_In` | `INCLUDED_IN` |
| WebVTT cues | `NONE` |
| W3C Web Annotation | `NONE` (use `motivation` for tier semantics) |

## Provenance on import

Every imported annotation gets:

```python
Provenance(
    was_generated_by=f"adapter:{adapter_name}",
    was_attributed_to=kwargs.get("attribution", "anonymous"),
    was_derived_from=[source_asset_id],   # content hash of the source file
    generated_at_time=RationalTime.now(),
    activity="import",
)
```

If the source format encodes its own provenance (W3C Web Annotation has
`creator` + `created`), preserve it under `was_derived_from` chain — don't
overwrite.

## Common pitfalls (catch in review)

1. **Off-by-one on closed-vs-open intervals.** Praat is closed, lacing is half-open. Document the conversion.
2. **Encoding assumptions.** TextGrid can be Latin-1 or UTF-8 with BOM. Always sniff.
3. **Rate mismatch within a single file.** ELAN's `TIME_ORDER` defines named anchors with one rate; don't assume project rate.
4. **String labels with embedded delimiters.** WebVTT cues with `-->` in the body. Use the format's escape rules, not naive split.
5. **Empty intervals.** Some formats forbid `start == end`; lacing allows it. Document drop / convert.
6. **Lossy round-trip not flagged.** If the format can't represent confidence/provenance, the adapter must say so in its docstring **and** in the dump return metadata.

## Adapter checklist

- [ ] `load` and `dump` signatures match the contract.
- [ ] `register_adapter` called at module import.
- [ ] License of any underlying parser is MIT/BSD/Apache.
- [ ] All time conversions go through `_to_rational` at the boundary.
- [ ] Tier stereotype mapping documented.
- [ ] Provenance set with `was_generated_by="adapter:<name>"`.
- [ ] Round-trip test on at least two real-world samples.
- [ ] Lossy fields documented in module docstring.
- [ ] `body_schema_uri` declared and registered.
- [ ] No core imports leaked into the adapter (it depends on `lacing.model`, not the other way).

## Adapter priority order (Phase 0 → Phase 1)

Phase 0: **TextGrid, WebVTT, W3C Web Annotation JSON-LD** — *all three
landed*. Three formats covering three audiences (linguistics, captions,
web/scholarly).

Phase 1: **ELAN EAF, JAMS, Label Studio JSON, OpenTimelineIO, CoNLL,
brat standoff, SubRip, TTML, CSV.**

Don't skip ahead — Phase 0 adapters validate the data model. If a Phase 0
adapter exposes a model gap, fix the model before adding more adapters.

## Examples to study

The Phase 0/1 adapters are deliberately diverse and demonstrate the pattern:

- [lacing/adapters/textgrid.py](../../../lacing/adapters/textgrid.py) — uses an external parser (`praatio`, MIT, optional install), maps both interval and point tiers, raises `ImportError` with the install hint when the extra is missing.
- [lacing/adapters/webvtt.py](../../../lacing/adapters/webvtt.py) — pure-Python parser, no dependency. Flat cues, no tier hierarchy. Demonstrates the `from_string-or-from-path` source heuristic.
- [lacing/adapters/web_annotation.py](../../../lacing/adapters/web_annotation.py) — JSON-LD, uses the standard `json` module. Demonstrates discriminated-union round-tripping and creator/provenance preservation.
- [lacing/adapters/annot.py](../../../lacing/adapters/annot.py) — *lossless* SQLite-based portable file format. Demonstrates the `persistent=True` mode (returns a live `SqliteStore` instead of a `MemoryStore`) and the fast-copy path when the source is already a `SqliteStore`.

## Source pointers

- Format catalogue and parser libraries: ANN-DOC §B, §E.
- Adapter pattern as architecture: ANN-DOC §C ("non-negotiable"); OSS-DOC OTIO `SchemaDef`.
- Provenance schema: ANN-DOC §C; BACK-DOC §4.5.
- Round-trip test pattern: BACK-DOC §4.3.
