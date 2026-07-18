"""AL\\CE — Headless (autonomous) turn runner (Fase 8, spec §8).

An autonomous turn IS a normal turn: same assembly, engine, permission
mode and scope of the conversation it belongs to. The only differences are
the missing surfaces: chat-stream events go to a :class:`NullEventSink`
(observability rides the background-task events) and interactive requests
are auto-declined by the engine's :class:`AutoDeclineInteractionPort`.

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
from backend.api.routes.chat._sink import NullEventSink, WSEventSink
from backend.api.ws_schema.wire import to_v2_frames
from backend.services.agent.models import TurnSource
from backend.services.agent.runner import run_agent_turn

if TYPE_CHECKING:
    from backend.core.context import AppContext
    from backend.services.agent.models import TurnOutcome


def _strip_ui_tools(
    ctx: AppContext, tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Drop UI-dependent tools: a headless turn has no UI to serve them.

    Covers both client-executed tools and user-interaction tools
    (``ask_user``): the engine would auto-decline them to clean errors
    anyway, but not offering them avoids wasted loop iterations.
    """
    if not tools:
        return tools
    registry = ctx.tool_registry
    if registry is None:
        return tools
    kept: list[dict[str, Any]] = []
    for entry in tools:
        fn = entry.get("function")
        name = fn.get("name", "") if isinstance(fn, dict) else ""
        tool_def = registry.get_tool_definition(name)
        if tool_def is not None and (
            tool_def.client_execution or tool_def.user_interaction
        ):
            continue
        kept.append(entry)
    return kept


async def run_headless_turn(
    ctx: AppContext,
    *,
    conversation_id: str | None,
    prompt: str,
    origin: str = "system",
    sink: WSEventSink | None = None,
) -> TurnOutcome | None:
    """Run one autonomous turn through the normal pipeline and persist it.

    Args:
        ctx: The application context.
        conversation_id: Target conversation (``None`` creates a new one).
        prompt: The user-role content that starts the turn.
        origin: Provenance recorded in logs (``system`` for triggers).
        sink: Event sink opzionale per osservare i frame del turno
            (eval harness). Default: :class:`NullEventSink` (drop).

    Returns:
        The :class:`TurnOutcome`, or ``None`` when the turn could not start
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

        # Headless overrides the request: strip UI-dependent tools, force the
        # HEADLESS source, and clear any voice tool-call cap.
        request = replace(
            assembly.request,
            tools=_strip_ui_tools(ctx, assembly.request.tools) or [],
            source=TurnSource.HEADLESS,
            max_tool_calls=None,
        )
        turn_sink: WSEventSink = sink if sink is not None else NullEventSink()
        cancel_event = asyncio.Event()

        # Fase 1: greenfield engine, no UI. Events flow to ``turn_sink``
        # (SinkEventPort); interactions are auto-declined
        # (AutoDeclineInteractionPort). ``transport=None`` selects the
        # headless port configuration in ``run_agent_turn``.
        with conversation_active(str(assembly.conv.id)):
            result = await run_agent_turn(
                ctx,
                request=request,
                session=session,
                transport=None,
                translator=to_v2_frames,
                sink_fallback=turn_sink,
                cancel=cancel_event,
            )

        await _persist_final_turn(
            session=session,
            conv=assembly.conv,
            conv_id=assembly.conv.id,
            user_msg=assembly.user_msg,
            result=result,
            sink=turn_sink,
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
