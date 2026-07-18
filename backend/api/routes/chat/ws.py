"""AL\\CE — Chat WebSocket streaming endpoint.

Hosts the ``/ws/chat`` endpoint.  Connection lifecycle, the receive loop,
control-frame handling and message validation live here; the heavy turn
assembly (history, tools, context, compression) is delegated to
:class:`._assembly.TurnAssembler`, and the post-turn persistence to
:mod:`._persist`.

The turn itself runs on the greenfield :class:`AgentEngine`
(``services/agent``), wired by ``run_agent_turn``: the :class:`WsTransport`
owns the socket (single reader) and serves interactions, the engine emits
its own wire frames, and the api-layer :class:`TransportEventSink` carries
only the post-turn ``context.usage`` / ``context.compaction`` frames — over
the SAME transport, so the chat channel has a single writer (carry #3).
"""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from backend.api.ws_schema.guard import chat_frame_validator
from backend.services.agent.adapters.ws import WsTransport
from backend.services.agent.models import TurnOutcome
from backend.services.agent.runner import run_agent_turn
from backend.services.llm_service import LLMService

from ._assembly import TurnAssembler
from ._persist import _persist_final_turn
from ._shared import (
    _ctx,
    _error_frame,
    _get_ws_lock,
    _ws_connections,
    conversation_active,
    router,
)
from ._sink import TransportEventSink

#: Hard cap on a single inbound user message (characters).
_MAX_USER_MESSAGE_LENGTH = 50_000


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """Accept a WebSocket, stream LLM responses token-by-token.

    Incoming JSON::

        {"content": "user message", "conversation_id": "optional-uuid"}

    Outgoing JSON (one per frame, canonical v2 vocabulary)::

        {"type": "turn.delta", "text": "..."} | {"type": "turn.finished",
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
            _error_frame(
                "server_not_ready", "Server not ready — services not initialized",
            )
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

    # Single inbound read-pump: ``WsTransport`` OWNS ``receive`` for the whole
    # connection and demultiplexes interaction responses / cancel / user
    # messages, so there is never more than one concurrent reader on the
    # socket (invariant §6.6). Malformed JSON is dropped in the pump.
    transport = WsTransport(websocket)
    await transport.start()

    try:
        while True:
            # The pump delivers only non-interaction (user/idle) frames here,
            # already JSON-parsed; ``None`` means the socket disconnected.
            data = await transport.next_user_message()
            if data is None:
                break

            user_content: str = data.get("content", "").strip()
            if not user_content:
                await websocket.send_json(
                    _error_frame("empty_message", "Empty message")
                )
                continue

            if len(user_content) > _MAX_USER_MESSAGE_LENGTH:
                await websocket.send_json(
                    _error_frame("message_too_long", "Message too long")
                )
                continue

            # Re-read the LLM service (and rebuild the cheap assembler) for
            # every turn: a provider/API-key change via PUT /api/config
            # replaces ``ctx.llm_service`` and CLOSES the old instance, so a
            # snapshot taken at connection time would break open sockets.
            llm: LLMService = ctx.llm_service  # type: ignore[assignment]
            if llm is None:
                await websocket.send_json(
                    _error_frame("llm_unavailable", "LLM service unavailable")
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

                conv = assembly.conv
                conv_id = conv.id
                user_msg = assembly.user_msg

                cancel_event = transport.begin_turn()

                # The persist path emits its post-turn ``context.*`` frames
                # through this sink, which rides the SAME transport as the
                # engine's wire stream (single writer, carry #3). No second
                # reader either — the transport owns the socket.
                sink = TransportEventSink(
                    transport, frame_validator=chat_frame_validator,
                )

                # Fase 1: greenfield engine is the only path. ``run_agent_turn``
                # mounts the ports (WsEventPort/WsInteractionPort over the
                # transport) and drives the turn; it never raises — every
                # failure is mapped into the ``TurnOutcome``.
                with conversation_active(str(conv_id)):
                    result: TurnOutcome = await run_agent_turn(
                        ctx,
                        request=assembly.request,
                        session=session,
                        transport=transport,
                        cancel=cancel_event,
                    )

                if result.finish_reason == "disconnected":
                    # Il recovery message parziale è già stato persistito dal
                    # motore (matrice _finish, carry #3): qui si esce e basta.
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
                    was_compressed=assembly.comp is not None,
                    pre_comp=assembly.comp,
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
        await transport.aclose()
        async with ws_lock:
            _ws_connections[client_ip] = max(
                0, _ws_connections[client_ip] - 1,
            )
            if _ws_connections[client_ip] <= 0:
                _ws_connections.pop(client_ip, None)
