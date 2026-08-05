"""Tests for lacing.digest — the annotation value/body content digests.

The acceptance criteria of thorwhalen/lacing#16 are the first four classes:
regeneration-invariance, value-sensitivity, cross-process + round-trip
stability, and FastAPI-free importability.
"""

from __future__ import annotations

import doctest
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

import lacing.digest as digest_module
from lacing import (
    Annotation,
    AnnotationRef,
    MediaRef,
    NodeRef,
    Provenance,
    RationalTime,
    TimeInterval,
    annotation_body_digest,
    annotation_value_digest,
)


def _ti(start: int = 0, end: int = 24000) -> TimeInterval:
    return TimeInterval(RationalTime(start), RationalTime(end))


def _prov(*, at: int = 0, by: str = "agent:m@1", derived=()) -> Provenance:
    return Provenance(
        was_generated_by=by,
        was_attributed_to="thor",
        was_derived_from=list(derived),
        generated_at_time=RationalTime(at),
    )


def _ann(**overrides) -> Annotation:
    kwargs = dict(
        id=uuid4(),
        tier="words",
        reference=MediaRef(asset_id="sha256:abc", interval=_ti()),
        body={"text": "hello"},
        body_schema_uri="annot://schema/word/v1",
        provenance=_prov(),
        confidence=None,
    )
    kwargs.update(overrides)
    return Annotation(**kwargs)


# --- 1. the whole point: regeneration-invariance -----------------------------


class TestRegenerationInvariance:
    """Acceptance criterion #1 — this is why the module exists."""

    def test_id_and_timestamp_do_not_change_the_value_digest(self):
        a = _ann()
        b = _ann(provenance=_prov(at=987654))
        assert a.id != b.id
        assert a.provenance.generated_at_time != b.provenance.generated_at_time
        assert annotation_value_digest(a) == annotation_value_digest(b)

    def test_but_they_do_change_the_etag(self):
        """The contrast is the acceptance criterion, not an implementation detail."""
        etag = pytest.importorskip("lacing.server.etag")
        a = _ann()
        b = _ann(provenance=_prov(at=987654))
        assert etag.annotation_etag(a) != etag.annotation_etag(b)

    def test_whole_provenance_is_excluded(self):
        a = _ann()
        for changed in (
            _ann(provenance=_prov(by="agent:other@2")),
            _ann(provenance=_prov(derived=[uuid4(), uuid4()])),
            _ann(
                provenance=Provenance(
                    was_generated_by="agent:m@1",
                    was_attributed_to="someone-else",
                    generated_at_time=RationalTime(0),
                    activity="derive",
                )
            ),
        ):
            assert annotation_value_digest(changed) == annotation_value_digest(a)

    def test_body_digest_is_also_regeneration_invariant(self):
        assert annotation_body_digest(_ann()) == annotation_body_digest(
            _ann(provenance=_prov(at=5))
        )


# --- 2. every included field actually moves the digest -----------------------


class TestValueSensitivity:
    """Acceptance criterion #2 — one assertion per member of VALUE_FIELDS."""

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"body": {"text": "goodbye"}}, id="body"),
            pytest.param({"tier": "phonemes"}, id="tier"),
            pytest.param(
                {"body_schema_uri": "annot://schema/word/v2"}, id="body_schema_uri"
            ),
            pytest.param({"confidence": 0.5}, id="confidence"),
            pytest.param(
                {"reference": MediaRef(asset_id="sha256:abc", interval=_ti(1, 24000))},
                id="reference-interval",
            ),
            pytest.param(
                {"reference": MediaRef(asset_id="sha256:def", interval=_ti())},
                id="reference-asset",
            ),
            pytest.param(
                {"reference": NodeRef(scene_path="/scene/a", interval=_ti())},
                id="reference-kind",
            ),
        ],
    )
    def test_changing_an_included_field_changes_the_digest(self, overrides):
        assert annotation_value_digest(_ann(**overrides)) != annotation_value_digest(
            _ann()
        )

    def test_every_value_field_is_covered_by_the_parametrization(self):
        """Guard against a new VALUE_FIELDS entry sneaking in untested."""
        assert set(digest_module.VALUE_FIELDS) == {
            "body",
            "body_schema_uri",
            "confidence",
            "reference",
            "tier",
        }

    def test_value_fields_and_the_exclusions_partition_the_envelope(self):
        """The boundary must be exhaustive over `Annotation`, not just self-consistent.

        The test above pins VALUE_FIELDS against a literal, so it catches an
        edit to *digest.py*. It cannot catch an edit to *model.py* — and that
        is the direction that produces a wrong cache **hit**: a new
        value-bearing field on `Annotation` that nobody adds to VALUE_FIELDS is
        simply absent from the digest, so two annotations differing only in it
        digest alike and a downstream early cutoff never fires.

        Asserting the partition makes a new envelope field fail the build until
        someone rules it explicitly in (VALUE_FIELDS) or out (the exclusion
        set), which is the only safe default.
        """
        excluded = {"id", "provenance"}
        assert set(Annotation.model_fields) == (
            set(digest_module.VALUE_FIELDS) | excluded
        )

    def test_confidence_none_differs_from_zero(self):
        """None ('unscored') and 0.0 ('scored, and it is bad') are different claims."""
        assert annotation_value_digest(_ann(confidence=None)) != (
            annotation_value_digest(_ann(confidence=0.0))
        )

    def test_nested_body_change_changes_the_digest(self):
        a = _ann(body={"outer": {"inner": [1, 2, 3]}})
        b = _ann(body={"outer": {"inner": [1, 2, 4]}})
        assert annotation_value_digest(a) != annotation_value_digest(b)

    def test_id_is_not_in_the_payload(self):
        assert "id" not in digest_module.VALUE_FIELDS
        assert "provenance" not in digest_module.VALUE_FIELDS


class TestBodyDigestBoundary:
    """The narrow sibling: same body, different timing → same body digest."""

    def test_retiming_leaves_body_digest_unchanged(self):
        early = _ann(reference=MediaRef(asset_id="sha256:abc", interval=_ti(0, 100)))
        late = _ann(reference=MediaRef(asset_id="sha256:abc", interval=_ti(500, 600)))
        assert annotation_body_digest(early) == annotation_body_digest(late)
        assert annotation_value_digest(early) != annotation_value_digest(late)

    def test_tier_and_confidence_are_outside_the_body_digest(self):
        a = _ann()
        assert annotation_body_digest(_ann(tier="phonemes")) == annotation_body_digest(
            a
        )
        assert annotation_body_digest(_ann(confidence=0.9)) == annotation_body_digest(a)

    def test_body_and_schema_uri_are_inside_it(self):
        a = _ann()
        assert annotation_body_digest(_ann(body={"text": "x"})) != (
            annotation_body_digest(a)
        )
        assert annotation_body_digest(
            _ann(body_schema_uri="annot://schema/word/v2")
        ) != annotation_body_digest(a)

    def test_the_two_digests_are_domain_separated(self):
        """No annotation can make the value and body digests collide."""
        a = _ann()
        assert annotation_value_digest(a) != annotation_body_digest(a)
        assert digest_module.VALUE_DIGEST_SCHEME != digest_module.BODY_DIGEST_SCHEME

    def test_scheme_tag_participates_in_the_digest(self):
        """Mutation guard: a no-op scheme tag would make this pass regardless."""
        payload = {"body": {"text": "hello"}}
        assert digest_module._digest("a", payload) != digest_module._digest(
            "b", payload
        )


# --- 3. determinism ----------------------------------------------------------


class TestDeterminism:
    """Acceptance criterion #3 — across dict ordering, processes, round-trips."""

    def test_dict_insertion_order_does_not_matter(self):
        forward = {"a": 1, "b": {"x": 1, "y": 2}, "c": [1, 2]}
        backward = {"c": [1, 2], "b": {"y": 2, "x": 1}, "a": 1}
        assert forward == backward
        assert list(forward) != list(backward)
        assert annotation_value_digest(_ann(body=forward)) == annotation_value_digest(
            _ann(body=backward)
        )

    def test_non_string_body_keys_raise_rather_than_collapse(self):
        """A non-str key is refused, because coercing it can LOSE an entry.

        `model_dump(mode="json")` coerces keys to strings, and two distinct
        keys can coerce to the same string: `{1: "a", "1": "b"}` dumps to
        `{"1": "b"}`. Digesting that would let two annotations differing only
        in the annihilated entry digest alike — a wrong cache HIT, which is the
        exact hazard this module exists to prevent. Such a body is already
        broken data: it does not survive a store round-trip either.
        """
        for body in ({1: "a", "2": "b"}, {1: "a", "1": "b"}, {None: "x"}):
            with pytest.raises(digest_module.NonStringBodyKeyError):
                annotation_value_digest(_ann(body=body))
            with pytest.raises(digest_module.NonStringBodyKeyError):
                annotation_body_digest(_ann(body=body))

    def test_nested_non_string_keys_are_refused_too(self):
        """The collapse hazard is identical one level down, and inside lists."""
        for body in (
            {"k": {1: "a", "1": "b"}},
            {"k": [{"deep": {2: "v"}}]},
        ):
            with pytest.raises(digest_module.NonStringBodyKeyError):
                annotation_value_digest(_ann(body=body))

    def test_the_refusal_names_the_offending_path(self):
        """An error that does not say WHERE sends the reader to the wrong producer."""
        with pytest.raises(digest_module.NonStringBodyKeyError) as excinfo:
            annotation_value_digest(_ann(body={"outer": {7: "v"}}))
        assert "body['outer']" in str(excinfo.value)

    def test_the_collapse_this_guard_prevents_is_real(self):
        """Pin the underlying pydantic behaviour, so the guard's rationale is
        checked rather than asserted. If pydantic ever stops collapsing, this
        fails and the guard can be reconsidered on evidence."""
        collapsed = _ann(body={1: "a", "1": "b"}).model_dump(mode="json")["body"]
        assert collapsed == {"1": "b"}  # the {1: "a"} entry is gone

    def test_stable_across_processes(self, tmp_path: Path):
        """Fresh interpreters, hash randomisation on, must agree.

        PYTHONHASHSEED is what makes this a real test rather than a repeat of
        the in-process one: set-and-str hashing differs per process by default,
        and any ordering that leaked into the canonical form would show here.
        """
        script = tmp_path / "digest_once.py"
        script.write_text(
            "\n".join(
                [
                    "import json",
                    "from uuid import uuid4",
                    "from lacing import (Annotation, MediaRef, Provenance,",
                    "    RationalTime, TimeInterval, annotation_value_digest,",
                    "    annotation_body_digest)",
                    "body = {'zeta': 1, 'alpha': {'q': [1, 2], 'p': 'x'}, 'mid': None}",
                    "a = Annotation(",
                    "    id=uuid4(), tier='words',",
                    "    reference=MediaRef(asset_id='sha256:abc',",
                    "        interval=TimeInterval(RationalTime(0), RationalTime(24000))),",
                    "    body=body, body_schema_uri='annot://schema/word/v1',",
                    "    provenance=Provenance(was_generated_by='agent:m@1',",
                    "        was_attributed_to='thor', generated_at_time=RationalTime.now()),",
                    "    confidence=0.25)",
                    "print(json.dumps([annotation_value_digest(a),",
                    "    annotation_body_digest(a)]))",
                ]
            )
        )
        results = []
        for seed in ("0", "1", "12345"):
            out = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                check=True,
                env={**os.environ, "PYTHONHASHSEED": seed},
            )
            results.append(json.loads(out.stdout))
        assert results[0] == results[1] == results[2]
        # And the child agrees with this process, which is the real claim.
        assert results[0][0] == annotation_value_digest(
            _ann(
                body={"zeta": 1, "alpha": {"q": [1, 2], "p": "x"}, "mid": None},
                confidence=0.25,
            )
        )

    def test_stable_across_an_annot_round_trip(self, tmp_path: Path):
        from lacing.adapters import annot as annot_adapter
        from lacing.store import MemoryStore
        from lacing.tier import Tier

        store = MemoryStore()
        store.add_tier(Tier("words"))
        original = _ann(body={"text": "hello", "n": 3}, confidence=0.75)
        store.add(original)
        before = annotation_value_digest(original)

        path = tmp_path / "round-trip.annot"
        annot_adapter.dump(store, path)
        reloaded = annot_adapter.load(path)
        [restored] = list(reloaded.all())

        assert annotation_value_digest(restored) == before
        assert annotation_body_digest(restored) == annotation_body_digest(original)

    def test_repeated_calls_agree(self):
        a = _ann(body={"k": [{"z": 1, "a": 2}]})
        assert len({annotation_value_digest(a) for _ in range(20)}) == 1


# --- 4. packaging: usable without the server extra ---------------------------


class TestImportLightness:
    """Acceptance criterion #4 — `from lacing import annotation_value_digest`
    must work without FastAPI, i.e. must not route through lacing.server."""

    def test_digest_modules_own_imports_are_stdlib_only(self, tmp_path: Path):
        """Execute lacing/digest.py in a fresh interpreter, bypassing the
        package ``__init__``, and assert every module it newly imports is in
        the standard library. That is what "import-light" has to mean: not
        "does not import FastAPI today" but "cannot acquire a heavy import".
        """
        script = tmp_path / "import_probe.py"
        script.write_text(
            "\n".join(
                [
                    "import sys, json",
                    "import importlib.util as u",
                    "before = set(sys.modules)",
                    "spec = u.spec_from_file_location('_probe', sys.argv[1])",
                    "m = u.module_from_spec(spec); spec.loader.exec_module(m)",
                    "new = {n.split('.')[0] for n in set(sys.modules) - before}",
                    "print(json.dumps(sorted(",
                    "    n for n in new",
                    "    if n and not n.startswith('_')",
                    "    and n not in sys.stdlib_module_names))) ",
                ]
            )
        )
        out = subprocess.run(
            [sys.executable, str(script), str(Path(digest_module.__file__))],
            capture_output=True,
            text=True,
            check=True,
        )
        non_stdlib = json.loads(out.stdout)
        assert non_stdlib == [], f"lacing.digest dragged in {non_stdlib}"

    def test_importing_lacing_does_not_import_fastapi(self, tmp_path: Path):
        script = tmp_path / "pkg_probe.py"
        script.write_text(
            "\n".join(
                [
                    "import sys, lacing",
                    "assert lacing.annotation_value_digest",
                    "assert lacing.annotation_body_digest",
                    "print(','.join(n for n in ('fastapi', 'starlette')",
                    "    if n in sys.modules))",
                ]
            )
        )
        out = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            check=True,
        )
        assert out.stdout.strip() == ""

    def test_digest_module_is_not_under_server(self):
        assert Path(digest_module.__file__).parent.name == "lacing"

    def test_exported_from_package_root(self):
        import lacing

        assert "annotation_value_digest" in lacing.__all__
        assert "annotation_body_digest" in lacing.__all__


# --- 5. misc contracts -------------------------------------------------------


class TestShape:
    def test_digests_are_sha256_hex(self):
        for fn in (annotation_value_digest, annotation_body_digest):
            d = fn(_ann())
            assert len(d) == 64
            assert set(d) <= set("0123456789abcdef")

    def test_works_for_every_reference_kind(self):
        refs = [
            MediaRef(asset_id="sha256:abc", interval=_ti()),
            NodeRef(scene_path="/scene/a", interval=_ti()),
            AnnotationRef(target_id=uuid4(), interval=None),
        ]
        digests = {annotation_value_digest(_ann(reference=r)) for r in refs}
        assert len(digests) == 3

    def test_unserialisable_body_raises_rather_than_digesting_a_repr(self):
        """A repr carries a memory address — digesting one would be silently
        non-deterministic. Failing loudly is the correct behaviour."""
        from pydantic_core import PydanticSerializationError

        with pytest.raises(PydanticSerializationError):
            annotation_value_digest(_ann(body={"o": object()}))

    def test_doctests(self):
        results = doctest.testmod(digest_module, verbose=False)
        # `failed == 0` alone passes vacuously on an example-free module, so
        # deleting every doctest would leave this test green. Pin the floor.
        assert results.attempted >= 10
        assert results.failed == 0
