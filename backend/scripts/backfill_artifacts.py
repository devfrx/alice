"""AL\\CE — Backfill artifacts from existing tool messages.

Scansiona tutti i ``Message`` con ``role='tool'`` esistenti nel DB e
crea righe ``Artifact`` retroattive per i payload riconosciuti dai
parser registrati (``cad_generate``, ``cad_generate_from_image``, …).

Idempotente: salta i messaggi che hanno già un artifact con lo stesso
``tool_call_id``.

Uso (dalla cartella ``alice/``)::

    python -m backend.scripts.backfill_artifacts
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure the project root (``alice/``) is importable when the script
# is invoked directly.
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]  # alice/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from sqlmodel import select

from backend.core.config import load_config
from backend.db.database import create_engine_and_session, init_db
from backend.db.models import Artifact, Message
from backend.services.artifacts.parsers import _PARSERS, parse_tool_payload
from backend.services.artifacts.registry import ArtifactRegistry


async def _backfill() -> None:
    """Walk the messages table and persist missing artifacts."""
    config = load_config()
    engine, session_factory = create_engine_and_session(config.database.url)
    await init_db(engine)

    registry = ArtifactRegistry(session_factory=session_factory)

    created = 0
    skipped_existing = 0
    skipped_unknown = 0
    skipped_malformed = 0

    async with session_factory() as session:
        existing_rows = await session.exec(
            select(Artifact.tool_call_id).where(
                Artifact.tool_call_id.is_not(None)
            )
        )
        existing: set[str] = {row for row in existing_rows.all() if row}

        msgs_q = await session.exec(
            select(Message).where(Message.role == "tool")
        )
        messages: list[Message] = list(msgs_q.all())

    logger.info(
        "Scanning {} tool messages (already-registered tool_call_ids: {})",
        len(messages), len(existing),
    )

    for msg in messages:
        tc_id = msg.tool_call_id
        if not tc_id:
            continue
        if tc_id in existing:
            skipped_existing += 1
            continue

        payload = _try_parse_json(msg.content)
        if not isinstance(payload, dict):
            skipped_malformed += 1
            continue

        # Message rows don't store the tool name — try every registered
        # parser until one matches the payload shape.
        descriptor = None
        matched_tool = None
        for tool_name in _PARSERS:
            descriptor = parse_tool_payload(tool_name, payload, None)
            if descriptor is not None:
                matched_tool = tool_name
                break
        if descriptor is None:
            skipped_unknown += 1
            continue

        try:
            artifact = await registry.register_from_tool_result(
                conversation_id=msg.conversation_id,
                message_id=msg.id,
                tool_call_id=tc_id,
                tool_name=matched_tool,
                payload=payload,
                content_type=None,
            )
        except Exception as exc:
            logger.warning("Backfill failed for msg {}: {}", msg.id, exc)
            continue

        if artifact is not None:
            created += 1
            logger.info(
                "  + artifact {} ({}) - {!r}",
                artifact.id, artifact.kind.value, artifact.title,
            )

    await engine.dispose()

    logger.success(
        "Backfill complete: {} created, {} already existed, "
        "{} unknown tool, {} malformed payload",
        created, skipped_existing, skipped_unknown, skipped_malformed,
    )


def _try_parse_json(content: str | None) -> object:
    """Best-effort JSON decode of a tool message content."""
    if not content:
        return None
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    asyncio.run(_backfill())
