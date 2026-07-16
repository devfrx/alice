"""AL\\CE — Tests for the model capability registry.

Covers the provider-namespace isolation (finding F4 della review
OpenRouter, 2026-07-16): un modello locale senza profilo esatto non deve
ereditare via fuzzy match il profilo di un modello del catalogo
OpenRouter, e viceversa — anche quando gli id ``org/model`` collidono
esattamente tra LM Studio e OpenRouter.
"""

from __future__ import annotations

import pytest

from backend.services.model_capability_registry import ModelCapabilityRegistry

pytestmark = pytest.mark.asyncio

# LM Studio v1 /api/v1/models entry: stesso id "qwen/qwen3-32b" del
# catalogo OpenRouter, ma capabilities e context window locali diversi.
_LMSTUDIO_MODELS = [
    {
        "key": "qwen/qwen3-32b",
        "path": "qwen/qwen3-32b",
        "capabilities": {
            "vision": False,
            "thinking": False,
            "trained_for_tool_use": True,
        },
        "max_context_length": 8192,
    },
]

# OpenRouter GET /v1/models entry con id che collide con il path LM Studio.
_OPENROUTER_CATALOG = [
    {
        "id": "qwen/qwen3-32b",
        "context_length": 40960,
        "architecture": {"input_modalities": ["text", "image"]},
        "supported_parameters": ["tools", "reasoning"],
    },
]


async def test_local_query_does_not_inherit_openrouter_profile() -> None:
    """Il caso del finding: Ollama ``qwen3:32b`` dopo il seeding del catalogo.

    Normalizzato, ``qwen3:32b`` è un suffisso di ``qwen/qwen3-32b``: il
    fuzzy match non deve attraversare il namespace e restituire il
    profilo cloud (thinking/vision/context_length sbagliati).
    """
    registry = ModelCapabilityRegistry()
    await registry.refresh_from_openrouter(_OPENROUTER_CATALOG)

    profile = registry.get_profile("qwen3:32b", namespace="local")

    assert profile.source != "openrouter_api"
    assert profile.supports_thinking is False
    assert profile.supports_vision is False
    assert profile.context_length == 0


async def test_runtime_learning_stays_in_local_namespace() -> None:
    """I flag runtime-learned di un modello locale non contaminano il cloud."""
    registry = ModelCapabilityRegistry()
    await registry.refresh_from_openrouter(_OPENROUTER_CATALOG)

    registry.mark_reasoning_param_accepted("qwen3:32b", namespace="local")

    cloud = registry.get_profile("qwen/qwen3-32b", namespace="openrouter")
    assert cloud.accepts_reasoning_param is None
    local = registry.get_profile("qwen3:32b", namespace="local")
    assert local.accepts_reasoning_param is True


async def test_colliding_ids_keep_per_provider_profiles() -> None:
    """Il gotcha: gli id ``org/model`` collidono davvero tra i provider.

    Con i namespace i due profili coesistono invece di contendersi la
    chiave (prima vinceva il locale e il profilo cloud andava perso).
    """
    registry = ModelCapabilityRegistry()
    await registry.refresh_from_api(_LMSTUDIO_MODELS)
    await registry.refresh_from_openrouter(_OPENROUTER_CATALOG)

    local = registry.get_profile("qwen/qwen3-32b", namespace="local")
    cloud = registry.get_profile("qwen/qwen3-32b", namespace="openrouter")

    assert local.source == "lmstudio_api"
    assert local.context_length == 8192
    assert local.supports_thinking is False
    assert cloud.source == "openrouter_api"
    assert cloud.context_length == 40960
    assert cloud.supports_thinking is True
    assert cloud.supports_vision is True


async def test_fuzzy_match_bridges_local_naming_conventions() -> None:
    """Il fuzzy match resta attivo DENTRO il namespace locale.

    È la sua ragione d'essere: riconciliare tag Ollama (``qwen3:32b``)
    e path LM Studio (``qwen/qwen3-32b``).
    """
    registry = ModelCapabilityRegistry()
    await registry.refresh_from_api(_LMSTUDIO_MODELS)

    profile = registry.get_profile("qwen3:32b", namespace="local")

    assert profile.source == "lmstudio_api"
    assert profile.context_length == 8192


async def test_openrouter_lookup_is_exact_match_only() -> None:
    """Gli id OpenRouter sono un vocabolario canonico: niente fuzzy.

    Un lookup cloud non deve ereditare un profilo locale per suffisso
    (``qwen/qwen3-32b`` normalizzato termina in ``qwen3-32b``).
    """
    registry = ModelCapabilityRegistry()
    # Crea un profilo locale di default per il tag Ollama.
    registry.get_profile("qwen3:32b", namespace="local")

    cloud = registry.get_profile("qwen/qwen3-32b", namespace="openrouter")

    assert cloud.model_id == "qwen/qwen3-32b"
    assert cloud.source == "default"


async def test_known_models_fallback_is_local_only() -> None:
    """Il fallback KNOWN_MODELS (chiavi Ollama/LM Studio) vale solo per il locale."""
    registry = ModelCapabilityRegistry()

    local = registry.get_profile("qwen3.5:9b", namespace="local")
    assert local.source == "known_models"
    assert local.supports_thinking is True

    cloud = registry.get_profile("qwen3.5:9b", namespace="openrouter")
    assert cloud.source == "default"
    assert cloud.supports_thinking is False


async def test_openrouter_refresh_preserves_runtime_learned_flags() -> None:
    """Un re-fetch del catalogo non azzera la conoscenza runtime-learned."""
    registry = ModelCapabilityRegistry()
    await registry.refresh_from_openrouter(_OPENROUTER_CATALOG)
    registry.mark_reasoning_param_accepted(
        "qwen/qwen3-32b", namespace="openrouter",
    )
    registry.mark_emits_reasoning_natively(
        "qwen/qwen3-32b", namespace="openrouter",
    )

    await registry.refresh_from_openrouter(_OPENROUTER_CATALOG)

    cloud = registry.get_profile("qwen/qwen3-32b", namespace="openrouter")
    assert cloud.accepts_reasoning_param is True
    assert cloud.emits_reasoning_natively is True


async def test_all_profiles_flat_view_prefers_local_on_collision() -> None:
    """La vista piatta (endpoint /models/capabilities) resta retrocompatibile.

    Su collisione di id vince il profilo locale, come nel comportamento
    pre-namespace in cui il profilo LM Studio non veniva clobberato.
    """
    registry = ModelCapabilityRegistry()
    await registry.refresh_from_api(_LMSTUDIO_MODELS)
    await registry.refresh_from_openrouter(_OPENROUTER_CATALOG)

    profiles = registry.all_profiles()

    assert profiles["qwen/qwen3-32b"].source == "lmstudio_api"


async def test_clear_empties_all_namespaces() -> None:
    """``clear`` svuota entrambi i namespace."""
    registry = ModelCapabilityRegistry()
    await registry.refresh_from_api(_LMSTUDIO_MODELS)
    await registry.refresh_from_openrouter(_OPENROUTER_CATALOG)

    registry.clear()

    assert registry.all_profiles() == {}
    assert registry.last_refresh == 0.0
