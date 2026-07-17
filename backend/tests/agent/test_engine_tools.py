"""Step con tool: invariante tool-response-per-ogni-call_id in OGNI ramo."""

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


def _request() -> TurnRequest:
    return TurnRequest(
        conversation_id="c1", system_prompt="sp",
        history=[{"role": "user", "content": "ciao"}], tools=[],
        source=TurnSource.CHAT, max_steps=8, context_window=32768,
        resolved_max_tokens=None, client_ip=None,
        version_group_id=None, version_index=None,
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
    outcome = await engine.run(_request(), cancel=cancel or asyncio.Event())
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
) -> tuple[InMemoryPersistence, TurnOutcome, RecordingEventPort]:
    """Come ``_run_with_port`` ma senza esporre l'ExecutionPort."""
    persistence, outcome, rec, _ = await _run_with_port(
        llm_steps=llm_steps, exec_tools=exec_tools, verdicts=verdicts,
        confirm=confirm, delays=delays, meta=meta, cancel=cancel,
    )
    return persistence, outcome, rec


async def test_every_call_id_gets_a_tool_result_across_branches() -> None:
    calls = (
        ToolInvocation(call_id="c_ok", name="echo", args={}, raw_args="{}"),
        ToolInvocation(call_id="c_bad", name="echo", args={}, raw_args="{x",
                       parse_error="argomenti non parsabili"),
        ToolInvocation(call_id="c_deny", name="rm", args={}, raw_args="{}"),
        ToolInvocation(call_id="c_missing", name="ghost", args={}, raw_args="{}"),
    )
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi"),
                    "rm": ports.ToolExecutionOutput(ok=True, content="")},
        verdicts={"rm": ports.GateVerdict(action=ports.GateAction.DENY,
                                          outcome="plan_denied", reason="plan mode")},
    )
    saved_ids = {r["call_id"] for r in persistence.tool_results}
    assert saved_ids == {"c_ok", "c_bad", "c_deny", "c_missing"}
    assert outcome.finish_reason == "stop" and outcome.content == "fatto"


async def test_assistant_step_persisted_before_results_and_checkpointed() -> None:
    calls = (ToolInvocation(call_id="c1", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    assert persistence.order[0] == ("assistant_step", "msg_1")
    assert persistence.checkpoints >= 2   # dopo assistant, dopo batch


async def test_duplicate_call_yields_synthetic_result_not_execution() -> None:
    same = ToolInvocation(call_id="c1", name="echo", args={"a": 1}, raw_args="{}")
    again = ToolInvocation(call_id="c2", name="echo", args={"a": 1}, raw_args="{}")
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step((same,)), _tool_step((again,)), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    dup = [r for r in persistence.tool_results if r["call_id"] == "c2"]
    assert dup and "duplicat" in dup[0]["content"].lower()


async def test_parallel_execution_of_greenlit_batch() -> None:
    calls = (
        ToolInvocation(call_id="a", name="slow_a", args={}, raw_args="{}"),
        ToolInvocation(call_id="b", name="slow_b", args={}, raw_args="{}"),
    )
    persistence, outcome, rec, exec_port = await _run_with_port(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"slow_a": ports.ToolExecutionOutput(ok=True, content=""),
                    "slow_b": ports.ToolExecutionOutput(ok=True, content="")},
        delays={"slow_a": 0.05, "slow_b": 0.05},
    )
    # se fossero seriali, il secondo inizierebbe dopo la fine del primo
    assert abs(exec_port.started_at["slow_a"] - exec_port.started_at["slow_b"]) < 0.04


async def test_confirmation_flow_events_and_audit() -> None:
    calls = (ToolInvocation(call_id="c1", name="write", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"write": ports.ToolExecutionOutput(ok=True, content="ok")},
        verdicts={"write": ports.GateVerdict(action=ports.GateAction.CONFIRM,
                                             outcome="needs_confirmation",
                                             risk_level="medium")},
        confirm=ports.InteractionOutcome.APPROVED,
    )
    types = [e.type for e in rec.events]
    assert "interaction.requested" in types and "interaction.resolved" in types
    assert persistence.audits and persistence.audits[0]["interaction"] == "approved"
    assert any(r["call_id"] == "c1" and r["status"] == "ok"
               for r in persistence.tool_results)


async def test_rejection_still_persists_tool_response() -> None:
    calls = (ToolInvocation(call_id="c1", name="write", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"write": ports.ToolExecutionOutput(ok=True, content="ok")},
        verdicts={"write": ports.GateVerdict(action=ports.GateAction.CONFIRM,
                                             outcome="needs_confirmation")},
        confirm=ports.InteractionOutcome.REJECTED,
    )
    saved = [r for r in persistence.tool_results if r["call_id"] == "c1"]
    assert saved and saved[0]["status"] == "rejected"


async def test_cancel_checked_only_after_persistence() -> None:
    # cancel scatta DURANTE l'esecuzione del tool: il result va comunque su DB
    calls = (ToolInvocation(call_id="c1", name="slow", args={}, raw_args="{}"),)
    cancel = asyncio.Event()

    async def _set_cancel_soon() -> None:
        await asyncio.sleep(0.01)
        cancel.set()

    task = asyncio.create_task(_set_cancel_soon())
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"slow": ports.ToolExecutionOutput(ok=True, content="ok")},
        delays={"slow": 0.05},
        cancel=cancel,
    )
    await task
    assert any(r["call_id"] == "c1" for r in persistence.tool_results)
    assert outcome.finish_reason == "cancelled"
