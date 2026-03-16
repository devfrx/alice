"""O.M.N.I.A. — Voice WebSocket endpoint (STT + TTS streaming)."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import uuid
import wave
from collections import defaultdict

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from loguru import logger
from starlette.websockets import WebSocketState

from backend.core.context import AppContext
from backend.core.event_bus import OmniaEvent
from backend.services.audio_utils import MAX_AUDIO_SIZE_BYTES

router = APIRouter(prefix="/voice", tags=["voice"])

# Active voice connections per IP (rate limiting).
_voice_connections: dict[str, int] = defaultdict(int)
_voice_lock = asyncio.Lock()
_MAX_VOICE_PER_IP = 2

# Active voice WebSocket connections (for pushing config updates).
_active_voice_sockets: set[WebSocket] = set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(ws_or_request: WebSocket | Request) -> AppContext:
    """Extract ``AppContext`` from ASGI app state."""
    return ws_or_request.app.state.context


async def _send_json(ws: WebSocket, data: dict) -> None:
    """Send JSON to client; silently ignore if connection already closed."""
    if ws.client_state == WebSocketState.CONNECTED:
        try:
            await ws.send_json(data)
        except Exception:
            pass


async def _stream_tts(
    ws: WebSocket, tts, text: str, cancel: asyncio.Event,
) -> None:
    """Stream TTS audio chunks (binary frames) to the client."""
    try:
        await _send_json(ws, {"type": "tts_start"})
        async for chunk in tts.synthesize_stream(text):
            if cancel.is_set():
                break
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_bytes(chunk)
        await _send_json(ws, {"type": "tts_done"})
    except asyncio.CancelledError:
        await _send_json(ws, {"type": "tts_cancelled"})
    except Exception as exc:
        logger.error("TTS streaming error: {}", exc)
        await _send_json(ws, {"type": "voice_error", "message": "TTS synthesis error"})


async def _cancel_tts(
    tts_task: asyncio.Task | None, cancel_event: asyncio.Event,
) -> asyncio.Event:
    """Cancel an ongoing TTS task and return a fresh cancel event."""
    cancel_event.set()
    if tts_task and not tts_task.done():
        tts_task.cancel()
        try:
            await asyncio.wait_for(tts_task, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
    return asyncio.Event()


# ---------------------------------------------------------------------------
# Helpers — voice_ready payload
# ---------------------------------------------------------------------------


def _build_voice_ready_payload(ctx: AppContext) -> dict:
    """Build a ``voice_ready`` message from current service state."""
    stt = ctx.stt_service
    tts = ctx.tts_service
    return {
        "type": "voice_ready",
        "stt_available": stt is not None,
        "tts_available": tts is not None,
        "stt_model": stt.model_name if stt else None,
        "stt_engine": stt.engine if stt else None,
        "tts_engine": tts.engine if tts else None,
        "tts_voice": tts.voice_name if tts else None,
        "sample_rate": tts.sample_rate if tts else None,
        "activation_mode": ctx.config.voice.activation_mode,
        "wake_word": ctx.config.voice.wake_word,
        "auto_tts_response": ctx.config.voice.auto_tts_response,
    }


async def push_voice_ready(ctx: AppContext) -> None:
    """Push a fresh ``voice_ready`` to all active voice WebSocket connections.

    Called after STT/TTS config changes so the frontend gets updated
    engine/model/availability info without requiring a WS reconnect.
    """
    if not _active_voice_sockets:
        return
    payload = _build_voice_ready_payload(ctx)
    for ws in list(_active_voice_sockets):
        await _send_json(ws, payload)
    logger.debug("Pushed voice_ready to {} active connections", len(_active_voice_sockets))


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket) -> None:
    """Voice streaming WebSocket endpoint.

    Protocol (binary + JSON on the same connection):

    **Client → Server**
      - ``{"type": "voice_start"}`` — begin recording
      - binary frames — raw audio (PCM 16 kHz 16-bit mono)
      - ``{"type": "voice_stop"}`` — end recording, trigger STT
      - ``{"type": "tts_speak", "text": "..."}`` — request TTS synthesis
      - ``{"type": "tts_cancel"}`` — interrupt ongoing TTS playback
      - ``{"type": "ping"}``

    **Server → Client**
      - ``{"type": "voice_ready", "stt_available": bool, "tts_available": bool, "stt_model": str|null, "stt_engine": str|null, "tts_engine": str|null, "sample_rate": int|null}``
      - ``{"type": "recording_started"}``
      - ``{"type": "stt_processing"}``
      - ``{"type": "transcript", "text": "...", "language": "...", ...}``
      - ``{"type": "tts_start"}`` / ``{"type": "tts_done"}`` / binary TTS audio
      - ``{"type": "voice_error", "message": "..."}``
    """
    ctx = _ctx(websocket)
    client_ip = websocket.client.host if websocket.client else "unknown"
    session_id = uuid.uuid4().hex[:12]

    # Connection limit check.
    async with _voice_lock:
        if _voice_connections.get(client_ip, 0) >= _MAX_VOICE_PER_IP:
            await websocket.close(code=4029, reason="Too many voice connections")
            return
        await websocket.accept()
        _voice_connections[client_ip] += 1
    logger.debug("Voice WS connected: session={} ip={}", session_id, client_ip)
    _active_voice_sockets.add(websocket)
    await ctx.event_bus.emit(OmniaEvent.VOICE_SESSION_START, session_id=session_id)

    # Per-session state.
    audio_buffer = bytearray()
    is_recording = False
    client_sample_rate = 16000  # default; updated by voice_start
    cancel_event = asyncio.Event()
    tts_task: asyncio.Task | None = None
    stt_task_ref: asyncio.Task | None = None

    try:
        # Read services dynamically from ctx so that config-driven
        # restarts are picked up within the same WS session.
        stt = ctx.stt_service
        tts = ctx.tts_service

        # Log unavailable services (voice_ready already carries the flags).
        if not stt:
            logger.warning("Voice WS {}: STT service not available at connect time", session_id)
        if not tts:
            logger.warning("Voice WS {}: TTS service not available at connect time", session_id)
        await _send_json(websocket, _build_voice_ready_payload(ctx))

        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # Re-read services on each iteration so config-driven
            # restarts (via PUT /config) are picked up immediately.
            stt = ctx.stt_service
            tts = ctx.tts_service

            # --- Binary frame: audio data ----------------------------------
            if "bytes" in message:
                if is_recording and stt:
                    if len(audio_buffer) + len(message["bytes"]) > MAX_AUDIO_SIZE_BYTES:
                        is_recording = False
                        audio_buffer.clear()
                        await _send_json(websocket, {
                            "type": "voice_error",
                            "message": "Audio buffer limit exceeded",
                        })
                    else:
                        audio_buffer.extend(message["bytes"])
                continue

            # --- JSON frame ------------------------------------------------
            if "text" not in message:
                continue
            try:
                data = json.loads(message["text"])
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            if msg_type == "voice_start":
                # Auto-cancel ongoing TTS when user starts speaking.
                cancel_event = await _cancel_tts(tts_task, cancel_event)
                audio_buffer.clear()
                is_recording = True
                # Client may send the actual AudioContext sample rate.
                try:
                    client_sample_rate = max(8000, min(48000, int(data.get("sample_rate", 16000))))
                except (ValueError, TypeError):
                    client_sample_rate = 16000
                logger.debug(
                    "Recording started: session={} sample_rate={}",
                    session_id, client_sample_rate,
                )
                await _send_json(websocket, {"type": "recording_started"})

            elif msg_type == "voice_stop":
                is_recording = False
                if not stt or len(audio_buffer) == 0:
                    await _send_json(websocket, {
                        "type": "recording_stopped", "empty": True,
                    })
                    continue

                audio_copy = bytes(audio_buffer)
                audio_buffer.clear()
                await _send_json(websocket, {"type": "recording_stopped", "empty": False})
                await _send_json(websocket, {"type": "stt_processing"})

                # Wrap raw PCM-16 mono in a WAV container using the
                # actual sample rate reported by the client.
                logger.debug(
                    "Wrapping PCM buffer: {} bytes, sample_rate={}",
                    len(audio_copy), client_sample_rate,
                )
                wav_buf = io.BytesIO()
                with wave.open(wav_buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(client_sample_rate)
                    wf.writeframes(audio_copy)
                wav_bytes = wav_buf.getvalue()

                # Offload STT to a task so the WS loop stays responsive
                async def _run_stt(
                    wav_data: bytes, sid: str, stt_svc: object,
                ) -> None:
                    try:
                        await ctx.event_bus.emit(OmniaEvent.STT_STARTED, session_id=sid)
                        result = await stt_svc.transcribe(wav_data)
                        logger.debug(
                            "STT result: text={!r} lang={} conf={:.3f} dur={:.1f}s",
                            result.text, result.language,
                            result.confidence, result.duration_s,
                        )
                        await ctx.event_bus.emit(
                            OmniaEvent.STT_RESULT, session_id=sid, text=result.text,
                        )
                        await _send_json(websocket, {
                            "type": "transcript",
                            "text": result.text,
                            "language": result.language,
                            "confidence": result.confidence,
                            "duration_s": result.duration_s,
                        })
                    except RuntimeError as exc:
                        logger.error("STT RuntimeError: {}", exc)
                        await ctx.event_bus.emit(
                            OmniaEvent.STT_ERROR, session_id=sid, error=str(exc),
                        )
                        await _send_json(websocket, {
                            "type": "voice_error",
                            "message": f"Transcription failed: {type(exc).__name__}. "
                                       "The model will reload on the next attempt.",
                        })
                    except Exception as exc:
                        logger.exception("STT transcription failed: {}", exc)
                        await ctx.event_bus.emit(
                            OmniaEvent.STT_ERROR, session_id=sid, error=str(exc),
                        )
                        await _send_json(websocket, {
                            "type": "voice_error",
                            "message": f"Transcription failed: {type(exc).__name__}",
                        })

                stt_task_ref = asyncio.create_task(
                    _run_stt(wav_bytes, session_id, stt),
                )

            elif msg_type == "tts_speak":
                text = data.get("text", "").strip()
                if not tts or not text:
                    continue
                if len(text) > 10_000:
                    await _send_json(websocket, {
                        "type": "voice_error",
                        "message": "Text too long for TTS synthesis",
                    })
                    continue
                cancel_event = await _cancel_tts(tts_task, cancel_event)
                tts_task = asyncio.create_task(
                    _stream_tts(websocket, tts, text, cancel_event),
                )

            elif msg_type == "tts_cancel":
                cancel_event = await _cancel_tts(tts_task, cancel_event)

            elif msg_type == "ping":
                await _send_json(websocket, {"type": "pong"})

    except WebSocketDisconnect:
        logger.debug("Voice WS disconnected: session={}", session_id)
    except Exception as exc:
        logger.error("Voice WS error [{}]: {}", session_id, exc)
    finally:
        # Cancel any running STT task
        if stt_task_ref and not stt_task_ref.done():
            stt_task_ref.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stt_task_ref
        # Cancel any running TTS task
        if tts_task and not tts_task.done():
            tts_task.cancel()
            try:
                await tts_task
            except (asyncio.CancelledError, Exception):
                pass
        async with _voice_lock:
            _voice_connections[client_ip] = max(
                0, _voice_connections.get(client_ip, 1) - 1,
            )
            if _voice_connections.get(client_ip, 0) <= 0:
                _voice_connections.pop(client_ip, None)
        _active_voice_sockets.discard(websocket)
        cancel_event.set()
        try:
            await ctx.event_bus.emit(
                OmniaEvent.VOICE_SESSION_END, session_id=session_id,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# REST — voice service health
# ---------------------------------------------------------------------------


@router.get("/status")
async def voice_status(request: Request) -> dict:
    """Return availability of STT/TTS services and active connection count."""
    ctx = _ctx(request)
    stt_ok = (
        ctx.stt_service is not None and await ctx.stt_service.health_check()
    )
    tts_ok = (
        ctx.tts_service is not None and await ctx.tts_service.health_check()
    )
    return {
        "stt_available": stt_ok,
        "tts_available": tts_ok,
        "active_connections": sum(_voice_connections.values()),
    }
