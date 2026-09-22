# lacing.cli

Command-line interface for lacing.

Built with `cw` (argparse + signature-driven argument inference).
The entry point is `lacing` — see `project.scripts` in pyproject.toml.

Subcommands:

> lacing convert <src> <dst> [–src-format] [–dst-format] [–rate]
> : Convert between any two registered formats. Inferred from
>   extension; override with `--src-format` / `--dst-format`.

> lacing query <path> [–tier] [–start] [–end] [–relation]
> : Print annotations matching a tier and/or interval query.
>   Output is JSON-lines on stdout.

> lacing validate <path> [–rate]
> : Load + re-dump round-trip; print a summary. Useful for sanity
>   checking files before adopting them.

> lacing migrate <path> [–to-version N]
> : Upgrade a `.annot` file to the current store schema, in place,
>   via the registered store-migration ladder. Explicit by design:
>   opening a stale file never rewrites it.

> lacing list-formats
> : Print every registered format adapter.

The CLI imports each Phase 0/1 adapter at startup so they self-register.
Add new adapters by editing `_ENABLED_ADAPTERS` in this module.

## Type annotations are load-bearing here

This module has `from __future__ import annotations`, so every annotation
below is a *string* at runtime. `argh`, which this CLI used to be built with,
reads `__annotations__` raw and is therefore blind to PEP 563: under it,
`--start`, `--end` and `--to-version` all arrived as `str` no matter what
their annotations said, and the only defence was hand-written coercion in the
command body (which `migrate` had and `query` did not — so
`lacing query f.vtt --start abc --end 2.0` used to get all the way into
`RationalTime` before failing).

`_CONVENTION` turns that off. `resolve_hints=True` makes `cw` resolve
annotations with [`typing.get_type_hints()`](https://docs.python.org/3/library/typing.html#typing.get_type_hints) instead of reading them raw, so
`start: float | None` becomes `type=float` at argparse’s `type=` site —
where a bad value is a clean `usage:` + exit 2 rather than a traceback from
somewhere in the call stack. Which means: \*\*annotate the parameters, and do not
coerce in the body.\*\*

### Functions

| [`convert`](#lacing.cli.convert)(src, dst, \*[, src_format, ...])           | Convert between annotation file formats.                                                                                                  |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| [`list_formats`](#lacing.cli.list_formats)()                                     | Print every registered format adapter.                                                                                                    |
| [`main`](#lacing.cli.main)([argv])                                       | Entry point for the `lacing` console script.                                                                                              |
| [`migrate`](#lacing.cli.migrate)(path, \*[, to_version])                    | Upgrade PATH (a `.annot` file) to the current store schema, in place.                                                                     |
| [`mk_parser`](#lacing.cli.mk_parser)()                                        | Build the `lacing` parser — a plain [`argparse.ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser). |
| [`query`](#lacing.cli.query)(path, \*[, tier, start, end, relation, ...]) | Print annotations from PATH matching a tier and/or time-interval query.                                                                   |
| [`validate`](#lacing.cli.validate)(path, \*[, src_format, rate])             | Round-trip PATH through load + dump and report a summary.                                                                                 |

### lacing.cli.convert(src, dst, , src_format=None, dst_format=None, rate=24000)

Convert between annotation file formats.

SRC is a path to a recognized file (or `-` for stdin bytes — not yet).
DST is the output path. Formats are inferred from extensions; override
with –src-format / –dst-format.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.cli.list_formats()

Print every registered format adapter.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.cli.main(argv=None)

Entry point for the `lacing` console script.

`cw.run` *returns* the exit code where argh’s `dispatch` exited by
itself, so the `SystemExit` here is what makes `lacing no-such-command`
exit 2 rather than 0.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.cli.migrate(path, , to_version=None)

Upgrade PATH (a `.annot` file) to the current store schema, in place.

Migration is explicit — opening a stale file never rewrites it — so this
verb is the ladder’s front door. Already-current files are a no-op.
`--to-version` upgrades part-way (mainly useful in tests).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.cli.mk_parser()

Build the `lacing` parser — a plain [`argparse.ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser).

* **Return type:**
  [`ArgumentParser`](https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser)

### lacing.cli.query(path, , tier=None, start=None, end=None, relation='intersects', src_format=None, rate=24000, limit=100)

Print annotations from PATH matching a tier and/or time-interval query.

Output is JSON-lines on stdout. `--start` and `--end` are seconds.
`--relation` is one of: intersects, during, contains, overlaps, meets,
starts, finishes, equals.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### lacing.cli.validate(path, , src_format=None, rate=24000)

Round-trip PATH through load + dump and report a summary.

Useful for confirming an external file is well-formed and that the
adapter understands it.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
