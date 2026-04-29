"""AL\\CE — Embedding client with automatic fallback.

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

    # Chunk sizes tried in order when the server rejects a batch.
    # 32 is the empirical safe cap for LM Studio with LM Link relaying:
    # batches >=64 trigger ``LM Link connection closed`` (HTTP 400).
    _BATCH_CHUNK_SIZES: tuple[int, ...] = (32, 8)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts, chunking to survive server limits.

        Strategy (each step only kicks in if the previous one fails):

        1. Send the full list in one request (fast path).
        2. Retry by splitting into smaller batches (``_BATCH_CHUNK_SIZES``).
           Needed for LM Studio when the model is served via LM Link
           — the relay closes the connection on payloads above ~48 items.
        3. Last resort: sequential one-by-one calls.
        """
        if not texts:
            return []

        # 1. Fast path — try as a single batch
        try:
            return await self._embed_chunk(texts)
        except httpx.HTTPStatusError as exc:
            logger.debug(
                "Embedding batch of {} rejected (HTTP {}: {!r}); "
                "falling back to chunked requests",
                len(texts), exc.response.status_code,
                (exc.response.text or "")[:120],
            )

        # 2. Chunked retries
        for chunk_size in self._BATCH_CHUNK_SIZES:
            if chunk_size >= len(texts):
                continue
            try:
                results: list[list[float]] = []
                for start in range(0, len(texts), chunk_size):
                    sub = texts[start:start + chunk_size]
                    results.extend(await self._embed_chunk(sub))
                return results
            except httpx.HTTPStatusError as exc:
                logger.debug(
                    "Embedding chunk size {} also rejected (HTTP {}); "
                    "trying smaller",
                    chunk_size, exc.response.status_code,
                )

        # 3. Last resort — sequential
        logger.warning(
            "Embedding server rejected all batch sizes; falling back to "
            "{} sequential calls (slow path)", len(texts),
        )
        results = []
        for text in texts:
            vec = await self.encode(text)
            results.append(vec)
        return results

    async def _embed_chunk(self, texts: list[str]) -> list[list[float]]:
        """POST one batch and return ordered embeddings.

        Raises ``httpx.HTTPStatusError`` so the caller can decide whether
        to retry with a smaller chunk.
        """
        resp = await self._client.post(
            "/v1/embeddings",
            json={"input": texts, "model": self._model},
        )
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]

    async def is_model_loaded(self) -> bool:
        """Return True if the embedding model is currently loaded in LM Studio.

        Queries ``GET /v1/models`` and checks whether ``self._model``
        appears in the returned list.  Returns False on any network or
        parse error so callers can fail gracefully.
        """
        try:
            resp = await self._client.get(
                "/v1/models",
                timeout=httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0),
            )
            resp.raise_for_status()
            items = resp.json().get("data") or []
            loaded_ids = {m.get("id", "") for m in items}
            return self._model in loaded_ids
        except Exception:
            return False

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

    async def probe_dimensions(self) -> int:
        """Discover the actual embedding dimensionality by making one test call.

        Only probes if the embedding model is already loaded in LM Studio
        (checked via ``GET /v1/models``).  This avoids triggering an
        auto-load when the model is not running — callers get back the
        configured default dimension and the model stays unloaded.

        Corrects the internal dim value (and collection size used for
        ``ensure_collection``) if the configured value doesn't match
        what the model actually returns.  Disables the fastembed fallback
        when its dim would differ from the probed dim.

        Returns:
            Actual number of dimensions produced by the active backend.
        """
        # Guard: don't trigger an LM Studio auto-load if the model isn't up.
        model_loaded = await self._openai.is_model_loaded()
        if not model_loaded:
            logger.debug(
                "Embedding model '{}' not loaded in LM Studio — skipping probe"
                " (using configured dim={})",
                self._openai._model,
                self._openai._dim,
            )
            return self._openai.dimensions

        try:
            vec = await self._openai.encode("probe")
            actual = len(vec)
        except Exception:
            # API unavailable — use fastembed to probe
            if self._fastembed is not None:
                try:
                    vec = await self._fastembed.encode("probe")
                    actual = len(vec)
                except Exception:
                    return self._openai.dimensions
            else:
                return self._openai.dimensions

        if actual != self._openai._dim:
            logger.warning(
                "Embedding dim mismatch — config says {} but model returns {}."
                " Updating to {}.",
                self._openai._dim, actual, actual,
            )
            self._openai._dim = actual
            # Disable fastembed if its dim no longer matches
            if self._fastembed is not None and self._fastembed._dim != actual:
                logger.warning(
                    "fastembed fallback disabled — its dim ({}) != actual dim ({})",
                    self._fastembed._dim, actual,
                )
                self._fastembed = None

        return actual

    async def encode(self, text: str) -> list[float]:
        """Encode a single text, falling back to CPU if the API is unreachable."""
        try:
            return await self._openai.encode(text)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.debug("OpenAI embedding failed: {}", exc)
            return await self._fallback_encode(text)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts, falling back to CPU if the API is unreachable."""
        try:
            return await self._openai.encode_batch(texts)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
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
