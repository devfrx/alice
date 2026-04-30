"""AL\\CE — Service orchestrator REST endpoints.

Endpoints:

* ``GET    /api/services``                       — list all services.
* ``GET    /api/services/{name}/health``         — single-service snapshot.
* ``POST   /api/services/{name}/restart``        — schedule a restart.
* ``GET    /api/services/{name}/models``         — downloadable model catalog.
* ``GET    /api/services/{name}/models/installed`` — installed models on disk.
* ``POST   /api/services/{name}/models/{model_id}/download`` — fetch a model.
* ``GET    /api/services/{name}/config``         — current trellis* config.
* ``POST   /api/services/{name}/configure``      — update trellis* config.
* ``GET    /api/services/trellis2/setup-guide``  — markdown setup walkthrough.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from loguru import logger

from backend.core.context import AppContext
from backend.services.model_downloader import CATALOG, list_catalog

router = APIRouter(tags=["services"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


def _orchestrator(request: Request):
    ctx = _ctx(request)
    orch = getattr(ctx, "orchestrator", None)
    if orch is None:
        raise HTTPException(
            status_code=503,
            detail="Service orchestrator not initialised",
        )
    return orch


def _downloader(request: Request):
    ctx = _ctx(request)
    dl = getattr(ctx, "model_downloader", None)
    if dl is None:
        raise HTTPException(
            status_code=503,
            detail="Model downloader not initialised",
        )
    return dl


def _config_service(request: Request):
    ctx = _ctx(request)
    svc = getattr(ctx, "config_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail="Layered config service not initialised",
        )
    return svc


# ---------------------------------------------------------------------------
# Health / lifecycle
# ---------------------------------------------------------------------------


@router.get("/services")
async def list_services(request: Request) -> list[dict[str, Any]]:
    """Return a snapshot of every registered managed service."""
    return _orchestrator(request).snapshot()


@router.get("/services/{name}/health")
async def get_service_health(
    request: Request, name: str,
) -> dict[str, Any]:
    """Return the cached health snapshot for *name*."""
    orch = _orchestrator(request)
    health = orch.health_of(name)
    if health is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown service '{name}'",
        )
    return {"name": name, **health.to_dict()}


@router.post("/services/{name}/restart")
async def restart_service(
    request: Request, name: str,
) -> JSONResponse:
    """Schedule a restart for *name* and return ``202 Accepted``."""
    orch = _orchestrator(request)
    try:
        await orch.restart(name)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Unknown service '{name}'",
        )
    logger.info("Service restart requested: {}", name)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"name": name, "status": "restart_scheduled"},
    )


# ---------------------------------------------------------------------------
# Model management (STT / TTS)
# ---------------------------------------------------------------------------


@router.get("/services/{name}/models")
async def list_service_models(
    request: Request, name: str,
) -> dict[str, Any]:
    """Return the downloadable model catalog for a service.

    Each entry includes ``installed: bool`` so the UI can mark models that
    are already on disk.

    Args:
        name: Service name (currently ``"stt"`` or ``"tts"``).
    """
    if name not in {"stt", "tts"}:
        raise HTTPException(
            status_code=404,
            detail=f"Service '{name}' has no downloadable models",
        )
    dl = _downloader(request)
    items = list_catalog(name)
    for item in items:
        item["installed"] = dl.is_present(name, item["model_id"])
        target = dl.target_dir(name, item["model_id"])
        item["path"] = str(target) if target else None
    return {"service": name, "models": items}


@router.get("/services/{name}/models/installed")
async def list_installed_models(
    request: Request, name: str,
) -> dict[str, Any]:
    """Return the catalog entries that are present on disk."""
    if name not in {"stt", "tts"}:
        raise HTTPException(
            status_code=404,
            detail=f"Service '{name}' has no downloadable models",
        )
    dl = _downloader(request)
    installed = [
        {**entry, "path": str(dl.target_dir(name, entry["model_id"]))}
        for entry in list_catalog(name)
        if dl.is_present(name, entry["model_id"])
    ]
    return {"service": name, "installed": installed}


@router.post("/services/{name}/models/{model_id}/download")
async def download_service_model(
    request: Request, name: str, model_id: str,
) -> JSONResponse:
    """Schedule a model download.

    Returns ``202 Accepted`` immediately; progress is broadcast on the
    ``/api/events/ws`` WebSocket as
    ``service.model_download_progress`` events.
    """
    if (name, model_id) not in CATALOG:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown model '{name}/{model_id}'",
        )
    dl = _downloader(request)

    if dl.is_present(name, model_id):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "service": name,
                "model_id": model_id,
                "status": "already_present",
                "path": str(dl.target_dir(name, model_id)),
            },
        )

    async def _runner() -> None:
        try:
            await dl.download(name, model_id)
        except Exception as exc:
            logger.exception(
                "Model download failed: {}/{} ({})", name, model_id, exc,
            )

    asyncio.create_task(_runner(), name=f"dl-{name}-{model_id}")
    logger.info("Model download requested: {}/{}", name, model_id)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "service": name,
            "model_id": model_id,
            "status": "download_scheduled",
        },
    )


# ---------------------------------------------------------------------------
# Trellis-specific endpoints
# ---------------------------------------------------------------------------


# Allow-list mapping: REST body key → dotted config path.  Both ``trellis``
# (text-to-3D, v1) and ``trellis2`` (image-to-3D, v2) accept the same shape;
# the route writes into the correct config namespace based on ``name``.
_TRELLIS_CONFIG_KEYS: dict[str, dict[str, str]] = {
    "trellis": {
        "enabled": "trellis.enabled",
        "service_url": "trellis.service_url",
        "trellis_dir": "trellis.trellis_dir",
        "trellis_model": "trellis.trellis_model",
    },
    "trellis2": {
        "enabled": "trellis2.enabled",
        "service_url": "trellis2.service_url",
        "trellis2_dir": "trellis2.trellis2_dir",
        "trellis2_model": "trellis2.trellis2_model",
    },
}


_TRELLIS_GUIDE_MD = """\
# TRELLIS.2 — Guida setup

TRELLIS.2 è un microservizio separato (porta **8091**) per la generazione
3D image-to-3D.  Richiede CUDA Toolkit, Visual Studio Build Tools e
~30-60 minuti di compilazione.

## 1. Prerequisiti

- **Sistema**: Windows 10/11 con NVIDIA GPU ≥ 16 GB VRAM.
- **CUDA Toolkit 12.x** (raccomandato 12.8) — *NON* 13.x.
  Scaricare da <https://developer.nvidia.com/cuda-toolkit-archive>.
- **Visual Studio Build Tools 2022** con il workload "Desktop C++"
  (cl.exe, MSVC v143, Windows SDK).
- **uv**: `winget install --id=astral-sh.uv -e`
- **Git**: `winget install --id=Git.Git -e`

## 2. Clonare il fork AL\\CE-friendly

Apri PowerShell **come amministratore** e da una directory a tua scelta:

```powershell
git clone --recurse-submodules https://github.com/devfrx/TRELLIS.2.git
```

Annota il percorso completo (es. `C:\\Users\\<tu>\\Source\\TRELLIS.2`).

## 3. Configurare AL\\CE

In questa pagina:

1. Incolla il percorso nel campo **TRELLIS.2 directory**.
2. Premi **Salva**.

Oppure modifica `%APPDATA%\\alice\\user.yaml`:

```yaml
trellis2:
  enabled: true
  trellis2_dir: "C:/Users/<tu>/Source/TRELLIS.2"
```

## 4. Installazione one-shot

Il primo avvio lancia automaticamente lo script di setup
(`scripts/start-trellis2.ps1 -Install`) che:

- crea un venv Python 3.10 dentro la cartella TRELLIS.2;
- installa torch + estensioni CUDA (flash-attn, nvdiffrast, CuMesh,
  FlexGEMM, o-voxel);
- scarica i pesi (~8 GB) al primo run.

Tempo stimato: **30-60 min** la prima volta.

## 5. Avvio normale

Dopo l'install, ogni Start successivo è veloce (~10-30 s warm-up).
Lo status passa da `starting` a `up` quando `http://localhost:8091/health`
risponde 200.

## Troubleshooting

| Problema | Soluzione |
|----------|-----------|
| `nvcc fatal: cannot find compiler 'cl.exe'` | Installa Visual Studio Build Tools |
| `CUDA version (13.x) mismatches PyTorch (12.8)` | Disinstalla CUDA 13 o imposta `CUDA_HOME` su CUDA 12.x |
| `flash-attn` build OOM | Chiudi browser/IDE durante il build, serve ~16 GB RAM |
| Status sempre `down` | Verifica che `start-trellis2.ps1` parta a mano dal terminale |
"""


@router.get("/services/trellis2/setup-guide")
async def trellis_setup_guide() -> dict[str, str]:
    """Return the in-app setup walkthrough for TRELLIS.2."""
    return {
        "service": "trellis2",
        "format": "markdown",
        "content": _TRELLIS_GUIDE_MD,
    }


@router.get("/services/{name}/config")
async def get_trellis_config(
    request: Request, name: str,
) -> dict[str, Any]:
    """Return the current ``trellis`` or ``trellis2`` config snapshot.

    Used by the configure card to prefill its form on mount instead of
    parsing the free-form ``health.detail`` string.
    """
    if name not in _TRELLIS_CONFIG_KEYS:
        raise HTTPException(
            status_code=404,
            detail=f"Service '{name}' has no configurable settings",
        )
    cfg_svc = _config_service(request)
    resolved = cfg_svc.get_resolved()
    section = getattr(resolved, name, None)
    if section is None:
        raise HTTPException(
            status_code=404,
            detail=f"Config section '{name}' not present in resolved schema",
        )
    return {
        "service": name,
        "config": {
            key: getattr(section, key.split(".")[-1], None)
            for key in _TRELLIS_CONFIG_KEYS[name]
        },
    }


@router.post("/services/{name}/configure")
async def configure_trellis(
    request: Request, name: str,
) -> dict[str, Any]:
    """Persist Trellis / Trellis2 configuration into the user layer.

    Body (all optional, keys depend on service variant)::

        # trellis (v1)
        {"enabled": true, "trellis_dir": "...", "trellis_model": "...",
         "service_url": "http://localhost:8090"}

        # trellis2 (v2)
        {"enabled": true, "trellis2_dir": "...", "trellis2_model": "...",
         "service_url": "http://localhost:8091"}

    Unknown keys are ignored silently to keep the API forward-compatible.
    """
    allowed = _TRELLIS_CONFIG_KEYS.get(name)
    if allowed is None:
        raise HTTPException(
            status_code=404,
            detail=f"Service '{name}' is not configurable via this endpoint",
        )
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")

    cfg_svc = _config_service(request)
    updated: dict[str, Any] = {}
    dir_key = "trellis_dir" if name == "trellis" else "trellis2_dir"

    for key, value in body.items():
        path = allowed.get(key)
        if path is None:
            continue
        if key == dir_key and value:
            cleaned = str(value).strip().strip('"')
            if cleaned and not Path(cleaned).is_dir():
                raise HTTPException(
                    status_code=400,
                    detail=f"Directory does not exist: {cleaned}",
                )
            value = cleaned
        try:
            await cfg_svc.set(path, value)
            updated[key] = value
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to set {path}: {exc}",
            )

    logger.info("'{}' configuration updated: {}", name, list(updated))
    return {"service": name, "updated": updated}
