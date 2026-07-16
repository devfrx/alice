"""Test della CLI (parsing e wiring, senza run reali)."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from backend.evals.cli import build_parser, main, resolve_api_key
from backend.evals.loader import ScenarioLoadError
from backend.evals.models import CheckSpec, RunReport, Scenario


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


def _fake_scenario() -> Scenario:
    """Scenario minimo valido: mai eseguito davvero, ``run_suite`` è stubbato."""
    return Scenario(
        id="fake-01",
        title="Fake scenario",
        domain="filesystem",
        prompt="prompt fittizio",
        checks=[CheckSpec(kind="finished_ok")],
    )


def _make_captured_run_suite(
    captured: dict[str, str | None],
) -> Callable[..., Awaitable[RunReport]]:
    """Fabbrica di uno stub async di ``run_suite`` che cattura l'env al call-time.

    Args:
        captured: Dizionario in cui scrivere ``qdrant_path`` (il valore di
            ``ALICE_QDRANT__PATH`` letto nel momento in cui lo stub viene
            invocato, cioè dopo che ``_cmd_run`` ha già forzato l'ambiente).

    Returns:
        Una coroutine function con la stessa firma di
        :func:`backend.evals.runner.run_suite`, che non esegue alcun turno
        reale e ritorna un :class:`RunReport` vuoto ma valido.
    """

    async def _fake_run_suite(
        scenarios: list[Scenario],
        *,
        output_dir: Path,
        run_id: str,
        started_at: str,
        model: str = "irrelevant-model",
        judge_enabled: bool = True,
    ) -> RunReport:
        del scenarios, output_dir, judge_enabled  # non rilevanti per questo stub
        captured["qdrant_path"] = os.environ.get("ALICE_QDRANT__PATH")
        return RunReport(run_id=run_id, model=model, started_at=started_at, scenarios=[])

    return _fake_run_suite


def test_cmd_run_sets_qdrant_isolation_when_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Senza override pre-esistente, ``_cmd_run`` isola Qdrant sotto l'output del run.

    Regressione safety-critical (review T7/T9): un run eval con LLM vero non
    deve mai scrivere nel vector store reale dell'utente. Usa ``main(["run",
    ...])`` (non ``_cmd_run`` direttamente) cosi' il test copre anche il
    dispatch di ``main`` sul subcomando ``run``.
    """
    monkeypatch.setenv("ALICE_LLM__OPENROUTER_API_KEY", "sk-test")
    # _cmd_run scrive ALICE_LLM__PROVIDER e ALICE_LLM__OPENROUTER_MODEL
    # incondizionatamente via os.environ diretto (non tramite monkeypatch):
    # portarle sotto controllo del teardown ora, prima che _cmd_run le tocchi,
    # cosi' il valore pre-test (qui: assente) viene ripristinato a fine test
    # qualunque cosa scriva _cmd_run nel frattempo.
    monkeypatch.setenv("ALICE_LLM__PROVIDER", "sentinel")
    monkeypatch.setenv("ALICE_LLM__OPENROUTER_MODEL", "sentinel")
    # ALICE_QDRANT__PATH e' scritto da _cmd_run solo via os.environ.setdefault
    # (mai se gia' presente): per testare il ramo "assente" dobbiamo garantire
    # che parta assente E che monkeypatch la tracci comunque per il teardown.
    # monkeypatch.delenv(..., raising=False) su una chiave gia' assente NON la
    # registra per il ripristino (si limita a fare return) — quindi il valore
    # scritto da setdefault durante il test sopravviverebbe e inquinerebbe i
    # test successivi. Il trucco setenv+delenv la mette sotto controllo prima.
    monkeypatch.setenv("ALICE_QDRANT__PATH", "sentinel")
    monkeypatch.delenv("ALICE_QDRANT__PATH")

    captured: dict[str, str | None] = {}
    monkeypatch.setattr("backend.evals.cli.load_scenarios", lambda *a, **k: [_fake_scenario()])
    monkeypatch.setattr("backend.evals.cli.run_suite", _make_captured_run_suite(captured))

    exit_code = main(["run", "--output", str(tmp_path), "--no-judge"])

    assert exit_code == 0
    assert captured["qdrant_path"] is not None
    captured_path = Path(captured["qdrant_path"])
    assert captured_path.is_relative_to(tmp_path)
    assert captured_path.name == "qdrant"


def test_cmd_run_respects_preexisting_qdrant_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Un ``ALICE_QDRANT__PATH`` pre-esistente non viene sovrascritto da ``_cmd_run``."""
    monkeypatch.setenv("ALICE_LLM__OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("ALICE_LLM__PROVIDER", "sentinel")
    monkeypatch.setenv("ALICE_LLM__OPENROUTER_MODEL", "sentinel")
    monkeypatch.setenv("ALICE_QDRANT__PATH", "X:/custom")

    captured: dict[str, str | None] = {}
    monkeypatch.setattr("backend.evals.cli.load_scenarios", lambda *a, **k: [_fake_scenario()])
    monkeypatch.setattr("backend.evals.cli.run_suite", _make_captured_run_suite(captured))

    exit_code = main(["run", "--output", str(tmp_path), "--no-judge"])

    assert exit_code == 0
    assert captured["qdrant_path"] == "X:/custom"


def test_main_list_dispatches_to_cmd_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main(["list"])`` instrada su ``_cmd_list`` e ritorna 0 anche a lista vuota.

    Il dispatch di ``main`` su ``run`` è già coperto dai due test precedenti
    (usano ``main([...])`` invece di chiamare ``_cmd_run`` direttamente).
    """
    monkeypatch.setattr("backend.evals.cli.load_scenarios", lambda *a, **k: [])
    assert main(["list"]) == 0


def test_main_list_survives_narrow_console_encoding(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """main() non deve crashare quando stdout non supporta UTF-8 (cp1252)."""
    monkeypatch.setattr(
        "backend.evals.cli.load_scenarios",
        lambda *a, **k: [],
    )
    assert main(["list"]) == 0


def test_cmd_list_invalid_scenario_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(*a: object, **k: object) -> list[object]:
        raise ScenarioLoadError("rotto.yaml: schema invalido")

    monkeypatch.setattr("backend.evals.cli.load_scenarios", _boom)
    assert main(["list"]) == 2
    assert "rotto.yaml" in capsys.readouterr().err
