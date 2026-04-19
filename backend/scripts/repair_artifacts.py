"""AL\\CE — One-shot repair for backfilled artifacts.

The first run of :mod:`backend.scripts.backfill_artifacts` matched
every payload against the more permissive ``cad_generate`` parser,
because both built-in 3D parsers were too lenient (they accepted any
payload carrying ``file_path``).  Tool messages had also been
sanitised before reaching the registry, so ``file_path`` was stored
as the literal string ``"[path removed]"``.

This script repairs both issues for existing rows:

* Re-derives :class:`ArtifactKind` from the source ``Message.content``
  payload (presence of ``source_image`` / ``pipeline_type`` ⇒
  ``cad_3d_image``).
* Restores ``file_path`` by checking ``data/3d_models/{model_name}.glb``
  on disk; if the file exists the path (relative to ``PROJECT_ROOT``)
  is stored, otherwise the row is left untouched.
* Recomputes ``size_bytes`` from the restored file when missing.

Idempotent: rows that already point to an existing file are skipped.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Make the project root importable when invoked directly.
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]  # alice/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from sqlmodel import select

from backend.core.config import load_config
from backend.db.database import create_engine_and_session, init_db
from backend.db.models import Artifact, ArtifactKind, Message


_MODELS_DIR = _PROJECT_ROOT / "data" / "3d_models"


async def _repair() -> None:
    config = load_config()
    engine, session_factory = create_engine_and_session(config.database.url)
    await init_db(engine)

    fixed_kind = 0
    fixed_path = 0
    skipped = 0

    async with session_factory() as session:
        rows_q = await session.exec(select(Artifact))
        artifacts: list[Artifact] = list(rows_q.all())

        for art in artifacts:
            payload = await _payload_for(session, art)

            # 1. Re-derive kind from the original payload.
            new_kind = _derive_kind(payload)
            if new_kind is not None and new_kind != art.kind:
                art.kind = new_kind
                fixed_kind += 1

            # 2. Restore file_path from disk via model_name.
            current = Path(art.file_path)
            current_abs = (
                current if current.is_absolute() else _PROJECT_ROOT / current
            )
            if not current_abs.exists() or not current_abs.is_file():
                model_name = (
                    (payload or {}).get("model_name")
                    or art.artifact_metadata.get("model_name")
                    or art.title
                )
                candidate = _MODELS_DIR / f"{model_name}.glb"
                if candidate.exists() and candidate.is_file():
                    rel = candidate.relative_to(_PROJECT_ROOT)
                    art.file_path = str(rel).replace("\\", "/")
                    if not art.size_bytes:
                        art.size_bytes = candidate.stat().st_size
                    fixed_path += 1
                else:
                    skipped += 1
                    logger.warning(
                        "No GLB found for {!r} (artifact {})",
                        model_name, art.id,
                    )

            session.add(art)

        await session.commit()

    await engine.dispose()

    logger.success(
        "Repair complete: kind fixed for {}, file_path restored for {}, "
        "{} could not be matched on disk.",
        fixed_kind, fixed_path, skipped,
    )


async def _payload_for(session, artifact: Artifact) -> dict | None:
    """Return the parsed JSON payload from the source tool message."""
    if artifact.message_id is None:
        return None
    msg = await session.get(Message, artifact.message_id)
    if msg is None or not msg.content:
        return None
    try:
        data = json.loads(msg.content)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _derive_kind(payload: dict | None) -> ArtifactKind | None:
    """Distinguish text-to-3D from image-to-3D by payload shape."""
    if not payload:
        return None
    if payload.get("source_image") or payload.get("pipeline_type"):
        return ArtifactKind.CAD_3D_IMAGE
    if "description" in payload:
        return ArtifactKind.CAD_3D_TEXT
    return None


if __name__ == "__main__":
    asyncio.run(_repair())
