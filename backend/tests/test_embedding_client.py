"""Tests for the Embedding Client (Phase 9)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIMS = 384
MODEL = "text-embedding-nomic-embed-text-v1.5"
BASE_URL = "http://localhost:1234"


def _openai_response(vectors: list[list[float]]) -> dict:
    """Build a fake OpenAI-compatible /v1/embeddings response."""
    return {
        "data": [{"embedding": vec, "index": i} for i, vec in enumerate(vectors)],
        "model": MODEL,
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }


def _make_httpx_response(
    payload: dict,
    status_code: int = 200,
) -> httpx.Response:
    """Create an httpx.Response from a dict payload."""
    import json

    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("POST", f"{BASE_URL}/v1/embeddings"),
    )


# ---------------------------------------------------------------------------
# Tests — OpenAI backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_encode_success():
    """OpenAI encode returns the expected vector on success."""
    from backend.services.embedding_client import EmbeddingClient

    expected = [0.1, 0.2, 0.3]
    mock_response = _make_httpx_response(_openai_response([expected]))

    with patch("backend.services.embedding_client.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=mock_response)
        instance.aclose = AsyncMock()
        MockClient.return_value = instance

        client = EmbeddingClient(
            base_url=BASE_URL, model=MODEL, dimensions=DIMS,
        )
        result = await client.encode("hello world")

    assert result == expected


@pytest.mark.asyncio
async def test_openai_encode_batch():
    """OpenAI encode_batch returns correct list of vectors."""
    from backend.services.embedding_client import EmbeddingClient

    vectors = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    mock_response = _make_httpx_response(_openai_response(vectors))

    with patch("backend.services.embedding_client.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=mock_response)
        instance.aclose = AsyncMock()
        MockClient.return_value = instance

        client = EmbeddingClient(
            base_url=BASE_URL, model=MODEL, dimensions=DIMS,
        )
        result = await client.encode_batch(["a", "b", "c"])

    assert result == vectors
    assert len(result) == 3


# ---------------------------------------------------------------------------
# Tests — Fallback to fastembed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_failure_fastembed_fallback():
    """ConnectError on OpenAI triggers fastembed fallback."""
    from backend.services.embedding_client import EmbeddingClient

    fallback_vec = [0.9, 0.8, 0.7]

    with (
        patch("backend.services.embedding_client.httpx.AsyncClient") as MockClient,
        patch(
            "backend.services.embedding_client.FastEmbedClient",
        ) as MockFallback,
    ):
        # OpenAI side — raise ConnectError
        instance = AsyncMock()
        instance.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused"),
        )
        instance.aclose = AsyncMock()
        MockClient.return_value = instance

        # fastembed side — return a vector
        fb_instance = MagicMock()
        fb_instance.encode = AsyncMock(return_value=fallback_vec)
        MockFallback.return_value = fb_instance

        client = EmbeddingClient(
            base_url=BASE_URL, model=MODEL, dimensions=DIMS,
            fallback_enabled=True,
        )
        result = await client.encode("test text")

    assert result == fallback_vec
    fb_instance.encode.assert_called_once()


@pytest.mark.asyncio
async def test_openai_timeout_fastembed_fallback():
    """Timeout on OpenAI triggers fastembed fallback."""
    from backend.services.embedding_client import EmbeddingClient

    fallback_vec = [0.5, 0.4, 0.3]

    with (
        patch("backend.services.embedding_client.httpx.AsyncClient") as MockClient,
        patch(
            "backend.services.embedding_client.FastEmbedClient",
        ) as MockFallback,
    ):
        instance = AsyncMock()
        instance.post = AsyncMock(
            side_effect=httpx.ReadTimeout("read timed out"),
        )
        instance.aclose = AsyncMock()
        MockClient.return_value = instance

        fb_instance = MagicMock()
        fb_instance.encode = AsyncMock(return_value=fallback_vec)
        MockFallback.return_value = fb_instance

        client = EmbeddingClient(
            base_url=BASE_URL, model=MODEL, dimensions=DIMS,
            fallback_enabled=True,
        )
        result = await client.encode("timeout text")

    assert result == fallback_vec
    fb_instance.encode.assert_called_once()


@pytest.mark.asyncio
async def test_openai_http_status_error_fastembed_fallback():
    """HTTPStatusError on OpenAI triggers fastembed fallback."""
    from backend.services.embedding_client import EmbeddingClient

    fallback_vec = [0.7, 0.6, 0.5]
    error_response = httpx.Response(
        status_code=500,
        request=httpx.Request("POST", f"{BASE_URL}/v1/embeddings"),
    )

    with (
        patch("backend.services.embedding_client.httpx.AsyncClient") as MockClient,
        patch(
            "backend.services.embedding_client.FastEmbedClient",
        ) as MockFallback,
    ):
        instance = AsyncMock()
        instance.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=error_response.request,
                response=error_response,
            ),
        )
        instance.aclose = AsyncMock()
        MockClient.return_value = instance

        fb_instance = MagicMock()
        fb_instance.encode = AsyncMock(return_value=fallback_vec)
        MockFallback.return_value = fb_instance

        client = EmbeddingClient(
            base_url=BASE_URL, model=MODEL, dimensions=DIMS,
            fallback_enabled=True,
        )
        result = await client.encode("error text")

    assert result == fallback_vec
    fb_instance.encode.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — Properties & lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dimensions_property():
    """dimensions property returns the configured value."""
    from backend.services.embedding_client import EmbeddingClient

    with patch("backend.services.embedding_client.httpx.AsyncClient"):
        client = EmbeddingClient(
            base_url=BASE_URL, model=MODEL, dimensions=DIMS,
        )

    assert client.dimensions == DIMS


@pytest.mark.asyncio
async def test_close():
    """close() calls the underlying HTTP client's aclose."""
    from backend.services.embedding_client import EmbeddingClient

    with patch("backend.services.embedding_client.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.aclose = AsyncMock()
        MockClient.return_value = instance

        client = EmbeddingClient(
            base_url=BASE_URL, model=MODEL, dimensions=DIMS,
        )
        await client.close()

    instance.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests — Fallback disabled / unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_disabled():
    """With fallback_enabled=False, OpenAI failure raises instead of falling back."""
    from backend.services.embedding_client import EmbeddingClient

    with patch("backend.services.embedding_client.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused"),
        )
        instance.aclose = AsyncMock()
        MockClient.return_value = instance

        client = EmbeddingClient(
            base_url=BASE_URL, model=MODEL, dimensions=DIMS,
            fallback_enabled=False,
        )

        with pytest.raises(RuntimeError, match="fallback is disabled"):
            await client.encode("should fail")


@pytest.mark.asyncio
async def test_fastembed_not_available():
    """When fastembed is not installed, construction raises ImportError."""
    from backend.services.embedding_client import EmbeddingClient

    with (
        patch("backend.services.embedding_client.httpx.AsyncClient") as MockClient,
        patch(
            "backend.services.embedding_client.FastEmbedClient",
            side_effect=ImportError("No module named 'fastembed'"),
        ),
    ):
        instance = AsyncMock()
        instance.aclose = AsyncMock()
        MockClient.return_value = instance

        # FastEmbedClient() is called during __init__ when fallback_enabled,
        # so ImportError propagates at construction time.
        with pytest.raises(ImportError):
            EmbeddingClient(
                base_url=BASE_URL, model=MODEL, dimensions=DIMS,
                fallback_enabled=True,
            )
