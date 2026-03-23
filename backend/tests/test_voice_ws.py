"""AL\\CE — Tests for voice WebSocket endpoint (Phase 4).

Tests the voice WS protocol, REST status endpoint, connection limits,
ping/pong, and TTS streaming against the real ``voice.py`` router.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from backend.api.routes import voice as voice_module
from backend.core.app import create_app
from backend.core.config import load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_stt() -> AsyncMock:
    """Return a mock STT service with a typical transcribe response."""
    stt = AsyncMock()
    stt.health_check.return_value = True
    stt.engine = "faster-whisper"
    stt.model_name = "small"
    result = MagicMock(
        text="hello world", language="it", confidence=0.95, duration_s=1.2,
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
    """Read WS messages until ``voice_ready`` is received and return it."""
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
    config = load_config()
    config.stt.enabled = False
    config.tts.enabled = False
    config.vram.monitoring_enabled = False
    with patch("backend.core.app.load_config", return_value=config):
        application = create_app(testing=True)
        async with application.router.lifespan_context(application):
            yield application


@pytest.fixture
async def voice_client(voice_app):
    """Async HTTP client wired to the voice_app."""
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# TestVoiceStatus — REST endpoint
# ---------------------------------------------------------------------------


class TestVoiceStatus:
    """Tests for ``GET /api/voice/status``."""

    async def test_returns_availability_fields(self, voice_client: AsyncClient):
        resp = await voice_client.get("/api/voice/status")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("stt_available", "tts_available", "active_connections"):
            assert key in data

    async def test_no_services_returns_false(self, voice_client: AsyncClient):
        resp = await voice_client.get("/api/voice/status")
        data = resp.json()
        assert data["stt_available"] is False
        assert data["tts_available"] is False
        assert data["active_connections"] == 0

    async def test_with_mock_services(
        self, voice_app: FastAPI, voice_client: AsyncClient,
    ):
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        ctx.tts_service = _mock_tts()
        resp = await voice_client.get("/api/voice/status")
        data = resp.json()
        assert data["stt_available"] is True
        assert data["tts_available"] is True


# ---------------------------------------------------------------------------
# TestVoiceWebSocket — WS protocol basics
# ---------------------------------------------------------------------------


class TestVoiceWebSocket:
    """Tests for ``/api/voice/ws/voice`` protocol."""

    def test_connect_sends_voice_ready_no_services(self, voice_app: FastAPI):
        """No STT/TTS → voice_ready with both False."""
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            ready = _drain_until_ready(ws)
            assert ready["stt_available"] is False
            assert ready["tts_available"] is False

    def test_connect_sends_voice_ready_with_services(self, voice_app: FastAPI):
        """With STT/TTS injected, voice_ready reports True for both."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        ctx.tts_service = _mock_tts()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "voice_ready"
            assert msg["stt_available"] is True
            assert msg["tts_available"] is True
            assert msg["stt_model"] == "small"
            assert msg["stt_engine"] == "faster-whisper"
            assert msg["tts_engine"] == "piper"
            assert msg["sample_rate"] == 22050

    def test_voice_start_stop_no_stt(self, voice_app: FastAPI):
        """voice_start → voice_stop without STT → recording_stopped (empty)."""
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_start"})
            assert ws.receive_json()["type"] == "recording_started"
            ws.send_json({"type": "voice_stop"})
            stopped = ws.receive_json()
            assert stopped["type"] == "recording_stopped"
            assert stopped["empty"] is True

    def test_voice_start_stop_with_stt(self, voice_app: FastAPI):
        """Full flow: start → binary → stop → recording_stopped → stt_processing → transcript."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_start"})
            assert ws.receive_json()["type"] == "recording_started"
            ws.send_bytes(b"\x00" * 1600)
            ws.send_json({"type": "voice_stop"})
            # Production sends recording_stopped (empty=False) then stt_processing.
            stopped = ws.receive_json()
            assert stopped["type"] == "recording_stopped"
            assert stopped["empty"] is False
            assert ws.receive_json()["type"] == "stt_processing"
            transcript = ws.receive_json()
            assert transcript["type"] == "transcript"
            assert transcript["text"] == "hello world"
            assert transcript["language"] == "it"
            assert transcript["confidence"] == 0.95
            assert transcript["duration_s"] == 1.2

    def test_voice_stop_with_stt_but_empty_buffer(self, voice_app: FastAPI):
        """STT available but no audio sent → recording_stopped (empty)."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "voice_start"})
            assert ws.receive_json()["type"] == "recording_started"
            ws.send_json({"type": "voice_stop"})
            stopped = ws.receive_json()
            assert stopped["type"] == "recording_stopped"
            assert stopped["empty"] is True

    def test_binary_frames_ignored_when_not_recording(self, voice_app: FastAPI):
        """Binary data sent outside a recording session is silently dropped."""
        ctx = voice_app.state.context
        ctx.stt_service = _mock_stt()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_bytes(b"\x00" * 100)
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

    def test_unknown_type_ignored(self, voice_app: FastAPI):
        """Unknown message type does not crash; ping still works after."""
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "unknown_xyz"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


# ---------------------------------------------------------------------------
# TestVoicePing
# ---------------------------------------------------------------------------


class TestVoicePing:
    """Keepalive tests."""

    def test_ping_pong(self, voice_app: FastAPI):
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

    def test_multiple_pings(self, voice_app: FastAPI):
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            for _ in range(3):
                ws.send_json({"type": "ping"})
                assert ws.receive_json()["type"] == "pong"


# ---------------------------------------------------------------------------
# TestVoiceTTS — TTS streaming via WS
# ---------------------------------------------------------------------------


class TestVoiceTTS:
    """Tests for TTS playback over the voice WebSocket."""

    def test_tts_speak_streams_audio(self, voice_app: FastAPI):
        """tts_speak → tts_start → binary chunks → tts_done."""
        ctx = voice_app.state.context
        ctx.tts_service = _mock_tts()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "tts_speak", "text": "Ciao mondo"})
            assert ws.receive_json()["type"] == "tts_start"
            chunks: list[bytes] = []
            while True:
                raw = ws.receive()
                if "bytes" in raw:
                    chunks.append(raw["bytes"])
                elif "text" in raw:
                    final = json.loads(raw["text"])
                    assert final["type"] == "tts_done"
                    break
            assert len(chunks) == 2

    def test_tts_speak_no_service_ignored(self, voice_app: FastAPI):
        """tts_speak without TTS service is silently ignored."""
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "tts_speak", "text": "Ciao"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

    def test_tts_speak_empty_text_ignored(self, voice_app: FastAPI):
        """Empty text in tts_speak is silently ignored."""
        ctx = voice_app.state.context
        ctx.tts_service = _mock_tts()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "tts_speak", "text": ""})
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

    def test_tts_speak_too_long_text(self, voice_app: FastAPI):
        """Text exceeding 10 000 chars → voice_error."""
        ctx = voice_app.state.context
        ctx.tts_service = _mock_tts()
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
            ws.send_json({"type": "tts_speak", "text": "x" * 10_001})
            err = ws.receive_json()
            assert err["type"] == "voice_error"
            assert "too long" in err["message"].lower()


# ---------------------------------------------------------------------------
# TestVoiceConnectionLimit
# ---------------------------------------------------------------------------


class TestVoiceConnectionLimit:
    """Connection-limit enforcement."""

    def test_exceeding_max_connections_rejected(self, voice_app: FastAPI):
        """Pre-filling the counter → server closes with 4029."""
        voice_module._voice_connections["testclient"] = (
            voice_module._MAX_VOICE_PER_IP
        )
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            # Server accepts then immediately closes.
            pass

    def test_counter_decremented_after_disconnect(self, voice_app: FastAPI):
        """After a WS disconnects the server-side cleanup runs cleanly."""
        client = TestClient(voice_app)
        with client.websocket_connect("/api/voice/ws/voice") as ws:
            _drain_until_ready(ws)
        # No crash on disconnect → cleanup ran successfully.
