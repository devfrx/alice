"""AL\\CE — Pydantic schemas for the Artifacts REST API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from backend.db.models import Artifact, ArtifactKind


class ArtifactRead(BaseModel):
    """Public representation of an :class:`Artifact` row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    tool_call_id: str | None = None
    kind: ArtifactKind
    title: str
    file_path: str
    mime: str
    size_bytes: int
    artifact_metadata: dict[str, Any] = Field(default_factory=dict)
    pinned: bool = False
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def download_url(self) -> str:
        """Convenience URL for the binary download endpoint."""
        return f"/api/artifacts/{self.id}/download"

    @classmethod
    def from_orm_artifact(cls, artifact: Artifact) -> "ArtifactRead":
        """Build a schema instance from an ORM row."""
        return cls.model_validate(artifact, from_attributes=True)


class ArtifactListResponse(BaseModel):
    """Paginated list of artifacts."""

    items: list[ArtifactRead]
    total: int


class ArtifactPinUpdate(BaseModel):
    """Body of ``PATCH /api/artifacts/{id}/pin``."""

    pinned: bool
