"""AL\\CE — Single implementation of filesystem path-safety primitives.

Consolidates the deliberate replicas that lived in ``file_search/searcher.py``,
``terminal/security.py``, ``permission_service.py``,
``pc_automation/security.py`` and ``scope_service`` (censused debt, saldato in
Fase 2).  Semantics are IDENTICAL to the replicas: resolve-first,
forbidden-before-containment, no I/O beyond ``Path.resolve``.

Contract: :func:`within_any_root` and :func:`is_forbidden` compare paths the
CALLER has already resolved (via :func:`safe_resolve`) — they perform no
filesystem access themselves.  This mirrors every replica, where
``Path.resolve()`` is always called *before* any containment or forbidden
comparison so that ``..`` traversal and symlinks/junctions surface as a
resolved path the checks can judge.

Note: some replicas (terminal, pc_automation) additionally refuse a *single*
leading backslash because their normalisation could degrade it into a UNC
path.  That stricter check is a caller-side concern and deliberately NOT part
of :func:`is_unc_path` (which pins the shared ``\\\\`` / ``//`` rejection).

Migration note (Task 7): ``file_search/searcher.py::_is_relative_to`` resolves
INTERNALLY (``path.resolve().relative_to(parent)``) while this module's
:func:`is_relative_to` does not — the file_search call sites must add the
``.resolve()`` themselves when migrating (it is what catches a symlink into a
forbidden tree), otherwise the check degrades to a purely lexical one.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "is_forbidden",
    "is_relative_to",
    "is_unc_path",
    "safe_resolve",
    "within_any_root",
]


def is_unc_path(raw: str) -> bool:
    """Return ``True`` for Windows UNC/device paths (``\\\\server`` or ``//server``).

    Covers network shares (``\\\\server\\share``), Win32 device paths
    (``\\\\.\\device``) and forward-slash UNC (``//server/share``).

    Args:
        raw: The raw, unresolved path string (untrusted input).

    Returns:
        ``True`` when the string starts with a UNC/device prefix.
    """
    return raw.startswith(("\\\\", "//"))


def safe_resolve(raw: str | Path) -> Path | None:
    """``Path.resolve()`` that returns ``None`` instead of raising.

    Best-effort absolute resolution (``strict=False`` semantics): a
    non-existent path still resolves lexically (collapsing ``..``); an
    *invalid* path (e.g. an embedded NUL) yields ``None``.

    Fail-closed rule for callers: ``None`` must be treated as
    out-of-scope/forbidden (deny), and ``None`` entries must be filtered out
    BEFORE building root/forbidden lists — the containment helpers take
    ``Path``, never ``None``.  Migration warning (Task 7): the replica
    ``permission_service._safe_resolve`` never returns ``None`` (it lets
    ``resolve`` raise), so a mechanical swap without the ``None`` handling
    would feed ``None`` into :func:`is_relative_to` → ``TypeError``.

    Args:
        raw: The raw path string or ``Path`` to resolve.

    Returns:
        The resolved absolute ``Path``, or ``None`` when the input is not a
        valid path on this platform.
    """
    try:
        return Path(raw).resolve()
    except (OSError, ValueError):
        return None


def is_relative_to(child: Path, parent: Path) -> bool:
    """Containment check on already-resolved paths (no filesystem access).

    Answers "is *child* equal to, or nested inside, *parent*?" and swallows
    the :class:`ValueError` that :meth:`pathlib.PurePath.relative_to` raises
    when it is not.  Purely lexical: a sibling sharing a name prefix
    (``C:\\Windows2`` vs ``C:\\Windows``) is NOT contained, and different
    drives never contain each other.

    Args:
        child: The already-resolved candidate path.
        parent: The already-resolved root to test containment against.

    Returns:
        ``True`` when *child* is *parent* itself or a descendant of it.
    """
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def within_any_root(target: Path, roots: list[Path] | tuple[Path, ...]) -> bool:
    """Return ``True`` if the resolved target sits under at least one resolved root.

    Both *target* and every entry of *roots* must already be resolved by the
    caller.  An empty *roots* means nothing is in-scope: always ``False``.

    Args:
        target: The already-resolved candidate path.
        roots: The already-resolved allowed roots.

    Returns:
        ``True`` when *target* is at or under at least one root.
    """
    return any(is_relative_to(target, root) for root in roots)


def is_forbidden(target: Path, forbidden: list[Path] | tuple[Path, ...]) -> bool:
    """Return ``True`` if the target is one of, or sits under, a forbidden directory.

    Both *target* and every entry of *forbidden* must already be resolved by
    the caller.  Callers check this BEFORE containment, so a forbidden subtree
    is refused even when it is technically inside an allowed root (pinned
    replica behaviour).

    Args:
        target: The already-resolved candidate path.
        forbidden: The already-resolved directories that are always blocked.

    Returns:
        ``True`` when *target* matches or descends from a forbidden directory.
    """
    # The exact-match case is already covered: is_relative_to(f, f) is True
    # (relative_to succeeds on itself, same case-normalisation), so a separate
    # ``target == f`` check would be redundant.
    return any(is_relative_to(target, f) for f in forbidden)
