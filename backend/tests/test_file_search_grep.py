"""Unit tests for the bounded pure-Python content grep (Fase 2)."""

from pathlib import Path

import pytest

from backend.plugins.file_search.grep import GrepOptions, run_grep


def _tree(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 42\n")
    (tmp_path / "b.py").write_text("x = 'foo bar'\n")
    (tmp_path / "c.txt").write_text("nothing here\n")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01binary")


def test_grep_files_with_matches(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"foo"))
    assert sorted(p.name for p in result.files) == ["a.py", "b.py"]
    assert not result.truncated


def test_grep_content_mode_with_context(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(
        tmp_path,
        GrepOptions(pattern=r"return", output_mode="content", context_lines=1))
    [match] = result.matches
    assert match.path.name == "a.py" and match.line_number == 2
    assert "def foo()" in match.context_before[0]


def test_grep_glob_filter(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"foo", glob="*.txt"))
    assert result.files == []


def test_grep_extensions_filter(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"here", extensions=(".txt",)))
    assert [p.name for p in result.files] == ["c.txt"]


def test_grep_skips_binaries(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"binary"))
    assert result.files == []


def test_grep_case_insensitive(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"FOO", case_insensitive=True))
    assert len(result.files) == 2


def test_grep_count_mode(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"foo", output_mode="count"))
    assert sum(result.counts.values()) == 2


def test_grep_bounded_matches(tmp_path: Path) -> None:
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text("hit\n")
    result = run_grep(tmp_path, GrepOptions(pattern=r"hit", max_matches=5))
    assert result.truncated


def test_grep_bounded_files(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x\n")
    result = run_grep(tmp_path, GrepOptions(pattern=r"zzz", max_files=3))
    assert result.truncated and result.files_scanned == 3


def test_grep_forbidden_skipped(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "s.txt").write_text("foo\n")
    result = run_grep(tmp_path, GrepOptions(pattern=r"foo"),
                      forbidden=(secret.resolve(),))
    assert result.files == []


def test_grep_invalid_regex_is_clean_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="regex"):
        run_grep(tmp_path, GrepOptions(pattern=r"foo["))
