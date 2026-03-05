"""O.M.N.I.A. — File-based conversation persistence.

Saves every conversation as an organized JSON file so that conversations
can be recovered if the SQLite database is lost or corrupted.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from backend.db.models import Attachment, Conversation, Message

CURRENT_SCHEMA_VERSION: int = 2

_SAFE_USER_ID: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate v1 (pre-Phase 3) JSON to v2 (with tool_calls fields).

    Adds ``tool_calls`` and ``tool_call_id`` keys (defaulting to ``None``)
    to every message that does not already have them, and stamps the
    schema version as 2.

    Args:
        data: Parsed conversation dict (mutated in place and returned).

    Returns:
        The same dict with v2 fields guaranteed on every message.
    """
    for msg in data.get("messages", []):
        if "tool_calls" not in msg:
            msg["tool_calls"] = None
        if "tool_call_id" not in msg:
            msg["tool_call_id"] = None
    data["schema_version"] = CURRENT_SCHEMA_VERSION
    return data


class ConversationFileManager:
    """Manages JSON file persistence for conversations.

    Each conversation is stored as ``{base_dir}/{conversation_id}.json``.
    Writes are atomic (temp file + rename) to prevent corruption.
    """

    def __init__(self, base_dir: Path) -> None:
        """Initialise the file manager.

        Args:
            base_dir: Directory where conversation JSON files are stored.
        """
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # -- internal helpers ---------------------------------------------------

    def _resolve_dir(self, user_id: str | None = None) -> Path:
        """Return the storage directory, optionally scoped to a user.

        Args:
            user_id: When provided the returned path is
                ``base_dir / user_id``; the subdirectory is created
                automatically.

        Returns:
            The resolved directory path.

        Raises:
            ValueError: If *user_id* contains invalid characters.
        """
        if user_id is None:
            return self._base_dir
        if not _SAFE_USER_ID.match(user_id):
            raise ValueError(f"Invalid user_id: {user_id!r}")
        user_dir = self._base_dir / user_id
        if not user_dir.resolve().is_relative_to(self._base_dir.resolve()):
            raise ValueError(f"user_id escapes base directory: {user_id!r}")
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    @property
    def base_dir(self) -> Path:
        """The directory where conversation JSON files are stored."""
        return self._base_dir

    # -- public API ---------------------------------------------------------

    async def save(
        self,
        conversation_data: dict[str, Any],
        user_id: str | None = None,
    ) -> None:
        """Persist a conversation dict to its JSON file atomically.

        Args:
            conversation_data: Full conversation dict including messages.
            user_id: Optional user id for per-user subdirectory sharding.
        """
        conversation_data["schema_version"] = CURRENT_SCHEMA_VERSION
        conv_id = conversation_data["id"]
        directory = self._resolve_dir(user_id)
        target = directory / f"{conv_id}.json"
        tmp = target.with_suffix(".tmp")

        payload = json.dumps(conversation_data, ensure_ascii=False, indent=2)

        def _write() -> None:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(target)

        await asyncio.to_thread(_write)
        logger.debug("Saved conversation file {}", target.name)

    async def delete(
        self,
        conversation_id: str,
        user_id: str | None = None,
    ) -> None:
        """Remove the JSON file for a conversation.

        Args:
            conversation_id: UUID string of the conversation.
            user_id: Optional user id for per-user subdirectory sharding.
        """
        directory = self._resolve_dir(user_id)
        target = directory / f"{conversation_id}.json"

        def _remove() -> None:
            if target.exists():
                target.unlink()

        await asyncio.to_thread(_remove)
        logger.debug("Deleted conversation file {}.json", conversation_id)

    async def load(
        self,
        conversation_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Read a single conversation from its JSON file.

        If the file uses schema v1 (or has no version), it is migrated
        to v2 in memory and re-saved to disk.

        Args:
            conversation_id: UUID string of the conversation.
            user_id: Optional user id for per-user subdirectory sharding.

        Returns:
            Parsed conversation dict, or ``None`` if the file doesn't exist.
        """
        directory = self._resolve_dir(user_id)
        target = directory / f"{conversation_id}.json"

        def _read() -> str | None:
            if not target.exists():
                return None
            return target.read_text(encoding="utf-8")

        raw = await asyncio.to_thread(_read)
        if raw is None:
            return None

        data: dict[str, Any] = json.loads(raw)
        if data.get("schema_version", 1) < CURRENT_SCHEMA_VERSION:
            data = _migrate_v1_to_v2(data)
            await self.save(data, user_id=user_id)
            logger.info("Migrated conversation {} to schema v2", conversation_id)
        return data

    async def load_all(
        self,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read all conversation JSON files in the target directory.

        Files using schema v1 are migrated to v2 and re-saved.

        Args:
            user_id: Optional user id for per-user subdirectory sharding.

        Returns:
            List of parsed conversation dicts (order is arbitrary).
        """
        directory = self._resolve_dir(user_id)

        def _read_all() -> list[str]:
            results: list[str] = []
            for path in directory.glob("*.json"):
                try:
                    results.append(path.read_text(encoding="utf-8"))
                except Exception:
                    logger.warning("Failed to read {}", path)
            return results

        raw_list = await asyncio.to_thread(_read_all)
        conversations: list[dict[str, Any]] = []
        for raw in raw_list:
            try:
                data: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed conversation JSON")
                continue

            if data.get("schema_version", 1) < CURRENT_SCHEMA_VERSION:
                data = _migrate_v1_to_v2(data)
                await self.save(data, user_id=user_id)
                logger.info(
                    "Migrated conversation {} to schema v2", data.get("id")
                )
            conversations.append(data)
        return conversations

    async def rebuild_from_files(self, session_factory: Any) -> int:
        """Rebuild the database from saved JSON files.

        Args:
            session_factory: An ``async_sessionmaker`` for creating DB sessions.

        Returns:
            Number of conversations successfully restored.
        """
        all_data = await self.load_all()
        restored = 0

        async with session_factory() as session:
            for conv_data in all_data:
                try:
                    conv_id = uuid.UUID(conv_data["id"])

                    existing = await session.get(Conversation, conv_id)
                    if existing is not None:
                        continue

                    # Use a savepoint so a single failure doesn't
                    # roll back all previously restored conversations.
                    async with session.begin_nested():
                        conv = Conversation(
                            id=conv_id,
                            title=conv_data.get("title"),
                            created_at=datetime.fromisoformat(
                                conv_data["created_at"]
                            ),
                            updated_at=datetime.fromisoformat(
                                conv_data["updated_at"]
                            ),
                        )
                        session.add(conv)
                        await session.flush()

                        for msg_data in conv_data.get("messages", []):
                            msg = Message(
                                id=uuid.UUID(msg_data["id"]),
                                conversation_id=conv_id,
                                role=msg_data["role"],
                                content=msg_data.get("content", ""),
                                tool_calls=msg_data.get("tool_calls"),
                                tool_call_id=msg_data.get("tool_call_id"),
                                thinking_content=msg_data.get(
                                    "thinking_content"
                                ),
                                created_at=datetime.fromisoformat(
                                    msg_data["created_at"]
                                ),
                            )
                            session.add(msg)
                            await session.flush()

                            for att_data in msg_data.get("attachments") or []:
                                att = Attachment(
                                    id=uuid.UUID(att_data["file_id"]),
                                    message_id=msg.id,
                                    filename=att_data["filename"],
                                    content_type=att_data["content_type"],
                                    file_path=att_data.get(
                                        "file_path", ""
                                    ),
                                )
                                session.add(att)

                    restored += 1
                except Exception:
                    logger.exception(
                        "Failed to restore conversation {}",
                        conv_data.get("id", "???"),
                    )
                    # Savepoint already rolled back; outer transaction intact.
                    continue

            await session.commit()

        logger.info("Rebuilt {} conversations from JSON files", restored)
        return restored
