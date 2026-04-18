"""REST API per il recupero e la gestione delle lavagne tldraw."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import select

from backend.db.models import Conversation

router = APIRouter(prefix="/whiteboards", tags=["whiteboards"])

# Maximum serialised size of a tldraw snapshot accepted via PATCH.
# Protects the JSON store and the WS broadcast pipeline from runaway
# payloads caused by buggy or malicious clients.
_MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024  # 5 MiB


def _get_store(request: Request):
    """Recupera il WhiteboardStore dal plugin whiteboard tramite AppContext."""
    ctx = request.app.state.context
    if ctx.plugin_manager is None:
        raise HTTPException(
            status_code=503, detail="Plugin manager not available",
        )
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
    try:
        spec = await store.load(board_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=str(exc)
        ) from exc
    if spec is None:
        raise HTTPException(
            status_code=404, detail=f"Lavagna non trovata: {board_id}"
        )
    return JSONResponse(content=spec.model_dump(mode="json"))


@router.get("", summary="Lista lavagne salvate")
async def list_whiteboards(
    request: Request,
    conversation_id: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Restituisce la lista paginata delle lavagne, con filtro opzionale.

    Ogni item include ``conversation_title`` (risolto dal DB) quando la
    lavagna è associata a una conversazione.
    """
    store = _get_store(request)
    items = await store.list(
        limit=limit,
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
    try:
        deleted = await store.delete(board_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=str(exc)
        ) from exc
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Lavagna non trovata: {board_id}"
        )
    return {"status": "deleted", "board_id": board_id}


class UpdateSnapshotRequest(BaseModel):
    """Payload for updating a whiteboard snapshot."""

    snapshot: dict


@router.patch(
    "/{board_id}/snapshot",
    summary="Aggiorna lo snapshot tldraw di una lavagna",
)
async def update_snapshot(
    board_id: str, body: UpdateSnapshotRequest, request: Request,
) -> dict[str, Any]:
    """Aggiorna lo snapshot tldraw (chiamato dal frontend dopo editing)."""
    store = _get_store(request)
    # Reject oversized snapshots before they hit disk / WS broadcast.
    try:
        size = len(
            json.dumps(body.snapshot, ensure_ascii=False).encode("utf-8"),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Snapshot non serializzabile: {exc}",
        ) from exc
    if size > _MAX_SNAPSHOT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Snapshot troppo grande ({size} bytes). "
                f"Massimo consentito: {_MAX_SNAPSHOT_BYTES} bytes."
            ),
        )
    try:
        updated = await store.update_snapshot(board_id, body.snapshot)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=str(exc)
        ) from exc
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
