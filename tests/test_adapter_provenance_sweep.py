"""Every import adapter stamps a *known* generation time (lacing#44).

The adapters used to stamp ``RationalTime.zero(rate)`` — lacing's UNKNOWN
sentinel — as ``generated_at_time`` on every imported annotation, so an
import manufactured exactly the rows that read as unverifiable downstream.
This sweep runs each adapter's import on its own sample input and asserts
that every produced annotation can be placed in time. A guard test keeps
the sweep honest: a new adapter module must be added here or the guard
fails.
"""

from __future__ import annotations

import json
import pkgutil

import pytest

import lacing.adapters


# Adapters whose import *creates* provenance. ``annot`` is lacing's own
# format: it round-trips the provenance it was given, so it is not a
# stamping site.
STAMPING_ADAPTERS = (
    "eaf",
    "textgrid",
    "webvtt",
    "jams",
    "otio",
    "label_studio",
    "web_annotation",
)


def _load_eaf(tmp_path):
    from tests.test_adapter_eaf import adapter_module, build_sample_eaf

    return adapter_module.load(build_sample_eaf(tmp_path), rate=1000)


def _load_textgrid(tmp_path):
    from tests.test_adapter_textgrid import adapter_module, build_sample_textgrid

    return adapter_module.load(build_sample_textgrid(tmp_path), rate=1000)


def _load_webvtt(tmp_path):
    from tests.test_adapter_webvtt import SAMPLE_VTT, adapter_module

    return adapter_module.load(SAMPLE_VTT, rate=1000)


def _load_jams(tmp_path):
    from tests.test_adapter_jams import adapter_module, build_sample_jams

    return adapter_module.load(build_sample_jams(tmp_path), rate=1000)


def _load_otio(tmp_path):
    from tests.test_adapter_otio import adapter_module, build_sample_otio

    return adapter_module.load(build_sample_otio(tmp_path), rate=1000)


def _load_label_studio(tmp_path):
    from tests.test_adapter_label_studio import SAMPLE_TASK, adapter_module

    return adapter_module.load(json.dumps(SAMPLE_TASK), rate=1000)


def _load_web_annotation(tmp_path):
    from tests.test_adapter_web_annotation import COLLECTION, adapter_module

    return adapter_module.load(json.dumps(COLLECTION))


_LOADERS = {
    "eaf": _load_eaf,
    "textgrid": _load_textgrid,
    "webvtt": _load_webvtt,
    "jams": _load_jams,
    "otio": _load_otio,
    "label_studio": _load_label_studio,
    "web_annotation": _load_web_annotation,
}


@pytest.mark.parametrize("name", STAMPING_ADAPTERS)
def test_import_stamps_a_known_generation_time(name, tmp_path):
    """Every annotation an import produces has ``generated_at_is_known``.

    The sibling test module's ``importorskip`` fires on import, so an adapter
    whose optional dependency is absent skips here exactly as it does there.
    """
    store = _LOADERS[name](tmp_path)
    produced = list(store.all())
    assert produced, f"{name}: the sample input produced no annotations"
    unknown = [a.id for a in produced if not a.provenance.generated_at_is_known]
    assert unknown == [], f"{name}: tick-0 generated_at_time on {unknown}"


def test_every_adapter_module_is_swept():
    """A new adapter module lands in this sweep or this fails."""
    modules = {m.name for m in pkgutil.iter_modules(lacing.adapters.__path__)}
    assert modules == {"annot", *STAMPING_ADAPTERS}
