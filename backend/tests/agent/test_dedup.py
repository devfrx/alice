"""Dedup cross-step: stessa call → duplicata; path Windows normalizzati."""

from backend.services.agent.dedup import DedupRegistry
from backend.services.agent.models import ToolInvocation


def _call(name: str, args: dict) -> ToolInvocation:
    return ToolInvocation(call_id="x", name=name, args=args, raw_args="{}")


def test_first_time_is_not_duplicate_second_is() -> None:
    reg = DedupRegistry()
    assert reg.seen_before(_call("read", {"path": "a.txt"})) is False
    assert reg.seen_before(_call("read", {"path": "a.txt"})) is True


def test_different_args_are_distinct() -> None:
    reg = DedupRegistry()
    assert reg.seen_before(_call("read", {"path": "a.txt"})) is False
    assert reg.seen_before(_call("read", {"path": "b.txt"})) is False


def test_windows_backslash_paths_collide() -> None:
    reg = DedupRegistry()
    assert reg.seen_before(_call("read", {"path": "dir\\a.txt"})) is False
    assert reg.seen_before(_call("read", {"path": "dir/a.txt"})) is True


def test_key_order_is_irrelevant() -> None:
    reg = DedupRegistry()
    assert reg.seen_before(_call("t", {"a": 1, "b": 2})) is False
    assert reg.seen_before(_call("t", {"b": 2, "a": 1})) is True
