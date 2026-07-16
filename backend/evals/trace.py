"""AL\\CE — Sintesi e persistenza della trace di un turno eval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.evals.models import TraceSummary


def summarize_trace(
    events: list[dict[str, Any]],
    *,
    finish_reason: str,
    cost: float,
) -> TraceSummary:
    """Riduce i frame registrati dal sink a una :class:`TraceSummary`.

    Args:
        events: Frame emessi dal turno (vocabolario canonico + legacy).
        finish_reason: ``TurnResult.finish_reason`` del turno.
        cost: ``TurnResult.cost`` del turno (crediti provider).

    Returns:
        La sintesi numerica della trace.
    """
    steps = 0
    tool_calls: list[str] = []
    input_tokens = 0
    output_tokens = 0
    for event in events:
        etype = event.get("type")
        if etype == "turn.llm_step":
            steps += 1
        elif etype == "tool.call":
            tool_calls.append(str(event.get("tool_name", "")))
        elif etype == "turn.usage":
            input_tokens = int(event.get("input_tokens", 0) or 0)
            output_tokens = int(event.get("output_tokens", 0) or 0)
    return TraceSummary(
        steps=steps,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
    )


def write_trace_jsonl(
    path: Path,
    events: list[dict[str, Any]],
    *,
    final: dict[str, Any],
) -> None:
    """Scrive la trace completa in JSONL (un frame per riga + riga finale).

    Args:
        path: File di destinazione (la directory viene creata).
        events: Frame registrati dal sink, in ordine di emissione.
        final: Payload conclusivo (risposta, esiti) scritto come ultima
            riga con ``type: "eval.final"``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        fh.write(
            json.dumps(
                {"type": "eval.final", **final},
                ensure_ascii=False,
                default=str,
            )
            + "\n",
        )
