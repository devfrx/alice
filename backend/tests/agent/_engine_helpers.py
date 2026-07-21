"""Helper condivisi per i test dell'engine: script LLM, richiesta, run.

Non è un modulo di test (niente ``test_*``): pytest non lo colleziona,
esattamente come ``doubles.py``.
"""

from __future__ import annotations

import asyncio

from backend.services.agent import ports
from backend.services.agent.engine import AgentEngine
from backend.services.agent.models import (
    ToolInvocation,
    ToolMeta,
    TurnOutcome,
    TurnRequest,
    TurnSource,
)
from backend.services.agent.retry import RetryPolicy
from backend.tests.agent.doubles import (
    InMemoryPersistence,
    MapExecutionPort,
    NoopContextPort,
    RecordingEventPort,
    ScriptedInteractionPort,
    ScriptedLLMPort,
    StaticPermissionPort,
    TriggeringContextPort,
)

# helper: uno ScriptedLLMPort a 2 step — step 1 emette le tool call date,
# step 2 chiude con testo "fatto".


def _tool_step(calls: tuple[ToolInvocation, ...]) -> list[ports.LLMEvent]:
    return [ports.LLMStepDone(finish_reason="tool_calls", tool_calls=calls)]


def _final_step() -> list[ports.LLMEvent]:
    return [ports.LLMTextDelta(text="fatto"),
            ports.LLMStepDone(finish_reason="stop", tool_calls=())]


def _request(
    *, max_steps: int = 8, max_tool_calls: int | None = None,
    user_message_id: str | None = None,
    version_group_id: str | None = None,
    version_index: int | None = None,
) -> TurnRequest:
    return TurnRequest(
        conversation_id="c1", system_prompt="sp",
        history=[{"role": "user", "content": "ciao"}], tools=[],
        source=TurnSource.CHAT, max_steps=max_steps, context_window=32768,
        resolved_max_tokens=None, client_ip=None,
        version_group_id=version_group_id, version_index=version_index,
        user_message_id=user_message_id,
        max_tool_calls=max_tool_calls,
    )


def _engine(
    *,
    llm: ScriptedLLMPort,
    events: RecordingEventPort,
    persistence: InMemoryPersistence,
    execution: MapExecutionPort,
    verdicts: dict[str, ports.GateVerdict] | None,
    confirm: ports.InteractionOutcome,
    context: ports.ContextPort | None = None,
    client_result: ports.ToolExecutionOutput | None = None,
    ask_user_result: ports.ToolExecutionOutput | None = None,
    confirm_remember: ports.RememberScope = ports.RememberScope.NONE,
    permission_port: StaticPermissionPort | None = None,
    vision_enabled: bool = True,
    vision_max_images: int = 4,
) -> AgentEngine:
    return AgentEngine(
        llm=llm,
        permissions=permission_port if permission_port is not None else StaticPermissionPort(
            verdicts=verdicts or {},
            default=ports.GateVerdict(action=ports.GateAction.EXECUTE, outcome="allow"),
        ),
        interaction=ScriptedInteractionPort(
            confirm=confirm, client_result=client_result, ask_user_result=ask_user_result,
            confirm_remember=confirm_remember,
        ),
        events=events,
        persistence=persistence,
        context=context or NoopContextPort(),
        execution=execution,
        retry=RetryPolicy(),
        vision_enabled=vision_enabled,
        vision_max_images=vision_max_images,
    )


async def _run_with_port(
    *,
    llm_steps: list[list[ports.LLMEvent]],
    exec_tools: dict[str, ports.ToolExecutionOutput],
    verdicts: dict[str, ports.GateVerdict] | None = None,
    confirm: ports.InteractionOutcome = ports.InteractionOutcome.APPROVED,
    delays: dict[str, float] | None = None,
    errors: dict[str, Exception] | None = None,
    meta: dict[str, ToolMeta] | None = None,
    cancel: asyncio.Event | None = None,
    max_steps: int = 8,
    max_tool_calls: int | None = None,
    client_result: ports.ToolExecutionOutput | None = None,
    ask_user_result: ports.ToolExecutionOutput | None = None,
    progress: dict[str, dict] | None = None,
    fail_final: bool = False,
    fail_final_checkpoint: bool = False,
    user_message_id: str | None = None,
    version_group_id: str | None = None,
    version_index: int | None = None,
    confirm_remember: ports.RememberScope = ports.RememberScope.NONE,
    permission_port: StaticPermissionPort | None = None,
) -> tuple[InMemoryPersistence, TurnOutcome, RecordingEventPort, MapExecutionPort]:
    """Costruisce l'engine coi double e lo esegue, esponendo anche l'ExecutionPort."""
    persistence = InMemoryPersistence(
        fail_final=fail_final, fail_final_checkpoint=fail_final_checkpoint,
    )
    rec = RecordingEventPort()
    llm = ScriptedLLMPort(steps=llm_steps)
    exec_port = MapExecutionPort(
        tools=exec_tools, meta=meta, delays=delays, errors=errors, progress=progress,
    )
    engine = _engine(
        llm=llm, events=rec, persistence=persistence, execution=exec_port,
        verdicts=verdicts, confirm=confirm, client_result=client_result,
        ask_user_result=ask_user_result, confirm_remember=confirm_remember,
        permission_port=permission_port,
    )
    request = _request(
        max_steps=max_steps, max_tool_calls=max_tool_calls,
        user_message_id=user_message_id, version_group_id=version_group_id,
        version_index=version_index,
    )
    outcome = await engine.run(request, cancel=cancel or asyncio.Event())
    return persistence, outcome, rec, exec_port


async def _run_with(
    *,
    llm_steps: list[list[ports.LLMEvent]],
    exec_tools: dict[str, ports.ToolExecutionOutput],
    verdicts: dict[str, ports.GateVerdict] | None = None,
    confirm: ports.InteractionOutcome = ports.InteractionOutcome.APPROVED,
    delays: dict[str, float] | None = None,
    errors: dict[str, Exception] | None = None,
    meta: dict[str, ToolMeta] | None = None,
    cancel: asyncio.Event | None = None,
    max_steps: int = 8,
    max_tool_calls: int | None = None,
    client_result: ports.ToolExecutionOutput | None = None,
    ask_user_result: ports.ToolExecutionOutput | None = None,
    progress: dict[str, dict] | None = None,
    fail_final: bool = False,
    fail_final_checkpoint: bool = False,
    user_message_id: str | None = None,
    version_group_id: str | None = None,
    version_index: int | None = None,
    confirm_remember: ports.RememberScope = ports.RememberScope.NONE,
    permission_port: StaticPermissionPort | None = None,
) -> tuple[InMemoryPersistence, TurnOutcome, RecordingEventPort]:
    """Come ``_run_with_port`` ma senza esporre l'ExecutionPort."""
    persistence, outcome, rec, _ = await _run_with_port(
        llm_steps=llm_steps, exec_tools=exec_tools, verdicts=verdicts,
        confirm=confirm, delays=delays, errors=errors, meta=meta, cancel=cancel,
        max_steps=max_steps, max_tool_calls=max_tool_calls, client_result=client_result,
        ask_user_result=ask_user_result, progress=progress, fail_final=fail_final,
        fail_final_checkpoint=fail_final_checkpoint,
        user_message_id=user_message_id, version_group_id=version_group_id,
        version_index=version_index, confirm_remember=confirm_remember,
        permission_port=permission_port,
    )
    return persistence, outcome, rec


async def _run_with_compaction(
    *,
    llm_steps: list[list[ports.LLMEvent]],
    exec_tools: dict[str, ports.ToolExecutionOutput],
    compaction: ports.CompactionResult | None = None,
    context_port: ports.ContextPort | None = None,
    verdicts: dict[str, ports.GateVerdict] | None = None,
    confirm: ports.InteractionOutcome = ports.InteractionOutcome.APPROVED,
    delays: dict[str, float] | None = None,
    meta: dict[str, ToolMeta] | None = None,
    cancel: asyncio.Event | None = None,
    max_steps: int = 8,
    max_tool_calls: int | None = None,
) -> tuple[InMemoryPersistence, TurnOutcome, RecordingEventPort, ScriptedLLMPort]:
    """Come ``_run_with`` ma con un ``ContextPort`` iniettato, esponendo l'LLMPort.

    Se ``context_port`` è None, usa ``TriggeringContextPort(compaction)``; altrimenti
    usa il context_port fornito (compaction viene ignorato in questo caso).
    """
    persistence = InMemoryPersistence()
    rec = RecordingEventPort()
    llm = ScriptedLLMPort(steps=llm_steps)
    exec_port = MapExecutionPort(tools=exec_tools, meta=meta, delays=delays)
    if context_port is None:
        if compaction is None:
            raise ValueError("Almeno uno tra context_port e compaction deve essere fornito")
        context_port = TriggeringContextPort(compaction)
    engine = _engine(
        llm=llm, events=rec, persistence=persistence, execution=exec_port,
        verdicts=verdicts, confirm=confirm,
        context=context_port,
    )
    request = _request(max_steps=max_steps, max_tool_calls=max_tool_calls)
    outcome = await engine.run(request, cancel=cancel or asyncio.Event())
    return persistence, outcome, rec, llm
