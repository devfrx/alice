"""O.M.N.I.A. — Embedding client with automatic fallback.

Provides vector embeddings for semantic memory search.  Two backends:

1. **OpenAIEmbeddingClient** — calls ``POST /v1/embeddings`` on the same
   LM Studio / Ollama server used for chat (primary, GPU-accelerated).
2. **FastEmbedClient** — pure-Python CPU fallback via ``fastembed``
   (no PyTorch required, ~33 MB model).

The :class:`EmbeddingClient` facade tries the API first and transparently
falls back to the CPU backend when the server is unreachable.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import httpx
from loguru import logger

# Dimensionality of the default fastembed CPU fallback model
# (BAAI/bge-small-en-v1.5).  Used by both FastEmbedClient and EmbeddingClient
# so that mismatched configs are caught early without relying on class
# attributes that tests may patch away.
_FASTEMBED_DEFAULT_DIMS: int = 384


# ----------------------------------------------------------------------- #
# Protocol
# ----------------------------------------------------------------------- #


class EmbeddingClientProtocol(Protocol):
    """Structural interface every embedding backend must satisfy."""

    async def encode(self, text: str) -> list[float]:
        """Return the embedding vector for a single piece of text."""
        ...

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for multiple texts."""
        ...

    @property
    def dimensions(self) -> int:
        """Number of dimensions each embedding vector has."""
        ...

    async def close(self) -> None:
        """Release resources held by the backend."""
        ...


# ----------------------------------------------------------------------- #
# Backend 1 — LM Studio / Ollama (OpenAI-compatible API)
# ----------------------------------------------------------------------- #


class OpenAIEmbeddingClient:
    """Calls the ``/v1/embeddings`` endpoint on LM Studio or Ollama.

    Args:
        base_url: Server origin, e.g. ``http://localhost:1234``.
        model: Embedding model tag (e.g. ``nomic-embed-text``).
        dim: Dimensionality of the model's output vectors.
    """

    def __init__(self, base_url: str, model: str, dim: int) -> None:
        self._model = model
        self._dim = dim
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )

    @property
    def dimensions(self) -> int:
        return self._dim

    async def encode(self, text: str) -> list[float]:
        """Encode a single text via the embeddings API."""
        resp = await self._client.post(
            "/v1/embeddings",
            json={"input": text, "model": self._model},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts in one API call."""
        resp = await self._client.post(
            "/v1/embeddings",
            json={"input": texts, "model": self._model},
        )
        resp.raise_for_status()
        data = resp.json()
        # API returns items sorted by index
        items = sorted(data["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]

    async def close(self) -> None:
        await self._client.aclose()


# ----------------------------------------------------------------------- #
# Backend 2 — fastembed (CPU-only fallback)
# ----------------------------------------------------------------------- #


class FastEmbedClient:
    """CPU-only embeddings via ``fastembed`` (lazy-loaded).

    Args:
        model_name: HuggingFace model id, default ``BAAI/bge-small-en-v1.5``
            (33 MB, 384 dimensions).
        dim: Vector dimensionality of the chosen model.
    """

    _DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
    _DEFAULT_DIM = _FASTEMBED_DEFAULT_DIMS

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        dim: int = _FASTEMBED_DEFAULT_DIMS,
    ) -> None:
        self._model_name = model_name
        self._dim = dim
        self._model: object | None = None  # lazily initialised

    @property
    def dimensions(self) -> int:
        return self._dim

    def _get_model(self) -> object:
        """Return the cached ``TextEmbedding`` instance, creating it on first use."""
        if self._model is None:
            try:
                from fastembed import TextEmbedding  # type: ignore[import-untyped]
            except ImportError as exc:
                raise RuntimeError(
                    "fastembed is not installed. "
                    "Install it with: pip install fastembed"
                ) from exc
            self._model = TextEmbedding(model_name=self._model_name)
            logger.info("fastembed model loaded: {}", self._model_name)
        return self._model

    async def encode(self, text: str) -> list[float]:
        """Encode a single text using the CPU model."""
        vectors = await asyncio.to_thread(self._encode_sync, [text])
        return vectors[0]

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts using the CPU model."""
        return await asyncio.to_thread(self._encode_sync, texts)

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        """Blocking helper — runs in a worker thread."""
        model = self._get_model()
        # fastembed's embed() returns a generator of numpy arrays
        return [vec.tolist() for vec in model.embed(texts)]  # type: ignore[union-attr]

    async def close(self) -> None:
        self._model = None


# ----------------------------------------------------------------------- #
# Facade — automatic fallback
# ----------------------------------------------------------------------- #


class EmbeddingClient:
    """Facade with automatic fallback: OpenAI API -> fastembed (CPU).

    Args:
        base_url: LM Studio / Ollama server URL.
        model: Embedding model tag for the API backend.
        dimensions: Vector dimensionality of the primary model.
        fallback_enabled: If ``True``, fall back to fastembed on API errors.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        dimensions: int,
        fallback_enabled: bool = True,
    ) -> None:
        self._openai = OpenAIEmbeddingClient(base_url, model, dimensions)
        self._fallback_enabled = fallback_enabled
        # Only enable fastembed fallback when its default model dimensions
        # (384 for BAAI/bge-small-en-v1.5) match the configured dimensions.
        # A mismatch would produce wrong-sized vectors and corrupt the vector
        # table — better to fail loudly than silently insert garbage.
        if fallback_enabled and dimensions == _FASTEMBED_DEFAULT_DIMS:
            self._fastembed: FastEmbedClient | None = FastEmbedClient()
        elif fallback_enabled:
            logger.warning(
                "embedding_fallback is enabled but the configured embedding_dim "
                "({}) does not match fastembed's default model dimensions ({}). "
                "Fallback is disabled — configure an embedding model with {} dims "
                "or set embedding_fallback: false.",
                dimensions,
                _FASTEMBED_DEFAULT_DIMS,
                _FASTEMBED_DEFAULT_DIMS,
            )
            self._fastembed = None
        else:
            self._fastembed = None

    @property
    def dimensions(self) -> int:
        return self._openai.dimensions

    async def encode(self, text: str) -> list[float]:
        """Encode a single text, falling back to CPU if the API is unreachable."""
        try:
            return await self._openai.encode(text)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            logger.debug("OpenAI embedding failed: {}", exc)
            return await self._fallback_encode(text)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts, falling back to CPU if the API is unreachable."""
        try:
            return await self._openai.encode_batch(texts)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            logger.debug("OpenAI embedding batch failed: {}", exc)
            return await self._fallback_encode_batch(texts)

    async def _fallback_encode(self, text: str) -> list[float]:
        """Attempt single-text encoding via fastembed."""
        if self._fastembed is None:
            raise RuntimeError(
                "Embedding API unreachable and fastembed fallback is disabled"
            )
        logger.warning("Embedding API unreachable, falling back to fastembed")
        return await self._fastembed.encode(text)

    async def _fallback_encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Attempt batch encoding via fastembed."""
        if self._fastembed is None:
            raise RuntimeError(
                "Embedding API unreachable and fastembed fallback is disabled"
            )
        logger.warning("Embedding API unreachable, falling back to fastembed")
        return await self._fastembed.encode_batch(texts)

    async def close(self) -> None:
        """Release resources held by both backends."""
        await self._openai.close()
        if self._fastembed is not None:
            await self._fastembed.close()
