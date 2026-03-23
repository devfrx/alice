"""AL\\CE — TRELLIS microservice HTTP client.

Async client wrapping the local TRELLIS 3D generation microservice.
Handles health checks, text/image-to-3D generation, model download,
and model unloading.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from loguru import logger


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Immutable result from a TRELLIS 3D generation call.

    Attributes:
        model_name: Name of the generated 3D model file.
        format: File format (e.g. ``"glb"``).
        size_bytes: Size of the generated file in bytes.
        file_path: Path on the TRELLIS server where the model is stored.
    """

    model_name: str
    format: str
    size_bytes: int
    file_path: str


def _validate_local_url(url: str) -> None:
    """Validate that *url* points to a local TRELLIS microservice.

    Only ``http`` / ``https`` schemes targeting ``localhost`` or
    ``127.0.0.1`` are accepted.  This is intentionally less restrictive
    than :func:`validate_url_ssrf` because the TRELLIS service runs
    locally by design.

    Raises:
        ValueError: If the URL scheme or hostname is not allowed.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"TRELLIS service URL must use http or https, got '{parsed.scheme}'"
        )
    hostname = (parsed.hostname or "").lower()
    if hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            f"TRELLIS service must run on localhost or 127.0.0.1, got '{hostname}'"
        )


class TrellisClient:
    """Async HTTP client for the TRELLIS 3D generation microservice.

    Args:
        base_url: Base URL of the TRELLIS service (must be localhost).
        timeout_s: Default request timeout in seconds.
        max_model_size_mb: Maximum allowed GLB download size in megabytes.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: int = 120,
        max_model_size_mb: int = 100,
    ) -> None:
        _validate_local_url(base_url)
        self._base_url = base_url.rstrip("/")
        self._max_model_bytes = max_model_size_mb * 1024 * 1024
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(timeout_s),
                write=10.0,
                pool=10.0,
            ),
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check whether the TRELLIS microservice is reachable.

        Returns:
            ``True`` if the service responds to ``GET /health``.
        """
        try:
            resp = await self._client.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def get_status(self) -> dict | None:
        """Return the full health/status payload from the TRELLIS server.

        Returns:
            A dict with ``model_name``, ``model_loaded``, etc., or
            ``None`` if the server is unreachable.
        """
        try:
            resp = await self._client.get("/health", timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    async def request_model(self, model_name: str) -> bool:
        """Ask the TRELLIS server to switch to a specific model.

        Args:
            model_name: One of ``TRELLIS-image-large``,
                ``TRELLIS-text-large``, ``TRELLIS-text-base``.

        Returns:
            ``True`` if the server accepted or already had the model.
        """
        try:
            resp = await self._client.post(
                "/load",
                data={"model": model_name},
            )
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("TRELLIS model switch failed: {}", exc)
            return False

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def generate_from_image(
        self,
        image_bytes: bytes,
        model_name: str,
        seed: int = -1,
    ) -> GenerationResult:
        """Generate a 3D model from an image.

        Args:
            image_bytes: Raw image data (PNG/JPEG).
            model_name: Desired output name for the 3D model.
            seed: Generation seed (-1 for random).

        Returns:
            A :class:`GenerationResult` with generation metadata.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
        """
        resp = await self._client.post(
            "/generate",
            files={"image": ("input.png", image_bytes, "image/png")},
            data={"output_name": model_name, "seed": str(seed)},
        )
        resp.raise_for_status()
        data = resp.json()
        return GenerationResult(
            model_name=data["model_name"],
            format=data.get("format", "glb"),
            size_bytes=data.get("size_bytes", 0),
            file_path=data.get("file_path", ""),
        )

    async def generate_from_text(
        self,
        prompt: str,
        model_name: str,
        seed: int = -1,
    ) -> GenerationResult:
        """Generate a 3D model from a text description.

        Args:
            prompt: Natural-language description of the desired 3D model.
            model_name: Desired output name for the 3D model.
            seed: Generation seed (-1 for random).

        Returns:
            A :class:`GenerationResult` with generation metadata.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
        """
        resp = await self._client.post(
            "/generate",
            data={
                "prompt": prompt,
                "output_name": model_name,
                "seed": str(seed),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return GenerationResult(
            model_name=data["model_name"],
            format=data.get("format", "glb"),
            size_bytes=data.get("size_bytes", 0),
            file_path=data.get("file_path", ""),
        )

    # ------------------------------------------------------------------
    # Download / Unload
    # ------------------------------------------------------------------

    async def download_model(self, model_name: str) -> bytes:
        """Download a generated GLB file from the TRELLIS service.

        Args:
            model_name: Name of the model to download.

        Returns:
            Raw bytes of the GLB file.

        Raises:
            ValueError: If the file exceeds ``max_model_size_mb``.
            httpx.HTTPStatusError: On non-2xx responses.
        """
        resp = await self._client.get(f"/models/{model_name}")
        resp.raise_for_status()
        if len(resp.content) > self._max_model_bytes:
            raise ValueError(
                f"Model file exceeds maximum allowed size "
                f"({len(resp.content)} > {self._max_model_bytes} bytes)"
            )
        return resp.content

    async def unload_model(self) -> None:
        """Ask the TRELLIS service to unload the current model.

        Best-effort — errors are logged but not raised.
        """
        try:
            resp = await self._client.post("/unload")
            resp.raise_for_status()
            logger.debug("TRELLIS model unloaded")
        except Exception as exc:
            logger.warning("TRELLIS unload failed (best-effort): {}", exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
