"""AL\\CE — Tool catalog REST surface (picker regole permessi, spec Fase 2 §6.3)."""

from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.core.context import AppContext

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolCatalogEntry(BaseModel):
    """Descrittore flat di un tool del registry."""

    name: str
    plugin: str
    label: str
    description: str
    capabilities: list[str]
    risk_level: Literal["safe", "medium", "dangerous", "forbidden"]
    requires_confirmation: bool
    mcp_server: str | None = None


class ToolsCatalogResponse(BaseModel):
    """Catalogo completo dei tool registrati."""

    tools: list[ToolCatalogEntry]


def _ctx(request: Request) -> AppContext:
    return cast(AppContext, request.app.state.context)


@router.get("/catalog", response_model=ToolsCatalogResponse)
async def get_tools_catalog(request: Request) -> ToolsCatalogResponse:
    """Elenco flat dei tool registrati con livello di rischio e provenienza."""
    ctx = _ctx(request)
    entries: list[ToolCatalogEntry] = []
    if ctx.tool_registry is not None:
        entries = [ToolCatalogEntry(**e) for e in ctx.tool_registry.get_tool_catalog()]
    return ToolsCatalogResponse(tools=sorted(entries, key=lambda e: e.name))
