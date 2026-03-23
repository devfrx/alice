"""AL\\CE — Tests for TTS service (Phase 4)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from backend.core.config import TTSConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeChunk:
    """Mimics ``piper.voice.AudioChunk`` with just the bytes we need."""
    def __init__(self, data: bytes) -> None:
        self.audio_int16_bytes = data


def _mock_piper_module() -> MagicMock:
    """Build a mock ``piper`` module whose ``PiperVoice.load()`` returns a
    voice that yields ``_FakeChunk`` objects (matching the current Piper API)."""
    mod = MagicMock()
    voice = MagicMock()
    voice.synthesize.return_value = [_FakeChunk(b"\x00" * 2000)]
    mod.PiperVoice.load.return_value = voice
    # Ensure `from piper.config import SynthesisConfig` resolves
    mod.config.SynthesisConfig = MagicMock
    return mod


def _mock_xtts_modules() -> tuple[MagicMock, MagicMock]:
    """Build mock ``TTS`` / ``TTS.api`` modules so that
    ``from TTS.api import TTS`` resolves to a MagicMock class.

    Returns ``(parent_module, api_module)``.
    """
    api_mod = MagicMock()
    parent_mod = MagicMock(api=api_mod)
    return parent_mod, api_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tts_config() -> TTSConfig:
    return TTSConfig(enabled=True, engine="piper")


@pytest.fixture
def xtts_config() -> TTSConfig:
    return TTSConfig(enabled=True, engine="xtts", xtts_speaker_wav="fake.wav")


def _build_service(cfg: TTSConfig):
    """Instantiate TTSService."""
    from backend.services.tts_service import TTSService

    return TTSService(cfg)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestTTSServiceLifecycle:
    async def test_start_initializes_engine(self, tts_config: TTSConfig):
        """Starting should initialize the Piper engine."""
        piper = _mock_piper_module()
        with patch.dict(sys.modules, {"piper": piper, "piper.config": piper.config}):
            svc = _build_service(tts_config)
            await svc.start()
            assert await svc.health_check() is True
            piper.PiperVoice.load.assert_called_once()

    async def test_stop_cleans_up(self, tts_config: TTSConfig):
        """Stopping should release engine resources."""
        piper = _mock_piper_module()
        with patch.dict(sys.modules, {"piper": piper, "piper.config": piper.config, "piper.config": piper.config}):
            svc = _build_service(tts_config)
            await svc.start()
            await svc.stop()
            assert await svc.health_check() is False

    async def test_health_check_true(self, tts_config: TTSConfig):
        """health_check True when engine loaded."""
        piper = _mock_piper_module()
        with patch.dict(sys.modules, {"piper": piper, "piper.config": piper.config, "piper.config": piper.config}):
            svc = _build_service(tts_config)
            await svc.start()
            assert await svc.health_check() is True

    async def test_health_check_false(self, tts_config: TTSConfig):
        """health_check False when engine not loaded."""
        svc = _build_service(tts_config)
        assert await svc.health_check() is False


# ---------------------------------------------------------------------------
# Synthesize
# ---------------------------------------------------------------------------


class TestTTSSynthesize:
    async def test_synthesize_returns_wav_bytes(self, tts_config: TTSConfig):
        """synthesize() should return valid WAV bytes."""
        piper = _mock_piper_module()
        with patch.dict(sys.modules, {"piper": piper, "piper.config": piper.config}):
            svc = _build_service(tts_config)
            await svc.start()
            result = await svc.synthesize("Ciao mondo")
            assert isinstance(result, bytes)
            assert result[:4] == b"RIFF"
            assert len(result) > 44  # WAV header = 44 bytes

    async def test_synthesize_empty_text_raises(self, tts_config: TTSConfig):
        """Empty text should raise ValueError."""
        piper = _mock_piper_module()
        with patch.dict(sys.modules, {"piper": piper, "piper.config": piper.config}):
            svc = _build_service(tts_config)
            await svc.start()
            with pytest.raises(ValueError, match="(?i)empty"):
                await svc.synthesize("")

    async def test_synthesize_blank_text_raises(self, tts_config: TTSConfig):
        """Whitespace-only text should raise ValueError."""
        piper = _mock_piper_module()
        with patch.dict(sys.modules, {"piper": piper, "piper.config": piper.config}):
            svc = _build_service(tts_config)
            await svc.start()
            with pytest.raises(ValueError, match="(?i)empty"):
                await svc.synthesize("   ")

    async def test_synthesize_not_started_raises(self, tts_config: TTSConfig):
        """Synthesize without start() should raise RuntimeError."""
        svc = _build_service(tts_config)
        with pytest.raises(RuntimeError, match="(?i)not initialised"):
            await svc.synthesize("Ciao")

    async def test_sample_rate_property(self, tts_config: TTSConfig):
        """sample_rate should match config."""
        svc = _build_service(tts_config)
        assert svc.sample_rate == tts_config.sample_rate


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------


class TestTTSStream:
    async def test_stream_yields_chunks(self, tts_config: TTSConfig):
        """synthesize_stream should yield audio chunks."""
        piper = _mock_piper_module()
        with patch.dict(sys.modules, {"piper": piper, "piper.config": piper.config}):
            svc = _build_service(tts_config)
            await svc.start()
            chunks: list[bytes] = []
            async for c in svc.synthesize_stream("Ciao mondo"):
                chunks.append(c)
            assert len(chunks) >= 1
            assert all(isinstance(c, bytes) for c in chunks)

    async def test_stream_splits_sentences(self, tts_config: TTSConfig):
        """Long text should be split into sentence chunks."""
        piper = _mock_piper_module()
        with patch.dict(sys.modules, {"piper": piper, "piper.config": piper.config}):
            svc = _build_service(tts_config)
            await svc.start()
            # Sentences must start with uppercase to match the improved splitter
            text = "Prima frase. Seconda frase. Terza frase."
            chunks: list[bytes] = []
            async for c in svc.synthesize_stream(text):
                chunks.append(c)
            assert len(chunks) >= 3

    async def test_stream_not_started_raises(self, tts_config: TTSConfig):
        """Stream without start() should raise RuntimeError."""
        svc = _build_service(tts_config)
        with pytest.raises(RuntimeError, match="(?i)not initialised"):
            async for _ in svc.synthesize_stream("Ciao"):
                pass


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------


class TestTTSEngineSelection:
    async def test_piper_engine_selected(self, tts_config: TTSConfig):
        """Config engine=piper should invoke PiperVoice.load()."""
        piper = _mock_piper_module()
        with patch.dict(sys.modules, {"piper": piper, "piper.config": piper.config}):
            svc = _build_service(tts_config)
            await svc.start()
            piper.PiperVoice.load.assert_called_once()

    async def test_xtts_engine_selected(self, xtts_config: TTSConfig):
        """Config engine=xtts should instantiate TTS class."""
        parent, api = _mock_xtts_modules()
        with patch.dict(sys.modules, {"TTS": parent, "TTS.api": api}):
            svc = _build_service(xtts_config)
            await svc.start()
            api.TTS.assert_called_once()
            assert await svc.health_check() is True
