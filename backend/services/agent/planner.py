"""Plan generation service.

Produces a :class:`Plan` JSON document from a user goal and the list of
available tools.  When parsing fails (small models routinely emit
malformed JSON), falls back to a single-step plan so the orchestrator
can still proceed without aborting the user turn.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from loguru import logger
from pydantic import ValidationError

from .models import Plan, PlannerConfig, Step
from .prompts import PLANNER_SYSTEM_PROMPT
from ._runner import collect_text

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class PlannerService:
    """Translate a goal + available tools into a structured :class:`Plan`."""

    def __init__(self, llm: Any, cfg: PlannerConfig) -> None:
        """Bind the underlying LLM service and the planner config.

        Args:
            llm: An ``LLMService``-compatible object.
            cfg: Tunables (max tokens, temperature, JSON mode flag).
        """
        self._llm = llm
        self._cfg = cfg

    async def plan(
        self,
        *,
        goal: str,
        available_tools: list[dict[str, Any]],
        history_summary: str | None = None,
        remaining_goal: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Plan:
        """Generate a :class:`Plan` for the requested goal.

        Args:
            goal: High-level user intent.
            available_tools: Tool definitions as exposed by the registry
                (OpenAI function-calling format).
            history_summary: Optional short context block describing
                prior steps (used when re-planning).
            remaining_goal: Optional override that focuses the planner
                on what's left to do after a partial execution.
            cancel_event: Optional cooperative cancellation event.

        Returns:
            A validated :class:`Plan`.  On any failure returns a safe
            single-step fallback plan rather than raising.
        """
        effective_goal = remaining_goal or goal
        user_prompt = self._build_user_prompt(
            effective_goal,
            available_tools,
            history_summary,
        )
        messages = [{"role": "user", "content": user_prompt}]
        system_prompt = PLANNER_SYSTEM_PROMPT
        if self._cfg.require_json_object:
            system_prompt = (
                f"{system_prompt}\n\n"
                "IMPORTANTE: rispondi ESCLUSIVAMENTE con un oggetto JSON "
                "valido — niente testo, niente markdown, niente commenti."
            )

        try:
            raw = await collect_text(
                self._llm,
                messages,
                system_prompt=system_prompt,
                max_output_tokens=self._cfg.max_output_tokens,
                cancel_event=cancel_event,
            )
        except Exception as exc:  # noqa: BLE001 — fall back gracefully
            logger.warning("Planner LLM call failed: {}", exc)
            return self._fallback(effective_goal)

        plan = self._try_parse(raw)
        if plan is not None:
            return plan
        logger.debug("Planner JSON parse failed; returning single-step plan.")
        return self._fallback(effective_goal)

    @staticmethod
    def _build_user_prompt(
        goal: str,
        tools: list[dict[str, Any]],
        history_summary: str | None,
    ) -> str:
        """Assemble the user-side prompt fed to the LLM."""
        tool_names = [
            t.get("function", {}).get("name", "?")
            for t in tools
            if isinstance(t, dict)
        ]
        sections: list[str] = [f"Obiettivo: {goal}"]
        if tool_names:
            sections.append("Tool disponibili: " + ", ".join(tool_names))
        else:
            sections.append("Tool disponibili: (nessuno)")
        if history_summary:
            sections.append(f"Contesto precedente:\n{history_summary}")
        sections.append("Produci ora il piano JSON.")
        return "\n\n".join(sections)

    @staticmethod
    def _try_parse(raw: str) -> Plan | None:
        """Best-effort parse of the LLM output into a :class:`Plan`.

        Accepts both a raw JSON object and one wrapped in stray prose
        (extracts the first ``{...}`` substring).  Returns ``None`` on
        any failure so the caller can apply the fallback.
        """
        if not raw:
            return None
        candidate = raw.strip()
        try:
            return Plan.model_validate_json(candidate)
        except ValidationError:
            pass
        except ValueError:
            pass
        match = _JSON_OBJECT_RE.search(candidate)
        if match is None:
            return None
        try:
            data = json.loads(match.group(0))
            return Plan.model_validate(data)
        except (ValueError, ValidationError):
            return None

    @staticmethod
    def _fallback(goal: str) -> Plan:
        """Return a single-step plan that just restates the goal."""
        return Plan(
            goal=goal,
            steps=[
                Step(
                    index=0,
                    description=goal,
                    expected_outcome="risposta diretta",
                ),
            ],
        )


__all__ = ["PlannerService"]
