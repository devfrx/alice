"""AL\\CE — Central tool-permission authority (Fase 2, foundation D).

``PermissionService`` is the single place that answers *"may this tool-call
run?"* for the turn engine. It replaces the per-plugin, easily-forgotten
checks that let a new tool silently escape a sandbox. The turn engine's
``PermissionMiddleware`` delegates here for:

* **risk policy** — a ``risk_level="forbidden"`` tool is always blocked;
  ``requires_confirmation`` tools are *classified* here (the actual user
  round-trip lives in ``ConfirmationMiddleware``);
* **scope confinement (by construction)** — any tool tagged with a filesystem
  capability (``fs_read`` / ``fs_write``) has every declared ``path_args``
  argument resolved against the conversation's workspace scope; a path outside
  the scope is **denied by default**. A tool that forgets a manual check still
  cannot escape, because the guard is generic (capability-driven), not
  per-plugin;
* **per-conversation grants** — an *"always allow X here"* override that bypasses
  the scope check for a specific tool within one conversation.

Fase 2 wires the *mechanism*; the workspace scope itself arrives in Fase 6
(``ScopeService``). Until a ``scope_provider`` yields folders for a conversation
there is **no confinement** — so this service introduces *no new denials* and
the turn behaviour is preserved.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from loguru import logger

from backend.core.plugin_models import ToolDefinition
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_rules import RuleEffect

# A scope provider maps a conversation id to its allowed root folders, or
# ``None``/empty when no workspace scope is configured (the Fase 2 default).
ScopeProvider = Callable[[str], "list[Path] | None"]

# A rule provider maps (conversation_id, tool_name) to a persisted rule effect,
# or ``None`` when no rule applies (the gate then falls back to the tier).
RuleProvider = Callable[[str, str], "RuleEffect | None"]

# Resolves a UI command name to its manifest capability tag
# (navigation|read|mutate|destructive), or ``None`` when unknown (Fase 7).
CommandCapabilityProvider = Callable[[str], "str | None"]

#: Capability tag marking the kernel's ``app_command`` tool: its EFFECTIVE
#: capability is per-call (the invoked command's manifest tag), resolved via
#: the injected ``command_capability_provider``.
UI_COMMAND_CAPABILITY = "ui_command"

#: Capability tag marking an MCP tool that (potentially) mutates state (Fase 2
#: MCP perimeter). Treated by the plan tier exactly like ``fs_write`` /
#: ``process_exec``: denied, and withheld from the offered toolset
#: (``permission_mode_policy``).
MCP_WRITE_CAPABILITY = "mcp_write"

# Capability tags that mark a tool as filesystem-path-confined.
_DEFAULT_FS_CAPABILITIES: frozenset[str] = frozenset({"fs_read", "fs_write"})


class PermissionOutcome(StrEnum):
    """Why a permission decision came out the way it did."""

    ALLOW = "allow"
    DENY_FORBIDDEN = "deny_forbidden"
    DENY_SCOPE = "deny_scope"
    DENY_NO_SCOPE = "deny_no_scope"
    DENY_PLAN_MODE = "deny_plan_mode"
    DENY_RULE = "deny_rule"


class GateAction(StrEnum):
    """The action the permission gate asks the engine to take for a tool-call."""

    ALLOW = "allow"
    DENY = "deny"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Result of :meth:`PermissionService.evaluate`.

    Attributes:
        allowed: ``True`` if the tool-call may proceed.
        outcome: The classification behind the decision.
        reason: Short machine-friendly reason (used for audit rows /
            user-facing messages) when denied; ``None`` when allowed.
    """

    allowed: bool
    outcome: PermissionOutcome
    reason: str | None = None

    @classmethod
    def allow(cls) -> PermissionDecision:
        """Return an allowing decision."""
        return cls(allowed=True, outcome=PermissionOutcome.ALLOW, reason=None)

    @classmethod
    def deny(cls, outcome: PermissionOutcome, reason: str) -> PermissionDecision:
        """Return a denying decision with *reason*."""
        return cls(allowed=False, outcome=outcome, reason=reason)


@dataclass(frozen=True, slots=True)
class GateDecision:
    """The three-valued verdict returned by :meth:`PermissionService.decide`.

    Attributes:
        action: ``ALLOW`` (run, no prompt), ``DENY`` (hard block), or
            ``NEEDS_CONFIRMATION`` (round-trip with the user).
        outcome: The classification behind the verdict (for audit / messaging).
        reason: Short machine-friendly reason when denied; ``None`` otherwise.
    """

    action: GateAction
    outcome: PermissionOutcome
    reason: str | None = None

    @classmethod
    def allow(cls, outcome: PermissionOutcome = PermissionOutcome.ALLOW) -> GateDecision:
        """Return an allowing verdict."""
        return cls(action=GateAction.ALLOW, outcome=outcome, reason=None)

    @classmethod
    def confirm(cls) -> GateDecision:
        """Return a verdict requesting a user confirmation round-trip."""
        return cls(action=GateAction.NEEDS_CONFIRMATION, outcome=PermissionOutcome.ALLOW)

    @classmethod
    def deny(cls, outcome: PermissionOutcome, reason: str) -> GateDecision:
        """Return a denying verdict with *reason*."""
        return cls(action=GateAction.DENY, outcome=outcome, reason=reason)


class PermissionService:
    """Central authority for tool risk policy, scope confinement and grants."""

    def __init__(
        self,
        *,
        scope_provider: ScopeProvider | None = None,
        rule_provider: RuleProvider | None = None,
        forbidden_paths: Iterable[str | Path] = (),
        fs_capabilities: Iterable[str] = _DEFAULT_FS_CAPABILITIES,
        command_capability_provider: CommandCapabilityProvider | None = None,
    ) -> None:
        """Initialise the service.

        Args:
            scope_provider: Callable returning the allowed root folders for a
                conversation, or ``None`` when no scope is set. ``None``
                (the Fase 2 default) disables confinement entirely.
            rule_provider: Callable returning the persisted rule effect for a
                ``(conversation_id, tool_name)`` pair, or ``None`` when no rule
                applies (Fase 7). ``None`` disables persistent-rule consultation.
            forbidden_paths: Roots that are always out of scope even when a
                workspace scope is set (Fase 6 ``WorkspaceScopeConfig``).
            fs_capabilities: Capability tags that mark a tool as
                path-confined. Defaults to ``{"fs_read", "fs_write"}``.
            command_capability_provider: Resolves a UI command name to its
                manifest capability tag (Fase 7 Command Bridge). ``None``
                (or an unknown command) makes ``app_command`` calls
                fail-conservative (treated as ``destructive``).
        """
        self._scope_provider = scope_provider
        self._rule_provider = rule_provider
        self._fs_capabilities = frozenset(fs_capabilities)
        self._command_capability_provider = command_capability_provider
        self._forbidden_paths: tuple[Path, ...] = tuple(
            self._safe_resolve(p) for p in forbidden_paths
        )
        # Per-conversation grants: conversation_id -> set of granted keys
        # (a key is typically a tool name). An *"always allow"* override.
        self._grants: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Risk classification
    # ------------------------------------------------------------------

    @staticmethod
    def is_forbidden(tool_def: ToolDefinition | None) -> bool:
        """Return ``True`` for a tool whose risk level is ``"forbidden"``."""
        return tool_def is not None and tool_def.risk_level == "forbidden"

    @staticmethod
    def requires_confirmation(tool_def: ToolDefinition | None) -> bool:
        """Return ``True`` when the tool opts into a user confirmation gate.

        Centralises the per-tool classification; whether the confirmation is
        actually requested also depends on the runtime
        ``permissions.confirmations_enabled`` toggle, applied by the engine's
        ``ConfirmationMiddleware``.
        """
        return tool_def is not None and tool_def.requires_confirmation

    # ------------------------------------------------------------------
    # Combined evaluation (forbidden + scope confinement)
    # ------------------------------------------------------------------

    def evaluate(
        self,
        *,
        tool_name: str,
        args: dict[str, object],
        tool_def: ToolDefinition | None,
        conversation_id: str,
    ) -> PermissionDecision:
        """Decide whether a tool-call may run.

        Order: forbidden risk wins first, then by-construction scope
        confinement. Returns :meth:`PermissionDecision.allow` when neither
        applies (always, in Fase 2, for non-forbidden tools — no scope yet).

        Args:
            tool_name: Namespaced tool name.
            args: Parsed tool arguments.
            tool_def: The tool's definition (``None`` ⇒ unknown tool, allowed
                here; the registry rejects truly unknown tools at execution).
            conversation_id: Conversation the call belongs to (scope + grants).
        """
        if self.is_forbidden(tool_def):
            return PermissionDecision.deny(
                PermissionOutcome.DENY_FORBIDDEN, "forbidden_tool",
            )
        return self._check_scope(tool_name, args, tool_def, conversation_id)

    def decide(
        self,
        *,
        tool_name: str,
        args: dict[str, object],
        tool_def: ToolDefinition | None,
        conversation_id: str,
        mode: PermissionMode,
    ) -> GateDecision:
        """Resolve a tool-call to ALLOW / DENY / NEEDS_CONFIRMATION for *mode*.

        The single policy function the turn engine's permission gate consults.
        Precedence (top wins); circuit-breakers and explicit user rules are
        evaluated before the tier defaults so they hold in **every** tier,
        autopilot included:

        1. forbidden risk → DENY (breaker).
        2. explicit ``deny`` rule → DENY (a user prohibition wins everywhere).
        2-bis. ``ui_command`` tool without fs/exec capabilities → the §7
           matrix on the invoked command's manifest tag
           (:meth:`_decide_ui_command`); a hybrid with fs/exec capabilities
           falls through to the scope guard below.
        3. fs tool with no scope set → DENY (scope is the workspace boundary —
           holds even in autopilot).
        4. fs tool whose path is out of scope → DENY (a session grant or an
           explicit ``allow`` rule bypasses *only* this check, never #3).
        5. ``plan`` tier + write/exec/MCP-write → DENY (read-only stance;
           allow-rules and grants do not reopen writes in plan mode).
        6. read-only fs in scope → ALLOW (reads never prompt, any tier).
        7. session grant / ``allow`` rule → ALLOW; ``ask`` rule → confirmation.
        8. ``autopilot`` → ALLOW.
        9. ``auto_edits`` → confirmation for exec/dangerous, ALLOW for safe
           in-scope writes, confirmation for other confirmation-required tools.
        10. ``strict`` (default) → confirmation iff the tool requires it, else
            ALLOW (reproduces the pre-Fase-7 behaviour exactly).

        Args:
            tool_name: Namespaced tool name.
            args: Parsed tool arguments.
            tool_def: The tool's definition (``None`` ⇒ unknown tool).
            conversation_id: Conversation the call belongs to (scope/rules/grants).
            mode: The conversation's permission tier.

        Returns:
            A :class:`GateDecision`.
        """
        caps = set(tool_def.capabilities) if tool_def is not None else set()
        is_write = "fs_write" in caps
        is_exec = "process_exec" in caps
        is_fs = bool(caps & self._fs_capabilities)
        is_read_only_fs = ("fs_read" in caps) and not (is_write or is_exec)

        # 1. forbidden risk — absolute.
        if self.is_forbidden(tool_def):
            return GateDecision.deny(PermissionOutcome.DENY_FORBIDDEN, "forbidden_tool")

        rule = (
            self._rule_provider(conversation_id, tool_name)
            if self._rule_provider is not None
            else None
        )
        granted = self.is_granted(conversation_id, tool_name)

        # 2. explicit deny rule — a user prohibition wins in every tier.
        if rule is RuleEffect.DENY:
            return GateDecision.deny(PermissionOutcome.DENY_RULE, "user_denied")

        # 2-bis. UI commands (Fase 7, spec §7): the EFFECTIVE capability is
        # the invoked command's manifest tag, not the tool's own — resolve it
        # per-call and apply the §7 matrix. Grants and allow/ask rules keep
        # their usual precedence; the deny rule above already won. A hybrid
        # declaring ui_command TOGETHER with fs/exec capabilities does NOT
        # take this branch: it falls through to scope confinement below, so
        # the tag can never be used to skip the by-construction fs guard.
        if UI_COMMAND_CAPABILITY in caps and not (is_fs or is_exec):
            return self._decide_ui_command(args, mode, granted=granted, rule=rule)

        # 3 + 4. filesystem scope confinement (by construction).
        if is_fs:
            scope_roots = self._resolve_scope(conversation_id)
            if not scope_roots:
                # No workspace boundary ⇒ no filesystem access, even in autopilot.
                return GateDecision.deny(PermissionOutcome.DENY_NO_SCOPE, "no_scope")
            # A session grant or an explicit allow-rule bypasses ONLY the
            # out-of-scope path check (never the no-scope breaker above).
            if not granted and rule is not RuleEffect.ALLOW:
                path_args = tool_def.path_args if tool_def is not None else ()
                for arg_name in path_args:
                    raw = args.get(arg_name)
                    if raw is None:
                        continue
                    if not self._within_scope(str(raw), scope_roots):
                        logger.warning(
                            "Permission: '{}' arg '{}'={!r} is outside conversation "
                            "scope (conv={})",
                            tool_name, arg_name, raw, conversation_id,
                        )
                        return GateDecision.deny(
                            PermissionOutcome.DENY_SCOPE, "outside_scope",
                        )

        # 5. plan tier is read-only: block writes / process-exec / MCP writes.
        if mode is PermissionMode.PLAN and (
            is_write or is_exec or MCP_WRITE_CAPABILITY in caps
        ):
            return GateDecision.deny(PermissionOutcome.DENY_PLAN_MODE, "plan_mode")

        # 6. reads inside scope never prompt, in any tier.
        if is_read_only_fs:
            return GateDecision.allow()

        # 7. explicit user grant / rule override the tier default.
        if granted or rule is RuleEffect.ALLOW:
            return GateDecision.allow()
        if rule is RuleEffect.ASK:
            return GateDecision.confirm()

        # 8-10. tier defaults.
        if mode is PermissionMode.AUTOPILOT:
            return GateDecision.allow()
        if mode is PermissionMode.AUTO_EDITS:
            if is_exec or (tool_def is not None and tool_def.risk_level == "dangerous"):
                return GateDecision.confirm()
            if is_write:
                return GateDecision.allow()
            if self.requires_confirmation(tool_def):
                return GateDecision.confirm()
            return GateDecision.allow()
        # plan (neutral, non-write/exec tools) and strict share the default tail.
        if self.requires_confirmation(tool_def):
            return GateDecision.confirm()
        return GateDecision.allow()

    def explain_denial(
        self,
        *,
        tool_name: str,
        args: dict[str, object],
        tool_def: ToolDefinition | None,
        conversation_id: str,
        mode: PermissionMode | None,
    ) -> str | None:
        """Gate one call for surfaces that have no confirmation UI (Fase 8).

        Same policy as a normal turn (spec §4.5: no privileged path), but a
        ``NEEDS_CONFIRMATION`` verdict is a *denial* here: headless surfaces
        (sub-agents, autonomous turns) have no user to ask — the Fase 7
        clean-result philosophy.

        Returns:
            ``None`` when the call may run, else a human-readable reason.
        """
        if mode is None:
            mode = PermissionMode.STRICT
        decision = self.decide(
            tool_name=tool_name,
            args=args,
            tool_def=tool_def,
            conversation_id=conversation_id,
            mode=mode,
        )
        if decision.action is GateAction.ALLOW:
            return None
        if decision.action is GateAction.NEEDS_CONFIRMATION:
            return (
                f"Tool '{tool_name}' requires user confirmation, which is "
                "not available in this context."
            )
        reason = f" ({decision.reason})" if decision.reason else ""
        return f"Tool '{tool_name}' denied by permission policy{reason}."

    def _decide_ui_command(
        self,
        args: dict[str, object],
        mode: PermissionMode,
        *,
        granted: bool,
        rule: RuleEffect | None,
    ) -> GateDecision:
        """Spec §7 matrix for ``app_command``: gate on the command's tag.

        ``navigation``/``read`` are always allowed (reads never prompt, any
        tier — plan included); ``mutate``/``destructive`` are denied in
        ``plan`` and confirmed in ``strict``; ``auto_edits`` auto-approves
        ``mutate`` but confirms ``destructive``; ``autopilot`` allows. An
        unknown command (absent manifest/provider) is treated as
        ``destructive`` — fail-conservative; execution then returns its own
        clean "unknown command" / "UI not available" result.
        """
        command = str(args.get("name", ""))
        # The provider only ever returns manifest-validated tags (the bridge
        # rejects out-of-vocabulary capabilities at ingestion); any other
        # non-falsy string still lands in the destructive-equivalent branch.
        capability = (
            self._command_capability_provider(command)
            if self._command_capability_provider is not None
            else None
        ) or "destructive"
        if capability in ("navigation", "read"):
            return GateDecision.allow()
        if mode is PermissionMode.PLAN:
            logger.info(
                "Permission: ui command '{}' denied in plan mode (capability {})",
                command, capability,
            )
            return GateDecision.deny(PermissionOutcome.DENY_PLAN_MODE, "plan_mode")
        if granted or rule is RuleEffect.ALLOW:
            return GateDecision.allow()
        if rule is RuleEffect.ASK:
            return GateDecision.confirm()
        if mode is PermissionMode.AUTOPILOT:
            return GateDecision.allow()
        if mode is PermissionMode.AUTO_EDITS and capability == "mutate":
            return GateDecision.allow()
        return GateDecision.confirm()

    def _check_scope(
        self,
        tool_name: str,
        args: dict[str, object],
        tool_def: ToolDefinition | None,
        conversation_id: str,
    ) -> PermissionDecision:
        """Confine a filesystem tool's path arguments to the conversation scope.

        Allows when: the tool is not filesystem-tagged, no scope is configured,
        the call is explicitly granted, or every declared path argument
        resolves inside the scope. Denies by default otherwise.
        """
        if tool_def is None:
            return PermissionDecision.allow()
        if not (set(tool_def.capabilities) & self._fs_capabilities):
            # Not a path-confined tool — no scope policy applies.
            return PermissionDecision.allow()

        scope_roots = self._resolve_scope(conversation_id)
        if not scope_roots:
            # Fase 2: no workspace scope set ⇒ no confinement (allow).
            return PermissionDecision.allow()

        if self.is_granted(conversation_id, tool_name):
            # Explicit per-conversation override ("always allow X here").
            return PermissionDecision.allow()

        for arg_name in tool_def.path_args:
            raw = args.get(arg_name)
            if raw is None:
                continue
            if not self._within_scope(str(raw), scope_roots):
                logger.warning(
                    "Permission: '{}' arg '{}'={!r} is outside conversation "
                    "scope (conv={})",
                    tool_name, arg_name, raw, conversation_id,
                )
                return PermissionDecision.deny(
                    PermissionOutcome.DENY_SCOPE, "outside_scope",
                )
        return PermissionDecision.allow()

    # ------------------------------------------------------------------
    # Per-conversation grants
    # ------------------------------------------------------------------

    def grant(self, conversation_id: str, key: str) -> None:
        """Record an *"always allow ``key`` in this conversation"* override."""
        self._grants.setdefault(conversation_id, set()).add(key)

    def revoke(self, conversation_id: str, key: str) -> None:
        """Remove a previously-recorded grant (no-op if absent)."""
        grants = self._grants.get(conversation_id)
        if grants is not None:
            grants.discard(key)

    def is_granted(self, conversation_id: str, key: str) -> bool:
        """Return ``True`` if *key* was granted in *conversation_id*."""
        return key in self._grants.get(conversation_id, ())

    def clear_grants(self, conversation_id: str) -> None:
        """Drop every grant recorded for *conversation_id*."""
        self._grants.pop(conversation_id, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_scope(self, conversation_id: str) -> list[Path]:
        """Return the resolved scope roots for a conversation (empty ⇒ none)."""
        if self._scope_provider is None:
            return []
        roots = self._scope_provider(conversation_id)
        if not roots:
            return []
        return [self._safe_resolve(r) for r in roots]

    def _within_scope(self, raw_path: str, scope_roots: Iterable[Path]) -> bool:
        """Return ``True`` iff *raw_path* resolves inside a scope root.

        Resolves symlinks/``..`` first (so traversal cannot escape), then
        rejects anything under a configured forbidden path.
        """
        target = self._safe_resolve(raw_path)
        for forbidden in self._forbidden_paths:
            if self._is_relative_to(target, forbidden):
                return False
        return any(self._is_relative_to(target, root) for root in scope_roots)

    @staticmethod
    def _safe_resolve(path: str | Path) -> Path:
        """Best-effort absolute resolution (``strict=False``)."""
        return Path(path).resolve()

    @staticmethod
    def _is_relative_to(target: Path, root: Path) -> bool:
        """``Path.is_relative_to`` without raising (3.9+ compatible)."""
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False
