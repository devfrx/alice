"""LLM scriptato per i test e2e dell'eval harness (zero rete)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any


def tool_call_event(
    name: str,
    args: dict[str, Any],
    call_id: str,
) -> dict[str, Any]:
    """Evento scriptato di tool call con argomenti STRUTTURATI.

    Gli argomenti restano un dict (non la stringa JSON del contratto LLM):
    :class:`SandboxScriptedLLM` sostituisce il placeholder ``{sandbox}`` nei
    valori stringa e serializza in JSON solo al momento dello yield.

    Args:
        name: Nome namespaced del tool da invocare.
        args: Argomenti della call (valori stringa possono contenere
            ``{sandbox}``).
        call_id: Id univoco della call (dedup del motore).

    Returns:
        L'evento scriptato da inserire in uno script di :class:`ScriptedLLM`.
    """
    return {"type": "tool_call", "id": call_id, "name": name, "args": args}


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


class SandboxScriptedLLM(ScriptedLLM):
    """ScriptedLLM che risolve il placeholder ``{sandbox}`` negli argomenti.

    La sandbox di ``run_scenario`` è una directory ``mkdtemp`` nota solo a
    runtime: il path reale viene estratto dal messaggio utente, che per
    convenzione degli scenari mock inizia con la riga
    ``Cartella di lavoro: <path>`` (il runner sostituisce ``{sandbox}`` nel
    prompt prima del turno). Gli eventi ``tool_call`` strutturati (prodotti
    da :func:`tool_call_event`) vengono riscritti nel contratto reale del
    servizio LLM (``function.arguments`` stringa JSON) con il placeholder
    risolto; ogni altro evento passa invariato.
    """

    _WORKSPACE_RE = re.compile(r"^Cartella di lavoro: (.+)$", re.MULTILINE)

    def _find_sandbox(self, messages: list[dict[str, Any]]) -> str:
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                match = self._WORKSPACE_RE.search(content)
                if match:
                    return match.group(1).strip()
        # Fail-fast: senza il marker il placeholder resterebbe irrisolto e
        # il tool fallirebbe a valle con un errore di path fuorviante.
        raise RuntimeError(
            "SandboxScriptedLLM: nessun messaggio contiene la riga "
            "'Cartella di lavoro: <path>' richiesta dalla convenzione "
            "sandbox degli scenari mock — aggiungila al prompt dello "
            "scenario."
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        cancel_event: asyncio.Event | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        sandbox = self._find_sandbox(messages)
        async for event in super().chat(
            messages,
            tools=tools,
            cancel_event=cancel_event,
            **kwargs,
        ):
            if event.get("type") == "tool_call" and "args" in event:
                args = {
                    key: (value.replace("{sandbox}", sandbox) if isinstance(value, str) else value)
                    for key, value in event["args"].items()
                }
                yield {
                    "type": "tool_call",
                    "id": event.get("id", ""),
                    "function": {
                        "name": event["name"],
                        "arguments": json.dumps(args),
                    },
                }
            else:
                yield event
