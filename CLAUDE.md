# lacing — agent entry point

`lacing` is a **standoff, interval-keyed annotation system** with a Python
backend and a TypeScript/React frontend, sharing one schema-versioned data
model.

## Read these before non-trivial work

1. **[misc/docs/Lacing Development Roadmap.md](misc/docs/Lacing%20Development%20Roadmap.md)** — what to build, in phases, with cross-references to the design docs.
2. The four design docs in [misc/docs/](misc/docs/) — the *why* behind every decision. The roadmap cites them by section.

## Skills available in this repo

`.claude/skills/` contains four lacing-specific skills. Use them when their
trigger conditions match — they encode rules that are easy to violate:

- **lacing-architecture** — primer; load when starting work on lacing.
- **lacing-time-and-intervals** — rational time + Allen relations; load when touching anything time-related.
- **lacing-adapter-authoring** — recipe for new I/O format adapters.
- **lacing-schema-codegen** — Pydantic → JSON Schema → Zod flow.

## Non-negotiables (ten rules — see roadmap for sources)

1. Time is `RationalTime(value: int, rate: int)`. **Never floats.**
2. Standoff annotations only. Source media is immutable.
3. One `Annotation` envelope, typed `body: dict` validated by `body_schema_uri`.
4. `intervaltree` in memory; PostgreSQL `tstzrange` + GiST when persistent.
5. Public API is a `MutableMapping[TimeInterval, list[Annotation]]` facade exposing Allen's relations.
6. Tier stereotypes from ELAN, verbatim: `NONE`, `TIME_SUBDIVISION`, `INCLUDED_IN`, `SYMBOLIC_SUBDIVISION`, `SYMBOLIC_ASSOCIATION`.
7. I/O is plugin adapters. Core never imports a format.
8. PROV-O provenance inline on every annotation.
9. Pydantic v2 → JSON Schema → Zod. One SoT, two languages.
10. MIT/BSD/Apache licenses only. No LGPL/GPL/AGPL/BSL dependencies.

If docs and roadmap disagree, **docs win** — fix the roadmap.
