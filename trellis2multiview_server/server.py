"""TRELLIS.2 multi-view microservice — image(s)-to-3D with multi-view conditioning.

Sibling of ``trellis2_server/server.py``.  Where the single-image
service exposes ``pipeline.run(image)``, this one exposes
``pipeline.run_multi_image([image_1, image_2, ...])`` so the LLM /
frontend can drive a higher-quality reconstruction by uploading several
photos of the same object taken from different angles.

The vendored pipeline lives in the ``cpuai/Trellis.2.multiview`` clone
(by default ``<workspace>/TRELLIS.2.multiview``).  All other plumbing
(progress polling, VRAM-friendly idle state, REST surface) intentionally
mirrors the single-image service so the frontend can treat both as
parametric variants of the same kind.

IMPORTANT — GPU isolation
--------------------------
This file must NEVER ``import torch`` (or any module that pulls in
torch) at module level.  A module-level import would create a CUDA
context the moment the process starts and steal ~300-500 MB of VRAM
from co-resident processes such as LM Studio.  All torch / trellis2
imports are deferred to the functions that actually need them.

Usage:
    python server.py [--model microsoft/TRELLIS.2-4B] [--port 8092]
                     [--trellis2multiview-dir /path/to/TRELLIS.2.multiview]
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
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("CUDA_MODULE_LOADING", "LAZY")
# The multiview fork also forces ``flash_attn_3`` on Linux but falls
# back to ``sdpa`` on Windows, so we leave ATTN_BACKEND unset and let
# the pipeline auto-detect.
_venv_scripts = str(Path(sys.executable).parent)
if _venv_scripts not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _venv_scripts + os.pathsep + os.environ.get("PATH", "")
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

app = FastAPI(title="TRELLIS.2 Multi-view Microservice", version="1.0.0")
logger = logging.getLogger("trellis2multiview")

# ── Module-level state (mirrors trellis2_server/server.py) ────────
_pipeline = None
_model_name: str = "microsoft/TRELLIS.2-4B"
_output_dir: Path = Path(tempfile.gettempdir()) / "trellis2multiview_output"
_generation_lock = asyncio.Lock()
_state_lock = threading.Lock()
_generation_busy = False
_generation_started_at: float | None = None
_generation_name: str | None = None
_generation_pipeline_type: str | None = None
_generation_image_count: int = 0

# Sampling stages, in order, emitted by the multi-view pipeline.  The
# multi-view fork issues the same three diffusion bars as the single-
# image variant, so the totals match what the frontend already expects.
_PROGRESS_STAGES: list[tuple[str, str, int]] = [
    ("sampling sparse structure", "Sparse structure", 12),
    ("sampling shape slat",       "Shape latent",     12),
    ("sampling texture slat",     "Texture latent",   12),
]
_PROGRESS_TOTAL_STEPS: int = sum(s[2] for s in _PROGRESS_STAGES)

_progress_lock = threading.Lock()
_progress_state: dict[str, object] = {
    "stage_index": -1,
    "stage_label": None,
    "stage_step": 0,
    "stage_total": 0,
    "global_step": 0,
    "global_total": _PROGRESS_TOTAL_STEPS,
    "phase": "init",
}

# Allowed pipeline types: same string namespace as the single-image
# service; the multi-view pipeline maps "1024_cascade"/"1536_cascade"
# internally and accepts plain "512" / "1024" too.
_ALLOWED_PIPELINE_TYPES = {"512", "1024", "1024_cascade", "1536_cascade"}

# Short-name → HuggingFace repo ID.  Only the published 4B checkpoint
# supports multi-view conditioning today.
_MODEL_ALIASES: dict[str, str] = {
    "TRELLIS.2-4B": "microsoft/TRELLIS.2-4B",
}

# Hard cap on the number of input views.  Keeps a single bad client
# from exhausting GPU memory by uploading 100 images.
_MAX_INPUT_IMAGES: int = 8


def _resolve_model_name(name: str) -> str:
    """Normalize a short model name to the full HuggingFace repo ID."""
    return _MODEL_ALIASES.get(name, name)


# ── Progress helpers (mirror trellis2_server/server.py) ───────────


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
    """Update the high-level phase tag."""
    with _progress_lock:
        _progress_state["phase"] = phase
        if phase == "postprocess":
            _progress_state["global_step"] = _PROGRESS_TOTAL_STEPS


def _update_sampling_progress(desc: str, n: int, total: int) -> None:
    """Update sampling progress from a tqdm callback."""
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
        return

    actual_total = total if total and total > 0 else expected_total
    cumulative_prior = sum(s[2] for s in _PROGRESS_STAGES[:stage_idx])
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
    """Monkey-patch tqdm to forward sampling progress.  Idempotent."""
    try:
        from tqdm import std as tqdm_std
    except Exception:  # pragma: no cover
        return

    if getattr(tqdm_std.tqdm, "_alice_mv_patch_version", 0) >= 1:
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
    tqdm_std.tqdm._alice_mv_patch_version = 1


# ── Pipeline lifecycle ────────────────────────────────────────────


def _load_pipeline():
    """Lazy-load the multi-view TRELLIS.2 pipeline on first request."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    _install_tqdm_progress_hook()

    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(_model_name)
    if getattr(pipeline, "rembg_model", None) is None:
        logger.warning(
            "TRELLIS.2 multi-view RMBG model was not loaded; "
            "non-transparent input images will not be preprocessed.",
        )
    pipeline.cuda()
    _pipeline = pipeline
    return _pipeline


def _unload_pipeline():
    """Release the pipeline from VRAM and shrink the CUDA cache."""
    import torch

    global _pipeline
    if _pipeline is not None:
        try:
            _pipeline.to("cpu")
        except Exception:
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
    image_count: int = 0,
) -> None:
    """Update the generation state exposed by ``/health``."""
    global _generation_busy, _generation_started_at
    global _generation_name, _generation_pipeline_type, _generation_image_count
    with _state_lock:
        _generation_busy = busy
        _generation_started_at = time.monotonic() if busy else None
        _generation_name = name if busy else None
        _generation_pipeline_type = pipeline_type if busy else None
        _generation_image_count = image_count if busy else 0


def _generation_state() -> dict[str, object]:
    """Return a thread-safe snapshot of the current generation state."""
    with _state_lock:
        started = _generation_started_at
        return {
            "busy": _generation_busy,
            "current_job_name": _generation_name,
            "current_pipeline_type": _generation_pipeline_type,
            "current_image_count": _generation_image_count,
            "current_job_elapsed_s": (
                round(time.monotonic() - started, 3)
                if started is not None else 0
            ),
        }


# ── Generation ────────────────────────────────────────────────────


def _has_cutout_alpha(image: Image.Image) -> bool:
    """Return true when an image already carries a non-opaque alpha mask."""
    if image.mode != "RGBA":
        return False
    alpha_min, _ = image.getchannel("A").getextrema()
    return alpha_min < 255


def _generate_glb_sync(
    *,
    images_bytes: list[bytes],
    seed: int,
    output_name: str,
    pipeline_type: str,
    decimation_target: int,
    texture_size: int,
) -> dict[str, object]:
    """Run the blocking multi-view pipeline in a worker thread."""
    import o_voxel  # local import — pulls torch + CUDA
    import torch

    _reset_progress(phase="init")
    pipeline = _load_pipeline()
    actual_seed = seed if seed >= 0 else int(time.time()) % (2**32)
    name = output_name or f"model_{uuid.uuid4().hex[:8]}"
    _output_dir.mkdir(parents=True, exist_ok=True)
    out_path = _output_dir / f"{name}.glb"

    pil_images = [
        Image.open(io.BytesIO(b)).convert("RGBA") for b in images_bytes
    ]
    needs_background_removal = any(
        not _has_cutout_alpha(image) for image in pil_images
    )
    if needs_background_removal and getattr(pipeline, "rembg_model", None) is None:
        raise RuntimeError(
            "Background removal model is not loaded. Upload RGBA PNGs with "
            "transparency, or verify the RMBG model download/install for "
            "TRELLIS.2.multiview.",
        )

    # ``return_latent=True`` mirrors the upstream Gradio app and gives
    # us the (shape_slat, tex_slat, res) triple required by
    # ``decode_latent`` for the GLB bake.  ``preprocess_image=True``
    # lets the fork run its own background-removal + crop pass on
    # any view that arrives without alpha.
    outputs, latents = pipeline.run_multi_image(
        pil_images,
        seed=actual_seed,
        preprocess_image=True,
        pipeline_type=pipeline_type,
        return_latent=True,
    )
    del outputs  # the GLB bake re-decodes from the latent triple

    _set_progress_phase("postprocess")

    shape_slat, tex_slat, res = latents
    mesh = pipeline.decode_latent(shape_slat, tex_slat, res)[0]

    # CuMesh post-processing allocates several GB of CUDA scratch
    # buffers; the diffusion submodules already moved to CPU at the
    # end of ``run_multi_image`` in low-VRAM mode, but the allocator
    # keeps fragmented blocks that raw cudaMalloc cannot reuse.
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.ipc_collect()

    mesh.simplify(16_777_216)  # nvdiffrast hard limit on vertex count

    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=pipeline.pbr_attr_layout,
        grid_size=res,
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
        "image_count": len(images_bytes),
    }


# ── Endpoints ─────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Lightweight health check — never touches CUDA when idle."""
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
        "service": "trellis2multiview",
        "gpu_available": gpu_available,
        "vram_free_mb": vram_free_mb,
        "model_loaded": _pipeline is not None,
        "model_name": _model_name,
        "max_input_images": _MAX_INPUT_IMAGES,
        "progress": progress_snapshot,
        **state,
    }


@app.post("/generate")
async def generate(
    images: list[UploadFile] = File(...),
    seed: int = Form(-1),
    output_name: str = Form(""),
    pipeline_type: str = Form("1024"),
    decimation_target: int = Form(500_000),
    texture_size: int = Form(4096),
):
    """Generate a 3D GLB model from one or more views of the same object.

    Args:
        images: One to ``_MAX_INPUT_IMAGES`` images (multipart files).
            Each image should show the same object from a different
            angle; alpha channel is honoured when present, otherwise
            the pipeline strips the background internally.
        seed: Random seed; ``-1`` picks a fresh seed each call.
        output_name: Optional alphanumeric filename stem.
        pipeline_type: One of ``512`` / ``1024`` / ``1024_cascade``
            / ``1536_cascade``.
        decimation_target: Target triangle count for the GLB.
        texture_size: Square PBR texture resolution.
    """
    if not images:
        raise HTTPException(400, "At least one input image is required.")
    if len(images) > _MAX_INPUT_IMAGES:
        raise HTTPException(
            400,
            f"Too many input images ({len(images)} > {_MAX_INPUT_IMAGES}). "
            "Provide fewer views.",
        )
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
            "TRELLIS.2 multi-view generation already in progress. "
            "Wait for it to finish.",
        )

    try:
        async with _generation_lock:
            images_bytes = [await up.read() for up in images]
            _set_generation_state(
                busy=True,
                name=name,
                pipeline_type=pipeline_type,
                image_count=len(images_bytes),
            )
            try:
                payload = await asyncio.to_thread(
                    _generate_glb_sync,
                    images_bytes=images_bytes,
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
        logger.exception("TRELLIS.2 multi-view generation failed")
        raise HTTPException(500, f"Generation failed: {exc}")

    return JSONResponse(payload)


@app.post("/unload")
async def unload():
    """Unload the model from VRAM to free memory for the LLM."""
    if _generation_lock.locked():
        raise HTTPException(409, "Cannot unload while generation is running.")
    _unload_pipeline()
    return {"status": "unloaded"}


@app.post("/load")
async def load_model(model: str = Form(...)):
    """Switch to a different TRELLIS.2 checkpoint at runtime."""
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
        description="TRELLIS.2 multi-view 3D generation microservice",
    )
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument(
        "--model",
        type=str,
        default="TRELLIS.2-4B",
        help=(
            "TRELLIS.2 model name or local path. "
            "Currently only 'TRELLIS.2-4B' (microsoft/TRELLIS.2-4B) supports "
            "multi-view conditioning."
        ),
    )
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument(
        "--trellis2multiview-dir",
        type=str,
        default=None,
        help="Path to the TRELLIS.2.multiview root directory.  Added to "
             "sys.path so that 'trellis2.*' imports resolve to the "
             "multi-view fork.",
    )
    args = parser.parse_args()

    # Inject the multi-view source tree.  Layout:
    #   <workspace>/alice/trellis2multiview_server/server.py
    #   <workspace>/TRELLIS.2.multiview/trellis2/__init__.py
    if args.trellis2multiview_dir:
        mv_root = Path(args.trellis2multiview_dir).resolve()
    else:
        mv_root = (
            Path(__file__).resolve().parent.parent.parent / "TRELLIS.2.multiview"
        )
    if mv_root.is_dir() and str(mv_root) not in sys.path:
        sys.path.insert(0, str(mv_root))

    _model_name = _resolve_model_name(args.model)
    if args.output_dir:
        _output_dir = Path(args.output_dir)

    uvicorn.run(app, host="127.0.0.1", port=args.port)
