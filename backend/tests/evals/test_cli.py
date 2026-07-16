"""Test della CLI (parsing e wiring, senza run reali)."""

from __future__ import annotations

import pytest
from backend.evals.cli import build_parser, resolve_api_key


def test_parser_run_defaults() -> None:
    args = build_parser().parse_args(["run"])
    assert args.command == "run"
    assert args.filter is None
    assert args.no_judge is False
    assert args.baseline is None


def test_parser_list() -> None:
    args = build_parser().parse_args(["list"])
    assert args.command == "list"


def test_resolve_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALICE_LLM__OPENROUTER_API_KEY", "sk-test")
    assert resolve_api_key() == "sk-test"


def test_resolve_api_key_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALICE_LLM__OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "backend.evals.cli.keyring.get_password",
        lambda service, name: (
            "sk-keyring" if (service, name) == ("alice", "llm.openrouter_api_key") else None
        ),
    )
    assert resolve_api_key() == "sk-keyring"
