"""O.M.N.I.A. — File system search with path validation."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger


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
    if raw.startswith("\\\\"):
        raise ValueError(f"UNC paths are not allowed: {raw}")

    p = Path(raw)
    resolved = p.resolve()

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

    # Block forbidden directories
    for fb in forbidden:
        fb_resolved = fb.resolve()
        try:
            resolved.relative_to(fb_resolved)
            raise ForbiddenPathError(
                f"Path is inside forbidden directory {fb_resolved}: {resolved}"
            )
        except ValueError as exc:
            if isinstance(exc, ForbiddenPathError):
                raise
            # relative_to failed → path is not inside forbidden dir
            continue

    # Must be inside at least one allowed root
    inside_allowed = False
    for root in allowed_roots:
        root_resolved = root.resolve()
        try:
            resolved.relative_to(root_resolved)
            inside_allowed = True
            break
        except ValueError:
            continue

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
    forbidden_resolved = {fb.resolve() for fb in forbidden}
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
            skip = False
            for fb in forbidden_resolved:
                try:
                    current.relative_to(fb)
                    skip = True
                    break
                except ValueError:
                    continue
            if skip:
                dirnames.clear()
                continue

            # Prune forbidden from subdirectories
            dirnames[:] = [
                d for d in dirnames
                if not any(
                    _is_relative_to(current / d, fb)
                    for fb in forbidden_resolved
                )
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
                        stat.st_mtime, tz=timezone.utc
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


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Check if *path* is relative to *parent* (compat helper).

    Args:
        path: The path to test.
        parent: The potential parent directory.

    Returns:
        True if *path* is inside *parent*.
    """
    try:
        path.resolve().relative_to(parent)
        return True
    except ValueError:
        return False


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
    except asyncio.TimeoutError:
        logger.warning("File search timed out after 60 seconds")
        results = []

    return results
