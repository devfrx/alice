"""AL\\CE — Text-to-Speech service.

Supports **Piper TTS** (CPU-only, low RAM) as primary engine,
**XTTS v2** (GPU, voice-cloning) and **Kokoro** (ONNX, CPU-friendly,
high-quality) as optional alternatives.  Both engines
run blocking synthesis in a thread pool to keep the async loop free.
Audio is returned as WAV-formatted audio bytes at the configured
sample rate.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import sys
import tempfile
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING


def _resolve_resource_root() -> Path:
    """Return the directory that holds bundled ``models/`` and other data.

    In a PyInstaller --onedir build ``__file__`` lives inside ``_internal/``
    and walking three parents up lands in ``_internal/`` itself, **not** in
    the directory next to ``backend.exe`` where ``build-installer.ps1``
    actually stages ``models/``.  Use ``sys.executable`` in frozen mode so
    paths line up with the installer layout; in dev mode keep the original
    ``services/`` ↑ ``backend/`` ↑ ``alice/`` resolution.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent

from loguru import logger

if TYPE_CHECKING:
    from backend.core.config import TTSConfig

# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Ý\"'(])")
_CLAUSE_RE = re.compile(r"(?<=[,;:—–])\s+")

# Piper truncates phoneme sequences at 510 and then has an off-by-one crash
# when the slice boundary lands exactly on index 510.  Keeping each chunk
# well below ~250 chars (≈ 400 Italian phonemes) avoids the issue entirely.
_MAX_CHUNK_CHARS = 220


def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentence-like chunks for incremental synthesis.

    First splits on sentence-ending punctuation, then subdivides any
    remaining chunk that exceeds ``_MAX_CHUNK_CHARS`` on clause boundaries
    (comma, semicolon, colon, em-dash) to prevent Piper's phoneme-length
    crash.
    """
    if not text or not text.strip():
        return []
    raw = _SENTENCE_RE.split(text.strip())
    sentences = [p.strip() for p in raw if p.strip()]

    result: list[str] = []
    for sentence in sentences:
        if len(sentence) <= _MAX_CHUNK_CHARS:
            result.append(sentence)
            continue
        # Secondary split on clause boundaries.
        clauses = [c.strip() for c in _CLAUSE_RE.split(sentence) if c.strip()]
        current = ""
        for clause in clauses:
            candidate = f"{current}, {clause}" if current else clause
            if len(candidate) <= _MAX_CHUNK_CHARS:
                current = candidate
            else:
                if current:
                    result.append(current)
                # If a single clause is still too long, hard-split by words.
                if len(clause) > _MAX_CHUNK_CHARS:
                    words = clause.split()
                    buf = ""
                    for word in words:
                        addition = f"{buf} {word}" if buf else word
                        if len(addition) <= _MAX_CHUNK_CHARS:
                            buf = addition
                        else:
                            if buf:
                                result.append(buf)
                            buf = word
                    if buf:
                        current = buf
                else:
                    current = clause
        if current:
            result.append(current)

    return result


# ---------------------------------------------------------------------------
# Markdown / formatting cleanup for TTS
# ---------------------------------------------------------------------------

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_FENCED_CODE_RE = re.compile(r"```[^\n]*\n[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BOLD3_RE = re.compile(r"\*{3}(.+?)\*{3}|_{3}(.+?)_{3}")
_BOLD_RE = re.compile(r"\*{2}(.+?)\*{2}|_{2}(.+?)_{2}")
_ITALIC_RE = re.compile(r"(?<!\w)\*(.+?)\*(?!\w)|(?<!\w)_(.+?)_(?!\w)")
_HR_RE = re.compile(r"^[ \t]*([\-*_])\1{2,}[ \t]*$", re.MULTILINE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{2,}")
_SINGLE_NEWLINE_RE = re.compile(r"\n")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
# Matches any bullet (- * +) or numbered (1.) list item line
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$")
_PUNCT_DUP_RE = re.compile(r"([.!?])\s*\.\s*")
_COMMA_PERIOD_RE = re.compile(r",\s*\.")
_PERIOD_COMMA_RE = re.compile(r"\.\s*,")
# Table separator rows: |------|------| or | :---: | etc.
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:?\-|]+\|\s*$", re.MULTILINE)
# Any table row: | cell | cell | ... |
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")


def _normalize_for_tts(text: str) -> str:
    """Strip markdown and convert structure to natural TTS-friendly prose.

    List bullets and numbered items are converted to capitalized sentences
    with terminal punctuation so that :func:`_split_sentences` can insert
    natural pauses between them.  Paragraph breaks become sentence
    boundaries; inline line-feeds become spaces.
    """
    t = text

    # Remove non-speakable elements
    t = _IMAGE_RE.sub("", t)        # ![alt](url) → remove
    t = _FENCED_CODE_RE.sub("", t)  # ```code``` → remove (not speakable)
    t = _HTML_TAG_RE.sub("", t)     # <tag> → remove
    t = _HR_RE.sub("\n\n", t)       # horizontal rule → paragraph break

    # Convert markdown tables to natural prose.
    # Header row cells become labels paired with each data row's values.
    t = _TABLE_SEP_RE.sub("", t)      # remove separator rows first
    table_lines: list[str] = []
    other_lines: list[str] = []
    headers: list[str] | None = None
    for line in t.split("\n"):
        row_m = _TABLE_ROW_RE.match(line)
        if row_m:
            cells = [c.strip() for c in row_m.group(1).split("|")]
            cells = [c for c in cells if c]
            if headers is None:
                headers = cells
            else:
                # Pair each header with the corresponding data cell
                parts = []
                for i, cell in enumerate(cells):
                    label = headers[i] if i < len(headers) else ""
                    if label and cell:
                        parts.append(f"{label} {cell}")
                    elif cell:
                        parts.append(cell)
                if parts:
                    sentence = ", ".join(parts)
                    if sentence[-1] not in ".!?":
                        sentence += "."
                    table_lines.append(sentence)
        else:
            # Flush accumulated table rows when we leave a table
            if headers is not None:
                other_lines.extend(table_lines)
                table_lines = []
                headers = None
            other_lines.append(line)
    # Flush any remaining table at end of text
    if headers is not None:
        other_lines.extend(table_lines)
    t = "\n".join(other_lines)

    # Preserve readable text from markdown decorators
    t = _LINK_RE.sub(r"\1", t)             # [text](url) → text
    t = _INLINE_CODE_RE.sub(r"\1", t)      # `code` → code
    t = _HEADING_RE.sub("", t)             # ## Heading → Heading (newlines kept)
    t = _BOLD3_RE.sub(lambda m: m.group(1) or m.group(2), t)
    t = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2), t)
    t = _ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), t)

    # Convert list items to prose sentences.
    # Each item is capitalised and given terminal punctuation so that
    # _split_sentences() creates a natural pause between every item.
    lines = t.split("\n")
    out: list[str] = []
    for line in lines:
        m = _LIST_ITEM_RE.match(line)
        if m:
            item = m.group(1).strip()
            if not item:
                continue
            # Capitalise first character for sentence-boundary detection
            item = item[0].upper() + item[1:]
            # Ensure every item ends with terminal punctuation
            if item[-1] not in ".!?":
                item += "."
            out.append(item)
        else:
            out.append(line)
    t = "\n".join(out)

    # Paragraph breaks → sentence pause so _split_sentences fires correctly
    t = _MULTI_NEWLINE_RE.sub(". ", t)
    # Remaining single newlines (line continuations) → space
    t = _SINGLE_NEWLINE_RE.sub(" ", t)

    # Remove punctuation artifacts introduced by the substitutions above
    t = _PUNCT_DUP_RE.sub(r"\1 ", t)  # ". ." / ".." → ". "
    t = _COMMA_PERIOD_RE.sub(".", t)   # ",." → "."
    t = _PERIOD_COMMA_RE.sub(".", t)   # ".," → "."

    t = _MULTI_SPACE_RE.sub(" ", t)
    return t.strip()


# ---------------------------------------------------------------------------
# Piper engine (lazy import)
# ---------------------------------------------------------------------------


class _PiperEngine:
    """Thin wrapper around ``piper.PiperVoice``."""

    def __init__(self, voice: str, sample_rate: int, speed: float = 1.0) -> None:
        from piper import PiperVoice  # lazy
        from piper.config import SynthesisConfig  # lazy

        self._sample_rate = sample_rate
        self._syn_config = SynthesisConfig(
            length_scale=1.0 / speed if speed > 0 else 1.0,
        )

        # Resolve relative to the runtime resource root (handles both dev
        # and PyInstaller --onedir layouts).
        project_root = _resolve_resource_root()
        model_path = voice if voice.endswith(".onnx") else f"{voice}.onnx"
        model_path_obj = Path(model_path)
        if not model_path_obj.is_absolute():
            model_path_obj = project_root / model_path_obj
        model_path = str(model_path_obj)

        logger.info("Loading Piper voice: {}", model_path)
        self._voice = PiperVoice.load(model_path)

    def synthesize(self, text: str) -> bytes:
        """Synthesize *text* and return WAV-formatted audio bytes (blocking)."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            for chunk in self._voice.synthesize(text, syn_config=self._syn_config):
                wf.writeframes(chunk.audio_int16_bytes)
        return buf.getvalue()

    def close(self) -> None:
        """Release resources."""
        self._voice = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# XTTS v2 engine (lazy import)
# ---------------------------------------------------------------------------


class _XTTSEngine:
    """Thin wrapper around ``TTS`` (Coqui TTS) for XTTS v2."""

    def __init__(
        self, model: str, speaker_wav: str, language: str,
        speed: float = 1.0,
    ) -> None:
        from TTS.api import TTS  # lazy

        logger.info("Loading XTTS model: {}", model)
        self._tts = TTS(model_name=model, gpu=True)
        self._speaker_wav = speaker_wav
        self._language = language
        self._speed = speed

        if not speaker_wav or not Path(speaker_wav).is_file():
            logger.warning("XTTS speaker_wav not found or empty: {}", speaker_wav)

    def synthesize(self, text: str) -> bytes:
        """Synthesize *text* and return WAV bytes (blocking)."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            self._tts.tts_to_file(
                text=text,
                speaker_wav=self._speaker_wav,
                language=self._language,
                file_path=tmp_path,
                speed=self._speed,
            )
            return Path(tmp_path).read_bytes()
        finally:
            os.unlink(tmp_path)

    def close(self) -> None:
        """Release GPU resources."""
        self._tts = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Kokoro engine (lazy import, ONNX-based)
# ---------------------------------------------------------------------------


class _KokoroEngine:
    """Wrapper around ``kokoro_onnx.Kokoro`` for high-quality TTS."""

    def __init__(
        self, model_path: str, voices_path: str, voice: str,
        language: str, speed: float = 1.0,
    ) -> None:
        import kokoro_onnx  # lazy

        # Resolve relative paths against the runtime resource root
        # (PyInstaller-aware via _resolve_resource_root).
        project_root = _resolve_resource_root()
        model_resolved = Path(model_path)
        voices_resolved = Path(voices_path)
        if not model_resolved.is_absolute():
            model_resolved = project_root / model_resolved
        if not voices_resolved.is_absolute():
            voices_resolved = project_root / voices_resolved

        logger.info("Loading Kokoro model: {}", model_resolved)
        self._kokoro = kokoro_onnx.Kokoro(
            str(model_resolved), str(voices_resolved),
        )
        self._voice = voice
        self._language = language
        self._speed = speed
        self._sample_rate = 24000  # Kokoro outputs 24kHz

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def synthesize(self, text: str) -> bytes:
        """Synthesize *text* and return WAV-formatted audio bytes (blocking)."""
        import soundfile as sf

        samples, sr = self._kokoro.create(
            text, voice=self._voice, speed=self._speed, lang=self._language,
        )
        buf = io.BytesIO()
        sf.write(buf, samples, sr, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return buf.getvalue()

    def close(self) -> None:
        """Release resources."""
        self._kokoro = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


class TTSService:
    """High-level TTS service with async interface and streaming support.

    Implements the ``TTSServiceProtocol`` expected by ``AppContext``.

    Args:
        config: ``TTSConfig`` from the application configuration.
    """

    def __init__(self, config: TTSConfig) -> None:
        self._config = config
        self._engine: _PiperEngine | _XTTSEngine | _KokoroEngine | None = None
        self._started = False
        self._synth_lock = asyncio.Lock()

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Initialise the selected TTS engine in a background thread.

        All ``ImportError`` cases (missing optional library) are handled
        gracefully: a WARNING is logged and TTS stays disabled.  Only true
        unexpected errors produce an ERROR-level log with traceback.
        """
        if self._started:
            return
        engine = self._config.engine
        logger.info("Starting TTS service (engine={})", engine)
        try:
            if engine == "xtts":
                try:
                    self._engine = await asyncio.to_thread(
                        _XTTSEngine,
                        self._config.xtts_model,
                        self._config.xtts_speaker_wav,
                        self._config.xtts_language,
                        self._config.speed,
                    )
                    self._started = True
                except ImportError as exc:
                    logger.warning(
                        "XTTS not available ({}): falling back to Piper", exc,
                    )
                    self._started = await self._try_start_piper()
                except Exception as exc:
                    logger.warning(
                        "XTTS failed to load ({}): falling back to Piper", exc,
                    )
                    self._started = await self._try_start_piper()

            elif engine == "kokoro":
                try:
                    self._engine = await asyncio.to_thread(
                        _KokoroEngine,
                        self._config.kokoro_model,
                        self._config.kokoro_voices,
                        self._config.kokoro_voice,
                        self._config.kokoro_language,
                        self._config.speed,
                    )
                    self._started = True
                except ImportError as exc:
                    logger.warning(
                        "Kokoro not available ({}): falling back to Piper", exc,
                    )
                    self._started = await self._try_start_piper()
                except Exception as exc:
                    logger.warning(
                        "Kokoro failed to load ({}): falling back to Piper", exc,
                    )
                    self._started = await self._try_start_piper()

            else:  # piper (primary)
                self._started = await self._try_start_piper()

            if self._started:
                logger.info("TTS service ready (engine={})", engine)
            else:
                logger.warning(
                    "TTS service unavailable — engine '{}' and all fallbacks "
                    "could not be loaded (install the matching extras: "
                    "tts-piper / tts-kokoro / voice)",
                    engine,
                )
        except Exception:
            logger.exception("Unexpected error starting TTS engine '{}'", engine)

    async def _try_start_piper(self) -> bool:
        """Attempt to load the Piper engine using the configured voice.

        Returns:
            ``True`` on success, ``False`` if the library is missing or the
            model file cannot be loaded (logged at WARNING, not ERROR).
        """
        try:
            self._engine = await asyncio.to_thread(
                _PiperEngine,
                self._config.voice,
                self._config.sample_rate,
                self._config.speed,
            )
            logger.info("Piper TTS engine loaded")
            return True
        except ImportError as exc:
            logger.warning(
                "Piper not available ({}): TTS disabled. "
                "Install with: uv sync --extra tts-piper",
                exc,
            )
            return False
        except Exception as exc:
            logger.warning("Piper failed to load ({}): TTS disabled", exc)
            return False

    async def stop(self) -> None:
        """Shut down the engine and free resources."""
        if self._engine is not None:
            await asyncio.to_thread(self._engine.close)
            self._engine = None
        self._started = False
        logger.info("TTS service stopped")

    async def health_check(self) -> bool:
        """Return ``True`` when an engine is loaded and ready."""
        return self._started and self._engine is not None

    # -- synthesis ----------------------------------------------------------

    async def synthesize(self, text: str) -> bytes:
        """Convert *text* to a complete WAV audio buffer.

        Args:
            text: The text to synthesize.

        Returns:
            WAV-formatted audio bytes.

        Raises:
            RuntimeError: If the service has not been started.
            ValueError: If *text* is empty or blank.
        """
        if not text or not text.strip():
            raise ValueError("Text must not be empty or blank")
        engine = self._engine
        if engine is None:
            raise RuntimeError("TTS engine not initialised — call start()")
        clean = _normalize_for_tts(text)
        if not clean:
            raise ValueError("Text must not be empty or blank")
        logger.debug("[TTS] synthesize → {!r}", clean)
        async with self._synth_lock:
            return await asyncio.to_thread(engine.synthesize, clean)

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield WAV audio chunks sentence-by-sentence.

        Splits *text* into sentences and synthesizes each independently,
        yielding results as soon as each sentence is ready.  This reduces
        time-to-first-audio compared to synthesizing the full text at once.

        Args:
            text: The text to synthesize.

        Yields:
            WAV-formatted audio bytes for each sentence.

        Raises:
            RuntimeError: If the service has not been started.
        """
        engine = self._engine
        if engine is None:
            raise RuntimeError("TTS engine not initialised — call start()")
        clean = _normalize_for_tts(text)
        sentences = _split_sentences(clean)
        if not sentences:
            return
        logger.debug("[TTS] stream → {} chunk(s): {!r}", len(sentences), clean)
        for i, sentence in enumerate(sentences, 1):
            logger.debug("[TTS]   chunk {}/{}: {!r}", i, len(sentences), sentence)
            async with self._synth_lock:
                chunk = await asyncio.to_thread(engine.synthesize, sentence)
            yield chunk

    # -- properties ---------------------------------------------------------

    @property
    def engine(self) -> str:
        """TTS engine identifier (e.g. ``'piper'``, ``'xtts'``)."""
        return self._config.engine

    @property
    def voice_name(self) -> str:
        """Human-readable voice name for the active engine."""
        engine = self._config.engine
        if engine == "kokoro":
            return self._config.kokoro_voice
        if engine == "xtts":
            return "xtts-clone"
        # Piper: extract name from path like "models/tts/it_IT-paola-medium"
        segment = self._config.voice.rsplit("/", 1)[-1].split(".")[0]
        parts = segment.split("-")
        if len(parts) >= 3:
            return "-".join(parts[1:-1])
        return segment

    @property
    def sample_rate(self) -> int:
        """Configured audio sample rate in Hz."""
        if isinstance(self._engine, _KokoroEngine):
            return self._engine.sample_rate
        return self._config.sample_rate
