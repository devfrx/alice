"""AL\\CE — MCP Client plugin.

Bridges AL\\CE to external MCP servers. Each server's tools are
namespaced as ``mcp_{server_name}_{tool_name}`` and exposed via
``get_tools()``, making them available to the LLM automatically.

Workspace-scope → MCP ``roots`` bridge: every session is built with a
``roots_provider`` reading the **global union** of workspace scopes
(:meth:`ScopeService.all_scope_folders`), and on ``AliceEvent.SCOPE_UPDATED``
the plugin nudges every session with ``notify_roots_changed()`` so
roots-aware servers (e.g. the filesystem server) re-request ``roots/list``
and accept folders added to a scope mid-session.  Deliberate limit: MCP
servers are one process shared by all conversations, so the roots are
global (union of all scopes + static launch dirs), not per-conversation —
per-conversation confinement of MCP tools is a censused gap of the
permission gate (fase 2+).  See :mod:`backend.services.mcp_session` for the
session-side details (why the static CLI dirs must ride along).
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from backend.core.context import AppContext
from backend.core.event_bus import AliceEvent
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.services.mcp_session import McpSession


class McpClientPlugin(BasePlugin):
    """Bridges AL\\CE to external MCP servers.

    At startup, connects to every enabled server in ``config.mcp.servers``.
    Each server's tools are namespaced as ``mcp_{server_name}_{tool_name}``
    and exposed via ``get_tools()``, making them available to the LLM.
    """

    plugin_name = "mcp_client"
    plugin_version = "1.0.0"
    plugin_description = (
        "Bridges AL\\CE to external MCP servers "
        "(filesystem, git, browser, search engine, …)"
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 10  # Load after other plugins

    def __init__(self) -> None:
        super().__init__()
        self._sessions: dict[str, McpSession] = {}
        self._tool_dispatch_map: dict[str, tuple[str, str]] = {}

    async def initialize(self, ctx: AppContext) -> None:
        """Connect to all enabled MCP servers from configuration."""
        await super().initialize(ctx)

        for server_cfg in ctx.config.mcp.servers:
            if not server_cfg.enabled:
                self.logger.debug(
                    "MCP server '{}' is disabled, skipping",
                    server_cfg.name,
                )
                continue

            session = McpSession(
                server_cfg, roots_provider=self._scope_roots_provider,
            )
            try:
                await session.start()
                self._sessions[server_cfg.name] = session
                self.logger.info(
                    "MCP '{}' connected ({} tools)",
                    server_cfg.name,
                    len(session.get_tools()),
                )
                await ctx.event_bus.emit(
                    AliceEvent.MCP_SERVER_CONNECTED,
                    server=server_cfg.name,
                )
            except Exception as exc:
                self.logger.error(
                    "MCP '{}' connection failed: {}",
                    server_cfg.name,
                    exc,
                )
                await ctx.event_bus.emit(
                    AliceEvent.MCP_SERVER_DISCONNECTED,
                    server=server_cfg.name,
                    reason=str(exc),
                )

    async def on_app_startup(self) -> None:
        """Subscribe the roots bridge to workspace-scope changes.

        Runs after all plugins are initialised (inside ``stage_plugins``,
        i.e. *before* ``stage_workspace`` wires ``ctx.scope_service`` — the
        provider is lazy, so that is fine; ``stage_workspace`` replays one
        ``SCOPE_UPDATED`` after loading persisted scopes to catch us up).
        """
        self.ctx.event_bus.subscribe(
            AliceEvent.SCOPE_UPDATED, self._on_scope_updated,
        )

    def _scope_roots_provider(self) -> list[Path]:
        """Return the global union of workspace-scope folders (lazy).

        Injected into every :class:`McpSession` as its ``roots_provider``.
        Degrades to ``[]`` when :class:`ScopeService` is not (yet) wired —
        MCP sessions connect during ``stage_plugins``, before
        ``stage_workspace`` sets ``ctx.scope_service`` — leaving only the
        servers' static CLI dirs in the roots.
        """
        ctx = self._ctx
        scope_service = (
            getattr(ctx, "scope_service", None) if ctx is not None else None
        )
        if scope_service is None:
            return []
        folders: list[Path] = list(scope_service.all_scope_folders())
        return folders

    async def _on_scope_updated(self, **kwargs: Any) -> None:
        """Nudge every session to re-request roots (best-effort each)."""
        for session in list(self._sessions.values()):
            try:
                await session.notify_roots_changed()
            except Exception as exc:
                self.logger.warning(
                    "MCP '{}': roots change notification failed: {}",
                    session.server_name,
                    exc,
                )

    async def cleanup(self) -> None:
        """Disconnect all MCP sessions."""
        # Drop the scope subscription first so a scope change during
        # shutdown cannot touch half-stopped sessions (and the event bus
        # does not retain this defunct instance across hot-reloads).
        try:
            self.ctx.event_bus.unsubscribe(
                AliceEvent.SCOPE_UPDATED, self._on_scope_updated,
            )
        except Exception as exc:
            self.logger.debug(
                "Scope-updated unsubscribe skipped: {}", exc,
            )
        for session in self._sessions.values():
            try:
                await session.stop()
            except Exception as exc:
                self.logger.warning(
                    "Error closing MCP '{}': {}",
                    session.server_name,
                    exc,
                )
        self._sessions.clear()
        self._tool_dispatch_map.clear()
        await super().cleanup()

    # MCP tools often return large payloads (web pages, file content, directory
    # listings, search results).  Using the global default of 4 KB would cause
    # almost every fetch-style call to be silently truncated before the LLM
    # can act on it.  20 000 chars is a safe ceiling that stays well within
    # typical context windows while covering most real-world responses.
    _MCP_MAX_RESULT_CHARS: int = 20_000

    # Maximum length for a tool name (from plugin_models.TOOL_NAME_PATTERN).
    _MAX_TOOL_NAME_LEN: int = 64

    def get_tools(self) -> list[ToolDefinition]:
        """Aggregate tool definitions from all connected MCP sessions."""
        tools: list[ToolDefinition] = []
        dispatch_map: dict[str, tuple[str, str]] = {}
        for server_name, session in self._sessions.items():
            if session.status != ConnectionStatus.CONNECTED:
                continue
            safe_server = re.sub(r"[^a-zA-Z0-9_-]", "_", server_name)
            for tool in session.get_tools():
                full_name = f"mcp_{safe_server}_{tool.name}"
                # Truncate to 64-char limit enforced by ToolDefinition
                if len(full_name) > self._MAX_TOOL_NAME_LEN:
                    self.logger.warning(
                        "MCP tool name '{}' exceeds {} chars, truncating",
                        full_name, self._MAX_TOOL_NAME_LEN,
                    )
                    full_name = full_name[:self._MAX_TOOL_NAME_LEN]
                # Truncation may collide with another tool that already
                # mapped to the same prefix.  Skip the duplicate so we do
                # not silently route both names to the wrong server/tool.
                if full_name in dispatch_map:
                    existing_server, existing_tool = dispatch_map[full_name]
                    self.logger.warning(
                        "MCP tool name collision after truncation: '{}' "
                        "already maps to ({}, {}); skipping ({}, {})",
                        full_name,
                        existing_server, existing_tool,
                        server_name, tool.name,
                    )
                    continue
                full_desc = f"[{server_name}] {tool.description}"
                try:
                    # ``replace`` keeps every mapped field (capabilities,
                    # risk_level, requires_confirmation, path_args, …) —
                    # rebuilding from scratch would silently strip the
                    # permission-gate metadata set by map_mcp_tool().
                    tools.append(
                        replace(
                            tool,
                            name=full_name,
                            description=full_desc[:512],
                            max_result_chars=self._MCP_MAX_RESULT_CHARS,
                        )
                    )
                    # Map display name → (server, original tool name)
                    # so truncated names dispatch to the correct tool.
                    dispatch_map[full_name] = (server_name, tool.name)
                except (TypeError, ValueError) as exc:
                    # ValueError: __post_init__ re-validation of the renamed
                    # tool failed.  TypeError: the session handed us something
                    # that is not a ToolDefinition dataclass, or ``replace``
                    # was given a stale kwarg after a field rename — both
                    # programming bugs rather than bad server data.  This
                    # code runs on the turn-assembly path, so per-tool
                    # isolation (warn + skip) is the deliberate choice over
                    # letting one broken tool take down every MCP tool of
                    # every server.
                    self.logger.warning(
                        "Skipping invalid MCP tool '{}': {}",
                        full_name, exc,
                    )
        self._tool_dispatch_map = dispatch_map
        return tools

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch a tool call to the correct MCP session.

        Uses the dispatch map populated by :meth:`get_tools` for O(1)
        lookup that correctly handles truncated tool names.  Falls back
        to prefix matching when the map has no entry.
        """
        # Fast path: dispatch map (handles truncated names correctly)
        if tool_name in self._tool_dispatch_map:
            server_name, original_name = self._tool_dispatch_map[tool_name]
            session = self._sessions.get(server_name)
            if session is None:
                return ToolResult.error(
                    f"MCP server '{server_name}' is not connected"
                )
            try:
                content = await session.call_tool(original_name, args)
                return ToolResult.ok(content)
            except Exception as exc:
                return ToolResult.error(
                    f"MCP tool '{original_name}' on server "
                    f"'{server_name}' failed: {exc}"
                )

        # Fallback: prefix matching for tools not yet in the map
        sorted_sessions = sorted(
            self._sessions.items(),
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
        for server_name, session in sorted_sessions:
            safe_server = re.sub(r"[^a-zA-Z0-9_-]", "_", server_name)
            prefix = f"mcp_{safe_server}_"
            if tool_name.startswith(prefix):
                original_name = tool_name[len(prefix):]
                try:
                    content = await session.call_tool(
                        original_name, args,
                    )
                    return ToolResult.ok(content)
                except Exception as exc:
                    return ToolResult.error(
                        f"MCP tool '{original_name}' on server "
                        f"'{server_name}' failed: {exc}"
                    )

        return ToolResult.error(f"MCP tool not found: {tool_name}")

    async def get_connection_status(self) -> ConnectionStatus:
        """Aggregate connection status across all MCP sessions."""
        if not self._sessions:
            return ConnectionStatus.CONNECTED  # No servers = not an error
        connected = sum(
            1
            for s in self._sessions.values()
            if s.status == ConnectionStatus.CONNECTED
        )
        if connected == len(self._sessions):
            return ConnectionStatus.CONNECTED
        return (
            ConnectionStatus.DEGRADED
            if connected > 0
            else ConnectionStatus.ERROR
        )

    def get_server_tools(
        self, server_name: str,
    ) -> list[ToolDefinition]:
        """Return tool definitions for a specific connected server."""
        session = self._sessions.get(server_name)
        if session and session.status == ConnectionStatus.CONNECTED:
            return session.get_tools()
        return []

    def get_session(self, server_name: str) -> McpSession | None:
        """Return the live :class:`McpSession` for ``server_name``.

        Public accessor used by REST endpoints (e.g. the MCP memory
        routes) that need to invoke tools on a specific server without
        going through the LLM tool-dispatch path.

        Args:
            server_name: Name of the configured MCP server.

        Returns:
            The live session if the server is connected, otherwise
            ``None``. The returned session may be in any
            :class:`ConnectionStatus`; callers should check
            ``session.status`` if they require a healthy connection.
        """
        return self._sessions.get(server_name)

    async def reconnect_server(
        self, server_name: str, config: Any,
    ) -> McpSession:
        """Stop existing session (if any) and reconnect.

        Args:
            server_name: Name of the server to reconnect.
            config: McpServerConfig for the server.

        Returns:
            The new connected McpSession.

        Raises:
            RuntimeError: If reconnection fails.
        """
        old_session = self._sessions.pop(server_name, None)
        if old_session:
            try:
                await old_session.stop()
            except Exception as exc:
                # Stale connection cleanup is best-effort; the new
                # session will be created regardless.  Log so operators
                # can spot zombie subprocesses / leaked file handles.
                self.logger.warning(
                    "Failed to stop stale MCP session for '{}': {}",
                    server_name,
                    exc,
                )

        session = McpSession(
            config, roots_provider=self._scope_roots_provider,
        )
        await session.start()
        self._sessions[server_name] = session
        return session

    async def get_status(self) -> dict[str, str]:
        """Return per-server connection status for health reporting."""
        return {
            name: s.status.value
            for name, s in self._sessions.items()
        }
