"""AL\\CE — File content readers for different formats."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.core.plugin_models import ToolResult

# -- Lazy imports for optional dependencies --------------------------------

try:
    import pdfplumber
    _PDF_AVAILABLE = True
except ImportError:
    pdfplumber = None  # type: ignore[assignment]
    _PDF_AVAILABLE = False

try:
    import docx as python_docx
    _DOCX_AVAILABLE = True
except ImportError:
    python_docx = None  # type: ignore[assignment]
    _DOCX_AVAILABLE = False

# -- Supported text extensions ---------------------------------------------

_TEXT_EXTENSIONS: set[str] = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml",
    ".csv", ".log", ".xml", ".html", ".css", ".ini", ".cfg", ".toml",
}


# -- Formatting ------------------------------------------------------------

def format_numbered(
    text: str,
    *,
    offset: int = 1,
    limit: int,
    max_line_chars: int,
) -> tuple[str, dict[str, int | bool]]:
    """Render a ``cat -n`` style numbered slice of *text*.

    Args:
        text: Full decoded text to slice.
        offset: 1-based line number to start from.
        limit: Maximum number of lines to render.
        max_line_chars: Cap on the characters of a single line; longer
            lines are cut and marked with ``…[riga troncata]``.

    Returns:
        A ``(content, meta)`` tuple where *content* is the numbered
        slice and *meta* holds ``total_lines``, ``lines_read``,
        ``truncated`` and ``next_offset`` (0 when the slice reaches
        the end of the text).
    """
    lines = text.splitlines()
    total = len(lines)
    start = max(offset, 1) - 1
    window = lines[start:start + limit]
    rendered = []
    for i, line in enumerate(window, start=start + 1):
        if len(line) > max_line_chars:
            line = line[:max_line_chars] + " …[riga troncata]"
        rendered.append(f"{i:>6}\t{line}")
    truncated = start + len(window) < total
    meta: dict[str, int | bool] = {
        "total_lines": total,
        "lines_read": len(window),
        "truncated": truncated,
        "next_offset": (start + len(window) + 1) if truncated else 0,
    }
    return "\n".join(rendered), meta


# -- Private readers -------------------------------------------------------

def _read_plain_text(
    path: Path,
    max_bytes: int,
    max_chars: int,
    offset: int,
    limit: int,
    max_line_chars: int,
) -> dict[str, Any]:
    """Read a plain-text file as a numbered slice of lines.

    Opens in binary mode so *max_bytes* truly limits bytes read from
    disk, then decodes to UTF-8 and renders a ``cat -n`` style window
    of lines via :func:`format_numbered`.  *max_chars* caps the
    characters of the rendered output as a final safety net.

    Args:
        path: Absolute path to the file.
        max_bytes: Maximum bytes to read from disk.
        max_chars: Maximum characters of numbered output to return.
        offset: 1-based line number to start from.
        limit: Maximum number of lines to return.
        max_line_chars: Per-line character cap before truncation.

    Returns:
        A dict with the numbered content, path and the slice metadata
        (``total_lines``, ``lines_read``, ``truncated``,
        ``next_offset``).  ``total_lines`` counts decoded lines only:
        if the byte cap cut the file, the tail is not counted.
    """
    with open(path, "rb") as fh:
        raw_bytes = fh.read(max_bytes)

    bytes_truncated = len(raw_bytes) >= max_bytes
    raw = raw_bytes.decode("utf-8", errors="replace")

    content, meta = format_numbered(
        raw, offset=offset, limit=limit, max_line_chars=max_line_chars,
    )
    truncated = bool(meta["truncated"]) or bytes_truncated
    if len(content) > max_chars:
        content = (
            content[:max_chars]
            + "\n… [output troncato a max_chars: riduci limit o continua con offset]"
        )
        truncated = True

    return {
        "content": content,
        "path": str(path),
        "total_lines": meta["total_lines"],
        "lines_read": meta["lines_read"],
        "truncated": truncated,
        "next_offset": meta["next_offset"],
    }


def _read_pdf(path: Path, max_chars: int) -> dict[str, Any]:
    """Extract text from a PDF using pdfplumber.

    Args:
        path: Absolute path to the PDF file.
        max_chars: Maximum characters to return.

    Returns:
        A dict with content, truncated flag, chars_read and path.
    """
    pages_text: list[str] = []
    total_chars = 0

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
            total_chars += len(text)
            if total_chars >= max_chars:
                break

    full_text = "\n".join(pages_text)
    truncated = len(full_text) > max_chars
    content = full_text[:max_chars]

    return {
        "content": content,
        "truncated": truncated,
        "chars_read": len(content),
        "path": str(path),
    }


def _read_docx(path: Path, max_chars: int) -> dict[str, Any]:
    """Extract text from a DOCX using python-docx.

    Args:
        path: Absolute path to the DOCX file.
        max_chars: Maximum characters to return.

    Returns:
        A dict with content, truncated flag, chars_read and path.
    """
    doc = python_docx.Document(str(path))
    paragraphs: list[str] = []
    total_chars = 0

    for para in doc.paragraphs:
        paragraphs.append(para.text)
        total_chars += len(para.text) + 1  # +1 for newline
        if total_chars >= max_chars:
            break

    full_text = "\n".join(paragraphs)
    truncated = len(full_text) > max_chars
    content = full_text[:max_chars]

    return {
        "content": content,
        "truncated": truncated,
        "chars_read": len(content),
        "path": str(path),
    }


# -- Public API ------------------------------------------------------------

async def read_text_file(
    path: Path,
    max_bytes: int,
    max_chars: int,
    *,
    offset: int = 1,
    limit: int = 2000,
    max_line_chars: int = 2000,
) -> dict[str, Any] | ToolResult:
    """Read file content, dispatching by extension.

    Supports plain text formats, PDF (via pdfplumber) and DOCX
    (via python-docx).  Unsupported extensions return a ToolResult error.
    Plain-text files are returned as a ``cat -n`` style numbered slice
    (*offset*/*limit* are line-based); PDF and DOCX return plain
    extracted text without line numbers.

    Args:
        path: Absolute path to the file.
        max_bytes: Maximum bytes to read (text files only).
        max_chars: Maximum characters to return.
        offset: 1-based start line for text files.
        limit: Maximum lines to return for text files.
        max_line_chars: Per-line character cap for text files.

    Returns:
        A dict with content info on success, or a ``ToolResult.error``
        for unsupported formats or missing dependencies.
    """
    ext = path.suffix.lower()

    if ext in _TEXT_EXTENSIONS:
        return await asyncio.to_thread(
            _read_plain_text, path, max_bytes, max_chars,
            offset, limit, max_line_chars,
        )

    if ext == ".pdf":
        if not _PDF_AVAILABLE:
            return ToolResult.error(
                "pdfplumber is not installed — cannot read PDF files. "
                "Install with: pip install pdfplumber"
            )
        return await asyncio.to_thread(_read_pdf, path, max_chars)

    if ext == ".docx":
        if not _DOCX_AVAILABLE:
            return ToolResult.error(
                "python-docx is not installed — cannot read DOCX files. "
                "Install with: pip install python-docx"
            )
        return await asyncio.to_thread(_read_docx, path, max_chars)

    return ToolResult.error(f"Unsupported file type: {ext}")
