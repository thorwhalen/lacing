"""Tests for the ``lacing`` CLI.

We invoke functions directly rather than spawning subprocesses, both for
speed and to keep stdout/stderr capture clean.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from lacing import cli
from lacing.adapters import annot as _annot_adapter  # noqa: F401  registers
from lacing.adapters import textgrid as _tg  # noqa: F401  registers
from lacing.adapters import webvtt as _vtt  # noqa: F401  registers
from lacing.adapters import web_annotation as _wa  # noqa: F401  registers
from lacing.model import Annotation, MediaRef, Provenance
from lacing.store import MemoryStore
from lacing.tier import Tier
from lacing.time import RationalTime, TimeInterval


SAMPLE_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:01.500
hello

2
00:00:01.500 --> 00:00:03.000
world
"""


@pytest.fixture
def vtt_path(tmp_path):
    p = tmp_path / "in.vtt"
    p.write_text(SAMPLE_VTT, encoding="utf-8")
    return p


@pytest.fixture
def annot_path(tmp_path):
    """Build a small ``.annot`` file from scratch."""
    s = MemoryStore()
    s.add_tier(Tier("words"))
    for start, end, text in ((0, 1500, "hello"), (1500, 3000, "world"), (5000, 6250, "again")):
        s.add(
            Annotation(
                id=uuid4(),
                tier="words",
                reference=MediaRef(
                    asset_id="blake3:test",
                    interval=TimeInterval(
                        RationalTime(start, 1000), RationalTime(end, 1000)
                    ),
                ),
                body={"text": text},
                body_schema_uri="annot://schema/word/v1",
                provenance=Provenance(
                    was_generated_by="user:test",
                    was_attributed_to="test",
                    generated_at_time=RationalTime(0),
                ),
            )
        )
    p = tmp_path / "in.annot"
    _annot_adapter.dump(s, p)
    return p


# --- list_formats ----------------------------------------------------------


class TestListFormats:
    def test_lists_all_phase01_formats(self, capsys):
        cli.list_formats()
        captured = capsys.readouterr()
        for name in ("textgrid", "webvtt", "web_annotation", "annot"):
            assert name in captured.out


# --- convert ---------------------------------------------------------------


class TestConvert:
    def test_convert_vtt_to_annot(self, vtt_path, tmp_path, capsys):
        out = tmp_path / "out.annot"
        cli.convert(str(vtt_path), str(out))
        assert out.exists()
        # round-trip: load the .annot and confirm 2 cues survived
        loaded = _annot_adapter.load(out)
        anns = list(loaded.all())
        assert len(anns) == 2

    def test_convert_annot_to_jsonld(self, annot_path, tmp_path):
        out = tmp_path / "out.jsonld"
        cli.convert(str(annot_path), str(out))
        assert out.exists()
        d = json.loads(out.read_text())
        assert d["type"] == "AnnotationCollection"
        assert d["total"] == 3

    def test_convert_explicit_formats(self, vtt_path, tmp_path):
        out = tmp_path / "out.dat"  # extensionless target
        cli.convert(
            str(vtt_path),
            str(out),
            src_format="webvtt",
            dst_format="annot",
        )
        assert out.exists()

    def test_convert_unknown_dst_raises_systemexit(self, vtt_path, tmp_path):
        out = tmp_path / "out.unknown"
        with pytest.raises(SystemExit):
            cli.convert(str(vtt_path), str(out))


# --- query ----------------------------------------------------------------


class TestQuery:
    def test_query_all(self, annot_path, capsys):
        cli.query(str(annot_path))
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 3
        for line in out:
            d = json.loads(line)
            assert "id" in d
            assert "tier" in d

    def test_query_by_tier(self, annot_path, capsys):
        cli.query(str(annot_path), tier="words")
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 3

    def test_query_by_tier_no_matches(self, annot_path, capsys):
        cli.query(str(annot_path), tier="nonexistent")
        out = capsys.readouterr().out.strip()
        assert out == ""

    def test_query_window_intersects(self, annot_path, capsys):
        # The .annot was built with rate=1000; querying via the CLI uses
        # rate=24000 by default. Pick a window that intersects two cues
        # at any rate: [1.0, 2.0) intersects both [0, 1.5) and [1.5, 3.0).
        cli.query(
            str(annot_path),
            start=1.0,
            end=2.0,
            relation="intersects",
            rate=1000,
        )
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 2

    def test_query_window_during(self, annot_path, capsys):
        # Allen 'during' is strict: same start/end with the parent counts as
        # 'starts'/'finishes', not 'during'. [0, 4) strictly contains only
        # [1.5, 3.0) — [0, 1.5) shares a start (Allen 's', not 'd').
        cli.query(
            str(annot_path),
            start=0.0,
            end=4.0,
            relation="during",
            rate=1000,
        )
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1
        d = json.loads(out[0])
        assert d["start_seconds"] == 1.5

    def test_query_unknown_relation_raises(self, annot_path):
        with pytest.raises(SystemExit):
            cli.query(
                str(annot_path),
                start=0.0,
                end=10.0,
                relation="bogus",
                rate=1000,
            )

    def test_query_partial_window_raises(self, annot_path):
        with pytest.raises(SystemExit):
            cli.query(str(annot_path), start=1.0)  # missing --end

    def test_query_limit(self, annot_path, capsys):
        cli.query(str(annot_path), limit=1)
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1


# --- validate -------------------------------------------------------------


class TestValidate:
    def test_validate_summary(self, annot_path, capsys):
        cli.validate(str(annot_path))
        out = capsys.readouterr().out
        assert "annotations: 3" in out
        assert "tiers declared: 1" in out
        assert "words: 3" in out

    def test_validate_format_inferred(self, vtt_path, capsys):
        cli.validate(str(vtt_path))
        out = capsys.readouterr().out
        assert "format: webvtt" in out
        assert "annotations: 2" in out


# --- main entry point -----------------------------------------------------


class TestMain:
    def test_help_returns_cleanly(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "convert" in out
        assert "query" in out
        assert "validate" in out

    def test_subcommand_dispatch(self, capsys):
        """``main`` exits with the dispatcher's code — 0 on success.

        ``cw.run`` *returns* the exit code where argh's ``dispatch`` exited by
        itself, so ``main`` raises ``SystemExit`` with it. Without that,
        ``lacing no-such-command`` would exit 0; see
        ``TestExitCodes::test_unknown_command_exits_two``.
        """
        with pytest.raises(SystemExit) as exc:
            cli.main(["list-formats"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "textgrid" in out


class TestExitCodes:
    """What a shell sees. Recorded from the argh implementation before the swap."""

    def test_no_arguments_prints_usage_and_exits_zero(self, capsys):
        """argh's behaviour, which plain argparse does NOT reproduce."""
        with pytest.raises(SystemExit) as exc:
            cli.main([])
        assert exc.value.code == 0
        assert capsys.readouterr().out.startswith("usage: lacing")

    def test_unknown_command_exits_two(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["no-such-command"])
        assert exc.value.code == 2

    def test_underscored_command_spelling_is_not_accepted(self):
        """argh hyphenated command names; so does cw. ``list_formats`` never worked."""
        with pytest.raises(SystemExit) as exc:
            cli.main(["list_formats"])
        assert exc.value.code == 2

    def test_prog_stays_pinned_to_lacing(self):
        """``prog="lacing"`` was pinned before the migration; it still is.

        Without it, ``python -m lacing.cli`` would report ``cli.py``.
        """
        assert cli.mk_parser().prog == "lacing"


class TestOptionCoercion:
    """Option values reach the command as the type its annotation declares.

    ``lacing/cli.py`` has ``from __future__ import annotations``, so every
    annotation is a string at runtime. argh read ``__annotations__`` raw and was
    therefore blind to them: ``--start``, ``--end`` and ``--to-version`` all
    arrived as ``str``. ``migrate`` compensated with a hand-written ``int()`` in
    the command body; ``query`` never did. ``cw``'s ``resolve_hints=True``
    convention puts the conversion at argparse's ``type=`` site instead, which
    is where a bad value produces ``usage:`` + exit 2 rather than a traceback.
    """

    def _namespace(self, argv):
        return cli.mk_parser().parse_args(argv)

    def test_start_and_end_are_floats(self):
        ns = self._namespace(["query", "f.vtt", "--start", "1.5", "--end", "2"])
        assert ns.start == 1.5
        assert ns.end == 2.0
        assert isinstance(ns.start, float)
        assert isinstance(ns.end, float)

    def test_to_version_is_an_int(self):
        ns = self._namespace(["migrate", "f.annot", "--to-version", "3"])
        assert ns.to_version == 3
        assert isinstance(ns.to_version, int)

    def test_omitted_options_stay_none(self):
        ns = self._namespace(["query", "f.vtt"])
        assert ns.start is None and ns.end is None

    @pytest.mark.parametrize(
        "argv, flag",
        [
            (["query", "f.vtt", "--start", "abc", "--end", "2"], "--start"),
            (["query", "f.vtt", "--start", "1", "--end", "abc"], "--end"),
            (["migrate", "f.annot", "--to-version", "abc"], "--to-version"),
        ],
    )
    def test_a_bad_numeric_value_is_a_usage_error_not_a_traceback(
        self, argv, flag, capsys
    ):
        """Under argh these three exited 1 with a traceback from deep in the call stack."""
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "usage: lacing" in err
        assert flag in err

    def test_rate_and_limit_keep_the_int_type_argh_inferred_from_their_defaults(self):
        ns = self._namespace(["query", "f.vtt", "--rate", "1000", "--limit", "5"])
        assert (ns.rate, ns.limit) == (1000, 5)
