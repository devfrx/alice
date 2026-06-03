"""AL\\CE — Continuum plugin note CRUD tools.

The six persistent-note tools — ``create_note``, ``read_note``,
``update_note``, ``delete_note``, ``search_notes``, ``list_notes`` — that
let the agent manage Continuum notes. They route through the application's
:class:`~backend.services.knowledge.protocol.KnowledgeBackend` with
``kind="note"``, which delegates note storage to the running Continuum
server (see :class:`~backend.services.knowledge.continuum_backend.\
ContinuumBackend`). Markdown bodies are rendered to HTML on write so the
LLM can author natural markdown while Continuum stores rich blocks.

Kept in a dedicated module so :mod:`backend.plugins.continuum.plugin`
stays focused on lifecycle and the structured-surface dispatch.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from backend.core.event_bus import AliceEvent
from backend.core.plugin_models import ToolDefinition, ToolResult
from backend.services.knowledge import (
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeDocPatch,
)
from backend.services.markdown_render import markdown_to_html

if TYPE_CHECKING:
    from loguru import Logger

    from backend.core.context import AppContext


#: Tool names handled by this module. Used by the plugin to route dispatch
#: to :func:`execute_note_tool` before its structured-surface handlers.
NOTE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_note",
        "read_note",
        "update_note",
        "delete_note",
        "search_notes",
        "list_notes",
    }
)

#: Hard cap on note body length accepted from the LLM (characters).
_MAX_CONTENT_CHARS: int = 100_000


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _isoformat_or_empty(value: datetime | str | None) -> str:
    """Return an ISO-8601 string or ``""`` if value is missing."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _note_doc_to_payload(doc: KnowledgeDoc) -> dict[str, Any]:
    """Serialise a note :class:`KnowledgeDoc` to the LLM-facing dict shape."""
    meta = doc.metadata or {}
    return {
        "id": doc.id,
        "title": doc.title or "",
        "content": doc.content,
        "folder_path": meta.get("folder_path", ""),
        "tags": list(doc.tags),
        "wikilinks": list(meta.get("wikilinks", []) or []),
        "pinned": bool(meta.get("pinned", False)),
        "created_at": _isoformat_or_empty(doc.created_at),
        "updated_at": _isoformat_or_empty(doc.updated_at),
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def build_note_tool_definitions() -> list[ToolDefinition]:
    """Return the note CRUD tool definitions.

    Tool names are unqualified; the tool registry namespaces them as
    ``continuum_<name>`` at registration time.
    """
    return [
        ToolDefinition(
            name="create_note",
            description=(
                "Create a structured Markdown document in Continuum. "
                "Use for long-form content the user will review and edit in the UI "
                "(recipes, project plans, summaries, guides). "
                "DISTINCT from memory_remember which stores short atomic facts — "
                "use notes for rich, titled, user-visible documents. "
                "Never create a duplicate — use update_note if a note already exists."
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
                            "Markdown body of the note. Standard "
                            "markdown is supported and rendered into "
                            "formatted blocks (headings #, lists, fenced "
                            "code ```lang, blockquotes >, tables, "
                            "**bold**, `code`, [links](url)); write "
                            "natural markdown, not raw HTML."
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
                        "description": (
                            "New Markdown body. Standard markdown is "
                            "rendered into formatted blocks (headings, "
                            "lists, fenced code, tables, inline marks); "
                            "replaces the note's current content."
                        ),
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
                "Search notes by text and semantic "
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
                "List notes with optional "
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


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def execute_note_tool(
    ctx: AppContext,
    tool_name: str,
    args: dict[str, Any],
    logger: Logger,
) -> ToolResult:
    """Execute one of the note CRUD tools against the knowledge backend.

    Args:
        ctx: Application context exposing ``knowledge_backend``,
            ``event_bus`` and ``config``.
        tool_name: One of :data:`NOTE_TOOL_NAMES`.
        args: Validated tool arguments from the LLM call.
        logger: Plugin logger used to record failures.

    Returns:
        A :class:`ToolResult`; an error result when the knowledge backend
        is unavailable or the operation fails.
    """
    if ctx.knowledge_backend is None:
        return ToolResult.error("Note service not available")

    start = time.perf_counter()

    if tool_name == "create_note":
        return await _handle_create(ctx, args, start, logger)
    if tool_name == "read_note":
        return await _handle_read(ctx, args, start, logger)
    if tool_name == "update_note":
        return await _handle_update(ctx, args, start, logger)
    if tool_name == "delete_note":
        return await _handle_delete(ctx, args, start, logger)
    if tool_name == "search_notes":
        return await _handle_search(ctx, args, start, logger)
    if tool_name == "list_notes":
        return await _handle_list(ctx, args, start, logger)

    return ToolResult.error(f"Unknown tool: {tool_name}")


# ---------------------------------------------------------------------------
# Private handlers
# ---------------------------------------------------------------------------

async def _handle_create(
    ctx: AppContext, args: dict[str, Any], start: float, logger: Logger,
) -> ToolResult:
    """Create a new note."""
    title = (args.get("title") or "").strip()
    if not title:
        return ToolResult.error("Missing required parameter: title")
    content = args.get("content", "")
    if len(content) > _MAX_CONTENT_CHARS:
        return ToolResult.error(
            "Content too long (max 100 000 characters)"
        )
    folder_path = args.get("folder_path", "")
    tags = args.get("tags")

    try:
        doc = await ctx.knowledge_backend.create(
            KnowledgeDocCreate(
                kind="note",
                title=title,
                content=markdown_to_html(content),
                tags=list(tags) if tags else [],
                metadata={"folder_path": folder_path},
            ),
        )
        elapsed = (time.perf_counter() - start) * 1000
        await ctx.event_bus.emit(
            AliceEvent.NOTE_CREATED,
            note_id=doc.id, title=title,
        )
        return ToolResult.ok(
            content=(
                f"Note created (id={doc.id}, "
                f"title={title!r})"
            ),
            execution_time_ms=elapsed,
        )
    except Exception as exc:
        logger.error("create_note failed: {}", exc)
        return ToolResult.error(f"Failed to create note: {exc}")


async def _handle_read(
    ctx: AppContext, args: dict[str, Any], start: float, logger: Logger,
) -> ToolResult:
    """Read a note by ID."""
    note_id = (args.get("note_id") or "").strip()
    if not note_id:
        return ToolResult.error("Missing required parameter: note_id")
    try:
        uuid.UUID(note_id)
    except ValueError:
        return ToolResult.error(f"Invalid note_id: {note_id!r}")

    try:
        doc = await ctx.knowledge_backend.get(note_id, kind="note")
        elapsed = (time.perf_counter() - start) * 1000
        if doc is None:
            return ToolResult.error(
                f"Note {note_id} not found",
                execution_time_ms=elapsed,
            )
        data = _note_doc_to_payload(doc)
        max_chars = ctx.config.continuum.note_max_content_chars_llm
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
        logger.error("read_note failed: {}", exc)
        return ToolResult.error(f"Failed to read note: {exc}")


async def _handle_update(
    ctx: AppContext, args: dict[str, Any], start: float, logger: Logger,
) -> ToolResult:
    """Update an existing note."""
    note_id = (args.get("note_id") or "").strip()
    if not note_id:
        return ToolResult.error("Missing required parameter: note_id")
    try:
        uuid.UUID(note_id)
    except ValueError:
        return ToolResult.error(f"Invalid note_id: {note_id!r}")

    content = args.get("content")
    if content is not None and len(content) > _MAX_CONTENT_CHARS:
        return ToolResult.error(
            "Content too long (max 100 000 characters)"
        )

    try:
        patch_metadata: dict[str, Any] = {}
        folder_path_arg = args.get("folder_path")
        if folder_path_arg is not None:
            patch_metadata["folder_path"] = folder_path_arg
        pinned_arg = args.get("pinned")
        if pinned_arg is not None:
            patch_metadata["pinned"] = pinned_arg

        doc = await ctx.knowledge_backend.update(
            note_id,
            KnowledgeDocPatch(
                title=args.get("title"),
                content=(
                    markdown_to_html(content)
                    if content is not None
                    else None
                ),
                tags=args.get("tags"),
                metadata=patch_metadata or None,
            ),
            kind="note",
        )
        elapsed = (time.perf_counter() - start) * 1000
        if doc is None:
            return ToolResult.error(
                f"Note {note_id} not found",
                execution_time_ms=elapsed,
            )
        await ctx.event_bus.emit(
            AliceEvent.NOTE_UPDATED, note_id=note_id,
        )
        return ToolResult.ok(
            content=f"Note {note_id} updated",
            execution_time_ms=elapsed,
        )
    except Exception as exc:
        logger.error("update_note failed: {}", exc)
        return ToolResult.error(f"Failed to update note: {exc}")


async def _handle_delete(
    ctx: AppContext, args: dict[str, Any], start: float, logger: Logger,
) -> ToolResult:
    """Delete a note by ID."""
    note_id = (args.get("note_id") or "").strip()
    if not note_id:
        return ToolResult.error("Missing required parameter: note_id")
    try:
        uuid.UUID(note_id)
    except ValueError:
        return ToolResult.error(f"Invalid note_id: {note_id!r}")

    try:
        deleted = await ctx.knowledge_backend.delete(note_id, kind="note")
        elapsed = (time.perf_counter() - start) * 1000
        if deleted:
            await ctx.event_bus.emit(
                AliceEvent.NOTE_DELETED, note_id=note_id,
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
        logger.error("delete_note failed: {}", exc)
        return ToolResult.error(f"Failed to delete note: {exc}")


async def _handle_search(
    ctx: AppContext, args: dict[str, Any], start: float, logger: Logger,
) -> ToolResult:
    """Search notes by text and semantic similarity."""
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult.error("Missing required parameter: query")

    limit = args.get("limit", 10)
    if not isinstance(limit, int) or not 1 <= limit <= 20:
        limit = 10

    try:
        search_filters: dict[str, Any] = {}
        if args.get("folder") is not None:
            search_filters["folder"] = args.get("folder")
        if args.get("tags") is not None:
            search_filters["tags"] = args.get("tags")

        hits = await ctx.knowledge_backend.search(
            query,
            kind="note",
            k=limit,
            filters=search_filters or None,
        )
        notes = [
            {
                "id": h.doc.id,
                "title": h.doc.title or "",
                "folder_path": (h.doc.metadata or {}).get(
                    "folder_path", "",
                ),
                "tags": list(h.doc.tags),
                "score": h.score,
                "updated_at": _isoformat_or_empty(h.doc.updated_at),
            }
            for h in hits
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
        logger.error("search_notes failed: {}", exc)
        return ToolResult.error(f"Failed to search notes: {exc}")


async def _handle_list(
    ctx: AppContext, args: dict[str, Any], start: float, logger: Logger,
) -> ToolResult:
    """List notes with optional filters."""
    limit = args.get("limit", 20)
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        limit = 20

    try:
        list_filters: dict[str, Any] = {}
        if args.get("folder") is not None:
            list_filters["folder"] = args.get("folder")
        if args.get("tags") is not None:
            list_filters["tags"] = args.get("tags")
        pinned_only = bool(args.get("pinned_only", False))
        if pinned_only:
            list_filters["pinned_only"] = True

        docs, total = await ctx.knowledge_backend.list(
            kind="note",
            filters=list_filters or None,
            limit=limit,
        )
        notes = [
            {
                "id": d.id,
                "title": d.title or "",
                "folder_path": (d.metadata or {}).get(
                    "folder_path", "",
                ),
                "tags": list(d.tags),
                "pinned": bool((d.metadata or {}).get("pinned", False)),
                "updated_at": _isoformat_or_empty(d.updated_at),
            }
            for d in docs
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
        logger.error("list_notes failed: {}", exc)
        return ToolResult.error(f"Failed to list notes: {exc}")
