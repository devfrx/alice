"""REST API per il recupero e la gestione delle lavagne tldraw."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import select

from backend.db.models import Conversation

router = APIRouter(prefix="/whiteboards", tags=["whiteboards"])


def _get_store(request: Request):
    """Recupera il WhiteboardStore dal plugin whiteboard tramite AppContext."""
    ctx = request.app.state.context
    plugin = ctx.plugin_manager.get_plugin("whiteboard")
    if plugin is None or not ctx.config.whiteboard.enabled:
        raise HTTPException(
            status_code=503, detail="Plugin whiteboard non disponibile."
        )
    store = plugin.store
    if store is None:
        raise HTTPException(
            status_code=503, detail="WhiteboardStore non inizializzato."
        )
    return store


@router.get("/{board_id}", summary="Recupera la spec completa di una lavagna")
async def get_whiteboard(board_id: str, request: Request) -> JSONResponse:
    """Restituisce il JSON completo della WhiteboardSpec (incluso snapshot)."""
    store = _get_store(request)
    spec = await store.load(board_id)
    if spec is None:
        raise HTTPException(
            status_code=404, detail=f"Lavagna non trovata: {board_id}"
        )
    return JSONResponse(content=spec.model_dump(mode="json"))


@router.get("", summary="Lista lavagne salvate")
async def list_whiteboards(
    request: Request,
    conversation_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Restituisce la lista paginata delle lavagne, con filtro opzionale.

    Ogni item include ``conversation_title`` (risolto dal DB) quando la
    lavagna è associata a una conversazione.
    """
    store = _get_store(request)
    items = await store.list(
        limit=min(limit, 100),
        offset=offset,
        conversation_id=conversation_id,
    )
    total = await store.count()

    # Resolve conversation titles for all board items.
    conv_ids = {
        item.conversation_id
        for item in items
        if item.conversation_id
    }
    title_map: dict[str, str | None] = {}
    if conv_ids:
        ctx = request.app.state.context
        if ctx.db:
            async with ctx.db() as session:
                uuids = [uuid.UUID(cid) for cid in conv_ids]
                result = await session.exec(
                    select(Conversation.id, Conversation.title).where(
                        Conversation.id.in_(uuids)  # type: ignore[union-attr]
                    )
                )
                for row in result.all():
                    title_map[str(row.id)] = row.title

    serialized = []
    for item in items:
        d = item.model_dump(mode="json")
        d["conversation_title"] = title_map.get(
            item.conversation_id or ""
        )
        serialized.append(d)

    return {
        "items": serialized,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.delete("/{board_id}", summary="Elimina una lavagna")
async def delete_whiteboard(
    board_id: str, request: Request
) -> dict[str, str]:
    """Elimina il file JSON della lavagna dal disco."""
    store = _get_store(request)
    deleted = await store.delete(board_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Lavagna non trovata: {board_id}"
        )
    return {"status": "deleted", "board_id": board_id}


@router.patch(
    "/{board_id}/snapshot",
    summary="Aggiorna lo snapshot tldraw di una lavagna",
)
async def update_snapshot(
    board_id: str, request: Request
) -> dict[str, Any]:
    """Aggiorna lo snapshot tldraw (chiamato dal frontend dopo editing)."""
    store = _get_store(request)
    body = await request.json()
    snapshot = body.get("snapshot")
    if not isinstance(snapshot, dict):
        raise HTTPException(
            status_code=422,
            detail="Body deve contenere un campo 'snapshot' di tipo oggetto.",
        )

    updated = await store.update_snapshot(board_id, snapshot)
    if not updated:
        raise HTTPException(
            status_code=404, detail=f"Lavagna non trovata: {board_id}"
        )

    spec = await store.load(board_id)
    return {
        "status": "ok",
        "board_id": board_id,
        "updated_at": spec.updated_at.isoformat() if spec else None,
    }
