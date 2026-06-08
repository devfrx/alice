"""AL\\CE — Persistent per-tool permission rules (Fase 7).

A small, independently-testable layer that persists *"always allow / ask /
deny tool X"* decisions so they survive restarts — the durable counterpart to
:class:`~backend.services.permission_service.PermissionService`'s ephemeral
in-memory *session grants*.  It is injected into the permission gate as a
**synchronous** ``match`` provider (mirroring the scope provider) so the hot
tool-call path never awaits.

Resolution semantics:

* a **conversation-scoped** rule (``conversation_id`` set) wins over a
  **global** rule (``conversation_id`` is ``NULL``) for the same tool;
* there is at most one rule per ``(scope, tool_name)`` — :meth:`add_rule`
  UPSERTs — so within a scope there is nothing to disambiguate, but the mirror
  builder still resolves any accidental duplicates by precedence
  ``deny > ask > allow`` (defence-in-depth).

``tool_name`` is matched exactly; the reserved ``pattern`` column (see
:class:`~backend.db.models.PermissionRule`) lets a future bash-prefix matcher
land without changing this contract.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import PermissionRule


class RuleEffect(StrEnum):
    """The effect a matched permission rule imposes on a tool-call."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


# Precedence used only to resolve accidental duplicate rules in one scope.
_EFFECT_RANK: dict[RuleEffect, int] = {
    RuleEffect.DENY: 3,
    RuleEffect.ASK: 2,
    RuleEffect.ALLOW: 1,
}


@dataclass(frozen=True, slots=True)
class _Rule:
    """A detached, immutable snapshot of a persisted rule (for the sync mirror)."""

    id: str
    conversation_id: str | None
    tool_name: str
    effect: RuleEffect


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def _to_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce *value* to ``uuid.UUID`` (accepts an existing UUID or a str)."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class PermissionRuleService:
    """Persist and serve per-tool allow/ask/deny rules.

    Keeps an in-memory list of rules plus two derived lookup dicts
    (conversation-scoped and global, strongest-effect per tool) so :meth:`match`
    — read by the permission gate — answers synchronously.  Mutations
    (:meth:`add_rule` / :meth:`remove_rule`) write the DB then rebuild the mirror.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[SQLModelAsyncSession],
    ) -> None:
        """Build a new rule service.

        Args:
            session_factory: An async SQLModel session factory (the same one
                stored on :attr:`AppContext.db`).
        """
        self._session_factory = session_factory
        self._rules: list[_Rule] = []
        # Derived (rebuilt on every load/mutation): strongest effect per key.
        self._by_conv: dict[tuple[str, str], RuleEffect] = {}
        self._global: dict[str, RuleEffect] = {}

    # ------------------------------------------------------------------
    # Load / mirror
    # ------------------------------------------------------------------

    async def load_all(self) -> None:
        """Populate the in-memory mirror from every persisted rule row."""
        async with self._session_factory() as session:
            result = await session.exec(select(PermissionRule))
            rows = result.all()
        self._rules = [
            _Rule(
                id=str(row.id),
                conversation_id=(str(row.conversation_id) if row.conversation_id else None),
                tool_name=row.tool_name,
                effect=RuleEffect(row.effect),
            )
            for row in rows
        ]
        self._rebuild()
        logger.debug("Loaded {} permission rule(s)", len(self._rules))

    def _rebuild(self) -> None:
        """Recompute the conversation/global lookup dicts from ``self._rules``."""
        by_conv: dict[tuple[str, str], RuleEffect] = {}
        glob: dict[str, RuleEffect] = {}
        for rule in self._rules:
            if rule.conversation_id is None:
                key = rule.tool_name
                if key not in glob or _EFFECT_RANK[rule.effect] > _EFFECT_RANK[glob[key]]:
                    glob[key] = rule.effect
            else:
                ckey = (rule.conversation_id, rule.tool_name)
                if ckey not in by_conv or _EFFECT_RANK[rule.effect] > _EFFECT_RANK[by_conv[ckey]]:
                    by_conv[ckey] = rule.effect
        self._by_conv = by_conv
        self._global = glob

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def match(self, conversation_id: str, tool_name: str) -> RuleEffect | None:
        """Return the effective rule for *tool_name* in *conversation_id* (**SYNC**).

        A conversation-scoped rule shadows a global one for the same tool.
        Returns ``None`` when no rule applies (the gate then falls back to the
        tier default).

        Args:
            conversation_id: The conversation the tool-call belongs to.
            tool_name: The namespaced tool name.

        Returns:
            The matched :class:`RuleEffect`, or ``None``.
        """
        conv_hit = self._by_conv.get((str(conversation_id), tool_name))
        if conv_hit is not None:
            return conv_hit
        return self._global.get(tool_name)

    async def list_rules(self, conversation_id: uuid.UUID | str) -> list[PermissionRule]:
        """Return all rules visible to *conversation_id* (its own + global).

        Reads the DB so the API always reflects persisted truth.

        Args:
            conversation_id: The owning conversation id.

        Returns:
            The matching :class:`PermissionRule` rows (conversation-scoped and
            global), newest first.
        """
        conv_uuid = _to_uuid(conversation_id)
        async with self._session_factory() as session:
            result = await session.exec(
                select(PermissionRule)
                .where(
                    (col(PermissionRule.conversation_id) == conv_uuid)
                    | col(PermissionRule.conversation_id).is_(None)
                )
                .order_by(col(PermissionRule.created_at).desc())
            )
            return list(result.all())

    # ------------------------------------------------------------------
    # Mutate
    # ------------------------------------------------------------------

    async def add_rule(
        self,
        *,
        tool_name: str,
        effect: RuleEffect,
        conversation_id: uuid.UUID | str | None = None,
    ) -> PermissionRule:
        """UPSERT a rule for ``(scope, tool_name)`` and refresh the mirror.

        At most one rule exists per ``(conversation_id, tool_name)`` pair
        (``conversation_id is None`` ⇒ a global rule); an existing rule for the
        same key has its effect updated rather than a duplicate inserted.

        Args:
            tool_name: The namespaced tool name the rule applies to.
            effect: The rule effect (allow / ask / deny).
            conversation_id: The owning conversation, or ``None`` for a global
                rule.

        Returns:
            The persisted :class:`PermissionRule` row.
        """
        conv_uuid = _to_uuid(conversation_id) if conversation_id is not None else None
        async with self._session_factory() as session:
            existing = await session.exec(
                select(PermissionRule).where(
                    col(PermissionRule.tool_name) == tool_name,
                    (
                        col(PermissionRule.conversation_id) == conv_uuid
                        if conv_uuid is not None
                        else col(PermissionRule.conversation_id).is_(None)
                    ),
                )
            )
            row = existing.first()
            if row is None:
                row = PermissionRule(
                    conversation_id=conv_uuid,
                    tool_name=tool_name,
                    effect=effect.value,
                )
                session.add(row)
            else:
                row.effect = effect.value
            await session.commit()
            await session.refresh(row)
            persisted = row

        await self._reload_into_mirror()
        logger.debug(
            "Permission rule upserted: tool={} effect={} scope={}",
            tool_name, effect.value, "global" if conv_uuid is None else str(conv_uuid),
        )
        return persisted

    async def remove_rule(self, rule_id: uuid.UUID | str) -> None:
        """Delete the rule *rule_id* and refresh the mirror (no-op if absent)."""
        rid = _to_uuid(rule_id)
        async with self._session_factory() as session:
            row = await session.get(PermissionRule, rid)
            if row is not None:
                await session.delete(row)
                await session.commit()
        await self._reload_into_mirror()

    async def _reload_into_mirror(self) -> None:
        """Re-read every rule into the in-memory mirror after a mutation."""
        await self.load_all()

    # Typing helper for callers that want the raw effect dicts (tests).
    def _snapshot(self) -> dict[str, Any]:
        """Return a debug snapshot of the derived lookup dicts."""
        return {"by_conv": dict(self._by_conv), "global": dict(self._global)}
