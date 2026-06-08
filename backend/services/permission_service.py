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

# A scope provider maps a conversation id to its allowed root folders, or
# ``None``/empty when no workspace scope is configured (the Fase 2 default).
ScopeProvider = Callable[[str], "list[Path] | None"]

# Capability tags that mark a tool as filesystem-path-confined.
_DEFAULT_FS_CAPABILITIES: frozenset[str] = frozenset({"fs_read", "fs_write"})


class PermissionOutcome(StrEnum):
    """Why a permission decision came out the way it did."""

    ALLOW = "allow"
    DENY_FORBIDDEN = "deny_forbidden"
    DENY_SCOPE = "deny_scope"


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


class PermissionService:
    """Central authority for tool risk policy, scope confinement and grants."""

    def __init__(
        self,
        *,
        scope_provider: ScopeProvider | None = None,
        forbidden_paths: Iterable[str | Path] = (),
        fs_capabilities: Iterable[str] = _DEFAULT_FS_CAPABILITIES,
    ) -> None:
        """Initialise the service.

        Args:
            scope_provider: Callable returning the allowed root folders for a
                conversation, or ``None`` when no scope is set. ``None``
                (the Fase 2 default) disables confinement entirely.
            forbidden_paths: Roots that are always out of scope even when a
                workspace scope is set (Fase 6 ``WorkspaceScopeConfig``).
            fs_capabilities: Capability tags that mark a tool as
                path-confined. Defaults to ``{"fs_read", "fs_write"}``.
        """
        self._scope_provider = scope_provider
        self._fs_capabilities = frozenset(fs_capabilities)
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
