"""AL\\CE — Tests for STT service (Phase 4)."""

from __future__ import annotations

import math
import struct
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.core.config import STTConfig


# ---------------------------------------------------------------------------
# Mock faster_whisper module (avoids needing the real native package)
# ---------------------------------------------------------------------------

def _mock_faster_whisper_module() -> MagicMock:
    """Build a mock ``faster_whisper`` module so ``from faster_whisper import
    WhisperModel`` resolves to a MagicMock class without the real package."""
    mod = MagicMock()
    return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wav(duration_s: float = 1.0, rate: int = 16000) -> bytes:
    """Create minimal valid WAV file bytes (16-bit mono PCM)."""
    num_samples = int(rate * duration_s)
    data_size = num_samples * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16,
        b"data", data_size,
    )
    return header + b"\x00" * data_size


def _make_mock_model(
    text: str = " Ciao, come stai?",
    avg_logprob: float = -0.3,
    duration: float = 2.5,
    language: str = "it",
) -> MagicMock:
    """Build a mock WhisperModel with configurable segment/info."""
    model = MagicMock()
    segment = MagicMock()
    segment.text = text
    segment.start = 0.0
    segment.end = duration
    segment.avg_logprob = avg_logprob
    info = MagicMock()
    info.language = language
    info.language_probability = 0.95
    info.duration = duration
    model.transcribe.return_value = ([segment], info)
    return model


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def stt_config() -> STTConfig:
    """Minimal CPU config for testing."""
    return STTConfig(enabled=True, device="cpu", compute_type="int8")


@pytest.fixture
def mock_whisper_model():
    """Mock faster-whisper WhisperModel with a single Italian segment."""
    return _make_mock_model()


@pytest.fixture
def mock_fw():
    """Inject a mock ``faster_whisper`` module into ``sys.modules``.

    Yields the mock ``WhisperModel`` class so tests can configure
    return values and assert calls — without needing the real native
    package installed.
    """
    fw = _mock_faster_whisper_module()
    with patch.dict(sys.modules, {"faster_whisper": fw}):
        yield fw.WhisperModel


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestSTTServiceLifecycle:
    """Test start / stop / health_check."""

    async def test_start_loads_model(self, mock_fw, stt_config):
        """Starting the service should trigger model loading."""
        from backend.services.stt_service import STTService

        svc = STTService(stt_config)
        await svc.start()

        mock_fw.assert_called_once_with(
            stt_config.model,
            device=stt_config.device,
            compute_type=stt_config.compute_type,
        )
        assert await svc.health_check() is True

    async def test_stop_unloads_model(self, mock_fw, stt_config):
        """Stopping should release model resources."""
        from backend.services.stt_service import STTService

        svc = STTService(stt_config)
        await svc.start()
        await svc.stop()

        assert await svc.health_check() is False

    async def test_health_check_true_when_loaded(self, mock_fw, stt_config):
        """health_check returns True when model is loaded."""
        from backend.services.stt_service import STTService

        svc = STTService(stt_config)
        await svc.start()
        assert await svc.health_check() is True

    async def test_health_check_false_when_not_loaded(self, stt_config):
        """health_check returns False before model is loaded."""
        from backend.services.stt_service import STTService

        svc = STTService(stt_config)
        assert await svc.health_check() is False


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

class TestSTTTranscribe:
    """Test transcription."""

    async def test_transcribe_returns_result(
        self, mock_fw, stt_config, mock_whisper_model
    ):
        """Basic transcription returns a TranscriptResult."""
        from backend.services.stt_service import STTService, TranscriptResult

        mock_fw.return_value = mock_whisper_model
        svc = STTService(stt_config)
        await svc.start()

        result = await svc.transcribe(_make_wav(duration_s=1.0))

        assert isinstance(result, TranscriptResult)
        assert "Ciao" in result.text
        assert result.language == "it"
        assert 0.0 <= result.confidence <= 1.0
        expected_conf = math.exp(-0.3)
        assert result.confidence == pytest.approx(expected_conf, rel=1e-3)
        assert result.duration_s == pytest.approx(2.5)

    async def test_transcribe_lazy_loads_model(self, mock_fw, stt_config):
        """Transcribe should auto-load the model if not yet started."""
        from backend.services.stt_service import STTService

        mock_fw.return_value = _make_mock_model(
            text=" Test", avg_logprob=-0.2, duration=1.0,
        )

        svc = STTService(stt_config)
        result = await svc.transcribe(_make_wav())

        mock_fw.assert_called_once()
        assert result.text.strip() == "Test"

    async def test_transcribe_segment_confidence(self, mock_fw, stt_config):
        """Per-segment confidence should use math.exp(avg_logprob)."""
        from backend.services.stt_service import STTService

        logprob = -0.5
        mock_fw.return_value = _make_mock_model(avg_logprob=logprob)
        svc = STTService(stt_config)
        await svc.start()

        result = await svc.transcribe(_make_wav())

        assert result.segments is not None
        seg = result.segments[0]
        assert seg.confidence == pytest.approx(math.exp(logprob), rel=1e-3)

    @patch("backend.services.stt_service.TRANSCRIPTION_TIMEOUT_S", 1)
    async def test_transcribe_timeout(self, mock_fw, stt_config):
        """Should raise RuntimeError on transcription timeout."""
        from backend.services.stt_service import STTService

        def _hang(*_a, **_kw):
            time.sleep(10)

        mock_fw.return_value.transcribe.side_effect = _hang

        svc = STTService(stt_config)
        await svc.start()

        with pytest.raises(RuntimeError, match="[Tt]imed? ?out"):
            await svc.transcribe(_make_wav())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestSTTValidation:
    """Test audio data validation."""

    async def test_reject_oversized_audio(self, stt_config):
        """Audio exceeding max_audio_size_mb should be rejected."""
        from backend.services.stt_service import STTService

        svc = STTService(stt_config)
        huge = b"RIFF" + b"\x00" * (stt_config.max_audio_size_mb * 1024 * 1024)

        with pytest.raises(ValueError, match="[Ss]ize|[Tt]oo large|exceeds"):
            await svc.transcribe(huge)

    async def test_reject_invalid_format(self, stt_config):
        """Random bytes should be rejected as invalid audio."""
        from backend.services.stt_service import STTService

        svc = STTService(stt_config)

        with pytest.raises(ValueError, match="[Ff]ormat|[Uu]nsupported|[Ii]nvalid"):
            await svc.transcribe(b"not audio data at all")

    async def test_reject_empty_audio(self, stt_config):
        """Empty bytes should be rejected."""
        from backend.services.stt_service import STTService

        svc = STTService(stt_config)

        with pytest.raises(ValueError, match="[Ee]mpty"):
            await svc.transcribe(b"")

    async def test_accept_wav_format(self, mock_fw, stt_config, mock_whisper_model):
        """WAV audio with RIFF header should be accepted."""
        from backend.services.stt_service import STTService

        mock_fw.return_value = mock_whisper_model
        svc = STTService(stt_config)
        await svc.start()

        result = await svc.transcribe(_make_wav())
        assert result.text.strip() != ""

    async def test_accept_mp3_format(self, mock_fw, stt_config, mock_whisper_model):
        """MP3 magic bytes (ID3 / 0xFFxFB) should pass validation."""
        from backend.services.stt_service import STTService

        mock_fw.return_value = mock_whisper_model
        svc = STTService(stt_config)
        await svc.start()

        mp3_data = b"ID3" + b"\x00" * 1024
        result = await svc.transcribe(mp3_data)
        assert result is not None

    async def test_accept_ogg_format(self, mock_fw, stt_config, mock_whisper_model):
        """OGG magic bytes should pass validation."""
        from backend.services.stt_service import STTService

        mock_fw.return_value = mock_whisper_model
        svc = STTService(stt_config)
        await svc.start()

        ogg_data = b"OggS" + b"\x00" * 1024
        result = await svc.transcribe(ogg_data)
        assert result is not None

    async def test_accept_flac_format(self, mock_fw, stt_config, mock_whisper_model):
        """FLAC magic bytes should pass validation."""
        from backend.services.stt_service import STTService

        mock_fw.return_value = mock_whisper_model
        svc = STTService(stt_config)
        await svc.start()

        flac_data = b"fLaC" + b"\x00" * 1024
        result = await svc.transcribe(flac_data)
        assert result is not None

    async def test_reject_wav_exceeding_duration(self, stt_config):
        """WAV longer than max_audio_duration_s should be rejected."""
        from backend.services.stt_service import STTService

        svc = STTService(stt_config)
        # Build a WAV header claiming a very long duration
        wav = _make_wav(duration_s=stt_config.max_audio_duration_s + 10)

        with pytest.raises(ValueError, match="[Dd]uration"):
            await svc.transcribe(wav)
