"""Unit tests for the bounded pure-Python content grep (Fase 2)."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from backend.plugins.file_search.grep import GrepOptions, GrepResult, run_grep

_WalkTriple = tuple[str, list[str], list[str]]


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


def test_grep_walk_streams_and_fills_sink_incrementally(tmp_path: Path) -> None:
    """The walk is streaming (os.walk), NOT a materialized rglob: matches
    from a directory are already in the sink BEFORE the next directory
    tuple is pulled from the walk (salvage-on-timeout depends on this)."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("hit\n")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "y.txt").write_text("hit\n")

    sink = GrepResult()
    observed: list[int] = []
    real_walk = os.walk

    def spy_walk(top: Any, **kwargs: Any) -> Iterator[_WalkTriple]:
        for triple in real_walk(top, **kwargs):
            yield triple
            observed.append(len(sink.files))

    with patch("backend.plugins.file_search.grep.os.walk", new=spy_walk):
        run_grep(tmp_path, GrepOptions(pattern=r"hit"), sink=sink)

    # After each directory tuple was consumed its matches were already
    # harvested: root (no files), then a/ (1), then b/ (2).
    assert observed == [0, 1, 2]


def test_grep_forbidden_dir_pruned_from_walk(tmp_path: Path) -> None:
    """A forbidden directory is pruned from the walk itself (in-place
    dirnames edit, like _sync_walk): os.walk never descends into it."""
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "s.txt").write_text("foo\n")
    (tmp_path / "ok.txt").write_text("foo\n")

    visited: list[str] = []
    real_walk = os.walk

    def spy_walk(top: Any, **kwargs: Any) -> Iterator[_WalkTriple]:
        for dirpath, dirnames, filenames in real_walk(top, **kwargs):
            visited.append(str(dirpath))
            yield dirpath, dirnames, filenames

    with patch("backend.plugins.file_search.grep.os.walk", new=spy_walk):
        result = run_grep(tmp_path, GrepOptions(pattern=r"foo"),
                          forbidden=(secret.resolve(),))

    assert [p.name for p in result.files] == ["ok.txt"]
    assert visited  # the scan really went through os.walk
    assert all("secret" not in v for v in visited)


def test_grep_long_lines_capped_before_matching(tmp_path: Path) -> None:
    """Lines over max_line_chars are truncated BEFORE matching (regex-cost
    bound): a match entirely beyond the cap is lost and counted."""
    (tmp_path / "min.js").write_text("x" * 300 + "needle\nshort needle\n")

    result = run_grep(
        tmp_path,
        GrepOptions(pattern=r"needle", output_mode="content", max_line_chars=100),
    )

    [match] = result.matches  # capped line 1 no longer matches
    assert match.line_number == 2
    assert result.lines_capped == 1


def test_grep_emitted_lines_capped(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("needle" + "x" * 300 + "\n")

    result = run_grep(
        tmp_path,
        GrepOptions(pattern=r"needle", output_mode="content", max_line_chars=50),
    )

    [match] = result.matches
    assert len(match.line) == 50
    assert result.lines_capped == 1


def test_grep_max_file_bytes_config_driven(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("foo " * 100)
    result = run_grep(tmp_path, GrepOptions(pattern=r"foo", max_file_bytes=10))
    assert result.files == []
    assert result.files_scanned == 0


def test_grep_budget_is_global_in_files_mode(tmp_path: Path) -> None:
    """Pin: max_matches is a GLOBAL budget, not per-file — N files with one
    hit each and max_matches < N stop the scan at max_matches files."""
    for i in range(6):
        (tmp_path / f"f{i}.txt").write_text("hit\n")

    result = run_grep(tmp_path, GrepOptions(pattern=r"hit", max_matches=4))

    assert result.truncated
    assert len(result.files) == 4


def test_grep_count_mode_partial_file_lower_bound(tmp_path: Path) -> None:
    """Pin: when the budget fires mid-file the count of that file is a
    lower bound and the file is flagged via partial_file."""
    target = tmp_path / "a.txt"
    target.write_text("hit\nhit\nhit\n")

    result = run_grep(
        tmp_path, GrepOptions(pattern=r"hit", output_mode="count", max_matches=2))

    assert result.truncated
    assert result.counts == {str(target.resolve()): 2}
    assert result.partial_file == str(target.resolve())


def test_grep_extensions_without_dot_case_insensitive(tmp_path: Path) -> None:
    """Pin the shared extension normalization: no dot + wrong case still
    filters correctly (single source with search_files)."""
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"here", extensions=("TXT",)))
    assert [p.name for p in result.files] == ["c.txt"]
