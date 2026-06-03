"""AL\\CE — Tests for LLM auto-model resolution.

Regression coverage for the bug where sending a chat message made LM
Studio JIT-load an unrelated model (e.g. an OCR checkpoint), evicting the
embedding model from VRAM.  ``LLMService._resolve_model`` must prefer a
model that is *already loaded* and must never pick an embedding model.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.config import PROJECT_ROOT, LLMConfig
from backend.services.llm_service import LLMService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _service(model: str = "auto") -> LLMService:
    """Build an LLMService with no capability registry."""
    config = LLMConfig(
        base_url="http://localhost:1234",
        model=model,
        system_prompt_file=str(PROJECT_ROOT / "config" / "system_prompt.md"),
    )
    return LLMService(config)


def _v1_response(models: list[dict]) -> MagicMock:
    """Fake httpx response for the v1 ``/api/v1/models`` endpoint."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"models": models})
    return resp


def _oai_response(data: list[dict]) -> MagicMock:
    """Fake httpx response for the OAI-compat ``/v1/models`` endpoint."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"data": data})
    return resp


def _patch_get(svc: LLMService, by_url: dict[str, MagicMock]) -> AsyncMock:
    """Patch ``svc._client.get`` to dispatch responses by URL substring."""
    async def _get(url: str, **_kwargs):
        for fragment, resp in by_url.items():
            if fragment in url:
                return resp
        raise AssertionError(f"unexpected URL: {url}")

    mock = AsyncMock(side_effect=_get)
    svc._client.get = mock  # type: ignore[method-assign]
    return mock


# A realistic LM Studio v1 model list: one loaded embedding model, one
# loaded chat model (gemma), and several unloaded models — including an
# OCR checkpoint that sorts *before* the loaded chat model.
_REAL_MODELS = [
    {
        "key": "text-embedding-qwen3-embedding-0.6b",
        "path": "text-embedding-qwen3-embedding-0.6b",
        "type": "embedding",
        "loaded_instances": ["inst-embed"],
        "capabilities": {},
    },
    {
        "key": "glm-ocr",
        "path": "glm-ocr",
        "type": "llm",
        "loaded_instances": [],
        "capabilities": {"vision": True, "trained_for_tool_use": False},
    },
    {
        "key": "google/gemma-4-e4b",
        "path": "google/gemma-4-e4b",
        "type": "llm",
        "loaded_instances": ["inst-gemma"],
        "capabilities": {"vision": True, "trained_for_tool_use": True},
    },
    {
        "key": "qwen3.5-9b-distilled",
        "path": "qwen3.5-9b-distilled",
        "type": "llm",
        "loaded_instances": [],
        "capabilities": {"vision": True, "trained_for_tool_use": True},
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prefers_loaded_chat_model_over_unloaded_ocr():
    """The loaded gemma must win over the unloaded OCR model."""
    svc = _service("auto")
    _patch_get(svc, {"/api/v1/models": _v1_response(_REAL_MODELS)})

    resolved = await svc._resolve_model()

    assert resolved == "google/gemma-4-e4b"


@pytest.mark.asyncio
async def test_never_resolves_to_embedding_model():
    """Even if the only loaded model is an embedding one, skip it."""
    svc = _service("auto")
    models = [
        {
            "key": "text-embedding-qwen3-embedding-0.6b",
            "path": "text-embedding-qwen3-embedding-0.6b",
            "type": "embedding",
            "loaded_instances": ["inst-embed"],
            "capabilities": {},
        },
        {
            "key": "glm-ocr",
            "path": "glm-ocr",
            "type": "llm",
            "loaded_instances": [],
            "capabilities": {"trained_for_tool_use": False},
        },
        {
            "key": "google/gemma-4-e4b",
            "path": "google/gemma-4-e4b",
            "type": "llm",
            "loaded_instances": [],
            "capabilities": {"trained_for_tool_use": True},
        },
    ]
    _patch_get(svc, {"/api/v1/models": _v1_response(models)})

    resolved = await svc._resolve_model()

    # No chat model loaded -> JIT fallback, but must skip OCR (no tool use)
    # in favour of the tool-capable chat model, and never the embedding.
    assert resolved == "google/gemma-4-e4b"


@pytest.mark.asyncio
async def test_jit_fallback_skips_ocr_for_tool_use_model():
    """With nothing loaded, prefer a tool-use model over an OCR model."""
    svc = _service("auto")
    models = [
        {
            "key": "glm-ocr", "path": "glm-ocr", "type": "llm",
            "loaded_instances": [],
            "capabilities": {"trained_for_tool_use": False},
        },
        {
            "key": "chat-model", "path": "chat-model", "type": "llm",
            "loaded_instances": [],
            "capabilities": {"trained_for_tool_use": True},
        },
    ]
    _patch_get(svc, {"/api/v1/models": _v1_response(models)})

    assert await svc._resolve_model() == "chat-model"


@pytest.mark.asyncio
async def test_explicit_config_model_is_returned_verbatim():
    """A non-'auto' config model short-circuits resolution (no HTTP)."""
    svc = _service("my/specific-model")
    mock = _patch_get(svc, {})

    assert await svc._resolve_model() == "my/specific-model"
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_configured_model_preferred_among_loaded():
    """When config names a loaded model, it wins over heuristics."""
    svc = _service("glm-ocr")
    # config.model is a concrete value -> short-circuits before HTTP.
    assert await svc._resolve_model() == "glm-ocr"


@pytest.mark.asyncio
async def test_result_is_cached():
    """A second resolution within the TTL must not re-query LM Studio."""
    svc = _service("auto")
    mock = _patch_get(svc, {"/api/v1/models": _v1_response(_REAL_MODELS)})

    first = await svc._resolve_model()
    second = await svc._resolve_model()

    assert first == second == "google/gemma-4-e4b"
    assert mock.await_count == 1


@pytest.mark.asyncio
async def test_invalidate_cache_forces_requery():
    """invalidate_model_cache() makes the next call re-resolve."""
    svc = _service("auto")
    mock = _patch_get(svc, {"/api/v1/models": _v1_response(_REAL_MODELS)})

    await svc._resolve_model()
    svc.invalidate_model_cache()
    await svc._resolve_model()

    assert mock.await_count == 2


@pytest.mark.asyncio
async def test_falls_back_to_oai_when_v1_only_embeddings():
    """All-embedding v1 response -> OAI-compat fallback picks a chat model."""
    svc = _service("auto")
    v1_models = [
        {
            "key": "text-embedding-foo", "path": "text-embedding-foo",
            "type": "embedding", "loaded_instances": [],
        },
    ]
    oai_data = [
        {"id": "text-embedding-foo"},
        {"id": "chat-model"},
    ]
    _patch_get(svc, {
        "/api/v1/models": _v1_response(v1_models),
        "/v1/models": _oai_response(oai_data),
    })

    assert await svc._resolve_model() == "chat-model"


def test_is_loaded_detects_instances():
    """_is_loaded recognises loaded_instances and the state field."""
    assert LLMService._is_loaded({"loaded_instances": ["x"]}) is True
    assert LLMService._is_loaded({"loaded_instances": []}) is False
    assert LLMService._is_loaded({"state": "loaded"}) is True
    assert LLMService._is_loaded({"state": "loading"}) is True
    assert LLMService._is_loaded({"state": "", "loaded_instances": []}) is False
    assert LLMService._is_loaded({}) is False


def test_is_embedding_model_by_type_and_name():
    """_is_embedding_model catches both the type field and name heuristic."""
    assert LLMService._is_embedding_model({"type": "embedding"}) is True
    assert LLMService._is_embedding_model({"id": "nomic-embed-text"}) is True
    assert LLMService._is_embedding_model(
        {"type": "llm", "id": "gemma"},
    ) is False
