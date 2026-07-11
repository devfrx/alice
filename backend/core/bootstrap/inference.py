"""AL\\CE — Bootstrap stage: inference services (Fase 5).

Model capability registry, LLM service, context manager, and the LM
Studio manager (registered with the orchestrator, health-only).
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from backend.core.context import AppContext
from backend.core.managed_services import LMStudioManagedService
from backend.services.llm_service import LLMService
from backend.services.lmstudio_service import LMStudioManager
from backend.services.model_capability_registry import ModelCapabilityRegistry


async def stage_inference(ctx: AppContext) -> None:
    """Wire the inference group: model registry, LLM service, LM Studio.

    Args:
        ctx: The application context being bootstrapped.
    """
    config = ctx.config

    # -- Model capability registry ------------------------------------------
    model_registry = ModelCapabilityRegistry()
    ctx.model_registry = model_registry

    llm_service = LLMService(config.llm, model_registry=model_registry)
    ctx.llm_service = llm_service

    from backend.services.context_manager import ContextManager
    ctx.context_manager = ContextManager(config.llm)

    # Validate system prompt file exists at startup.
    prompt_path = Path(config.llm.system_prompt_file)
    if not prompt_path.exists():
        logger.warning(
            "System prompt file not found: {} — LLM will use no system prompt",
            prompt_path,
        )

    lmstudio_manager = LMStudioManager(
        base_url=config.llm.base_url,
        api_token=config.llm.api_token,
    )
    ctx.lmstudio_manager = lmstudio_manager

    # Drop the cached LLM context window whenever the loaded-model set changes
    # (load/unload paths call invalidate_models_cache), so the next probe
    # re-reads the window for the now-active model.
    lmstudio_manager.add_models_changed_listener(
        llm_service.invalidate_context_window_cache
    )

    # Register LM Studio with the orchestrator (health-only, never auto-start).
    try:
        await ctx.orchestrator.attach_started(
            LMStudioManagedService(lmstudio_manager),
        )
    except Exception as exc:
        logger.warning("Orchestrator: failed to attach LM Studio: {}", exc)
