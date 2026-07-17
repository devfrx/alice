"""AgentEngine, percorso senza tool: eventi, retry vuoto, cancel, errore."""

import asyncio

import pytest

from backend.services.agent import ports
from backend.services.agent.engine import AgentEngine
from backend.services.agent.models import StopReason, TurnRequest, TurnSource
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


def _request() -> TurnRequest:
    return TurnRequest(
        conversation_id="c1", system_prompt="sp",
        history=[{"role": "user", "content": "ciao"}], tools=[],
        source=TurnSource.CHAT, max_steps=5, context_window=32768,
        resolved_max_tokens=None, client_ip=None,
        version_group_id=None, version_index=None,
    )


def _engine(llm: ScriptedLLMPort, events: RecordingEventPort) -> AgentEngine:
    return AgentEngine(
        llm=llm,
        permissions=StaticPermissionPort(verdicts={}, default=ports.GateVerdict(
            action=ports.GateAction.EXECUTE, outcome="allow")),
        interaction=ScriptedInteractionPort(),
        events=events,
        persistence=InMemoryPersistence(),
        context=NoopContextPort(),
        execution=MapExecutionPort(tools={}),
        retry=RetryPolicy(),
    )


async def test_happy_path_stream_to_finished() -> None:
    llm = ScriptedLLMPort(steps=[[
        ports.LLMTextDelta(text="ci"), ports.LLMTextDelta(text="ao"),
        ports.LLMUsage(input_tokens=10, output_tokens=2, cost=0.001),
        ports.LLMStepDone(finish_reason="stop", tool_calls=()),
    ]])
    rec = RecordingEventPort()
    outcome = await _engine(llm, rec).run(_request(), cancel=asyncio.Event())
    assert outcome.content == "ciao"
    assert outcome.finish_reason == "stop"
    assert outcome.stop_reason is StopReason.COMPLETED
    assert outcome.steps == 1 and outcome.cost == pytest.approx(0.001)
    types = [e.type for e in rec.events]
    assert types[0] == "turn.started"
    assert "turn.llm_step" in types and "turn.delta" in types
    assert types[-1] == "turn.finished"
    deltas = [e for e in rec.events if e.type == "turn.delta"]
    assert "".join(d.text for d in deltas) == "ciao"


async def test_empty_response_retried_with_nudge() -> None:
    llm = ScriptedLLMPort(steps=[
        [ports.LLMStepDone(finish_reason="stop", tool_calls=())],       # vuoto
        [ports.LLMTextDelta(text="eccomi"),
         ports.LLMStepDone(finish_reason="stop", tool_calls=())],
    ])
    rec = RecordingEventPort()
    outcome = await _engine(llm, rec).run(_request(), cancel=asyncio.Event())
    assert outcome.content == "eccomi"
    assert outcome.steps == 2
    # il nudge è stato appeso ai messaggi del secondo step
    assert any("vuota" in str(m) for m in llm.calls[1]["messages"])


async def test_cancel_before_step_stops_clean() -> None:
    llm = ScriptedLLMPort(steps=[[
        ports.LLMTextDelta(text="mai"),
        ports.LLMStepDone(finish_reason="stop", tool_calls=()),
    ]])
    cancel = asyncio.Event()
    cancel.set()
    rec = RecordingEventPort()
    outcome = await _engine(llm, rec).run(_request(), cancel=cancel)
    assert outcome.finish_reason == "cancelled"
    assert rec.events[-1].type == "turn.finished"


async def test_non_retryable_failure_is_error() -> None:
    llm = ScriptedLLMPort(steps=[[
        ports.LLMFailure(message="400", status_code=400, retryable=False),
    ]])
    rec = RecordingEventPort()
    outcome = await _engine(llm, rec).run(_request(), cancel=asyncio.Event())
    assert outcome.finish_reason == "error"
    assert any(e.type == "turn.error" for e in rec.events)
    assert rec.events[-1].type == "turn.finished"
