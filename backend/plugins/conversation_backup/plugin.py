"""AL\\CE — Conversation backup plugin.

Exposes the ``backup_conversations`` tool: the agent-facing entry point of
the explicit conversation export command (spec §5.2). Delegates to the same
``conversation_export`` service used by the REST backup endpoint — one
capability, one implementation.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.core.config import PROJECT_ROOT
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.services.conversation_export import export_conversations_to_dir


class ConversationBackupPlugin(BasePlugin):
    """Explicit JSON backup of conversations (app-owned backups directory)."""

    plugin_name: str = "conversation_backup"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Export conversations as JSON backup files on explicit request."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 20

    def get_tools(self) -> list[ToolDefinition]:
        """Return the backup tool definition."""
        return [
            ToolDefinition(
                name="backup_conversations",
                description=(
                    "Export conversations as JSON backup files into the "
                    "app-managed backups folder (data/backups). Pass "
                    "conversation_id (a UUID, or the literal string 'current' "
                    "for the conversation this turn belongs to) to export a "
                    "single conversation; omit it to export all conversations. "
                    "Returns the number of exported conversations and the "
                    "destination path."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": (
                                "UUID of a single conversation to export, or the literal "
                                "string 'current' for the active conversation. Omit to "
                                "export all conversations."
                            ),
                        },
                    },
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=60000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Run the backup into ``data/backups/conversations-<timestamp>/``."""
        if tool_name != "backup_conversations":
            return ToolResult.error(f"Unknown tool: {tool_name}")

        conversation_ids: list[uuid.UUID] | None = None
        raw_id = args.get("conversation_id")
        if raw_id == "current":
            raw_id = context.conversation_id
        if raw_id:
            try:
                conversation_ids = [uuid.UUID(str(raw_id))]
            except ValueError:
                return ToolResult.error(f"Invalid conversation_id: {raw_id!r}")

        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        dest = PROJECT_ROOT / "data" / "backups" / f"conversations-{stamp}"

        start = time.perf_counter()
        try:
            exported = await export_conversations_to_dir(
                self.ctx.db, dest, conversation_ids,
            )
        except OSError as exc:
            return ToolResult.error(f"Backup failed: {exc}")
        except Exception as exc:
            self.logger.error("backup_conversations failed: {}", exc)
            return ToolResult.error(f"Backup failed: {exc}")

        if conversation_ids is not None and exported == 0:
            return ToolResult.error(
                f"Conversation {conversation_ids[0]} not found — nothing exported",
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content={"exported": exported, "path": str(dest)},
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )
