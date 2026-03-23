"""AL\\CE — File content readers for different formats."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

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


# -- Private readers -------------------------------------------------------

def _read_plain_text(path: Path, max_bytes: int, max_chars: int) -> dict:
    """Read a plain-text file with size limits.

    Opens in binary mode so *max_bytes* truly limits bytes read from
    disk, then decodes to UTF-8.  *max_chars* limits the characters
    returned to the caller.

    Args:
        path: Absolute path to the file.
        max_bytes: Maximum bytes to read from disk.
        max_chars: Maximum characters to return after decoding.

    Returns:
        A dict with content, truncated flag, chars_read and path.
    """
    with open(path, "rb") as fh:
        raw_bytes = fh.read(max_bytes)

    truncated = len(raw_bytes) >= max_bytes
    raw = raw_bytes.decode("utf-8", errors="replace")
    content = raw[:max_chars]
    if len(raw) > max_chars:
        truncated = True

    return {
        "content": content,
        "truncated": truncated,
        "chars_read": len(content),
        "path": str(path),
    }


def _read_pdf(path: Path, max_chars: int) -> dict:
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


def _read_docx(path: Path, max_chars: int) -> dict:
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
) -> dict | ToolResult:
    """Read file content, dispatching by extension.

    Supports plain text formats, PDF (via pdfplumber) and DOCX
    (via python-docx).  Unsupported extensions return a ToolResult error.

    Args:
        path: Absolute path to the file.
        max_bytes: Maximum bytes to read (text files only).
        max_chars: Maximum characters to return.

    Returns:
        A dict with content info on success, or a ``ToolResult.error``
        for unsupported formats or missing dependencies.
    """
    ext = path.suffix.lower()

    if ext in _TEXT_EXTENSIONS:
        return await asyncio.to_thread(
            _read_plain_text, path, max_bytes, max_chars,
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
