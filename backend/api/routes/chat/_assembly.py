"""AL\\CE — Chat turn assembly.

Extracts the heavy ``ws_chat`` preamble — conversation resolution, user
message persistence (with edit-versioning / branch inheritance),
attachment linking, history fetch + filtering, tool selection, auxiliary
context (memory / MCP / whiteboards), system-prompt + message building,
and pre-generation context compression — into a single cohesive
:class:`TurnAssembler`.

The assembler returns an :class:`AssemblyResult` bundling the immutable
:class:`TurnInput` together with the few stateful objects the WebSocket
handler still needs for execution and persistence.  Validation failures
emit a WS ``error`` frame and return ``None`` so the caller skips the turn
(identical to the legacy ``continue`` branches).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import WebSocket
from loguru import logger
from sqlmodel import select

from backend.core.config import PROJECT_ROOT
from backend.core.context import AppContext
from backend.db.models import Attachment, Conversation, Message
from backend.services.context_manager import CompressionResult, ContextUsage
from backend.services.llm_service import LLMService
from backend.services.permission_mode_policy import ModePolicy, policy_for
from backend.services.permission_mode_service import PermissionMode
from backend.services.plan_document_service import render_plan_document
from backend.services.plan_service import render_task_steps
from backend.services.turn import TurnInput

from ._helpers import (
    _archive_messages_in_db,
    _build_mcp_context,
    _build_permission_context,
    _build_tool_rag_query,
    _build_whiteboard_context,
    _compute_context_breakdown,
    _filter_history_for_llm,
    _format_memory_context,
    _sync_conversation_to_file,
)


def _coerce_tier_guidance(
    raw: dict[str, str] | None,
) -> dict[PermissionMode, str]:
    """Map a tier-string→text config dict to ``{PermissionMode: str}``.

    The user-facing config (``agent.prompts.tier_guidance``) is keyed by tier
    *strings* (``"strict"``, ``"auto_edits"``, ``"plan"``, ``"autopilot"``).
    This converts those keys to :class:`PermissionMode` members, dropping any
    unknown key or empty/blank value so they transparently fall back to the
    built-in per-tier defaults inside :func:`policy_for`.

    Args:
        raw: The config mapping (possibly ``None`` / empty).

    Returns:
        A ``{PermissionMode: guidance}`` mapping (empty when nothing applies).
    """
    if not raw:
        return {}
    result: dict[PermissionMode, str] = {}
    for key, text in raw.items():
        if not text or not str(text).strip():
            continue
        try:
            mode = PermissionMode(key)
        except ValueError:
            continue
        result[mode] = str(text)
    return result


@dataclass(slots=True)
class AssemblyResult:
    """Bundle returned by :meth:`TurnAssembler.assemble`.

    Carries the immutable :class:`TurnInput` plus the live objects the
    WebSocket handler still needs after assembly (the ORM conversation /
    user message, the active-version map, the assembled prompt, the
    pre-generation compression result and the context-window / tool-token
    figures, and the cached system prompt for re-compression).
    """

    turn: TurnInput
    conv: Conversation
    user_msg: Message
    av_map: dict[str, int]
    messages: list[dict[str, Any]]
    comp: CompressionResult | None
    context_window: int
    tool_tokens: int
    cached_sys_prompt: str | None


class TurnAssembler:
    """Build a :class:`TurnInput` for one user turn over a shared session."""

    def __init__(
        self,
        ctx: AppContext,
        llm: LLMService,
        *,
        continuum_scope: bool,
        client_ip: str,
    ) -> None:
        self._ctx = ctx
        self._llm = llm
        self._continuum_scope = continuum_scope
        self._client_ip = client_ip

    async def assemble(
        self,
        *,
        session: Any,
        websocket: WebSocket,
        data: dict[str, Any],
        user_content: str,
    ) -> AssemblyResult | None:
        """Assemble the turn input, or ``None`` to skip the turn.

        On a validation failure (bad conversation id, edit target) the
        method sends a WS ``error`` frame and returns ``None`` — the caller
        should ``continue`` to the next message, mirroring the legacy
        inline branches exactly.
        """
        ctx = self._ctx
        llm = self._llm
        continuum_scope = self._continuum_scope
        client_ip = self._client_ip

        conv_id_raw: str | None = data.get("conversation_id")
        attachment_ids: list[str] = data.get("attachments", [])
        edit_message_id: str | None = data.get("edit_message_id")

        # --- resolve or create conversation -----------------------
        if conv_id_raw:
            try:
                conv_id = uuid.UUID(conv_id_raw)
            except ValueError:
                await websocket.send_json(
                    {"type": "error", "content": "Invalid conversation_id"}
                )
                return None
            conv = await session.get(Conversation, conv_id)
            if conv is None:
                conv = Conversation(id=conv_id)
                session.add(conv)
                await session.flush()
        else:
            conv = Conversation()
            session.add(conv)
            await session.flush()
            conv_id = conv.id

        # --- save user message ------------------------------------
        if edit_message_id:
            # --- handle edit-message flow -------------------------
            try:
                original_msg_id = uuid.UUID(edit_message_id)
            except ValueError:
                await websocket.send_json(
                    {"type": "error", "content": "Invalid edit_message_id"},
                )
                return None
            original_msg = await session.get(Message, original_msg_id)
            if (
                original_msg is None
                or original_msg.conversation_id != conv_id
                or original_msg.role != "user"
            ):
                await websocket.send_json(
                    {"type": "error", "content": "Invalid edit target"},
                )
                return None

            # Assign a version_group_id to the original if it
            # doesn't have one yet, and tag all subsequent messages
            # in the same conversation with the same group+index.
            if original_msg.version_group_id is None:
                vg_id = uuid.uuid4()
                original_msg.version_group_id = vg_id
                original_msg.version_index = 0
                # Tag all messages from the original onward.
                after_stmt = (
                    select(Message)
                    .where(
                        Message.conversation_id == conv_id,
                        sa.or_(
                            Message.created_at > original_msg.created_at,
                            (Message.created_at == original_msg.created_at)
                            & (Message.id > original_msg.id),
                        ),
                        Message.id != original_msg.id,
                        Message.version_group_id.is_(None),  # type: ignore[union-attr]
                    )
                )
                after_results = await session.exec(after_stmt)
                for m in after_results.all():
                    m.version_group_id = vg_id
                    m.version_index = 0
                await session.flush()
            else:
                vg_id = original_msg.version_group_id

            # Determine the next version index.
            max_idx_result = await session.scalar(
                sa.select(sa.func.max(Message.version_index)).where(
                    Message.version_group_id == vg_id,
                )
            )
            new_version_idx = (max_idx_result or 0) + 1

            user_msg = Message(
                conversation_id=conv_id,
                role="user",
                content=user_content,
                version_group_id=vg_id,
                version_index=new_version_idx,
            )
            session.add(user_msg)
            await session.flush()

            # Update active_versions on the conversation.
            av = dict(conv.active_versions or {})
            av[str(vg_id)] = new_version_idx
            conv.active_versions = av
            await session.flush()
        else:
            # Inherit version context from the active branch
            # so new messages belong to the currently viewed branch.
            inherit_vg: uuid.UUID | None = None
            inherit_vi: int = 0
            av = dict(conv.active_versions or {})
            if av:
                conds = [
                    sa.and_(
                        Message.version_group_id == uuid.UUID(vg),
                        Message.version_index == idx,
                    )
                    for vg, idx in av.items()
                ]
                latest = (
                    await session.exec(
                        select(Message)
                        .where(
                            Message.conversation_id == conv_id,
                            sa.or_(*conds),
                        )
                        .order_by(Message.created_at.desc())
                        .limit(1)
                    )
                ).first()
                if latest:
                    inherit_vg = latest.version_group_id
                    inherit_vi = latest.version_index

            user_msg = Message(
                conversation_id=conv_id,
                role="user",
                content=user_content,
                version_group_id=inherit_vg,
                version_index=inherit_vi,
            )
            session.add(user_msg)
            await session.flush()

        # --- link uploaded attachments to the user message --------
        attachment_info: list[dict[str, str]] = []
        for att_id_str in attachment_ids:
            try:
                att_id = uuid.UUID(att_id_str)
            except ValueError:
                logger.warning("Invalid attachment id: {}", att_id_str)
                continue
            att = await session.get(Attachment, att_id)
            if att is None:
                logger.warning("Attachment {} not found", att_id_str)
                continue
            att.message_id = user_msg.id
            attachment_info.append(
                {
                    "file_path": str(PROJECT_ROOT / att.file_path),
                    "content_type": att.content_type,
                }
            )
        if attachment_info:
            await session.flush()

        # Commit conversation + user message so they are visible to
        # other sessions (REST endpoints) immediately.  The session
        # uses expire_on_commit=False so `conv` stays usable.
        await session.commit()
        if ctx.conversation_file_manager:
            await _sync_conversation_to_file(
                session, conv_id, ctx.conversation_file_manager,
            )

        # --- fetch history for context ----------------------------
        stmt = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at, Message.id)
        )
        results = await session.exec(stmt)
        all_messages = results.all()

        # Build active_versions map for filtering.
        av_map: dict[str, int] = dict(conv.active_versions or {})
        raw_history: list[dict[str, Any]] = [
            {
                "role": m.role,
                "content": m.content,
                "tool_calls": m.tool_calls,
                "tool_call_id": m.tool_call_id,
                "version_group_id": str(m.version_group_id)
                if m.version_group_id
                else None,
                "version_index": m.version_index,
                "context_excluded": getattr(m, "context_excluded", False),
                "is_context_summary": getattr(m, "is_context_summary", False),
                "_db_pos": i,
            }
            for i, m in enumerate(all_messages)
        ]
        history = _filter_history_for_llm(
            raw_history, av_map,
        )

        # --- RAG readiness gate (functionality-fixes #3) ----------
        # When the vector/embedding stack isn't 100% healthy the lifespan
        # gate disables memory-search + tool-RAG. ``rr is None`` (gate not
        # yet computed) keeps memory enabled but forces full-tools for
        # tool-RAG (safe default).
        rr = getattr(ctx, "rag_readiness", None)
        memory_ok = rr is None or rr.memory_enabled
        tool_rag_ok = rr is not None and rr.tool_rag_enabled

        # --- resolve the conversation's permission tier -----------
        # The tier shapes BOTH the offered toolset (below) and the system-prompt
        # steering (further down), so the user's choice actually changes the
        # agent's behaviour — not only the per-call gate. Resolved defensively:
        # a missing/odd service degrades to the default tier rather than raising.
        mode: PermissionMode | None = None
        policy: ModePolicy | None = None
        mode_service = getattr(ctx, "permission_mode_service", None)
        if mode_service is not None:
            mode = PermissionMode.coerce(
                mode_service.get_mode(conv_id), PermissionMode.STRICT,
            )
            # Resolve the tier policy with the user's per-tier guidance
            # overrides (config keyed by tier strings). Skipped under the
            # Continuum-scoped agent, which owns its own persona/toolset and
            # never uses this policy.
            if continuum_scope:
                policy = policy_for(mode)
            else:
                policy = policy_for(
                    mode,
                    custom_guidance=_coerce_tier_guidance(
                        ctx.config.agent.prompts.tier_guidance,
                    ),
                )

        # --- fetch available tools for LLM ------------------------
        tools: list[dict[str, Any]] | None = None
        if ctx.tool_registry and ctx.config.llm.tools_enabled:
            if continuum_scope:
                # Continuum-scoped agent: always inject the full
                # Continuum toolset (bypass tool RAG) so the agent
                # reliably knows how to act on Continuum.
                tools = await ctx.tool_registry.get_tools_for_plugins(
                    set(ctx.config.continuum.agent_tool_plugins),
                )
            elif (
                ctx.config.llm.tool_rag_enabled
                and tool_rag_ok
                and ctx.qdrant_service is not None
            ):
                tool_query = _build_tool_rag_query(
                    user_content, history,
                )
                tools = await ctx.tool_registry.get_relevant_tools(
                    tool_query,
                    ctx.config.llm.tool_rag_top_k,
                )
            else:
                tools = await ctx.tool_registry.get_available_tools()
                if tools and ctx.config.llm.disabled_tools:
                    # Apply the user's per-chat tool selection
                    # (opt-out). Skipped under tool RAG / continuum
                    # scope, which pick their own toolset above.
                    tools = ctx.tool_registry.exclude_disabled(
                        tools,
                        set(ctx.config.llm.disabled_tools),
                    )
                if tools and ctx.config.llm.max_tools > 0:
                    tools = ctx.tool_registry.limit_tools(
                        tools,
                        max_tools=ctx.config.llm.max_tools,
                        priority_plugins=ctx.config.llm.priority_plugins,
                    )

            # Align the offered toolset with the active permission tier: in the
            # read-only (plan) tier, withhold write/exec tools the gate would
            # block anyway and lead with the planning tools — guaranteeing they
            # are present even if tool RAG didn't surface them. Skipped for the
            # Continuum-scoped agent, which owns its own fixed toolset.
            if tools and policy is not None and not continuum_scope:
                if policy.priority_plugins:
                    have = {t["function"]["name"] for t in tools}
                    extra = await ctx.tool_registry.get_tools_for_plugins(
                        set(policy.priority_plugins),
                    )
                    tools.extend(
                        e for e in extra if e["function"]["name"] not in have
                    )
                tools = ctx.tool_registry.apply_mode_policy(
                    tools,
                    drop_capabilities=policy.blocked_capabilities,
                    always_allow_tools=policy.always_allow_tools,
                    priority_plugins=policy.priority_plugins,
                )

            if not tools:
                tools = None  # empty list confuses some LLMs

        # --- pre-read attachment bytes async (avoid blocking I/O) --
        if attachment_info:
            for att in attachment_info:
                fp = Path(att["file_path"])
                att["_bytes"] = await asyncio.to_thread(fp.read_bytes)

        # --- retrieve relevant memories (Phase 9) -----------------
        memory_context: str | None = None
        if (
            ctx.memory_service
            and ctx.config.memory.inject_in_context
            and memory_ok
        ):
            try:
                relevant = await ctx.memory_service.search(
                    query=user_content,
                    k=ctx.config.memory.top_k,
                    filter={"scope": "long_term"},
                )
                if relevant:
                    memory_context = _format_memory_context(
                        relevant,
                        ctx.config.memory.context_max_chars,
                    )
            except Exception as exc:
                logger.warning(
                    "Memory retrieval failed: {}", exc,
                )

        # --- inject active MCP server list (Phase 11) -------------
        mcp_ctx = _build_mcp_context(ctx)
        if mcp_ctx:
            memory_context = (
                f"{memory_context}\n\n{mcp_ctx}"
                if memory_context
                else mcp_ctx
            )

        # --- inject whiteboards for current conversation ----------
        wb_ctx = await _build_whiteboard_context(ctx, str(conv_id))
        if wb_ctx:
            memory_context = (
                f"{memory_context}\n\n{wb_ctx}"
                if memory_context
                else wb_ctx
            )

        # --- inject the living plan document so the model continues it ---
        # The free-form markdown strategy doc (distinct from the task
        # checklist below). Placed after the permission block (prepended last,
        # so it leads) and before the task steps. Skipped for the
        # Continuum-scoped agent, which owns its own persona/context.
        if ctx.plan_document_service is not None and not continuum_scope:
            plan_doc = await ctx.plan_document_service.get_document(conv_id)
            if plan_doc:
                plan_doc_ctx = render_plan_document(plan_doc)
                if plan_doc_ctx:
                    memory_context = (
                        f"{memory_context}\n\n{plan_doc_ctx}"
                        if memory_context
                        else plan_doc_ctx
                    )

        # --- inject persisted plan so the model continues it (Fase 5) ---
        if ctx.plan_service is not None:
            plan_steps = await ctx.plan_service.get_plan(conv_id)
            if plan_steps:
                plan_ctx = render_task_steps(plan_steps)
                if plan_ctx:
                    memory_context = (
                        f"{memory_context}\n\n{plan_ctx}"
                        if memory_context
                        else plan_ctx
                    )

        # --- inject workspace scope + permission-tier steering ----
        # Prepended so it LEADS the dynamic context: the model must know which
        # folders it may touch (else it defaults to the OS home from the env
        # block and every write lands out of scope) and what its tier permits.
        # Skipped for the Continuum-scoped agent (its own persona/toolset).
        if not continuum_scope:
            perm_ctx = _build_permission_context(ctx, str(conv_id), mode, policy)
            if perm_ctx:
                memory_context = (
                    f"{perm_ctx}\n\n{memory_context}"
                    if memory_context
                    else perm_ctx
                )

        # --- call LLM (streaming) ---------------------------------
        # Build system prompt once for the entire request — reused
        # in build_messages, build_continuation_messages, and the
        # native API path.
        if continuum_scope:
            cached_sys_prompt = llm.get_scoped_system_prompt(
                ctx.config.continuum.agent_prompt_file,
                memory_context=memory_context,
            )
        else:
            cached_sys_prompt = llm.get_system_prompt(
                memory_context=memory_context,
                persona=ctx.config.agent.prompts.persona,
            )

        messages = llm.build_messages(
            user_content,
            history=history[:-1],  # history already has user msg
            attachments=attachment_info or None,
            system_prompt=cached_sys_prompt,
        )

        # -- Context management ---------------------------------------
        comp: CompressionResult | None = None
        context_window = 0
        _tool_tokens = 0

        if ctx.context_manager is not None:
            context_window = llm.get_cached_context_window(ctx.lmstudio_manager)

        if context_window > 0 and ctx.context_manager is not None:
            # Compute tool tokens for compression regardless
            # of estimation path — compress() needs them.
            if tools:
                _tool_tokens = (
                    ctx.context_manager.estimate_tokens(
                        json.dumps(tools, ensure_ascii=False),
                    )
                )

            # Prefer anchor+delta over full estimation.
            snap = getattr(conv, "context_snapshot", None)
            if (
                snap
                and isinstance(snap, dict)
                and snap.get("prompt_tokens", 0) > 0
            ):
                # Real tokens from last exchange — already
                # include system prompt + tools + all messages.
                anchor = (
                    snap["prompt_tokens"]
                    + snap.get("completion_tokens", 0)
                )
                # Estimate only the new user message.
                delta = ctx.context_manager.estimate_tokens(
                    user_content or "",
                )
                used = anchor + delta
                available = max(0, context_window - used)
                pct = (
                    round(used / context_window, 4)
                    if context_window > 0 else 0.0
                )
                usage_est = ContextUsage(
                    used_tokens=used,
                    available_tokens=available,
                    context_window=context_window,
                    percentage=pct,
                    was_compressed=False,
                    messages_summarized=0,
                    is_estimated=False,
                )
            else:
                # Fallback: full char/4 estimation.
                usage_est = (
                    ctx.context_manager.get_usage_estimated(
                        messages, context_window,
                    )
                )
                # Add tool tokens (not in the messages array).
                if _tool_tokens > 0:
                    usage_est.used_tokens += _tool_tokens
                    usage_est.available_tokens = max(
                        0,
                        context_window - usage_est.used_tokens,
                    )
                    usage_est.percentage = (
                        round(
                            usage_est.used_tokens
                            / context_window,
                            4,
                        )
                        if context_window > 0 else 0.0
                    )

            # Pre-generation compression check.
            if (
                ctx.config.llm.context_compression_enabled
                and ctx.context_manager.should_compress(usage_est)
            ):
                await websocket.send_json(
                    {"type": "context_compression_start"},
                )
                try:
                    comp = await ctx.context_manager.compress(
                        messages,
                        llm,
                        context_window,
                        ctx.config.llm.context_compression_reserve,
                        tool_tokens=_tool_tokens
                        if tools else 0,
                    )
                    messages = comp.messages

                    # Archive messages in DB.
                    await _archive_messages_in_db(
                        session, all_messages, raw_history,
                        comp.split_index,
                        active_versions=av_map,
                    )
                    # Save summary message.
                    summary_content = (
                        f"[Context summary of "
                        f"{comp.split_index} earlier "
                        f"messages]:\n{comp.summary_text}"
                    )
                    summary_msg = Message(
                        conversation_id=conv_id,
                        role="assistant",
                        content=summary_content,
                        is_context_summary=True,
                    )
                    session.add(summary_msg)
                    await session.flush()

                    await websocket.send_json({
                        "type": "context_compression_done",
                        "messages_summarized": (
                            comp.usage.messages_summarized
                        ),
                        "summary_message_id": str(summary_msg.id),
                    })
                    # Re-estimate after compression.
                    usage_est = comp.usage
                except Exception as exc:
                    logger.warning(
                        "Context compression failed: {}", exc,
                    )
                    await websocket.send_json(
                        {"type": "context_compression_failed"},
                    )
                    comp = None

            # Send initial context_info.
            await websocket.send_json({
                "type": "context_info",
                "used": usage_est.used_tokens,
                "available": usage_est.available_tokens,
                "context_window": context_window,
                "percentage": usage_est.percentage,
                "was_compressed": comp is not None,
                "messages_summarized": (
                    comp.usage.messages_summarized if comp else 0
                ),
                "is_estimated": usage_est.is_estimated,
                "breakdown": _compute_context_breakdown(
                    messages, _tool_tokens, ctx.context_manager,
                ),
            })

        # Resolve max_output_tokens once when the global cap is
        # unset — mirrors the legacy ``_stream_and_collect`` logic.
        resolved_max: int | None = None
        if (
            ctx.config.llm.max_tokens <= 0
            and context_window > 0
            and ctx.context_manager is not None
        ):
            resolved_max = max(
                1024,
                usage_est.available_tokens
                - ctx.config.llm.context_compression_reserve,
            )

        # Build the immutable turn input.  When pre-gen
        # compression ran, the executor must use the compressed
        # history (so the tool loop does not re-compress) and the
        # OAI-compat path (forced by user_content=None inside
        # the executor when ``was_compressed=True``).
        turn = TurnInput(
            conv_id=conv_id,
            user_msg_id=user_msg.id,
            user_content=user_content,
            history=history,
            messages=messages,
            tools=tools,
            memory_context=memory_context,
            cached_sys_prompt=cached_sys_prompt,
            attachment_info=attachment_info or None,
            context_window=context_window,
            version_group_id=user_msg.version_group_id,
            version_index=user_msg.version_index,
            client_ip=client_ip,
            resolved_max_tokens=resolved_max,
            was_compressed=comp is not None,
            compressed_history=(
                [
                    m for m in comp.messages
                    if m.get("role") != "system"
                ]
                if comp is not None else None
            ),
            tool_tokens=_tool_tokens if context_window > 0 else 0,
        )

        return AssemblyResult(
            turn=turn,
            conv=conv,
            user_msg=user_msg,
            av_map=av_map,
            messages=messages,
            comp=comp,
            context_window=context_window,
            tool_tokens=_tool_tokens if context_window > 0 else 0,
            cached_sys_prompt=cached_sys_prompt,
        )
