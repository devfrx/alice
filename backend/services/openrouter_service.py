"""AL\\CE — OpenRouter catalog and credits service.

Thin httpx wrapper over the two ancillary OpenRouter endpoints:
``GET /v1/models`` (public catalog, cached in-process) and
``GET /v1/key`` (key limits/usage, authenticated). Chat streaming does
NOT go through this service — it lives in ``services/llm/client.py``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from loguru import logger

from backend.core.config import LLMConfig
from backend.services.model_capability_registry import ModelCapabilityRegistry


class OpenRouterService:
    """Catalog + credits access for OpenRouter.

    Args:
        config: The shared ``LLMConfig`` (reads ``openrouter_base_url`` /
            ``openrouter_api_key`` at call time, so runtime key changes
            are picked up without a rebuild).
        model_registry: Optional capability registry seeded from the
            catalog on every successful fetch.
    """

    def __init__(
        self,
        config: LLMConfig,
        model_registry: ModelCapabilityRegistry | None = None,
    ) -> None:
        self._config = config
        self._registry = model_registry
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0, read=30.0, write=10.0, pool=10.0,
            ),
        )
        self._catalog_cache: list[dict[str, Any]] | None = None
        self._catalog_fetched_at: float = 0.0
        self._catalog_ttl: float = 3600.0
        self._lock = asyncio.Lock()

    def _base(self) -> str:
        return self._config.openrouter_base_url.rstrip("/")

    def _auth_headers(self) -> dict[str, str]:
        api_key = self._config.openrouter_api_key.get_secret_value()
        if not api_key:
            return {}
        return {
            "Authorization": f"Bearer {api_key}",
        }

    async def list_models(
        self, force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Return the OpenRouter model catalog (cached, TTL 1h).

        Args:
            force_refresh: Bypass the cache and re-fetch.

        Returns:
            A shallow copy of the raw ``data`` list from the OpenRouter
            response (safe for callers to mutate without corrupting the
            shared cache).
        """
        now = time.monotonic()
        if (
            not force_refresh
            and self._catalog_cache is not None
            and now - self._catalog_fetched_at < self._catalog_ttl
        ):
            return list(self._catalog_cache)
        async with self._lock:
            now = time.monotonic()
            if (
                not force_refresh
                and self._catalog_cache is not None
                and now - self._catalog_fetched_at < self._catalog_ttl
            ):
                return list(self._catalog_cache)
            resp = await self._http.get(f"{self._base()}/v1/models")
            resp.raise_for_status()
            models: list[dict[str, Any]] = resp.json().get("data", [])
            if self._registry is not None and models:
                await self._registry.refresh_from_openrouter(models)
            self._catalog_cache = models
            self._catalog_fetched_at = now
            logger.info("OpenRouter catalog fetched: {} models", len(models))
            return list(models)

    async def get_credits(self) -> dict[str, Any]:
        """Return key limits/usage from ``GET /v1/key``.

        Raises:
            httpx.HTTPStatusError: On 401 (invalid key) or other HTTP errors.
            httpx.HTTPError: When OpenRouter is unreachable.
        """
        resp = await self._http.get(
            f"{self._base()}/v1/key", headers=self._auth_headers(),
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json().get("data", {})
        return data

    def invalidate_catalog(self) -> None:
        """Drop the cached catalog (next call re-fetches)."""
        self._catalog_cache = None
        self._catalog_fetched_at = 0.0

    async def close(self) -> None:
        """Release the underlying httpx client."""
        await self._http.aclose()
