"""AL\\CE — Judge LLM per i criteri qualitativi (misura secondaria)."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from loguru import logger

from backend.evals.models import JudgeSpec, JudgeVerdict

_JUDGE_SYSTEM = (
    "Sei un giudice imparziale di risposte di un assistente AI. Valuti UN "
    "criterio alla volta con un punteggio intero 0-10 (0 = per niente, 10 = "
    "perfettamente). Rispondi SOLO con JSON: "
    '{"score": <0-10>, "reason": "<una frase>"}'
)

_JUDGE_USER = (
    "Task assegnato all'assistente:\n{task}\n\n"
    "Risposta finale dell'assistente:\n{response}\n\n"
    "Criterio da valutare: {criterion}"
)


class _JudgeLLM(Protocol):
    """Sottoinsieme del servizio LLM usato dal judge."""

    async def complete_nonstreaming(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 512,
    ) -> str: ...


def _parse_verdict(raw: str, criterion: str) -> JudgeVerdict:
    """Parsa la risposta del judge: JSON, poi regex, poi 0 esplicito.

    Il ``json.loads`` puo' riuscire su un payload che non e' un ``dict``
    (es. la stringa ``"15"`` e' JSON valido e diventa l'int ``15``): in tal
    caso ``data.get`` solleverebbe ``AttributeError``, quindi la eccettiamo
    esplicitamente insieme agli errori di parsing/casting per far cadere
    anche questo caso nel fallback a regex.
    """
    try:
        data = json.loads(raw.strip())
        score = int(data.get("score", 0))
        reason = str(data.get("reason", ""))
        return JudgeVerdict(
            criterion=criterion,
            score=max(0, min(10, score)),
            reason=reason,
        )
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        pass
    match = re.search(r"\b(\d{1,2})\b", raw)
    if match:
        score = max(0, min(10, int(match.group(1))))
        return JudgeVerdict(criterion=criterion, score=score, reason=raw.strip()[:200])
    return JudgeVerdict(
        criterion=criterion,
        score=0,
        reason=f"verdetto non parsabile: {raw.strip()[:120]}",
    )


async def judge_response(
    llm: _JudgeLLM,
    *,
    spec: JudgeSpec,
    task_prompt: str,
    response: str,
) -> list[JudgeVerdict]:
    """Valuta *response* contro ogni criterio di *spec* (una chiamata l'uno).

    Args:
        llm: Servizio LLM attivo (stesso modello pinnato del run).
        spec: I criteri qualitativi dello scenario.
        task_prompt: Il prompt originale del task (contesto per il giudizio).
        response: La risposta finale dell'assistente.

    Returns:
        Un verdetto per criterio; gli errori LLM diventano verdetti score=0.
    """
    verdicts: list[JudgeVerdict] = []
    for criterion in spec.criteria:
        messages = [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {
                "role": "user",
                "content": _JUDGE_USER.format(
                    task=task_prompt,
                    response=response or "(vuota)",
                    criterion=criterion,
                ),
            },
        ]
        try:
            raw = await llm.complete_nonstreaming(messages, max_tokens=200)
        except Exception as exc:
            logger.warning("Judge LLM fallito sul criterio {!r}: {}", criterion, exc)
            verdicts.append(
                JudgeVerdict(criterion=criterion, score=0, reason=f"errore judge: {exc}"),
            )
            continue
        verdicts.append(_parse_verdict(raw, criterion))
    return verdicts
