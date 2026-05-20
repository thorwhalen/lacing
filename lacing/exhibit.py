"""Artifact exhibit — render an annotation graph as a readable document.

Walks a set of :class:`~lacing.Annotation`\\ s and lays them out as a
document: each artifact is a card with its body, any generated images
embedded inline, and **in-document hyperlinks** to the artifacts it was
derived from and the ones it feeds into.

The annotation graph — annotations + ``provenance.was_derived_from`` +
image references — *is* the "artifacts and links" model, so this runs on
**any** lacing graph: a project, a test run's artifacts, anything. The
renderer is pure (graph → document) and has no knowledge of where the
graph came from.

HTML is the authored format; the PDF and Markdown derive from it so the
three never drift:

- **PDF** via ``weasyprint`` — chosen over wkhtmltopdf because it is the
  HTML→PDF engine that carries the in-document anchor links through to
  **clickable PDF links** (wkhtmltopdf renders them as broken external
  URIs).
- **Markdown** via ``dn.html_to_markdown``.

Both derivations are optional — ``pip install lacing[exhibit]``. A
missing converter raises an informative error naming the install
command, rather than silently dropping the format.

Images are resolved through an injected ``image_resolver`` callback
(image-reference → local file path) so this module needs no knowledge
of how media is stored or downloaded — the caller wires that in.
"""

from __future__ import annotations

import base64
import html as _html
import importlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Optional

__all__ = ["render_artifact_exhibit"]


# --------------------------------------------------------------------------
# Per-artifact rendering helpers
# --------------------------------------------------------------------------

_LABEL_FIELDS = (
    "caption",
    "logline",
    "description",
    "name",
    "panel_id",
    "beat_id",
    "label",
    "kind",
)


def _artifact_kind(ann: Any) -> str:
    """Short schema name of an annotation, e.g. ``storyboard-panel``."""
    uri = ann.body_schema_uri
    parts = [p for p in uri.replace("annot://", "").split("/") if p]
    # .../<name>/<version> → the name is the second-to-last segment.
    return parts[-2] if len(parts) >= 2 else uri


def _artifact_label(ann: Any) -> str:
    """A short human label — the first populated of a few well-known
    body fields, else the kind."""
    body = ann.body or {}
    for field in _LABEL_FIELDS:
        value = body.get(field)
        if isinstance(value, str) and value.strip():
            text = " ".join(value.split())
            return text if len(text) <= 70 else text[:67] + "…"
    return _artifact_kind(ann)


def _image_data_uri(
    image: Mapping, resolver: Callable[[Mapping], Optional[str]]
) -> Optional[str]:
    """Best-effort ``data:`` URI for one image reference.

    The ``resolver`` turns an image reference into a local file path
    (or ``None``). Returns ``None`` when the bytes can't be obtained —
    the caller then shows a placeholder.
    """
    try:
        path = resolver(image)
    except Exception:
        return None
    if not (path and Path(path).exists()):
        return None
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    ext = Path(path).suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if ext == "jpg" else ext
    return f"data:image/{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _render_value(value: Any) -> str:
    """HTML for one body-field value — readable, escaped, fold-if-long."""
    if isinstance(value, str):
        text = _html.escape(value).replace("\n", "<br>")
        if len(value) > 500:
            return f"<details><summary>{len(value)} chars</summary>{text}</details>"
        return text or "<em>—</em>"
    rendered = _html.escape(json.dumps(value, indent=2, default=str))
    if len(rendered) > 500:
        return f"<details><summary>show</summary><pre>{rendered}</pre></details>"
    return f"<pre>{rendered}</pre>"


def _render_body(body: Mapping) -> str:
    """A ``<dl>`` of an annotation's body fields (``images`` excluded —
    rendered separately)."""
    rows = []
    for key in sorted(body):
        if key == "images":
            continue
        rows.append(
            f"<dt>{_html.escape(str(key))}</dt><dd>{_render_value(body[key])}</dd>"
        )
    return f"<dl>{''.join(rows)}</dl>" if rows else ""


_EXHIBIT_CSS = """
:root { color-scheme: light dark; }
body { font: 15px/1.55 -apple-system, system-ui, sans-serif;
  max-width: 920px; margin: 0 auto; padding: 2rem 1.5rem; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
.summary { color: #666; margin-bottom: 2rem; }
.artifact { border: 1px solid #ccc; border-radius: 8px; padding: 1rem 1.25rem;
  margin: 1rem 0; }
.artifact h2 { font-size: 1.05rem; margin: 0 0 .5rem;
  display: flex; gap: .5rem; align-items: baseline; flex-wrap: wrap; }
.kind { font: 600 .7rem/1 ui-monospace, monospace; text-transform: uppercase;
  letter-spacing: .06em; background: #2a3a6e; color: #fff;
  padding: .2rem .45rem; border-radius: 4px; }
.aid { font: .7rem ui-monospace, monospace; color: #999; }
.label { font-weight: 400; color: #333; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .15rem .9rem;
  margin: .5rem 0; }
dt { font: 600 .75rem ui-monospace, monospace; color: #555; }
dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
pre { background: #f4f4f4; padding: .5rem; border-radius: 4px; overflow-x: auto;
  font-size: .8rem; margin: 0; white-space: pre-wrap; }
img.panel { max-width: 100%; border-radius: 6px; margin: .5rem 0; }
.links { font-size: .82rem; margin-top: .6rem; }
.links a { color: #2a3a6e; }
"""


def _build_exhibit_html(
    annotations: Sequence,
    *,
    title: str,
    image_resolver: Callable[[Mapping], Optional[str]],
) -> str:
    """Render the annotation graph as one self-contained HTML document —
    each artifact a card, images inline, derivation links as
    in-document hyperlinks."""
    by_id = {str(a.id): a for a in annotations}
    feeds: dict[str, list[str]] = {}
    for ann in annotations:
        for src in ann.provenance.was_derived_from:
            feeds.setdefault(str(src), []).append(str(ann.id))

    def _link(aid: str) -> str:
        target = by_id.get(aid)
        if target is None:
            return f'<span class="aid">{_html.escape(aid[:8])}</span>'
        text = f"{_artifact_kind(target)} · {_artifact_label(target)}"
        return f'<a href="#a-{aid}">{_html.escape(text)}</a>'

    kinds: dict[str, int] = {}
    for ann in annotations:
        kinds[_artifact_kind(ann)] = kinds.get(_artifact_kind(ann), 0) + 1
    summary = ", ".join(f"{n}× {k}" for k, n in sorted(kinds.items()))

    cards = []
    for ann in annotations:
        aid = str(ann.id)
        body = ann.body or {}
        imgs = ""
        for image in body.get("images") or ():
            uri = _image_data_uri(image, image_resolver)
            imgs += (
                f'<img class="panel" src="{uri}" alt="panel image">'
                if uri
                else f"<p><em>image unavailable: "
                f'{_html.escape(str(image.get("url") or ""))}</em></p>'
            )
        derived = ann.provenance.was_derived_from
        links = ""
        if derived:
            links += (
                '<div class="links">↑ derived from: '
                + ", ".join(_link(str(s)) for s in derived)
                + "</div>"
            )
        if feeds.get(aid):
            links += (
                '<div class="links">↓ feeds into: '
                + ", ".join(_link(c) for c in feeds[aid])
                + "</div>"
            )
        # Literal spaces between the heading spans: the flex layout
        # ignores them for the HTML render, but they give the HTML→md
        # conversion the word boundaries it needs.
        cards.append(
            f'<section class="artifact" id="a-{aid}">'
            f'<h2><span class="kind">{_html.escape(_artifact_kind(ann))}</span> '
            f'<span class="label">{_html.escape(_artifact_label(ann))}</span> '
            f'<span class="aid">{_html.escape(aid[:8])}</span></h2>'
            f"{imgs}{_render_body(body)}{links}</section>"
        )

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_html.escape(title)}</title><style>{_EXHIBIT_CSS}</style>"
        f"</head><body><h1>{_html.escape(title)}</h1>"
        f'<p class="summary">{len(annotations)} artifacts — '
        f"{_html.escape(summary)}</p>"
        f"{''.join(cards)}</body></html>"
    )


# --------------------------------------------------------------------------
# Optional-converter loading — informative errors, never a silent drop
# --------------------------------------------------------------------------


def _require(module: str, purpose: str):
    """Import an optional converter, or raise a clear, actionable error."""
    try:
        return importlib.import_module(module)
    except ImportError as e:  # noqa: TRY003 — the message *is* the point
        raise RuntimeError(
            f"lacing.exhibit: {purpose} needs the optional '{module}' "
            f"package. Install it with `pip install lacing[exhibit]` "
            f"(or `pip install {module}`)."
        ) from e


def _default_image_resolver(image: Mapping) -> Optional[str]:
    """The fallback resolver — use the image reference's own ``path``."""
    return image.get("path")


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def render_artifact_exhibit(
    annotations: Iterable,
    *,
    out_dir: str | Path,
    formats: Sequence[str] = ("html", "pdf", "md"),
    title: str = "Artifact exhibit",
    image_resolver: Optional[Callable[[Mapping], Optional[str]]] = None,
) -> list[Path]:
    """Render an annotation graph as a human-readable artifact exhibit.

    Lays every annotation out as a card — body, embedded images, and
    in-document hyperlinks to the artifacts it derives from / feeds
    into. **HTML is authored**; the PDF and Markdown derive from it.

    Args:
        annotations: the lacing annotations to exhibit (any iterable).
            Order is preserved — pass them chain-ordered for a document
            that reads top-to-bottom.
        out_dir: directory the ``exhibit.{html,pdf,md}`` files land in.
        formats: which of ``html`` / ``pdf`` / ``md`` to write. The HTML
            is always built in memory (the others derive from it).
        title: document title.
        image_resolver: ``image-reference → local file path`` callback.
            Defaults to reading the reference's own ``path`` field; a
            caller whose images live behind URLs passes a resolver that
            downloads / caches them (keeping this module media-agnostic).

    Returns:
        The written file paths.

    Raises:
        RuntimeError: when ``pdf`` / ``md`` is requested but its optional
            converter (``weasyprint`` / ``dn``) is not installed — the
            message names the install command.
    """
    annotations = list(annotations)
    resolver = image_resolver or _default_image_resolver
    html_doc = _build_exhibit_html(
        annotations, title=title, image_resolver=resolver
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if "html" in formats:
        p = out / "exhibit.html"
        p.write_text(html_doc, encoding="utf-8")
        written.append(p)

    if "pdf" in formats:
        # weasyprint, not wkhtmltopdf: only weasyprint carries the
        # in-document anchor links through to clickable PDF links.
        weasyprint = _require("weasyprint", "the PDF export")
        p = out / "exhibit.pdf"
        weasyprint.HTML(string=html_doc).write_pdf(str(p))
        written.append(p)

    if "md" in formats:
        dn = _require("dn", "the Markdown export")
        p = out / "exhibit.md"
        p.write_text(
            dn.html_to_markdown(html_doc.encode("utf-8")), encoding="utf-8"
        )
        written.append(p)

    return written
