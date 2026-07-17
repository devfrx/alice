"""Loop multi-step: budget step, disconnect via porte, voice trim, costo."""

from backend.services.agent import ports
from backend.services.agent.models import StopReason, ToolInvocation
from backend.tests.agent._engine_helpers import _final_step, _run_with, _tool_step


async def test_max_steps_stops_loop_with_warning() -> None:
    # LLM che chiede sempre tool: con max_steps=2 il loop si ferma
    call_step = _tool_step((ToolInvocation(call_id="c", name="echo",
                                           args={}, raw_args="{}"),))
    persistence, outcome, rec = await _run_with(
        llm_steps=[call_step, call_step, _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        max_steps=2,
    )
    assert outcome.stop_reason is StopReason.MAX_STEPS
    assert outcome.finish_reason == "stop"
    assert outcome.steps == 2
    assert any(e.type == "turn.warning" for e in rec.events)


async def test_disconnect_from_interaction_port_stops_after_persist() -> None:
    calls = (ToolInvocation(call_id="c1", name="write", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"write": ports.ToolExecutionOutput(ok=True, content="ok")},
        verdicts={"write": ports.GateVerdict(action=ports.GateAction.CONFIRM,
                                             outcome="needs_confirmation")},
        confirm=ports.InteractionOutcome.DISCONNECTED,
    )
    assert outcome.finish_reason == "disconnected"
    # la tool response del call annullato esiste comunque (§6.1.1)
    assert any(r["call_id"] == "c1" for r in persistence.tool_results)
    assert rec.events[-1].type == "turn.finished"


async def test_voice_trim_caps_tool_calls() -> None:
    one = ToolInvocation(call_id="c1", name="echo", args={"n": 1}, raw_args="{}")
    two = ToolInvocation(call_id="c2", name="echo", args={"n": 2}, raw_args="{}")
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step((one, two)), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        max_tool_calls=1,
    )
    trimmed = [r for r in persistence.tool_results if r["call_id"] == "c2"]
    assert trimmed and "budget" in trimmed[0]["content"].lower()
    assert outcome.tool_calls == 1        # solo la eseguita conta


async def test_cost_and_usage_accumulate_across_steps() -> None:
    step1 = [ports.LLMUsage(input_tokens=100, output_tokens=10, cost=0.01),
             ports.LLMStepDone(finish_reason="tool_calls", tool_calls=(
                 ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),))]
    step2 = [ports.LLMTextDelta(text="fine"),
             ports.LLMUsage(input_tokens=200, output_tokens=20, cost=0.02),
             ports.LLMStepDone(finish_reason="stop", tool_calls=())]
    persistence, outcome, rec = await _run_with(
        llm_steps=[step1, step2],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    assert outcome.input_tokens == 300 and outcome.output_tokens == 30
    assert round(outcome.cost, 4) == 0.03
    finished = rec.events[-1]
    assert finished.type == "turn.finished" and round(finished.cost, 4) == 0.03
    usage_events = [e for e in rec.events if e.type == "turn.usage"]
    assert len(usage_events) == 2         # uno per step (semantica attuale)
