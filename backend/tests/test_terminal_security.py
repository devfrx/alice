"""AL\\CE — Tests for the terminal plugin security primitives (Fase 6d).

Pure unit tests: they use ``tmp_path`` only and never spawn a subprocess.  They
exercise the three primitives adversarially — ``..`` traversal, symlink escape,
UNC/device paths, forbidden-root precedence, id-driven traversal and shell
metacharacters — because these functions are the entire security boundary for
the scoped terminal.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.plugins.terminal.security import (
    build_argv,
    ensure_sandbox,
    validate_cwd_within_scope,
)

# ---------------------------------------------------------------------------
# validate_cwd_within_scope
# ---------------------------------------------------------------------------


def test_cwd_in_scope_subdir_returns_resolved(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    sub = ws / "sub"
    sub.mkdir()

    result = validate_cwd_within_scope(str(sub), [ws.resolve()])

    assert result == sub.resolve()


def test_cwd_scope_root_itself_is_allowed(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    result = validate_cwd_within_scope(str(ws), [ws.resolve()])

    assert result == ws.resolve()


def test_cwd_out_of_scope_sibling_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ValueError, match="outside the workspace scope"):
        validate_cwd_within_scope(str(other), [ws.resolve()])


def test_cwd_dotdot_traversal_escapes_scope(tmp_path: Path) -> None:
    """``..`` climbing out of the scope is caught by resolve-first containment."""
    ws = tmp_path / "ws"
    ws.mkdir()
    sub = ws / "sub"
    sub.mkdir()
    other = tmp_path / "other"
    other.mkdir()  # exists + is a dir, so only the containment check can fail

    sneaky = str(sub / ".." / ".." / "other")  # resolves to tmp_path/other

    with pytest.raises(ValueError, match="outside the workspace scope"):
        validate_cwd_within_scope(sneaky, [ws.resolve()])


def test_cwd_symlink_escape_rejected(tmp_path: Path) -> None:
    """A symlink inside the scope pointing outside it must be rejected.

    ``resolve()`` follows the link, so the resolved target lands outside ``ws``
    and fails containment.  Skipped where the OS forbids symlink creation
    (Windows without privilege / developer mode) so the suite stays portable.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    link = ws / "link"
    try:
        os.symlink(other, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform gate
        pytest.skip(f"symlink not permitted on this platform: {exc}")

    with pytest.raises(ValueError, match="outside the workspace scope"):
        validate_cwd_within_scope(str(link), [ws.resolve()])


def test_cwd_unc_path_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    with pytest.raises(ValueError, match="UNC"):
        validate_cwd_within_scope(r"\\server\share", [ws.resolve()])


def test_cwd_device_path_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    with pytest.raises(ValueError, match="UNC"):
        validate_cwd_within_scope(r"\\.\C:", [ws.resolve()])


def test_cwd_forward_slash_unc_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    with pytest.raises(ValueError, match="UNC"):
        validate_cwd_within_scope("//server/share", [ws.resolve()])


def test_cwd_nonexistent_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    missing = ws / "does_not_exist"

    with pytest.raises(ValueError, match="does not exist"):
        validate_cwd_within_scope(str(missing), [ws.resolve()])


def test_cwd_existing_file_not_dir_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    file_in_scope = ws / "file.txt"
    file_in_scope.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="Not a directory"):
        validate_cwd_within_scope(str(file_in_scope), [ws.resolve()])


def test_cwd_forbidden_path_takes_precedence_over_scope(tmp_path: Path) -> None:
    """A forbidden subtree is rejected even though it is inside the scope."""
    ws = tmp_path / "ws"
    ws.mkdir()
    secret = ws / "secret"
    secret.mkdir()
    inner = secret / "inner"
    inner.mkdir()

    with pytest.raises(ValueError, match="forbidden"):
        validate_cwd_within_scope(
            str(inner), [ws.resolve()], forbidden_paths=[str(secret)]
        )


def test_cwd_empty_or_blank_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    for bad in ("", "   ", "\t"):
        with pytest.raises(ValueError, match="Empty"):
            validate_cwd_within_scope(bad, [ws.resolve()])


def test_cwd_empty_scope_roots_rejects_any_existing_dir(tmp_path: Path) -> None:
    """With no scope roots, nothing is in-scope — even a perfectly valid dir."""
    anywhere = tmp_path / "anywhere"
    anywhere.mkdir()

    with pytest.raises(ValueError, match="outside the workspace scope"):
        validate_cwd_within_scope(str(anywhere), [])


# ---------------------------------------------------------------------------
# ensure_sandbox
# ---------------------------------------------------------------------------


def test_ensure_sandbox_creates_dir_under_root_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    cid = "123e4567-e89b-12d3-a456-426614174000"  # UUID-like

    first = ensure_sandbox(cid, root)

    assert first == (root / cid).resolve()
    assert first.parent == root.resolve()  # confined to the resolved root
    assert first.is_dir()

    # Second call must not raise and must return the same path (lazy/idempotent).
    second = ensure_sandbox(cid, root)
    assert second == first
    assert second.is_dir()


def test_ensure_sandbox_accepts_str_or_path_root(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    cid = "abc00000-0000-0000-0000-000000000abc"

    from_str = ensure_sandbox(cid, str(root))
    from_path = ensure_sandbox(cid, root)

    assert from_str == from_path == (root / cid).resolve()


@pytest.mark.parametrize("bad_id", ["../evil", "a/b", "a\\b", "C:evil", "..", "."])
def test_ensure_sandbox_rejects_traversal_ids(tmp_path: Path, bad_id: str) -> None:
    root = tmp_path / "workspaces"

    with pytest.raises(ValueError, match="Unsafe conversation id"):
        ensure_sandbox(bad_id, root)

    # Nothing must have been created outside the sandbox root.
    assert not (tmp_path / "evil").exists()


def test_ensure_sandbox_rejects_empty_id(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"

    for bad in ("", "   "):
        with pytest.raises(ValueError, match="Empty conversation id"):
            ensure_sandbox(bad, root)


def test_ensure_sandbox_rejects_control_char_id(tmp_path: Path) -> None:
    """Hardening beyond the spec: control chars (e.g. NUL) in an id are refused."""
    root = tmp_path / "workspaces"

    with pytest.raises(ValueError, match="Unsafe conversation id"):
        ensure_sandbox("a\x00b", root)


# ---------------------------------------------------------------------------
# build_argv
# ---------------------------------------------------------------------------


def test_build_argv_simple() -> None:
    assert build_argv("python script.py") == ["python", "script.py"]


def test_build_argv_quoted_message_keeps_quotes() -> None:
    """Documented contract: ``posix=False`` RETAINS the surrounding quotes.

    ``shlex.split('git commit -m "a message"', posix=False)`` yields four tokens
    where the message stays a single token *with* its double-quotes.
    """
    argv = build_argv('git commit -m "a message"')

    assert argv == ["git", "commit", "-m", '"a message"']
    assert len(argv) == 4


def test_build_argv_windows_path_keeps_backslashes() -> None:
    argv = build_argv(r"type C:\ws\file.txt")

    assert argv == ["type", r"C:\ws\file.txt"]


def test_build_argv_empty_or_blank_rejected() -> None:
    for bad in ("", "   ", "\t"):
        with pytest.raises(ValueError, match="Empty command"):
            build_argv(bad)


def test_build_argv_newline_rejected() -> None:
    with pytest.raises(ValueError, match="Control characters"):
        build_argv("echo \n rm")


def test_build_argv_carriage_return_rejected() -> None:
    with pytest.raises(ValueError, match="Control characters"):
        build_argv("echo \r x")


def test_build_argv_nul_rejected() -> None:
    with pytest.raises(ValueError, match="Control characters"):
        build_argv("echo \x00 x")


def test_build_argv_unbalanced_quotes_rejected() -> None:
    with pytest.raises(ValueError, match="Could not parse command"):
        build_argv('echo "unterminated')


def test_build_argv_metacharacters_stay_literal() -> None:
    """``>`` is a literal token, not interpreted (shell=False is the defense)."""
    argv = build_argv("echo a > b")

    assert argv == ["echo", "a", ">", "b"]
    assert ">" in argv  # present as a literal arg, NOT rejected, NOT interpreted


def test_build_argv_chaining_metacharacters_stay_literal() -> None:
    argv = build_argv("echo a ; rm")

    assert ";" in argv
    assert argv == ["echo", "a", ";", "rm"]
