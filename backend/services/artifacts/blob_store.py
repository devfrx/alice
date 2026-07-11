"""AL\\CE — JSON blob store for artifact content.

Owns the on-disk *content* of JSON-kind artifacts (charts, whiteboards,
...) under ``data/artifacts/<kind>/<artifact_id>.json``.  The DB row
(:class:`backend.db.models.Artifact`) remains the source of truth for
metadata; this store only owns blob bytes (atomic writes).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.config import PROJECT_ROOT
from backend.db.models import ArtifactKind

DEFAULT_BLOB_BASE_DIR = PROJECT_ROOT / "data" / "artifacts"


class ArtifactBlobStore:
    """On-disk JSON blobs for artifacts, one file per artifact id."""

    def __init__(self, base_dir: Path | None = None) -> None:
        """Build a blob store rooted at *base_dir* (default ``data/artifacts``)."""
        self._base_dir = base_dir or DEFAULT_BLOB_BASE_DIR

    def path_for(self, kind: ArtifactKind, artifact_id: uuid.UUID) -> Path:
        """Return the canonical blob path for *kind* / *artifact_id*."""
        return self._base_dir / kind.value / f"{artifact_id}.json"

    async def write(
        self,
        kind: ArtifactKind,
        artifact_id: uuid.UUID,
        content: dict[str, Any],
    ) -> tuple[Path, int]:
        """Atomically serialise *content*; return ``(path, size_bytes)``."""
        path = self.path_for(kind, artifact_id)
        data = json.dumps(content, ensure_ascii=False, indent=2, default=str)
        size = await asyncio.to_thread(self._write_sync, path, data)
        return path, size

    async def read(self, file_path: str | Path) -> dict[str, Any] | None:
        """Load a blob by its (possibly relative) *file_path*.

        Returns ``None`` when the file is missing or not a JSON object.
        """
        p = Path(file_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return await asyncio.to_thread(self._read_sync, p)

    @staticmethod
    def _write_sync(path: Path, data: str) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(data, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        return path.stat().st_size

    @staticmethod
    def _read_sync(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Artifact blob unreadable {}: {}", path, exc)
            return None
        return loaded if isinstance(loaded, dict) else None
