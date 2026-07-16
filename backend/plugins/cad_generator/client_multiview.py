"""AL\\CE — TRELLIS.2 multi-view microservice HTTP client.

Sibling of :mod:`backend.plugins.cad_generator.client_v2`.  Where the
single-image client uploads a single ``image`` field, this one
uploads a *list* under field name ``images`` so the multi-view
pipeline can condition on several views of the same object.

The wire protocol matches ``alice/trellis2multiview_server/server.py``:

* ``POST /generate`` — multipart with ``images`` (1..N UploadFiles),
  ``output_name``, ``pipeline_type``, ``seed``, ``decimation_target``,
  ``texture_size``.
* ``GET /health`` — returns ``{model_name, model_loaded,
  max_input_images, ...}``.
* ``GET /models/{name}`` — returns the GLB bytes.
* ``POST /unload`` / ``POST /load`` — same as the single-image variant.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from loguru import logger

from backend.plugins.cad_generator.client import GenerationResult

# Pipeline types mirror ``trellis2multiview_server.server._ALLOWED_PIPELINE_TYPES``.
_ALLOWED_PIPELINE_TYPES: frozenset[str] = frozenset(
    {"512", "1024", "1024_cascade", "1536_cascade"}
)


@dataclass(frozen=True, slots=True)
class Trellis2MultiviewGenerationResult:
    """Multi-view image-to-3D result with TRELLIS.2-specific metadata."""

    base: GenerationResult
    pipeline_type: str
    seed: int
    image_count: int


def _validate_local_url(url: str) -> None:
    """Validate that *url* targets the local TRELLIS.2 multi-view service."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"TRELLIS.2 multi-view URL must use http/https, got '{parsed.scheme}'"
        )
    hostname = (parsed.hostname or "").lower()
    if hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            f"TRELLIS.2 multi-view must run on localhost, got '{hostname}'"
        )


class Trellis2MultiviewClient:
    """Async HTTP client for the TRELLIS.2 multi-view microservice.

    Args:
        base_url: Base URL (must be localhost). Defaults to port 8092.
        timeout_s: Read timeout in seconds — multi-view runs longer
            than single-image so the default is doubled.
        max_model_size_mb: Maximum accepted size for downloaded GLB files.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: int = 1800,
        max_model_size_mb: int = 10_000,
    ) -> None:
        _validate_local_url(base_url)
        self._base_url = base_url.rstrip("/")
        self._max_model_bytes = max_model_size_mb * 1024 * 1024
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(timeout_s),
                # Multi-view uploads are larger (N images instead of 1)
                # so allow more time for the multipart write.
                write=120.0,
                pool=10.0,
            ),
        )

    # ------------------------------------------------------------------
    # Health / status
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check whether the TRELLIS.2 multi-view microservice is reachable."""
        try:
            resp = await self._client.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def get_status(self) -> dict | None:
        """Return the full ``/health`` payload, or ``None`` if offline."""
        try:
            resp = await self._client.get("/health", timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    async def request_model(self, model_name: str) -> bool:
        """Ask the server to switch to a specific TRELLIS.2 checkpoint."""
        try:
            resp = await self._client.post(
                "/load", data={"model": model_name}
            )
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("TRELLIS.2 multi-view model switch failed: {}", exc)
            return False

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def generate_from_images(
        self,
        images_bytes: list[bytes],
        model_name: str,
        *,
        pipeline_type: str = "1024",
        seed: int = -1,
        decimation_target: int = 500_000,
        texture_size: int = 4096,
        image_mime: str = "image/png",
    ) -> Trellis2MultiviewGenerationResult:
        """Lift multiple views of the same object to a 3D GLB.

        Args:
            images_bytes: 1..N raw image payloads (PNG/JPEG).  Each
                image should depict the same object from a different
                angle.  The server enforces an upper bound (currently
                8); going much above 6 yields diminishing returns.
            model_name: Desired output filename stem (alphanumeric +
                underscore, max 64 chars — server-validated).
            pipeline_type: Resolution / quality preset.  One of
                ``512`` / ``1024`` / ``1024_cascade`` / ``1536_cascade``.
            seed: Random seed (``-1`` for random).
            decimation_target: Target triangle count for the GLB.
            texture_size: Square PBR texture resolution.
            image_mime: MIME type sent in the multipart payload.

        Returns:
            A :class:`Trellis2MultiviewGenerationResult` with the
            canonical generation metadata, plus pipeline / seed echo
            and the number of input views the server actually used.

        Raises:
            ValueError: If ``pipeline_type`` is not allowed or
                ``images_bytes`` is empty.
            httpx.HTTPStatusError: On non-2xx server responses.
        """
        if not images_bytes:
            raise ValueError("At least one input image is required.")
        if pipeline_type not in _ALLOWED_PIPELINE_TYPES:
            raise ValueError(
                f"Invalid pipeline_type '{pipeline_type}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_PIPELINE_TYPES))}"
            )

        ext = "jpg" if image_mime == "image/jpeg" else "png"
        # FastAPI / Starlette decode duplicate field names with the
        # *same* key as a list[UploadFile]; mirror that here by passing
        # a list of (key, tuple) pairs to httpx.
        files = [
            ("images", (f"view_{i}.{ext}", payload, image_mime))
            for i, payload in enumerate(images_bytes)
        ]
        resp = await self._client.post(
            "/generate",
            files=files,
            data={
                "output_name": model_name,
                "seed": str(seed),
                "pipeline_type": pipeline_type,
                "decimation_target": str(decimation_target),
                "texture_size": str(texture_size),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        base = GenerationResult(
            model_name=data["model_name"],
            format=data.get("format", "glb"),
            size_bytes=data.get("size_bytes", 0),
            file_path=data.get("file_path", ""),
        )
        return Trellis2MultiviewGenerationResult(
            base=base,
            pipeline_type=data.get("pipeline_type", pipeline_type),
            seed=int(data.get("seed", seed)),
            image_count=int(data.get("image_count", len(images_bytes))),
        )

    # ------------------------------------------------------------------
    # Download / unload
    # ------------------------------------------------------------------

    async def download_model(self, model_name: str) -> bytes:
        """Download a generated GLB."""
        resp = await self._client.get(f"/models/{model_name}")
        resp.raise_for_status()
        if len(resp.content) > self._max_model_bytes:
            raise ValueError(
                f"GLB exceeds maximum allowed size "
                f"({len(resp.content)} > {self._max_model_bytes} bytes)"
            )
        return resp.content

    async def unload_model(self) -> None:
        """Best-effort request to release VRAM on the multi-view server."""
        try:
            resp = await self._client.post("/unload")
            resp.raise_for_status()
            logger.debug("TRELLIS.2 multi-view model unloaded")
        except Exception as exc:
            logger.warning(
                "TRELLIS.2 multi-view unload failed (best-effort): {}", exc,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
