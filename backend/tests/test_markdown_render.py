"""Tests for :mod:`backend.services.markdown_render`."""

from __future__ import annotations

from backend.services.markdown_render import markdown_to_html


class TestMarkdownToHtml:
    """The renderer must emit TipTap/editor-compatible HTML."""

    def test_empty_input_returns_empty(self) -> None:
        assert markdown_to_html("") == ""
        assert markdown_to_html("   \n  ") == ""

    def test_headings(self) -> None:
        assert "<h2>Section</h2>" in markdown_to_html("## Section")

    def test_inline_marks(self) -> None:
        html = markdown_to_html("Text with **bold**, *italic*, `code`.")
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html
        assert "<code>code</code>" in html

    def test_links(self) -> None:
        html = markdown_to_html("See [site](https://example.com).")
        assert '<a href="https://example.com">site</a>' in html

    def test_lists(self) -> None:
        assert "<ul>" in markdown_to_html("- a\n- b")
        assert "<ol>" in markdown_to_html("1. a\n2. b")

    def test_fenced_code_gets_language_class(self) -> None:
        # CodeBlockLowlight reads the `language-` prefix.
        html = markdown_to_html("```c\nint main(){}\n```")
        assert '<code class="language-c">' in html
        assert "int main(){}" in html

    def test_blockquote_and_rule(self) -> None:
        assert "<blockquote>" in markdown_to_html("> quote")
        assert "<hr" in markdown_to_html("---")

    def test_table(self) -> None:
        html = markdown_to_html("| a | b |\n| - | - |\n| 1 | 2 |")
        assert "<table>" in html
        assert "<th>a</th>" in html

    def test_no_literal_markdown_leaks(self) -> None:
        html = markdown_to_html("## Title\n\n**bold**")
        assert "## Title" not in html
        assert "**bold**" not in html
