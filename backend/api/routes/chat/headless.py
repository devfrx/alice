"""AL\\CE — Headless (autonomous) turn runner (Fase 8, spec §8).

An autonomous turn IS a normal turn: same assembly, executor, permission
mode and scope of the conversation it belongs to. The only differences are
the missing surfaces: chat-stream events go to a :class:`NullEventSink`
(observability rides the background-task events) and interactive requests
are auto-declined by a :class:`HeadlessInteractionChannel`.

Lives in the api layer because it reuses :class:`TurnAssembler` and
``_persist_final_turn``; the TriggerService (services layer) receives it as
an injected ``turn_runner`` from ``stage_jarvis`` (the composition root is
the sanctioned ``backend.core.bootstrap.* -> backend.api.**`` exception).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.api.routes.chat._assembly import TurnAssembler
from backend.api.routes.chat._persist import _persist_final_turn
from backend.api.routes.chat._shared import conversation_active
from backend.services.turn.channel import HeadlessInteractionChannel
from backend.services.turn.factory import create_turn_executor
from backend.services.turn.sink import NullEventSink

if TYPE_CHECKING:
    from backend.core.context import AppContext
    from backend.services.turn.models import TurnResult


def _strip_client_tools(
    ctx: AppContext, tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Drop client-executed tools: a headless turn has no UI to run them."""
    if not tools:
        return tools
    registry = ctx.tool_registry
    if registry is None:
        return tools
    kept: list[dict[str, Any]] = []
    for entry in tools:
        name = entry.get("function", {}).get("name", "")
        tool_def = registry.get_tool_definition(name)
        if tool_def is not None and tool_def.client_execution:
            continue
        kept.append(entry)
    return kept


async def run_headless_turn(
    ctx: AppContext,
    *,
    conversation_id: str | None,
    prompt: str,
    origin: str = "system",
) -> TurnResult | None:
    """Run one autonomous turn through the normal pipeline and persist it.

    Args:
        ctx: The application context.
        conversation_id: Target conversation (``None`` creates a new one).
        prompt: The user-role content that starts the turn.
        origin: Provenance recorded in logs (``system`` for triggers).

    Returns:
        The :class:`TurnResult`, or ``None`` when the turn could not start
        (no DB / no LLM / assembly validation failure).
    """
    llm = ctx.llm_service
    if ctx.db is None or llm is None:
        logger.warning("Headless turn skipped: DB or LLM service unavailable")
        return None

    assembler = TurnAssembler(ctx, llm, continuum_scope=False, client_ip="headless")
    data: dict[str, Any] = {"content": prompt}
    if conversation_id:
        data["conversation_id"] = conversation_id

    async with ctx.db() as session:
        assembly = await assembler.assemble(
            session=session, websocket=None, data=data, user_content=prompt,
        )
        if assembly is None:
            logger.warning("Headless turn: assembly failed (origin={})", origin)
            return None

        turn = replace(
            assembly.turn, tools=_strip_client_tools(ctx, assembly.turn.tools),
        )
        sink = NullEventSink()
        channel = HeadlessInteractionChannel()
        cancel_event = asyncio.Event()

        executor = create_turn_executor(ctx, llm)
        with conversation_active(str(turn.conv_id)):
            result = await executor.execute(turn, sink, cancel_event, session, channel)

        await _persist_final_turn(
            session=session,
            conv=assembly.conv,
            conv_id=turn.conv_id,
            user_msg=assembly.user_msg,
            result=result,
            sink=sink,
            ctx=ctx,
            llm=llm,
            user_content=prompt,
            was_compressed=assembly.comp is not None,
            pre_comp=assembly.comp,
            context_window=assembly.context_window,
            tool_tokens=assembly.tool_tokens,
            messages=assembly.messages,
            av_map=assembly.av_map,
            cached_sys_prompt=assembly.cached_sys_prompt,
        )
        return result
