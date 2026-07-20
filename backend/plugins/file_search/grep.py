"""Bounded pure-Python content grep (spec Fase 2 §4.6 — no ripgrep binary).

Deliberate deviation from Claude Code: no external ripgrep binary (PyInstaller
bundling), a pure-Python scan with hard bounds instead.  The walk is
``Path.rglob("*")`` in sorted order, each candidate passing the filters is
read whole (UTF-8 with replacement) and matched line-by-line with ``re``.

Bounds (all fail-open into ``truncated=True``, never an error):

* ``max_files`` — number of files actually content-scanned.
* ``max_matches`` — a GLOBAL budget of matching lines across the whole scan,
  in every output mode.  In ``content`` mode it coincides with the number of
  collected :class:`GrepMatch` entries; in ``files_with_matches``/``count``
  mode it caps the total hits counted, so the LAST file recorded may carry a
  partial (lower-bound) count.  Reaching the budget stops the scan.
* binary files (NUL byte in the first 8 KiB) and files over 1 MiB are
  skipped silently, mirroring ``read_text_file``'s byte cap.

Line numbering uses ``text.split("\\n")`` (NOT ``splitlines``) for parity
with ``read_text_file``'s numbering (decisione T9).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from backend.core.path_safety import is_forbidden, is_relative_to

_BINARY_SNIFF_BYTES = 8192
_MAX_FILE_BYTES = 1_048_576  # allineato a max_file_size_read_bytes

OUTPUT_MODES: tuple[str, ...] = ("files_with_matches", "content", "count")


@dataclass(frozen=True, slots=True)
class GrepOptions:
    """Options for :func:`run_grep`.

    Attributes:
        pattern: Python regular expression matched per-line.
        glob: Optional ``fnmatch`` pattern applied to the file NAME
            (not the full path), e.g. ``*.py``.
        extensions: Optional suffix whitelist (leading dot optional,
            case-insensitive), e.g. ``(".py", ".txt")``.
        output_mode: One of :data:`OUTPUT_MODES`.
        context_lines: Lines of context around each match
            (``content`` mode only).
        case_insensitive: Compile the regex with ``re.IGNORECASE``.
        max_files: Maximum number of files to content-scan.
        max_matches: Global budget of matching lines (see module docs).
        follow_symlinks: Whether symlinked files may be scanned.
    """

    pattern: str
    glob: str | None = None
    extensions: tuple[str, ...] = ()
    output_mode: str = "files_with_matches"  # | "content" | "count"
    context_lines: int = 0
    case_insensitive: bool = False
    max_files: int = 5000
    max_matches: int = 200
    follow_symlinks: bool = False


@dataclass(frozen=True, slots=True)
class GrepMatch:
    """A single matching line with optional surrounding context."""

    path: Path
    line_number: int
    line: str
    context_before: tuple[str, ...] = ()
    context_after: tuple[str, ...] = ()


@dataclass(slots=True)
class GrepResult:
    """Mutable, incrementally-filled result of :func:`run_grep`.

    Filled in place during the scan so a caller that abandons the call
    (timeout) can still read the partial harvest via a shared instance.

    Attributes:
        files: Resolved paths of files with at least one hit, in scan
            (sorted-walk) order.
        matches: Collected matches (``content`` mode only).
        counts: Per-file hit counts keyed by resolved path string
            (every mode; the last entry may be a lower bound when the
            ``max_matches`` budget fired mid-file).
        truncated: ``True`` when any bound fired (``max_files``,
            ``max_matches`` or a caller-side timeout).
        files_scanned: Number of files actually content-scanned.
    """

    files: list[Path] = field(default_factory=list)
    matches: list[GrepMatch] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    files_scanned: int = 0


def _normalize_extensions(extensions: tuple[str, ...]) -> set[str]:
    """Lowercase the suffix whitelist and ensure each entry has a dot.

    Args:
        extensions: Raw suffixes, with or without the leading dot.

    Returns:
        A set of lowercase dotted suffixes (empty when no filter).
    """
    normalized: set[str] = set()
    for ext in extensions:
        e = ext.lower()
        normalized.add(e if e.startswith(".") else f".{e}")
    return normalized


def _is_binary(path: Path) -> bool:
    """Sniff the first ``_BINARY_SNIFF_BYTES`` for a NUL byte.

    Args:
        path: Resolved file path to sniff.

    Returns:
        ``True`` when the file looks binary.
    """
    with path.open("rb") as fh:
        return b"\x00" in fh.read(_BINARY_SNIFF_BYTES)


def run_grep(
    root: Path,
    options: GrepOptions,
    forbidden: tuple[Path, ...] = (),
    sink: GrepResult | None = None,
) -> GrepResult:
    """Scan file CONTENTS under *root* for a regex, bounded.

    Walks ``root.rglob("*")`` in sorted order and matches every eligible
    text file line-by-line.  A candidate is skipped when it is not a
    regular file, is a symlink while ``follow_symlinks`` is off, resolves
    outside *root* (symlink escape), sits under a forbidden directory,
    fails the ``glob``/``extensions`` filters, exceeds 1 MiB or sniffs
    as binary.  Unreadable files (``OSError``) are skipped, never fatal.

    Bound semantics (declared, see module docstring): ``max_files``
    bounds the files content-scanned; ``max_matches`` is a single global
    budget of matching lines across the whole scan in EVERY output mode —
    when it fires the scan stops and ``truncated`` is set (in non-content
    modes the last recorded file's count is then a lower bound, correct
    up to the budget).  ``truncated`` may be conservatively ``True`` when
    the budget is reached exactly on the final match.

    Args:
        root: Already-validated root directory to scan under.
        options: Scan options (pattern, filters, mode, bounds).
        forbidden: Directories that are always blocked (resolved or
            resolvable; re-resolved defensively here).
        sink: Optional pre-built result to fill in place, so a caller
            that times out can still read the partial harvest.

    Returns:
        The (possibly shared) :class:`GrepResult`.

    Raises:
        ValueError: If the regex does not compile or ``output_mode`` is
            not one of :data:`OUTPUT_MODES`.
    """
    if options.output_mode not in OUTPUT_MODES:
        raise ValueError(
            f"output_mode non valido: {options.output_mode!r} "
            f"(ammessi: {', '.join(OUTPUT_MODES)})"
        )
    try:
        regex = re.compile(
            options.pattern, re.IGNORECASE if options.case_insensitive else 0,
        )
    except re.error as exc:
        raise ValueError(f"regex non valida: {exc}") from exc

    root_resolved = root.resolve()
    forbidden_resolved = tuple(fb.resolve() for fb in forbidden)
    ext_filter = _normalize_extensions(options.extensions)
    context_lines = max(options.context_lines, 0)
    result = sink if sink is not None else GrepResult()
    total_hits = 0

    for candidate in sorted(root_resolved.rglob("*")):
        try:
            if not candidate.is_file():
                continue
            if result.files_scanned >= options.max_files:
                # Another file was up next: the enumeration is incomplete.
                result.truncated = True
                break
            if not options.follow_symlinks and candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if not is_relative_to(resolved, root_resolved):
                continue
            if is_forbidden(resolved, forbidden_resolved):
                continue
            if options.glob and not fnmatch.fnmatch(candidate.name, options.glob):
                continue
            if ext_filter and candidate.suffix.lower() not in ext_filter:
                continue
            if resolved.stat().st_size > _MAX_FILE_BYTES or _is_binary(resolved):
                continue
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("grep: skipping {}: {}", candidate, exc)
            continue

        result.files_scanned += 1
        lines = text.split("\n")
        file_hits = 0
        budget_hit = False
        for idx, line in enumerate(lines):
            if not regex.search(line):
                continue
            file_hits += 1
            total_hits += 1
            if options.output_mode == "content":
                lo = max(0, idx - context_lines)
                result.matches.append(GrepMatch(
                    path=resolved,
                    line_number=idx + 1,
                    line=line,
                    context_before=tuple(lines[lo:idx]),
                    context_after=tuple(
                        lines[idx + 1:idx + 1 + context_lines],
                    ),
                ))
            if total_hits >= options.max_matches:
                budget_hit = True
                break
        if file_hits:
            result.files.append(resolved)
            result.counts[str(resolved)] = file_hits
        if budget_hit:
            result.truncated = True
            break

    return result
