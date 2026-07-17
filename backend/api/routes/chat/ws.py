"""AL\\CE — Chat WebSocket streaming endpoint.

Hosts the ``/ws/chat`` endpoint.  Connection lifecycle, the receive loop,
control-frame handling and message validation live here; the heavy turn
assembly (history, tools, context, compression) is delegated to
:class:`._assembly.TurnAssembler`, and the post-turn persistence to
:mod:`._persist`.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from backend.api.ws_schema.guard import chat_frame_validator
from backend.db.models import Message
from backend.services.agent.adapters.ws import WsTransport
from backend.services.llm_service import LLMService
from backend.services.turn import (
    TurnResult,
    WebSocketEventSink,
    WebSocketInteractionChannel,
    create_turn_executor,
)
from backend.services.turn.channel import MALFORMED_FRAME_KEY

from ._assembly import TurnAssembler
from ._persist import _persist_final_turn
from ._shared import (
    _ctx,
    _get_ws_lock,
    _utcnow,
    _ws_connections,
    conversation_active,
    router,
)

#: Hard cap on a single inbound user message (characters).
_MAX_USER_MESSAGE_LENGTH = 50_000


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """Accept a WebSocket, stream LLM responses token-by-token.

    Incoming JSON::

        {"content": "user message", "conversation_id": "optional-uuid"}

    Outgoing JSON (one per frame)::

        {"type": "token", "content": "..."} | {"type": "done",
         "conversation_id": "...", "message_id": "..."}
    """
    ctx = _ctx(websocket)
    max_ws = ctx.config.server.ws_max_connections_per_ip

    # Track per-IP WebSocket connections.
    client_ip = (
        websocket.client.host if websocket.client else "unknown"
    )
    ws_lock = _get_ws_lock()
    async with ws_lock:
        if _ws_connections.get(client_ip, 0) >= max_ws:
            await websocket.accept()
            await websocket.close(
                code=1008, reason="Too many connections",
            )
            logger.warning(
                "WS rejected for {} — {} active connections",
                client_ip, _ws_connections[client_ip],
            )
            return
        await websocket.accept()
        _ws_connections[client_ip] += 1

    session_factory = ctx.db

    if ctx.llm_service is None or session_factory is None:
        await websocket.send_json(
            {"type": "error", "content": "Server not ready \u2014 services not initialized"}
        )
        await websocket.close(code=1011)
        async with ws_lock:
            _ws_connections[client_ip] = max(0, _ws_connections[client_ip] - 1)
            if _ws_connections[client_ip] <= 0:
                _ws_connections.pop(client_ip, None)
        return

    # Agent scope (constant for the connection lifetime). A chat opened
    # *from* Continuum passes ``?scope=continuum`` so Alice uses a clean,
    # Continuum-only persona and always-injected Continuum tools.
    agent_scope = (websocket.query_params.get("scope") or "").strip().lower()
    continuum_scope = agent_scope == "continuum"

    # Turn engine selector (flag ``agent.engine``, TEMPORANEO Fase 1). Constant
    # per connection: read once here so the read-pump ownership is decided a
    # single time (single-reader invariant — NEVER two readers on the socket).
    engine_v2 = ctx.config.agent.engine == "v2"

    # Single inbound read-pump: it owns ``receive`` for the whole connection
    # and demultiplexes interaction responses / cancel / user messages, so
    # there is never more than one concurrent reader on the socket. In v2 the
    # ``WsTransport`` IS that single reader (it replaces the legacy channel);
    # ``reader`` exposes the shared surface both use (``next_user_message`` /
    # ``begin_turn``).
    channel: WebSocketInteractionChannel | None = None
    transport: WsTransport | None = None
    if engine_v2:
        transport = WsTransport(websocket)
        await transport.start()
        reader: Any = transport
    else:
        channel = WebSocketInteractionChannel(
            websocket, frame_validator=chat_frame_validator,
        )
        channel.start()
        reader = channel

    try:
        while True:
            # The pump delivers only non-interaction (user/idle) frames here,
            # already JSON-parsed; ``None`` means the socket disconnected.
            data = await reader.next_user_message()
            if data is None:
                break
            if data.get(MALFORMED_FRAME_KEY):
                await websocket.send_json(
                    {"type": "error", "content": "Invalid JSON"}
                )
                continue

            user_content: str = data.get("content", "").strip()
            if not user_content:
                await websocket.send_json(
                    {"type": "error", "content": "Empty message"}
                )
                continue

            if len(user_content) > _MAX_USER_MESSAGE_LENGTH:
                await websocket.send_json(
                    {"type": "error", "content": "Message too long"}
                )
                continue

            # Re-read the LLM service (and rebuild the cheap assembler) for
            # every turn: a provider/API-key change via PUT /api/config
            # replaces ``ctx.llm_service`` and CLOSES the old instance, so a
            # snapshot taken at connection time would break open sockets.
            llm: LLMService = ctx.llm_service  # type: ignore[assignment]
            if llm is None:
                await websocket.send_json(
                    {"type": "error", "content": "LLM service unavailable"}
                )
                continue
            assembler = TurnAssembler(
                ctx, llm, continuum_scope=continuum_scope, client_ip=client_ip,
            )

            async with session_factory() as session:
                # Assemble the turn (conversation, history, tools, context,
                # pre-gen compression).  ``None`` signals a validation
                # failure already reported to the client → skip this turn.
                assembly = await assembler.assemble(
                    session=session,
                    websocket=websocket,
                    data=data,
                    user_content=user_content,
                )
                if assembly is None:
                    continue

                turn = assembly.turn
                conv = assembly.conv
                conv_id = turn.conv_id
                user_msg = assembly.user_msg
                comp = assembly.comp

                full_content = ""
                thinking_content = ""
                tool_calls_collected: list[dict[str, Any]] = []
                finish_reason = "stop"
                cancel_event = reader.begin_turn()

                sink = WebSocketEventSink(websocket, frame_validator=chat_frame_validator)

                result: TurnResult
                if engine_v2:
                    # Fase 1 Task 16: greenfield engine. ``WsTransport`` (the
                    # single reader) also serves interactions; the engine emits
                    # its own wire frames via ``WsEventPort``. The ``sink`` is
                    # reused only by the shared persist path below (``done`` +
                    # context frames). No second reader — see connection setup.
                    from backend.api.routes.chat._engine_bridge import (
                        build_turn_request,
                        outcome_to_turn_result,
                    )
                    from backend.services.agent.models import TurnSource
                    from backend.services.agent.runner import run_agent_turn

                    source = (
                        TurnSource.VOICE
                        if (data.get("source") or "").strip().lower() == "voice"
                        else TurnSource.CHAT
                    )
                    voice_cap = ctx.config.agent.voice.max_tools
                    max_tool_calls = (
                        voice_cap
                        if source is TurnSource.VOICE and voice_cap > 0
                        else None
                    )
                    request = build_turn_request(
                        ctx, turn, source=source, max_tool_calls=max_tool_calls,
                    )
                    with conversation_active(str(conv_id)):
                        outcome = await run_agent_turn(
                            ctx,
                            request=request,
                            session=session,
                            transport=transport,
                            cancel=cancel_event,
                        )
                    result = outcome_to_turn_result(outcome)
                else:
                    executor = create_turn_executor(ctx, llm)
                    executor_task = asyncio.create_task(
                        executor.execute(
                            turn, sink, cancel_event, session, channel,
                        ),
                    )

                    # Idle-guard (Fase 6b): mark the conversation busy for the
                    # executor's lifetime so scope mutations are rejected (409)
                    # while a turn is running.  Persist below runs idle — it
                    # does not touch the workspace scope.
                    with conversation_active(str(conv_id)):
                        try:
                            result = await executor_task
                        except asyncio.CancelledError:
                            cancel_event.set()
                            logger.debug("Executor task cancelled")
                            result = TurnResult(
                                content=full_content,
                                thinking=thinking_content,
                                input_tokens=0,
                                output_tokens=0,
                                finish_reason="cancelled",
                                final_assistant_message_id=None,
                                had_tool_calls=bool(tool_calls_collected),
                            )

                # Mirror legacy behaviour: feed locals from the result so
                # disconnect-recovery has access to partial content.
                full_content = result.content
                thinking_content = result.thinking
                finish_reason = result.finish_reason

                # FIX v2-4: disconnect recovery — save partial content
                # then propagate so the outer WS loop exits cleanly.
                if finish_reason == "disconnected":
                    if full_content:
                        recovery_msg = Message(
                            conversation_id=conv_id,
                            role="assistant",
                            content=full_content,
                            thinking_content=thinking_content or None,
                            version_group_id=user_msg.version_group_id,
                            version_index=user_msg.version_index,
                        )
                        session.add(recovery_msg)
                        conv.updated_at = _utcnow()
                        with contextlib.suppress(Exception):
                            await session.commit()
                    raise WebSocketDisconnect()

                await _persist_final_turn(
                    session=session,
                    conv=conv,
                    conv_id=conv_id,
                    user_msg=user_msg,
                    result=result,
                    sink=sink,
                    ctx=ctx,
                    llm=llm,
                    user_content=user_content,
                    was_compressed=comp is not None,
                    pre_comp=comp,
                    context_window=assembly.context_window,
                    tool_tokens=assembly.tool_tokens,
                    messages=assembly.messages,
                    av_map=assembly.av_map,
                    cached_sys_prompt=assembly.cached_sys_prompt,
                )

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception:
        logger.exception("WebSocket unexpected error")
    finally:
        if transport is not None:
            await transport.aclose()
        if channel is not None:
            await channel.aclose()
        async with ws_lock:
            _ws_connections[client_ip] = max(
                0, _ws_connections[client_ip] - 1,
            )
            if _ws_connections[client_ip] <= 0:
                _ws_connections.pop(client_ip, None)
