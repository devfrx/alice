"""AL\\CE — Plugin management endpoints."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from backend.core.context import AppContext
from backend.core.plugin_models import ExecutionContext

router = APIRouter(tags=["plugins"])

# Serialises concurrent enable/disable operations on the same plugin so
# that the ``ctx.config.plugins.enabled`` list and the PluginManager state
# never disagree if two clients toggle the same plugin in parallel.
_toggle_lock = asyncio.Lock()


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


@router.get("/plugins")
async def list_plugins(request: Request) -> list[dict[str, Any]]:
    """Return all available plugins and their status.

    Discovers every plugin under ``backend/plugins/`` (even those
    not currently enabled) so the frontend can display toggles for
    all of them.
    """
    ctx = _ctx(request)
    enabled_list = ctx.config.plugins.enabled
    pm = ctx.plugin_manager

    loaded = pm.get_all_plugins() if pm else {}

    # Discover ALL plugin classes (imports modules that aren't loaded yet).
    all_available = pm.discover_available_plugins() if pm else {}

    results: list[dict[str, Any]] = []

    for name, plugin_cls in sorted(all_available.items()):
        plugin = loaded.get(name)
        if plugin is not None:
            # Loaded — real metadata
            tools = [
                {"name": t.name, "description": t.description}
                for t in plugin.get_tools()
            ]
            results.append(
                {
                    "name": name,
                    "version": plugin.plugin_version,
                    "description": plugin.plugin_description,
                    "author": getattr(plugin, "plugin_author", ""),
                    "enabled": name in enabled_list,
                    "tools": tools,
                }
            )
        else:
            # Not loaded — extract class-level metadata
            results.append(
                {
                    "name": name,
                    "version": getattr(plugin_cls, "plugin_version", "unknown"),
                    "description": getattr(
                        plugin_cls, "plugin_description", ""
                    ),
                    "author": getattr(plugin_cls, "plugin_author", ""),
                    "enabled": False,
                    "tools": [],
                }
            )

    return results


class TogglePluginRequest(BaseModel):
    """Request body for toggling a plugin."""

    enabled: bool


@router.patch("/plugins/{plugin_name}")
async def toggle_plugin(
    plugin_name: str, body: TogglePluginRequest, request: Request,
) -> dict[str, Any]:
    """Enable or disable a plugin by name.

    Body: ``{"enabled": true|false}``

    Actually loads or unloads the plugin via the PluginManager.
    """
    ctx = _ctx(request)
    enabled = body.enabled
    pm = ctx.plugin_manager

    if pm is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin manager not available",
        )

    async with _toggle_lock:
        current = ctx.config.plugins.enabled

        if enabled:
            if plugin_name not in current:
                current.append(plugin_name)
            ok = await pm.load_plugin(plugin_name)
            if not ok:
                # Roll back the enable so config and PluginManager stay in
                # sync, then surface the failure to the caller.
                if plugin_name in current:
                    current.remove(plugin_name)
                logger.warning(
                    "Plugin '{}' was enabled but failed to load",
                    plugin_name,
                )
                if ctx.tool_registry:
                    await ctx.tool_registry.refresh()
                raise HTTPException(
                    status_code=500,
                    detail=f"Plugin '{plugin_name}' failed to load",
                )
        else:
            if plugin_name in current:
                current.remove(plugin_name)
            await pm.unload_plugin(plugin_name)

        # Persist the new state so it survives restarts.
        if ctx.plugin_state_repo:
            await ctx.plugin_state_repo.set(plugin_name, enabled)

        # Refresh tool registry so the LLM sees updated tool definitions.
        if ctx.tool_registry:
            await ctx.tool_registry.refresh()

    # Build full plugin info for the response.
    plugin = pm.get_plugin(plugin_name) if pm else None
    if plugin is not None:
        tools = [
            {"name": t.name, "description": t.description}
            for t in plugin.get_tools()
        ]
        return {
            "name": plugin_name,
            "version": plugin.plugin_version,
            "description": plugin.plugin_description,
            "author": getattr(plugin, "plugin_author", ""),
            "enabled": plugin_name in current,
            "tools": tools,
        }

    return {
        "name": plugin_name,
        "version": "unknown",
        "description": f"Plugin '{plugin_name}' not loaded",
        "author": "",
        "enabled": plugin_name in current,
        "tools": [],
    }


# -------------------------------------------------------------------
# Direct plugin tool execution
# -------------------------------------------------------------------


class _ExecuteRequest(BaseModel):
    """Body schema for ``POST /plugins/execute``."""

    plugin: str = Field(..., min_length=1, max_length=64)
    tool: str = Field(..., min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


@router.post("/plugins/execute")
async def execute_plugin_tool(
    body: _ExecuteRequest, request: Request,
) -> dict[str, Any]:
    """Execute a plugin tool directly via REST.

    Body: ``{"plugin": str, "tool": str, "args": dict}``

    Returns ``{"success": bool, "content": ..., "error_message": ...}``.
    """
    ctx = _ctx(request)
    pm = ctx.plugin_manager

    if pm is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin manager not available",
        )

    plugin = pm.get_plugin(body.plugin)
    if plugin is None:
        return {
            "success": False,
            "content": None,
            "error_message": f"Plugin '{body.plugin}' is not loaded or enabled",
        }

    # Verify the tool exists on the plugin
    known_tools = {t.name for t in plugin.get_tools()}
    if body.tool not in known_tools:
        return {
            "success": False,
            "content": None,
            "error_message": (
                f"Tool '{body.tool}' not found on plugin '{body.plugin}'"
            ),
        }

    exec_ctx = ExecutionContext(
        session_id="rest",
        conversation_id="rest",
        execution_id=str(uuid.uuid4()),
    )

    try:
        result = await plugin.execute_tool(body.tool, body.args, exec_ctx)
    except Exception as exc:
        logger.error(
            "Plugin '{}' tool '{}' raised: {}",
            body.plugin,
            body.tool,
            exc,
        )
        return {
            "success": False,
            "content": None,
            "error_message": f"Tool execution failed: {exc}",
        }

    return {
        "success": result.success,
        "content": result.content,
        "error_message": result.error_message,
    }
