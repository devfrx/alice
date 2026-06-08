"""AL\\CE — Persistent permission-rule REST API (Fase 7).

Endpoints (mounted under ``/api/permission-rules``):

* ``GET /{conversation_id}`` — list the rules visible to the conversation (its
  own conversation-scoped rules plus all global rules).
* ``POST /{conversation_id}`` — UPSERT a rule (``scope`` selects conversation vs
  global).
* ``DELETE /{conversation_id}/{rule_id}`` — delete a rule by id.

These rules are the **durable** counterpart to the engine's ephemeral session
grants; they are read by the permission gate through
:meth:`~backend.services.permission_rules.PermissionRuleService.match`.  Like
the other permission surfaces, they are reachable only from the user (never from
a tool).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from backend.services.permission_rules import PermissionRuleService, RuleEffect

router = APIRouter(prefix="/permission-rules", tags=["permissions"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PermissionRuleOut(BaseModel):
    """A persisted permission rule, as returned by the API."""

    id: str
    conversation_id: str | None
    tool_name: str
    effect: str


class PermissionRuleCreateRequest(BaseModel):
    """Request body for ``POST /permission-rules/{conversation_id}``.

    Attributes:
        tool_name: The namespaced tool the rule applies to (exact match).
        effect: ``allow`` / ``ask`` / ``deny``.
        scope: ``conversation`` (default) ties the rule to this conversation;
            ``global`` applies it everywhere.
    """

    tool_name: str
    effect: str
    scope: str = "conversation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_uuid(value: str) -> uuid.UUID:
    """Validate *value* as a UUID or raise a 400."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID: {value}",
        ) from exc


def _get_rule_service(request: Request) -> PermissionRuleService | None:
    """Fetch the permission-rule service off ``app.state.context`` (``None`` if absent)."""
    ctx = getattr(request.app.state, "context", None)
    service: PermissionRuleService | None = (
        getattr(ctx, "permission_rule_service", None) if ctx else None
    )
    return service


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{conversation_id}",
    response_model=list[PermissionRuleOut],
    summary="List permission rules visible to a conversation",
)
async def list_permission_rules(
    conversation_id: str, request: Request,
) -> list[PermissionRuleOut]:
    """Return the conversation's own rules plus all global rules.

    Always succeeds for a valid id: an unwired service yields an empty list.

    Raises:
        HTTPException: ``400`` when *conversation_id* is not a valid UUID.
    """
    conv_uuid = _to_uuid(conversation_id)
    service = _get_rule_service(request)
    if service is None:
        return []
    rows = await service.list_rules(conv_uuid)
    return [
        PermissionRuleOut(
            id=str(r.id),
            conversation_id=(str(r.conversation_id) if r.conversation_id else None),
            tool_name=r.tool_name,
            effect=r.effect,
        )
        for r in rows
    ]


@router.post(
    "/{conversation_id}",
    response_model=PermissionRuleOut,
    summary="Add or update a permission rule",
)
async def create_permission_rule(
    conversation_id: str, body: PermissionRuleCreateRequest, request: Request,
) -> PermissionRuleOut:
    """UPSERT a rule for the conversation (``scope=conversation``) or globally.

    Raises:
        HTTPException: ``400`` for a bad UUID / unknown effect / unknown scope,
            ``503`` when the rule service is unavailable.
    """
    conv_uuid = _to_uuid(conversation_id)
    service = _get_rule_service(request)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Permission-rule service unavailable",
        )
    try:
        effect = RuleEffect(body.effect)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid effect: {body.effect}",
        ) from exc
    if body.scope not in ("conversation", "global"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope: {body.scope}",
        )
    target_conv = conv_uuid if body.scope == "conversation" else None
    row = await service.add_rule(
        tool_name=body.tool_name, effect=effect, conversation_id=target_conv,
    )
    return PermissionRuleOut(
        id=str(row.id),
        conversation_id=(str(row.conversation_id) if row.conversation_id else None),
        tool_name=row.tool_name,
        effect=row.effect,
    )


@router.delete(
    "/{conversation_id}/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a permission rule by id",
)
async def delete_permission_rule(
    conversation_id: str, rule_id: str, request: Request,
) -> None:
    """Delete the rule *rule_id* (no-op if it does not exist).

    Raises:
        HTTPException: ``400`` for a bad UUID, ``503`` when the rule service is
            unavailable.
    """
    _to_uuid(conversation_id)
    rid = _to_uuid(rule_id)
    service = _get_rule_service(request)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Permission-rule service unavailable",
        )
    await service.remove_rule(rid)
