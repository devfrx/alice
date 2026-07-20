"""AL\\CE — File system search with path validation."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from loguru import logger

from backend.core.path_safety import (
    is_forbidden,
    is_relative_to,
    is_unc_path,
    safe_resolve,
)


class ForbiddenPathError(ValueError):
    """Raised when a path is in a forbidden directory."""


def normalize_extensions(extensions: Iterable[str]) -> set[str]:
    """Normalize an extension whitelist to lowercase dotted suffixes.

    Single source shared by ``_sync_walk`` (search_files) and
    ``grep.run_grep`` — the third inline copy was consolidated here.

    Args:
        extensions: Raw suffixes, with or without the leading dot,
            in any case (e.g. ``["txt", ".PY"]``).

    Returns:
        A set of lowercase suffixes, each with a leading dot.
    """
    normalized: set[str] = set()
    for ext in extensions:
        e = ext.lower()
        normalized.add(e if e.startswith(".") else f".{e}")
    return normalized


def _validate_path(
    path: str | Path,
    allowed_roots: list[Path],
    forbidden: list[Path],
    follow_symlinks: bool,
) -> Path:
    """Resolve and validate a filesystem path against security constraints.

    Checks that the path is not a UNC path, is not inside any forbidden
    directory, and falls within at least one allowed root.

    Args:
        path: The raw path string or Path object to validate.
        allowed_roots: Directories the user is permitted to access.
        forbidden: Directories that are always blocked.
        follow_symlinks: Whether to resolve symlinks before checking.

    Returns:
        The resolved, validated ``Path``.

    Raises:
        ValueError: If the path violates any security constraint.
    """
    raw = str(path)

    # Block UNC paths (network shares)
    if is_unc_path(raw):
        raise ValueError(f"UNC paths are not allowed: {raw}")

    p = Path(raw)
    resolved = safe_resolve(p)
    if resolved is None:
        raise ValueError(f"Invalid path: {raw}")

    # When symlinks should not be followed, reject symlinks.
    # Wrap is_symlink() to handle TypeError from Python 3.13 pathlib when
    # lstat().st_mode is unavailable (mocked path or non-existent file).
    if not follow_symlinks:
        try:
            is_symlink = p.is_symlink()
        except (OSError, TypeError):
            is_symlink = False
        if is_symlink:
            raise ValueError(f"Symlinks not allowed: {raw}")

    # Block forbidden directories (checked BEFORE containment)
    for fb in forbidden:
        fb_resolved = fb.resolve()
        if is_relative_to(resolved, fb_resolved):
            raise ForbiddenPathError(
                f"Path is inside forbidden directory {fb_resolved}: {resolved}"
            )

    # Must be inside at least one allowed root
    inside_allowed = False
    for root in allowed_roots:
        if is_relative_to(resolved, root.resolve()):
            inside_allowed = True
            break

    if not inside_allowed:
        raise ValueError(
            f"Path is outside all allowed directories: {resolved}"
        )

    return resolved


def _sync_walk(
    query: str,
    roots: list[Path],
    extensions: list[str] | None,
    max_results: int,
    forbidden: list[Path],
    follow_symlinks: bool,
) -> list[dict]:
    """Walk directories synchronously, matching files by name.

    Args:
        query: Case-insensitive substring to match in filenames.
        roots: Root directories to search.
        extensions: Optional extension filter (e.g. [".txt", ".py"]).
        max_results: Maximum number of results to return.
        forbidden: Directories to skip entirely.
        follow_symlinks: Whether os.walk should follow symlinks.

    Returns:
        A list of file-info dicts.
    """
    query_lower = query.lower()
    forbidden_resolved = [fb.resolve() for fb in forbidden]
    results: list[dict] = []

    # Normalize extensions to lowercase with leading dot
    ext_filter: set[str] | None = None
    if extensions:
        ext_filter = normalize_extensions(extensions)

    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(
            root, followlinks=follow_symlinks
        ):
            current = Path(dirpath).resolve()

            # Skip forbidden directories
            if is_forbidden(current, forbidden_resolved):
                dirnames.clear()
                continue

            # Prune forbidden from subdirectories. The join is resolved at
            # the call site (is_forbidden compares already-resolved paths):
            # this is what catches a symlink pointing into a forbidden tree.
            dirnames[:] = [
                d for d in dirnames
                if not is_forbidden((current / d).resolve(), forbidden_resolved)
            ]

            for filename in filenames:
                if query_lower not in filename.lower():
                    continue

                if ext_filter:
                    file_ext = Path(filename).suffix.lower()
                    if file_ext not in ext_filter:
                        continue

                filepath = current / filename
                try:
                    stat = filepath.stat()
                    modified_dt = datetime.fromtimestamp(
                        stat.st_mtime, tz=UTC
                    )
                    results.append({
                        "path": str(filepath),
                        "name": filename,
                        "size_bytes": stat.st_size,
                        "modified_iso": modified_dt.isoformat(),
                        "extension": Path(filename).suffix,
                    })
                except PermissionError:
                    logger.warning(
                        "Permission denied reading file: {}", filepath
                    )
                    continue
                except OSError as exc:
                    logger.warning(
                        "OS error reading file {}: {}", filepath, exc
                    )
                    continue

                if len(results) >= max_results:
                    return results

    return results


class GlobOutcome(NamedTuple):
    """Result of :func:`run_glob`.

    Attributes:
        matches: Resolved absolute file paths, newest-first, at most
            ``max_results`` of them.
        truncated: ``True`` when the result set was cut short for any
            reason (early-break, slice-cut or caller-side timeout).
        partial: ``True`` when the enumeration itself stopped early
            (cap or timeout): newest-first then holds only over the
            files examined, NOT over the whole tree.
    """

    matches: list[Path]
    truncated: bool
    partial: bool


def _finalize_glob(
    stamped: list[tuple[int, Path]], max_results: int,
) -> tuple[list[Path], bool]:
    """Sort ``(mtime_ns, path)`` stamps newest-first and cut to *max_results*.

    Args:
        stamped: Collected ``(st_mtime_ns, resolved_path)`` tuples.
        max_results: Maximum number of paths to keep.

    Returns:
        A ``(matches, slice_cut)`` tuple: the newest *max_results* paths
        and whether anything was dropped by the cut.
    """
    ordered = sorted(stamped, key=lambda t: t[0], reverse=True)
    return [p for _, p in ordered[:max_results]], len(ordered) > max_results


def run_glob(
    root: Path,
    pattern: str,
    *,
    max_results: int,
    forbidden: list[Path] | tuple[Path, ...],
    follow_symlinks: bool,
    sink: list[tuple[int, Path]] | None = None,
) -> GlobOutcome:
    """Glob under *root*, newest-first, bounded.

    Runs ``Path.glob`` with the given pattern (real ``**`` recursion is
    supported), keeping only regular files that resolve inside *root*
    and outside every forbidden directory.  Collection stops early once
    ``max_results * 4`` candidates have been gathered; survivors are
    sorted by modification time (newest first) and cut to
    ``max_results``.

    Truncation honesty: when the early-break cap fires (``partial`` is
    ``True``), the enumeration is INCOMPLETE — newest-first then holds
    only among the files examined in ``Path.glob`` traversal order, not
    over the whole tree.  When only the final slice-cut fires, the
    ordering is complete and merely shortened.

    Bound caveat: the cap bounds how many MATCHES are collected, not
    the walk itself — pathlib offers no pruning hook, so ``**`` still
    descends into forbidden subtrees (their files are only filtered out
    afterwards) and into match-free trees.  Unlike ``_sync_walk``,
    which prunes forbidden directories during traversal, the real bound
    on walk time here is the caller's timeout; passing *sink* lets the
    caller salvage what was collected when it abandons the call.

    Symlink behaviour: when *follow_symlinks* is ``False``, symlinked
    files are skipped; ``Path.glob`` itself never recurses into
    symlinked directories when expanding ``**``, and a candidate whose
    resolution escapes *root* (e.g. via a symlinked path component or a
    ``..`` in the pattern) is dropped by the containment check either
    way.

    Args:
        root: Already-validated root directory to glob under.
        pattern: Glob pattern relative to *root* (e.g. ``**/*.py``).
            Absolute or drive/root-anchored patterns are rejected.
        max_results: Maximum number of paths to return (>= 1).
        forbidden: Directories that are always blocked.
        follow_symlinks: Whether symlinked files may appear in results.
        sink: Optional shared accumulator for ``(mtime_ns, path)``
            stamps, filled in place during the walk so a caller that
            times out can still read the partial harvest.

    Returns:
        A :class:`GlobOutcome` ``(matches, truncated, partial)``.

    Raises:
        ValueError: If *pattern* is absolute or root-anchored.
    """
    if Path(pattern).anchor:
        raise ValueError(
            "Il pattern deve essere relativo alla root: indica la "
            "directory di partenza con 'path' e usa un pattern come "
            "'**/*.py'."
        )

    root_resolved = root.resolve()
    forbidden_resolved = [fb.resolve() for fb in forbidden]
    stamped: list[tuple[int, Path]] = sink if sink is not None else []
    partial = False

    for candidate in root_resolved.glob(pattern):
        try:
            if not candidate.is_file():
                continue
            if not follow_symlinks and candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if not is_relative_to(resolved, root_resolved):
                continue
            if is_forbidden(resolved, forbidden_resolved):
                continue
            stamped.append((resolved.stat().st_mtime_ns, resolved))
        except OSError as exc:
            logger.warning("glob: skipping {}: {}", candidate, exc)
            continue
        if len(stamped) >= max_results * 4:
            # Enough extras collected: stop enumerating (incomplete!).
            partial = True
            break

    matches, slice_cut = _finalize_glob(stamped, max_results)
    return GlobOutcome(matches, partial or slice_cut, partial)


async def search_files(
    query: str,
    roots: list[Path],
    extensions: list[str] | None,
    max_results: int,
    forbidden: list[Path],
    follow_symlinks: bool,
) -> list[dict]:
    """Search for files matching *query* across the given roots.

    Runs the synchronous directory walk in a thread pool with a 5-second
    timeout to prevent blocking the event loop on deep hierarchies.

    Args:
        query: Case-insensitive substring to match in filenames.
        roots: Root directories to search.
        extensions: Optional extension filter (e.g. [".txt", ".py"]).
        max_results: Maximum number of results to return.
        forbidden: Directories to skip entirely.
        follow_symlinks: Whether to follow symlinks during the walk.

    Returns:
        A list of file-info dicts with path, name, size, modified date
        and extension.
    """
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(
                _sync_walk, query, roots, extensions,
                max_results, forbidden, follow_symlinks,
            ),
            timeout=60.0,
        )
    except TimeoutError:
        logger.warning("File search timed out after 60 seconds")
        results = []

    return results
