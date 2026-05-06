"""TRELLIS.2 microservice — minimal FastAPI wrapper for high-fidelity 3D generation.

Sibling of ``trellis_server/server.py`` but targets Microsoft's
**TRELLIS.2** (4B parameter image-to-3D model, ``microsoft/TRELLIS.2-4B``).

Runs as a separate Python 3.10-3.12 process, isolated from the AL\\CE
backend.  Exposes ``/generate``, ``/unload``, ``/health``, ``/load`` and
``/models/{name}`` on port 8091 by default (TRELLIS classic uses 8090).

IMPORTANT — GPU isolation
--------------------------
This file must NEVER ``import torch`` (or any module that pulls in
torch) at module level.  A module-level import creates a CUDA context
the moment the process starts, which steals ~300-500 MB of VRAM and
causes persistent GPU context-switching overhead that slows down
co-resident processes such as LM Studio.

All torch / trellis2 imports are therefore deferred to the functions
that actually need them (``_load_pipeline``, ``_unload_pipeline``,
``generate``).  When the server is idle, it is a plain FastAPI process
with **zero** GPU footprint.

Differences vs. the TRELLIS-classic server
-------------------------------------------
* **Image-only** — TRELLIS.2 does not ship a text-to-3D variant; the
  ``prompt`` form field is rejected.
* **Output pipeline** — uses ``o_voxel.postprocess.to_glb`` (the new
  field-free O-Voxel format) instead of ``trellis.utils.postprocessing_utils.to_glb``.
* **Pipeline type** — exposes the ``pipeline_type`` parameter
  (``512`` / ``1024`` / ``1024_cascade`` / ``1536_cascade``) which trades
  resolution for time (~3 s up to ~60 s on H100).

Usage:
    python server.py [--model microsoft/TRELLIS.2-4B] [--port 8091]
                     [--trellis2-dir /path/to/TRELLIS.2]
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import io
import logging
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

# ── Environment tweaks (set BEFORE any torch import) ──────────────
# Required by the TRELLIS.2 example for HDRI / EXR loading.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
# Helps keep VRAM fragmentation low across sequential generations.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
# Tell PyTorch to defer CUDA kernel loading until actually needed.
os.environ.setdefault("CUDA_MODULE_LOADING", "LAZY")
# Ensure the venv Scripts/ dir is on PATH so JIT tools like ninja are found.
_venv_scripts = str(Path(sys.executable).parent)
if _venv_scripts not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _venv_scripts + os.pathsep + os.environ.get("PATH", "")
# Auto-detect CUDA_HOME for nvdiffrast JIT compilation (nvcc, cudart.lib, headers).
if not os.environ.get("CUDA_HOME"):
    _cuda_base = Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA")
    if _cuda_base.is_dir():
        _versions = sorted(_cuda_base.iterdir(), reverse=True)
        if _versions and (_versions[0] / "bin" / "nvcc.exe").exists():
            os.environ["CUDA_HOME"] = str(_versions[0])
            os.environ.setdefault("CUDA_PATH", str(_versions[0]))

# ── Non-GPU imports only ──────────────────────────────────────────
import uvicorn  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from PIL import Image  # noqa: E402

app = FastAPI(title="TRELLIS.2 Microservice", version="1.0.0")
logger = logging.getLogger("trellis2")

# Set by __main__ — determines which pipeline class to load.
_pipeline = None
_model_name: str = "microsoft/TRELLIS.2-4B"
_output_dir: Path = Path(tempfile.gettempdir()) / "trellis2_output"
_generation_lock = asyncio.Lock()
_state_lock = threading.Lock()
_generation_busy = False
_generation_started_at: float | None = None
_generation_name: str | None = None
_generation_pipeline_type: str | None = None

# ── Progress tracking (populated by tqdm monkey-patch) ────────────
# Sampling stages (in execution order) emitted by the TRELLIS.2 pipeline.
# Each entry: tqdm description prefix → (human label, expected steps).
# The expected steps are used as the "total" weight for the global
# progress bar even before the first tqdm update arrives.
_PROGRESS_STAGES: list[tuple[str, str, int]] = [
    ("sampling sparse structure", "Sparse structure", 12),
    ("sampling shape slat",        "Shape latent",      12),
    ("sampling texture slat",      "Texture latent",    12),
]
_PROGRESS_TOTAL_STEPS: int = sum(s[2] for s in _PROGRESS_STAGES)

_progress_lock = threading.Lock()
_progress_state: dict[str, object] = {
    "stage_index": -1,        # 0-based index into _PROGRESS_STAGES (-1 = not yet sampling)
    "stage_label": None,      # human-readable phase name
    "stage_step": 0,          # current step within the active stage
    "stage_total": 0,         # total steps of the active stage
    "global_step": 0,         # cumulative step across all stages
    "global_total": _PROGRESS_TOTAL_STEPS,
    "phase": "init",          # "init" | "sampling" | "postprocess" | "done"
}


def _reset_progress(phase: str = "init") -> None:
    """Reset progress tracking to its starting state."""
    with _progress_lock:
        _progress_state.update({
            "stage_index": -1,
            "stage_label": None,
            "stage_step": 0,
            "stage_total": 0,
            "global_step": 0,
            "global_total": _PROGRESS_TOTAL_STEPS,
            "phase": phase,
        })


def _set_progress_phase(phase: str) -> None:
    """Update the high-level phase tag (``init``/``sampling``/``postprocess``/``done``)."""
    with _progress_lock:
        _progress_state["phase"] = phase
        if phase == "postprocess":
            # Force the bar to 100% of sampling so the UI shows we are
            # finalizing rather than still mid-stage.
            _progress_state["global_step"] = _PROGRESS_TOTAL_STEPS


def _update_sampling_progress(desc: str, n: int, total: int) -> None:
    """Update sampling progress from a tqdm callback.

    Args:
        desc: The raw tqdm bar description (e.g. ``"Sampling shape SLat"``).
        n: Current iteration count of that bar.
        total: Total iterations of that bar (may be 0 / unknown).
    """
    if not desc:
        return
    desc_l = desc.lower()
    stage_idx = -1
    label = None
    expected_total = 0
    for i, (prefix, lbl, weight) in enumerate(_PROGRESS_STAGES):
        if desc_l.startswith(prefix):
            stage_idx = i
            label = lbl
            expected_total = weight
            break
    if stage_idx < 0:
        return  # not a sampling bar we care about

    actual_total = total if total and total > 0 else expected_total
    cumulative_prior = sum(s[2] for s in _PROGRESS_STAGES[:stage_idx])
    # Clamp stage step to actual_total to keep the global counter monotonic.
    safe_n = min(max(n, 0), actual_total)
    with _progress_lock:
        _progress_state.update({
            "stage_index": stage_idx,
            "stage_label": label,
            "stage_step": safe_n,
            "stage_total": actual_total,
            "global_step": cumulative_prior + safe_n,
            "global_total": _PROGRESS_TOTAL_STEPS,
            "phase": "sampling",
        })


def _install_tqdm_progress_hook() -> None:
    """Monkey-patch tqdm to forward sampling progress to ``_progress_state``.

    Idempotent — calling twice is a no-op.  Hooks both ``__init__`` and
    ``update`` so we capture the very first frame (n=0) as well as
    every subsequent step the diffusion loop emits.
    """
    try:
        from tqdm import std as tqdm_std
    except Exception:  # pragma: no cover — tqdm always installed via trellis2 deps
        return

    if getattr(tqdm_std.tqdm, "_alice_patch_version", 0) >= 3:
        return

    _orig_init = tqdm_std.tqdm.__init__
    _orig_update = tqdm_std.tqdm.update
    _orig_iter = tqdm_std.tqdm.__iter__
    _orig_display = tqdm_std.tqdm.display

    def _safe_desc(instance) -> str:
        return str(getattr(instance, "desc", None) or "")

    def _safe_int_attr(instance, attr: str) -> int:
        try:
            return int(getattr(instance, attr, 0) or 0)
        except Exception:
            return 0

    def _patched_init(self, *a, **kw):
        _orig_init(self, *a, **kw)
        try:
            _update_sampling_progress(
                _safe_desc(self), _safe_int_attr(self, "n"),
                _safe_int_attr(self, "total"),
            )
        except Exception:
            pass

    def _patched_update(self, n=1):
        result = _orig_update(self, n)
        try:
            _update_sampling_progress(
                _safe_desc(self), _safe_int_attr(self, "n"),
                _safe_int_attr(self, "total"),
            )
        except Exception:
            pass
        return result

    def _patched_iter(self):
        desc = _safe_desc(self)
        track = False
        manual_n = _safe_int_attr(self, "n")
        total = _safe_int_attr(self, "total")
        try:
            track = any(
                desc.lower().startswith(prefix)
                for prefix, _, _ in _PROGRESS_STAGES
            )
            if track:
                _update_sampling_progress(desc, manual_n, total)
        except Exception:
            track = False
        try:
            for obj in _orig_iter(self):
                yield obj
                if track:
                    try:
                        manual_n += 1
                        _update_sampling_progress(desc, manual_n, total)
                    except Exception:
                        track = False
        finally:
            if track and total > 0:
                try:
                    _update_sampling_progress(desc, min(manual_n, total), total)
                except Exception:
                    pass

    def _patched_display(self, *a, **kw):
        try:
            _update_sampling_progress(
                _safe_desc(self), _safe_int_attr(self, "n"),
                _safe_int_attr(self, "total"),
            )
        except Exception:
            pass
        return _orig_display(self, *a, **kw)

    tqdm_std.tqdm.__init__ = _patched_init
    tqdm_std.tqdm.update = _patched_update
    tqdm_std.tqdm.__iter__ = _patched_iter
    tqdm_std.tqdm.display = _patched_display
    tqdm_std.tqdm._alice_patch_version = 3

# Short-name → full HuggingFace repo ID mapping.
_MODEL_ALIASES: dict[str, str] = {
    "TRELLIS.2-4B": "microsoft/TRELLIS.2-4B",
}

# Allowed pipeline types per TRELLIS.2 paper (resolution / quality tradeoff).
_ALLOWED_PIPELINE_TYPES = {"512", "1024", "1024_cascade", "1536_cascade"}


def _resolve_model_name(name: str) -> str:
    """Normalize a short model name to the full HuggingFace repo ID."""
    return _MODEL_ALIASES.get(name, name)


def _load_pipeline():
    """Lazy-load the TRELLIS.2 image-to-3D pipeline on first request.

    This is the first point where ``torch`` and ``trellis2`` are imported,
    and therefore the first point where a CUDA context is created.
    """
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    # Hook tqdm before any trellis2 import so the very first sampling
    # bar is captured (the import itself triggers a couple of
    # "Loading weights" bars that we intentionally ignore via the
    # description filter).
    _install_tqdm_progress_hook()

    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    _pipeline = Trellis2ImageTo3DPipeline.from_pretrained(_model_name)
    _pipeline.cuda()
    return _pipeline


def _unload_pipeline():
    """Release the TRELLIS.2 model from VRAM and shrink the CUDA cache."""
    import torch

    global _pipeline
    if _pipeline is not None:
        try:
            _pipeline.to("cpu")
        except Exception:
            # Some pipelines move sub-modules independently; ignore failures.
            logger.exception("Failed to move pipeline to CPU before unload")
        del _pipeline
        _pipeline = None
        gc.collect()
        torch.cuda.empty_cache()


def _set_generation_state(
    *,
    busy: bool,
    name: str | None = None,
    pipeline_type: str | None = None,
) -> None:
    """Update the generation state exposed by ``/health``."""
    global _generation_busy, _generation_started_at
    global _generation_name, _generation_pipeline_type
    with _state_lock:
        _generation_busy = busy
        _generation_started_at = time.monotonic() if busy else None
        _generation_name = name if busy else None
        _generation_pipeline_type = pipeline_type if busy else None


def _generation_state() -> dict[str, object]:
    """Return a thread-safe snapshot of the current generation state."""
    with _state_lock:
        started = _generation_started_at
        return {
            "busy": _generation_busy,
            "current_job_name": _generation_name,
            "current_pipeline_type": _generation_pipeline_type,
            "current_job_elapsed_s": (
                round(time.monotonic() - started, 3)
                if started is not None else 0
            ),
        }


def _generate_glb_sync(
    *,
    image_bytes: bytes,
    seed: int,
    output_name: str,
    pipeline_type: str,
    decimation_target: int,
    texture_size: int,
) -> dict[str, object]:
    """Run the blocking TRELLIS.2 pipeline in a worker thread."""
    import o_voxel  # local import — pulls torch + CUDA

    _reset_progress(phase="init")
    pipeline = _load_pipeline()
    actual_seed = seed if seed >= 0 else int(time.time()) % (2**32)
    name = output_name or f"model_{uuid.uuid4().hex[:8]}"
    _output_dir.mkdir(parents=True, exist_ok=True)
    out_path = _output_dir / f"{name}.glb"

    pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    meshes = pipeline.run(
        pil_image,
        seed=actual_seed,
        pipeline_type=pipeline_type,
    )
    mesh = meshes[0]

    # Sampling is finished — from here on the work is CPU/GPU mesh
    # post-processing (decimation, UV unwrap, texture bake) which the
    # tqdm hook does not cover.
    _set_progress_phase("postprocess")

    # CuMesh post-processing (simplify + UV unwrap + texture bake)
    # allocates several GB of CUDA scratch buffers.  On consumer GPUs
    # (16 GB) the only way to make it fit is to evict the diffusion
    # weights from VRAM first.  In ``low_vram`` mode the per-step
    # modules are already swapped back to CPU at the end of
    # ``pipeline.run()``, but the allocator keeps fragmented blocks
    # around that CuMesh's raw cudaMalloc cannot reuse.
    # IMPORTANT: do not call ``pipeline.to('cpu')`` here — in low-VRAM
    # mode that rewrites ``self._device`` and breaks the next call by
    # sending per-step submodules to CPU.
    import torch  # local — already imported by pipeline.run
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.ipc_collect()

    # nvdiffrast hard limit on total vertex count.
    mesh.simplify(16_777_216)

    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=decimation_target,
        texture_size=texture_size,
        remesh=True,
        remesh_band=1,
        remesh_project=0,
        verbose=False,
    )
    glb.export(str(out_path), extension_webp=True)

    _set_progress_phase("done")

    return {
        "model_name": name,
        "file_path": str(out_path),
        "format": "glb",
        "size_bytes": out_path.stat().st_size,
        "pipeline_type": pipeline_type,
        "seed": actual_seed,
    }


# ── Endpoints ─────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Lightweight health check — never touches CUDA when idle.

    GPU/VRAM info is only returned when the pipeline is already loaded
    (meaning a CUDA context already exists).  When idle, this endpoint
    is essentially free.
    """
    vram_free_mb = 0
    gpu_available = False
    state = _generation_state()

    if _pipeline is not None and not state["busy"]:
        import torch
        gpu_available = torch.cuda.is_available()
        if gpu_available:
            vram_free_mb = torch.cuda.mem_get_info()[0] // (1024 * 1024)

    with _progress_lock:
        progress_snapshot = dict(_progress_state)

    return {
        "status": "ok",
        "service": "trellis2",
        "gpu_available": gpu_available,
        "vram_free_mb": vram_free_mb,
        "model_loaded": _pipeline is not None,
        "model_name": _model_name,
        "progress": progress_snapshot,
        **state,
    }


@app.post("/generate")
async def generate(
    image: UploadFile = File(...),
    seed: int = Form(-1),
    output_name: str = Form(""),
    pipeline_type: str = Form("512"),
    decimation_target: int = Form(500_000),
    texture_size: int = Form(4096),
):
    """Generate a 3D GLB model from an input image.

    Args:
        image: The image to lift to 3D (RGBA-friendly).
        seed: Random seed; ``-1`` picks a fresh seed each call.
        output_name: Optional alphanumeric filename stem.
        pipeline_type: One of ``512`` (~3 s), ``1024`` (~17 s),
            ``1024_cascade`` or ``1536_cascade`` (~60 s).
        decimation_target: Target triangle count for the exported GLB.
        texture_size: Square PBR texture resolution.
    """
    if pipeline_type not in _ALLOWED_PIPELINE_TYPES:
        raise HTTPException(
            400,
            f"Invalid pipeline_type '{pipeline_type}'. "
            f"Allowed: {', '.join(sorted(_ALLOWED_PIPELINE_TYPES))}",
        )

    name = output_name or f"model_{uuid.uuid4().hex[:8]}"
    if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", name):
        raise HTTPException(
            400, "output_name must be alphanumeric/underscore, max 64 chars.",
        )

    if _generation_lock.locked():
        raise HTTPException(
            409,
            "TRELLIS.2 generation already in progress. Wait for it to finish.",
        )

    try:
        async with _generation_lock:
            img_bytes = await image.read()
            _set_generation_state(
                busy=True,
                name=name,
                pipeline_type=pipeline_type,
            )
            try:
                payload = await asyncio.to_thread(
                    _generate_glb_sync,
                    image_bytes=img_bytes,
                    seed=seed,
                    output_name=name,
                    pipeline_type=pipeline_type,
                    decimation_target=decimation_target,
                    texture_size=texture_size,
                )
            finally:
                _set_generation_state(busy=False)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("TRELLIS.2 generation failed")
        raise HTTPException(500, f"Generation failed: {exc}")

    return JSONResponse(payload)


@app.post("/unload")
async def unload():
    """Unload the TRELLIS.2 model from VRAM to free memory for the LLM."""
    if _generation_lock.locked():
        raise HTTPException(409, "Cannot unload while generation is running.")
    _unload_pipeline()
    return {"status": "unloaded"}


@app.post("/load")
async def load_model(model: str = Form(...)):
    """Switch to a different TRELLIS.2 model at runtime."""
    global _model_name
    if _generation_lock.locked():
        raise HTTPException(409, "Cannot switch models while generation is running.")
    allowed = set(_MODEL_ALIASES.keys()) | set(_MODEL_ALIASES.values())
    if model not in allowed:
        raise HTTPException(
            400,
            f"Unknown model '{model}'. Allowed: "
            f"{', '.join(sorted(_MODEL_ALIASES.keys()))}",
        )
    resolved = _resolve_model_name(model)
    if resolved == _model_name and _pipeline is not None:
        return {"status": "already_loaded", "model_name": _model_name}

    _unload_pipeline()
    _model_name = resolved
    return {"status": "ok", "model_name": _model_name}


@app.get("/models/{model_name}")
async def get_model(model_name: str):
    """Download a previously generated GLB file by name."""
    if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", model_name):
        raise HTTPException(400, "Invalid model name.")
    path = _output_dir / f"{model_name}.glb"
    if not path.exists():
        raise HTTPException(404, f"Model '{model_name}' not found.")
    return FileResponse(
        path, media_type="model/gltf-binary", filename=f"{model_name}.glb",
    )


# ── Entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TRELLIS.2 3D generation microservice",
    )
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument(
        "--model",
        type=str,
        default="TRELLIS.2-4B",
        help=(
            "TRELLIS.2 model name or local path. "
            "Currently only 'TRELLIS.2-4B' (microsoft/TRELLIS.2-4B) is published."
        ),
    )
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument(
        "--trellis2-dir",
        type=str,
        default=None,
        help="Path to the TRELLIS.2 root directory. "
             "Added to sys.path so that 'trellis2.*' imports work when "
             "server.py is run from outside that directory.",
    )
    args = parser.parse_args()

    # Inject the TRELLIS.2 source tree so all 'trellis2.*' imports resolve.
    if args.trellis2_dir:
        trellis2_root = Path(args.trellis2_dir).resolve()
        if str(trellis2_root) not in sys.path:
            sys.path.insert(0, str(trellis2_root))
    else:
        # Fallback: assume TRELLIS.2 sits next to the alice repo root.
        # Layout: <workspace>/alice/trellis2_server/server.py
        #         <workspace>/TRELLIS.2/trellis2/__init__.py
        fallback = Path(__file__).resolve().parent.parent.parent / "TRELLIS.2"
        if fallback.is_dir() and str(fallback) not in sys.path:
            sys.path.insert(0, str(fallback))

    _model_name = _resolve_model_name(args.model)
    if args.output_dir:
        _output_dir = Path(args.output_dir)

    uvicorn.run(app, host="127.0.0.1", port=args.port)
