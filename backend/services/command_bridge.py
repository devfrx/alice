"""AL\\CE — Command Bridge (Fase 7, spec §7): the kernel's hands on the app UI.

Backend side of the Command Layer: holds the frontend's agent-exposable
command manifest, gates it structurally (guardrail domains are rejected at
ingestion — the anti-escalation invariant), and runs the events-WS RPC for
the kernel-owned ``app_command`` tool: broadcast a ``command.request`` with a
fresh ``correlation_id``, await the matching ``command.result`` with a
timeout, and hand a CLEAN outcome back to the tool loop ("UI not available"
is a result, never an exception).

Layering: this module never imports ``backend.api.ws_schema`` — outbound
frames are plain dicts validated by the frame validator injected into the
connection manager; inbound frames are validated by the events route.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger

from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult
from backend.core.protocols import ToolRegistryProtocol, WSConnectionManagerProtocol

#: Command-name domains that configure the guardrails themselves. STRUCTURAL
#: anti-escalation (spec §7, non-negotiable): a manifest entry whose first
#: dotted segment is in this set is rejected at ingestion — the agent can
#: never call it, regardless of what the frontend declares.
GUARDRAIL_COMMAND_DOMAINS: frozenset[str] = frozenset({
    "permission",
    "permissions",
    "permission_mode",
    "scope",
    "guardrail",
    "guardrails",
})

_VALID_CAPABILITIES: frozenset[str] = frozenset({
    "navigation", "read", "mutate", "destructive",
})

#: Strict grammar for agent-callable command names: lowercase dotted
#: ``domain.action`` segments. Ingestion NFKC-normalizes, strips, then
#: rejects anything outside this grammar BEFORE the guardrail-domain check,
#: collapsing the whole unicode/whitespace/case trick space — the backend
#: leg of the anti-escalation gate must hold on its own against a
#: misbehaving frontend.
_COMMAND_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Service-layer mirror of one accepted manifest entry.

    Attributes:
        name: Dotted command name (``domain.action``).
        description: Machine-facing description for the LLM guidance.
        capability: One of ``navigation|read|mutate|destructive``.
        args_schema: JSON Schema of the command's args (informational here;
            enforced client-side before execution).
    """

    name: str
    description: str
    capability: str
    args_schema: dict[str, Any]


def build_app_command_definition(specs: list[CommandSpec]) -> ToolDefinition:
    """Build the kernel-owned ``app_command`` ToolDefinition for *specs*.

    The live manifest is baked into the tool surface: the ``name`` parameter
    carries an enum of the agent-callable command names (so the executor's
    JSON-Schema validation rejects unknown names for free) and
    ``usage_guidance`` lists each command for the system prompt.

    Args:
        specs: Accepted manifest entries (possibly empty).

    Returns:
        The ``app_command`` tool definition.
    """
    names = sorted(spec.name for spec in specs)
    name_schema: dict[str, Any] = {"type": "string"}
    if names:
        name_schema["enum"] = names
    guidance: str | None = None
    if specs:
        lines = [
            f"- `{spec.name}` ({spec.capability}): {spec.description}"
            for spec in sorted(specs, key=lambda spec: spec.name)
        ]
        guidance = (
            "Use `app_command` to drive the ALICE app UI itself (navigate, "
            "open conversations or artifacts). Pass the command `name` and "
            "its `args` object. Commands available now:\n" + "\n".join(lines)
        )
    return ToolDefinition(
        name="app_command",
        description=(
            "Invoke a UI command of the ALICE app (Command Layer). Available "
            "commands come from the app's live manifest; pass the command "
            "name and its args object."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": name_schema,
                "args": {"type": "object"},
            },
            "required": ["name"],
        },
        result_type="json",
        timeout_ms=30_000,
        capabilities=("ui_command",),
        always_offered=True,
        usage_guidance=guidance,
    )


class CommandBridgeService:
    """Manifest store + events-WS RPC for the ``app_command`` kernel tool."""

    def __init__(
        self,
        *,
        ws_manager: WSConnectionManagerProtocol | None,
        tool_registry: ToolRegistryProtocol | None,
        enabled: bool,
        rpc_timeout_s: float,
        disabled_commands: list[str],
    ) -> None:
        """Initialise the bridge.

        Args:
            ws_manager: Events-WS connection manager (broadcast + count).
            tool_registry: Registry used to (re-)register ``app_command`` on
                every manifest update. ``None`` skips tool refresh (tests).
            enabled: Master switch (``commands.enabled``).
            rpc_timeout_s: Seconds to wait for the UI's ``command.result``.
            disabled_commands: Per-command denylist
                (``commands.disabled_commands``).
        """
        self._ws_manager = ws_manager
        self._tool_registry = tool_registry
        self._enabled = enabled
        self._timeout_s = rpc_timeout_s
        self._disabled = frozenset(disabled_commands)
        self._manifest: dict[str, CommandSpec] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    def capability_of(self, command_name: str) -> str | None:
        """Return the manifest capability of *command_name* (``None`` = unknown).

        Consumed by ``PermissionService.decide`` as the
        ``command_capability_provider`` to resolve ``app_command``'s
        per-call effective capability.
        """
        spec = self._manifest.get(command_name)
        return spec.capability if spec is not None else None

    async def set_manifest(self, entries: list[dict[str, Any]]) -> None:
        """Replace the manifest with *entries* and refresh the kernel tool.

        Structural gates, in order: guardrail domains are REJECTED (the
        anti-escalation invariant — not configuration, construction),
        unknown capabilities are rejected, configured ``disabled_commands``
        are dropped. The surviving set replaces the previous manifest
        wholesale and ``app_command`` is re-registered with the new name
        enum + usage guidance.

        Args:
            entries: Plain-dict manifest entries (validated upstream by the
                events route against ``ws_schema``).
        """
        if not self._enabled:
            # Single authority for the master switch: a disabled bridge must
            # neither ingest manifests nor (re-)register the tool — otherwise
            # every FE connect would re-arm the surface the flag removes.
            logger.info(
                "Command Bridge disabled (commands.enabled=false): manifest ignored",
            )
            return
        accepted: dict[str, CommandSpec] = {}
        for entry in entries:
            raw_name = str(entry.get("name", ""))
            name = unicodedata.normalize("NFKC", raw_name).strip()
            capability = str(entry.get("capability", ""))
            if not name:
                logger.warning(
                    "Command Bridge: rejected manifest entry with empty name",
                )
                continue
            if not _COMMAND_NAME_PATTERN.match(name):
                logger.warning(
                    "Command Bridge: rejected command with invalid name {!r}",
                    raw_name,
                )
                continue
            domain = name.split(".", 1)[0]
            if domain in GUARDRAIL_COMMAND_DOMAINS:
                logger.warning(
                    "Command Bridge: rejected guardrail command '{}' from manifest",
                    name,
                )
                continue
            if capability not in _VALID_CAPABILITIES:
                logger.warning(
                    "Command Bridge: rejected command '{}' with invalid capability '{}'",
                    name, capability,
                )
                continue
            if name in self._disabled:
                logger.info(
                    "Command Bridge: command '{}' disabled by configuration", name,
                )
                continue
            if name in accepted:
                logger.debug(
                    "Command Bridge: duplicate manifest entry '{}' (last wins)", name,
                )
            args_schema = entry.get("args_schema")
            accepted[name] = CommandSpec(
                name=name,
                description=str(entry.get("description", "")),
                capability=capability,
                args_schema=dict(args_schema) if isinstance(args_schema, dict) else {},
            )
        self._manifest = accepted
        logger.info(
            "Command Bridge: manifest updated ({} agent-callable commands)",
            len(accepted),
        )
        if self._tool_registry is not None:
            await self._tool_registry.register_kernel_tool(
                build_app_command_definition(list(accepted.values())),
                self.execute_app_command,
            )

    # ------------------------------------------------------------------
    # RPC
    # ------------------------------------------------------------------

    def resolve(self, correlation_id: str, payload: dict[str, Any]) -> None:
        """Resolve the pending request matching *correlation_id*.

        Called by the events route on an inbound ``command.result``. A stale
        or unknown id (timeout already fired, duplicate window answering
        twice) is a debug-logged no-op.
        """
        future = self._pending.pop(correlation_id, None)
        if future is None or future.done():
            logger.debug(
                "Command Bridge: stale/unknown correlation_id '{}'", correlation_id,
            )
            return
        future.set_result(payload)

    async def call_command(
        self,
        name: str,
        args: dict[str, Any],
        *,
        conversation_id: str,
    ) -> dict[str, Any]:
        """Run one command RPC round-trip against the UI.

        Every failure mode is a CLEAN outcome dict (never an exception), so
        the tool loop always receives a normal ``ToolResult``.

        Args:
            name: Manifest command name.
            args: Command args (opaque JSON object, validated client-side).
            conversation_id: Conversation the turn belongs to (audit/context).

        Returns:
            ``{"ok": True, "result": ...}`` or ``{"ok": False, "error": str}``.
        """
        if not self._enabled:
            return {
                "ok": False,
                "error": (
                    "Command Bridge disabled by configuration "
                    "(commands.enabled=false)"
                ),
            }
        if name in self._disabled:
            return {
                "ok": False,
                "error": f"Command '{name}' is disabled by configuration",
            }
        if name not in self._manifest:
            known = ", ".join(sorted(self._manifest)) or "none"
            return {
                "ok": False,
                "error": (
                    f"Unknown command '{name}'. Agent-callable commands: {known}"
                ),
            }
        if self._ws_manager is None or self._ws_manager.connection_count == 0:
            return {"ok": False, "error": "UI not available (no connected frontend)"}

        correlation_id = uuid.uuid4().hex
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[correlation_id] = future
        try:
            await self._ws_manager.broadcast({
                "type": "command.request",
                "origin": "agent",
                "correlation_id": correlation_id,
                "name": name,
                "args": args,
                "conversation_id": conversation_id,
            })
            payload = await asyncio.wait_for(future, timeout=self._timeout_s)
        except TimeoutError:
            return {
                "ok": False,
                "error": (
                    f"UI did not respond to '{name}' within {self._timeout_s:g}s"
                ),
            }
        except Exception as exc:  # noqa: BLE001 — a clean result, never an exception
            logger.warning("Command Bridge: dispatch of '{}' failed: {}", name, exc)
            return {"ok": False, "error": f"Command dispatch failed: {exc}"}
        finally:
            self._pending.pop(correlation_id, None)

        if payload.get("ok"):
            return {"ok": True, "result": payload.get("result")}
        return {
            "ok": False,
            "error": str(payload.get("error") or "command failed in the UI"),
        }

    # ------------------------------------------------------------------
    # Kernel tool handler
    # ------------------------------------------------------------------

    async def execute_app_command(
        self, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        """Kernel handler for the ``app_command`` tool.

        Args:
            args: ``{"name": str, "args": dict}`` (schema-validated upstream
                by the executor against the manifest-derived enum).
            context: The turn's execution context.

        Returns:
            ``ToolResult.ok`` with the UI's result payload, or a clean
            ``ToolResult.error``.
        """
        name = str(args.get("name", ""))
        command_args = args.get("args")
        if command_args is None:
            command_args = {}
        if not isinstance(command_args, dict):
            return ToolResult.error("app_command: 'args' must be an object")
        # NB: the permission gate resolved this command's capability at
        # decide() time; a manifest update in between could re-tag it (TOCTOU).
        # Only the trusted frontend can push manifests, and call_command still
        # re-checks membership — accepted window.
        outcome = await self.call_command(
            name, command_args, conversation_id=context.conversation_id,
        )
        if outcome.get("ok"):
            return ToolResult.ok(
                {"command": name, "result": outcome.get("result")},
                content_type="application/json",
            )
        return ToolResult.error(str(outcome.get("error") or "command failed"))
