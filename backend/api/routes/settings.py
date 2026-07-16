"""AL\\CE — Settings endpoints (runtime toggles)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from backend.core.context import AppContext
from backend.services.config_service import ConfigLayer

router = APIRouter(prefix="/settings", tags=["settings"])


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


async def _set_preference(ctx: AppContext, path: str, value: Any, *, label: str) -> None:
    """Persist a single dotted-path preference, with an in-memory fallback.

    Encapsulates the pattern repeated by every runtime toggle in this
    module: write through ``config_service`` (PREFERENCES layer) and
    refresh ``ctx.config`` from the resolved result; if the service is
    unavailable or the persisted write fails for any reason, fall back to
    mutating ``ctx.config`` directly so the running process still reflects
    the change, with a warning logged.

    Args:
        ctx: App context — reads/writes ``ctx.config`` and ``ctx.config_service``.
        path: Dotted config path, e.g. ``"llm.tools_enabled"`` (single level:
            ``section.field``).
        value: The new value to set.
        label: Short human label for the warning log message, e.g. "tools".
    """
    section, _, field = path.partition(".")
    if ctx.config_service is not None:
        try:
            await ctx.config_service.set(path, value, layer=ConfigLayer.PREFERENCES)
            ctx.config = ctx.config_service.get_resolved()
            return
        except Exception as exc:
            logger.warning("Failed to persist {} preference: {}", label, exc)
    object.__setattr__(getattr(ctx.config, section), field, value)


class ToolConfirmationsRequest(BaseModel):
    """Body for the tool-confirmations toggle."""

    enabled: bool


class ToolConfirmationsResponse(BaseModel):
    """Response after updating tool confirmations."""

    confirmations_enabled: bool


@router.put("/tool-confirmations")
async def set_tool_confirmations(
    body: ToolConfirmationsRequest,
    request: Request,
) -> ToolConfirmationsResponse:
    """Toggle tool confirmations at runtime.

    Updates ``ctx.config.permissions.confirmations_enabled`` so that
    the frontend can sync its toggle with the backend state. (The flag was
    promoted out of ``pc_automation`` to the neutral ``permissions`` block in
    Fase 2; the API field name is unchanged.)
    """
    ctx = _ctx(request)
    await _set_preference(
        ctx, "permissions.confirmations_enabled", body.enabled, label="tool-confirmations",
    )
    return ToolConfirmationsResponse(
        confirmations_enabled=ctx.config.permissions.confirmations_enabled,
    )


@router.get("/tool-confirmations")
async def get_tool_confirmations(
    request: Request,
) -> ToolConfirmationsResponse:
    """Read the current tool confirmations state."""
    ctx = _ctx(request)
    return ToolConfirmationsResponse(
        confirmations_enabled=ctx.config.permissions.confirmations_enabled,
    )


# -- System prompt toggle ---------------------------------------------------


class SystemPromptRequest(BaseModel):
    """Body for the system-prompt toggle."""

    enabled: bool


class SystemPromptResponse(BaseModel):
    """Response after updating system prompt setting."""

    system_prompt_enabled: bool


@router.put("/system-prompt")
async def set_system_prompt(
    body: SystemPromptRequest,
    request: Request,
) -> SystemPromptResponse:
    """Toggle system prompt on/off at runtime."""
    ctx = _ctx(request)
    await _set_preference(
        ctx, "llm.system_prompt_enabled", body.enabled, label="system-prompt",
    )
    # Invalidate cached system prompt so change takes effect immediately
    if ctx.llm_service is not None:
        ctx.llm_service.invalidate_system_prompt_cache()
    return SystemPromptResponse(
        system_prompt_enabled=ctx.config.llm.system_prompt_enabled,
    )


@router.get("/system-prompt")
async def get_system_prompt(
    request: Request,
) -> SystemPromptResponse:
    """Read the current system prompt enabled state."""
    ctx = _ctx(request)
    return SystemPromptResponse(
        system_prompt_enabled=ctx.config.llm.system_prompt_enabled,
    )


# -- Tools toggle -----------------------------------------------------------


class ToolsRequest(BaseModel):
    """Body for the tools toggle."""

    enabled: bool


class ToolsResponse(BaseModel):
    """Response after updating tools setting."""

    tools_enabled: bool


@router.put("/tools")
async def set_tools(
    body: ToolsRequest,
    request: Request,
) -> ToolsResponse:
    """Toggle tool definitions on/off at runtime."""
    ctx = _ctx(request)
    await _set_preference(ctx, "llm.tools_enabled", body.enabled, label="tools")
    return ToolsResponse(
        tools_enabled=ctx.config.llm.tools_enabled,
    )


@router.get("/tools")
async def get_tools(
    request: Request,
) -> ToolsResponse:
    """Read the current tools enabled state."""
    ctx = _ctx(request)
    return ToolsResponse(
        tools_enabled=ctx.config.llm.tools_enabled,
    )


# -- Active tools selection -------------------------------------------------


class ToolCatalogTool(BaseModel):
    """A single tool entry in the chat tool-picker catalog."""

    name: str
    """Namespaced tool name (the value persisted in ``disabled_tools``)."""
    label: str
    """Bare tool name for display."""
    description: str
    """Human-readable tool description."""
    enabled: bool
    """Whether this tool is currently offered to the LLM."""
    capabilities: list[str] = []
    """Capability tags (e.g. ``fs_write``, ``process_exec``) so the UI can
    reflect what the active permission tier withholds."""


class ToolCatalogPlugin(BaseModel):
    """Tools grouped under their owning plugin."""

    plugin: str
    tools: list[ToolCatalogTool]


class ToolCatalogResponse(BaseModel):
    """Full catalog plus the gating flags the chat UI needs."""

    tools_enabled: bool
    tool_rag_enabled: bool
    disabled_tools: list[str]
    plugins: list[ToolCatalogPlugin]


class ActiveToolsRequest(BaseModel):
    """Body for updating the chat tool selection (opt-out list)."""

    disabled_tools: list[str]


def _build_tool_catalog(ctx: AppContext) -> ToolCatalogResponse:
    """Assemble the tool catalog grouped by plugin from the registry."""
    disabled = set(ctx.config.llm.disabled_tools)
    grouped: dict[str, list[ToolCatalogTool]] = {}
    if ctx.tool_registry is not None:
        for entry in ctx.tool_registry.get_tool_catalog():
            grouped.setdefault(entry["plugin"], []).append(
                ToolCatalogTool(
                    name=entry["name"],
                    label=entry["label"],
                    description=entry["description"],
                    enabled=entry["name"] not in disabled,
                    capabilities=list(entry.get("capabilities", [])),
                )
            )
    plugins = [
        ToolCatalogPlugin(
            plugin=plugin,
            tools=sorted(tools, key=lambda t: t.label),
        )
        for plugin, tools in sorted(grouped.items())
    ]
    return ToolCatalogResponse(
        tools_enabled=ctx.config.llm.tools_enabled,
        tool_rag_enabled=ctx.config.llm.tool_rag_enabled,
        disabled_tools=sorted(disabled),
        plugins=plugins,
    )


@router.get("/tool-catalog")
async def get_tool_catalog(request: Request) -> ToolCatalogResponse:
    """Return all registered tools grouped by plugin for the chat picker.

    Includes ``tools_enabled`` and ``tool_rag_enabled`` so the frontend
    can disable the selection UI when manual choice has no effect.
    """
    return _build_tool_catalog(_ctx(request))


@router.put("/active-tools")
async def set_active_tools(
    body: ActiveToolsRequest,
    request: Request,
) -> ToolCatalogResponse:
    """Update the per-chat tool selection (opt-out list) at runtime.

    Stores the namespaced names of tools the user turned off in
    ``ctx.config.llm.disabled_tools`` and persists them so the choice
    survives restarts.
    """
    ctx = _ctx(request)
    cleaned = sorted({n for n in body.disabled_tools if isinstance(n, str) and n})
    await _set_preference(ctx, "llm.disabled_tools", cleaned, label="active-tools")
    return _build_tool_catalog(ctx)


# -- Preferences persistence -----------------------------------------------


@router.get("/preferences")
async def get_preferences(request: Request) -> dict[str, Any]:
    """Return all persisted user preferences."""
    ctx = _ctx(request)
    if ctx.preferences_store is None:
        return {}
    return await ctx.preferences_store.load()


# -- Voice engine availability check ---------------------------------------


@router.get("/voice/available-engines")
async def get_available_voice_engines() -> dict[str, Any]:
    """Probe which TTS and STT engine libraries are actually installed.

    Uses ``importlib.util.find_spec`` — no import side-effects.  The
    frontend uses this to hide engine options that cannot be used.

    Returns::

        {
            "tts": {"piper": true, "kokoro": false, "xtts": false},
            "stt": {"faster_whisper": true}
        }
    """
    import importlib.util

    def installed(module: str) -> bool:
        return importlib.util.find_spec(module) is not None

    return {
        "tts": {
            "piper": installed("piper"),
            "kokoro": installed("kokoro_onnx"),
            "xtts": installed("TTS"),
        },
        "stt": {
            "faster_whisper": installed("faster_whisper"),
        },
    }


@router.delete("/preferences")
async def reset_preferences(request: Request) -> dict[str, Any]:
    """Reset all persisted user preferences to defaults.

    The next restart will use only YAML defaults.
    """
    ctx = _ctx(request)
    if ctx.preferences_store is None:
        raise HTTPException(503, "Preferences service not available")
    count = await ctx.preferences_store.delete_all()
    return {
        "deleted": count,
        "message": "Preferences reset. Restart to apply YAML defaults.",
    }
