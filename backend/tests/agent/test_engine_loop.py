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


async def test_clean_final_answer_on_last_step_has_no_warning() -> None:
    persistence, outcome, rec = await _run_with(
        llm_steps=[_final_step()],
        exec_tools={},
        max_steps=1,
    )
    assert outcome.finish_reason == "stop"
    assert not [e for e in rec.events if e.type == "turn.warning"]


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


async def test_final_content_excludes_pre_tool_prose() -> None:
    # fix review T16: TurnOutcome.content = solo l'ultimo step, non il
    # cumulato — altrimenti la prosa pre-tool (già persistita come step
    # intermedio) verrebbe ri-scritta dal persist path come messaggio finale.
    step1 = [ports.LLMTextDelta(text="Sto per usare un tool. "),
             ports.LLMUsage(input_tokens=10, output_tokens=5, cost=0.001),
             ports.LLMStepDone(finish_reason="tool_calls", tool_calls=(
                 ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),))]
    step2 = [ports.LLMTextDelta(text="Ecco il risultato."),
             ports.LLMStepDone(finish_reason="stop", tool_calls=())]
    persistence, outcome, rec = await _run_with(
        llm_steps=[step1, step2],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    assert outcome.content == "Ecco il risultato."          # solo l'ultimo step
    # la prosa pre-tool e' persistita UNA volta, nello step intermedio
    assert persistence.assistant_steps[0]["content"] == "Sto per usare un tool. "
    # lo stream wire resta completo: tutti i delta emessi
    deltas = [e.text for e in rec.events if e.type == "turn.delta" and e.kind == "text"]
    assert "".join(deltas) == "Sto per usare un tool. Ecco il risultato."


# --- Matrice di salvataggio del messaggio finale (carry #2/#3) --------------
#   COMPLETED/LENGTH/MAX_STEPS -> content.strip() non vuoto OPPURE tool_calls == 0
#   CANCELLED                  -> content o thinking non vuoti
#   DISCONNECTED               -> content non vuoto (recovery message)
#   ERROR                      -> mai


async def test_finish_saves_final_message_on_completed() -> None:
    persistence, outcome, rec = await _run_with(
        llm_steps=[_final_step()],
        exec_tools={},
    )
    assert outcome.stop_reason is StopReason.COMPLETED
    assert len(persistence.final_messages) == 1
    assert persistence.final_messages[0]["content"] == "fatto"
    assert outcome.final_assistant_message_id == "final-msg-1"
    finished = rec.events[-1]
    assert finished.type == "turn.finished"
    assert finished.final_message_id == "final-msg-1"


async def test_finish_skips_save_on_tool_only_turn() -> None:
    # content vuoto (lo step con tool non produce prosa) + tool_calls>0:
    # MAX_STEPS con budget esaurito su tool call -> nessun messaggio finale.
    call = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(call)],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        max_steps=1,
    )
    assert outcome.stop_reason is StopReason.MAX_STEPS
    assert outcome.tool_calls == 1
    assert persistence.final_messages == []
    assert outcome.final_assistant_message_id is None
    finished = rec.events[-1]
    assert finished.type == "turn.finished" and finished.final_message_id is None


async def test_finish_saves_recovery_on_disconnect() -> None:
    # step con prosa parziale + tool call che il gate manda a conferma;
    # il client cade (DISCONNECTED) -> recovery message col parziale.
    step1 = [ports.LLMTextDelta(text="parziale"),
             ports.LLMStepDone(finish_reason="tool_calls", tool_calls=(
                 ToolInvocation(call_id="c1", name="write", args={}, raw_args="{}"),))]
    persistence, outcome, rec = await _run_with(
        llm_steps=[step1],
        exec_tools={"write": ports.ToolExecutionOutput(ok=True, content="ok")},
        verdicts={"write": ports.GateVerdict(action=ports.GateAction.CONFIRM,
                                             outcome="needs_confirmation")},
        confirm=ports.InteractionOutcome.DISCONNECTED,
    )
    assert outcome.finish_reason == "disconnected"
    assert len(persistence.final_messages) == 1
    assert persistence.final_messages[0]["content"] == "parziale"
    assert outcome.final_assistant_message_id == "final-msg-1"


async def test_finish_never_saves_on_error() -> None:
    persistence, outcome, rec = await _run_with(
        llm_steps=[[ports.LLMFailure(message="boom", status_code=None, retryable=False)]],
        exec_tools={},
    )
    assert outcome.finish_reason == "error"
    assert persistence.final_messages == []
    assert outcome.final_assistant_message_id is None


async def test_turn_finished_event_carries_ids_and_totals() -> None:
    step1 = [ports.LLMTextDelta(text="ciao"),
             ports.LLMUsage(input_tokens=100, output_tokens=10, cost=0.01),
             ports.LLMStepDone(finish_reason="stop", tool_calls=())]
    persistence, outcome, rec = await _run_with(
        llm_steps=[step1],
        exec_tools={},
        user_message_id="user-42",
        version_group_id="vg-7",
        version_index=3,
    )
    finished = rec.events[-1]
    assert finished.type == "turn.finished"
    # final_message_id = id ritornato dal save; ids/version dalla request;
    # token/cost = totali accumulati; emesso DOPO save+checkpoint.
    assert finished.final_message_id == "final-msg-1"
    assert finished.conversation_id == "c1"
    assert finished.user_message_id == "user-42"
    assert finished.version_group_id == "vg-7"
    assert finished.version_index == 3
    assert finished.input_tokens == 100 and finished.output_tokens == 10
    assert round(finished.cost, 4) == 0.01
    assert finished.tool_calls == 0
    # save + checkpoint accadono PRIMA dell'emissione di turn.finished
    assert ("final_message", "final-msg-1") in persistence.order
    assert persistence.order[-1] == ("checkpoint", "")


async def test_save_failure_degrades_to_error() -> None:
    persistence, outcome, rec = await _run_with(
        llm_steps=[_final_step()],
        exec_tools={},
        fail_final=True,
    )
    assert outcome.finish_reason == "error"
    assert outcome.final_assistant_message_id is None
    assert any(
        e.type == "turn.error" and e.code == "persist_failed" for e in rec.events
    )
    finished = rec.events[-1]
    assert finished.type == "turn.finished" and finished.finish_reason == "error"


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
