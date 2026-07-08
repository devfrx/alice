"""AL\\CE — MCP Memory (Knowledge Graph) management REST endpoints.

Provides a REST API to manage the MCP Memory server's knowledge graph.
Each endpoint proxies to the corresponding MCP tool via the live session,
keeping the frontend decoupled from the MCP protocol.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from backend.core.context import AppContext

if TYPE_CHECKING:
    from backend.plugins.mcp_client.plugin import McpClientPlugin
    from backend.services.mcp_session import McpSession

router = APIRouter(prefix="/mcp/memory", tags=["mcp-memory"])

_SERVER_NAME = "memory"


# ── Helpers ────────────────────────────────────────────────────────────────


def _get_memory_session(request: Request) -> McpSession:
    """Retrieve the live MCP 'memory' session.

    Raises:
        HTTPException 503: MCP client plugin or memory session unavailable.
    """
    ctx: AppContext = request.app.state.context
    if ctx.plugin_manager is None:
        raise HTTPException(503, "Plugin manager not available")

    plugin: McpClientPlugin | None = ctx.plugin_manager.get_plugin("mcp_client")
    if plugin is None:
        raise HTTPException(503, "MCP client plugin not loaded")

    # Use the plugin's public accessor to fetch the live session.
    session = plugin.get_session(_SERVER_NAME)
    if session is None:
        raise HTTPException(503, f"MCP server '{_SERVER_NAME}' not connected")

    return session


async def _call(session: McpSession, tool: str, args: dict[str, Any]) -> Any:
    """Call an MCP tool and parse the JSON response.

    Returns:
        Parsed JSON content from the tool result.

    Raises:
        HTTPException 502: Tool returned non-JSON or failed.
    """
    try:
        raw = await session.call_tool(tool, args)
    except Exception as exc:
        logger.warning("MCP memory tool '{}' failed: {}", tool, exc)
        raise HTTPException(502, f"MCP tool '{tool}' failed: {exc}")

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"result": raw}


# ── Request models ─────────────────────────────────────────────────────────


class EntityInput(BaseModel):
    """Single entity to create."""

    name: str
    entityType: str
    observations: list[str] = []


class CreateEntitiesRequest(BaseModel):
    """Request body for creating entities."""

    entities: list[EntityInput]


class RelationInput(BaseModel):
    """Single relation between entities."""

    from_entity: str = Field(alias="from")
    to: str
    relationType: str

    model_config = {"populate_by_name": True}


class CreateRelationsRequest(BaseModel):
    """Request body for creating relations."""

    relations: list[RelationInput]


class ObservationInput(BaseModel):
    """Observations to add to an entity."""

    entityName: str
    contents: list[str]


class AddObservationsRequest(BaseModel):
    """Request body for adding observations to existing entities."""

    observations: list[ObservationInput]


class DeleteEntitiesRequest(BaseModel):
    """Request body for deleting entities."""

    entityNames: list[str]


class DeleteObservationItem(BaseModel):
    """Observations to remove from an entity."""

    entityName: str
    observations: list[str]


class DeleteObservationsRequest(BaseModel):
    """Request body for deleting observations."""

    deletions: list[DeleteObservationItem]


class DeleteRelationsRequest(BaseModel):
    """Request body for deleting relations."""

    relations: list[RelationInput]


class SearchRequest(BaseModel):
    """Request body for searching the knowledge graph."""

    query: str


class OpenNodesRequest(BaseModel):
    """Request body for opening specific nodes."""

    names: list[str]


# ── Response models ────────────────────────────────────────────────────────


class KGEntityRead(BaseModel):
    """Entity node as returned by the MCP memory server."""

    name: str
    entityType: str  # noqa: N815 — MCP server field name (camelCase, as in EntityInput)
    observations: list[str]


class KGRelationRead(BaseModel):
    """Directed relation between two entities."""

    from_entity: str = Field(alias="from")
    to: str
    relationType: str  # noqa: N815 — MCP server field name (camelCase, as in RelationInput)

    model_config = {"populate_by_name": True}


class KGGraphResponse(BaseModel):
    """Knowledge-graph snapshot (entities + relations)."""

    entities: list[KGEntityRead]
    relations: list[KGRelationRead]


class KGMutationResponse(BaseModel):
    """Mutation acknowledgement (the client reloads the graph)."""

    ok: bool = True


def _graph(data: Any) -> KGGraphResponse:
    """Normalise an MCP tool result to a graph (empty on unexpected shape)."""
    try:
        return KGGraphResponse.model_validate(data)
    except ValidationError:
        logger.warning("MCP memory returned an unexpected graph shape")
        return KGGraphResponse(entities=[], relations=[])


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/graph", response_model=KGGraphResponse)
async def read_graph(request: Request) -> KGGraphResponse:
    """Read the entire knowledge graph (entities + relations)."""
    session = _get_memory_session(request)
    return _graph(await _call(session, "read_graph", {}))


@router.post("/search", response_model=KGGraphResponse)
async def search_nodes(request: Request, body: SearchRequest) -> KGGraphResponse:
    """Search entities by query across names, types, and observations."""
    session = _get_memory_session(request)
    return _graph(await _call(session, "search_nodes", {"query": body.query}))


@router.post("/nodes", response_model=KGGraphResponse)
async def open_nodes(request: Request, body: OpenNodesRequest) -> KGGraphResponse:
    """Retrieve specific entities by name with their relations."""
    session = _get_memory_session(request)
    return _graph(await _call(session, "open_nodes", {"names": body.names}))


@router.post("/entities", response_model=KGMutationResponse)
async def create_entities(
    request: Request, body: CreateEntitiesRequest,
) -> KGMutationResponse:
    """Create new entities in the knowledge graph."""
    session = _get_memory_session(request)
    entities = [
        {
            "name": e.name,
            "entityType": e.entityType,
            "observations": e.observations,
        }
        for e in body.entities
    ]
    await _call(session, "create_entities", {"entities": entities})
    return KGMutationResponse()


@router.delete("/entities", response_model=KGMutationResponse)
async def delete_entities(
    request: Request, body: DeleteEntitiesRequest,
) -> KGMutationResponse:
    """Delete entities and their associated relations."""
    session = _get_memory_session(request)
    await _call(
        session, "delete_entities", {"entityNames": body.entityNames},
    )
    return KGMutationResponse()


@router.post("/relations", response_model=KGMutationResponse)
async def create_relations(
    request: Request, body: CreateRelationsRequest,
) -> KGMutationResponse:
    """Create new relations between entities."""
    session = _get_memory_session(request)
    relations = [
        {"from": r.from_entity, "to": r.to, "relationType": r.relationType}
        for r in body.relations
    ]
    await _call(session, "create_relations", {"relations": relations})
    return KGMutationResponse()


@router.delete("/relations", response_model=KGMutationResponse)
async def delete_relations(
    request: Request, body: DeleteRelationsRequest,
) -> KGMutationResponse:
    """Delete specific relations."""
    session = _get_memory_session(request)
    relations = [
        {"from": r.from_entity, "to": r.to, "relationType": r.relationType}
        for r in body.relations
    ]
    await _call(session, "delete_relations", {"relations": relations})
    return KGMutationResponse()


@router.post("/observations", response_model=KGMutationResponse)
async def add_observations(
    request: Request, body: AddObservationsRequest,
) -> KGMutationResponse:
    """Add observations to existing entities."""
    session = _get_memory_session(request)
    observations = [
        {"entityName": o.entityName, "contents": o.contents}
        for o in body.observations
    ]
    await _call(
        session, "add_observations", {"observations": observations},
    )
    return KGMutationResponse()


@router.delete("/observations", response_model=KGMutationResponse)
async def delete_observations(
    request: Request, body: DeleteObservationsRequest,
) -> KGMutationResponse:
    """Remove specific observations from entities."""
    session = _get_memory_session(request)
    deletions = [
        {"entityName": d.entityName, "observations": d.observations}
        for d in body.deletions
    ]
    await _call(
        session, "delete_observations", {"deletions": deletions},
    )
    return KGMutationResponse()
