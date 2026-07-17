"""Step con tool: invariante tool-response-per-ogni-call_id in OGNI ramo."""

import asyncio

from backend.services.agent import events as ev
from backend.services.agent import ports
from backend.services.agent.models import ToolInvocation, ToolMeta
from backend.tests.agent._engine_helpers import (
    _final_step,
    _run_with,
    _run_with_port,
    _tool_step,
)


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
    # Ordine pinnato (invariante engine): requested < resolved < tool.result
    # per la STESSA call.
    req_i = next(i for i, e in enumerate(rec.events)
                 if isinstance(e, ev.InteractionRequestedEvent) and e.call_id == "c1")
    res_i = next(i for i, e in enumerate(rec.events)
                 if isinstance(e, ev.InteractionResolvedEvent) and e.call_id == "c1")
    result_i = next(i for i, e in enumerate(rec.events)
                    if isinstance(e, ev.ToolResultEvent) and e.call_id == "c1")
    assert req_i < res_i < result_i
    assert persistence.audits and persistence.audits[0]["interaction"] == "approved"
    assert any(r["call_id"] == "c1" and r["status"] == "ok"
               for r in persistence.tool_results)


async def test_confirm_event_payload_is_complete() -> None:
    """Il requested del confirm porta il payload COMPLETO (carry #4, spec §4):
    args/risk_level/description/reasoning/allow_remember, non più minimale; il
    resolved porta il call_id per la correlazione FE."""
    calls = (ToolInvocation(call_id="c1", name="write",
                            args={"path": "x.txt"}, raw_args="{}"),)
    verdict = ports.GateVerdict(
        action=ports.GateAction.CONFIRM, outcome="needs_confirmation",
        reason="fuori scope", risk_level="dangerous", description="scrive un file",
    )
    _persistence, _outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"write": ports.ToolExecutionOutput(ok=True, content="ok")},
        verdicts={"write": verdict},
        confirm=ports.InteractionOutcome.APPROVED,
    )
    requested = [e for e in rec.events if isinstance(e, ev.InteractionRequestedEvent)]
    resolved = [e for e in rec.events if isinstance(e, ev.InteractionResolvedEvent)]
    assert len(requested) == 1 and len(resolved) == 1
    req = requested[0]
    assert req.kind == "confirm" and req.call_id == "c1" and req.tool_name == "write"
    assert req.payload == {
        "args": {"path": "x.txt"},
        "risk_level": "dangerous",
        "description": "scrive un file",
        "reasoning": "fuori scope",
        "allow_remember": True,
    }
    res = resolved[0]
    assert res.kind == "confirm" and res.call_id == "c1" and res.outcome == "approved"
    # Ordine pinnato (invariante engine): requested < resolved < tool.result.
    assert (rec.events.index(req) < rec.events.index(res)
            < next(i for i, e in enumerate(rec.events)
                   if isinstance(e, ev.ToolResultEvent) and e.call_id == "c1"))


async def test_ask_user_emits_interaction_events() -> None:
    """ask_user emette interaction.requested/resolved con payload completo
    (questions) e outcome 'answered' sul successo (carry #4)."""
    questions = [{"id": "q1", "text": "Quale?", "type": "radio", "options": ["a", "b"]}]
    calls = (ToolInvocation(call_id="c1", name="ask_user",
                            args={"questions": questions}, raw_args="{}"),)
    _persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={},
        meta={"ask_user": ToolMeta(exists=True, interactive="ask_user")},
        ask_user_result=ports.ToolExecutionOutput(ok=True, content="a"),
    )
    requested = [e for e in rec.events if isinstance(e, ev.InteractionRequestedEvent)]
    resolved = [e for e in rec.events if isinstance(e, ev.InteractionResolvedEvent)]
    assert len(requested) == 1 and len(resolved) == 1
    req = requested[0]
    assert req.kind == "ask_user" and req.call_id == "c1" and req.tool_name == "ask_user"
    assert req.payload == {"questions": questions}
    res = resolved[0]
    assert res.kind == "ask_user" and res.call_id == "c1" and res.outcome == "answered"
    # Ordine pinnato (invariante engine): requested < resolved < tool.result.
    assert (rec.events.index(req) < rec.events.index(res)
            < next(i for i, e in enumerate(rec.events)
                   if isinstance(e, ev.ToolResultEvent) and e.call_id == "c1"))
    assert outcome.finish_reason == "stop"


async def test_client_tool_emits_interaction_events_on_success() -> None:
    """client tool emette requested/resolved con payload={args} e outcome
    'executed' sul successo (carry #4)."""
    calls = (ToolInvocation(call_id="c1", name="ui_pick",
                            args={"k": "v"}, raw_args="{}"),)
    _persistence, _outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={},
        meta={"ui_pick": ToolMeta(exists=True, client_executed=True)},
        client_result=ports.ToolExecutionOutput(ok=True, content="scelto"),
    )
    requested = [e for e in rec.events if isinstance(e, ev.InteractionRequestedEvent)]
    resolved = [e for e in rec.events if isinstance(e, ev.InteractionResolvedEvent)]
    assert len(requested) == 1 and len(resolved) == 1
    req = requested[0]
    assert req.kind == "client" and req.call_id == "c1" and req.tool_name == "ui_pick"
    assert req.payload == {"args": {"k": "v"}}
    res = resolved[0]
    assert res.kind == "client" and res.call_id == "c1" and res.outcome == "executed"
    # Ordine pinnato (invariante engine): requested < resolved < tool.result.
    assert (rec.events.index(req) < rec.events.index(res)
            < next(i for i, e in enumerate(rec.events)
                   if isinstance(e, ev.ToolResultEvent) and e.call_id == "c1"))


async def test_client_tool_failure_emits_failed_outcome() -> None:
    """client tool con ok=False → resolved outcome 'failed' e tool response error."""
    calls = (ToolInvocation(call_id="c1", name="ui_pick", args={}, raw_args="{}"),)
    persistence, _outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={},
        meta={"ui_pick": ToolMeta(exists=True, client_executed=True)},
        client_result=ports.ToolExecutionOutput(ok=False, content="ko", error="boom"),
    )
    resolved = [e for e in rec.events if isinstance(e, ev.InteractionResolvedEvent)]
    assert len(resolved) == 1 and resolved[0].outcome == "failed"
    saved = [r for r in persistence.tool_results if r["call_id"] == "c1"]
    assert saved and saved[0]["status"] == "error"


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


async def test_artifact_registered_after_checkpoint_of_the_batch() -> None:
    # fix review T13: register_artifacts deve avvenire DOPO il checkpoint che
    # committa la riga Message del tool result, non prima (niente FK orfane).
    calls = (ToolInvocation(call_id="c1", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    tool_result_index = persistence.order.index(("tool_result", "c1"))
    artifact_index = persistence.order.index(("artifact", "c1"))
    checkpoint_index = next(
        i for i, entry in enumerate(persistence.order)
        if entry == ("checkpoint", "") and i > tool_result_index
    )
    assert tool_result_index < checkpoint_index < artifact_index


async def test_tool_exception_yields_error_result_not_crash() -> None:
    # §6.1.1: un'eccezione dell'ExecutionPort non affonda le altre call né
    # il turno — viene sintetizzata in una tool response di status "error".
    calls = (ToolInvocation(call_id="c1", name="boom", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"boom": ports.ToolExecutionOutput(ok=True, content="unreachable")},
        errors={"boom": RuntimeError("kaboom")},
    )
    saved = [r for r in persistence.tool_results if r["call_id"] == "c1"]
    assert saved and saved[0]["status"] == "error"
    assert "kaboom" in saved[0]["content"]
    assert outcome.finish_reason == "stop"


async def test_client_executed_tool_routes_through_interaction_port() -> None:
    # ramo "client-executed" di §6.1.1: la call non passa dall'ExecutionPort
    # server-side, ma dall'InteractionPort (run_client_tool).
    calls = (ToolInvocation(call_id="c1", name="ui_pick_file", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={},
        meta={"ui_pick_file": ToolMeta(exists=True, client_executed=True)},
        client_result=ports.ToolExecutionOutput(ok=True, content="scelto.txt"),
    )
    saved = [r for r in persistence.tool_results if r["call_id"] == "c1"]
    assert saved and saved[0]["status"] == "ok" and saved[0]["content"] == "scelto.txt"


async def test_deny_verdict_is_audited() -> None:
    # §6.7: ogni gate di negazione è auditato (interaction=None: nessun
    # round-trip di conferma, la negazione è decisa a monte).
    calls = (ToolInvocation(call_id="c1", name="rm", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"rm": ports.ToolExecutionOutput(ok=True, content="")},
        verdicts={"rm": ports.GateVerdict(action=ports.GateAction.DENY,
                                          outcome="plan_denied", reason="plan mode")},
    )
    assert persistence.audits and persistence.audits[0]["interaction"] is None
    assert persistence.audits[0]["verdict"].outcome == "plan_denied"


async def test_tool_progress_callback_emits_event() -> None:
    """La callback on_progress passata all'ExecutionPort produce ToolProgressEvent
    con turn_id/call_id/name reali e il payload del tool (carry #1)."""
    calls = (ToolInvocation(call_id="c_cad", name="cad", args={}, raw_args="{}"),)
    _persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"cad": ports.ToolExecutionOutput(ok=True, content="done")},
        progress={"cad": {"phase": "sampling", "percent": 50}},
    )
    progress_events = [e for e in rec.events if isinstance(e, ev.ToolProgressEvent)]
    assert len(progress_events) == 1
    pe = progress_events[0]
    assert pe.call_id == "c_cad"
    assert pe.name == "cad"
    assert pe.progress == {"phase": "sampling", "percent": 50}
    assert outcome.finish_reason == "stop"


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
