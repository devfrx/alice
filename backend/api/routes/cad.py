"""AL\\CE — CAD / 3D model REST endpoints.

Serves generated GLB files and provides a health-check proxy for the
TRELLIS microservice.
"""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import FileResponse

from backend.core.config import PROJECT_ROOT

router = APIRouter(prefix="/cad", tags=["cad"])

_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,64}$")


@router.get("/models/{model_name}")
async def get_model(model_name: str, request: Request) -> FileResponse:
    """Serve a generated GLB file by name.

    Args:
        model_name: Alphanumeric model identifier (max 64 chars).
        request: The incoming HTTP request.

    Raises:
        HTTPException 400: If the model name is invalid.
        HTTPException 404: If the GLB file does not exist.
    """
    if not _MODEL_NAME_RE.match(model_name):
        raise HTTPException(400, "Invalid model name")

    ctx = request.app.state.context
    output_dir = PROJECT_ROOT / ctx.config.trellis.model_output_dir
    file_path = (output_dir / f"{model_name}.glb").resolve()

    if not file_path.is_relative_to(output_dir.resolve()):
        raise HTTPException(400, "Invalid model path")
    if not file_path.is_file():
        raise HTTPException(404, "Model not found")

    return FileResponse(
        path=file_path,
        media_type="model/gltf-binary",
        filename=f"{model_name}.glb",
    )


@router.get("/models")
async def list_models(request: Request) -> dict:
    """List all generated GLB models.

    Returns:
        A dict with a ``models`` key listing available model names.
    """
    ctx = request.app.state.context
    output_dir = PROJECT_ROOT / ctx.config.trellis.model_output_dir
    await asyncio.to_thread(
        output_dir.mkdir, parents=True, exist_ok=True,
    )

    models = await asyncio.to_thread(
        lambda: sorted(p.stem for p in output_dir.glob("*.glb")),
    )
    return {"models": models}


@router.get("/health")
async def health(request: Request) -> dict:
    """Proxy health check to the TRELLIS microservice.

    Returns:
        ``{"status": "ok"}`` if reachable, ``{"status": "unreachable"}``
        otherwise.
    """
    ctx = request.app.state.context
    pm = ctx.plugin_manager
    if pm is None:
        raise HTTPException(503, "Plugin manager not available")

    plugin = pm.get_plugin("cad_generator")
    if plugin is None or plugin.client is None:
        return {"status": "unreachable", "detail": "cad_generator plugin not loaded"}

    reachable = await plugin.client.health_check()
    return {"status": "ok" if reachable else "unreachable"}
