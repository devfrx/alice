"""AL\\CE — Markdown → editor-HTML rendering.

The Continuum note editor stores a note's body as **HTML** (``Note.content``):
the TipTap/ProseMirror document is serialised with ``getHTML()`` and re-parsed
with ``setContent(html)`` against the editor schema. Large-language-model
output, however, is naturally **markdown** (``# heading``, fenced ``` ``` ```
code, ``**bold**``, lists, tables). Writing that raw markdown straight into the
HTML ``content`` field makes the editor render the syntax literally instead of
as formatted blocks.

This module renders LLM markdown to the HTML the editor expects, so notes
created or updated through the ``notes`` plugin land as real blocks. The output
uses standard HTML5 elements that TipTap parses into native nodes — headings,
paragraphs, bullet/ordered lists, fenced code with ``language-<lang>`` classes
(matching ``CodeBlockLowlight``), blockquotes, GitHub-style tables and
horizontal rules, plus inline marks (bold, italic, inline code, links).
"""

from __future__ import annotations

import markdown

# Extensions chosen to match the editor's TipTap/HTML parsing surface:
# - ``fenced_code``: ``` fences → ``<pre><code class="language-x">`` (TipTap
#   CodeBlockLowlight reads the ``language-`` prefix).
# - ``tables``: GitHub-flavoured pipe tables → ``<table>``.
# - ``sane_lists``: list parsing that does not greedily merge adjacent
#   ordered/unordered lists, matching common editor expectations.
#
# Raw inline/block HTML is intentionally *not* enabled beyond markdown's
# defaults; the only surfaces that render this HTML are the TipTap schema
# parser (which admits known nodes only) and the editor's ``sanitizeHtml``
# preview, so model-supplied markup cannot introduce script execution.
_EXTENSIONS: list[str] = ["fenced_code", "tables", "sane_lists"]


def markdown_to_html(text: str) -> str:
    """Render markdown source to editor-compatible HTML.

    A fresh parser is created per call (``markdown.markdown`` is stateful
    across documents), which is fine for the low-frequency note-write path.

    Args:
        text: Markdown source (may be empty).

    Returns:
        HTML string, or ``""`` when ``text`` is empty/whitespace-only.
    """
    if not text or not text.strip():
        return ""
    return markdown.markdown(text, extensions=_EXTENSIONS)
