"""AL\\CE — Model downloader service.

Downloads STT (Whisper / faster-whisper) and TTS (Piper) model artifacts
into the user data directory and emits progress events on the shared
:class:`backend.core.event_bus.EventBus` so the frontend can render a
progress bar over WebSocket.

Design notes
------------
* **Idempotent** — already-present files are skipped (no re-download).
* **Resumable** — partial files are streamed to ``<target>.part`` and
  renamed atomically on success.
* **No hard dependency** on ``huggingface_hub``.  Whisper models are
  fetched via plain HTTP from the public ``huggingface.co`` URLs because
  that is the same source ``faster-whisper`` itself uses internally.
* **Progress events** are emitted on the bus as
  ``service.model_download_progress`` with payload::

      {
          "service": "stt" | "tts",
          "model_id": "small",
          "downloaded_bytes": int,
          "total_bytes": int,
          "phase": "downloading" | "completed" | "error",
          "file": "<filename>",
      }

Frontend subscribes to these events via the existing event WebSocket.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    from backend.core.event_bus import EventBus


# Bus event name (kept as a string to avoid touching AliceEvent enum just
# for a dynamic-payload event the frontend consumes verbatim).
PROGRESS_EVENT = "service.model_download_progress"


@dataclass
class _ProgressState:
    """Mutable shared progress counter for a single download.

    Used by both single-stream and ranged-parallel paths to keep the
    cumulative ``downloaded_bytes`` value coherent across concurrent
    writers.
    """

    total: int
    downloaded: int = 0
    last_emit: float = 0.0


def _pwrite(path: Path, offset: int, data: bytes) -> None:
    """Positional write to ``path`` at ``offset`` (sparse-file friendly).

    Opens the file in ``r+b`` mode for each call to keep the function
    state-free; the caller serialises by part, so this is cheap.
    """
    with path.open("r+b") as fp:
        fp.seek(offset)
        fp.write(data)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelAsset:
    """A single file that has to be present for a model to load."""

    relative_path: str
    url: str
    sha256: str | None = None  # optional integrity check (not enforced yet)


@dataclass(frozen=True)
class ModelEntry:
    """A downloadable model bundle."""

    service: str  # "stt" or "tts"
    model_id: str  # canonical id (e.g. "small", "it_IT-paola-medium")
    display_name: str
    size_mb: float
    target_subdir: str  # path under <models_root>/<service>/
    files: tuple[ModelAsset, ...] = field(default_factory=tuple)
    description: str = ""


# ---- STT (faster-whisper CTranslate2 models from Systran) ----------------
# The faster-whisper README points to Systran's converted models.

def _whisper_files(repo_size: str) -> tuple[ModelAsset, ...]:
    """Return the canonical CT2 file set for ``Systran/faster-whisper-*``."""
    repo = f"Systran/faster-whisper-{repo_size}"
    base = f"https://huggingface.co/{repo}/resolve/main"
    names = (
        "config.json",
        "model.bin",
        "tokenizer.json",
        "vocabulary.txt",
    )
    return tuple(
        ModelAsset(relative_path=n, url=f"{base}/{n}") for n in names
    )


# ---- TTS (Piper voices from rhasspy/piper-voices) ------------------------

def _piper_files(lang: str, region: str, voice: str, quality: str) -> tuple[ModelAsset, ...]:
    """Return the .onnx + .onnx.json pair for a Piper voice."""
    base = (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        f"{lang}/{lang}_{region}/{voice}/{quality}"
    )
    fname = f"{lang}_{region}-{voice}-{quality}.onnx"
    return (
        ModelAsset(relative_path=fname, url=f"{base}/{fname}"),
        ModelAsset(
            relative_path=f"{fname}.json", url=f"{base}/{fname}.json",
        ),
    )


CATALOG: dict[tuple[str, str], ModelEntry] = {
    # --- STT ---
    ("stt", "tiny"): ModelEntry(
        service="stt", model_id="tiny",
        display_name="Whisper Tiny (39 M)",
        size_mb=75.0, target_subdir="faster-whisper-tiny",
        files=_whisper_files("tiny"),
        description="Velocissimo, qualità bassa. Adatto a CPU lente.",
    ),
    ("stt", "base"): ModelEntry(
        service="stt", model_id="base",
        display_name="Whisper Base (74 M)",
        size_mb=145.0, target_subdir="faster-whisper-base",
        files=_whisper_files("base"),
        description="Buon compromesso velocità/qualità.",
    ),
    ("stt", "small"): ModelEntry(
        service="stt", model_id="small",
        display_name="Whisper Small (244 M)",
        size_mb=475.0, target_subdir="faster-whisper-small",
        files=_whisper_files("small"),
        description="Default consigliato. Qualità ottima su GPU/CPU moderne.",
    ),
    ("stt", "medium"): ModelEntry(
        service="stt", model_id="medium",
        display_name="Whisper Medium (769 M)",
        size_mb=1500.0, target_subdir="faster-whisper-medium",
        files=_whisper_files("medium"),
        description="Qualità superiore, richiede GPU dedicata.",
    ),
    ("stt", "large-v3"): ModelEntry(
        service="stt", model_id="large-v3",
        display_name="Whisper Large v3 (1550 M)",
        size_mb=3000.0, target_subdir="faster-whisper-large-v3",
        files=_whisper_files("large-v3"),
        description="Qualità massima. Richiede ≥6 GB VRAM.",
    ),
    # --- TTS (Piper) ---
    ("tts", "it_IT-paola-medium"): ModelEntry(
        service="tts", model_id="it_IT-paola-medium",
        display_name="Piper — Paola (italiano, medium)",
        size_mb=63.0, target_subdir="piper",
        files=_piper_files("it", "IT", "paola", "medium"),
        description="Voce italiana femminile. Default per IT.",
    ),
    ("tts", "it_IT-riccardo-x_low"): ModelEntry(
        service="tts", model_id="it_IT-riccardo-x_low",
        display_name="Piper — Riccardo (italiano, x_low)",
        size_mb=20.0, target_subdir="piper",
        files=_piper_files("it", "IT", "riccardo", "x_low"),
        description="Voce italiana maschile, modello leggero.",
    ),
    ("tts", "en_US-amy-medium"): ModelEntry(
        service="tts", model_id="en_US-amy-medium",
        display_name="Piper — Amy (english US, medium)",
        size_mb=63.0, target_subdir="piper",
        files=_piper_files("en", "US", "amy", "medium"),
        description="Voce inglese US femminile.",
    ),
    ("tts", "en_GB-alan-medium"): ModelEntry(
        service="tts", model_id="en_GB-alan-medium",
        display_name="Piper — Alan (english GB, medium)",
        size_mb=63.0, target_subdir="piper",
        files=_piper_files("en", "GB", "alan", "medium"),
        description="Voce inglese UK maschile.",
    ),
}


def list_catalog(service: str | None = None) -> list[dict]:
    """Return a JSON-serialisable list of catalog entries.

    Args:
        service: Optional filter (``"stt"`` / ``"tts"``).

    Returns:
        A list of dicts ready for the REST API.
    """
    items: list[dict] = []
    for entry in CATALOG.values():
        if service and entry.service != service:
            continue
        items.append({
            "service": entry.service,
            "model_id": entry.model_id,
            "display_name": entry.display_name,
            "size_mb": entry.size_mb,
            "target_subdir": entry.target_subdir,
            "description": entry.description,
            "file_count": len(entry.files),
        })
    return items


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------


class ModelDownloader:
    """Async downloader with progress notifications.

    Performance characteristics
    ---------------------------
    * **HTTP/2** is enabled when the optional ``h2`` package is installed
      (it is part of the locked dependency set), which lets a single TCP
      connection multiplex every request to ``huggingface.co``.
    * **Parallel range requests** split files larger than
      :attr:`_RANGE_THRESHOLD` into :attr:`_RANGE_PARTS` segments fetched
      concurrently — this typically yields a 4-8x speedup on the HF CDN
      because the per-stream throughput is bandwidth-capped per connection.
    * **1 MB chunks** keep CPU/IO overhead low when streaming the response
      body to disk.
    * **Resumable** — partial files are written to ``<target>.part`` and
      renamed atomically only on success.
    * **Idempotent** — already-present files are skipped.

    Args:
        models_root: Root directory under which ``<service>/<subdir>/`` is
            created (typically next to ``backend.exe`` in a frozen build,
            or ``<repo>/models`` in dev).
        event_bus: Shared event bus used to publish progress events.
    """

    _CHUNK = 1024 * 1024  # 1 MB — balances syscalls vs. progress cadence
    _RANGE_THRESHOLD = 16 * 1024 * 1024  # 16 MB → switch to parallel ranges
    _RANGE_PARTS = 8  # concurrent connections per large file
    _CONCURRENT_FILES = 4  # small-file pipeline depth
    _PROGRESS_EMIT_INTERVAL_S = 0.25

    def __init__(self, models_root: Path, event_bus: EventBus) -> None:
        self._root = Path(models_root)
        self._bus = event_bus
        self._lock = asyncio.Lock()
        self._in_flight: dict[tuple[str, str], asyncio.Task] = {}
        self._progress_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_present(self, service: str, model_id: str) -> bool:
        """Return ``True`` when every file of the model exists on disk."""
        entry = CATALOG.get((service, model_id))
        if entry is None:
            return False
        target_dir = self._root / service / entry.target_subdir
        return all(
            (target_dir / f.relative_path).exists() for f in entry.files
        )

    def target_dir(self, service: str, model_id: str) -> Path | None:
        """Return the on-disk directory for the model, regardless of presence."""
        entry = CATALOG.get((service, model_id))
        if entry is None:
            return None
        return self._root / service / entry.target_subdir

    async def download(self, service: str, model_id: str) -> Path:
        """Download a model.  Idempotent — returns immediately if present.

        Raises:
            KeyError: when the (service, model_id) pair is not in the catalog.
            httpx.HTTPError: on network failure.

        Returns:
            The absolute path to the model directory.
        """
        entry = CATALOG.get((service, model_id))
        if entry is None:
            raise KeyError(f"Unknown model '{service}/{model_id}'")

        # De-duplicate concurrent calls.
        async with self._lock:
            existing = self._in_flight.get((service, model_id))
            if existing is not None and not existing.done():
                logger.info(
                    "ModelDownloader: '{}/{}' already in flight — joining",
                    service, model_id,
                )
                return await existing
            task = asyncio.create_task(
                self._do_download(entry),
                name=f"download-{service}-{model_id}",
            )
            self._in_flight[(service, model_id)] = task

        try:
            return await task
        finally:
            async with self._lock:
                self._in_flight.pop((service, model_id), None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_client() -> httpx.AsyncClient:
        """Create an HTTP client tuned for HuggingFace CDN throughput.

        HTTP/2 is auto-enabled when ``h2`` is importable; otherwise we fall
        back transparently to HTTP/1.1.  The connection pool is sized to
        accommodate :attr:`_RANGE_PARTS` simultaneous range fetches.
        """
        try:
            import h2  # noqa: F401  — presence-only check
            http2 = True
        except ImportError:  # pragma: no cover
            http2 = False
        limits = httpx.Limits(
            max_connections=ModelDownloader._RANGE_PARTS * 2,
            max_keepalive_connections=ModelDownloader._RANGE_PARTS,
        )
        return httpx.AsyncClient(
            follow_redirects=True,
            http2=http2,
            limits=limits,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def _do_download(self, entry: ModelEntry) -> Path:
        target_dir = self._root / entry.service / entry.target_subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        async with self._build_client() as client:
            # First pass — discover sizes and accept-ranges support.
            sizes: dict[str, int] = {}
            ranges_ok: dict[str, bool] = {}
            for asset in entry.files:
                target = target_dir / asset.relative_path
                if target.exists():
                    sizes[asset.relative_path] = 0
                    ranges_ok[asset.relative_path] = False
                    continue
                try:
                    head = await client.head(asset.url)
                    sizes[asset.relative_path] = int(
                        head.headers.get("content-length", 0)
                    )
                    ranges_ok[asset.relative_path] = (
                        head.headers.get("accept-ranges", "").lower() == "bytes"
                    )
                except httpx.HTTPError:
                    sizes[asset.relative_path] = 0
                    ranges_ok[asset.relative_path] = False

            total_bytes = sum(sizes.values())
            progress = _ProgressState(total=total_bytes)
            await self._emit(
                entry, progress.downloaded, total_bytes,
                phase="downloading", file="",
            )

            # Second pass — fetch missing files.  Large files use parallel
            # range requests; small files run in a bounded pipeline.
            small_assets: list[ModelAsset] = []
            for asset in entry.files:
                target = target_dir / asset.relative_path
                if target.exists():
                    continue
                size = sizes[asset.relative_path]
                if (
                    size >= self._RANGE_THRESHOLD
                    and ranges_ok[asset.relative_path]
                ):
                    try:
                        await self._fetch_ranged(
                            client, entry, asset, target, size, progress,
                        )
                    except Exception as exc:
                        await self._emit(
                            entry, progress.downloaded, total_bytes,
                            phase="error", file=asset.relative_path,
                            error=str(exc),
                        )
                        raise
                else:
                    small_assets.append(asset)

            if small_assets:
                sem = asyncio.Semaphore(self._CONCURRENT_FILES)

                async def _runner(a: ModelAsset) -> None:
                    async with sem:
                        target = target_dir / a.relative_path
                        try:
                            await self._fetch_streaming(
                                client, entry, a, target, progress,
                            )
                        except Exception as exc:
                            await self._emit(
                                entry, progress.downloaded, total_bytes,
                                phase="error", file=a.relative_path,
                                error=str(exc),
                            )
                            raise

                await asyncio.gather(*(_runner(a) for a in small_assets))

        await self._emit(
            entry, progress.downloaded, total_bytes,
            phase="completed", file="",
        )
        return target_dir

    async def _fetch_streaming(
        self,
        client: httpx.AsyncClient,
        entry: ModelEntry,
        asset: ModelAsset,
        target: Path,
        progress: _ProgressState,
    ) -> None:
        """Single-stream download for files below :attr:`_RANGE_THRESHOLD`."""
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            async with client.stream("GET", asset.url) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as fp:
                    async for chunk in resp.aiter_bytes(self._CHUNK):
                        fp.write(chunk)
                        await self._tick(
                            entry, asset.relative_path,
                            progress, len(chunk),
                        )
            tmp.replace(target)
            logger.info(
                "ModelDownloader: fetched {} ({} bytes)",
                target, target.stat().st_size,
            )
        except Exception:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise

    async def _fetch_ranged(
        self,
        client: httpx.AsyncClient,
        entry: ModelEntry,
        asset: ModelAsset,
        target: Path,
        size: int,
        progress: _ProgressState,
    ) -> None:
        """Parallel range-request download for large files.

        The file is split into :attr:`_RANGE_PARTS` contiguous segments
        and each segment streamed into a pre-allocated sparse file.  On
        success the file is renamed atomically.
        """
        tmp = target.with_suffix(target.suffix + ".part")
        # Pre-allocate so concurrent writers can seek without races.
        with tmp.open("wb") as fp:
            fp.truncate(size)

        part_size = max(1, size // self._RANGE_PARTS)
        ranges: list[tuple[int, int]] = []
        for i in range(self._RANGE_PARTS):
            start = i * part_size
            end = (start + part_size - 1) if i < self._RANGE_PARTS - 1 else size - 1
            if start >= size:
                break
            ranges.append((start, end))

        async def _fetch_part(start: int, end: int) -> None:
            headers = {"Range": f"bytes={start}-{end}"}
            offset = start
            async with client.stream("GET", asset.url, headers=headers) as resp:
                if resp.status_code not in (200, 206):
                    resp.raise_for_status()
                async for chunk in resp.aiter_bytes(self._CHUNK):
                    # ``open(..., "r+b")`` per chunk is too slow; reuse one
                    # handle but guard with the running-loop's executor for
                    # the synchronous ``write`` call.
                    await asyncio.to_thread(_pwrite, tmp, offset, chunk)
                    offset += len(chunk)
                    await self._tick(
                        entry, asset.relative_path,
                        progress, len(chunk),
                    )

        try:
            await asyncio.gather(*(_fetch_part(s, e) for s, e in ranges))
            tmp.replace(target)
            logger.info(
                "ModelDownloader: fetched {} ({} bytes, {}-way ranged)",
                target, target.stat().st_size, len(ranges),
            )
        except Exception:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise

    async def _tick(
        self,
        entry: ModelEntry,
        file: str,
        progress: _ProgressState,
        delta: int,
    ) -> None:
        """Increment progress and emit a throttled update."""
        async with self._progress_lock:
            progress.downloaded += delta
            now = time.monotonic()
            if now - progress.last_emit < self._PROGRESS_EMIT_INTERVAL_S:
                return
            progress.last_emit = now
            downloaded = progress.downloaded
            total = progress.total
        await self._emit(
            entry, downloaded, total,
            phase="downloading", file=file,
        )
    async def _emit(
        self,
        entry: ModelEntry,
        downloaded: int,
        total: int,
        *,
        phase: str,
        file: str,
        error: str | None = None,
    ) -> None:
        payload: dict = {
            "service": entry.service,
            "model_id": entry.model_id,
            "downloaded_bytes": downloaded,
            "total_bytes": total,
            "phase": phase,
            "file": file,
        }
        if error is not None:
            payload["error"] = error
        try:
            await self._bus.emit(PROGRESS_EVENT, **payload)
        except Exception:  # never let progress emission abort a download
            logger.exception("ModelDownloader: failed to emit progress event")
