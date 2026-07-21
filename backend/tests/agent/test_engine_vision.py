"""Consegna vision in-turn (T14): messaggio user multimodale dopo il batch tool.

Il seam di osservazione è lo ``ScriptedLLMPort``: ogni ``stream_step``
snapshotta le messages ricevute, quindi ciò che il modello "vede" allo step
successivo al batch è esattamente la working history con (o senza) il
messaggio vision iniettato.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.services.agent import events as ev
from backend.services.agent import ports
from backend.services.agent.models import ToolInvocation, TurnOutcome
from backend.tests.agent._engine_helpers import _engine, _final_step, _request, _tool_step
from backend.tests.agent.doubles import (
    InMemoryPersistence,
    MapExecutionPort,
    RecordingEventPort,
    ScriptedLLMPort,
)

_PNG = ports.ToolImage(mime="image/png", base64_data="QUJD")
_DATA_URL = "data:image/png;base64,QUJD"


def _image_output(*images: ports.ToolImage, content: str = "[immagine: shot.png]",
                  ) -> ports.ToolExecutionOutput:
    return ports.ToolExecutionOutput(
        ok=True, content=content, images=tuple(images), content_type="image/png",
    )


async def _run_vision(
    *,
    llm_steps: list[list[ports.LLMEvent]],
    exec_tools: dict[str, ports.ToolExecutionOutput],
    vision: bool = True,
    vision_enabled: bool = True,
    vision_max_images: int = 4,
) -> tuple[InMemoryPersistence, TurnOutcome, ScriptedLLMPort, RecordingEventPort]:
    """Esegue un turno coi double, esponendo LLMPort ed EventPort per le asserzioni."""
    persistence = InMemoryPersistence()
    rec = RecordingEventPort()
    llm = ScriptedLLMPort(steps=llm_steps, vision=vision)
    exec_port = MapExecutionPort(tools=exec_tools)
    engine = _engine(
        llm=llm, events=rec, persistence=persistence, execution=exec_port,
        verdicts=None, confirm=ports.InteractionOutcome.APPROVED,
        vision_enabled=vision_enabled, vision_max_images=vision_max_images,
    )
    outcome = await engine.run(_request(), cancel=asyncio.Event())
    return persistence, outcome, llm, rec


def _multimodal_user_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        m for m in messages
        if m.get("role") == "user" and isinstance(m.get("content"), list)
    ]


def _image_parts(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        part
        for m in _multimodal_user_messages(messages)
        for part in m["content"]
        if part.get("type") == "image_url"
    ]


async def test_vision_injects_user_message_after_batch() -> None:
    calls = (ToolInvocation(call_id="c1", name="screenshot", args={}, raw_args="{}"),)
    _, outcome, llm, _ = await _run_vision(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"screenshot": _image_output(_PNG)},
    )
    assert outcome.finish_reason == "stop"
    step2 = llm.calls[1]["messages"]
    last = step2[-1]
    assert last["role"] == "user"
    parts = last["content"]
    assert isinstance(parts, list)
    assert parts[0]["type"] == "text"
    assert "screenshot" in parts[0]["text"]
    assert parts[1] == {"type": "image_url", "image_url": {"url": _DATA_URL}}
    # Il messaggio vision viene DOPO il tool message placeholder del batch.
    assert step2[-2]["role"] == "tool"
    assert step2[-2]["content"] == "[immagine: shot.png]"


async def test_vision_skipped_when_model_not_capable() -> None:
    calls = (ToolInvocation(call_id="c1", name="screenshot", args={}, raw_args="{}"),)
    _, _, llm, _ = await _run_vision(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"screenshot": _image_output(_PNG)},
        vision=False,
    )
    step2 = llm.calls[1]["messages"]
    assert step2[-1]["role"] == "tool"           # solo il placeholder
    assert _multimodal_user_messages(step2) == []


async def test_vision_skipped_when_disabled() -> None:
    calls = (ToolInvocation(call_id="c1", name="screenshot", args={}, raw_args="{}"),)
    _, _, llm, _ = await _run_vision(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"screenshot": _image_output(_PNG)},
        vision_enabled=False,
    )
    step2 = llm.calls[1]["messages"]
    assert step2[-1]["role"] == "tool"
    assert _multimodal_user_messages(step2) == []


async def test_vision_caps_images_per_turn() -> None:
    # Batch 1: 6 immagini (3+3) con cap 4 -> 4 image parts + nota cap.
    # Batch 2: contatore esaurito -> nessuna nuova iniezione.
    step1 = (
        ToolInvocation(call_id="a", name="shot_a", args={}, raw_args="{}"),
        ToolInvocation(call_id="b", name="shot_b", args={}, raw_args="{}"),
    )
    step2 = (ToolInvocation(call_id="c", name="shot_c", args={}, raw_args="{}"),)
    _, outcome, llm, _ = await _run_vision(
        llm_steps=[_tool_step(step1), _tool_step(step2), _final_step()],
        exec_tools={
            "shot_a": _image_output(_PNG, _PNG, _PNG),
            "shot_b": _image_output(_PNG, _PNG, _PNG),
            "shot_c": _image_output(_PNG),
        },
        vision_max_images=4,
    )
    assert outcome.finish_reason == "stop"
    after_first = llm.calls[1]["messages"]
    injected = _multimodal_user_messages(after_first)
    assert len(injected) == 1
    assert len(_image_parts(after_first)) == 4
    text = injected[0]["content"][0]["text"]
    assert "shot_a" in text and "shot_b" in text
    assert "cap" in text                          # nota sul cap raggiunto
    # Dopo il secondo batch: nessun nuovo messaggio vision, totale invariato.
    after_second = llm.calls[2]["messages"]
    assert len(_multimodal_user_messages(after_second)) == 1
    assert len(_image_parts(after_second)) == 4
    assert after_second[-1]["role"] == "tool"     # shot_c resta solo placeholder


async def test_vision_cap_partial_remainder_across_batches() -> None:
    # Batch 1: 3/4 del cap consumate (nessuna nota). Batch 2: 2 immagini con
    # residuo 1 -> 1 iniettata + nota di troncamento.
    step1 = (ToolInvocation(call_id="a", name="shot_a", args={}, raw_args="{}"),)
    step2 = (ToolInvocation(call_id="b", name="shot_b", args={}, raw_args="{}"),)
    _, outcome, llm, _ = await _run_vision(
        llm_steps=[_tool_step(step1), _tool_step(step2), _final_step()],
        exec_tools={
            "shot_a": _image_output(_PNG, _PNG, _PNG),
            "shot_b": _image_output(_PNG, _PNG),
        },
        vision_max_images=4,
    )
    assert outcome.finish_reason == "stop"
    after_first = llm.calls[1]["messages"]
    first = _multimodal_user_messages(after_first)
    assert len(first) == 1
    assert len(_image_parts(after_first)) == 3
    assert "cap" not in first[0]["content"][0]["text"]     # sotto il cap: nessuna nota
    after_second = llm.calls[2]["messages"]
    injected = _multimodal_user_messages(after_second)
    assert len(injected) == 2
    assert len(_image_parts(after_second)) == 4            # 3 + il residuo di 1
    second_text = injected[1]["content"][0]["text"]
    assert "shot_b" in second_text
    assert "cap" in second_text                            # nota di troncamento


async def test_vision_message_not_persisted() -> None:
    calls = (ToolInvocation(call_id="c1", name="screenshot", args={}, raw_args="{}"),)
    persistence, _, llm, rec = await _run_vision(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"screenshot": _image_output(_PNG)},
    )
    # Il messaggio vision esiste nella working history in memoria...
    assert _multimodal_user_messages(llm.calls[1]["messages"])
    # ...ma la persistenza vede SOLO il placeholder testuale: mai il base64.
    assert [r["content"] for r in persistence.tool_results] == ["[immagine: shot.png]"]
    persisted = (
        [r["content"] for r in persistence.tool_results]
        + [s["content"] for s in persistence.assistant_steps]
        + [f["content"] for f in persistence.final_messages]
    )
    assert all(isinstance(c, str) for c in persisted)
    assert all(_DATA_URL not in c and "QUJD" not in c for c in persisted)
    # Guardia larga: NIENTE nello stato della persistenza porta il base64
    # (copre anche sink futuri aggiunti a InMemoryPersistence).
    assert "QUJD" not in repr(vars(persistence))
    # E nessun AgentEvent emesso porta il base64: la ToolResultEvent
    # trasporta il placeholder, non il data URL.
    tool_results = [e for e in rec.events if isinstance(e, ev.ToolResultEvent)]
    assert [e.result for e in tool_results] == ["[immagine: shot.png]"]
    assert all("QUJD" not in repr(e) for e in rec.events)
