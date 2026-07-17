"""Compaction tra gli step: trigger, archiviazione, fail-open."""

import asyncio
from typing import Any

from backend.core.config import LLMConfig
from backend.services.agent import ports
from backend.services.agent.adapters.context import ContextManagerAdapter
from backend.services.agent.models import ToolInvocation, TurnRequest, TurnSource
from backend.services.context_manager import ContextManager
from backend.tests.agent._engine_helpers import (
    _engine,
    _final_step,
    _run_with,
    _run_with_compaction,
    _tool_step,
)
from backend.tests.agent.doubles import (
    InMemoryPersistence,
    MapExecutionPort,
    RaisingContextPort,
    RecordingEventPort,
    ScriptedLLMPort,
)


async def test_compaction_triggers_between_steps_and_rewrites_history() -> None:
    calls = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    # ``kept_messages`` rappresentativo del contratto reale dell'adapter:
    # ContextManager.compress ritorna GIÀ la history nuova completa
    # (system + summary_msg piattaforma + coda tenuta) — il motore la adotta
    # così com'è, senza aggiungere entry sintetiche.
    kept = (
        {"role": "system", "content": "SYS"},
        {
            "role": "assistant",
            "content": "[Context summary of 2 earlier messages]:\nRIASSUNTO",
        },
        {"role": "user", "content": "resto"},
    )
    persistence, outcome, rec, llm = await _run_with_compaction(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        compaction=ports.CompactionResult(
            performed=True, summary_text="RIASSUNTO", tokens_before=30000,
            tokens_after=500, kept_messages=kept,
            archived_message_ids=("m1", "m2")),
    )
    phases = [e.phase for e in rec.events if e.type == "context.compaction"]
    assert phases == ["started", "done"]
    assert persistence.archived == [("RIASSUNTO", ["m1", "m2"])]
    # il secondo step LLM vede ESATTAMENTE kept_messages come working history:
    # nessuna entry prepesa (una seconda copia duplicherebbe il summary).
    assert llm.calls[1]["messages"] == list(kept)


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


class _SummaryLLMStub:
    """Stub del solo metodo che ``ContextManager.compress`` usa dell'LLM."""

    async def complete_nonstreaming(
        self, messages: list[dict[str, Any]], max_tokens: int = 512,
    ) -> str:
        """Ritorna un riassunto fisso (nessuna chiamata LLM reale)."""
        return "RIASSUNTO"


async def test_real_adapter_compaction_has_exactly_one_summary() -> None:
    """Via ``ContextManagerAdapter`` + ``ContextManager`` REALI: nessun duplicato.

    Il summary con prefisso piattaforma lo costruisce ``compress`` (dentro
    ``kept_messages``); il motore NON deve aggiungerne una seconda copia, e il
    conteggio nel prefisso deve essere lo ``split_index`` reale (i messaggi di
    conversazione archiviati), non ``len(archived_message_ids)`` (vuoto in
    produzione: i dict di history non hanno chiave ``id``).
    """
    config = LLMConfig()
    adapter = ContextManagerAdapter(
        ContextManager(config), _SummaryLLMStub(), config,  # type: ignore[arg-type]
    )
    calls = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    persistence = InMemoryPersistence()
    rec = RecordingEventPort()
    llm = ScriptedLLMPort(steps=[_tool_step(calls), _final_step()])
    exec_port = MapExecutionPort(
        tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    engine = _engine(
        llm=llm, events=rec, persistence=persistence, execution=exec_port,
        verdicts=None, confirm=ports.InteractionOutcome.APPROVED, context=adapter,
    )
    # Finestra piccola: available <= context_compression_reserve ad ogni check,
    # quindi should_compact scatta (via should_compress reale) prima dello
    # step 2. A quel punto la working history è: 3 messaggi di history +
    # assistant(tool_calls) + tool result = 5 conversazionali; compress reale
    # ne tiene 2 (target budget negativo) -> split_index = 3.
    request = TurnRequest(
        conversation_id="c1", system_prompt="sp",
        history=[
            {"role": "user", "content": "primo messaggio"},
            {"role": "assistant", "content": "prima risposta"},
            {"role": "user", "content": "ciao"},
        ],
        tools=[], source=TurnSource.CHAT, max_steps=8, context_window=1000,
        resolved_max_tokens=None, client_ip=None,
        version_group_id=None, version_index=None, max_tool_calls=None,
    )
    outcome = await engine.run(request, cancel=asyncio.Event())
    assert outcome.finish_reason == "stop"
    phases = [e.phase for e in rec.events if e.type == "context.compaction"]
    assert phases == ["started", "done"]
    step2_messages = llm.calls[1]["messages"]
    summaries = [
        m for m in step2_messages
        if str(m.get("content", "")).startswith("[Context summary of ")
    ]
    # ESATTAMENTE un summary (niente duplicazione motore+compress) e col
    # conteggio dello split_index reale.
    assert len(summaries) == 1
    assert summaries[0] == {
        "role": "assistant",
        "content": "[Context summary of 3 earlier messages]:\nRIASSUNTO",
    }
    # Debito censito (pre-esistente M1): i dict di history non portano "id",
    # quindi gli archived_message_ids passati alla persistenza sono vuoti.
    assert persistence.archived == [("RIASSUNTO", [])]
