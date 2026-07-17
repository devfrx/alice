"""Test d'integrazione del composition root (``services/agent/runner.py``).

Un turno headless COMPLETO sull'app di test con ``ALICE_AGENT__ENGINE=v2``
(pattern env-before-boot dell'eval runner, ``tests/evals/test_runner_mock.py``):
il ramo v2 di ``run_headless_turn`` costruisce un ``TurnRequest``, monta le
porte via ``run_agent_turn`` e guida il turno attraverso ``AgentEngine``.

PILASTRO (engine tests own their doubles): lo shim LLM (``ScriptedLLMShim``,
importato da ``_llm_shim.py``) è LOCALE alla suite ``tests/agent/``, NON
riusa ``tests/evals/scripted_llm.py`` (quel doppio serve al percorso legacy).
Espone la superficie di piattaforma consumata dall'assembly/persist
(``get_system_prompt``/``build_messages``/...) e la ``chat`` async-iterator
consumata da ``LLMServiceAdapter``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.core.app import create_app
from backend.services.agent.models import ToolInvocation
from backend.services.agent.ports import GateAction, GateVerdict, InteractionOutcome
from backend.services.agent.runner import AutoDeclineInteractionPort, SinkEventPort
from backend.tests.agent._llm_shim import ScriptedLLMShim


@pytest.fixture
async def v2_app(monkeypatch: pytest.MonkeyPatch):
    """App di test bootata con ``agent.engine=v2`` (env-before-boot)."""
    monkeypatch.setenv("ALICE_AGENT__ENGINE", "v2")
    application = create_app(testing=True)
    async with application.router.lifespan_context(application):
        yield application


async def test_headless_turn_runs_on_v2_engine(v2_app: Any) -> None:
    from backend.api.routes.chat.headless import run_headless_turn
    from backend.evals.sink import RecordingSink

    ctx = v2_app.state.context
    assert ctx.config.agent.engine == "v2"

    ctx.llm_service = ScriptedLLMShim([
        {"type": "token", "content": "Ciao! Come posso aiutarti?"},
        {"type": "usage", "input_tokens": 12, "output_tokens": 6, "cost": 0.0},
        {"type": "done", "finish_reason": "stop"},
    ])
    sink = RecordingSink()

    result = await run_headless_turn(
        ctx, conversation_id=None, prompt="ciao", sink=sink,
    )

    assert result is not None
    assert result.finish_reason == "stop"
    assert "Ciao!" in result.content

    types = [f["type"] for f in sink.events]
    assert "turn.llm_step" in types
    assert "turn.finished" in types


# ---------------------------------------------------------------------------
# Unit: le due porte headless del composition root (§6.14).
# ---------------------------------------------------------------------------

_CALL = ToolInvocation(call_id="c1", name="write_file", args={}, raw_args="{}")
_VERDICT = GateVerdict(action=GateAction.CONFIRM, outcome="needs_confirmation")


async def test_auto_decline_interaction_port_declines_all() -> None:
    """Headless (§6.14): nessuna UI da servire — ``confirm_tool`` rifiuta
    pulito, ``run_client_tool``/``ask_user`` tornano un ``ToolExecutionOutput``
    d'errore esplicito (mai un'eccezione: il motore riceve comunque un dato)."""
    port = AutoDeclineInteractionPort()

    outcome = await port.confirm_tool(
        _CALL, verdict=_VERDICT, timeout_s=1, cancel=asyncio.Event(),
    )
    assert outcome is InteractionOutcome.REJECTED

    client_out = await port.run_client_tool(_CALL, timeout_s=1, cancel=asyncio.Event())
    assert client_out.ok is False and client_out.error

    ask_out = await port.ask_user(_CALL, timeout_s=1, cancel=asyncio.Event())
    assert ask_out.ok is False and ask_out.error


async def test_sink_event_port_noop_when_sink_disconnected() -> None:
    """``SinkEventPort`` rispetta ``sink.is_connected`` (§6.14: contratto
    eval — ``RecordingEventSink`` parte con ``is_connected=True``, ma un sink
    disconnesso non deve ricevere frame)."""

    class _DisconnectedSink:
        def __init__(self) -> None:
            self.sent: list[dict[str, Any]] = []

        async def send(self, event: dict[str, Any]) -> None:
            self.sent.append(event)

        @property
        def is_connected(self) -> bool:
            return False

    sink = _DisconnectedSink()
    port = SinkEventPort(sink, lambda _event: [{"type": "token", "content": "x"}])

    await port.emit(object())  # type: ignore[arg-type] — translator banale

    assert sink.sent == []
