"""AL\\CE — Direct turn executor (legacy behaviour, refactored).

:class:`DirectTurnExecutor` is the default :class:`TurnExecutor` strategy.
It preserves the *exact* behaviour of the original closure-based
``ws_chat`` flow:

1. Stream the initial LLM completion via :meth:`LLMService.chat`,
   relaying ``token`` / ``thinking`` / ``tool_call`` / ``error`` / ``done``
   events through a :class:`WSEventSink`.
2. If tool calls were requested, delegate to
   :func:`backend.api.routes._tool_loop.run_tool_loop`, passing the
   outbound ``sink`` and the inbound :class:`InteractionChannel`.
3. Honour ``cancel_event`` at every chunk and after the tool loop (the
   channel's single read-pump sets it on a cancel frame).
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
import uuid
from dataclasses import replace
from typing import Any

from fastapi import WebSocketDisconnect
from loguru import logger

from backend.core.context import AppContext
from backend.services.llm_service import LLMService
from backend.services.turn import events
from backend.services.turn.channel import InteractionChannel
from backend.services.turn.models import TurnInput, TurnProgress, TurnResult
from backend.services.turn.sink import (
    WSEventSink,
    is_websocket_closed_runtime_error,
)


class DirectTurnExecutor:
    """Executes a turn using the legacy stream + tool-loop pipeline.

    Args:
        ctx: Application context (config, tool registry, services).
        llm: Active :class:`LLMService` instance.
    """

    def __init__(
        self,
        ctx: AppContext,
        llm: LLMService,
    ) -> None:
        self.ctx = ctx
        self.llm = llm

    async def execute(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        session: Any,
        channel: InteractionChannel | None = None,
    ) -> TurnResult:
        """Run the full turn and return its outcome.

        Args:
            turn: Immutable input bundle.
            sink: Sink used for outbound WS events.
            cancel_event: Event toggled by the caller (or the channel's
                read-pump) to abort the turn early.
            session: Active async DB session (forwarded to the tool loop).
            channel: Inbound interaction channel used by the tool loop for
                confirmation / client-tool round-trips. ``None`` (e.g. in
                tests with a non-WS sink) disables the tool-loop path.

        Returns:
            A :class:`TurnResult` describing the final state. The
            executor swallows :class:`WebSocketDisconnect` and LLM
            errors, surfacing them through ``finish_reason``
            (``"disconnected"`` / ``"error"``).
        """
        progress = TurnProgress(turn_id=uuid.uuid4().hex)
        max_steps = self.ctx.config.llm.max_tool_iterations + 1
        with contextlib.suppress(Exception):
            await sink.send(events.turn_started(
                turn_id=progress.turn_id,
                conversation_id=str(turn.conv_id),
            ))

        # ------------------------------------------------------------------
        # Phase 1 — stream initial LLM response.  Owns its own cancel
        # reader so the WebSocket never has two concurrent readers (v3-1).
        # ------------------------------------------------------------------
        progress.steps = 1
        with contextlib.suppress(Exception):
            await sink.send(
                events.turn_llm_step(turn_id=progress.turn_id, step=1),
            )

        try:
            (
                full_content,
                thinking,
                tool_calls,
                finish_reason,
                in_tok,
                out_tok,
            ) = await self._stream_initial(turn, sink, cancel_event, progress)
        except WebSocketDisconnect:
            # v2-4 / v3-1: disconnect during initial stream.  No content
            # has been collected yet — bubble up as "disconnected" with
            # whatever the executor managed to accumulate (typically "").
            logger.debug("WS disconnected during initial stream")
            return await self._finish(sink, progress, TurnResult(
                content="",
                thinking="",
                input_tokens=0,
                output_tokens=0,
                finish_reason="disconnected",
                final_assistant_message_id=None,
                had_tool_calls=False,
            ))

        # Step-1 usage snapshot (success path only — the disconnect branch
        # above returns before reaching here).
        with contextlib.suppress(Exception):
            await sink.send(events.turn_usage(
                turn_id=progress.turn_id,
                step=1,
                input_tokens=in_tok,
                output_tokens=out_tok,
                tool_calls=0,
                max_steps=max_steps,
            ))

        # v3-2 (also valid post-stream): cancel takes precedence over
        # any other finish reason emitted by the LLM.
        if finish_reason == "disconnected":
            return await self._finish(sink, progress, TurnResult(
                content=full_content,
                thinking=thinking,
                input_tokens=in_tok,
                output_tokens=out_tok,
                finish_reason="disconnected",
                final_assistant_message_id=None,
                had_tool_calls=False,
            ))

        if cancel_event.is_set():
            return await self._finish(sink, progress, TurnResult(
                content=full_content,
                thinking=thinking,
                input_tokens=in_tok,
                output_tokens=out_tok,
                finish_reason="cancelled",
                final_assistant_message_id=None,
                had_tool_calls=False,
            ))

        # The streaming layer captured an LLM error (already emitted as
        # WS event by ``_stream_initial``) — short-circuit.
        if finish_reason == "error":
            return await self._finish(sink, progress, TurnResult(
                content=full_content,
                thinking=thinking,
                input_tokens=in_tok,
                output_tokens=out_tok,
                finish_reason="error",
                final_assistant_message_id=None,
                had_tool_calls=False,
            ))

        # ------------------------------------------------------------------
        # Phase 2 — tool loop.
        # ------------------------------------------------------------------
        had_tool_calls = False
        if tool_calls:
            had_tool_calls = True
            if channel is None:
                # In tests with a RecordingEventSink and no channel, the
                # tool loop is not exercised because run_tool_loop needs an
                # inbound channel.  Surface a deterministic error instead of
                # a cryptic AttributeError.
                logger.error(
                    "DirectTurnExecutor: tool calls requested but no "
                    "InteractionChannel was provided — refusing to invoke "
                    "run_tool_loop.",
                )
                return await self._finish(sink, progress, TurnResult(
                    content=full_content,
                    thinking=thinking,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    finish_reason="error",
                    final_assistant_message_id=None,
                    had_tool_calls=True,
                ))

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
            from backend.services.turn.tool_loop import run_tool_loop

            try:
                (
                    full_content,
                    thinking,
                    in_tok2,
                    out_tok2,
                    loop_finish,
                ) = await run_tool_loop(
                    channel=channel,
                    sink=sink,
                    ctx=self.ctx,
                    session=session,
                    conv_id=turn.conv_id,
                    llm=self.llm,
                    tool_calls_from_llm=tool_calls,
                    full_content=full_content,
                    thinking_content=thinking,
                    max_iterations=self.ctx.config.llm.max_tool_iterations,
                    confirmation_timeout_s=(
                        self.ctx.config.permissions.confirmation_timeout_s
                    ),
                    client_ip=turn.client_ip,
                    cancel_event=cancel_event,
                    memory_context=turn.memory_context,
                    tools=turn.tools,
                    initial_history=effective_history,
                    system_prompt=turn.cached_sys_prompt,
                    version_group_id=turn.version_group_id,
                    version_index=turn.version_index,
                    context_window=turn.context_window,
                    turn_progress=progress,
                )
                if in_tok2 > 0:
                    in_tok = in_tok2
                    out_tok = out_tok2
                finish_reason = loop_finish
            except WebSocketDisconnect:
                # v2-4: keep partial content for recovery in ws_chat.
                logger.debug("WS disconnected during tool loop")
                return await self._finish(sink, progress, TurnResult(
                    content=full_content,
                    thinking=thinking,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    finish_reason="disconnected",
                    final_assistant_message_id=None,
                    had_tool_calls=True,
                ))
            except Exception:
                # Preserve legacy behaviour: a generic tool-loop failure
                # surfaces as a sink error event + finish_reason="error".
                logger.exception("Tool loop error")
                with contextlib.suppress(Exception):
                    await sink.send({
                        "type": "error",
                        "content": "Tool execution error",
                    })
                return await self._finish(sink, progress, TurnResult(
                    content=full_content,
                    thinking=thinking,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    finish_reason="error",
                    final_assistant_message_id=None,
                    had_tool_calls=True,
                ))

            # v3-2: cancel during the tool loop returns the loop's last
            # finish_reason (typically "stop") — override it to
            # "cancelled" so the persistence layer takes the cancel path.
            if cancel_event.is_set():
                return await self._finish(sink, progress, TurnResult(
                    content=full_content,
                    thinking=thinking,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    finish_reason="cancelled",
                    final_assistant_message_id=None,
                    had_tool_calls=True,
                ))

        return await self._finish(sink, progress, TurnResult(
            content=full_content,
            thinking=thinking,
            input_tokens=in_tok,
            output_tokens=out_tok,
            finish_reason=finish_reason,
            final_assistant_message_id=None,
            had_tool_calls=had_tool_calls,
        ))

    async def _finish(
        self,
        sink: WSEventSink,
        progress: TurnProgress,
        result: TurnResult,
    ) -> TurnResult:
        """Emit the terminal ``turn.finished`` frame, then return ``result``.

        Routing every :meth:`execute` exit through this helper guarantees a
        single ``turn.finished`` per turn, carrying the result's real
        ``finish_reason`` / token usage and the per-turn step count. The
        accumulated ``progress.cost`` is stamped onto the returned result via
        :func:`dataclasses.replace` (the sole construction site that sets
        ``cost`` — the seven :class:`TurnResult` call sites in :meth:`execute`
        stay untouched). The emission is best-effort (wrapped in
        :func:`contextlib.suppress`) so it can never alter the existing
        control flow or return value.

        On ``finish_reason == "error"`` the frame carries ``cost=None`` even
        when credits were spent on intermediate steps: ``_persist_final_turn``
        rolls back error turns, so a cost on the frame would be summed by the
        frontend live chip but never backed by the persisted ledger — the
        total would drop on reload. The discarded cost joins the documented
        under-count classes (handoff OpenRouter, gotcha 7). The returned
        ``result`` keeps the real accumulated cost either way.

        Args:
            sink: Outbound event sink for the turn.
            progress: Mutable per-turn counters (supplies ``turn_id``,
                ``steps`` and the accumulated ``cost``).
            result: The :class:`TurnResult` about to be returned.

        Returns:
            ``result`` with ``cost`` stamped from ``progress.cost``.
        """
        result = replace(result, cost=progress.cost)
        frame_cost = (
            result.cost
            if result.cost > 0 and result.finish_reason != "error"
            else None
        )
        with contextlib.suppress(Exception):
            await sink.send(events.turn_finished(
                turn_id=progress.turn_id,
                finish_reason=result.finish_reason,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                steps=progress.steps,
                cost=frame_cost,
            ))
        return result

    # ------------------------------------------------------------------
    # Internal: initial streaming pass (legacy ``_stream_and_collect``).
    # ------------------------------------------------------------------

    async def _stream_initial(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        progress: TurnProgress,
    ) -> tuple[str, str, list[dict[str, Any]], str, int, int]:
        """Stream the first LLM response and relay events to ``sink``.

        Mirrors the behaviour of the legacy ``_stream_and_collect``
        closure in ``ws_chat``.  Cancellation is observed by the
        :class:`InteractionChannel` read-pump (the single WS reader), which
        sets ``cancel_event``; this method just honours it per chunk.

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

        # Cancel during streaming is observed by the channel's single
        # read-pump (it sets ``cancel_event``), which ``llm.chat`` honours
        # per chunk — no dedicated reader here (avoids a second WS reader).
        async def _send(event: dict[str, Any]) -> bool:
            await sink.send(event)
            return sink.is_connected

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
                    if not await _send(event):
                        finish_reason = "disconnected"
                        break
                elif etype == "thinking":
                    thinking += event.get("content", "")
                    if not await _send(event):
                        finish_reason = "disconnected"
                        break
                elif etype == "tool_call":
                    tool_calls_collected.append(event)
                    if not await _send(event):
                        finish_reason = "disconnected"
                        break
                elif etype == "usage":
                    in_tok = int(event.get("input_tokens", 0) or 0)
                    out_tok = int(event.get("output_tokens", 0) or 0)
                    progress.cost += float(event.get("cost") or 0.0)
                elif etype == "error":
                    # v3-5: capture LLM error here, emit to sink, and
                    # stop without raising.  ws_chat reads finish_reason.
                    logger.error(
                        "LLM error during initial stream: {}",
                        event.get("content", "unknown"),
                    )
                    if not await _send(event):
                        finish_reason = "disconnected"
                        break
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
            if (
                isinstance(exc, RuntimeError)
                and is_websocket_closed_runtime_error(exc)
            ):
                finish_reason = "disconnected"
                return (
                    full_content,
                    thinking,
                    tool_calls_collected,
                    finish_reason,
                    in_tok,
                    out_tok,
                )
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

        return (
            full_content,
            thinking,
            tool_calls_collected,
            finish_reason,
            in_tok,
            out_tok,
        )


__all__ = ["DirectTurnExecutor"]
