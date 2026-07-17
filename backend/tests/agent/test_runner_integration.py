"""Test d'integrazione del composition root (``services/agent/runner.py``).

Un turno headless COMPLETO sull'app di test con ``ALICE_AGENT__ENGINE=v2``
(pattern env-before-boot dell'eval runner, ``tests/evals/test_runner_mock.py``):
il ramo v2 di ``run_headless_turn`` costruisce un ``TurnRequest``, monta le
porte via ``run_agent_turn`` e guida il turno attraverso ``AgentEngine``.

PILASTRO (engine tests own their doubles): lo shim LLM è LOCALE a questo file,
NON riusa ``tests/evals/scripted_llm.py`` (quel doppio serve al percorso
legacy). Espone la superficie di piattaforma consumata dall'assembly/persist
(``get_system_prompt``/``build_messages``/...) e la ``chat`` async-iterator
consumata da ``LLMServiceAdapter``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from backend.core.app import create_app


class _ScriptedLLMShim:
    """Doppio LLM minimo: assembly-surface + ``chat`` scriptata.

    ``chat`` è un async-generator che rende i chunk in formato piattaforma
    (``token``/``usage``/``done``), esattamente ciò che ``LLMServiceAdapter``
    normalizza in ``LLMEvent``.
    """

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks
        self.chat_calls = 0

    @property
    def supports_vision(self) -> bool:
        return False

    def get_system_prompt(
        self, memory_context: str | None = None, *, persona: str | None = None,
    ) -> str:
        return "Sei un assistente di test."

    def get_scoped_system_prompt(
        self, base_prompt_path: str, memory_context: str | None = None,
    ) -> str:
        return "Sei un assistente di test."

    def build_messages(
        self,
        user_content: str,
        history: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, str]] | None = None,
        memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt or self.get_system_prompt()},
        ]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_content})
        return messages

    def build_continuation_messages(
        self,
        history: list[dict[str, Any]],
        memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": system_prompt or self.get_system_prompt()},
            *history,
        ]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        cancel_event: Any = None,
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.chat_calls += 1
        for chunk in self._chunks:
            yield dict(chunk)

    async def complete_nonstreaming(
        self, messages: list[dict[str, Any]], max_tokens: int = 512,
    ) -> str:
        return "ok"

    async def get_active_context_window(self, lmstudio_manager: Any = None) -> int:
        return 8192

    def get_cached_context_window(self, lmstudio_manager: Any = None) -> int:
        return 8192

    def invalidate_context_window_cache(self) -> None:
        return None

    def invalidate_model_cache(self) -> None:
        return None

    def invalidate_system_prompt_cache(self) -> None:
        return None


@pytest.fixture
async def v2_app(monkeypatch: pytest.MonkeyPatch):
    """App di test bootata con ``agent.engine=v2`` (env-before-boot)."""
    monkeypatch.setenv("ALICE_AGENT__ENGINE", "v2")
    application = create_app(testing=True)
    async with application.router.lifespan_context(application):
        yield application


async def test_headless_turn_runs_on_v2_engine(v2_app: Any) -> None:
    from backend.api.routes.chat.headless import run_headless_turn
    from backend.services.turn.sink import RecordingEventSink

    ctx = v2_app.state.context
    assert ctx.config.agent.engine == "v2"

    ctx.llm_service = _ScriptedLLMShim([
        {"type": "token", "content": "Ciao! Come posso aiutarti?"},
        {"type": "usage", "input_tokens": 12, "output_tokens": 6, "cost": 0.0},
        {"type": "done", "finish_reason": "stop"},
    ])
    sink = RecordingEventSink()

    result = await run_headless_turn(
        ctx, conversation_id=None, prompt="ciao", sink=sink,
    )

    assert result is not None
    assert result.finish_reason == "stop"
    assert "Ciao!" in result.content

    types = [f["type"] for f in sink.events]
    assert "turn.llm_step" in types
    assert "turn.finished" in types
