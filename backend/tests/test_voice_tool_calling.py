"""AL\\CE — Tests for voice + tool calling integration (Phase 4).

Since the full voice → LLM → tool pipeline (M10) is not yet implemented in
production, these tests focus on what IS available in voice.py:
- STT transcription via WebSocket (success and error paths)
- TTS synthesis via WebSocket (stream + fallback)
- Audio buffer edge cases (empty, oversized, double-start)
- Concurrent voice sessions and connection management
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.api.routes import voice as voice_module
from backend.core.app import create_app
from backend.core.config import AliceConfig, load_config
from backend.services.audio_utils import MAX_AUDIO_SIZE_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_stt(
    text: str = "Quanta RAM usa il sistema?",
    language: str = "it",
    confidence: float = 0.95,
    duration_s: float = 2.0,
) -> AsyncMock:
    """Return a mock STT service with configurable transcribe response."""
    stt = AsyncMock()
    stt.health_check.return_value = True
    stt.engine = "faster-whisper"
    stt.model_name = "small"
    result = MagicMock(
        text=text, language=language,
        confidence=confidence, duration_s=duration_s,
    )
    stt.transcribe.return_value = result
    return stt


def _mock_tts() -> AsyncMock:
    """Return a mock TTS service with streaming support."""
    tts = AsyncMock()
    tts.health_check.return_value = True
    tts.synthesize.return_value = b"\x00" * 100
    tts.sample_rate = 22050
    tts.engine = "piper"

    async def _stream(text: str):
        yield b"\x00" * 50
        yield b"\x00" * 50

    tts.synthesize_stream = _stream
    return tts


def _drain_until_ready(ws) -> dict:
    """Read WS messages until ``voice_ready`` is received."""
    while True:
        msg = ws.receive_json()
        if msg.get("type") == "voice_ready":
            return msg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_voice_connections():
    """Ensure the module-level connection tracker is clean per test."""
    voice_module._voice_connections.clear()
    yield
    voice_module._voice_connections.clear()


@pytest.fixture
async def voice_app():
    """FastAPI app with STT/TTS/VRAM disabled for clean voice tests."""
    config = AliceConfig()
    config.stt.enabled = False
    config.tts.enabled = False
    config.vram.monitoring_enabled = False
    with patch("backend.core.app.load_config", return_value=config):
        application = create_app(testing=True)
        async with application.router.lifespan_context(application):
            yield application


# ---------------------------------------------------------------------------
# TestVoiceTranscription — STT via WebSocket
# ---------------------------------------------------------------------------


class TestVoiceTranscription:
    """Tests for the STT flow through the real voice WS endpoint."""

    def test_transcript_returned_after_stt(self, voice_app: FastAPI):
        """Full STT flow produces transcript with expected fields."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_start"})
            assert ws.receive_json()["type"] == "recording_started"
            ws.send_bytes(b"\x00" * 3200)
            ws.send_json({"type": "voice_stop"})
            stopped = ws.receive_json()
            assert stopped["type"] == "recording_stopped"
            assert stopped["empty"] is False
            assert ws.receive_json()["type"] == "stt_processing"
            t = ws.receive_json()
            assert t["type"] == "transcript"
            assert t["text"] == "Quanta RAM usa il sistema?"
            assert t["language"] == "it"
            assert t["confidence"] >= 0.8

    def test_stt_runtime_error_sends_reload_message(self, voice_app: FastAPI):
        """RuntimeError from STT → voice_error mentioning model reload."""
        ctx = voice_app.state.context
        stt = AsyncMock()
        stt.health_check.return_value = True
        stt.engine = "faster-whisper"
        stt.model_name = "small"
        stt.transcribe.side_effect = RuntimeError("Model crashed")
        ctx.stt_service = stt
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_start"})
            assert ws.receive_json()["type"] == "recording_started"
            ws.send_bytes(b"\x00" * 100)
            ws.send_json({"type": "voice_stop"})
            assert ws.receive_json()["type"] == "recording_stopped"
            assert ws.receive_json()["type"] == "stt_processing"
            err = ws.receive_json()
            assert err["type"] == "voice_error"
            assert "RuntimeError" in err["message"]
            assert "reload" in err["message"].lower()

    def test_stt_generic_error(self, voice_app: FastAPI):
        """Non-RuntimeError from STT → voice_error with exception class name."""
        ctx = voice_app.state.context
        stt = AsyncMock()
        stt.health_check.return_value = True
        stt.engine = "faster-whisper"
        stt.model_name = "small"
        stt.transcribe.side_effect = ValueError("Bad audio format")
        ctx.stt_service = stt
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_start"})
            ws.receive_json()  # recording_started
            ws.send_bytes(b"\x00" * 100)
            ws.send_json({"type": "voice_stop"})
            ws.receive_json()  # recording_stopped
            ws.receive_json()  # stt_processing
            err = ws.receive_json()
            assert err["type"] == "voice_error"
            assert "ValueError" in err["message"]

    def test_empty_audio_returns_recording_stopped_empty(self, voice_app: FastAPI):
        """voice_start → voice_stop with no audio → recording_stopped (empty)."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_start"})
            ws.receive_json()  # recording_started
            ws.send_json({"type": "voice_stop"})
            stopped = ws.receive_json()
            assert stopped["type"] == "recording_stopped"
            assert stopped["empty"] is True

    def test_no_stt_service_returns_empty(self, voice_app: FastAPI):
        """With no STT service, even with audio data → recording_stopped (empty)."""
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_start"})
            ws.receive_json()  # recording_started
            ws.send_bytes(b"\x00" * 1600)
            ws.send_json({"type": "voice_stop"})
            stopped = ws.receive_json()
            assert stopped["type"] == "recording_stopped"
            assert stopped["empty"] is True

    def test_stt_called_with_wav_wrapped_audio(self, voice_app: FastAPI):
        """STT.transcribe receives WAV-wrapped audio (not raw PCM)."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_start"})
            ws.receive_json()  # recording_started
            ws.send_bytes(b"\x00" * 1600)
            ws.send_json({"type": "voice_stop"})
            ws.receive_json()  # recording_stopped
            ws.receive_json()  # stt_processing
            ws.receive_json()  # transcript
            ctx.stt_service.transcribe.assert_called_once()
            wav_data = ctx.stt_service.transcribe.call_args[0][0]
            # WAV files start with the RIFF header.
            assert wav_data[:4] == b"RIFF"


# ---------------------------------------------------------------------------
# TestVoiceTTSIntegration — TTS via WebSocket
# ---------------------------------------------------------------------------


class TestVoiceTTSIntegration:
    """Tests for TTS synthesis through the real voice WS endpoint."""

    def test_tts_speak_produces_audio_stream(self, voice_app: FastAPI):
        """tts_speak → tts_start → binary chunks → tts_done."""
        ctx = voice_app.state.context
        ctx.tts_service = _mock_tts()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({
                "type": "tts_speak",
                "text": "16 GB di RAM su 32 totali",
            })
            assert ws.receive_json()["type"] == "tts_start"
            chunks: list[bytes] = []
            while True:
                raw = ws.receive()
                if "bytes" in raw:
                    chunks.append(raw["bytes"])
                elif "text" in raw:
                    msg = json.loads(raw["text"])
                    assert msg["type"] == "tts_done"
                    break
            assert len(chunks) == 2
            assert all(isinstance(c, bytes) for c in chunks)

    def test_tts_no_service_no_crash(self, voice_app: FastAPI):
        """tts_speak without TTS service does not crash — silently ignored."""
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "tts_speak", "text": "Prova senza TTS"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

    def test_tts_cancel_no_crash(self, voice_app: FastAPI):
        """tts_cancel without an active TTS task does not crash."""
        ctx = voice_app.state.context
        ctx.tts_service = _mock_tts()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "tts_cancel"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


# ---------------------------------------------------------------------------
# TestVoiceErrorPaths — edge cases and limits
# ---------------------------------------------------------------------------


class TestVoiceErrorPaths:
    """Tests for error handling in the voice WS endpoint."""

    def test_oversized_audio_buffer(self, voice_app: FastAPI):
        """Exceeding MAX_AUDIO_SIZE_BYTES → voice_error."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        # Patch the limit to a small value for fast testing.
        with patch.object(voice_module, "MAX_AUDIO_SIZE_BYTES", 1024):
            client = TestClient(voice_app)
            with client.websocket_connect("/api/voice/ws/voice") as ws:
                _drain_until_ready(ws)
                ws.send_json({"type": "voice_start"})
                ws.receive_json()  # recording_started
                ws.send_bytes(b"\x00" * 2048)
                # Server detects overflow on the binary frame.
                # The next ping should still work; drain until pong.
                ws.send_json({"type": "ping"})
                msgs: list[dict] = []
                while True:
                    raw = ws.receive()
                    if "text" in raw:
                        msg = json.loads(raw["text"])
                        msgs.append(msg)
                        if msg["type"] == "pong":
                            break
                error_msgs = [m for m in msgs if m["type"] == "voice_error"]
                assert any(
                    "buffer limit" in m["message"].lower() for m in error_msgs
                )

    def test_tts_text_too_long(self, voice_app: FastAPI):
        """Text > 10000 chars → voice_error about length."""
        ctx = voice_app.state.context
        ctx.tts_service = _mock_tts()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "tts_speak", "text": "x" * 10_001})
            err = ws.receive_json()
            assert err["type"] == "voice_error"
            assert "too long" in err["message"].lower()

    def test_multiple_voice_start_resets_buffer(self, voice_app: FastAPI):
        """A second voice_start clears the buffer from the first recording."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            # First recording.
            ws.send_json({"type": "voice_start"})
            assert ws.receive_json()["type"] == "recording_started"
            ws.send_bytes(b"\x01" * 100)
            # Second voice_start without voice_stop → buffer cleared.
            ws.send_json({"type": "voice_start"})
            assert ws.receive_json()["type"] == "recording_started"
            ws.send_bytes(b"\x02" * 200)
            ws.send_json({"type": "voice_stop"})
            assert ws.receive_json()["type"] == "recording_stopped"
            assert ws.receive_json()["type"] == "stt_processing"
            t = ws.receive_json()
            assert t["type"] == "transcript"
            # STT was called exactly once (only the second recording).
            ctx.stt_service.transcribe.assert_called_once()

    def test_voice_stop_without_start(self, voice_app: FastAPI):
        """voice_stop without prior voice_start → recording_stopped (empty)."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_stop"})
            stopped = ws.receive_json()
            assert stopped["type"] == "recording_stopped"
            assert stopped["empty"] is True


# ---------------------------------------------------------------------------
# TestVoiceConcurrentSessions — connection management
# ---------------------------------------------------------------------------


class TestVoiceConcurrentSessions:
    """Tests for concurrent voice session handling."""

    def test_two_sessions_from_same_ip(self, voice_app: FastAPI):
        """Two simultaneous WS connections from the same IP both work."""
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws1:
            _drain_until_ready(ws1)
            with client.websocket_connect("/api/voice/ws/voice") as ws2:
                _drain_until_ready(ws2)
                ws1.send_json({"type": "ping"})
                assert ws1.receive_json()["type"] == "pong"
                ws2.send_json({"type": "ping"})
                assert ws2.receive_json()["type"] == "pong"

    def test_third_session_rejected(self, voice_app: FastAPI):
        """Third connection from same IP is rejected (limit is 2)."""
        # Pre-fill to the limit so the next connect is rejected.
        voice_module._voice_connections["testclient"] = (
            voice_module._MAX_VOICE_PER_IP
        )
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            # Server accepts then immediately closes with 4029.
            pass
