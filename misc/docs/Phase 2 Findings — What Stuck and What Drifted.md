# Phase 2 Findings — What Stuck and What Drifted

This document records the things the design docs *didn't* anticipate (or
got wrong) plus the calls I made that future sessions should know about.
Anything not mentioned here was implemented as the design docs specified
— the docs are still authoritative for everything else.

Pair this doc with the original four design docs and with
`Lacing Development Roadmap.md`.

---

## Decisions that diverged from BACK-DOC

### 1. `int8range` over `tstzrange` for the Postgres backend

BACK-DOC §4.2 leaned toward `tstzrange` (timestamp-with-tz). I picked
`int8range` because lacing's time model is **rational ticks at a
project-wide rate**, not wall-clock time. Forcing `tstzrange` would
have required inventing a fake epoch ("project start = 1970-01-01")
and would have made the queries nonsensical for non-time domains
(genomics, document offsets, etc.).

`int8range` gives the same `&&` / `<@` / `@>` / `-|-` operators and
the same GiST index. The project rate is stored in `meta`; opening
with a different rate raises `PgSchemaMismatchError`.

**Implication for Phase 3:** the wire format for time is `{v, r}` (lacing's
`RationalTime.to_wire()`). The frontend has to convert at the boundary.
This was already in the schema-codegen skill but worth surfacing again.

### 2. R*Tree as pre-filter, not source of truth, in SqliteStore

The doc described SQLite + R*Tree as the embedded backend without
addressing that R*Tree is `REAL`-valued. Integer rational pairs are
the source of truth; R*Tree pre-filters with ULP-widened bounds, then
exact rational predicates re-validate. Same trick on the Postgres side
for the strict Allen variants (`during`, `overlaps`, etc.).

### 3. Op-log is its own module, not folded into the server

BACK-DOC §4.7 mentioned the op-log + state-at endpoint as a server
feature. I extracted it to `lacing/oplog.py` (with `InMemoryOpLog` +
`SqliteOpLog` implementations). Reasoning: the op-log is useful in
non-server contexts (CLI batch operations, agent scripts, replication
into a backup). The server uses it via DI, so any embedder can plug
in their own storage.

### 4. MCP tools take seconds, not RationalTime wire format

The MCP tools (`add_annotation(start_seconds, end_seconds, ...)`)
deliberately accept floats and convert at the boundary. The doc
implied "agents drive the same surface humans do" but agents don't
benefit from `RationalTime`'s precision — they're working in
human-timescale audio/video. REST keeps the wire format intact;
MCP is the seconds-friendly surface.

### 5. Per-tier `EXCLUDE` constraint is opt-in

BACK-DOC §4.4 implied non-overlap should follow the stereotype
(`TIME_SUBDIVISION` → no overlap). I made it explicit: `add_tier(tier,
enforce_no_overlap=True)`. Reasoning: the constraint is enforced by
the database and **fails inserts**, which is great for production but
surprising for casual users importing data that happens to violate
the invariant. Default is permissive; opt in when you want database-
enforced invariants.

### 6. Processor pattern is independent of Arq

BACK-DOC §6 said "use Arq, not Celery." I split the concept:
processors are plain registered async functions (works without any
infra), and Arq is one of two ways to *invoke* them (the other being
sync run-in-current-loop). Most lacing users will never run Redis;
they shouldn't have to.

---

## Decisions the docs didn't address

### 7. `check_same_thread=False` is required for the SqliteStore in the server

FastAPI runs sync endpoints on a worker threadpool. The default
`SqliteStore(":memory:")` raises across threads. The default factory
in `lacing.server.deps` now passes `check_same_thread=False`. Document
this for any production wiring.

### 8. `Protocol` cannot inherit from `MutableMapping` in 3.10/3.12

The skill said `IntervalAnnotationStore(MutableMapping[...])` as a
nominal base. In practice, `Protocol` forbids inheriting from a
non-Protocol ABC. I made it a structural Protocol. Concrete backends
(`MemoryStore`, `SqliteStore`, `PostgresStore`) implement the full
mapping interface. Behavior matches the doc; the type-system shape
doesn't.

### 9. `typing.Self` is 3.11+ but the project targets 3.10

The first CI failure on the 3.10 matrix was `from typing import Self`.
Fixed by using string forward-refs (`-> "RationalTime"`); the
`from __future__ import annotations` already in effect makes them
string-evaluated regardless. Recurring pattern: don't reach for 3.11+
typing tricks while 3.10 is in the matrix.

### 10. `register_adapter` takes `body_schema_uris` (plural tuple)

The skill originally showed `body_schema_uri=`. Real adapters
(notably `otio.py`) emit multiple body schemas (`otio-clip/v1` +
`otio-marker/v1`), so the field is plural. Skill updated.

### 11. Inline strings vs. paths in adapter `load()`

WebVTT, JAMS, OTIO, Web Annotation, and Label Studio all accept
either a path or an inline string/bytes. The pattern: **try-as-path
first; fall back to inline content if the file doesn't exist**. The
inline-string heuristic ("starts with `WEBVTT`" or "starts with `{`")
is a second filter for quick rejection.

This isn't in the adapter-authoring skill yet — worth adding.

### 12. Idempotence is a real concern for processors

`low_confidence_review` re-runs without producing duplicates because
it skips sources already represented in the review tier. Similar
constraints apply to any processor that emits derived annotations.
Future processors should follow the pattern: encode the relationship
in the body (`source_id`, `was_derived_from`) and check for it on
re-run.

---

## Things to recheck if Phase 3 needs them

### Wads CI auto-bumps on every push

Every push to `main` triggers CI which bumps the version (0.0.1 →
0.0.10 over this session) and reformats code. This means:

- After every push, `git pull --rebase origin main` before continuing.
- Conflict resolution: I hit one conflict in `annotations.py` because
  the formatter touched lines I'd just edited. The resolution was to
  keep my version and let wads reformat it on the next push.
- The reformat happens automatically; don't manually format to match
  wads' style.

### CI runs `--doctest-modules`

The wads CI invocation includes `--doctest-modules`, so any
`>>> ` in module docstrings becomes a doctest. Currently 3 doctests
pass (in `lacing/time.py`). If Phase 3 introduces docstrings with
example code, ensure they're valid Python that runs cleanly.

### Postgres tests skip cleanly when binary missing

`tests/conftest.py` auto-skips the entire `test_store_postgres.py`
module when `pg_ctl`/`postgres` aren't on PATH. This is what makes CI
pass without Postgres installed. Don't change without thinking.

### One known un-cleaned file pattern

`SqliteStore`'s `__iter__` and the SQL `DISTINCT span ORDER BY
lower(span)` had to be wrapped in a subquery on Postgres because
PostgreSQL requires ORDER BY columns in the SELECT list with DISTINCT.
SQLite is permissive about this.

---

## Test architecture quirks worth knowing

### `pytest-postgresql` vs `pytest-anyio` vs FastMCP

- **Postgres tests** use a session-scoped sandbox via `pytest-postgresql`.
  The sandbox spawns one PostgreSQL process per session; each test gets
  a fresh database via the `postgresql` fixture.
- **MCP tests** use FastMCP's `call_tool(name, args)` directly with
  `@pytest.mark.anyio` + `anyio_backend = "asyncio"` fixtures.
- **OTel tests** use a **module-scoped** TracerProvider because OTel
  forbids replacing a configured provider. Each test clears the
  in-memory exporter buffer instead of replacing the provider. If
  Phase 3's tests also need OTel, follow this pattern — not the
  function-scoped pattern that "should" work.

### `FastMCP.call_tool` returns a tuple

`(content_parts, structured_dict)`. The structured dict is the
canonical Python-typed return; the content parts are JSON-serialized
TextContent objects, **one per item** in a list-typed return.
Use `structured` (and unwrap `{"result": ...}`) to test what tools
actually return. My `_call` helper in `tests/test_mcp.py` does this.

### `client.dependency_overrides` doesn't clear `_active_store`

The default factory in `lacing/server/deps.py` caches its store /
oplog at module level. Tests that create new apps via `create_app()`
must override `get_store` AND `get_oplog` if they want isolation.
This is what `tests/test_server.py`'s `client` fixture does.

---

## Things to do early in any future session

1. **Run `git fetch origin && git pull --rebase origin main`** to pick
   up the latest wads auto-bump.
2. **Run `python -m pytest tests/ -q`** to confirm baseline (should be
   552 passed, 1 skipped if you have Postgres binary on PATH; 510-ish
   passed if you don't).
3. **Read `Lacing Development Roadmap.md`** for the canonical phase
   list and current status.
4. **Check `gh run list --branch main --limit 3`** to make sure CI is
   currently green.
