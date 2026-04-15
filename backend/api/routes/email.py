"""REST API per l'Email Assistant (lettura, ricerca, gestione)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

_IMAP_ERRORS = (ConnectionError, OSError)

router = APIRouter(prefix="/email", tags=["email"])


def _validate_uid(uid: str) -> None:
    """Validate that an IMAP UID is a non-empty numeric string."""
    if not uid or not uid.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"UID non valido: {uid!r} (deve essere numerico)",
        )


def _get_email_service(request: Request):
    """Recupera EmailService dal contesto; 503 se non disponibile."""
    ctx = request.app.state.context
    if not ctx.config.email.enabled or ctx.email_service is None:
        raise HTTPException(
            status_code=503,
            detail="Email service non disponibile.",
        )
    return ctx.email_service


# ── Folders (MUST be before /{uid} to avoid path conflict) ─────────────


@router.get("/folders", summary="Lista cartelle IMAP")
async def list_folders(request: Request) -> list[str]:
    """Restituisce le cartelle IMAP disponibili."""
    svc = _get_email_service(request)
    try:
        return await svc.list_folders()
    except _IMAP_ERRORS as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


# ── Inbox ──────────────────────────────────────────────────────────────


@router.get("/inbox", summary="Lista email recenti")
async def get_inbox(
    request: Request,
    folder: str = "INBOX",
    limit: int | None = Query(None, ge=1),
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    """Restituisce le intestazioni delle email più recenti."""
    cfg = request.app.state.context.config.email
    svc = _get_email_service(request)
    try:
        return await svc.fetch_inbox(
            folder=folder,
            limit=min(limit or cfg.fetch_last_n, cfg.max_fetch),
            unread_only=unread_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except _IMAP_ERRORS as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@router.get("/{uid}", summary="Leggi email completa")
async def get_email(
    uid: str, request: Request, folder: str = "INBOX",
) -> dict[str, Any]:
    """Restituisce headers + body plain-text di una email."""
    svc = _get_email_service(request)
    _validate_uid(uid)
    try:
        mail = await svc.fetch_email(uid, folder=folder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except _IMAP_ERRORS as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    if mail is None:
        raise HTTPException(
            status_code=404, detail=f"Email non trovata: {uid}",
        )
    return mail


# ── Search ─────────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    """Payload for email search."""

    query: str
    folder: str = "INBOX"
    limit: int | None = Field(None, ge=1)


@router.post("/search", summary="Cerca email (IMAP SEARCH)")
async def search_emails(
    body: SearchRequest, request: Request,
) -> list[dict[str, Any]]:
    """Cerca email con criteri IMAP standard."""
    cfg = request.app.state.context.config.email
    svc = _get_email_service(request)
    try:
        return await svc.search(
            body.query,
            folder=body.folder,
            limit=min(body.limit or cfg.fetch_last_n, cfg.max_fetch),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except _IMAP_ERRORS as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


# ── Actions ────────────────────────────────────────────────────────────


@router.put("/{uid}/read", summary="Segna come letta/non letta")
async def mark_read(
    uid: str,
    request: Request,
    folder: str = "INBOX",
    read: bool = True,
) -> dict[str, bool]:
    """Imposta o rimuove il flag \\Seen."""
    svc = _get_email_service(request)
    _validate_uid(uid)
    try:
        ok = await svc.mark_read(uid, folder=folder, read=read)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except _IMAP_ERRORS as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    if not ok:
        logger.warning(
            "mark_read failed for uid={} folder={}", uid, folder,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Impossibile aggiornare flag per {uid}",
        )
    return {"success": True}


@router.put("/{uid}/archive", summary="Archivia email")
async def archive_email(
    uid: str, request: Request, from_folder: str = "INBOX",
) -> dict[str, bool]:
    """Sposta l'email nella cartella di archivio configurata."""
    svc = _get_email_service(request)
    _validate_uid(uid)
    try:
        ok = await svc.archive(uid, from_folder=from_folder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except _IMAP_ERRORS as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    if not ok:
        logger.warning(
            "archive failed for uid={} from_folder={}",
            uid, from_folder,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Archiviazione fallita per {uid}",
        )
    return {"success": True}
