"""Task complexity classifier service.

Wraps a small LLM call that returns one of the four ``TaskComplexity``
strings.  Results are cached in-memory (TTL) keyed by the user content
+ ``has_tools`` flag, since classification of an identical user turn
within the TTL window is deterministic enough to reuse.

Failure mode (LLM error or unrecognized output) is **fail-safe**:
returns ``MULTI_STEP`` when tools are available (preserving today's
full tool-loop path) and ``TRIVIAL`` otherwise.  See §3.8/v1-d of the
``agent_loop_plan.md``.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from loguru import logger

from .models import ClassifierConfig, TaskComplexity
from .prompts import CLASSIFIER_SYSTEM_PROMPT
from ._runner import collect_text

_VALID_TOKENS: dict[str, TaskComplexity] = {c.value: c for c in TaskComplexity}


class _TTLCache:
    """Tiny in-memory TTL cache.

    Avoids the optional ``cachetools`` dependency.  Sufficient for the
    classifier's single-process workload.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = max(0, ttl_seconds)
        self._store: dict[str, tuple[float, TaskComplexity]] = {}

    def get(self, key: str) -> TaskComplexity | None:
        """Return the cached value if still fresh, else ``None``."""
        if self._ttl == 0:
            return None
        item = self._store.get(key)
        if item is None:
            return None
        ts, value = item
        if (time.monotonic() - ts) > self._ttl:
            self._store.pop(key, None)
            return None
        return value

    def put(self, key: str, value: TaskComplexity) -> None:
        """Insert a value with the current timestamp."""
        if self._ttl == 0:
            return
        self._store[key] = (time.monotonic(), value)


class ClassifierService:
    """Classify a user turn into one of the four ``TaskComplexity`` levels."""

    def __init__(self, llm: Any, cfg: ClassifierConfig) -> None:
        """Bind the underlying LLM service and the classifier config.

        Args:
            llm: An ``LLMService``-compatible object (must expose
                ``async def chat(...)`` yielding event dicts).
            cfg: Tunables (TTL, max tokens, temperature, ...).
        """
        self._llm = llm
        self._cfg = cfg
        self._cache = _TTLCache(cfg.cache_ttl_seconds)

    async def classify(
        self,
        user_content: str,
        *,
        has_tools: bool,
        cancel_event: asyncio.Event | None = None,
    ) -> TaskComplexity:
        """Return the inferred complexity of ``user_content``.

        Args:
            user_content: Raw user message.
            has_tools: Whether tools are wired in for this turn.  Used
                both as part of the cache key and as the fallback hint.
            cancel_event: Optional cooperative cancellation event.

        Returns:
            One of the four :class:`TaskComplexity` values.  Never raises.
        """
        key = self._cache_key(user_content, has_tools=has_tools)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        try:
            messages = [{"role": "user", "content": user_content}]
            text = await collect_text(
                self._llm,
                messages,
                system_prompt=CLASSIFIER_SYSTEM_PROMPT,
                max_output_tokens=self._cfg.max_output_tokens,
                cancel_event=cancel_event,
            )
        except Exception as exc:  # noqa: BLE001 — fail-safe by design
            logger.warning("Classifier LLM call failed: {}", exc)
            return self._fallback(has_tools)

        parsed = self._parse(text)
        if parsed is None:
            logger.debug("Classifier produced unrecognized output: {!r}", text)
            return self._fallback(has_tools)

        self._cache.put(key, parsed)
        return parsed

    @staticmethod
    def _cache_key(user_content: str, *, has_tools: bool) -> str:
        """Stable hash of (user_content + has_tools) for cache lookup."""
        digest = hashlib.sha256(user_content.encode("utf-8")).hexdigest()
        return f"{digest}:{int(has_tools)}"

    @staticmethod
    def _parse(text: str) -> TaskComplexity | None:
        """Map the model output to a :class:`TaskComplexity`, or ``None``.

        Tolerant of leading/trailing whitespace, surrounding quotes, and
        case differences.  Anything else returns ``None`` so the caller
        can fall back.
        """
        if not text:
            return None
        cleaned = text.strip().strip("'\"`").lower().split()[0]
        cleaned = cleaned.rstrip(".,;:")
        return _VALID_TOKENS.get(cleaned)

    @staticmethod
    def _fallback(has_tools: bool) -> TaskComplexity:
        """Choose the safe default when classification fails.

        With tools available we prefer ``MULTI_STEP`` (full loop), which
        matches today's behaviour; otherwise ``TRIVIAL`` (direct reply).
        """
        return TaskComplexity.MULTI_STEP if has_tools else TaskComplexity.TRIVIAL


__all__ = ["ClassifierService"]
