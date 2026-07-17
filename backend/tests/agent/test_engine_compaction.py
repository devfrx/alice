"""Compaction tra gli step: trigger, archiviazione, fail-open."""

from backend.services.agent import ports
from backend.services.agent.models import ToolInvocation
from backend.tests.agent._engine_helpers import (
    _final_step,
    _run_with,
    _run_with_compaction,
    _tool_step,
)
from backend.tests.agent.doubles import RaisingContextPort


async def test_compaction_triggers_between_steps_and_rewrites_history() -> None:
    calls = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec, llm = await _run_with_compaction(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        compaction=ports.CompactionResult(
            performed=True, summary_text="RIASSUNTO", tokens_before=30000,
            tokens_after=500, kept_messages=(),
            archived_message_ids=("m1", "m2")),
    )
    phases = [e.phase for e in rec.events if e.type == "context.compaction"]
    assert phases == ["started", "done"]
    assert persistence.archived == [("RIASSUNTO", ["m1", "m2"])]
    # il secondo step LLM vede il summary in testa alla working history, nella
    # STESSA forma con cui la piattaforma lo persiste e ricarica (role=assistant
    # + prefisso "[Context summary of N earlier messages]:", vedi
    # adapters/db.py::archive_compacted e _assembly._filter_history_for_llm) —
    # così la history in-turn e quella ricostruita al turno dopo coincidono.
    assert llm.calls[1]["messages"][0] == {
        "role": "assistant",
        "content": "[Context summary of 2 earlier messages]:\nRIASSUNTO",
    }


async def test_compaction_failure_is_fail_open() -> None:
    calls = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec, llm = await _run_with_compaction(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        compaction=ports.CompactionResult(
            performed=False, summary_text=None, tokens_before=30000,
            tokens_after=30000, error="boom"),
    )
    phases = [e.phase for e in rec.events if e.type == "context.compaction"]
    assert phases == ["started", "failed"]
    assert outcome.finish_reason == "stop"     # il turno completa comunque


async def test_context_usage_emitted_each_extra_step() -> None:
    calls = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    assert any(e.type == "context.usage" for e in rec.events)


async def test_compaction_raise_is_fail_open() -> None:
    """Quando compact() solleva, il turno completa comunque (fail-open)."""
    calls = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec, llm = await _run_with_compaction(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        context_port=RaisingContextPort(),
    )
    phases = [e.phase for e in rec.events if e.type == "context.compaction"]
    assert phases == ["started", "failed"]
    # Verifica che l'errore sia presente nell'evento failed
    failed_events = [
        e for e in rec.events
        if e.type == "context.compaction" and e.phase == "failed"
    ]
    assert failed_events, "Dovrebbe esserci un evento compaction con phase=failed"
    assert "compaction esplosa" in failed_events[0].error
    # Il turno completa comunque (fail-open)
    assert outcome.finish_reason == "stop"
