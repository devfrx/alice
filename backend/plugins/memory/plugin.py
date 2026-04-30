"""AL\\CE — Memory plugin.

Exposes five tools — ``remember``, ``recall``, ``forget``,
``list_memories``, and ``clear_session_memory`` — that delegate to the
:class:`MemoryServiceProtocol` on the application context.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.services.knowledge import (
    KnowledgeDocCreate,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext


class MemoryPlugin(BasePlugin):
    """Persist and retrieve long-term memories via MemoryService."""

    plugin_name: str = "memory"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Persist and retrieve long-term memories. "
        "Use remember() to save facts and recall() to search them."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 90

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Store the context and verify the knowledge backend is wired.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)

        if ctx.knowledge_backend is None or ctx.memory_service is None:
            self.logger.warning(
                "Knowledge backend (memory) is not available "
                "— all memory tools will return errors"
            )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions for memory operations.

        Returns:
            A list of five ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="remember",
                description=(
                    "Save a fact to persistent memory. "
                    "Call this proactively — WITHOUT asking the user first — when they share: "
                    "preferences (food, apps, brands, habits) → category='preference'; "
                    "personal facts (job, hobby, family, birthday, city) → category='fact'; "
                    "skills or interests → category='skill'. "
                    "The tool call is mandatory; replying verbally is NOT enough. "
                    "Do NOT save: casual questions, search results, transient data, obvious conversation context."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": (
                                "The information to remember "
                                "(max 1000 characters)."
                            ),
                            "maxLength": 1000,
                        },
                        "category": {
                            "type": "string",
                            "description": (
                                "Optional category for the memory."
                            ),
                            "enum": [
                                "preference",
                                "fact",
                                "skill",
                                "context",
                            ],
                        },
                        "scope": {
                            "type": "string",
                            "description": (
                                "Memory scope: 'long_term' persists "
                                "across sessions, 'session' is temporary."
                            ),
                            "enum": ["long_term", "session"],
                            "default": "long_term",
                        },
                        "expires_hours": {
                            "type": "integer",
                            "description": (
                                "Optional expiration time in hours "
                                "(1–8760)."
                            ),
                            "minimum": 1,
                            "maximum": 8760,
                        },
                    },
                    "required": ["content"],
                },
                result_type="string",
                risk_level="safe",
                requires_confirmation=False,
            ),
            ToolDefinition(
                name="recall",
                description=(
                    "Search memories by semantic similarity. "
                    "Call this proactively when changing topic or when past context "
                    "would enrich the response — do not wait for the user to ask. "
                    "Never ask for information already stored in memory — search first."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Search query to match against memories "
                                "(max 500 characters)."
                            ),
                            "maxLength": 500,
                        },
                        "category": {
                            "type": "string",
                            "description": (
                                "Optional category filter."
                            ),
                            "enum": [
                                "preference",
                                "fact",
                                "skill",
                                "context",
                            ],
                        },
                        "limit": {
                            "type": "integer",
                            "description": (
                                "Maximum number of results (1–20). "
                                "Defaults to 5."
                            ),
                            "default": 5,
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
                name="forget",
                description=(
                    "Delete a specific memory by its ID. "
                    "Use this when the user explicitly asks to remove "
                    "a stored memory."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "memory_id": {
                            "type": "string",
                            "description": "The UUID of the memory to delete.",
                        },
                    },
                    "required": ["memory_id"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
            ),
            ToolDefinition(
                name="list_memories",
                description=(
                    "List stored memories with optional filters. "
                    "Returns memory entries sorted by creation date."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "scope": {
                            "type": "string",
                            "description": (
                                "Filter by scope: 'long_term' or 'session'."
                            ),
                            "enum": ["long_term", "session"],
                        },
                        "category": {
                            "type": "string",
                            "description": "Filter by category.",
                            "enum": [
                                "preference",
                                "fact",
                                "skill",
                                "context",
                            ],
                        },
                        "limit": {
                            "type": "integer",
                            "description": (
                                "Maximum number of results (1–50). "
                                "Defaults to 20."
                            ),
                            "default": 20,
                            "minimum": 1,
                            "maximum": 50,
                        },
                    },
                },
                result_type="json",
                risk_level="safe",
                requires_confirmation=False,
            ),
            ToolDefinition(
                name="clear_session_memory",
                description=(
                    "Delete all session-scoped memories. "
                    "Long-term memories are not affected."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested memory tool.

        Args:
            tool_name: One of the five memory tool names.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the payload or an error.
        """
        if (
            self._ctx is None
            or self._ctx.knowledge_backend is None
            or self._ctx.memory_service is None
        ):
            return ToolResult.error("Memory service not available")

        start = time.perf_counter()

        if tool_name == "remember":
            return await self._handle_remember(args, context, start)
        if tool_name == "recall":
            return await self._handle_recall(args, start)
        if tool_name == "forget":
            return await self._handle_forget(args, start)
        if tool_name == "list_memories":
            return await self._handle_list(args, start)
        if tool_name == "clear_session_memory":
            return await self._handle_clear_session(start)

        return ToolResult.error(f"Unknown tool: {tool_name}")

    # ------------------------------------------------------------------
    # Dependency / health
    # ------------------------------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Report missing dependencies.

        Returns:
            A list with ``"knowledge_backend"`` if unavailable, else empty.
        """
        if (
            self._ctx is None
            or self._ctx.knowledge_backend is None
            or self._ctx.memory_service is None
        ):
            return ["knowledge_backend"]
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED if the knowledge backend (memory) is available.

        Returns:
            Current connection status.
        """
        if (
            self._ctx
            and self._ctx.knowledge_backend is not None
            and self._ctx.memory_service is not None
        ):
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.ERROR

    # ------------------------------------------------------------------
    # Private handlers
    # ------------------------------------------------------------------

    async def _handle_remember(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
        start: float,
    ) -> ToolResult:
        """Store a new memory entry.

        Args:
            args: Must contain ``content``; may contain ``category``,
                ``scope``, ``expires_hours``.
            context: Execution metadata with conversation_id.
            start: ``time.perf_counter()`` timestamp for timing.

        Returns:
            ``ToolResult`` confirming storage or error.
        """
        content = (args.get("content") or "").strip()
        if not content:
            return ToolResult.error("Missing required parameter: content")
        if len(content) > 1000:
            return ToolResult.error(
                "Content exceeds maximum length of 1000 characters"
            )

        category = args.get("category")
        scope = args.get("scope", "long_term")
        if scope not in ("long_term", "session"):
            scope = "long_term"

        expires_at = None
        expires_hours = args.get("expires_hours")
        if expires_hours is not None:
            if isinstance(expires_hours, int) and 1 <= expires_hours <= 8760:
                expires_at = datetime.now(timezone.utc) + timedelta(
                    hours=expires_hours,
                )
            else:
                return ToolResult.error(
                    "expires_hours must be an integer between 1 and 8760"
                )

        try:
            doc = await self._ctx.knowledge_backend.create(
                KnowledgeDocCreate(
                    kind="memory",
                    content=content,
                    metadata={
                        "scope": scope,
                        "category": category,
                        "source": "llm",
                        "conversation_id": context.conversation_id,
                        "expires_at": expires_at,
                    },
                ),
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            entry_id = doc.id or "unknown"
            return ToolResult.ok(
                content=f"Memory saved (id={entry_id}, scope={scope})",
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            self.logger.error("remember failed: {}", exc)
            return ToolResult.error(f"Failed to save memory: {exc}")

    async def _handle_recall(
        self,
        args: dict[str, Any],
        start: float,
    ) -> ToolResult:
        """Search memories by semantic similarity.

        Args:
            args: Must contain ``query``; may contain ``category``, ``limit``.
            start: ``time.perf_counter()`` timestamp for timing.

        Returns:
            ``ToolResult`` with JSON results or error.
        """
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult.error("Missing required parameter: query")
        if len(query) > 500:
            return ToolResult.error(
                "Query exceeds maximum length of 500 characters"
            )

        limit = args.get("limit", 5)
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            limit = 5

        category = args.get("category")
        search_filters: dict[str, Any] | None = None
        if category:
            search_filters = {"category": category}

        try:
            hits = await self._ctx.knowledge_backend.search(
                query,
                kind="memory",
                k=limit,
                filters=search_filters,
            )
            memories = [
                {
                    "id": h.doc.id,
                    "content": h.doc.content,
                    "category": (h.doc.metadata or {}).get("category"),
                    "scope": (h.doc.metadata or {}).get("scope", ""),
                    "score": h.score,
                    "created_at": str(h.doc.created_at)
                    if h.doc.created_at is not None
                    else "",
                }
                for h in hits
            ]
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ToolResult.ok(
                content={
                    "query": query,
                    "count": len(memories),
                    "memories": memories,
                },
                content_type="application/json",
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            self.logger.error("recall failed: {}", exc)
            return ToolResult.error(f"Failed to search memories: {exc}")

    async def _handle_forget(
        self,
        args: dict[str, Any],
        start: float,
    ) -> ToolResult:
        """Delete a memory by UUID.

        Args:
            args: Must contain ``memory_id``.
            start: ``time.perf_counter()`` timestamp for timing.

        Returns:
            ``ToolResult`` confirming deletion or error.
        """
        memory_id = (args.get("memory_id") or "").strip()
        if not memory_id:
            return ToolResult.error("Missing required parameter: memory_id")

        try:
            uuid.UUID(memory_id)
        except ValueError:
            return ToolResult.error(
                f"Invalid memory_id: '{memory_id}' is not a valid UUID"
            )

        try:
            deleted = await self._ctx.memory_service.delete(memory_id)
            elapsed_ms = (time.perf_counter() - start) * 1000
            if deleted:
                return ToolResult.ok(
                    content=f"Memory {memory_id} deleted",
                    execution_time_ms=elapsed_ms,
                )
            return ToolResult.error(
                f"Memory {memory_id} not found",
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            self.logger.error("forget failed: {}", exc)
            return ToolResult.error(f"Failed to delete memory: {exc}")

    async def _handle_list(
        self,
        args: dict[str, Any],
        start: float,
    ) -> ToolResult:
        """List memories with optional filters.

        Args:
            args: May contain ``scope``, ``category``, ``limit``.
            start: ``time.perf_counter()`` timestamp for timing.

        Returns:
            ``ToolResult`` with JSON list or error.
        """
        list_filters: dict[str, Any] = {}
        scope = args.get("scope")
        if scope:
            list_filters["scope"] = scope
        category = args.get("category")
        if category:
            list_filters["category"] = category
        limit = int(args.get("limit", 50) or 50)

        try:
            docs, total = await self._ctx.knowledge_backend.list(
                kind="memory",
                filters=list_filters if list_filters else None,
                limit=limit,
            )
            memories = [
                {
                    "id": d.id,
                    "content": d.content,
                    "category": (d.metadata or {}).get("category"),
                    "scope": (d.metadata or {}).get("scope", ""),
                    "created_at": str(d.created_at)
                    if d.created_at is not None
                    else "",
                }
                for d in docs
            ]
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ToolResult.ok(
                content={
                    "total": total,
                    "count": len(memories),
                    "memories": memories,
                },
                content_type="application/json",
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            self.logger.error("list_memories failed: {}", exc)
            return ToolResult.error(f"Failed to list memories: {exc}")

    async def _handle_clear_session(self, start: float) -> ToolResult:
        """Delete all session-scoped memories.

        Args:
            start: ``time.perf_counter()`` timestamp for timing.

        Returns:
            ``ToolResult`` confirming deletion count or error.
        """
        try:
            deleted_count = await self._ctx.memory_service.delete_by_scope(
                "session",
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ToolResult.ok(
                content=(
                    f"Cleared {deleted_count} session "
                    f"memor{'y' if deleted_count == 1 else 'ies'}"
                ),
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            self.logger.error("clear_session_memory failed: {}", exc)
            return ToolResult.error(
                f"Failed to clear session memory: {exc}"
            )
