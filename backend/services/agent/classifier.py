"""Three-tier task complexity classifier (heuristic -> LLM -> safe default)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any, Final

from loguru import logger

from .models import ClassificationResult, ClassifierConfig, TaskComplexity
from .prompts import CLASSIFIER_SYSTEM_PROMPT
from ._runner import collect_text

_VALID_TOKENS: dict[str, TaskComplexity] = {c.value: c for c in TaskComplexity}

_PATTERN_A: Final[re.Pattern[str]] = re.compile(
    r"(ricerc\w*|cerc\w*|trov\w*|search|find|fetch)"
    r".{0,200}?"
    r"(report|grafic\w*|chart|analisi|tabell\w*|visualizz\w*|"
    r"salv\w*|email|file|scheda|riepilog\w*|riassunt\w*)",
    re.IGNORECASE | re.DOTALL,
)

_ACTION_VERB: Final[str] = (
    r"(?:cerc|trov|crea|salv|invia|mand|legg|apr|"
    r"genera|scriv|riassum|analizz|mostr|calcol|"
    r"search|find|create|save|send|read|open|generate|write|summari[sz]e|analy[sz]e)"
)
_PATTERN_B: Final[re.Pattern[str]] = re.compile(
    rf"\b{_ACTION_VERB}\w*\b"
    r".{0,150}?"
    r"(?:\s(?:e|poi|quindi|dopo|infine|then|after that|and then)\s)"
    r".{0,150}?"
    rf"\b{_ACTION_VERB}\w*\b",
    re.IGNORECASE | re.DOTALL,
)

_PATTERN_C_ACTION: Final[re.Pattern[str]] = re.compile(
    rf"\b{_ACTION_VERB}\w*\b", re.IGNORECASE,
)
_PATTERN_C_CONJ: Final[re.Pattern[str]] = re.compile(
    r"\b(e|poi|quindi|dopo|infine|then|after that|and then)\b",
    re.IGNORECASE,
)
_PATTERN_C_MIN_LEN: Final[int] = 200


def _heuristic_forces_multi_step(text: str) -> bool:
    """Return True when one of the deterministic patterns matches."""
    if not text:
        return False
    if _PATTERN_A.search(text):
        return True
    if _PATTERN_B.search(text):
        return True
    if (
        len(text) > _PATTERN_C_MIN_LEN
        and _PATTERN_C_ACTION.search(text)
        and _PATTERN_C_CONJ.search(text)
    ):
        return True
    return False


class _TTLCache:
    """Tiny in-memory TTL cache used by :class:`ClassifierService`."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = max(0, ttl_seconds)
        self._store: dict[str, tuple[float, TaskComplexity]] = {}

    def get(self, key: str) -> TaskComplexity | None:
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
        if self._ttl == 0:
            return
        self._store[key] = (time.monotonic(), value)


_RESPONSE_FORMAT: Final[dict[str, Any]] = {"type": "json_object"}
_JSON_OBJECT_RE: Final[re.Pattern[str]] = re.compile(r"\{.*\}", re.DOTALL)


class ClassifierService:
    """Classify a user turn into a :class:`TaskComplexity`."""

    def __init__(self, llm: Any, cfg: ClassifierConfig) -> None:
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
        """Legacy convenience wrapper returning the bare enum."""
        result = await self.classify_detailed(
            user_content, has_tools=has_tools, cancel_event=cancel_event,
        )
        return result.complexity

    async def classify_detailed(
        self,
        user_content: str,
        *,
        has_tools: bool,
        cancel_event: asyncio.Event | None = None,
    ) -> ClassificationResult:
        """Three-tier classification with provenance metadata."""
        if _heuristic_forces_multi_step(user_content):
            logger.debug("Classifier heuristic forced MULTI_STEP")
            return ClassificationResult(
                complexity=TaskComplexity.MULTI_STEP,
                source="heuristic",
                confidence=1.0,
            )

        key = self._cache_key(user_content, has_tools=has_tools)
        cached = self._cache.get(key)
        if cached is not None:
            return ClassificationResult(complexity=cached, source="llm")

        try:
            messages = [{"role": "user", "content": user_content}]
            text = await collect_text(
                self._llm,
                messages,
                system_prompt=CLASSIFIER_SYSTEM_PROMPT,
                max_output_tokens=self._cfg.max_output_tokens,
                cancel_event=cancel_event,
                response_format=_RESPONSE_FORMAT,
                temperature=self._cfg.temperature,
            )
        except Exception as exc:
            logger.warning("Classifier LLM call failed: {}", exc)
            return self._safe_default()

        parsed = self._parse(text)
        if parsed is None:
            logger.debug("Classifier produced unrecognized output: {!r}", text)
            return self._safe_default()

        self._cache.put(key, parsed)
        return ClassificationResult(complexity=parsed, source="llm")

    @staticmethod
    def _cache_key(user_content: str, *, has_tools: bool) -> str:
        digest = hashlib.sha256(user_content.encode("utf-8")).hexdigest()
        return f"{digest}:{int(has_tools)}"

    @staticmethod
    def _parse(text: str) -> TaskComplexity | None:
        """Map the model output to a TaskComplexity, or None."""
        if not text:
            return None
        cleaned = text.strip()
        match = _JSON_OBJECT_RE.search(cleaned)
        if match is not None:
            try:
                payload = json.loads(match.group(0))
                token = str(payload.get("complexity", "")).strip().lower()
                if token in _VALID_TOKENS:
                    return _VALID_TOKENS[token]
            except (ValueError, AttributeError):
                pass
        bare = cleaned.strip("'\"`").lower().split()[0] if cleaned.split() else ""
        bare = bare.rstrip(".,;:")
        return _VALID_TOKENS.get(bare)

    @staticmethod
    def _safe_default() -> ClassificationResult:
        """Safety > speed: prefer MULTI_STEP on any uncertainty."""
        return ClassificationResult(
            complexity=TaskComplexity.MULTI_STEP,
            source="default",
            confidence=0.0,
        )


__all__ = ["ClassifierService"]
