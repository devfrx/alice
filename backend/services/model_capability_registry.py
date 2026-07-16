"""AL\\CE — Dynamic per-model capability registry.

Single source of truth for what each model can do.  Populated from
LM Studio's ``/api/v1/models`` response, enriched by runtime learning
(e.g. whether a model accepts the ``reasoning`` parameter).

Profiles live in per-provider **namespaces** (``"local"`` for
LM Studio/Ollama, ``"openrouter"`` for the OpenRouter catalog) because
``org/model`` ids genuinely collide across providers — the same id can
name a locally-served checkpoint and a cloud model with different
capabilities and context windows.  Fuzzy id matching only exists to
bridge local naming conventions (Ollama tags vs LM Studio paths) and is
therefore confined to the ``"local"`` namespace; OpenRouter ids are a
canonical vocabulary and are always looked up verbatim.

Falls back to ``KNOWN_MODELS`` for Ollama or unknown local models.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal

from loguru import logger

from backend.core.config import KNOWN_MODELS

ModelNamespace = Literal["local", "openrouter"]
"""Provider family a profile belongs to.

``"local"`` covers LM Studio and Ollama (plus ``KNOWN_MODELS`` and
conservative defaults); ``"openrouter"`` covers the OpenRouter catalog.
"""


@dataclass
class ModelProfile:
    """Runtime capability profile for a single model.

    Attributes:
        model_id: Canonical model identifier (path or key).
        supports_thinking: Model can produce reasoning output
            (as reported by the LM Studio API — may be unreliable for
            fine-tuned/distilled models that have thinking in their weights).
        supports_vision: Model accepts image inputs.
        supports_tool_use: Model is trained for function calling.
        accepts_reasoning_param: Whether the LM Studio native API
            accepts ``"reasoning": "on"`` for this model.
            ``None`` = unknown (will try), ``True`` = confirmed,
            ``False`` = rejected (skip param to avoid wasted retry).
        emits_reasoning_natively: Model produces ``reasoning.delta`` SSE
            events even without the ``reasoning`` param (e.g. distilled
            reasoning models).  Detected at runtime from the first response.
            ``None`` = unknown, ``True`` = confirmed, ``False`` = confirmed not.
        context_length: Maximum context window size (0 = unknown).
        source: Where capabilities were detected from.
    """

    model_id: str
    supports_thinking: bool = False
    supports_vision: bool = False
    supports_tool_use: bool = False
    accepts_reasoning_param: bool | None = None
    emits_reasoning_natively: bool | None = None
    context_length: int = 0
    source: str = "unknown"

    @property
    def has_reasoning(self) -> bool:
        """True if the model reasons — either via API param or natively."""
        return bool(self.supports_thinking or self.emits_reasoning_natively)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for API responses and logging."""
        return {
            "model_id": self.model_id,
            "supports_thinking": self.supports_thinking,
            "supports_vision": self.supports_vision,
            "supports_tool_use": self.supports_tool_use,
            "accepts_reasoning_param": self.accepts_reasoning_param,
            "emits_reasoning_natively": self.emits_reasoning_natively,
            "has_reasoning": self.has_reasoning,
            "context_length": self.context_length,
            "source": self.source,
        }


class ModelCapabilityRegistry:
    """Dynamic per-model capability cache, namespaced by provider family.

    Populated from LM Studio v1 API responses (``"local"`` namespace)
    and the OpenRouter catalog (``"openrouter"`` namespace).  The LLM
    service queries this registry before every request to get the
    effective capabilities for the resolved model, eliminating static
    config flags and wasteful retry-on-error patterns.

    Thread-safe via asyncio locks; all public methods are sync or have
    async variants where needed.
    """

    def __init__(self) -> None:
        self._profiles: dict[ModelNamespace, dict[str, ModelProfile]] = {
            "local": {},
            "openrouter": {},
        }
        self._lock = asyncio.Lock()
        self._last_refresh: float = 0.0

    # ------------------------------------------------------------------
    # Bulk refresh from LM Studio v1 /api/v1/models response
    # ------------------------------------------------------------------

    async def refresh_from_api(self, models_data: list[dict[str, Any]]) -> int:
        """Update local profiles from the LM Studio ``/api/v1/models`` response.

        Each model entry is expected to have at least::

            {
                "key": "qwen/qwen3.5-9b",
                "path": "qwen/qwen3.5-9b",
                "capabilities": {"vision": false, "thinking": true},
                "max_context_length": 32768,
                ...
            }

        Args:
            models_data: The ``models`` list from the v1 API response.

        Returns:
            Number of profiles created or updated.
        """
        updated = 0
        async with self._lock:
            local = self._profiles["local"]
            for m in models_data:
                model_id = m.get("path") or m.get("key") or m.get("id", "")
                if not model_id:
                    continue

                caps = m.get("capabilities", {})
                old = local.get(model_id)

                profile = ModelProfile(
                    model_id=model_id,
                    supports_thinking=caps.get("thinking", False),
                    supports_vision=caps.get("vision", False),
                    supports_tool_use=caps.get(
                        "trained_for_tool_use", False,
                    ),
                    context_length=m.get("max_context_length", 0),
                    source="lmstudio_api",
                )

                # Preserve runtime-learned reasoning param knowledge.
                if old is not None and old.accepts_reasoning_param is not None:
                    profile.accepts_reasoning_param = (
                        old.accepts_reasoning_param
                    )

                local[model_id] = profile
                updated += 1

            self._last_refresh = time.monotonic()

        if updated:
            logger.debug(
                "Model registry refreshed: {} profile(s) updated", updated,
            )
        return updated

    async def refresh_from_openrouter(
        self, models_data: list[dict[str, Any]],
    ) -> int:
        """Update cloud profiles from the OpenRouter ``GET /v1/models`` response.

        Capabilities are derived from ``supported_parameters`` (tools,
        reasoning) and ``architecture.input_modalities`` (vision).
        Writes only to the ``"openrouter"`` namespace, so locally
        detected profiles are never touched even when ids collide.

        Args:
            models_data: The ``data`` list from the OpenRouter response.

        Returns:
            Number of profiles created or updated.
        """
        updated = 0
        async with self._lock:
            cloud = self._profiles["openrouter"]
            for m in models_data:
                model_id = m.get("id", "")
                if not model_id:
                    continue

                old = cloud.get(model_id)
                params = m.get("supported_parameters") or []
                arch = m.get("architecture") or {}
                modalities = arch.get("input_modalities") or []
                top = m.get("top_provider") or {}
                profile = ModelProfile(
                    model_id=model_id,
                    supports_thinking="reasoning" in params,
                    supports_vision="image" in modalities,
                    supports_tool_use="tools" in params,
                    context_length=int(
                        m.get("context_length")
                        or top.get("context_length")
                        or 0
                    ),
                    source="openrouter_api",
                )

                # Preserve runtime-learned knowledge (same policy as
                # refresh_from_api).
                if old is not None:
                    if old.accepts_reasoning_param is not None:
                        profile.accepts_reasoning_param = (
                            old.accepts_reasoning_param
                        )
                    if old.emits_reasoning_natively is not None:
                        profile.emits_reasoning_natively = (
                            old.emits_reasoning_natively
                        )

                cloud[model_id] = profile
                updated += 1
            self._last_refresh = time.monotonic()
        if updated:
            logger.debug(
                "Model registry refreshed from OpenRouter: {} profile(s)",
                updated,
            )
        return updated

    # ------------------------------------------------------------------
    # Single-model queries
    # ------------------------------------------------------------------

    def get_profile(
        self, model_id: str, *, namespace: ModelNamespace,
    ) -> ModelProfile:
        """Return the capability profile for a model.

        Lookup order:

        1. Exact match in the namespace's cached profiles.
        2. (``"local"`` only) Fuzzy match across local naming
           conventions — Ollama tags vs LM Studio paths.
        3. (``"local"`` only) ``KNOWN_MODELS`` fallback.
        4. A conservative default profile (no special capabilities).

        Fuzzy matching and ``KNOWN_MODELS`` never apply to the
        ``"openrouter"`` namespace: catalog ids are canonical and always
        queried verbatim, and a local model must never inherit a cloud
        profile (or vice versa) through a suffix collision such as
        ``qwen3:32b`` vs ``qwen/qwen3-32b``.

        Args:
            model_id: The model identifier (path, key, or Ollama tag).
            namespace: Provider family to look the model up in.

        Returns:
            A ``ModelProfile`` — never ``None``.
        """
        profiles = self._profiles[namespace]

        # 1. Exact cache hit
        profile = profiles.get(model_id)
        if profile is not None:
            return profile

        if namespace == "local":
            # 2. Fuzzy match: try without prefix/suffix variations
            for cached_id, cached_profile in profiles.items():
                if self._ids_match(model_id, cached_id):
                    return cached_profile

            # 3. KNOWN_MODELS fallback (Ollama-style keys, etc.)
            known = KNOWN_MODELS.get(model_id)
            if known is not None:
                profile = ModelProfile(
                    model_id=model_id,
                    supports_thinking=known.get("thinking", False),
                    supports_vision=known.get("vision", False),
                    source="known_models",
                )
                profiles[model_id] = profile
                return profile

        # 4. Conservative default
        logger.debug(
            "No capability data for model '{}' ({}) — using conservative "
            "defaults",
            model_id,
            namespace,
        )
        profile = ModelProfile(model_id=model_id, source="default")
        profiles[model_id] = profile
        return profile

    # ------------------------------------------------------------------
    # Runtime learning
    # ------------------------------------------------------------------

    def mark_reasoning_param_rejected(
        self, model_id: str, *, namespace: ModelNamespace,
    ) -> None:
        """Record that the model rejects ``"reasoning": "on"``.

        Called by the LLM service when LM Studio returns a 400 error
        for the reasoning parameter.  Future requests for this model
        will skip the param entirely.
        """
        profile = self.get_profile(model_id, namespace=namespace)
        if profile.accepts_reasoning_param is not False:
            profile.accepts_reasoning_param = False
            logger.info(
                "Model '{}' marked as rejecting reasoning param", model_id,
            )

    def mark_reasoning_param_accepted(
        self, model_id: str, *, namespace: ModelNamespace,
    ) -> None:
        """Record that the model accepts ``"reasoning": "on"``.

        Called when a request with the reasoning param succeeds.
        """
        profile = self.get_profile(model_id, namespace=namespace)
        if profile.accepts_reasoning_param is not True:
            profile.accepts_reasoning_param = True
            logger.debug(
                "Model '{}' confirmed accepting reasoning param", model_id,
            )

    def mark_emits_reasoning_natively(
        self, model_id: str, *, namespace: ModelNamespace,
    ) -> None:
        """Record that the model produces ``reasoning.delta`` events without
        the ``reasoning`` param being sent.

        This covers distilled/fine-tuned reasoning models that LM Studio
        reports as ``thinking: false`` in capabilities but have reasoning
        baked into their weights.  Detected at runtime from the first
        response that contains a ``reasoning.delta`` event.

        Called by the SSE parser in the LLM service.
        """
        profile = self.get_profile(model_id, namespace=namespace)
        if profile.emits_reasoning_natively is not True:
            profile.emits_reasoning_natively = True
            logger.info(
                "Model '{}' detected as emitting reasoning events natively "
                "(thinking baked into weights, not reported by LM Studio API)",
                model_id,
            )

    def mark_no_reasoning_natively(
        self, model_id: str, *, namespace: ModelNamespace,
    ) -> None:
        """Record that the model does NOT produce reasoning events natively.

        Called after a successful complete response with no ``reasoning.delta``
        events and no ``reasoning`` param was sent.  Confirms the model
        is a straightforward non-reasoning model.
        """
        profile = self.get_profile(model_id, namespace=namespace)
        if profile.emits_reasoning_natively is None:
            profile.emits_reasoning_natively = False
            logger.debug(
                "Model '{}' confirmed as non-reasoning (no native events)",
                model_id,
            )

    # ------------------------------------------------------------------
    # Bulk queries
    # ------------------------------------------------------------------

    def all_profiles(self) -> dict[str, ModelProfile]:
        """Return a flat, merged view of all cached profiles.

        On id collision across namespaces the local profile wins —
        matching the pre-namespace behaviour where a locally detected
        profile shadowed the catalog entry.  Used by display endpoints
        (``/models/capabilities``); provider-aware consumers should use
        :meth:`get_profile` with an explicit namespace instead.
        """
        return {**self._profiles["openrouter"], **self._profiles["local"]}

    @property
    def last_refresh(self) -> float:
        """Monotonic timestamp of the last bulk refresh."""
        return self._last_refresh

    def clear(self) -> None:
        """Remove all cached profiles in every namespace (useful for testing)."""
        for profiles in self._profiles.values():
            profiles.clear()
        self._last_refresh = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ids_match(query: str, cached: str) -> bool:
        """Fuzzy-match model IDs across local naming conventions.

        Handles differences between Ollama tags (``qwen3.5:9b``) and
        LM Studio paths (``qwen/qwen3.5-9b``).  Only ever applied within
        the ``"local"`` namespace — see :meth:`get_profile`.
        """
        q = query.lower().replace("/", "-").replace(":", "-").replace("_", "-")
        c = cached.lower().replace("/", "-").replace(":", "-").replace("_", "-")
        return q == c or q.endswith(c) or c.endswith(q)
