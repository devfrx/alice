"""AL\\CE — Pins for the single path-safety module (Fase 2, Blocco B).

These tests port the edge cases already covered by the suites of the four
deliberate replicas (``file_search/searcher.py``, ``terminal/security.py``,
``permission_service.py``, ``pc_automation/security.py``) so that the unified
``backend.core.path_safety`` module keeps IDENTICAL semantics when Task 7
migrates the consumers onto it.

Contract reminder (mirrors the replicas): ``within_any_root`` and
``is_forbidden`` compare paths that the CALLER has already resolved — they do
no filesystem access themselves.  Fixtures therefore call ``.resolve()``
explicitly (pytest's ``tmp_path`` on Windows can go through an 8.3 shortname).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.core.path_safety import (
    is_forbidden,
    is_relative_to,
    is_unc_path,
    safe_resolve,
    within_any_root,
)

# ---------------------------------------------------------------------------
# is_unc_path — pinned from file_search (UNC), terminal (device / forward-slash
# UNC) and pc_automation (same rejection set).
# ---------------------------------------------------------------------------


def test_unc_paths_rejected() -> None:
    assert is_unc_path(r"\\server\share")
    assert is_unc_path(r"\\server\share\file.txt")
    assert is_unc_path("//server/share")
    assert not is_unc_path(r"C:\Users\x")
    assert not is_unc_path("relative/path")


def test_device_path_is_unc() -> None:
    """Win32 device paths (``\\\\.\\C:``) start with ``\\\\`` — flagged too."""
    assert is_unc_path(r"\\.\C:")


def test_single_leading_backslash_is_not_unc() -> None:
    """A single leading ``\\`` is drive-relative, not UNC.

    terminal/security.py and pc_automation additionally refuse it because
    their normalisation could degrade it into a UNC path — that STRICTER
    check stays a caller-side concern (Task 7), not part of ``is_unc_path``.
    """
    assert not is_unc_path("\\folder")


# ---------------------------------------------------------------------------
# safe_resolve — pinned from permission_service._safe_resolve (best-effort
# strict=False) plus the None-on-invalid contract of this module.
# ---------------------------------------------------------------------------


def test_safe_resolve_normalises_dotdot(tmp_path: Path) -> None:
    child = tmp_path / "a" / ".." / "b"
    assert safe_resolve(str(child)) == (tmp_path / "b").resolve()


def test_safe_resolve_accepts_path_objects(tmp_path: Path) -> None:
    assert safe_resolve(tmp_path) == tmp_path.resolve()


def test_safe_resolve_nonexistent_path_still_resolves(tmp_path: Path) -> None:
    """strict=False semantics: a missing path resolves lexically, no raise."""
    missing = tmp_path / "does_not_exist" / "f.txt"
    resolved = safe_resolve(missing)
    assert resolved is not None
    assert resolved.is_absolute()


def test_safe_resolve_invalid_path_returns_none() -> None:
    """A resolve failure yields ``None``, never a raise.

    On Python 3.13 ``Path.resolve()`` swallows most bad inputs itself (an
    embedded NUL no longer raises), so the OSError/ValueError branch is pinned
    by patching — same technique the file_search suite uses.
    """
    with patch.object(Path, "resolve", side_effect=OSError("invalid path")):
        assert safe_resolve("whatever") is None
    with patch.object(Path, "resolve", side_effect=ValueError("embedded null")):
        assert safe_resolve("whatever") is None


# ---------------------------------------------------------------------------
# is_relative_to — pinned from terminal._is_relative_to (equal-or-descendant),
# permission_service._is_relative_to (never raises) and the SYSTEM_DIRS
# prefix-sibling case in pc_automation.validate_path.
# ---------------------------------------------------------------------------


def test_is_relative_to_root_itself() -> None:
    """The root IS contained in itself (terminal: scope root cwd is allowed)."""
    root = Path(r"C:\ws")
    assert is_relative_to(root, root)


def test_is_relative_to_descendant() -> None:
    assert is_relative_to(Path(r"C:\ws\sub\deep"), Path(r"C:\ws"))


def test_is_relative_to_sibling_rejected() -> None:
    assert not is_relative_to(Path(r"C:\other"), Path(r"C:\ws"))


def test_is_relative_to_parent_not_contained() -> None:
    assert not is_relative_to(Path(r"C:\ws"), Path(r"C:\ws\sub"))


def test_is_relative_to_common_prefix_sibling() -> None:
    """``C:\\Windows2`` is NOT under ``C:\\Windows`` (no naive startswith)."""
    assert not is_relative_to(Path(r"C:\Windows2"), Path(r"C:\Windows"))
    assert not is_relative_to(Path(r"C:\Windows2\file.txt"), Path(r"C:\Windows"))


def test_is_relative_to_cross_drive() -> None:
    assert not is_relative_to(Path(r"D:\x"), Path(r"C:\x"))


# ---------------------------------------------------------------------------
# within_any_root — pinned from file_search (at least one allowed root),
# permission_service._within_scope and terminal (empty scope ⇒ nothing is
# in-scope).  Resolve-first is the caller's job; fixtures resolve explicitly.
# ---------------------------------------------------------------------------


def test_within_any_root(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    inside = base / "sub" / "f.txt"
    assert within_any_root(inside, [base])
    assert not within_any_root(base.parent, [base])


def test_within_any_root_matches_second_root(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    target = base / "b" / "f.txt"
    assert within_any_root(target, [base / "a", base / "b"])


def test_within_any_root_root_itself(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    assert within_any_root(base, [base])


def test_within_any_root_empty_roots_is_false(tmp_path: Path) -> None:
    """No roots ⇒ nothing is in-scope (terminal: empty scope rejects all)."""
    assert not within_any_root(tmp_path.resolve(), [])


def test_within_any_root_resolved_traversal_escapes(tmp_path: Path) -> None:
    """Resolve-first pin: a ``..`` climb resolved by the caller lands outside."""
    base = tmp_path.resolve()
    inside = base / "inside"
    escaped = safe_resolve(inside / ".." / "outside" / "f.txt")
    assert escaped is not None
    assert not within_any_root(escaped, [inside])


def test_within_any_root_accepts_tuple(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    assert within_any_root(base / "f.txt", (base,))


# ---------------------------------------------------------------------------
# is_forbidden — pinned from file_search (forbidden dir blocks exact match and
# descendants) and terminal (forbidden checked before containment; a sibling
# sharing a name prefix must NOT match).
# ---------------------------------------------------------------------------


def test_forbidden_exact_descendant_and_sibling(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    forbidden = (base / "secret",)
    assert is_forbidden(base / "secret", forbidden)
    assert is_forbidden(base / "secret" / "deep" / "f.txt", forbidden)
    assert not is_forbidden(base / "secret2", forbidden)
    assert not is_forbidden(base / "other", forbidden)


def test_forbidden_windows_system_dirs() -> None:
    """The classic file_search / pc_automation pins on real system roots."""
    forbidden = (Path(r"C:\Windows"), Path(r"C:\Program Files"))
    assert is_forbidden(Path(r"C:\Windows\System32\cmd.exe"), forbidden)
    assert is_forbidden(Path(r"C:\Program Files\app\test.exe"), forbidden)
    assert not is_forbidden(Path(r"C:\Users\x\doc.txt"), forbidden)


def test_forbidden_empty_list_blocks_nothing(tmp_path: Path) -> None:
    assert not is_forbidden(tmp_path.resolve(), ())
    assert not is_forbidden(tmp_path.resolve(), [])
