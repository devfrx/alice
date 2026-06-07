"""AL\\CE — Self-contained reflection (final-answer self-check) module.

This module bundles everything the optional reflection pass needs so the
model-driven turn path has **no** dependency on the removed structured
pipeline (``backend.services.agent``):

* a local, rule-based :func:`detect_degeneration` that flags *objective*
  signs of model collapse (repeated paragraphs, inline ``<tool_code>``
  markers, fake JSON tool-call literals, truncated output);
* :func:`collect_text`, a thin streaming-to-string adapter over
  ``LLMService.chat``;
* :data:`CRITIC_SYSTEM_PROMPT`, the Italian validator system prompt;
* :class:`ReflectionVerdict`, the slim verdict DTO; and
* :class:`ReflectionCritic`, which runs the detector first and falls back
  to a single LLM verification call.

The critic never raises: every failure maps to a :class:`ReflectionVerdict`.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Final, Protocol

from loguru import logger
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Degeneration detector (rule-based, no LLM round-trip)
# ---------------------------------------------------------------------------

MIN_REPEATED_PARAGRAPH_LEN: Final[int] = 80
"""Minimum paragraph length (after normalisation) to count as duplicate."""

_PARAGRAPH_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")
"""Splits content into paragraphs on blank lines."""

_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
"""Collapses any run of whitespace into a single space."""

_TOOL_CODE_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"<\s*/?\s*tool_code\b", re.IGNORECASE,
)
"""Matches ``<tool_code>`` / ``</tool_code>`` tags emitted as plain text."""

_INLINE_JSON_TOOL_CALL_RE: Final[re.Pattern[str]] = re.compile(
    r"```(?:json|tool_code)?\s*\n\s*\{[^}]*\"name\"\s*:\s*\"[a-z_][a-z0-9_]*\"",
    re.IGNORECASE,
)
"""Matches a fenced JSON block that *looks* like a tool call literal."""

_FINISH_REASON_LENGTH: Final[str] = "length"

_JSON_OBJECT_RE: Final[re.Pattern[str]] = re.compile(r"\{.*\}", re.DOTALL)
_RESPONSE_FORMAT: Final[dict[str, Any]] = {"type": "json_object"}


@dataclass(slots=True)
class ReflectionVerdict:
    """Outcome of a reflection pass over a completed turn.

    Attributes:
        ok: ``True`` when the output is acceptable, ``False`` otherwise.
        reason: Short, user-facing Italian justification.
        source: Where the verdict came from — ``"detector"`` (local
            rule-based detector), ``"llm"`` (verification model call) or
            ``"fallback"`` (degraded path on LLM/parse error).
    """

    ok: bool
    reason: str
    source: str  # "detector" | "llm" | "fallback"


def _normalise(paragraph: str) -> str:
    """Collapse whitespace inside ``paragraph`` for comparison purposes."""
    return _WS_RE.sub(" ", paragraph).strip()


def _has_repeated_paragraph(content: str) -> str | None:
    """Return the offending paragraph when one is duplicated, else ``None``.

    A paragraph counts as a duplication trigger only when its
    normalised form is at least :data:`MIN_REPEATED_PARAGRAPH_LEN`
    characters long *and* it appears two or more times.
    """
    if not content:
        return None
    paragraphs = (
        _normalise(p) for p in _PARAGRAPH_SPLIT_RE.split(content) if p.strip()
    )
    counts = Counter(p for p in paragraphs if len(p) >= MIN_REPEATED_PARAGRAPH_LEN)
    for paragraph, count in counts.items():
        if count >= 2:
            return paragraph
    return None


def detect_degeneration(
    content: str,
    finish_reason: str | None,
) -> ReflectionVerdict | None:
    """Return a non-OK verdict when ``content`` shows degeneration.

    The detector is deliberately conservative: only patterns the backend
    can NEVER produce on the happy path are flagged, so false positives
    stay close to zero.

    Args:
        content: The plain-text assistant output to inspect.
        finish_reason: The ``finish_reason`` reported by the underlying
            LLM call (``"stop"``, ``"length"``, ``"tool_calls"`` …).
            Pass ``None`` when unknown.

    Returns:
        A :class:`ReflectionVerdict` with ``ok=False`` and
        ``source="detector"`` when a degeneration pattern is detected;
        ``None`` otherwise — the caller should then proceed with the
        regular LLM-driven verification call.
    """
    # --- (d) truncated output --------------------------------------------
    if finish_reason == _FINISH_REASON_LENGTH:
        return ReflectionVerdict(
            ok=False,
            reason="output troncato per cap di token (finish_reason=length)",
            source="detector",
        )

    if not content:
        return None

    # --- (b) inline <tool_code> markers ----------------------------------
    if _TOOL_CODE_TAG_RE.search(content):
        return ReflectionVerdict(
            ok=False,
            reason=(
                "il modello ha tentato tool call inline non eseguibili "
                "(tag <tool_code> nel testo)"
            ),
            source="detector",
        )

    # --- (c) fake JSON tool call literal ---------------------------------
    if _INLINE_JSON_TOOL_CALL_RE.search(content):
        return ReflectionVerdict(
            ok=False,
            reason=(
                "il modello ha emesso un blocco JSON tool-call testuale "
                "anziché una vera function call strutturata"
            ),
            source="detector",
        )

    # --- (a) repeated paragraph ------------------------------------------
    duplicate = _has_repeated_paragraph(content)
    if duplicate is not None:
        snippet = duplicate[:60].rstrip() + ("…" if len(duplicate) > 60 else "")
        return ReflectionVerdict(
            ok=False,
            reason=f'paragrafo ripetuto rilevato ("{snippet}")',
            source="detector",
        )

    return None


# ---------------------------------------------------------------------------
# Streaming-to-string adapter
# ---------------------------------------------------------------------------


class _LLMLike(Protocol):
    """Minimal async-iterator chat protocol used by the reflection critic."""

    def chat(  # noqa: D401 — protocol stub
        self,
        messages: list[dict[str, Any]],
        tools: Any = None,
        cancel_event: asyncio.Event | None = None,
        *,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ) -> Any: ...


async def collect_text(
    llm: _LLMLike,
    messages: list[dict[str, Any]],
    *,
    system_prompt: str | None,
    max_output_tokens: int | None,
    cancel_event: asyncio.Event | None,
    response_format: dict[str, Any] | None = None,
    temperature: float | None = None,
) -> str:
    """Run an LLM chat call and return the concatenated assistant text.

    Consumes the async iterator yielded by ``llm.chat``, accumulates the
    ``token`` events' ``content`` into one string and stops as soon as a
    ``done`` event arrives.  Other event types (``thinking``, ``tool_call``,
    ``error``) are intentionally ignored — reflection only needs the
    visible answer.

    Args:
        llm: Object that exposes ``chat(...)``.
        messages: Full prompt list.
        system_prompt: Optional system prompt forwarded to ``llm.chat``.
        max_output_tokens: Cap on generated tokens.
        cancel_event: Optional cooperative cancellation event.
        response_format: Optional structured-output hint forwarded to
            ``llm.chat`` (e.g. ``{"type": "json_object"}``).  Backends
            that don't support it degrade gracefully.
        temperature: Optional per-call temperature override.

    Returns:
        The plain-text response.  Empty string if the stream produced no
        ``token`` events (caller decides how to handle that).
    """
    chunks: list[str] = []
    extra: dict[str, Any] = {}
    if response_format is not None:
        extra["response_format"] = response_format
    if temperature is not None:
        extra["temperature"] = temperature
    async for event in llm.chat(
        messages,
        tools=None,
        cancel_event=cancel_event,
        system_prompt=system_prompt,
        max_output_tokens=max_output_tokens,
        **extra,
    ):
        etype = event.get("type")
        if etype == "token":
            content = event.get("content")
            if content:
                chunks.append(content)
        elif etype == "done":
            break
    return "".join(chunks).strip()


# ---------------------------------------------------------------------------
# Validator system prompt
# ---------------------------------------------------------------------------

CRITIC_SYSTEM_PROMPT = dedent(
    """\
    Sei un validatore.  Decidi se l'output di uno step è accettabile.
    Rispondi SOLO con un oggetto JSON di questa forma:

      {"action": "ok|retry|replan|ask_user|abort",
       "reason": "<frase italiana breve, comprensibile a un utente>",
       "question": "<domanda solo se action=ask_user, altrimenti null>"}

    Valori ammessi per "action":
      - ok        -> risultato accettabile, prosegui
      - retry     -> errore transitorio, riprova lo stesso step
      - replan    -> il piano va rifatto da qui in poi
      - ask_user  -> serve chiarimento (compila "question")
      - abort     -> impossibile procedere

    Sii conservativo: se il risultato è plausibile rispondi "ok".
    Niente prosa fuori dal JSON, niente markdown.

    Esempio:
      {"action":"ok","reason":"Risultato coerente con la richiesta.","question":null}
    """
).strip()


# ---------------------------------------------------------------------------
# Reflection critic
# ---------------------------------------------------------------------------


class ReflectionCritic:
    """Evaluate a completed turn's output and return a slim verdict.

    Runs the local degeneration detector first (when enabled) and only
    falls back to a single LLM verification call when the detector is
    silent.  Never raises — every failure maps to a
    :class:`ReflectionVerdict`.
    """

    def __init__(self, llm: Any, cfg: Any) -> None:
        """Bind the LLM service and the reflection config.

        Args:
            llm: An ``LLMService``-compatible object exposing ``chat``.
            cfg: Tunables exposing ``max_output_tokens``, ``temperature``,
                ``fail_open`` and ``degeneration_detector_enabled``.
        """
        self._llm = llm
        self._cfg = cfg

    async def evaluate(
        self,
        *,
        output: str,
        finish_reason: str | None,
        goal: str,
        cancel_event: asyncio.Event | None = None,
    ) -> ReflectionVerdict:
        """Return a :class:`ReflectionVerdict` for a completed turn.

        Args:
            output: The assistant's final visible answer.
            finish_reason: ``finish_reason`` reported for the turn.
            goal: The originating user request (used for context).
            cancel_event: Optional cooperative cancellation event.

        Returns:
            A verdict whose ``ok`` flag tells the caller whether to flag
            the answer.  Never raises.
        """
        if getattr(self._cfg, "degeneration_detector_enabled", True):
            verdict = detect_degeneration(output, finish_reason)
            if verdict is not None:
                return verdict

        user_prompt = self._build_user_prompt(goal, output)
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
            logger.warning("Reflection LLM call failed: {}", exc)
            return self._fallback()

        parsed = self._try_parse(raw)
        if parsed is not None:
            action, reason = parsed
            return ReflectionVerdict(
                ok=action.lower() == "ok",
                reason=reason or "Verifica completata.",
                source="llm",
            )
        logger.warning("Reflection JSON parse failed; raw={!r}", raw)
        return self._fallback()

    @staticmethod
    def _build_user_prompt(goal: str, output: str) -> str:
        """Assemble the user-side prompt fed to the reflection LLM."""
        return (
            f"Obiettivo dell'utente: {goal}\n"
            f"Output ottenuto:\n{output}\n\n"
            "Valuta e rispondi con il JSON del verdict."
        )

    @staticmethod
    def _try_parse(raw: str) -> tuple[str, str] | None:
        """Best-effort parse of the LLM output into ``(action, reason)``."""
        if not raw:
            return None
        candidate = raw.strip()
        data: Any = None
        try:
            data = json.loads(candidate)
        except (ValueError, ValidationError):
            match = _JSON_OBJECT_RE.search(candidate)
            if match is None:
                return None
            try:
                data = json.loads(match.group(0))
            except (ValueError, ValidationError):
                return None
        if not isinstance(data, dict):
            return None
        action = data.get("action")
        if not isinstance(action, str) or not action:
            return None
        reason = data.get("reason")
        return action, reason if isinstance(reason, str) else ""

    def _fallback(self) -> ReflectionVerdict:
        """Return the configured fail-open / fail-closed default verdict."""
        fail_open = bool(getattr(self._cfg, "fail_open", True))
        return ReflectionVerdict(
            ok=fail_open,
            reason="Verifica completata." if fail_open else "Verifica non riuscita.",
            source="fallback",
        )


__all__ = [
    "MIN_REPEATED_PARAGRAPH_LEN",
    "CRITIC_SYSTEM_PROMPT",
    "ReflectionVerdict",
    "ReflectionCritic",
    "detect_degeneration",
    "collect_text",
]
