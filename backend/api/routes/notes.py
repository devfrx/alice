"""AL\\CE — Notes REST endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from backend.core.event_bus import AliceEvent

router = APIRouter(prefix="/notes", tags=["notes"])


# ----------------------------------------------------------------------- #
# Request / response models
# ----------------------------------------------------------------------- #


class CreateNoteRequest(BaseModel):
    """Body for POST /notes."""

    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field("", max_length=100_000)
    folder_path: str = Field("", max_length=500)
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [t.strip() for t in v if t.strip()]

    @field_validator("folder_path")
    @classmethod
    def _validate_folder_path(cls, v: str) -> str:
        if v and (".." in v or v.startswith("/")):
            raise ValueError("Invalid folder path")
        return v.strip("/")


class UpdateNoteRequest(BaseModel):
    """Body for PUT /notes/{note_id}."""

    title: str | None = Field(None, min_length=1, max_length=500)
    content: str | None = Field(None, max_length=100_000)
    folder_path: str | None = Field(None, max_length=500)
    tags: list[str] | None = None
    pinned: bool | None = None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [t.strip() for t in v if t.strip()]

    @field_validator("folder_path")
    @classmethod
    def _validate_folder_path(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v and (".." in v or v.startswith("/")):
            raise ValueError("Invalid folder path")
        return v.strip("/")


class SearchNotesRequest(BaseModel):
    """Body for POST /notes/search."""

    query: str = Field(..., min_length=1, max_length=500)
    folder: str | None = None
    tags: list[str] | None = None
    limit: int = Field(10, ge=1, le=50)


# ----------------------------------------------------------------------- #
# Helpers
# ----------------------------------------------------------------------- #


def _get_note_service(request: Request):
    """Extract note_service from app context or raise 503."""
    ctx = request.app.state.context
    svc = ctx.note_service
    if svc is None:
        raise HTTPException(
            status_code=503, detail="Note service not available",
        )
    return svc


def _serialize_note(entry: Any) -> dict[str, Any]:
    """Normalise a note entry to a JSON-safe dict."""
    if hasattr(entry, "to_dict"):
        return entry.to_dict()
    if hasattr(entry, "__dict__"):
        return dict(entry.__dict__)
    return dict(entry)


def _validate_uuid(value: str) -> None:
    """Raise 400 if *value* is not a valid UUID."""
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid note ID format",
        )


# ----------------------------------------------------------------------- #
# Endpoints
# ----------------------------------------------------------------------- #


@router.get("")
async def list_notes(
    request: Request,
    folder: str | None = Query(None, description="Filter by folder"),
    tags: str | None = Query(
        None, description="Comma-separated tag filter",
    ),
    pinned: bool | None = Query(None, description="Pinned only"),
    q: str | None = Query(None, description="Quick text search"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List notes with optional filters."""
    svc = _get_note_service(request)

    tag_list = (
        [t.strip() for t in tags.split(",") if t.strip()]
        if tags else None
    )

    # Quick search shortcut
    if q:
        results = await svc.search(
            query=q, folder=folder, tags=tag_list, limit=limit,
        )
        entries = [
            r["entry"] for r in results
            if not pinned or r["entry"].pinned
        ]
        return {
            "notes": [_serialize_note(e) for e in entries],
            "total": len(entries),
        }

    entries, total = await svc.list(
        folder=folder,
        tags=tag_list,
        pinned_only=bool(pinned),
        limit=limit,
        offset=offset,
    )
    return {
        "notes": [_serialize_note(e) for e in entries],
        "total": total,
    }


@router.post("", status_code=201)
async def create_note(
    request: Request,
    body: CreateNoteRequest,
) -> dict[str, Any]:
    """Create a new note."""
    svc = _get_note_service(request)

    entry = await svc.create(
        title=body.title,
        content=body.content,
        folder_path=body.folder_path,
        tags=body.tags,
    )
    logger.info("Note created via API: {}", entry.id)

    ctx = request.app.state.context
    await ctx.event_bus.emit(
        AliceEvent.NOTE_CREATED, note_id=entry.id, title=entry.title,
    )
    return _serialize_note(entry)


class DeleteFolderRequest(BaseModel):
    """Body for DELETE /notes/folders."""

    folder_path: str = Field(..., min_length=1, max_length=500)
    mode: str = Field("move", pattern=r"^(move|delete)$")


@router.get("/folders")
async def list_folders(request: Request) -> list[dict[str, Any]]:
    """List all folders with note counts."""
    svc = _get_note_service(request)
    return await svc.get_folders()


@router.post("/folders/delete")
async def delete_folder(
    request: Request,
    body: DeleteFolderRequest,
) -> dict[str, Any]:
    """Delete a folder. ``mode`` = ``move`` (notes → root) or ``delete``."""
    svc = _get_note_service(request)
    affected = await svc.delete_folder(body.folder_path, mode=body.mode)
    logger.info(
        "Folder {!r} removed via API (mode={}, affected={})",
        body.folder_path, body.mode, affected,
    )
    return {"affected": affected, "mode": body.mode}


@router.get("/{note_id}")
async def get_note(request: Request, note_id: str) -> dict[str, Any]:
    """Get a single note by ID."""
    svc = _get_note_service(request)
    _validate_uuid(note_id)

    entry = await svc.get(note_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return _serialize_note(entry)


@router.put("/{note_id}")
async def update_note(
    request: Request,
    note_id: str,
    body: UpdateNoteRequest,
) -> dict[str, Any]:
    """Update a note."""
    svc = _get_note_service(request)
    _validate_uuid(note_id)

    entry = await svc.update(
        note_id,
        title=body.title,
        content=body.content,
        folder_path=body.folder_path,
        tags=body.tags,
        pinned=body.pinned,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Note not found")

    ctx = request.app.state.context
    await ctx.event_bus.emit(
        AliceEvent.NOTE_UPDATED, note_id=note_id,
    )
    logger.info("Note updated via API: {}", note_id)
    return _serialize_note(entry)


@router.delete("/{note_id}")
async def delete_note(
    request: Request,
    note_id: str,
) -> dict[str, bool]:
    """Delete a note by ID."""
    svc = _get_note_service(request)
    _validate_uuid(note_id)

    deleted = await svc.delete(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")

    ctx = request.app.state.context
    await ctx.event_bus.emit(
        AliceEvent.NOTE_DELETED, note_id=note_id,
    )
    logger.info("Note deleted via API: {}", note_id)
    return {"deleted": True}


@router.post("/search")
async def search_notes(
    request: Request,
    body: SearchNotesRequest,
) -> dict[str, Any]:
    """Search notes via FTS5 + semantic similarity."""
    svc = _get_note_service(request)

    results = await svc.search(
        query=body.query,
        folder=body.folder,
        tags=body.tags,
        limit=body.limit,
    )

    serialized = [
        {**_serialize_note(item["entry"]), "score": item["score"]}
        for item in results
    ]
    return {"results": serialized}
