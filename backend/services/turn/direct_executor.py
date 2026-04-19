"""AL\\CE — Direct turn executor (legacy behaviour, refactored).

:class:`DirectTurnExecutor` is the default :class:`TurnExecutor` strategy.
It preserves the *exact* behaviour of the original closure-based
``ws_chat`` flow:

1. Stream the initial LLM completion via :meth:`LLMService.chat`,
   relaying ``token`` / ``thinking`` / ``tool_call`` / ``error`` / ``done``
   events through a :class:`WSEventSink`.
2. If tool calls were requested, delegate to
   :func:`backend.api.routes._tool_loop.run_tool_loop`
   **without modifying it** (Phase 1 escape hatch — see ``sink._ws``).
3. Honour ``cancel_event`` at every chunk and after the tool loop.
4. Capture LLM exceptions and ``WebSocketDisconnect`` internally so
   ``ws_chat`` only needs to inspect ``finish_reason`` to decide what to
   persist (no exception-based control flow).

The executor never persists the *final* assistant message — that lives
in ``ws_chat::_persist_final_turn`` so post-stream compression and
context-info bookkeeping share a single code path with the cancelled /
disconnected fast paths.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, Callable, Coroutine

from fastapi import WebSocketDisconnect
from loguru import logger

from backend.core.context import AppContext
from backend.services.llm_service import LLMService
from backend.services.turn.models import TurnInput, TurnResult
from backend.services.turn.sink import WSEventSink

# Type alias for the "sync conversation to file" callback used by
# run_tool_loop.  Provided by the caller to avoid a circular import
# between ``turn`` and ``api.routes.chat``.
SyncFn = Callable[..., Coroutine[Any, Any, None]]


class DirectTurnExecutor:
    """Executes a turn using the legacy stream + tool-loop pipeline.

    Args:
        ctx: Application context (config, tool registry, services).
        llm: Active :class:`LLMService` instance.
        sync_fn: Optional ``_sync_conversation_to_file`` callback handed
            down to :func:`run_tool_loop`. ``None`` disables the
            per-iteration JSON sync (e.g. in unit tests).
    """

    def __init__(
        self,
        ctx: AppContext,
        llm: LLMService,
        sync_fn: SyncFn | None = None,
    ) -> None:
        self.ctx = ctx
        self.llm = llm
        self._sync_fn = sync_fn

    async def execute(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        session: Any,
    ) -> TurnResult:
        """Run the full turn and return its outcome.

        Args:
            turn: Immutable input bundle.
            sink: Sink used for outbound WS events.
            cancel_event: Event toggled by the caller (or the internal
                cancel reader) to abort the turn early.
            session: Active async DB session (forwarded to the tool loop).

        Returns:
            A :class:`TurnResult` describing the final state. The
            executor swallows :class:`WebSocketDisconnect` and LLM
            errors, surfacing them through ``finish_reason``
            (``"disconnected"`` / ``"error"``).
        """
        # ------------------------------------------------------------------
        # Phase 1 — stream initial LLM response.  Owns its own cancel
        # reader so the WebSocket never has two concurrent readers (v3-1).
        # ------------------------------------------------------------------
        try:
            (
                full_content,
                thinking,
                tool_calls,
                finish_reason,
                in_tok,
                out_tok,
            ) = await self._stream_initial(turn, sink, cancel_event)
        except WebSocketDisconnect:
            # v2-4 / v3-1: disconnect during initial stream.  No content
            # has been collected yet — bubble up as "disconnected" with
            # whatever the executor managed to accumulate (typically "").
            logger.debug("WS disconnected during initial stream")
            return TurnResult(
                content="",
                thinking="",
                input_tokens=0,
                output_tokens=0,
                finish_reason="disconnected",
                final_assistant_message_id=None,
                had_tool_calls=False,
            )

        # v3-2 (also valid post-stream): cancel takes precedence over
        # any other finish reason emitted by the LLM.
        if cancel_event.is_set():
            return TurnResult(
                content=full_content,
                thinking=thinking,
                input_tokens=in_tok,
                output_tokens=out_tok,
                finish_reason="cancelled",
                final_assistant_message_id=None,
                had_tool_calls=False,
            )

        # The streaming layer captured an LLM error (already emitted as
        # WS event by ``_stream_initial``) — short-circuit.
        if finish_reason == "error":
            return TurnResult(
                content=full_content,
                thinking=thinking,
                input_tokens=in_tok,
                output_tokens=out_tok,
                finish_reason="error",
                final_assistant_message_id=None,
                had_tool_calls=False,
            )

        # ------------------------------------------------------------------
        # Phase 2 — tool loop.
        # ------------------------------------------------------------------
        had_tool_calls = False
        if tool_calls:
            had_tool_calls = True
            ws_for_loop = sink._ws
            if ws_for_loop is None:
                # In tests with a RecordingEventSink, the tool loop is
                # not exercised because run_tool_loop expects a real
                # WebSocket.  Surface a deterministic error instead of a
                # cryptic AttributeError.
                logger.error(
                    "DirectTurnExecutor: tool calls requested but sink "
                    "has no underlying WebSocket — refusing to invoke "
                    "run_tool_loop.",
                )
                return TurnResult(
                    content=full_content,
                    thinking=thinking,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    finish_reason="error",
                    final_assistant_message_id=None,
                    had_tool_calls=True,
                )

            # Use the compressed history (when available) so the loop
                # does not re-trigger compression on its first iteration.
            effective_history = (
                turn.compressed_history
                if turn.was_compressed and turn.compressed_history is not None
                else turn.history
            )

            # Lazy import to break the circular dependency between
            # backend.services.turn and backend.api.routes (chat.py
            # imports from this package at module load).
            from backend.api.routes._tool_loop import run_tool_loop

            try:
                (
                    full_content,
                    thinking,
                    in_tok2,
                    out_tok2,
                    loop_finish,
                ) = await run_tool_loop(
                    websocket=ws_for_loop,
                    ctx=self.ctx,
                    session=session,
                    conv_id=turn.conv_id,
                    llm=self.llm,
                    tool_calls_from_llm=tool_calls,
                    full_content=full_content,
                    thinking_content=thinking,
                    max_iterations=self.ctx.config.llm.max_tool_iterations,
                    confirmation_timeout_s=(
                        self.ctx.config.pc_automation.confirmation_timeout_s
                    ),
                    client_ip=turn.client_ip,
                    sync_fn=self._sync_fn,
                    cancel_event=cancel_event,
                    memory_context=turn.memory_context,
                    tools=turn.tools,
                    initial_history=effective_history,
                    system_prompt=turn.cached_sys_prompt,
                    version_group_id=turn.version_group_id,
                    version_index=turn.version_index,
                    context_window=turn.context_window,
                )
                if in_tok2 > 0:
                    in_tok = in_tok2
                    out_tok = out_tok2
                finish_reason = loop_finish
            except WebSocketDisconnect:
                # v2-4: keep partial content for recovery in ws_chat.
                logger.debug("WS disconnected during tool loop")
                return TurnResult(
                    content=full_content,
                    thinking=thinking,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    finish_reason="disconnected",
                    final_assistant_message_id=None,
                    had_tool_calls=True,
                )
            except Exception:
                # Preserve legacy behaviour: a generic tool-loop failure
                # surfaces as a sink error event + finish_reason="error".
                logger.exception("Tool loop error")
                with contextlib.suppress(Exception):
                    await sink.send({
                        "type": "error",
                        "content": "Tool execution error",
                    })
                return TurnResult(
                    content=full_content,
                    thinking=thinking,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    finish_reason="error",
                    final_assistant_message_id=None,
                    had_tool_calls=True,
                )

            # v3-2: cancel during the tool loop returns the loop's last
            # finish_reason (typically "stop") — override it to
            # "cancelled" so the persistence layer takes the cancel path.
            if cancel_event.is_set():
                return TurnResult(
                    content=full_content,
                    thinking=thinking,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    finish_reason="cancelled",
                    final_assistant_message_id=None,
                    had_tool_calls=True,
                )

        return TurnResult(
            content=full_content,
            thinking=thinking,
            input_tokens=in_tok,
            output_tokens=out_tok,
            finish_reason=finish_reason,
            final_assistant_message_id=None,
            had_tool_calls=had_tool_calls,
        )

    # ------------------------------------------------------------------
    # Internal: initial streaming pass (legacy ``_stream_and_collect``).
    # ------------------------------------------------------------------

    async def _stream_initial(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
    ) -> tuple[str, str, list[dict[str, Any]], str, int, int]:
        """Stream the first LLM response and relay events to ``sink``.

        Mirrors the behaviour of the legacy ``_stream_and_collect``
        closure in ``ws_chat`` but owns its own WebSocket cancel reader
        (v3-1) so there is never an overlap with the per-request
        readers spawned by :func:`run_tool_loop`.

        Returns:
            ``(content, thinking, tool_calls, finish_reason,
            input_tokens, output_tokens)``.
        """
        full_content = ""
        thinking = ""
        tool_calls_collected: list[dict[str, Any]] = []
        finish_reason = "stop"
        in_tok = 0
        out_tok = 0

        # When pre-gen compression already happened, force the OAI-compat
        # path by suppressing user_content (the compressed messages list
        # carries everything).
        effective_user_content = (
            None if turn.was_compressed else turn.user_content
        )

        # v3-1: cancel reader scoped to the streaming phase only.
        reader_task = self._spawn_cancel_reader(sink, cancel_event)

        try:
            async for event in self.llm.chat(
                turn.messages,
                tools=turn.tools,
                cancel_event=cancel_event,
                user_content=effective_user_content,
                conversation_id=str(turn.conv_id),
                attachments=turn.attachment_info or None,
                system_prompt=turn.cached_sys_prompt,
                max_output_tokens=turn.resolved_max_tokens,
            ):
                etype = event.get("type")
                if etype == "token":
                    full_content += event.get("content", "")
                    await sink.send(event)
                elif etype == "thinking":
                    thinking += event.get("content", "")
                    await sink.send(event)
                elif etype == "tool_call":
                    tool_calls_collected.append(event)
                    await sink.send(event)
                elif etype == "usage":
                    in_tok = int(event.get("input_tokens", 0) or 0)
                    out_tok = int(event.get("output_tokens", 0) or 0)
                elif etype == "error":
                    # v3-5: capture LLM error here, emit to sink, and
                    # stop without raising.  ws_chat reads finish_reason.
                    logger.error(
                        "LLM error during initial stream: {}",
                        event.get("content", "unknown"),
                    )
                    await sink.send(event)
                    finish_reason = "error"
                elif etype == "done":
                    finish_reason = event.get("finish_reason", "stop")
        except WebSocketDisconnect:
            # Re-raise so execute() can wrap it as a TurnResult.
            raise
        except asyncio.CancelledError:
            # The outer task is being cancelled (e.g. WS shutdown).
            cancel_event.set()
            raise
        except Exception as exc:
            # v3-5: any LLM streaming error becomes a graceful "error"
            # finish, with detail forwarded through the sink.  The
            # caller persists nothing and emits the WS done(error)
            # event.
            err_detail = "LLM error"
            response = getattr(exc, "response", None)
            if response is not None and hasattr(response, "status_code"):
                err_detail = f"LLM returned {response.status_code}"
            logger.exception("LLM streaming error")
            with contextlib.suppress(Exception):
                await sink.send({"type": "error", "content": err_detail})
            finish_reason = "error"
        finally:
            if reader_task is not None:
                reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await reader_task

        return (
            full_content,
            thinking,
            tool_calls_collected,
            finish_reason,
            in_tok,
            out_tok,
        )

    # ------------------------------------------------------------------
    # Internal: WebSocket cancel reader.
    # ------------------------------------------------------------------

    def _spawn_cancel_reader(
        self,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
    ) -> asyncio.Task[None] | None:
        """Spawn an async task that watches for ``{"type": "cancel"}``.

        Returns ``None`` if the sink is not backed by a real WebSocket
        (e.g. :class:`RecordingEventSink` in tests). The task sets
        ``cancel_event`` on cancel requests or disconnects, allowing the
        streaming loop to exit on the next chunk (~1 ms).
        """
        ws = sink._ws
        if ws is None:
            return None

        async def _reader() -> None:
            while not cancel_event.is_set():
                try:
                    raw = await asyncio.wait_for(
                        ws.receive_text(), timeout=2.0,
                    )
                except asyncio.TimeoutError:
                    continue
                except WebSocketDisconnect:
                    cancel_event.set()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        "Non-fatal error in cancel reader, ignoring",
                    )
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "cancel":
                    cancel_event.set()
                    logger.debug("Client requested stream cancel")
                    return
                # Non-cancel messages received during streaming are
                # rare in practice; log and discard to mirror the
                # legacy ``msg_buffer`` behaviour without leaking
                # state out of the executor.
                logger.debug(
                    "Discarding non-cancel WS message during streaming",
                )

        return asyncio.create_task(_reader())


__all__ = ["DirectTurnExecutor"]
