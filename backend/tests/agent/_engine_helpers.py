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
) -> TurnRequest:
    return TurnRequest(
        conversation_id="c1", system_prompt="sp",
        history=[{"role": "user", "content": "ciao"}], tools=[],
        source=TurnSource.CHAT, max_steps=max_steps, context_window=32768,
        resolved_max_tokens=None, client_ip=None,
        version_group_id=None, version_index=None,
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
) -> AgentEngine:
    return AgentEngine(
        llm=llm,
        permissions=StaticPermissionPort(
            verdicts=verdicts or {},
            default=ports.GateVerdict(action=ports.GateAction.EXECUTE, outcome="allow"),
        ),
        interaction=ScriptedInteractionPort(confirm=confirm),
        events=events,
        persistence=persistence,
        context=NoopContextPort(),
        execution=execution,
        retry=RetryPolicy(),
    )


async def _run_with_port(
    *,
    llm_steps: list[list[ports.LLMEvent]],
    exec_tools: dict[str, ports.ToolExecutionOutput],
    verdicts: dict[str, ports.GateVerdict] | None = None,
    confirm: ports.InteractionOutcome = ports.InteractionOutcome.APPROVED,
    delays: dict[str, float] | None = None,
    meta: dict[str, ToolMeta] | None = None,
    cancel: asyncio.Event | None = None,
    max_steps: int = 8,
    max_tool_calls: int | None = None,
) -> tuple[InMemoryPersistence, TurnOutcome, RecordingEventPort, MapExecutionPort]:
    """Costruisce l'engine coi double e lo esegue, esponendo anche l'ExecutionPort."""
    persistence = InMemoryPersistence()
    rec = RecordingEventPort()
    llm = ScriptedLLMPort(steps=llm_steps)
    exec_port = MapExecutionPort(tools=exec_tools, meta=meta, delays=delays)
    engine = _engine(
        llm=llm, events=rec, persistence=persistence, execution=exec_port,
        verdicts=verdicts, confirm=confirm,
    )
    request = _request(max_steps=max_steps, max_tool_calls=max_tool_calls)
    outcome = await engine.run(request, cancel=cancel or asyncio.Event())
    return persistence, outcome, rec, exec_port


async def _run_with(
    *,
    llm_steps: list[list[ports.LLMEvent]],
    exec_tools: dict[str, ports.ToolExecutionOutput],
    verdicts: dict[str, ports.GateVerdict] | None = None,
    confirm: ports.InteractionOutcome = ports.InteractionOutcome.APPROVED,
    delays: dict[str, float] | None = None,
    meta: dict[str, ToolMeta] | None = None,
    cancel: asyncio.Event | None = None,
    max_steps: int = 8,
    max_tool_calls: int | None = None,
) -> tuple[InMemoryPersistence, TurnOutcome, RecordingEventPort]:
    """Come ``_run_with_port`` ma senza esporre l'ExecutionPort."""
    persistence, outcome, rec, _ = await _run_with_port(
        llm_steps=llm_steps, exec_tools=exec_tools, verdicts=verdicts,
        confirm=confirm, delays=delays, meta=meta, cancel=cancel,
        max_steps=max_steps, max_tool_calls=max_tool_calls,
    )
    return persistence, outcome, rec
