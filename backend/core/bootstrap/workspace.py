"""AL\\CE — Bootstrap stage: workspace services (Fase 5).

Scope service, permission mode service, permission rule service, the
central permission service, and the interactive terminal session
manager.  Hard ordering: ``permission_service`` needs scope + rules;
``terminal`` needs scope.
"""

from __future__ import annotations

from backend.core.context import AppContext


async def stage_workspace(ctx: AppContext) -> None:
    """Wire the workspace group: scope, permission mode/rules/service, terminal.

    Args:
        ctx: The application context being bootstrapped.
    """
    assert ctx.db is not None, "stage_database must run before stage_workspace"
    session_factory = ctx.db

    # -- Scope service (per-conversation workspace folder scope) --------
    from backend.services.scope_service import ScopeService

    scope_service = ScopeService(
        session_factory=session_factory,
        config=ctx.config.scope,
    )

    async def _broadcast_scope_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    scope_service.set_event_callback(_broadcast_scope_event)
    await scope_service.load_all()
    ctx.scope_service = scope_service

    # -- Permission mode service (per-conversation tier, Fase 7) --------
    from backend.services.permission_mode_service import (
        PermissionMode,
        PermissionModeService,
    )

    mode_service = PermissionModeService(
        session_factory=session_factory,
        default_mode=PermissionMode(ctx.config.permissions.default_mode),
    )

    async def _broadcast_permission_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    mode_service.set_event_callback(_broadcast_permission_event)
    await mode_service.load_all()
    ctx.permission_mode_service = mode_service

    # -- Permission rule service (persistent allow/ask/deny, Fase 7) ----
    from backend.services.permission_rules import PermissionRuleService

    rule_service = PermissionRuleService(session_factory=session_factory)
    await rule_service.load_all()
    ctx.permission_rule_service = rule_service

    # -- Command Bridge (Fase 7, spec §7): agent-driven UI commands ------
    # Needs the events-WS manager (stage_surfaces) and the tool registry
    # (stage_plugins) — both already wired when this stage runs. Created
    # BEFORE PermissionService so its bound ``capability_of`` can be
    # injected as the per-call capability resolver for ``app_command``.
    from backend.services.command_bridge import (
        CommandBridgeService,
        build_app_command_definition,
    )

    command_bridge = CommandBridgeService(
        ws_manager=ctx.ws_connection_manager,
        tool_registry=ctx.tool_registry,
        enabled=ctx.config.commands.enabled,
        rpc_timeout_s=ctx.config.commands.rpc_timeout_s,
        disabled_commands=ctx.config.commands.disabled_commands,
    )
    ctx.command_bridge_service = command_bridge

    # -- Permission service (central tool risk / scope / tier authority) -
    # Fase 6: ScopeService supplies the per-conversation scope provider, so a
    # tool tagged fs_read/fs_write is confined by construction. Fase 7:
    # PermissionRuleService supplies persistent allow/ask/deny rules. Hard
    # sandbox: ``effective_roots`` returns the explicit scope when set, else the
    # per-conversation ephemeral sandbox dir — so no scope set ⇒ filesystem
    # tools are confined to that sandbox (never the OS home/system root), not
    # denied outright.
    from backend.services.permission_service import PermissionService

    ctx.permission_service = PermissionService(
        scope_provider=scope_service.effective_roots,
        rule_provider=rule_service.match,
        forbidden_paths=ctx.config.scope.forbidden_paths,
        command_capability_provider=command_bridge.capability_of,
    )

    # -- Interactive terminal session manager (Fase 7 E1) ---------------
    # Live PTY shells, scope-confined via ScopeService.scope_roots; output is
    # broadcast on the events WS, input/resize arrive over its receive loop.
    from backend.services.terminal import TerminalSessionManager

    terminal_manager = TerminalSessionManager(
        scope_provider=scope_service.scope_roots,
        scope_config=ctx.config.scope,
        shell=ctx.config.terminal.interactive_shell,
        max_sessions=ctx.config.terminal.max_sessions,
    )

    async def _broadcast_terminal_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    terminal_manager.set_event_callback(_broadcast_terminal_event)
    ctx.terminal_session_manager = terminal_manager

    # -- Kernel tool: app_command (spec §7) ------------------------------
    # Registered from boot with an empty manifest so the tool exists even
    # before the UI connects; every command.manifest re-registers it with
    # the live name enum + usage guidance.
    if ctx.config.commands.enabled and ctx.tool_registry is not None:
        await ctx.tool_registry.register_kernel_tool(
            build_app_command_definition([]),
            command_bridge.execute_app_command,
        )
