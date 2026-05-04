"""AL\\CE — CAD Generator plugin (TRELLIS 3D).

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
from backend.plugins.cad_generator.client_v2 import (
    Trellis2Client,
    _ALLOWED_PIPELINE_TYPES as _TRELLIS2_PIPELINES,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext

_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,64}$")

# MIME type whitelist for the cad_generate_from_image tool.  Mirrors the
# upload validator in :mod:`backend.api.routes.chat` so the tool refuses
# anything the user could not have legitimately uploaded.
_ALLOWED_IMAGE_EXTS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


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
        # TRELLIS.2 image-to-3D client.  Created in ``initialize`` only
        # when ``ctx.config.trellis2.enabled`` is True; otherwise stays
        # ``None`` and the ``cad_generate_from_image`` tool is hidden
        # from the LLM by ``get_tools``.
        self._client_v2: Trellis2Client | None = None
        self._request_timeout_s: int = 1200
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

    @property
    def client_v2(self) -> Trellis2Client | None:
        """Expose the TRELLIS.2 client for route-level access (may be ``None``)."""
        return self._client_v2

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

        # Optional sibling: TRELLIS.2 (image-to-3D, 4B). Only created
        # when explicitly enabled in config to avoid spurious health
        # checks against a port nobody is listening on.
        cfg2 = ctx.config.trellis2
        if cfg2.enabled:
            self._client_v2 = Trellis2Client(
                base_url=cfg2.service_url,
                timeout_s=cfg2.request_timeout_s,
                max_model_size_mb=cfg2.max_model_size_mb,
            )
            output_dir2 = PROJECT_ROOT / cfg2.model_output_dir
            output_dir2.mkdir(parents=True, exist_ok=True)
            if await self._client_v2.health_check():
                logger.info(
                    "TRELLIS.2 microservice reachable at {}", cfg2.service_url
                )
            else:
                logger.warning(
                    "TRELLIS.2 microservice not reachable at {} — "
                    "image-to-3D will fail until start-trellis2.ps1 runs",
                    cfg2.service_url,
                )

    async def cleanup(self) -> None:
        """Close the TRELLIS and TRELLIS.2 HTTP clients."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        if self._client_v2 is not None:
            await self._client_v2.close()
            self._client_v2 = None
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
        """Return the available 3D-generation tools.

        ``cad_generate`` (text-to-3D via TRELLIS-classic) is always
        present.  ``cad_generate_from_image`` (image-to-3D via
        TRELLIS.2) is only exposed when the TRELLIS.2 microservice has
        been enabled in config; this keeps the LLM tool catalog clean
        on installations that have not set up the second service.

        Returns:
            A list of one or two :class:`ToolDefinition` instances.
        """
        tools: list[ToolDefinition] = [
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

        if self._client_v2 is not None:
            cfg2 = self.ctx.config.trellis2
            # Intersect the whitelist with the values the microservice
            # actually understands.  Empty intersection falls back to
            # the configured default to keep the tool callable.
            _allowed_pipeline_types = (
                set(cfg2.allowed_pipeline_types) & _TRELLIS2_PIPELINES
                or {cfg2.pipeline_type}
            )
            tools.append(
                ToolDefinition(
                    name="cad_generate_from_image",
                    description=(
                        "Generate a high-fidelity 3D model (GLB) from a USER-PROVIDED IMAGE "
                        "using the local TRELLIS.2 neural network (image-to-3D). "
                        "Use this when the user attaches a photo / sketch / render and asks for a 3D model of it. "
                        "REQUIRES an image: the 'image_path' parameter must point to a previously "
                        "uploaded file under 'data/uploads/...' (use the file_path from an attachment). "
                        "Generation takes ~10–60 seconds depending on pipeline_type — warn the user. "
                        "Do NOT use this tool for text-only requests; use 'cad_generate' instead."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "image_path": {
                                "type": "string",
                                "description": (
                                    "Path to the input image, relative to the project root "
                                    "(e.g. 'data/uploads/<conv_id>/<file_id>.png'). "
                                    "Must be an existing PNG/JPEG/WebP/GIF inside data/uploads/."
                                ),
                            },
                            "model_name": {
                                "type": "string",
                                "description": (
                                    "Output filename stem (alphanumeric + underscore, "
                                    "max 64 chars). Defaults to auto-generated."
                                ),
                            },
                            "pipeline_type": {
                                "type": "string",
                                "enum": sorted(_allowed_pipeline_types),
                                "description": (
                                    "Resolution / quality preset. '512' (~3s) is the fastest, "
                                    "'1536_cascade' (~60s) the highest quality. "
                                    f"Defaults to '{cfg2.pipeline_type}' from config. "
                                    "NOTE: only the values in the enum are allowed on this "
                                    "hardware — higher-resolution presets are gated by "
                                    "trellis2.allowed_pipeline_types in config/default.yaml."
                                ),
                            },
                        },
                        "required": ["image_path"],
                    },
                    result_type="json",
                    timeout_ms=(cfg2.request_timeout_s + 30) * 1000,
                    requires_confirmation=True,
                    risk_level="safe",
                )
            )

        return tools

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
        if tool_name == "cad_generate_from_image":
            return await self._execute_cad_generate_from_image(args, context)
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
    # VRAM swap helpers
    # ------------------------------------------------------------------

    async def _unload_llm_for_swap(self) -> list[str]:
        """Unload **all** loaded models from LM Studio (LLMs + embeddings).

        Used by both the text-to-3D (TRELLIS) and image-to-3D
        (TRELLIS.2) flows to free as much VRAM as possible before
        launching a 4B+ diffusion pass.  Best-effort: returns an empty
        list if LM Studio is absent, nothing is loaded, or every
        unload call fails.

        Returns:
            The list of ``key``/``path`` identifiers that were
            successfully unloaded, in the original load order.  Pass
            this list back to :meth:`_reload_llm_after_swap` to
            restore the previous state.
        """
        lm = self.ctx.lmstudio_manager
        if lm is None:
            return []

        unloaded: list[str] = []
        try:
            models_resp = await lm.list_models()
        except Exception as exc:
            logger.warning("VRAM swap list_models failed: {}", exc)
            return []

        for m in models_resp.get("models", []):
            instances = m.get("loaded_instances", [])
            if not instances:
                continue
            model_id = m.get("key") or m.get("path", "")
            if not model_id:
                continue
            # A single model may have multiple loaded instances (rare,
            # but possible when the user duplicates a slot in LM Studio).
            for inst in instances:
                instance_id = (
                    inst if isinstance(inst, str)
                    else inst.get("id", "")
                )
                if not instance_id:
                    continue
                try:
                    logger.info(
                        "VRAM swap: unloading '{}' (type={}, instance={})",
                        model_id, m.get("type", "?"), instance_id,
                    )
                    await lm.unload_model(instance_id)
                except Exception as exc:
                    logger.warning(
                        "VRAM swap: failed to unload '{}': {}",
                        model_id, exc,
                    )
                    continue
            unloaded.append(model_id)

        if unloaded:
            # Give LM Studio a moment to actually release the CUDA
            # context after the last unload call returns.
            await asyncio.sleep(2)
        return unloaded

    async def _reload_llm_after_swap(self, model_ids: list[str]) -> None:
        """Reload models previously unloaded by :meth:`_unload_llm_for_swap`.

        Restores LM Studio to the state it was in before the swap by
        loading each ``model_id`` sequentially (LM Studio serialises
        load operations internally).  All errors are logged but never
        raised: failure to reload must not mask a successful
        generation result.
        """
        lm = self.ctx.lmstudio_manager
        if lm is None or not model_ids:
            return

        for model_id in model_ids:
            try:
                logger.info("VRAM swap: reloading '{}'", model_id)
                await lm.load_model(model_id)
            except Exception as exc:
                logger.error(
                    "VRAM swap reload failed for '{}': {}", model_id, exc,
                )
                continue

            # Poll until the model shows up as loaded (max ~60 s).
            for _ in range(30):
                await asyncio.sleep(2)
                try:
                    resp = await lm.list_models()
                except Exception:
                    continue
                loaded_keys = {
                    m.get("key", "")
                    for m in resp.get("models", [])
                    if m.get("loaded_instances")
                }
                if model_id in loaded_keys:
                    logger.info("Model '{}' reloaded successfully", model_id)
                    break
            else:
                logger.warning(
                    "Model '{}' did not appear loaded within 60 s", model_id,
                )

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
        unloaded_models: list[str] = []

        # Step 1: unload all LM Studio models if auto_vram_swap is on
        if cfg.auto_vram_swap:
            unloaded_models = await self._unload_llm_for_swap()

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
        finally:
            # Step 3: unload TRELLIS model (best-effort)
            try:
                await self._client.unload_model()
            except Exception:
                pass

            # Step 4: reload everything we unloaded, including cancellation paths
            if cfg.auto_vram_swap and unloaded_models:
                await self._reload_llm_after_swap(unloaded_models)

        return gen_result, gen_error

    # ------------------------------------------------------------------
    # Image-to-3D (TRELLIS.2) flow
    # ------------------------------------------------------------------

    def _resolve_uploaded_image(self, image_path: str) -> tuple[Path, str] | str:
        """Validate *image_path* and return ``(absolute_path, mime_type)``.

        The path must be relative to ``PROJECT_ROOT`` and resolve inside
        ``data/uploads/``.  This blocks path-traversal (``..`` segments,
        absolute paths outside the project, drive-letter tricks) and
        keeps the tool from leaking arbitrary filesystem reads to the LLM.

        Returns:
            ``(abs_path, mime_type)`` on success, or an error string on
            failure.  Using a tagged-union return keeps the caller free
            of an extra exception type.
        """
        if not image_path or not isinstance(image_path, str):
            return "image_path must be a non-empty string"

        uploads_root = (PROJECT_ROOT / "data" / "uploads").resolve()
        candidate = (PROJECT_ROOT / image_path).resolve()
        try:
            candidate.relative_to(uploads_root)
        except ValueError:
            return (
                "image_path must point to a file inside data/uploads/ "
                "(use the file_path returned by the upload endpoint)"
            )

        if not candidate.is_file():
            return f"Image file not found: {image_path}"

        mime = _ALLOWED_IMAGE_EXTS.get(candidate.suffix.lower())
        if mime is None:
            allowed = ", ".join(sorted(_ALLOWED_IMAGE_EXTS))
            return f"Unsupported image extension '{candidate.suffix}'. Allowed: {allowed}"

        return candidate, mime

    async def _execute_cad_generate_from_image(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Run the image-to-3D pipeline via the TRELLIS.2 microservice.

        Steps: validate args + image path → health check → optional
        VRAM swap → generate → download → save under
        ``data/3d_models/`` → return JSON payload.
        """
        start = time.perf_counter()

        if self._client_v2 is None:
            return ToolResult.error(
                "TRELLIS.2 microservice is disabled — set trellis2.enabled "
                "in config/default.yaml and start scripts/start-trellis2.ps1"
            )

        # --- argument validation ---------------------------------------
        image_path_arg = args.get("image_path", "").strip()
        resolved = self._resolve_uploaded_image(image_path_arg)
        if isinstance(resolved, str):
            return ToolResult.error(resolved)
        abs_image_path, mime = resolved

        cfg2 = self.ctx.config.trellis2
        pipeline_type = (args.get("pipeline_type") or cfg2.pipeline_type).strip()
        # Cross-check both lists: whitelist (hardware budget) and the
        # full set of pipelines the microservice actually understands.
        allowed = set(cfg2.allowed_pipeline_types) & _TRELLIS2_PIPELINES
        if not allowed:
            allowed = {cfg2.pipeline_type}
        if pipeline_type not in allowed:
            return ToolResult.error(
                f"Invalid pipeline_type '{pipeline_type}'. "
                f"Allowed on this hardware: {', '.join(sorted(allowed))}"
            )

        model_name = args.get("model_name", "").strip()
        if model_name:
            model_name = re.sub(r"[^a-zA-Z0-9_]", "_", model_name).strip("_")
        if not model_name:
            # Derive from the input filename stem (already UUID-shaped).
            model_name = re.sub(
                r"[^a-zA-Z0-9_]", "_", abs_image_path.stem[:40]
            ).strip("_")
        if not model_name or not _MODEL_NAME_RE.match(model_name):
            return ToolResult.error(
                "model_name must be alphanumeric/underscore, max 64 chars"
            )

        # --- service availability --------------------------------------
        if not await self._client_v2.health_check():
            return ToolResult.error(
                "TRELLIS.2 microservice is not reachable — "
                "please start scripts/start-trellis2.ps1 before generating"
            )

        # --- read image off the loop -----------------------------------
        try:
            image_bytes = await asyncio.to_thread(abs_image_path.read_bytes)
        except OSError as exc:
            return ToolResult.error(f"Failed to read image: {exc}")

        # --- VRAM swap + generate --------------------------------------
        unloaded_models: list[str] = []
        if cfg2.auto_vram_swap:
            unloaded_models = await self._unload_llm_for_swap()

        gen_error: str | None = None
        gen_result = None
        try:
            gen_result = await self._client_v2.generate_from_image(
                image_bytes,
                model_name,
                pipeline_type=pipeline_type,
                seed=cfg2.seed,
                decimation_target=cfg2.decimation_target,
                texture_size=cfg2.texture_size,
                image_mime=mime,
            )
        except Exception as exc:
            gen_error = f"TRELLIS.2 generation failed: {exc}"
            logger.error(gen_error)
        finally:
            # Best-effort unload of the TRELLIS.2 weights so the LLM can
            # reclaim VRAM cleanly even on failure or cancellation.
            try:
                await self._client_v2.unload_model()
            except Exception:
                pass

            if cfg2.auto_vram_swap and unloaded_models:
                await self._reload_llm_after_swap(unloaded_models)

        if gen_result is None:
            result_model_name = model_name
            result_format = "glb"
            result_pipeline_type = pipeline_type
            result_seed = cfg2.seed
        else:
            result_model_name = gen_result.base.model_name
            result_format = gen_result.base.format
            result_pipeline_type = gen_result.pipeline_type
            result_seed = gen_result.seed

        output_dir = PROJECT_ROOT / cfg2.model_output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{result_model_name}.glb"

        if gen_error and not output_path.is_file():
            return ToolResult.error(gen_error)
        if gen_result is None and not output_path.is_file():
            return ToolResult.error("TRELLIS.2 generation returned no result")

        # --- download generated GLB ------------------------------------
        glb_bytes: bytes | None = None
        try:
            glb_bytes = await self._client_v2.download_model(result_model_name)
        except Exception as exc:
            if not output_path.is_file():
                return ToolResult.error(f"Failed to download model: {exc}")
            glb_bytes = await asyncio.to_thread(output_path.read_bytes)
            logger.warning(
                "Recovered TRELLIS.2 model '{}' from local output after download error: {}",
                result_model_name, exc,
            )
        else:
            await asyncio.to_thread(output_path.write_bytes, glb_bytes)

        if gen_error:
            logger.warning(
                "Recovered TRELLIS.2 model '{}' from local output after generation error: {}",
                result_model_name, gen_error,
            )
        if glb_bytes is None:
            return ToolResult.error("TRELLIS.2 generation produced no model bytes")

        elapsed = (time.perf_counter() - start) * 1000
        payload = {
            "model_name": result_model_name,
            "format": result_format,
            "size_bytes": len(glb_bytes),
            "file_path": str(output_path),
            "export_url": f"/api/cad/models/{result_model_name}",
            "source_image": image_path_arg,
            "pipeline_type": result_pipeline_type,
            "seed": result_seed,
        }
        logger.info(
            "3D model '{}' generated from image ({} bytes, {:.0f}ms, pipeline={})",
            result_model_name, len(glb_bytes), elapsed,
            result_pipeline_type,
        )
        return ToolResult.ok(
            payload,
            content_type="application/json",
            execution_time_ms=elapsed,
        )
