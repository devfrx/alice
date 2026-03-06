"""O.M.N.I.A. — Plugin management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from backend.core.context import AppContext

router = APIRouter()


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


@router.get("/plugins")
async def list_plugins(request: Request) -> list[dict[str, Any]]:
    """Return all available plugins and their status.

    Builds the list from loaded plugins (real metadata) plus any
    entries in ``plugins.enabled`` that failed to load.
    """
    ctx = _ctx(request)
    enabled_list = ctx.config.plugins.enabled
    pm = ctx.plugin_manager

    loaded = pm.get_all_plugins() if pm else {}
    seen: set[str] = set()
    results: list[dict[str, Any]] = []

    # Loaded plugins — real metadata
    for name, plugin in loaded.items():
        seen.add(name)
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

    # Expected but not loaded — show as disabled/unavailable
    for name in enabled_list:
        if name not in seen:
            results.append(
                {
                    "name": name,
                    "version": "unknown",
                    "description": f"Plugin '{name}' not loaded",
                    "author": "",
                    "enabled": True,
                    "tools": [],
                }
            )

    return results


@router.patch("/plugins/{plugin_name}")
async def toggle_plugin(
    plugin_name: str, request: Request
) -> dict[str, Any]:
    """Enable or disable a plugin by name.

    Body: ``{"enabled": true|false}``

    Actually loads or unloads the plugin via the PluginManager.
    """
    ctx = _ctx(request)
    body = await request.json()
    enabled: bool = body.get("enabled", True)
    pm = ctx.plugin_manager

    if pm is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin manager not available",
        )

    current = ctx.config.plugins.enabled

    if enabled:
        if plugin_name not in current:
            current.append(plugin_name)
        ok = await pm.load_plugin(plugin_name)
        if not ok:
            logger.warning(
                "Plugin '{}' was enabled but failed to load",
                plugin_name,
            )
    else:
        if plugin_name in current:
            current.remove(plugin_name)
        await pm.unload_plugin(plugin_name)

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
