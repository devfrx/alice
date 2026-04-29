"""AL\\CE — LM Studio v1 REST API client for model management."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx
from loguru import logger


class ModelOperation:
    """Tracks a single model operation (load/unload) in progress."""

    __slots__ = ("type", "model", "status", "progress", "error", "started_at")

    def __init__(self, op_type: str, model: str) -> None:
        self.type = op_type
        self.model = model
        self.status = "in_progress"
        self.progress: float = -1.0  # indeterminate
        self.error: str | None = None
        self.started_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Return a serialisable snapshot of this operation."""
        return {
            "type": self.type,
            "model": self.model,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "started_at": self.started_at,
        }


class LMStudioManager:
    """Async client for the LM Studio v1 REST API.

    Handles model listing, loading, unloading, downloading,
    and health checks against the ``/api/v1/`` endpoints.

    Args:
        base_url: LM Studio server base URL (e.g. ``http://localhost:1234``).
        api_token: Optional Bearer token for authenticated requests.
    """

    def __init__(self, base_url: str, api_token: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        headers: dict[str, str] = {}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
        self._operation_lock = asyncio.Lock()
        self._current_operation: ModelOperation | None = None
        # Short-lived cache for ``list_models`` so concurrent callers
        # (status endpoint, context-window probe, capability registry,
        # embedding refresh, …) don't each issue an independent
        # ``GET /api/v1/models``.  LM Studio is single-threaded on
        # inference; without coalescing these probes pile up into
        # ``ReadTimeout`` warnings whenever the server is busy with
        # a chat completion or a JIT model swap.
        self._models_cache: dict | None = None
        self._models_cache_expires: float = 0.0
        self._models_cache_lock = asyncio.Lock()
        self._models_cache_ttl: float = 5.0
        self._models_cache_ttl_failure: float = 20.0

    # -- Operation tracking -------------------------------------------------

    @property
    def current_operation(self) -> dict | None:
        """Return the current model operation status or None."""
        if self._current_operation is None:
            return None
        return self._current_operation.to_dict()

    @property
    def is_busy(self) -> bool:
        """Return True if a model operation is in progress."""
        return self._operation_lock.locked()

    def _schedule_clear(self, operation: ModelOperation) -> None:
        """Schedule clearing *operation* after a delay.

        Only clears if the tracked operation hasn't been replaced
        by a newer one in the meantime.
        """
        def _do_clear() -> None:
            if self._current_operation is operation:
                self._current_operation = None

        asyncio.get_running_loop().call_later(3.0, _do_clear)

    # -- Models -------------------------------------------------------------

    async def list_models(self) -> dict:
        """List all models known to LM Studio.

        Coalesced behind a short TTL cache so concurrent or repeated
        callers do not each round-trip to LM Studio.  The cache is
        invalidated automatically by :meth:`invalidate_models_cache`,
        which load/unload paths call to make state changes visible
        immediately.

        Returns:
            The JSON response from ``GET /api/v1/models``.
        """
        now = time.monotonic()
        cached = self._models_cache
        if cached is not None and now < self._models_cache_expires:
            return cached

        async with self._models_cache_lock:
            cached = self._models_cache
            now = time.monotonic()
            if cached is not None and now < self._models_cache_expires:
                return cached
            try:
                resp = await self._client.get(
                    "/api/v1/models",
                    timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError as exc:
                logger.warning(
                    "LM Studio list_models failed: {}: {}",
                    type(exc).__name__, exc,
                )
                # On failure, suppress repeated calls for a longer window
                # so we don't keep hammering an unreachable / busy server.
                self._models_cache_expires = (
                    time.monotonic() + self._models_cache_ttl_failure
                )
                raise
            self._models_cache = data
            self._models_cache_expires = (
                time.monotonic() + self._models_cache_ttl
            )
            return data

    def invalidate_models_cache(self) -> None:
        """Drop the cached ``list_models`` response.

        Called after load/unload so the next caller sees fresh state.
        """
        self._models_cache = None
        self._models_cache_expires = 0.0

    async def load_model(
        self,
        model: str,
        *,
        context_length: int | None = None,
        flash_attention: bool | None = None,
        eval_batch_size: int | None = None,
        num_experts: int | None = None,
        offload_kv_cache_to_gpu: bool | None = None,
    ) -> dict:
        """Load a model into LM Studio (mutually exclusive).

        Concurrent calls are serialised by ``self._operation_lock`` —
        a second caller awaits completion of the first.  Callers that
        need fail-fast semantics (e.g. HTTP routes returning 409) must
        check :pyattr:`is_busy` *before* invoking this method.

        Args:
            model: The model key to load.
            context_length: Override context window size.
            flash_attention: Enable flash attention.
            eval_batch_size: Evaluation batch size.
            num_experts: Number of experts for MoE models.
            offload_kv_cache_to_gpu: Offload KV cache to GPU.

        Returns:
            The JSON response from ``POST /api/v1/models/load``.
        """
        async with self._operation_lock:
            self._current_operation = ModelOperation("load", model)
            try:
                payload: dict = {
                    "model": model, "echo_load_config": True,
                }
                if context_length is not None:
                    payload["context_length"] = context_length
                if flash_attention is not None:
                    payload["flash_attention"] = flash_attention
                if eval_batch_size is not None:
                    payload["eval_batch_size"] = eval_batch_size
                if num_experts is not None:
                    payload["num_experts"] = num_experts
                if offload_kv_cache_to_gpu is not None:
                    payload["offload_kv_cache_to_gpu"] = (
                        offload_kv_cache_to_gpu
                    )

                resp = await self._client.post(
                    "/api/v1/models/load",
                    json=payload,
                    timeout=httpx.Timeout(
                        connect=5.0, read=120.0,
                        write=5.0, pool=5.0,
                    ),
                )
                resp.raise_for_status()
                result = resp.json()
                self._current_operation.status = "completed"
                self._current_operation.progress = 1.0
                self.invalidate_models_cache()
                return result
            except Exception as exc:
                if self._current_operation:
                    self._current_operation.status = "failed"
                    self._current_operation.error = str(exc)
                logger.error(
                    "LM Studio load_model({}) failed: {}",
                    model, exc,
                )
                raise
            finally:
                self._schedule_clear(self._current_operation)

    async def unload_model(self, instance_id: str) -> dict:
        """Unload a model from LM Studio (mutually exclusive).

        Concurrent calls are serialised by ``self._operation_lock`` —
        a second caller awaits completion of the first.  Callers that
        need fail-fast semantics (e.g. HTTP routes returning 409) must
        check :pyattr:`is_busy` *before* invoking this method.

        Args:
            instance_id: The instance ID of the loaded model.

        Returns:
            The JSON response from ``POST /api/v1/models/unload``.
        """
        async with self._operation_lock:
            self._current_operation = ModelOperation(
                "unload", instance_id,
            )
            try:
                resp = await self._client.post(
                    "/api/v1/models/unload",
                    json={"instance_id": instance_id},
                )
                resp.raise_for_status()
                result = resp.json()
                self._current_operation.status = "completed"
                self._current_operation.progress = 1.0
                self.invalidate_models_cache()
                return result
            except Exception as exc:
                if self._current_operation:
                    self._current_operation.status = "failed"
                    self._current_operation.error = str(exc)
                logger.error(
                    "LM Studio unload_model({}) failed: {}",
                    instance_id, exc,
                )
                raise
            finally:
                self._schedule_clear(self._current_operation)

    async def download_model(
        self,
        model: str,
        *,
        quantization: str | None = None,
    ) -> dict:
        """Start a model download.

        Args:
            model: The model identifier (e.g. ``ibm/granite-4-micro``).
            quantization: Quantization format (e.g. ``Q4_K_M``).

        Returns:
            The JSON response from ``POST /api/v1/models/download``.
        """
        payload: dict = {"model": model}
        if quantization is not None:
            payload["quantization"] = quantization
        try:
            resp = await self._client.post(
                "/api/v1/models/download",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.error("LM Studio download_model({}) failed: {}", model, exc)
            raise

    async def get_download_status(self, job_id: str) -> dict:
        """Get the status of a model download job.

        Args:
            job_id: The download job identifier.

        Returns:
            The JSON response from ``GET /api/v1/models/download/status/{job_id}``.
        """
        try:
            resp = await self._client.get(
                f"/api/v1/models/download/status/{job_id}",
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("LM Studio get_download_status({}) failed: {}", job_id, exc)
            raise

    # -- Health -------------------------------------------------------------

    async def check_health(self) -> bool:
        """Return ``True`` if LM Studio is reachable.

        Performs a lightweight ``GET /api/v1/models`` and returns
        ``False`` on any connection or HTTP error.
        """
        try:
            resp = await self._client.get(
                "/api/v1/models",
                timeout=httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0),
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    # -- Lifecycle ----------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client and clear state."""
        await self._client.aclose()
        self._current_operation = None
