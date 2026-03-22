"""AL\CE — CAD Generator plugin (TRELLIS 3D).

Orchestrates text-to-3D generation via the local TRELLIS microservice,
including automatic VRAM swapping (unload LLM → generate → reload LLM)
for GPUs with limited memory.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

# Seconds between live HTTP health checks when TRELLIS is reachable.
# Avoids hammering the server (and initialising its CUDA context) on
# every single LLM tool-building call.
_STATUS_CACHE_TTL_S: float = 30.0

from loguru import logger

from backend.core.config import PROJECT_ROOT
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.cad_generator.client import TrellisClient

if TYPE_CHECKING:
    from backend.core.context import AppContext

_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,64}$")


class CadGeneratorPlugin(BasePlugin):
    """3D model generation via the TRELLIS microservice."""

    plugin_name: str = "cad_generator"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Generate 3D models (GLB) from text descriptions via the local "
        "TRELLIS microservice."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 20

    def __init__(self) -> None:
        super().__init__()
        self._client: TrellisClient | None = None
        self._request_timeout_s: int = 600
        # Cached connection status + timestamp for TTL-based refresh.
        self._cached_status: ConnectionStatus = ConnectionStatus.UNKNOWN
        self._status_checked_at: float = 0.0

    # ------------------------------------------------------------------
    # Public property
    # ------------------------------------------------------------------

    @property
    def client(self) -> TrellisClient | None:
        """Expose the TRELLIS client for route-level access."""
        return self._client

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Create the TRELLIS client and prepare the output directory.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)
        cfg = ctx.config.trellis

        self._request_timeout_s = cfg.request_timeout_s
        self._client = TrellisClient(
            base_url=cfg.service_url,
            timeout_s=cfg.request_timeout_s,
            max_model_size_mb=cfg.max_model_size_mb,
        )

        output_dir = PROJECT_ROOT / cfg.model_output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        reachable = await self._client.health_check()
        if reachable:
            logger.info("TRELLIS microservice reachable at {}", cfg.service_url)
            # Ensure the server has the configured model loaded
            await self._sync_model(cfg.trellis_model)
        else:
            logger.warning(
                "TRELLIS microservice not reachable at {} — "
                "3D generation will fail until the service starts",
                cfg.service_url,
            )

    async def cleanup(self) -> None:
        """Close the TRELLIS HTTP client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        await super().cleanup()

    async def get_connection_status(self) -> ConnectionStatus:
        """Check TRELLIS microservice connectivity with TTL-based caching.

        Returns the cached status when the last check was less than
        ``_STATUS_CACHE_TTL_S`` seconds ago, avoiding an HTTP round-trip
        (and the attendant CUDA-context wake-up on the TRELLIS side) on
        every LLM tool-building call.

        Returns:
            ``CONNECTED`` if health check passes, ``DEGRADED`` if the
            client exists but the server is unreachable (tool stays
            visible to the LLM so it can return a helpful error),
            ``DISCONNECTED`` only if the client was never created.
        """
        if self._client is None:
            return ConnectionStatus.DISCONNECTED

        now = time.monotonic()
        if now - self._status_checked_at < _STATUS_CACHE_TTL_S:
            return self._cached_status

        reachable = await self._client.health_check()
        self._cached_status = (
            ConnectionStatus.CONNECTED if reachable else ConnectionStatus.DEGRADED
        )
        self._status_checked_at = now
        return self._cached_status

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def _is_text_model(self) -> bool:
        """Return True if the configured TRELLIS model is text-to-3D."""
        return "text" in self.ctx.config.trellis.trellis_model.lower()

    async def _sync_model(self, desired_model: str) -> None:
        """Ensure the TRELLIS server has the desired model loaded.

        Checks the server's current model and sends a /load request
        if it differs from *desired_model*.
        """
        status = await self._client.get_status()
        if status is None:
            return
        current = status.get("model_name", "")
        if current == desired_model:
            logger.debug("TRELLIS server already has model '{}'", desired_model)
            return
        logger.info(
            "TRELLIS model mismatch: server='{}', config='{}' — requesting switch",
            current, desired_model,
        )
        ok = await self._client.request_model(desired_model)
        if ok:
            logger.info("TRELLIS model switched to '{}'", desired_model)
        else:
            logger.warning(
                "Failed to switch TRELLIS model to '{}' — server keeps '{}'",
                desired_model, current,
            )

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return the ``cad_generate`` tool definition.

        Returns:
            A single-element list with the 3D generation tool.
        """
        return [
            ToolDefinition(
                name="cad_generate",
                description=(
                    "Generate a 3D model (GLB) from a text description using the local TRELLIS neural network. "
                    "Returns the file path and a URL to view the model. "
                    "Write DETAILED descriptions for best results: shape, dimensions, material, style, details. "
                    "Use descriptive English model_name (e.g. 'phone_stand', 'decorative_vase'). "
                    "Generation takes 30–90 seconds — warn the user. "
                    "Do NOT write CAD code — the system uses a neural network."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": (
                                "Detailed description of the 3D object to "
                                "generate (e.g. 'a red sports car')."
                            ),
                        },
                        "model_name": {
                            "type": "string",
                            "description": (
                                "Output filename (alphanumeric + underscore, "
                                "max 64 chars). Defaults to auto-generated."
                            ),
                        },
                    },
                    "required": ["description"],
                },
                result_type="json",
                timeout_ms=(self._request_timeout_s + 30) * 1000,
                requires_confirmation=True,
                risk_level="safe",
            ),
        ]

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch tool execution by name.

        Args:
            tool_name: Must be ``"cad_generate"``.
            args: Tool arguments from the LLM.
            context: Execution metadata.

        Returns:
            A :class:`ToolResult` with the generation outcome.
        """
        if tool_name == "cad_generate":
            return await self._execute_cad_generate(args, context)
        return ToolResult.error(f"Unknown tool: {tool_name}")

    async def _execute_cad_generate(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Run the full 3D generation pipeline.

        Steps: validate → health check → VRAM swap + generate →
        download → save locally → return result.
        """
        start = time.perf_counter()
        description = args.get("description", "").strip()
        if not description:
            return ToolResult.error("'description' is required")

        # Sanitise / default model_name
        model_name = args.get("model_name", "").strip()
        if model_name:
            # Sanitize invalid characters instead of rejecting
            model_name = re.sub(r"[^a-zA-Z0-9_]", "_", model_name).strip("_")
        if not model_name:
            model_name = re.sub(r"[^a-zA-Z0-9_]", "_", description[:40]).strip("_")
        if not model_name or not _MODEL_NAME_RE.match(model_name):
            return ToolResult.error(
                "model_name must be alphanumeric/underscore, max 64 chars"
            )

        if self._client is None:
            return ToolResult.error("TRELLIS client not initialised")

        if not await self._client.health_check():
            return ToolResult.error(
                "TRELLIS microservice is not reachable — "
                "please start it before generating"
            )

        cfg = self.ctx.config.trellis
        result, error = await self._vram_swap_generate(description, model_name)
        if error:
            return ToolResult.error(error)
        if result is None:
            return ToolResult.error("TRELLIS generation returned no result")

        # Download and save locally
        try:
            glb_bytes = await self._client.download_model(result.model_name)
        except Exception as exc:
            return ToolResult.error(f"Failed to download model: {exc}")

        output_dir = PROJECT_ROOT / cfg.model_output_dir
        output_path = output_dir / f"{result.model_name}.glb"
        await asyncio.to_thread(output_path.write_bytes, glb_bytes)

        elapsed = (time.perf_counter() - start) * 1000
        payload = {
            "model_name": result.model_name,
            "format": result.format,
            "size_bytes": len(glb_bytes),
            "file_path": str(output_path),
            "export_url": f"/api/cad/models/{result.model_name}",
            "description": description,
        }
        logger.info(
            "3D model '{}' generated ({} bytes, {:.0f}ms)",
            result.model_name, len(glb_bytes), elapsed,
        )
        return ToolResult.ok(
            payload,
            content_type="application/json",
            execution_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # VRAM swap helper
    # ------------------------------------------------------------------

    async def _vram_swap_generate(
        self,
        description: str,
        model_name: str,
    ) -> tuple[Any, str | None]:
        """Generate with optional VRAM swapping.

        If ``auto_vram_swap`` is enabled, unloads the LLM from VRAM
        before generation and reloads it afterwards.

        Returns:
            A ``(GenerationResult, None)`` on success or
            ``(None, error_message)`` on failure.
        """
        cfg = self.ctx.config.trellis
        lm = self.ctx.lmstudio_manager
        model_id: str | None = None

        # Step 1: unload LLM if auto_vram_swap is on
        if cfg.auto_vram_swap and lm is not None:
            try:
                models_resp = await lm.list_models()
                all_models = models_resp.get("models", [])
                # Find first loaded LLM (skip embedding models)
                for m in all_models:
                    if m.get("type") == "embedding":
                        continue
                    instances = m.get("loaded_instances", [])
                    if instances:
                        model_id = m.get("key") or m.get("path", "")
                        instance_id = instances[0] if isinstance(instances[0], str) else instances[0].get("id", "")
                        if instance_id:
                            logger.info("VRAM swap: unloading LLM '{}' (instance: {})", model_id, instance_id)
                            await lm.unload_model(instance_id)
                            await asyncio.sleep(2)
                        break
            except Exception as exc:
                logger.warning("VRAM swap unload failed: {}", exc)

        # Step 2: generate
        gen_error: str | None = None
        gen_result = None
        try:
            if self._is_text_model():
                gen_result = await self._client.generate_from_text(
                    description, model_name, seed=cfg.seed,
                )
            else:
                # Image model — generate an intermediate image from text first
                # via an external text-to-image pipeline, then feed it to TRELLIS.
                # For now, only text-to-3D is supported from the chat tool.
                gen_error = (
                    f"Model '{cfg.trellis_model}' is image-to-3D and requires "
                    "an image input. Switch trellis_model to a TRELLIS-text-* "
                    "model in config/default.yaml, or provide an image."
                )
        except Exception as exc:
            gen_error = f"TRELLIS generation failed: {exc}"
            logger.error(gen_error)

        # Step 3: unload TRELLIS model (best-effort)
        try:
            await self._client.unload_model()
        except Exception:
            pass

        # Step 4: reload LLM if we unloaded it
        if cfg.auto_vram_swap and model_id and lm is not None:
            try:
                logger.info("VRAM swap: reloading LLM '{}'", model_id)
                await lm.load_model(model_id)
                # Poll until the model is loaded (max 60s)
                for _ in range(30):
                    await asyncio.sleep(2)
                    resp = await lm.list_models()
                    loaded_keys = [
                        m.get("key", "")
                        for m in resp.get("models", [])
                        if m.get("loaded_instances")
                    ]
                    if model_id in loaded_keys:
                        logger.info("LLM '{}' reloaded successfully", model_id)
                        break
                else:
                    logger.warning(
                        "LLM '{}' did not appear within 60s", model_id,
                    )
            except Exception as exc:
                logger.error("VRAM swap reload failed: {}", exc)

        return gen_result, gen_error
