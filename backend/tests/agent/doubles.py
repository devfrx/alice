"""Double di test per le 7 porte del motore (structural typing, no ABC)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from backend.services.agent import ports
from backend.services.agent.events import AgentEvent
from backend.services.agent.models import ToolInvocation, ToolMeta


class ScriptedLLMPort:
    """LLMPort: ogni chiamata a ``stream_step`` consuma la prossima lista."""

    def __init__(self, steps: list[list[ports.LLMEvent]]) -> None:
        self._steps = list(steps)
        self.calls: list[dict[str, Any]] = []
        # Capability vision del double: i test la accendono per-test.
        self.vision = False

    def supports_vision(self) -> bool:
        return self.vision

    async def stream_step(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None,
        cancel: asyncio.Event,
    ) -> AsyncIterator[ports.LLMEvent]:
        self.calls.append({"messages": messages, "tools": tools})
        step_events = self._steps.pop(0)
        for event in step_events:
            yield event


class RecordingEventPort:
    """EventPort: append-only, ``emit`` non solleva mai."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


class InMemoryPersistence:
    """PersistencePort: stato in-memoria, ordine di chiamata tracciato."""

    def __init__(
        self, history: list[dict[str, Any]] | None = None, *,
        fail_final: bool = False, fail_final_checkpoint: bool = False,
    ) -> None:
        self._history = history or []
        self.assistant_steps: list[dict[str, Any]] = []
        self.tool_results: list[dict[str, Any]] = []
        self.audits: list[dict[str, Any]] = []
        self.final_messages: list[dict[str, Any]] = []
        self.checkpoints = 0
        self.order: list[tuple[str, str]] = []
        self.archived: list[tuple[str, list[str]]] = []
        self._next_id = 0
        self._fail_final = fail_final
        # ``fail_final_checkpoint``: il save finale riesce (id ritornato), ma
        # il checkpoint SUCCESSIVO solleva. Armato dentro save_final_message
        # cosi' i checkpoint degli step tool intermedi restano sani.
        self._fail_final_checkpoint = fail_final_checkpoint
        self._checkpoint_armed = False

    async def save_assistant_step(
        self, *, content: str, thinking: str,
        tool_calls: tuple[ToolInvocation, ...],
    ) -> str:
        self._next_id += 1
        msg_id = f"msg_{self._next_id}"
        self.assistant_steps.append({
            "content": content, "thinking": thinking, "tool_calls": tool_calls,
        })
        self.order.append(("assistant_step", msg_id))
        return msg_id

    async def save_tool_result(
        self, *, call: ToolInvocation, content: str, status: str,
    ) -> None:
        self.tool_results.append({
            "call_id": call.call_id, "call": call, "content": content, "status": status,
        })
        self.order.append(("tool_result", call.call_id))

    async def save_final_message(
        self, *, content: str, thinking: str,
        input_tokens: int, output_tokens: int, cost: float,
    ) -> str:
        if self._fail_final:
            raise RuntimeError("persist boom")
        if self._fail_final_checkpoint:
            self._checkpoint_armed = True
        self.final_messages.append({
            "content": content, "thinking": thinking,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost": cost,
        })
        self.order.append(("final_message", "final-msg-1"))
        return "final-msg-1"

    async def save_audit(
        self, *, call: ToolInvocation, verdict: ports.GateVerdict,
        interaction: ports.InteractionOutcome | None,
    ) -> None:
        self.audits.append({"call": call, "verdict": verdict, "interaction": interaction})

    async def register_artifacts(
        self, *, call: ToolInvocation, output: ports.ToolExecutionOutput,
    ) -> str | None:
        self.order.append(("artifact", call.call_id))
        return None

    async def checkpoint(self) -> None:
        if self._checkpoint_armed:
            raise RuntimeError("checkpoint boom")
        self.checkpoints += 1
        self.order.append(("checkpoint", ""))

    async def load_history(self) -> list[dict[str, Any]]:
        return self._history

    async def archive_compacted(
        self, *, summary_text: str, upto_message_ids: list[str],
    ) -> None:
        self.archived.append((summary_text, upto_message_ids))


class StaticPermissionPort:
    """PermissionPort: verdetto statico per nome tool, con default."""

    def __init__(
        self, verdicts: dict[str, ports.GateVerdict], default: ports.GateVerdict,
    ) -> None:
        self._verdicts = verdicts
        self._default = default
        self.calls: list[ToolInvocation] = []
        self.remember_calls: list[dict[str, Any]] = []

    async def decide(
        self, call: ToolInvocation, *, conversation_id: str,
    ) -> ports.GateVerdict:
        self.calls.append(call)
        return self._verdicts.get(call.name, self._default)

    async def remember_approval(
        self, call: ToolInvocation, *, conversation_id: str,
        scope: ports.RememberScope,
    ) -> None:
        self.remember_calls.append({
            "name": call.name, "conversation_id": conversation_id, "scope": scope,
        })


class ScriptedInteractionPort:
    """InteractionPort: esiti scriptati per conferma/tool client/ask_user."""

    def __init__(
        self,
        confirm: ports.InteractionOutcome = ports.InteractionOutcome.APPROVED,
        client_result: ports.ToolExecutionOutput | None = None,
        ask_user_result: ports.ToolExecutionOutput | None = None,
        confirm_remember: ports.RememberScope = ports.RememberScope.NONE,
    ) -> None:
        self._confirm = confirm
        self._client_result = client_result
        self._ask_user_result = ask_user_result
        self._confirm_remember = confirm_remember

    async def confirm_tool(
        self, call: ToolInvocation, *, interaction_id: str, verdict: ports.GateVerdict,
        timeout_s: float, cancel: asyncio.Event,
    ) -> ports.ConfirmationResult:
        # DISCONNECTED torna come dato: il motore persiste prima di fermarsi (spec §6.5)
        return ports.ConfirmationResult(
            outcome=self._confirm, remember=self._confirm_remember,
        )

    async def run_client_tool(
        self, call: ToolInvocation, *, interaction_id: str, timeout_s: float,
        cancel: asyncio.Event,
    ) -> ports.ToolExecutionOutput:
        if self._client_result is None:
            raise ports.EngineDisconnected("client disconnesso durante tool client")
        return self._client_result

    async def ask_user(
        self, call: ToolInvocation, *, interaction_id: str, timeout_s: float,
        cancel: asyncio.Event,
    ) -> ports.ToolExecutionOutput:
        if self._ask_user_result is None:
            raise ports.EngineDisconnected("client disconnesso durante ask_user")
        return self._ask_user_result


class NoopContextPort:
    """ContextPort: non compatta mai."""

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return 0

    def should_compact(self, *, tokens: int, context_window: int) -> bool:
        return False

    async def compact(
        self, *, messages: list[dict[str, Any]], context_window: int,
    ) -> ports.CompactionResult:
        return ports.CompactionResult(
            performed=False, summary_text=None, tokens_before=0, tokens_after=0,
        )


class TriggeringContextPort:
    """ContextPort: compatta alla prima chiamata a ``should_compact``, poi mai."""

    def __init__(self, result: ports.CompactionResult) -> None:
        self._result = result
        self._triggered = False
        self.calls: list[dict[str, Any]] = []

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return 0

    def should_compact(self, *, tokens: int, context_window: int) -> bool:
        self.calls.append({"tokens": tokens, "context_window": context_window})
        if self._triggered:
            return False
        self._triggered = True
        return True

    async def compact(
        self, *, messages: list[dict[str, Any]], context_window: int,
    ) -> ports.CompactionResult:
        return self._result


class RaisingContextPort:
    """ContextPort double: compact() solleva sempre (copre il ramo fail-open)."""

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return 99999

    def should_compact(self, *, tokens: int, context_window: int) -> bool:
        return True

    async def compact(
        self, *, messages: list[dict[str, Any]], context_window: int,
    ) -> ports.CompactionResult:
        raise RuntimeError("compaction esplosa")


class MapExecutionPort:
    """ExecutionPort: risultati/metadati/ritardi/errori mappati per nome tool.

    ``progress`` mappa il nome tool a un payload di progresso: quando presente e
    ``on_progress`` è fornito, ``execute`` invoca ``await on_progress(payload)``
    prima di ritornare l'output (simula un tool lungo che streamma progresso).
    """

    def __init__(
        self,
        tools: dict[str, ports.ToolExecutionOutput],
        meta: dict[str, ToolMeta] | None = None,
        delays: dict[str, float] | None = None,
        errors: dict[str, Exception] | None = None,
        progress: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._tools = tools
        self._meta = meta or {}
        self._delays = delays or {}
        self._errors = errors or {}
        self._progress = progress or {}
        self.started_at: dict[str, float] = {}

    def describe(self, name: str) -> ToolMeta:
        return self._meta.get(name, ToolMeta(exists=name in self._tools))

    async def execute(
        self, call: ToolInvocation, *, client_ip: str | None,
        conversation_id: str,
        on_progress: ports.ProgressCallback | None = None,
    ) -> ports.ToolExecutionOutput:
        loop = asyncio.get_running_loop()
        self.started_at.setdefault(call.name, loop.time())
        delay = self._delays.get(call.name, 0)
        if delay:
            await asyncio.sleep(delay)
        if call.name in self._errors:
            raise self._errors[call.name]
        payload = self._progress.get(call.name)
        if payload is not None and on_progress is not None:
            await on_progress(payload)
        return self._tools[call.name]
