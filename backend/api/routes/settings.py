"""O.M.N.I.A. — Settings endpoints (runtime toggles)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.core.context import AppContext

router = APIRouter(prefix="/settings", tags=["settings"])


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


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

    Updates ``ctx.config.pc_automation.confirmations_enabled`` so that
    the frontend can sync its toggle with the backend state.
    """
    ctx = _ctx(request)
    ctx.config.pc_automation.confirmations_enabled = body.enabled
    if ctx.preferences_service is not None:
        try:
            await ctx.preferences_service.save_preference(
                "pc_automation.confirmations_enabled", body.enabled,
            )
        except Exception:
            pass  # Non-critical — best effort
    return ToolConfirmationsResponse(
        confirmations_enabled=ctx.config.pc_automation.confirmations_enabled,
    )


@router.get("/tool-confirmations")
async def get_tool_confirmations(
    request: Request,
) -> ToolConfirmationsResponse:
    """Read the current tool confirmations state."""
    ctx = _ctx(request)
    return ToolConfirmationsResponse(
        confirmations_enabled=ctx.config.pc_automation.confirmations_enabled,
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
    ctx.config.llm.system_prompt_enabled = body.enabled
    # Invalidate cached system prompt so change takes effect immediately
    if hasattr(ctx, "llm_service") and ctx.llm_service:
        ctx.llm_service._system_prompt = None
    if ctx.preferences_service is not None:
        try:
            await ctx.preferences_service.save_preference(
                "llm.system_prompt_enabled", body.enabled,
            )
        except Exception:
            pass  # Non-critical — best effort
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
    ctx.config.llm.tools_enabled = body.enabled
    if ctx.preferences_service is not None:
        try:
            await ctx.preferences_service.save_preference(
                "llm.tools_enabled", body.enabled,
            )
        except Exception:
            pass  # Non-critical — best effort
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


# -- Preferences persistence -----------------------------------------------


@router.get("/preferences")
async def get_preferences(request: Request) -> dict[str, Any]:
    """Return all persisted user preferences."""
    ctx = _ctx(request)
    if ctx.preferences_service is None:
        return {}
    return await ctx.preferences_service.load_all()


@router.delete("/preferences")
async def reset_preferences(request: Request) -> dict[str, Any]:
    """Reset all persisted user preferences to defaults.

    The next restart will use only YAML defaults.
    """
    ctx = _ctx(request)
    if ctx.preferences_service is None:
        raise HTTPException(503, "Preferences service not available")
    count = await ctx.preferences_service.delete_all()
    return {
        "deleted": count,
        "message": "Preferences reset. Restart to apply YAML defaults.",
    }
