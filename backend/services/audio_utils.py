"""O.M.N.I.A. — Audio utility functions for voice services.

Provides audio buffer validation, format detection, temporary file management
with auto-deletion, and PCM/WAV conversion helpers.  No audio data is ever
persisted — only the resulting transcript enters chat history.
"""

from __future__ import annotations

import asyncio
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_AUDIO_DURATION_S: int = 300  # 5 minutes
MAX_AUDIO_SIZE_BYTES: int = 20 * 1024 * 1024  # 20 MB (5 min @ 16kHz 16-bit mono ≈ 9.6 MB)
TEMP_FILE_TTL_S: int = 60  # Auto-delete after 60 seconds

SUPPORTED_FORMATS: dict[str, list[bytes]] = {
    "wav": [b"RIFF"],
    "mp3": [b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"ID3"],
    "ogg": [b"OggS"],
    "flac": [b"fLaC"],
}

AudioFormat = Literal["wav", "mp3", "ogg", "flac", "unknown"]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AudioValidation:
    """Result of an audio buffer validation check."""

    valid: bool
    format: AudioFormat
    error: str | None = None


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def detect_audio_format(data: bytes) -> AudioFormat:
    """Detect audio format from magic bytes.

    Args:
        data: Raw audio bytes (at least the first 4 bytes are inspected).

    Returns:
        Detected format name, or ``"unknown"`` if no signature matched.
    """
    for fmt, signatures in SUPPORTED_FORMATS.items():
        for sig in signatures:
            if data[: len(sig)] == sig:
                return fmt  # type: ignore[return-value]
    return "unknown"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_audio_buffer(data: bytes) -> AudioValidation:
    """Validate an audio buffer against size, format, and duration limits.

    Checks performed (in order):
    1. Non-empty buffer.
    2. Buffer size ≤ ``MAX_AUDIO_SIZE_BYTES``.
    3. Magic-byte format detection (must be a supported format).
    4. For WAV files, header-based duration ≤ ``MAX_AUDIO_DURATION_S``.

    Args:
        data: Raw audio bytes to validate.

    Returns:
        An :class:`AudioValidation` with the outcome.

    Raises:
        ValueError: On any validation failure.
    """
    if not data:
        raise ValueError("Empty audio data")

    if len(data) > MAX_AUDIO_SIZE_BYTES:
        raise ValueError(
            f"Audio size {len(data)} bytes exceeds limit of {MAX_AUDIO_SIZE_BYTES} bytes"
        )

    fmt = detect_audio_format(data)
    if fmt == "unknown":
        raise ValueError("Unsupported audio format — expected WAV, MP3, OGG, or FLAC")

    if fmt == "wav":
        duration = estimate_audio_duration_s(data)
        if duration > MAX_AUDIO_DURATION_S:
            raise ValueError(
                f"Audio duration {duration:.1f}s exceeds limit of {MAX_AUDIO_DURATION_S}s"
            )

    return AudioValidation(valid=True, format=fmt)


# ---------------------------------------------------------------------------
# Duration estimation
# ---------------------------------------------------------------------------


def _find_data_chunk(audio_data: bytes) -> tuple[int, int]:
    """Find the ``data`` chunk in a WAV file.

    Walks the RIFF chunk list starting after the 12-byte RIFF header
    to locate the ``data`` sub-chunk, handling non-standard chunks
    (LIST, INFO, etc.) that may appear before it.

    Args:
        audio_data: Raw WAV bytes (must start with ``RIFF``).

    Returns:
        ``(data_offset, data_size)`` — byte offset of the PCM payload
        and its declared size.

    Raises:
        ValueError: If no ``data`` chunk is found.
    """
    pos = 12  # skip RIFF header (4 'RIFF' + 4 filesize + 4 'WAVE')
    while pos + 8 <= len(audio_data):
        chunk_id = audio_data[pos:pos + 4]
        chunk_size = struct.unpack_from("<I", audio_data, pos + 4)[0]
        if chunk_id == b"data":
            return pos + 8, chunk_size
        pos += 8 + chunk_size
        # WAV chunks are word-aligned
        if chunk_size % 2 != 0:
            pos += 1
    raise ValueError("No 'data' chunk found in WAV file")


def estimate_audio_duration_s(data: bytes, sample_rate: int = 16000) -> float:
    """Estimate audio duration in seconds.

    For WAV files the header is parsed (byte-rate from ``fmt`` chunk +
    data size from the ``data`` chunk, which is located by scanning
    rather than assuming a fixed offset).
    For other formats a rough estimate is derived from *sample_rate* and
    16-bit mono assumptions.

    Args:
        data: Raw audio bytes.
        sample_rate: Fallback sample rate used for non-WAV estimation.

    Returns:
        Estimated duration in seconds (``0.0`` on parse failure).

    Raises:
        ValueError: If a WAV file has an invalid byte_rate (≤ 0).
    """
    if len(data) >= 44 and data[:4] == b"RIFF":
        try:
            byte_rate = struct.unpack_from("<I", data, 28)[0]
            if byte_rate <= 0:
                raise ValueError("Invalid WAV: byte_rate must be > 0")
            _, data_size = _find_data_chunk(data)
            return data_size / byte_rate
        except ValueError:
            raise
        except (struct.error, Exception):
            logger.warning("Failed to parse WAV header for duration estimation")
            return 0.0

    # Fallback: assume 16-bit mono PCM
    bytes_per_sample = 2
    return len(data) / (sample_rate * bytes_per_sample)


# ---------------------------------------------------------------------------
# Temporary file management
# ---------------------------------------------------------------------------


def _sync_delete(path: Path) -> None:
    """Synchronously delete a temp file (callback for ``call_later``)."""
    try:
        path.unlink(missing_ok=True)
        logger.debug("Deleted temp audio file: {}", path)
    except OSError as exc:
        logger.warning("Failed to delete temp audio file {}: {}", path, exc)


async def save_temp_audio(data: bytes, suffix: str = ".wav") -> Path:
    """Save audio data to a temporary file and schedule auto-deletion.

    The file is created in the system temp directory and will be
    automatically removed after ``TEMP_FILE_TTL_S`` seconds.

    Args:
        data: Raw audio bytes to persist.
        suffix: File extension (e.g. ``".wav"``).

    Returns:
        :class:`Path` to the newly created temp file.
    """
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, prefix="omnia_audio_"
    )
    tmp_path = Path(tmp.name)
    try:
        tmp.write(data)
    finally:
        tmp.close()

    logger.debug("Saved temp audio file: {} ({} bytes)", tmp_path, len(data))

    loop = asyncio.get_running_loop()
    loop.call_later(TEMP_FILE_TTL_S, lambda: _sync_delete(tmp_path))

    return tmp_path


async def cleanup_temp_file(path: Path) -> None:
    """Delete a temporary audio file immediately if it still exists.

    Args:
        path: Path to the temp file.
    """
    try:
        path.unlink(missing_ok=True)
        logger.debug("Cleaned up temp audio file: {}", path)
    except OSError as exc:
        logger.warning("Failed to clean up temp audio file {}: {}", path, exc)


# ---------------------------------------------------------------------------
# PCM / WAV conversion helpers
# ---------------------------------------------------------------------------


def wav_header(
    data_size: int,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Generate a 44-byte WAV (RIFF) file header.

    Args:
        data_size: Size of the raw PCM data in bytes.
        sample_rate: Samples per second (default 16 kHz).
        channels: Number of audio channels (default mono).
        sample_width: Bytes per sample (default 2 → 16-bit).

    Returns:
        44-byte WAV header ready to prepend to PCM data.
    """
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    bits_per_sample = sample_width * 8
    file_size = 36 + data_size  # total file size minus 8

    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        file_size,
        b"WAVE",
        b"fmt ",
        16,  # PCM fmt chunk size
        1,  # PCM format tag
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )


def pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Convert raw PCM audio data to a complete WAV file.

    Args:
        pcm_data: Raw PCM samples.
        sample_rate: Samples per second (default 16 kHz).
        channels: Number of audio channels (default mono).
        sample_width: Bytes per sample (default 2 → 16-bit).

    Returns:
        Bytes containing a valid WAV file (header + PCM payload).
    """
    header = wav_header(len(pcm_data), sample_rate, channels, sample_width)
    return header + pcm_data
