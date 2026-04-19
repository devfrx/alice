"""AL\\CE — Artifacts REST API.

Endpoints (mounted under ``/api/artifacts``):

* ``GET    /``                     — list artifacts (filterable + paginated)
* ``GET    /{id}``                 — fetch a single artifact
* ``PATCH  /{id}/pin``             — toggle the ``pinned`` flag
* ``DELETE /{id}``                 — delete the row (and optionally the file)
* ``GET    /{id}/download``        — stream the binary
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from loguru import logger

from backend.core.config import PROJECT_ROOT
from backend.db.models import Artifact, ArtifactKind
from backend.services.artifacts import (
    ArtifactListResponse,
    ArtifactPinUpdate,
    ArtifactRead,
    ArtifactRegistry,
)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_MIME_EXTENSIONS: dict[str, str] = {
    "model/gltf-binary": ".glb",
    "model/gltf+json": ".gltf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "application/json": ".json",
}

_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _get_registry(request: Request) -> ArtifactRegistry:
    """Fetch the registry off ``app.state.context`` (503 if missing)."""
    ctx = getattr(request.app.state, "context", None)
    registry = getattr(ctx, "artifact_registry", None) if ctx else None
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Artifact registry not initialised.",
        )
    return registry


def _to_uuid(value: str) -> uuid.UUID:
    """Validate *value* as a UUID or 400."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID: {value}",
        ) from exc


def _build_download_filename(artifact: Artifact) -> str:
    """Sanitise ``artifact.title`` and append the proper extension."""
    base = _FILENAME_SAFE_RE.sub("_", artifact.title or "artifact").strip("._-")
    if not base:
        base = "artifact"
    suffix_from_path = Path(artifact.file_path).suffix
    suffix = suffix_from_path or _MIME_EXTENSIONS.get(artifact.mime, "")
    if suffix and base.lower().endswith(suffix.lower()):
        return base
    return f"{base}{suffix}"


def _resolve_artifact_path(artifact: Artifact) -> Path:
    """Resolve the on-disk path for *artifact* (relative → PROJECT_ROOT)."""
    p = Path(artifact.file_path)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ArtifactListResponse,
    summary="List artifacts",
)
async def list_artifacts(
    request: Request,
    conversation_id: str | None = Query(default=None),
    kind: ArtifactKind | None = Query(default=None),
    pinned: bool | None = Query(
        default=None,
        description="When true, return only pinned artifacts.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ArtifactListResponse:
    """Return a paginated list of artifacts."""
    registry = _get_registry(request)
    conv_uuid = _to_uuid(conversation_id) if conversation_id else None
    items, total = await registry.list_artifacts(
        conversation_id=conv_uuid,
        kind=kind,
        pinned_only=bool(pinned),
        limit=limit,
        offset=offset,
    )
    return ArtifactListResponse(
        items=[ArtifactRead.from_orm_artifact(a) for a in items],
        total=total,
    )


@router.get(
    "/{artifact_id}",
    response_model=ArtifactRead,
    summary="Get a single artifact",
)
async def get_artifact(artifact_id: str, request: Request) -> ArtifactRead:
    """Return one artifact by id (404 when missing)."""
    registry = _get_registry(request)
    artifact = await registry.get_artifact(_to_uuid(artifact_id))
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not found: {artifact_id}",
        )
    return ArtifactRead.from_orm_artifact(artifact)


@router.patch(
    "/{artifact_id}/pin",
    response_model=ArtifactRead,
    summary="Pin / unpin an artifact",
)
async def pin_artifact(
    artifact_id: str, body: ArtifactPinUpdate, request: Request,
) -> ArtifactRead:
    """Toggle the ``pinned`` flag."""
    registry = _get_registry(request)
    artifact = await registry.set_pinned(_to_uuid(artifact_id), body.pinned)
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not found: {artifact_id}",
        )
    return ArtifactRead.from_orm_artifact(artifact)


@router.delete(
    "/{artifact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an artifact",
)
async def delete_artifact(
    artifact_id: str,
    request: Request,
    delete_file: bool = Query(
        default=False,
        description="When true, also unlink the file on disk.",
    ),
) -> Response:
    """Delete an artifact and (optionally) its on-disk file."""
    registry = _get_registry(request)
    deleted = await registry.delete_artifact(
        _to_uuid(artifact_id), delete_file=delete_file,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not found: {artifact_id}",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{artifact_id}/download",
    summary="Download the binary for an artifact",
)
async def download_artifact(
    artifact_id: str, request: Request,
) -> FileResponse:
    """Stream the artifact file using its stored MIME type."""
    registry = _get_registry(request)
    artifact = await registry.get_artifact(_to_uuid(artifact_id))
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not found: {artifact_id}",
        )
    path = _resolve_artifact_path(artifact)
    if not path.exists() or not path.is_file():
        logger.warning(
            "Artifact {} points to missing file: {}", artifact.id, path,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact file is missing on disk.",
        )
    return FileResponse(
        path=str(path),
        media_type=artifact.mime,
        filename=_build_download_filename(artifact),
    )
