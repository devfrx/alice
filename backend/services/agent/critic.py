"""Critic service: judges step outputs and emits a :class:`Verdict`.

The critic is intentionally simple — it makes one LLM call and parses
a JSON object.  Parse failures degrade according to ``cfg.fail_open``:
``True`` returns ``OK`` (don't block the user), ``False`` returns
``RETRY`` (give the orchestrator another shot).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from loguru import logger
from pydantic import ValidationError

from .models import CriticConfig, Plan, Step, Verdict, VerdictAction
from .prompts import CRITIC_SYSTEM_PROMPT
from ._runner import collect_text

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class CriticService:
    """Evaluate a step's output and decide how the orchestrator proceeds."""

    def __init__(self, llm: Any, cfg: CriticConfig) -> None:
        """Bind the underlying LLM service and the critic config.

        Args:
            llm: An ``LLMService``-compatible object.
            cfg: Tunables (max tokens, temperature, fail_open).
        """
        self._llm = llm
        self._cfg = cfg

    async def evaluate(
        self,
        *,
        step: Step,
        output: str,
        plan: Plan,
        retries_used: int,
        cancel_event: asyncio.Event | None = None,
    ) -> Verdict:
        """Return a :class:`Verdict` for the just-executed step.

        Args:
            step: The step whose output we're judging.
            output: Plain-text result of the step (typically the
                assistant message produced by the inner executor).
            plan: The full plan (provides context about what comes next).
            retries_used: How many times this step has already been
                retried — surfaced to the prompt so the model can avoid
                infinite retry loops.
            cancel_event: Optional cooperative cancellation event.

        Returns:
            A validated :class:`Verdict`.  On parse error returns the
            safe default dictated by ``cfg.fail_open``.
        """
        user_prompt = self._build_user_prompt(step, output, plan, retries_used)
        messages = [{"role": "user", "content": user_prompt}]

        try:
            raw = await collect_text(
                self._llm,
                messages,
                system_prompt=CRITIC_SYSTEM_PROMPT,
                max_output_tokens=self._cfg.max_output_tokens,
                cancel_event=cancel_event,
            )
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            logger.warning("Critic LLM call failed: {}", exc)
            return self._fallback("LLM call failed")

        verdict = self._try_parse(raw)
        if verdict is not None:
            return verdict
        logger.debug("Critic JSON parse failed; raw={!r}", raw)
        return self._fallback("parse error")

    @staticmethod
    def _build_user_prompt(
        step: Step,
        output: str,
        plan: Plan,
        retries_used: int,
    ) -> str:
        """Assemble the user-side prompt fed to the critic LLM."""
        return (
            f"Obiettivo del piano: {plan.goal}\n"
            f"Step #{step.index}: {step.description}\n"
            f"Risultato atteso: {step.expected_outcome}\n"
            f"Retry usati per questo step: {retries_used}\n"
            f"Output ottenuto:\n{output}\n\n"
            "Valuta e rispondi con il JSON del verdict."
        )

    @staticmethod
    def _try_parse(raw: str) -> Verdict | None:
        """Best-effort parse of the LLM output into a :class:`Verdict`."""
        if not raw:
            return None
        candidate = raw.strip()
        try:
            return Verdict.model_validate_json(candidate)
        except ValidationError:
            pass
        except ValueError:
            pass
        match = _JSON_OBJECT_RE.search(candidate)
        if match is None:
            return None
        try:
            data = json.loads(match.group(0))
            return Verdict.model_validate(data)
        except (ValueError, ValidationError):
            return None

    def _fallback(self, reason: str) -> Verdict:
        """Return the configured fail-open / fail-closed default verdict."""
        if self._cfg.fail_open:
            return Verdict(
                action=VerdictAction.OK,
                reason=f"fail-open: {reason}",
            )
        return Verdict(
            action=VerdictAction.RETRY,
            reason=f"fail-closed: {reason}",
        )


__all__ = ["CriticService"]
