"""Tests for backend.plugins.cad_generator.client — TrellisClient."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from backend.plugins.cad_generator.client import GenerationResult, TrellisClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_REQUEST = httpx.Request("GET", "http://localhost:8090")


def _ok_response(json_data: dict | None = None, content: bytes = b"") -> httpx.Response:
    """Build a 200 httpx.Response with a request attached."""
    if json_data is not None:
        return httpx.Response(200, json=json_data, request=_DUMMY_REQUEST)
    return httpx.Response(200, content=content, request=_DUMMY_REQUEST)


def _error_response(status: int = 500, text: str = "Internal Server Error") -> httpx.Response:
    """Build an error httpx.Response."""
    return httpx.Response(status, text=text, request=_DUMMY_REQUEST)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TrellisClient:
    """Create a TrellisClient with the internal httpx client mocked out."""
    tc = TrellisClient(
        base_url="http://localhost:8090",
        timeout_s=10,
        max_model_size_mb=100,
    )
    tc._client = AsyncMock(spec=httpx.AsyncClient)
    return tc


# ===========================================================================
# 1. Health check
# ===========================================================================


class TestHealthCheck:
    """TrellisClient.health_check()."""

    @pytest.mark.asyncio
    async def test_health_check_success(self, client: TrellisClient) -> None:
        """GET /health returning 200 → True."""
        client._client.get = AsyncMock(return_value=_ok_response({"status": "ok"}))

        result = await client.health_check()

        assert result is True
        client._client.get.assert_awaited_once()
        call_args = client._client.get.call_args
        assert call_args[0][0] == "/health"

    @pytest.mark.asyncio
    async def test_health_check_failure_returns_false(self, client: TrellisClient) -> None:
        """Connection error → False (no exception propagated)."""
        client._client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        result = await client.health_check()

        assert result is False


# ===========================================================================
# 2. Generation
# ===========================================================================


_GENERATION_RESPONSE = {
    "model_name": "test_cube",
    "format": "glb",
    "size_bytes": 1024,
    "file_path": "/outputs/test_cube.glb",
}


class TestGeneration:
    """TrellisClient.generate_from_image / generate_from_text."""

    @pytest.mark.asyncio
    async def test_generate_from_image_success(self, client: TrellisClient) -> None:
        """POST /generate with image file → GenerationResult."""
        client._client.post = AsyncMock(
            return_value=_ok_response(_GENERATION_RESPONSE),
        )

        result = await client.generate_from_image(
            image_bytes=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
            model_name="test_cube",
            seed=42,
        )

        assert isinstance(result, GenerationResult)
        assert result.model_name == "test_cube"
        assert result.format == "glb"
        assert result.size_bytes == 1024
        assert result.file_path == "/outputs/test_cube.glb"
        client._client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_from_text_success(self, client: TrellisClient) -> None:
        """POST /generate with text prompt → GenerationResult."""
        client._client.post = AsyncMock(
            return_value=_ok_response(_GENERATION_RESPONSE),
        )

        result = await client.generate_from_text(
            prompt="a red cube with rounded edges",
            model_name="test_cube",
            seed=42,
        )

        assert isinstance(result, GenerationResult)
        assert result.model_name == "test_cube"
        assert result.format == "glb"
        assert result.size_bytes == 1024

    @pytest.mark.asyncio
    async def test_generate_http_error(self, client: TrellisClient) -> None:
        """HTTP 500 from microservice → HTTPStatusError propagated."""
        error_resp = _error_response(500, "GPU OOM")
        client._client.post = AsyncMock(return_value=error_resp)

        with pytest.raises(httpx.HTTPStatusError):
            await client.generate_from_text(
                prompt="a complex scene",
                model_name="oom_test",
            )


# ===========================================================================
# 3. Download
# ===========================================================================


class TestDownload:
    """TrellisClient.download_model."""

    @pytest.mark.asyncio
    async def test_download_model_success(self, client: TrellisClient) -> None:
        """GET /models/{name} → raw GLB bytes."""
        glb_data = b"glTF" + b"\x00" * 1000
        client._client.get = AsyncMock(return_value=_ok_response(content=glb_data))

        result = await client.download_model("test_cube")

        assert result == glb_data
        client._client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_download_model_exceeds_size(self, client: TrellisClient) -> None:
        """Response bigger than max_model_size_mb → ValueError."""
        # Config default is 100 MB; create oversized content
        huge = b"\x00" * (101 * 1_048_576)
        client._client.get = AsyncMock(return_value=_ok_response(content=huge))

        with pytest.raises(ValueError, match="exceeds maximum allowed size"):
            await client.download_model("huge_model")


# ===========================================================================
# 4. Unload
# ===========================================================================


class TestUnload:
    """TrellisClient.unload_model."""

    @pytest.mark.asyncio
    async def test_unload_model(self, client: TrellisClient) -> None:
        """POST /unload → success, no exception."""
        client._client.post = AsyncMock(return_value=_ok_response({"status": "unloaded"}))

        await client.unload_model()

        client._client.post.assert_awaited_once()


# ===========================================================================
# 5. URL validation
# ===========================================================================


class TestURLValidation:
    """TrellisClient constructor URL validation."""

    def test_url_validation_rejects_remote(self) -> None:
        """Remote private IP like 192.168.1.200 → ValueError on construction."""
        with pytest.raises(ValueError):
            TrellisClient(
                base_url="http://192.168.1.200:8090",
                timeout_s=10,
                max_model_size_mb=100,
            )

    def test_url_validation_allows_localhost(self) -> None:
        """localhost URL → no error on construction."""
        tc = TrellisClient(
            base_url="http://localhost:8090",
            timeout_s=10,
            max_model_size_mb=100,
        )
        assert tc._base_url == "http://localhost:8090"
