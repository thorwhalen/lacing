"""Tests for ``lacing.exhibit`` — the artifact-graph exhibit renderer.

The core is the pure ``annotations → HTML`` builder, exercised here with
lightweight stand-ins. The PDF / Markdown derivations are optional
converters; they are checked only for the "informative error when
absent" contract, not for output fidelity.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lacing.exhibit import (
    _artifact_kind,
    _artifact_label,
    _build_exhibit_html,
    _require,
    render_artifact_exhibit,
)


def _ann(aid: str, kind: str, body: dict, derived_from=()):
    """A minimal annotation stand-in — the fields the exhibit reads."""
    return SimpleNamespace(
        id=aid,
        body=body,
        body_schema_uri=f"annot://schema/{kind}/v1",
        provenance=SimpleNamespace(was_derived_from=list(derived_from)),
    )


def _resolver(_image):  # default-ish resolver for tests
    return None


def test_artifact_kind_and_label():
    beat = _ann("b1", "beat", {"description": "Alex climbs the tower"})
    assert _artifact_kind(beat) == "beat"
    assert _artifact_label(beat) == "Alex climbs the tower"
    assert _artifact_label(_ann("x", "treatment", {})) == "treatment"


def test_exhibit_html_renders_artifacts_and_derivation_links():
    treatment = _ann("t-1", "treatment", {"logline": "A bell rings at midnight"})
    beat = _ann("b-1", "beat", {"description": "Alex climbs"}, derived_from=["t-1"])
    html = _build_exhibit_html(
        [treatment, beat], title="Demo", image_resolver=_resolver
    )

    # Both artifacts are anchored sections.
    assert 'id="a-t-1"' in html
    assert 'id="a-b-1"' in html
    # The beat hyperlinks back to the treatment; the treatment shows the
    # reverse "feeds into" link — these are the in-document graph links.
    assert 'href="#a-t-1"' in html
    assert "derived from" in html and "feeds into" in html
    assert "A bell rings at midnight" in html


def test_exhibit_html_image_resolver_is_used_and_degrades_gracefully():
    panel = _ann(
        "p-1", "storyboard-panel", {"images": [{"url": "http://x/y.jpg"}]}
    )
    # Resolver yielding no usable path → graceful placeholder, not a crash.
    html = _build_exhibit_html([panel], title="Demo", image_resolver=_resolver)
    assert "image unavailable" in html


def test_exhibit_html_escapes_title_and_handles_an_empty_graph():
    html = _build_exhibit_html([], title="Empty <demo>", image_resolver=_resolver)
    assert "Empty &lt;demo&gt;" in html
    assert "0 artifacts" in html


def test_render_artifact_exhibit_writes_html(tmp_path):
    anns = [_ann("t-1", "treatment", {"logline": "x"})]
    written = render_artifact_exhibit(
        anns, out_dir=tmp_path, formats=("html",), title="T"
    )
    assert written == [tmp_path / "exhibit.html"]
    assert "treatment" in (tmp_path / "exhibit.html").read_text()


def test_render_artifact_exhibit_writes_images_as_sibling_files(tmp_path):
    """A panel image is written once under ``images/`` and referenced
    relatively — the HTML carries no base64 blob."""
    img = tmp_path / "src.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"fake-jpeg-bytes" * 80)
    panel = _ann("p-1", "storyboard-panel", {"images": [{"path": str(img)}]})

    out = tmp_path / "ex"
    written = render_artifact_exhibit(
        [panel], out_dir=out, formats=("html",), title="T"
    )
    html = written[0].read_text(encoding="utf-8")
    # A relative reference, not an inlined base64 data URI.
    assert 'src="images/' in html
    assert "data:image" not in html
    # The bytes landed once under images/.
    image_files = list((out / "images").iterdir())
    assert len(image_files) == 1
    assert image_files[0].read_bytes() == img.read_bytes()


def test_render_artifact_exhibit_no_images_leaves_no_images_dir(tmp_path):
    """An image-free graph creates no empty ``images/`` directory."""
    render_artifact_exhibit(
        [_ann("t-1", "treatment", {"logline": "x"})],
        out_dir=tmp_path, formats=("html",), title="T",
    )
    assert not (tmp_path / "images").exists()


def test_require_raises_an_install_hint_for_a_missing_converter():
    """A missing optional converter fails with an actionable error
    naming the install command — never a silent drop."""
    with pytest.raises(RuntimeError, match=r"pip install lacing\[exhibit\]"):
        _require("lacing_no_such_converter_xyz", "the PDF export")
