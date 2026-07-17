"""Doppio LLM scriptato condiviso dai test d'integrazione del motore.

Estratto da ``test_runner_integration.py`` (era ``_ScriptedLLMShim``, locale
a quel file) perché ``test_ws_chat_live.py`` ne ha bisogno anch'esso: il
PILASTRO "engine tests own their doubles" vale per i doppi del motore
greenfield (``services/agent``), non per l'infrastruttura di test condivisa
DENTRO ``tests/agent/`` — stesso pattern di ``_engine_helpers.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class ScriptedLLMShim:
    """Doppio LLM minimo: assembly-surface + ``chat`` scriptata.

    ``chat`` è un async-generator che rende i chunk in formato piattaforma
    (``token``/``usage``/``done``), esattamente ciò che ``LLMServiceAdapter``
    normalizza in ``LLMEvent``.

    Accetta uno script singolo (``list[dict]``, reso identico ad ogni
    chiamata — comportamento originale) oppure uno script per-step
    (``list[list[dict]]``, indicizzato da ``chat_calls``, l'ultimo elemento
    ripetuto se le chiamate superano gli script disponibili) per i test
    multi-step (es. tool call seguita da una seconda query).
    """

    def __init__(self, chunks: list[dict[str, Any]] | list[list[dict[str, Any]]]) -> None:
        if chunks and isinstance(chunks[0], list):
            self._scripts: list[list[dict[str, Any]]] = [
                list(script) for script in chunks  # type: ignore[arg-type]
            ]
        else:
            self._scripts = [list(chunks)]  # type: ignore[list-item]
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
        script = self._scripts[min(self.chat_calls - 1, len(self._scripts) - 1)]
        for chunk in script:
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
