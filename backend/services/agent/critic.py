"""Critic service: judges step outputs and emits a :class:`Verdict`.

The critic is intentionally simple — it makes one LLM call (with
``response_format={"type":"json_object"}`` and ``temperature=0``) and
parses a JSON object.  Parse / call failures degrade according to
``cfg.fail_open``: ``True`` returns ``OK`` (don't block the user),
``False`` returns ``RETRY`` (give the orchestrator another shot).

Reasons surfaced via :class:`Verdict.reason` are always plain Italian
sentences for end users; the underlying technical detail (parse
exception, raw output, ...) is logged via :mod:`loguru` for debugging.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Final

from loguru import logger
from pydantic import ValidationError

from .models import CriticConfig, Plan, Step, Verdict, VerdictAction
from .prompts import CRITIC_SYSTEM_PROMPT
from ._degeneration import detect_degeneration
from ._runner import collect_text

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_RESPONSE_FORMAT: Final[dict[str, Any]] = {"type": "json_object"}


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
        finish_reason: str | None = None,
    ) -> Verdict:
        """Return a :class:`Verdict` for the just-executed step.

        See module docstring for the contract.  Never raises — every
        failure mode is mapped to a :class:`Verdict` so the orchestrator
        keeps a single happy path.
        """
        # --- Local detector (no LLM round-trip on obvious degenerations).
        if getattr(self._cfg, "degeneration_detector_enabled", True):
            verdict = detect_degeneration(output, finish_reason)
            if verdict is not None:
                return verdict

        user_prompt = self._build_user_prompt(step, output, plan, retries_used)
        messages = [{"role": "user", "content": user_prompt}]

        try:
            raw = await collect_text(
                self._llm,
                messages,
                system_prompt=CRITIC_SYSTEM_PROMPT,
                max_output_tokens=self._cfg.max_output_tokens,
                cancel_event=cancel_event,
                response_format=_RESPONSE_FORMAT,
                temperature=self._cfg.temperature,
            )
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            logger.warning("Critic LLM call failed: {}", exc)
            return self._fallback(detail=f"LLM call failed: {exc}")

        verdict = self._try_parse(raw)
        if verdict is not None:
            verdict.source = "llm"
            return verdict
        logger.warning("Critic JSON parse failed; raw={!r}", raw)
        return self._fallback(detail="parse error")

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

    def _fallback(self, *, detail: str) -> Verdict:
        """Return the configured fail-open / fail-closed default verdict.

        Reasons are intentionally short, generic, and italian — they may
        bubble up to the user via ``agent.critic_invoked``.  The
        ``detail`` argument is only logged.
        """
        logger.debug("Critic fallback ({}): fail_open={}", detail, self._cfg.fail_open)
        if self._cfg.fail_open:
            return Verdict(
                action=VerdictAction.OK,
                reason="Verifica completata.",
                source="fallback",
            )
        return Verdict(
            action=VerdictAction.RETRY,
            reason="Verifica non riuscita, riprovo lo step.",
            source="fallback",
        )


__all__ = ["CriticService"]
