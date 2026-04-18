"""AL\\CE — TRELLIS.2 microservice HTTP client (image-to-3D).

Sibling of :mod:`backend.plugins.cad_generator.client` for the
**TRELLIS.2** (``microsoft/TRELLIS.2-4B``) microservice.  TRELLIS.2 is
image-only by design — there is no text-to-3D variant — so this client
exposes only :meth:`Trellis2Client.generate_from_image` plus the usual
health / download / unload helpers.

The wire protocol matches ``alice/trellis2_server/server.py``:

* ``POST /generate`` — multipart with ``image`` (UploadFile),
  ``output_name``, ``pipeline_type``, ``seed``, ``decimation_target``,
  ``texture_size``.
* ``GET /health`` — returns ``{model_name, model_loaded, ...}``.
* ``GET /models/{name}`` — returns the GLB bytes.
* ``POST /unload`` — best-effort VRAM release.
* ``POST /load`` — switch the served model.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from loguru import logger

# Re-export the shared GenerationResult dataclass so callers can keep a
# single import for both clients.  The TRELLIS.2 ``/generate`` response
# carries the same four canonical fields plus a couple of extras
# (``pipeline_type``, ``seed``) which we surface separately.
from backend.plugins.cad_generator.client import GenerationResult


# Pipeline types mirrored from ``trellis2_server.server._ALLOWED_PIPELINE_TYPES``.
# Kept here as a local constant so the client can validate before going
# over the wire (saves a 400 round-trip).
_ALLOWED_PIPELINE_TYPES: frozenset[str] = frozenset(
    {"512", "1024", "1024_cascade", "1536_cascade"}
)


@dataclass(frozen=True, slots=True)
class Trellis2GenerationResult:
    """Image-to-3D result with TRELLIS.2-specific metadata.

    Wraps :class:`GenerationResult` and adds the pipeline / seed echo
    returned by the TRELLIS.2 server, which callers sometimes log.
    """

    base: GenerationResult
    pipeline_type: str
    seed: int


def _validate_local_url(url: str) -> None:
    """Validate that *url* targets the local TRELLIS.2 microservice.

    Mirrors the helper in :mod:`client` — duplicated rather than
    imported to keep the two clients independently swappable.

    Raises:
        ValueError: If the URL scheme or hostname is not allowed.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"TRELLIS.2 service URL must use http or https, got '{parsed.scheme}'"
        )
    hostname = (parsed.hostname or "").lower()
    if hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            f"TRELLIS.2 service must run on localhost or 127.0.0.1, got '{hostname}'"
        )


class Trellis2Client:
    """Async HTTP client for the TRELLIS.2 image-to-3D microservice.

    Args:
        base_url: Base URL (must be localhost). Defaults to port 8091.
        timeout_s: Read timeout in seconds (4B model + 1536_cascade can
            reach ~60 s on H100; allow generous headroom on consumer GPUs).
        max_model_size_mb: Maximum accepted size for downloaded GLB files.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: int = 600,
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
                write=30.0,  # multipart upload of larger images
                pool=10.0,
            ),
        )

    # ------------------------------------------------------------------
    # Health / status
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check whether the TRELLIS.2 microservice is reachable."""
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
        """Ask the server to switch to a specific TRELLIS.2 checkpoint.

        Args:
            model_name: HuggingFace repo ID (currently only
                ``microsoft/TRELLIS.2-4B`` is published).

        Returns:
            ``True`` if the server accepted (or already had) the model.
        """
        try:
            resp = await self._client.post(
                "/load", data={"model": model_name}
            )
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("TRELLIS.2 model switch failed: {}", exc)
            return False

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def generate_from_image(
        self,
        image_bytes: bytes,
        model_name: str,
        *,
        pipeline_type: str = "512",
        seed: int = -1,
        decimation_target: int = 500_000,
        texture_size: int = 4096,
        image_mime: str = "image/png",
    ) -> Trellis2GenerationResult:
        """Lift an image to a 3D GLB via TRELLIS.2.

        Args:
            image_bytes: Raw image bytes (PNG/JPEG).
            model_name: Desired output filename stem (alphanumeric +
                underscore, max 64 chars — server-validated).
            pipeline_type: Resolution / quality preset. One of
                ``512`` / ``1024`` / ``1024_cascade`` / ``1536_cascade``.
            seed: Random seed (``-1`` for random).
            decimation_target: Target triangle count for the GLB.
            texture_size: Square PBR texture resolution.
            image_mime: MIME type sent in the multipart payload.

        Returns:
            A :class:`Trellis2GenerationResult` with the canonical
            generation metadata plus pipeline / seed echo.

        Raises:
            ValueError: If ``pipeline_type`` is not allowed.
            httpx.HTTPStatusError: On non-2xx server responses.
        """
        if pipeline_type not in _ALLOWED_PIPELINE_TYPES:
            raise ValueError(
                f"Invalid pipeline_type '{pipeline_type}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_PIPELINE_TYPES))}"
            )

        # The filename in the multipart tuple is irrelevant on the
        # server side (it discards it and reads the raw bytes), but a
        # valid extension keeps proxies / debug logs friendly.
        ext = "jpg" if image_mime == "image/jpeg" else "png"
        resp = await self._client.post(
            "/generate",
            files={"image": (f"input.{ext}", image_bytes, image_mime)},
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
        return Trellis2GenerationResult(
            base=base,
            pipeline_type=data.get("pipeline_type", pipeline_type),
            seed=int(data.get("seed", seed)),
        )

    # ------------------------------------------------------------------
    # Download / unload
    # ------------------------------------------------------------------

    async def download_model(self, model_name: str) -> bytes:
        """Download a generated GLB.

        Args:
            model_name: Name of the model (without extension).

        Raises:
            ValueError: If the GLB exceeds ``max_model_size_mb``.
            httpx.HTTPStatusError: On non-2xx responses.
        """
        resp = await self._client.get(f"/models/{model_name}")
        resp.raise_for_status()
        if len(resp.content) > self._max_model_bytes:
            raise ValueError(
                f"GLB exceeds maximum allowed size "
                f"({len(resp.content)} > {self._max_model_bytes} bytes)"
            )
        return resp.content

    async def unload_model(self) -> None:
        """Best-effort request to release VRAM on the TRELLIS.2 server."""
        try:
            resp = await self._client.post("/unload")
            resp.raise_for_status()
            logger.debug("TRELLIS.2 model unloaded")
        except Exception as exc:
            logger.warning("TRELLIS.2 unload failed (best-effort): {}", exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
