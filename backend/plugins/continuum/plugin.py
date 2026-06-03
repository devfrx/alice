"""AL\\CE — Continuum plugin.

Exposes every Continuum surface to the LLM as tools: note CRUD
(``create_note``/``read_note``/``update_note``/``delete_note``/
``search_notes``/``list_notes``) plus the structured surfaces (folders,
kinds, databases, graph) and the client-executed live-editor block tools.
Note CRUD routes through the application's knowledge backend, which
delegates note storage to the Continuum server; the structured surfaces
use the plugin's own :class:`ContinuumClient`.

The plugin owns its :class:`ContinuumClient` built from
``config.continuum`` during :meth:`initialize`, reusing the instance the
knowledge backend already wired so the folder path↔id cache stays
coherent. Only ``delete_note`` is destructive and requires confirmation;
every other server-side tool is read-oriented or additive.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.continuum.definitions import (
    build_client_tool_definitions,
    build_tool_definitions,
)
from backend.plugins.continuum.note_tools import (
    NOTE_TOOL_NAMES,
    build_note_tool_definitions,
    execute_note_tool,
)
from backend.services.knowledge.continuum_client import (
    ContinuumClient,
    ContinuumError,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext


#: Names of tools that are executed on the connected client (the Continuum
#: web editor), never on the server. They are exposed by this plugin so the
#: scoped agent can call them, but their execution is delegated over the
#: chat WebSocket — see :class:`ToolDefinition.client_execution`.
_CLIENT_EXECUTED_TOOLS: frozenset[str] = frozenset(
    t.name for t in build_client_tool_definitions()
)


class ContinuumPlugin(BasePlugin):
    """Expose Continuum's structured knowledge surfaces as LLM tools."""

    plugin_name: str = "continuum"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Interact with the Continuum knowledge base: create, read, update, "
        "delete and search notes; browse folders and kinds; query "
        "databases; and traverse the knowledge graph."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 80

    def __init__(self) -> None:
        super().__init__()
        self._client: ContinuumClient | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def initialize(self, ctx: AppContext) -> None:
        """Build the Continuum client from configuration."""
        await super().initialize(ctx)
        cfg = ctx.config.continuum
        if not cfg.enabled:
            self.logger.warning(
                "Continuum integration is disabled "
                "(config.continuum.enabled=False) — tools will return errors"
            )
            return
        # Reuse the client the knowledge backend already wired (so the
        # folder path↔id cache stays coherent across note placement and
        # the folder mutations this plugin performs). Fall back to a
        # self-built client when none is shared (e.g. continuum enabled as
        # a tool surface without the note backend).
        shared = getattr(ctx, "continuum_client", None)
        self._client = shared or ContinuumClient(
            base_url=cfg.base_url,
            api_token=cfg.api_token,
            timeout_s=cfg.timeout_s,
            folder_cache_ttl_s=cfg.folder_cache_ttl_s,
        )

    # ------------------------------------------------------------------ #
    # Tools
    # ------------------------------------------------------------------ #

    def get_tools(self) -> list[ToolDefinition]:
        """Return the Continuum tool definitions.

        Combines the note CRUD tools with the server-side structured-surface
        tools and the client-executed live-editor block tools. The latter
        never run on the server (see :meth:`execute_tool`); they are
        delegated to the connected web client by the chat WebSocket.
        """
        return (
            build_note_tool_definitions()
            + build_tool_definitions()
            + build_client_tool_definitions()
        )

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested Continuum tool."""
        if tool_name in _CLIENT_EXECUTED_TOOLS:
            # Defensive: client-executed block tools must be delegated to the
            # web client over the chat WebSocket and never reach the server.
            # If one lands here, the round-trip wiring is misconfigured.
            return ToolResult.error(
                f"Tool '{tool_name}' is client-executed and cannot run on "
                "the server; it must be delegated to the Continuum editor."
            )
        if self._client is None:
            return ToolResult.error("Continuum integration is not available")

        if tool_name in NOTE_TOOL_NAMES:
            # Note CRUD routes through the shared knowledge backend (which
            # delegates note storage to Continuum), not the plugin's client.
            return await execute_note_tool(
                self._ctx, tool_name, args, self.logger,
            )

        start = time.perf_counter()
        handlers = {
            "list_folders": self._list_folders,
            "create_folder": self._create_folder,
            "list_kinds": self._list_kinds,
            "list_databases": self._list_databases,
            "get_database": self._get_database,
            "query_database": self._query_database,
            "graph_query": self._graph_query,
            "note_backlinks": self._note_backlinks,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return ToolResult.error(f"Unknown tool: {tool_name}")

        try:
            return await handler(args, start)
        except ContinuumError as exc:
            self.logger.error("{} failed: {}", tool_name, exc)
            return ToolResult.error(f"Continuum error: {exc}")
        except Exception as exc:  # noqa: BLE001 — surface any failure as a tool error
            self.logger.error("{} crashed: {}", tool_name, exc)
            return ToolResult.error(f"Failed to run {tool_name}: {exc}")

    # ------------------------------------------------------------------ #
    # Dependency / health
    # ------------------------------------------------------------------ #

    def check_dependencies(self) -> list[str]:
        """Report missing dependencies."""
        return [] if self._client is not None else ["continuum"]

    async def get_connection_status(self) -> ConnectionStatus:
        """Probe the Continuum server with a cheap authenticated call."""
        if self._client is None:
            return ConnectionStatus.ERROR
        try:
            await self._client.request("GET", "/folders")
        except ContinuumError:
            return ConnectionStatus.ERROR
        return ConnectionStatus.CONNECTED

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _result(content: Any, start: float) -> ToolResult:
        """Build a JSON ``ToolResult`` with elapsed timing."""
        return ToolResult.ok(
            content=content,
            content_type="application/json",
            execution_time_ms=(time.perf_counter() - start) * 1000,
        )

    async def _list_folders(self, args: dict[str, Any], start: float) -> ToolResult:
        assert self._client is not None
        forest = await self._client.request("GET", "/folders") or []
        return self._result({"folders": forest, "count": len(forest)}, start)

    async def _create_folder(self, args: dict[str, Any], start: float) -> ToolResult:
        assert self._client is not None
        name = (args.get("name") or "").strip()
        if not name:
            return ToolResult.error("Missing required parameter: name")
        body: dict[str, Any] = {"name": name}
        parent_id = args.get("parent_id")
        if parent_id:
            body["parentId"] = parent_id
        folder = await self._client.request("POST", "/folders", json=body)
        # The folder tree changed — drop the cached path↔id map so the next
        # note placement into this folder resolves it instead of falling
        # back to root within the cache TTL window.
        self._client.invalidate_folder_cache()
        return self._result(folder, start)

    async def _list_kinds(self, args: dict[str, Any], start: float) -> ToolResult:
        assert self._client is not None
        kinds = await self._client.request("GET", "/kinds") or []
        return self._result({"kinds": kinds, "count": len(kinds)}, start)

    async def _list_databases(self, args: dict[str, Any], start: float) -> ToolResult:
        assert self._client is not None
        dbs = await self._client.request("GET", "/databases") or []
        return self._result({"databases": dbs, "count": len(dbs)}, start)

    async def _get_database(self, args: dict[str, Any], start: float) -> ToolResult:
        assert self._client is not None
        database_id = (args.get("database_id") or "").strip()
        if not database_id:
            return ToolResult.error("Missing required parameter: database_id")
        bundle = await self._client.request("GET", f"/databases/{database_id}")
        return self._result(bundle, start)

    async def _query_database(self, args: dict[str, Any], start: float) -> ToolResult:
        assert self._client is not None
        database_id = (args.get("database_id") or "").strip()
        if not database_id:
            return ToolResult.error("Missing required parameter: database_id")
        body: dict[str, Any] = {}
        if isinstance(args.get("config"), dict):
            body["config"] = args["config"]
        if isinstance(args.get("pagination"), dict):
            body["pagination"] = args["pagination"]
        result = await self._client.request(
            "POST", f"/databases/{database_id}/query", json=body,
        )
        return self._result(result, start)

    async def _graph_query(self, args: dict[str, Any], start: float) -> ToolResult:
        assert self._client is not None
        include_properties = args.get("include_properties")
        property_keys = include_properties if isinstance(include_properties, list) else []
        body: dict[str, Any] = {
            "filter": args.get("filter") if isinstance(args.get("filter"), dict) else {
                "type": "group", "id": "root", "combinator": "and", "children": [],
            },
            "edgeSources": args.get("edge_sources") if isinstance(args.get("edge_sources"), dict) else {
                "includeLinks": True,
                "allRelationProperties": True,
                "relationPropertyKeys": [],
            },
            "includeProperties": [
                item for item in property_keys
                if isinstance(item, str) and item
            ],
            "includeMetrics": bool(args.get("include_metrics")),
        }
        limit = args.get("limit")
        result = await self._client.request("POST", "/graph/query", json=body)
        if isinstance(limit, int) and 1 <= limit <= 200 and isinstance(result, dict):
            nodes = result.get("nodes")
            edges = result.get("edges")
            if isinstance(nodes, list) and isinstance(edges, list):
                limited_nodes = nodes[:limit]
                kept = {
                    node.get("id") for node in limited_nodes
                    if isinstance(node, dict) and node.get("id")
                }
                result = {
                    **result,
                    "nodes": limited_nodes,
                    "edges": [
                        edge for edge in edges
                        if isinstance(edge, dict)
                        and edge.get("source") in kept
                        and edge.get("target") in kept
                    ],
                }
        return self._result(result, start)

    async def _note_backlinks(self, args: dict[str, Any], start: float) -> ToolResult:
        assert self._client is not None
        note_id = (args.get("note_id") or "").strip()
        if not note_id:
            return ToolResult.error("Missing required parameter: note_id")
        backlinks = await self._client.request("GET", f"/notes/{note_id}/backlinks")
        return self._result(
            {"note_id": note_id, "backlinks": backlinks or []}, start,
        )
