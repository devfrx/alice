"""LLM scriptato per i test e2e dell'eval harness (zero rete)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


class ScriptedLLM:
    """Implementazione minima di ``LLMServiceProtocol`` a eventi scriptati.

    Args:
        scripts: Una lista di eventi per ogni chiamata a :meth:`chat`
            (la prima chiamata consuma ``scripts[0]``, ecc.).
        judge_reply: Risposta fissa di :meth:`complete_nonstreaming`.
    """

    def __init__(
        self,
        scripts: list[list[dict[str, Any]]],
        judge_reply: str = '{"score": 7, "reason": "ok"}',
    ) -> None:
        self._scripts = scripts
        self._judge_reply = judge_reply
        self.chat_calls = 0

    # -- Membri usati dal percorso assembly/esecuzione ------------------

    @property
    def supports_vision(self) -> bool:
        return False

    def get_system_prompt(
        self,
        memory_context: str | None = None,
        *,
        persona: str | None = None,
    ) -> str:
        return "Sei un assistente di test."

    def get_scoped_system_prompt(
        self,
        base_prompt_path: str,
        memory_context: str | None = None,
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
        cancel_event: asyncio.Event | None = None,
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        script = (
            self._scripts[self.chat_calls]
            if self.chat_calls < len(self._scripts)
            else [{"type": "done", "finish_reason": "stop"}]
        )
        self.chat_calls += 1
        for event in script:
            yield dict(event)

    async def complete_nonstreaming(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 512,
    ) -> str:
        return self._judge_reply

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
