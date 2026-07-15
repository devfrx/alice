"""AL\\CE — Model resolution and per-model capability helpers.

Owns ``"auto"`` model resolution against LM Studio/Ollama (with a
short-lived cache) and the static/dynamic per-model capability lookups
(embedding detection, loaded-state detection, chat-model picking,
capability profile). Collaborates with
:class:`~backend.services.model_capability_registry.ModelCapabilityRegistry`
when available, falling back to static config flags otherwise.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from loguru import logger

from backend.core.config import LLMConfig
from backend.services.model_capability_registry import (
    ModelCapabilityRegistry,
    ModelProfile,
)


class ModelResolver:
    """Resolve the effective model ID and its capability profile.

    Args:
        config: The ``LLMConfig`` holding provider URL, model name, etc.
        model_registry: Dynamic per-model capability registry.  When
            provided, per-request capability checks (thinking, vision,
            reasoning param) use the registry instead of static config
            flags.  Passing ``None`` preserves the legacy behaviour.
        http: Shared ``httpx.AsyncClient`` owned by the ``LLMService``
            facade, used for the ``/v1/models`` probes.
    """

    def __init__(
        self,
        config: LLMConfig,
        model_registry: ModelCapabilityRegistry | None,
        http: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._model_registry = model_registry
        self._http = http
        self._is_ollama = config.provider == "ollama"
        self._is_openrouter = config.provider == "openrouter"
        # Cache for "auto" model resolution: (resolved_id, resolved_at_monotonic)
        self._auto_model_cache: tuple[str, float] | None = None
        self._auto_model_ttl: float = 300.0  # seconds
        self._auto_model_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Model resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_embedding_model(item: dict[str, Any]) -> bool:
        """Check if a model entry represents an embedding model.

        Checks both the explicit ``type`` field (LM Studio v1 API) and
        the model name/id/path for heuristic detection (OAI-compat API).
        """
        if item.get("type") == "embedding":
            return True
        # Heuristic: check if name/id/path contains "embed"
        for key in ("id", "name", "path"):
            val = item.get(key, "")
            if val and "embed" in val.lower():
                return True
        return False

    @staticmethod
    def _model_id(item: dict[str, Any]) -> str | None:
        """Return the canonical identifier for a model entry."""
        return item.get("path") or item.get("id") or item.get("name")

    @staticmethod
    def _is_loaded(item: dict[str, Any]) -> bool:
        """Check if a model entry is currently loaded into memory.

        The LM Studio v1 API marks a loaded model with a non-empty
        ``loaded_instances`` list.  The ``state`` field is unreliable —
        recent builds leave it blank for every model — so it is only
        consulted as a secondary signal.  OAI-compatible responses carry
        no load information at all, in which case this returns ``False``.
        """
        if item.get("loaded_instances"):
            return True
        return item.get("state") in ("loaded", "loading")

    def _pick_chat_model_id(
        self, items: list[dict[str, Any]],
    ) -> str | None:
        """Choose the best chat model id from non-embedding candidates.

        Preference order:

        1. The configured model (when not ``"auto"``) if it is present in
           the candidate list — honours an explicit user choice.
        2. A model trained for tool use.  AL\\CE is fundamentally a
           tool-using agent, and this also skips single-purpose models
           such as OCR/vision-only checkpoints that would otherwise be
           picked just because they sort first.
        3. The first candidate, as a last resort.

        Args:
            items: Non-embedding model entries from the models API.

        Returns:
            The chosen model identifier, or ``None`` if *items* is empty.
        """
        if not items:
            return None

        configured = self._config.model
        if configured and configured != "auto":
            for item in items:
                if self._model_id(item) == configured:
                    return configured

        for item in items:
            caps = item.get("capabilities") or {}
            if caps.get("trained_for_tool_use"):
                model_id = self._model_id(item)
                if model_id:
                    return model_id

        return self._model_id(items[0])

    # ------------------------------------------------------------------
    # Per-model capability helpers
    # ------------------------------------------------------------------

    def get_model_profile(self, model_id: str) -> ModelProfile:
        """Return the capability profile for a specific model.

        Uses the dynamic registry when available; falls back to
        a profile built from static config flags.
        """
        if self._model_registry is not None:
            return self._model_registry.get_profile(model_id)
        # Legacy fallback: build profile from static config flags.
        return ModelProfile(
            model_id=model_id,
            supports_thinking=self._config.supports_thinking,
            supports_vision=self._config.supports_vision,
            source="config",
        )

    @property
    def supports_vision(self) -> bool:
        """Whether the active model supports multimodal (vision) input.

        Checks the registry first (if available), falling back to the
        static config flag.  Uses the cached auto-resolved model when
        available to avoid an async call.
        """
        if self._is_openrouter and self._model_registry is not None:
            return self._model_registry.get_profile(
                self._config.openrouter_model or "openrouter/auto",
            ).supports_vision
        if self._model_registry is not None and self._auto_model_cache:
            profile = self._model_registry.get_profile(
                self._auto_model_cache[0],
            )
            return profile.supports_vision
        return self._config.supports_vision

    async def resolve(self) -> str:
        """Return the effective model ID to use in API requests.

        When ``config.model`` is ``"auto"``, queries LM Studio (via the
        OAI-compatible ``/v1/models`` endpoint) for the first loaded model
        and caches the result for ``_auto_model_ttl`` seconds.  Falls back to
        ``"auto"`` itself if the query fails so LM Studio chooses for us.

        Returns:
            The resolved model ID string.
        """
        if self._is_openrouter:
            # Nessun concetto di "modello caricato" per un provider cloud:
            # il modello attivo è la scelta esplicita dell'utente.
            return self._config.openrouter_model or "openrouter/auto"

        if self._config.model != "auto":
            return self._config.model

        now = time.monotonic()
        if (
            self._auto_model_cache is not None
            and now - self._auto_model_cache[1] < self._auto_model_ttl
        ):
            return self._auto_model_cache[0]

        async with self._auto_model_lock:
            # Re-check cache after acquiring lock (another task may
            # have resolved while we waited).
            now = time.monotonic()
            if (
                self._auto_model_cache is not None
                and now - self._auto_model_cache[1] < self._auto_model_ttl
            ):
                return self._auto_model_cache[0]

            # Try LM Studio v1 API first, then OAI-compat fallback.
            resolved: str | None = None
            v1_url = (
                f"{self._config.base_url}/api/v1/models"
                if not self._is_ollama
                else f"{self._config.base_url}/api/tags"
            )
            try:
                resp = await self._http.get(
                    v1_url,
                    timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("models") or data.get("data") or []

                # Opportunistically refresh the capability registry
                # from this v1 API response.
                if items and self._model_registry is not None:
                    await self._model_registry.refresh_from_api(items)

                if items:
                    # Only consider chat-capable (non-embedding) models;
                    # sending chat/completions to an embedding model fails.
                    non_embedding = [
                        it for it in items
                        if not self._is_embedding_model(it)
                    ]
                    # Strongly prefer a model that is ALREADY loaded.
                    # Resolving to an unloaded model makes LM Studio
                    # JIT-load it on the next chat request, which evicts
                    # the embedding model (and any current chat model)
                    # from VRAM — the cause of the "loads an OCR model,
                    # drops embeddings, then reloads them" churn.  The
                    # ``state`` field is blank on recent LM Studio builds,
                    # so loadedness is detected via ``loaded_instances``.
                    loaded_llms = [
                        it for it in non_embedding if self._is_loaded(it)
                    ]
                    if loaded_llms:
                        resolved = self._pick_chat_model_id(loaded_llms)
                    elif non_embedding:
                        # No chat model is loaded — fall back to the best
                        # available so the user can still chat, accepting a
                        # one-time JIT load.  ``_pick_chat_model_id`` avoids
                        # single-purpose models (e.g. OCR) where possible.
                        resolved = self._pick_chat_model_id(non_embedding)
                        if resolved:
                            logger.info(
                                "No chat model loaded in LM Studio; "
                                "auto-selecting '{}' (will be JIT-loaded)",
                                resolved,
                            )
                    else:
                        logger.debug(
                            "LM Studio v1 API returned {} model(s), all "
                            "embedding — falling back to OAI-compat",
                            len(items),
                        )
            except Exception as exc:
                logger.debug(
                    "LM Studio v1 model query failed ({}: {}), trying OAI-compat",
                    type(exc).__name__, exc,
                )

            if not resolved:
                # Final fallback: OAI-compat /v1/models
                try:
                    resp = await self._http.get(
                        f"{self._config.base_url}/v1/models",
                        timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
                    )
                    resp.raise_for_status()
                    items = resp.json().get("data", [])
                    # Skip embedding models in OAI-compat responses too.
                    # This endpoint exposes no load state, so we cannot
                    # prefer a loaded model here; pick the best chat model.
                    non_embedding = [
                        it for it in items
                        if not self._is_embedding_model(it)
                    ]
                    resolved = self._pick_chat_model_id(non_embedding)
                    if not resolved and items:
                        logger.warning(
                            "All {} model(s) from OAI-compat API are embedding "
                            "models — cannot use for chat",
                            len(items),
                        )
                except Exception as exc2:
                    logger.warning(
                        "OAI-compat auto model resolution failed: {}: {}",
                        type(exc2).__name__, exc2,
                    )

            if resolved:
                prev = self._auto_model_cache
                self._auto_model_cache = (resolved, now)
                if prev is None or prev[0] != resolved:
                    logger.info("Auto-resolved LLM model: {}", resolved)
                return resolved

            # Could not resolve — let the server decide.
            logger.warning("Could not auto-resolve model; sending 'auto'")
            return "auto"

    def invalidate_model_cache(self) -> None:
        """Invalidate the cached auto-resolved model ID.

        Call this whenever the active model changes (load, unload,
        config update, sync) so the next chat request re-resolves the
        ``"auto"`` model against LM Studio's currently loaded set.
        """
        self._auto_model_cache = None
