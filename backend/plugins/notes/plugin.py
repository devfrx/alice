"""O.M.N.I.A. — Notes plugin.

Exposes six tools — ``create_note``, ``read_note``, ``update_note``,
``delete_note``, ``search_notes``, ``list_notes`` — that delegate to
the :class:`NoteServiceProtocol` on the application context.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

from backend.core.event_bus import OmniaEvent
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext


class NotesPlugin(BasePlugin):
    """Manage an Obsidian-like note vault via NoteService."""

    plugin_name: str = "notes"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Create, read, update, delete, and search Markdown notes "
        "in an Obsidian-like vault."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 85

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def initialize(self, ctx: AppContext) -> None:
        """Store context and verify note service availability."""
        await super().initialize(ctx)
        if ctx.note_service is None:
            self.logger.warning(
                "NoteService is not available "
                "— all notes tools will return errors"
            )

    # ------------------------------------------------------------------ #
    # Tools
    # ------------------------------------------------------------------ #

    def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions for note operations."""
        return [
            ToolDefinition(
                name="create_note",
                description=(
                    "Create a new Markdown note in the vault. "
                    "Use for documents the user wants to review "
                    "and edit later (recipes, plans, summaries)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Note title.",
                            "maxLength": 500,
                        },
                        "content": {
                            "type": "string",
                            "description": (
                                "Markdown body of the note."
                            ),
                            "maxLength": 100000,
                        },
                        "folder_path": {
                            "type": "string",
                            "description": (
                                "Virtual folder path "
                                "(e.g. 'recipes/italian')."
                            ),
                            "default": "",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tags.",
                        },
                    },
                    "required": ["title", "content"],
                },
                result_type="string",
                risk_level="safe",
                requires_confirmation=False,
            ),
            ToolDefinition(
                name="read_note",
                description=(
                    "Read a note by its ID. Use search_notes "
                    "first to find the ID if unknown."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "string",
                            "description": "UUID of the note.",
                        },
                    },
                    "required": ["note_id"],
                },
                result_type="json",
                risk_level="safe",
                requires_confirmation=False,
            ),
            ToolDefinition(
                name="update_note",
                description=(
                    "Update an existing note. Only the fields "
                    "provided will be changed."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "string",
                            "description": "UUID of the note.",
                        },
                        "title": {
                            "type": "string",
                            "description": "New title.",
                            "maxLength": 500,
                        },
                        "content": {
                            "type": "string",
                            "description": "New Markdown body.",
                            "maxLength": 100000,
                        },
                        "folder_path": {
                            "type": "string",
                            "description": "New folder path.",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "New tag list.",
                        },
                        "pinned": {
                            "type": "boolean",
                            "description": "Pin/unpin the note.",
                        },
                    },
                    "required": ["note_id"],
                },
                result_type="string",
                risk_level="safe",
                requires_confirmation=False,
            ),
            ToolDefinition(
                name="delete_note",
                description=(
                    "Delete a note by ID. Only use when "
                    "the user explicitly requests deletion."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "string",
                            "description": "UUID of the note.",
                        },
                    },
                    "required": ["note_id"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
            ),
            ToolDefinition(
                name="search_notes",
                description=(
                    "Search notes by text (FTS5) and semantic "
                    "similarity. Use before read or update to "
                    "find notes by topic."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query.",
                            "maxLength": 500,
                        },
                        "folder": {
                            "type": "string",
                            "description": "Filter by folder.",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by tags.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (1–20).",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 20,
                        },
                    },
                    "required": ["query"],
                },
                result_type="json",
                risk_level="safe",
                requires_confirmation=False,
            ),
            ToolDefinition(
                name="list_notes",
                description=(
                    "List notes in the vault with optional "
                    "folder, tag, or pinned filters."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "folder": {
                            "type": "string",
                            "description": "Filter by folder.",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by tags.",
                        },
                        "pinned_only": {
                            "type": "boolean",
                            "description": "Only pinned notes.",
                            "default": False,
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (1–50).",
                            "default": 20,
                            "minimum": 1,
                            "maximum": 50,
                        },
                    },
                    "required": [],
                },
                result_type="json",
                risk_level="safe",
                requires_confirmation=False,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested notes tool."""
        if self._ctx is None or self._ctx.note_service is None:
            return ToolResult.error("Note service not available")

        start = time.perf_counter()

        if tool_name == "create_note":
            return await self._handle_create(args, start)
        if tool_name == "read_note":
            return await self._handle_read(args, start)
        if tool_name == "update_note":
            return await self._handle_update(args, start)
        if tool_name == "delete_note":
            return await self._handle_delete(args, start)
        if tool_name == "search_notes":
            return await self._handle_search(args, start)
        if tool_name == "list_notes":
            return await self._handle_list(args, start)

        return ToolResult.error(f"Unknown tool: {tool_name}")

    # ------------------------------------------------------------------ #
    # Dependency / health
    # ------------------------------------------------------------------ #

    def check_dependencies(self) -> list[str]:
        """Report missing dependencies."""
        if self._ctx is None or self._ctx.note_service is None:
            return ["note_service"]
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED if note service is available."""
        if self._ctx and self._ctx.note_service is not None:
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.ERROR

    # ------------------------------------------------------------------ #
    # Private handlers
    # ------------------------------------------------------------------ #

    async def _handle_create(
        self, args: dict[str, Any], start: float,
    ) -> ToolResult:
        """Create a new note."""
        title = (args.get("title") or "").strip()
        if not title:
            return ToolResult.error("Missing required parameter: title")
        content = args.get("content", "")
        if len(content) > 100_000:
            return ToolResult.error(
                "Content too long (max 100 000 characters)"
            )
        folder_path = args.get("folder_path", "")
        tags = args.get("tags")

        try:
            entry = await self._ctx.note_service.create(
                title=title,
                content=content,
                folder_path=folder_path,
                tags=tags,
            )
            elapsed = (time.perf_counter() - start) * 1000
            await self._ctx.event_bus.emit(
                OmniaEvent.NOTE_CREATED,
                note_id=entry.id, title=title,
            )
            return ToolResult.ok(
                content=(
                    f"Note created (id={entry.id}, "
                    f"title={title!r})"
                ),
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            self.logger.error("create_note failed: {}", exc)
            return ToolResult.error(f"Failed to create note: {exc}")

    async def _handle_read(
        self, args: dict[str, Any], start: float,
    ) -> ToolResult:
        """Read a note by ID."""
        note_id = (args.get("note_id") or "").strip()
        if not note_id:
            return ToolResult.error(
                "Missing required parameter: note_id",
            )
        try:
            uuid.UUID(note_id)
        except ValueError:
            return ToolResult.error(f"Invalid note_id: {note_id!r}")

        try:
            entry = await self._ctx.note_service.get(note_id)
            elapsed = (time.perf_counter() - start) * 1000
            if entry is None:
                return ToolResult.error(
                    f"Note {note_id} not found",
                    execution_time_ms=elapsed,
                )
            data = entry.to_dict()
            max_chars = self._ctx.config.notes.max_content_chars_llm
            if len(data["content"]) > max_chars:
                data["content"] = (
                    data["content"][:max_chars] + "\n…(truncated)"
                )
            return ToolResult.ok(
                content=data,
                content_type="application/json",
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            self.logger.error("read_note failed: {}", exc)
            return ToolResult.error(f"Failed to read note: {exc}")

    async def _handle_update(
        self, args: dict[str, Any], start: float,
    ) -> ToolResult:
        """Update an existing note."""
        note_id = (args.get("note_id") or "").strip()
        if not note_id:
            return ToolResult.error(
                "Missing required parameter: note_id",
            )
        try:
            uuid.UUID(note_id)
        except ValueError:
            return ToolResult.error(f"Invalid note_id: {note_id!r}")

        content = args.get("content")
        if content is not None and len(content) > 100_000:
            return ToolResult.error(
                "Content too long (max 100 000 characters)"
            )

        try:
            entry = await self._ctx.note_service.update(
                note_id,
                title=args.get("title"),
                content=args.get("content"),
                folder_path=args.get("folder_path"),
                tags=args.get("tags"),
                pinned=args.get("pinned"),
            )
            elapsed = (time.perf_counter() - start) * 1000
            if entry is None:
                return ToolResult.error(
                    f"Note {note_id} not found",
                    execution_time_ms=elapsed,
                )
            await self._ctx.event_bus.emit(
                OmniaEvent.NOTE_UPDATED, note_id=note_id,
            )
            return ToolResult.ok(
                content=f"Note {note_id} updated",
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            self.logger.error("update_note failed: {}", exc)
            return ToolResult.error(f"Failed to update note: {exc}")

    async def _handle_delete(
        self, args: dict[str, Any], start: float,
    ) -> ToolResult:
        """Delete a note by ID."""
        note_id = (args.get("note_id") or "").strip()
        if not note_id:
            return ToolResult.error(
                "Missing required parameter: note_id",
            )
        try:
            uuid.UUID(note_id)
        except ValueError:
            return ToolResult.error(f"Invalid note_id: {note_id!r}")

        try:
            deleted = await self._ctx.note_service.delete(note_id)
            elapsed = (time.perf_counter() - start) * 1000
            if deleted:
                await self._ctx.event_bus.emit(
                    OmniaEvent.NOTE_DELETED, note_id=note_id,
                )
                return ToolResult.ok(
                    content=f"Note {note_id} deleted",
                    execution_time_ms=elapsed,
                )
            return ToolResult.error(
                f"Note {note_id} not found",
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            self.logger.error("delete_note failed: {}", exc)
            return ToolResult.error(f"Failed to delete note: {exc}")

    async def _handle_search(
        self, args: dict[str, Any], start: float,
    ) -> ToolResult:
        """Search notes by text and semantic similarity."""
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult.error(
                "Missing required parameter: query",
            )

        limit = args.get("limit", 10)
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            limit = 10

        try:
            results = await self._ctx.note_service.search(
                query=query,
                folder=args.get("folder"),
                tags=args.get("tags"),
                limit=limit,
            )
            notes = [
                {
                    "id": str(r["entry"].id),
                    "title": r["entry"].title,
                    "folder_path": r["entry"].folder_path,
                    "tags": r["entry"].tags,
                    "score": r.get("score", 0.0),
                    "updated_at": r["entry"].updated_at,
                }
                for r in results
            ]
            elapsed = (time.perf_counter() - start) * 1000
            return ToolResult.ok(
                content={
                    "query": query,
                    "count": len(notes),
                    "notes": notes,
                },
                content_type="application/json",
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            self.logger.error("search_notes failed: {}", exc)
            return ToolResult.error(
                f"Failed to search notes: {exc}",
            )

    async def _handle_list(
        self, args: dict[str, Any], start: float,
    ) -> ToolResult:
        """List notes with optional filters."""
        limit = args.get("limit", 20)
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            limit = 20

        try:
            entries, total = await self._ctx.note_service.list(
                folder=args.get("folder"),
                tags=args.get("tags"),
                pinned_only=bool(args.get("pinned_only", False)),
                limit=limit,
            )
            notes = [
                {
                    "id": str(e.id),
                    "title": e.title,
                    "folder_path": e.folder_path,
                    "tags": e.tags,
                    "pinned": e.pinned,
                    "updated_at": e.updated_at,
                }
                for e in entries
            ]
            elapsed = (time.perf_counter() - start) * 1000
            return ToolResult.ok(
                content={
                    "total": total,
                    "count": len(notes),
                    "notes": notes,
                },
                content_type="application/json",
                execution_time_ms=elapsed,
            )
        except Exception as exc:
            self.logger.error("list_notes failed: {}", exc)
            return ToolResult.error(
                f"Failed to list notes: {exc}",
            )
