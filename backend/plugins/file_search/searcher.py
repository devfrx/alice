"""AL\\CE — File system search with path validation."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from backend.core.path_safety import (
    is_forbidden,
    is_relative_to,
    is_unc_path,
    safe_resolve,
)


class ForbiddenPathError(ValueError):
    """Raised when a path is in a forbidden directory."""


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
        ext_filter = set()
        for ext in extensions:
            e = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            ext_filter.add(e)

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
