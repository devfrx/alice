"""AL\\CE — Speech-to-Text service (faster-whisper + Silero VAD).

Lazy-loads the Whisper model on first transcription (or explicit ``start()``)
to avoid VRAM allocation at startup.  Audio is validated for size, duration,
and format via magic-byte checks before processing.
"""

from __future__ import annotations

import asyncio
import math
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from backend.core.config import STTConfig
from backend.services.audio_utils import (
    _find_data_chunk,
    validate_audio_buffer,
)

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TRANSCRIPTION_TIMEOUT_S: float = 120.0  # fallback when duration unknown
MIN_TRANSCRIPTION_TIMEOUT_S: float = 30.0  # minimum timeout

# Backward-compatible alias (referenced by tests)
TRANSCRIPTION_TIMEOUT_S: float = DEFAULT_TRANSCRIPTION_TIMEOUT_S


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """A single timed segment inside a transcription."""

    start: float
    end: float
    text: str
    confidence: float


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    """Full transcription output returned by :meth:`STTService.transcribe`."""

    text: str
    language: str
    confidence: float
    duration_s: float
    segments: list[TranscriptSegment] | None = field(default=None)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class STTService:
    """Speech-to-Text service backed by *faster-whisper* with Silero VAD.

    The heavy model is loaded lazily — either on the first call to
    :meth:`transcribe` or via an explicit :meth:`start`.

    Args:
        config: STT configuration section from AL\\CE settings.
    """

    def __init__(self, config: STTConfig) -> None:
        self._config = config
        self._model: WhisperModel | None = None
        self._lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._dll_handles: list[object] = []  # prevent GC of os.add_dll_directory()

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Pre-load the Whisper model (optional — lazy load also works)."""
        await self._load_model()

    async def stop(self) -> None:
        """Unload model and free VRAM."""
        await self._unload_model()

    async def health_check(self) -> bool:
        """Return ``True`` when the model is loaded and usable."""
        return self._model is not None

    @property
    def engine(self) -> str:
        """STT engine identifier (e.g. ``'faster-whisper'``)."""
        return self._config.engine

    @property
    def model_name(self) -> str:
        """STT model name (e.g. ``'small'``, ``'large-v3'``)."""
        return self._config.model

    # -- public API ----------------------------------------------------------

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
    ) -> TranscriptResult:
        """Transcribe raw audio bytes into text.

        Args:
            audio_data: Audio file content (WAV, MP3, OGG, or FLAC).
            sample_rate: Hint for raw PCM; ignored when a container header
                is present.

        Returns:
            A :class:`TranscriptResult` with text, language, confidence,
            duration and optional per-segment detail.

        Raises:
            ValueError: If the audio fails validation checks.
            RuntimeError: If transcription fails.
        """
        self._validate_audio(audio_data)
        await self._load_model()

        # Proportional timeout based on audio duration
        timeout = self._compute_timeout(audio_data)

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = Path(tmp.name)
        try:
            tmp.write(audio_data)
            tmp.close()

            logger.debug(
                "Transcribing {} bytes of audio (sample_rate={})",
                len(audio_data), sample_rate,
            )
            result = await self._run_transcription(tmp_path, timeout)
        finally:
            tmp_path.unlink(missing_ok=True)

        return result

    # -- internals -----------------------------------------------------------

    def _compute_timeout(self, audio_data: bytes) -> float:
        """Calculate a proportional transcription timeout from audio duration.

        Uses ``duration * 1.5`` with a minimum of 30 s and a fallback of
        120 s when the duration cannot be determined.  The result is also
        capped by ``TRANSCRIPTION_TIMEOUT_S`` so the module-level
        constant still acts as an absolute upper bound.
        """
        cap = TRANSCRIPTION_TIMEOUT_S
        try:
            _, data_size = _find_data_chunk(audio_data)
            sample_rate = 16000  # STT input is always 16 kHz
            duration_s = data_size / (sample_rate * 2)  # 16-bit mono
            return min(max(MIN_TRANSCRIPTION_TIMEOUT_S, duration_s * 1.5), cap)
        except Exception:
            return cap

    async def _load_model(self) -> None:
        """Lazy-load the faster-whisper model (thread-safe)."""
        if self._model is not None:
            return
        async with self._lock:
            if self._model is not None:
                return  # another coroutine loaded while we waited
            logger.info(
                "Loading STT model {} on {} ({})",
                self._config.model,
                self._config.device,
                self._config.compute_type,
            )
            try:
                self._model = await asyncio.to_thread(self._create_model)
                logger.info("STT model loaded")
            except ImportError as exc:
                logger.warning(
                    "STT engine unavailable — faster-whisper not installed ({})."
                    " Install with: uv sync --extra voice",
                    exc,
                )
                # Leave self._model = None; health_check() will return False.

    def _create_model(self) -> WhisperModel:
        """Instantiate the WhisperModel (runs in a worker thread)."""
        import os
        import sys

        # On Windows, CTranslate2 pip wheels are built with
        # CUDA_DYNAMIC_LOADING=ON so cuBLAS (and cuDNN if present) are
        # loaded lazily at runtime — only when actual GPU computation runs
        # (beam-search decoding), NOT at import or model-creation time.
        #
        # The ``nvidia-cublas-cu12`` (and ``nvidia-cudnn-cu12``) pip
        # packages ship the DLLs but they're not on the default search
        # path.  ``os.add_dll_directory()`` adds them, but returns a
        # handle object — per Python docs: "Remove the directory by
        # calling close() on the returned object."  If the handle is
        # garbage-collected the directory is silently removed.  We store
        # all handles in ``self._dll_handles`` so they live as long as
        # the STTService instance.
        if sys.platform == "win32":
            self._register_nvidia_dlls(os)

        from faster_whisper import WhisperModel

        return WhisperModel(
            self._config.model,
            device=self._config.device,
            compute_type=self._config.compute_type,
        )

    def _register_nvidia_dlls(self, os_module) -> None:
        """Register NVIDIA pip-package DLL dirs on Windows.

        CTranslate2 pip wheels are built with ``CUDA_DYNAMIC_LOADING=ON``,
        meaning cuBLAS (and cuDNN) are loaded lazily via ``LoadLibrary()``
        only when the GPU decoder actually runs — not at import or
        model-creation time.

        The ``nvidia-cublas-cu12`` / ``nvidia-cudnn-cu12`` pip packages
        ship the DLLs but they are not on the default DLL search path.
        We use **three** mechanisms for maximum reliability:

        1. ``os.add_dll_directory()`` — adds the dirs to the
           ``LOAD_LIBRARY_SEARCH_USER_DIRS`` set.  Handle stored in
           ``self._dll_handles`` to prevent GC.
        2. ``os.environ["PATH"]`` — legacy fallback for code that
           may use the old search order.
        3. ``ctypes.CDLL(full_path)`` — **pre-loads** every DLL into
           the process address space.  Once loaded, any subsequent
           ``LoadLibrary("cublas64_12.dll")`` from CTranslate2's C++
           code finds the DLL already resident in memory, regardless
           of search-path configuration.  This is the same pattern
           CTranslate2 itself uses for its own extension DLLs.
        """
        import ctypes
        import glob

        packages = [
            ("nvidia.cublas", "cuBLAS"),
            ("nvidia.cudnn", "cuDNN"),
        ]
        for module_name, label in packages:
            try:
                mod = __import__(module_name, fromlist=["__path__"])
                bin_dir = Path(mod.__path__[0]) / "bin"
                if not bin_dir.is_dir():
                    continue

                bin_str = str(bin_dir)

                # 1) AddDllDirectory (handle retained to prevent GC)
                handle = os_module.add_dll_directory(bin_str)
                self._dll_handles.append(handle)

                # 2) PATH (belt-and-suspenders for legacy search)
                current_path = os_module.environ.get("PATH", "")
                if bin_str not in current_path:
                    os_module.environ["PATH"] = (
                        bin_str + os_module.pathsep + current_path
                    )

                # 3) Pre-load every DLL so it's resident in memory
                for dll in glob.glob(str(bin_dir / "*.dll")):
                    try:
                        ctypes.CDLL(dll)
                        logger.debug("Pre-loaded {}: {}", label, Path(dll).name)
                    except OSError as exc:
                        logger.warning(
                            "Failed to pre-load {} ({}): {}",
                            Path(dll).name, label, exc,
                        )

                logger.debug("Registered {} DLLs from: {}", label, bin_dir)
            except ImportError:
                logger.debug("{} pip package not installed, skipping", label)

    async def _unload_model(self) -> None:
        """Delete the model object to free VRAM."""
        async with self._lock:
            self._clear_model()

    async def _invalidate_model(self) -> None:
        """Force-clear a corrupted model so the next call reloads it.

        Unlike ``_unload_model`` this does NOT acquire the lock, because
        it is called from error paths where the lock is not held and a
        deadlocked worker thread might be holding CUDA resources.
        """
        self._clear_model()

    def _clear_model(self) -> None:
        """Synchronously release the model reference."""
        if self._model is None:
            return
        logger.info("Releasing STT model reference")
        self._model = None

    async def _run_transcription(
        self,
        audio_path: Path,
        timeout: float = DEFAULT_TRANSCRIPTION_TIMEOUT_S,
    ) -> TranscriptResult:
        """Run faster-whisper transcription in a worker thread.

        Both ``model.transcribe()`` and segment iteration MUST happen
        in the same thread — the returned generator holds CUDA state
        that cannot be accessed from a different thread.

        Includes a proportional timeout to prevent infinite hangs from
        CUDA errors, and invalidates the model on RuntimeError so the
        next call triggers a fresh reload.
        """
        try:
            async with self._inference_lock:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._transcribe_sync, audio_path),
                    timeout=timeout,
                )
        except TimeoutError:
            logger.error(
                "STT transcription timed out after {:.0f}s — invalidating model",
                timeout,
            )
            await self._invalidate_model()
            raise RuntimeError(
                f"Transcription timed out after {timeout:.0f}s"
            )
        except RuntimeError as exc:
            logger.error(
                "STT RuntimeError during transcription: {} — invalidating model",
                exc,
            )
            await self._invalidate_model()
            raise

    def _transcribe_sync(self, audio_path: Path) -> TranscriptResult:
        """Synchronous transcription — runs entirely in one worker thread."""
        model = self._model
        if model is None:
            raise RuntimeError("STT model is not loaded")
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=self._config.language,
            vad_filter=self._config.vad_filter,
            vad_parameters={"threshold": self._config.vad_threshold},
        )
        # Consume the generator in the SAME thread to avoid CUDA errors.
        segments_list = list(segments_iter)
        logger.debug(
            "STT raw: {} segments, duration={:.1f}s, lang={}",
            len(segments_list), info.duration, info.language,
        )

        full_text = " ".join(seg.text.strip() for seg in segments_list)
        avg_confidence = (
            math.exp(
                sum(seg.avg_logprob for seg in segments_list) / len(segments_list)
            )
            if segments_list
            else 0.0
        )

        transcript_segments = [
            TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                confidence=math.exp(seg.avg_logprob),
            )
            for seg in segments_list
        ]

        return TranscriptResult(
            text=full_text,
            language=info.language,
            confidence=avg_confidence,
            duration_s=info.duration,
            segments=transcript_segments or None,
        )

    # -- validation ----------------------------------------------------------

    def _validate_audio(self, data: bytes) -> None:
        """Validate audio data before transcription.

        Delegates common checks (format, size, WAV duration) to
        :func:`~backend.services.audio_utils.validate_audio_buffer`,
        then applies STT-specific limits from ``self._config``.

        Raises:
            ValueError: On any validation failure.
        """
        # Common audio buffer validation (format, size, duration)
        validate_audio_buffer(data)

        # STT-specific: enforce per-config size limit (may be stricter)
        max_size = self._config.max_audio_size_mb * 1024 * 1024
        if len(data) > max_size:
            raise ValueError(
                f"Audio exceeds {self._config.max_audio_size_mb} MB limit"
            )

        # STT-specific: enforce per-config duration limit for WAV
        if data[:4] == b"RIFF" and len(data) >= 44:
            try:
                _, data_size = _find_data_chunk(data)
                sample_rate = 16000  # STT input is always 16 kHz
                duration = data_size / (sample_rate * 2)  # 16-bit mono
                if duration > self._config.max_audio_duration_s:
                    raise ValueError(
                        f"Audio duration {duration:.1f}s exceeds "
                        f"{self._config.max_audio_duration_s}s limit"
                    )
            except ValueError:
                raise
            except (struct.error, IndexError):
                logger.warning("Failed to parse WAV header for duration check")
