"""Compaction tra gli step: trigger, archiviazione, fail-open, vision-safety."""

import asyncio
import json
from typing import Any

from backend.core.config import LLMConfig
from backend.services.agent import ports
from backend.services.agent.adapters.context import (
    _IMAGE_STRIP_MARKER,
    ContextManagerAdapter,
    _strip_image_parts,
)
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
    """Stub del solo metodo che ``ContextManager.compress`` usa dell'LLM.

    Registra i ``messages`` ricevuti per verificare cosa raggiunge il
    summarizer (vision-safety della compaction).
    """

    def __init__(self) -> None:
        self.received: list[list[dict[str, Any]]] = []

    async def complete_nonstreaming(
        self, messages: list[dict[str, Any]], max_tokens: int = 512,
    ) -> str:
        """Ritorna un riassunto fisso (nessuna chiamata LLM reale)."""
        self.received.append(messages)
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


def _real_adapter() -> tuple[ContextManagerAdapter, _SummaryLLMStub]:
    """Adapter reale + stub summarizer che registra i messaggi ricevuti."""
    config = LLMConfig()
    stub = _SummaryLLMStub()
    adapter = ContextManagerAdapter(
        ContextManager(config), stub, config,  # type: ignore[arg-type]
    )
    return adapter, stub


def _image_part(b64: str) -> dict[str, Any]:
    """Costruisce un image part OpenAI-shape con data URL base64."""
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64}"},
    }


def test_estimate_tokens_handles_multimodal_content() -> None:
    """Pin: la stima usa il costo flat per immagine, non len(base64).

    ``ContextManager.estimate_message_tokens`` gestisce già il content-list
    multimodale (~765 token flat per image part): con un base64 da ~1 MiB la
    stima deve restare di 3 ordini di grandezza sotto la tokenizzazione del
    payload (~260k token via tiktoken, ~260k via char/4).
    """
    adapter, _ = _real_adapter()
    big_b64 = "A" * 1_048_576  # ~1 MiB
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "guarda questa immagine"},
                _image_part(big_b64),
            ],
        },
    ]
    tokens = adapter.estimate_tokens(messages)
    assert tokens < 50_000


async def test_compact_strips_image_parts() -> None:
    """Le immagini non sopravvivono alla compaction (né summarizer né kept).

    Un messaggio vision nel segmento archiviato non deve raggiungere il
    summarizer come base64; uno nel segmento tenuto non deve sopravvivere
    in ``kept_messages``. Al posto di ogni immagine c'è il marker e il
    messaggio stripped è content-stringa.
    """
    adapter, stub = _real_adapter()
    b64_archived = "OLDIMAGEB64/" * 200
    b64_kept = "NEWIMAGEB64/" * 200
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "sp"},
        {
            "role": "user",
            "content": [{"type": "text", "text": "guarda"}, _image_part(b64_archived)],
        },
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "altro"},
        {
            "role": "user",
            "content": [{"type": "text", "text": "e questa"}, _image_part(b64_kept)],
        },
        {"role": "assistant", "content": "fine"},
    ]
    # Finestra piccola: target budget negativo -> compress reale tiene gli
    # ultimi 2 conversazionali (il vision "kept") e archivia i primi 3
    # (il vision "archived" finisce nell'input del summarizer).
    result = await adapter.compact(messages=messages, context_window=1000)

    assert result.performed is True, result.error
    summarizer_payload = json.dumps(stub.received)
    assert "OLDIMAGEB64" not in summarizer_payload
    assert "NEWIMAGEB64" not in summarizer_payload
    assert _IMAGE_STRIP_MARKER in summarizer_payload

    kept_payload = json.dumps(list(result.kept_messages))
    assert "OLDIMAGEB64" not in kept_payload
    assert "NEWIMAGEB64" not in kept_payload
    kept_stripped = [
        m for m in result.kept_messages
        if _IMAGE_STRIP_MARKER in str(m.get("content"))
    ]
    assert kept_stripped, "il vision tenuto deve portare il marker"
    assert all(isinstance(m["content"], str) for m in kept_stripped)
    # Gli input NON sono stati mutati: i content-list originali sono intatti.
    assert isinstance(messages[1]["content"], list)
    assert isinstance(messages[4]["content"], list)


def test_strip_image_parts_preserves_plain_messages() -> None:
    """Content stringa (o None) -> STESSI oggetti, lista di pari lunghezza."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "sp"},
        {"role": "user", "content": "ciao"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
    ]
    out = _strip_image_parts(messages)
    assert len(out) == len(messages)
    assert all(a is b for a, b in zip(out, messages, strict=True))


def test_strip_image_parts_rebuilds_multimodal() -> None:
    """text+image+text -> content stringa coi due testi e il marker in mezzo."""
    part_img = _image_part("AAAA")
    original: dict[str, Any] = {
        "role": "user",
        "content": [
            {"type": "text", "text": "prima"},
            part_img,
            {"type": "text", "text": "dopo"},
        ],
        "id": "m9",
    }
    out = _strip_image_parts([original])
    assert out[0] == {
        "role": "user",
        "content": f"prima\n{_IMAGE_STRIP_MARKER}\ndopo",
        "id": "m9",
    }
    # L'input NON è stato mutato (nuovo dict, part originali intatti).
    assert out[0] is not original
    assert isinstance(original["content"], list)
    assert original["content"][1] is part_img
