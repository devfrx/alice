"""Bounded pure-Python content grep (spec Fase 2 §4.6 — no ripgrep binary).

Deliberate deviation from Claude Code: no external ripgrep binary (PyInstaller
bundling), a pure-Python scan with hard bounds instead.  The walk is a
STREAMING ``os.walk`` — per-directory ``sorted`` order (stable), forbidden
directories PRUNED in place before descent (mirroring
``searcher._sync_walk``), no upfront materialization of the tree — so the
shared :class:`GrepResult` fills incrementally and a caller that times out
can salvage whatever was already collected.

Bounds (all fail-open into ``truncated=True``, never an error):

* ``max_files`` — number of files actually content-scanned.
* ``max_matches`` — a GLOBAL budget of matching lines across the whole scan,
  in every output mode.  In ``content`` mode it coincides with the number of
  collected :class:`GrepMatch` entries; in ``files_with_matches``/``count``
  mode it caps the total hits counted, so the LAST file recorded may carry a
  partial (lower-bound) count, flagged via :attr:`GrepResult.partial_file`.
  Reaching the budget stops the scan.
* ``max_file_bytes`` — files over this size are skipped silently (the tool
  handler passes the ``max_file_size_read_bytes`` config, same cap as
  ``read_text_file``); binary files (NUL byte in the first 8 KiB) are
  skipped too.
* ``max_line_chars`` — every line is truncated to this many characters
  BEFORE matching (and in emitted match/context lines).  This bounds the
  common polynomial regex-backtracking cases (minified JS, one-line JSON);
  a match lying entirely beyond the cap is LOST —
  :attr:`GrepResult.lines_capped` counts the capped lines so the caller
  can say so honestly.

Residual risk (declared): an exponential-backtracking pattern can still pin
a core past the caller's timeout — the abandoned ``asyncio.to_thread``
worker (default executor) keeps running to the end of the scan and occupies
a pool thread meanwhile.  A dedicated, cancellable executor is censused as
a future refinement, deliberately not built here.

Matching semantics (parità decisione T9, divergenze da rg dichiarate):

* Line numbering uses ``text.split("\\n")`` (NOT ``splitlines``) for parity
  with ``read_text_file``'s numbering: a newline-terminated file therefore
  has a phantom final EMPTY line that CAN match patterns like ``^$``
  (ripgrep would not report it) — deliberate consequence of the T9 parity.
* Matching is strictly line-by-line: a pattern containing ``\\n`` never
  matches (multi-line patterns are not supported).
* The ``glob`` filter uses ``fnmatch`` on the file NAME, which is
  case-insensitive on Windows (``os.path.normcase``).
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from backend.core.path_safety import is_forbidden, is_relative_to
from backend.plugins.file_search.searcher import normalize_extensions

_BINARY_SNIFF_BYTES = 8192

OUTPUT_MODES: tuple[str, ...] = ("files_with_matches", "content", "count")


@dataclass(frozen=True, slots=True)
class GrepOptions:
    """Options for :func:`run_grep`.

    Attributes:
        pattern: Python regular expression matched per-line.
        glob: Optional ``fnmatch`` pattern applied to the file NAME
            (not the full path), e.g. ``*.py``; case-insensitive on
            Windows.
        extensions: Optional suffix whitelist (leading dot optional,
            case-insensitive), e.g. ``(".py", ".txt")``.
        output_mode: One of :data:`OUTPUT_MODES`.
        context_lines: Lines of context around each match
            (``content`` mode only).
        case_insensitive: Compile the regex with ``re.IGNORECASE``.
        max_files: Maximum number of files to content-scan.
        max_matches: Global budget of matching lines (see module docs).
        max_file_bytes: Skip files larger than this many bytes (the
            handler passes the ``max_file_size_read_bytes`` config).
        max_line_chars: Truncate each line to this many characters
            before matching and in emitted lines (regex-cost bound;
            the handler passes the ``max_line_chars`` config).
        follow_symlinks: Whether symlinked files/dirs may be scanned.
    """

    pattern: str
    glob: str | None = None
    extensions: tuple[str, ...] = ()
    output_mode: str = "files_with_matches"  # | "content" | "count"
    context_lines: int = 0
    case_insensitive: bool = False
    max_files: int = 5000
    max_matches: int = 200
    max_file_bytes: int = 1_048_576
    max_line_chars: int = 2000
    follow_symlinks: bool = False


@dataclass(frozen=True, slots=True)
class GrepMatch:
    """A single matching line (capped to ``max_line_chars``) with context."""

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
            (per-directory sorted walk) order.
        matches: Collected matches (``content`` mode only).
        counts: Per-file hit counts keyed by resolved path string
            (every mode).
        truncated: ``True`` when any bound fired (``max_files``,
            ``max_matches`` or a caller-side timeout).
        files_scanned: Number of files actually content-scanned.
        lines_capped: Number of lines truncated to ``max_line_chars``
            before matching — matches beyond the cap may be lost.
        partial_file: Resolved path (str) of the file inside which the
            ``max_matches`` budget fired with lines still unscanned:
            its ``counts`` entry is a lower bound.  Conservatively set
            even when only the phantom trailing empty line remained.
    """

    files: list[Path] = field(default_factory=list)
    matches: list[GrepMatch] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    files_scanned: int = 0
    lines_capped: int = 0
    partial_file: str | None = None


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
    """Scan file CONTENTS under *root* for a regex, streaming and bounded.

    Walks *root* with ``os.walk`` (per-directory sorted order); forbidden
    directories are pruned from ``dirnames`` in place, so the walk never
    descends into them.  A file is skipped when it is not a regular file,
    is a symlink while ``follow_symlinks`` is off, resolves outside *root*
    (symlink escape), sits under a forbidden directory, fails the
    ``glob``/``extensions`` filters, exceeds ``max_file_bytes`` or sniffs
    as binary.  Unreadable files (``OSError``) are skipped, never fatal.

    Bound semantics (declared, see module docstring): ``max_files``
    bounds the files content-scanned; ``max_matches`` is a single global
    budget of matching lines across the whole scan in EVERY output mode —
    when it fires the scan stops, ``truncated`` is set and, if lines were
    left unscanned in the current file, ``partial_file`` names it (its
    count is a lower bound).  ``truncated`` may be conservatively ``True``
    when the budget is reached exactly on the final match.  Lines longer
    than ``max_line_chars`` are matched on the truncated prefix only
    (``lines_capped`` counts them).

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
    ext_filter = normalize_extensions(options.extensions)
    context_lines = max(options.context_lines, 0)
    line_cap = max(options.max_line_chars, 1)
    result = sink if sink is not None else GrepResult()
    total_hits = 0
    stop = False

    for dirpath, dirnames, filenames in os.walk(
        root_resolved, followlinks=options.follow_symlinks,
    ):
        current = Path(dirpath).resolve()

        # Skip forbidden directories entirely and prune them from the
        # descent (in-place edit, same approach as _sync_walk); the
        # join is resolved so a symlink into a forbidden tree is caught.
        if is_forbidden(current, forbidden_resolved):
            dirnames.clear()
            continue
        dirnames[:] = sorted(
            d for d in dirnames
            if not is_forbidden((current / d).resolve(), forbidden_resolved)
        )

        for filename in sorted(filenames):
            candidate = current / filename
            try:
                if not candidate.is_file():
                    continue
                if result.files_scanned >= options.max_files:
                    # Another file was up next: enumeration incomplete.
                    result.truncated = True
                    stop = True
                    break
                if not options.follow_symlinks and candidate.is_symlink():
                    continue
                resolved = candidate.resolve()
                if not is_relative_to(resolved, root_resolved):
                    continue
                if is_forbidden(resolved, forbidden_resolved):
                    continue
                if options.glob and not fnmatch.fnmatch(
                    candidate.name, options.glob,
                ):
                    continue
                if ext_filter and candidate.suffix.lower() not in ext_filter:
                    continue
                if (
                    resolved.stat().st_size > options.max_file_bytes
                    or _is_binary(resolved)
                ):
                    continue
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("grep: skipping {}: {}", candidate, exc)
                continue

            result.files_scanned += 1
            lines = text.split("\n")
            file_hits = 0
            budget_hit = False
            last_idx = -1
            for idx, line in enumerate(lines):
                if len(line) > line_cap:
                    result.lines_capped += 1
                    line = line[:line_cap]
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
                        context_before=tuple(
                            ln[:line_cap] for ln in lines[lo:idx]
                        ),
                        context_after=tuple(
                            ln[:line_cap]
                            for ln in lines[idx + 1:idx + 1 + context_lines]
                        ),
                    ))
                if total_hits >= options.max_matches:
                    budget_hit = True
                    last_idx = idx
                    break
            if file_hits:
                result.files.append(resolved)
                result.counts[str(resolved)] = file_hits
            if budget_hit:
                result.truncated = True
                if last_idx + 1 < len(lines):
                    result.partial_file = str(resolved)
                stop = True
                break
        if stop:
            break

    return result
