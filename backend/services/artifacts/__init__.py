"""AL\\CE — Artifacts subsystem.

Public API for the unified artifact registry.  Tools that produce
binary outputs (3D models, images, audio, charts, …) feed their
results into the registry, which persists a row in the ``artifacts``
table and broadcasts a ``artifact.created`` event over the global
WebSocket.
"""

from backend.services.artifacts.blob_store import ArtifactBlobStore
from backend.services.artifacts.parsers import (
    ArtifactDescriptor,
    parse_tool_payload,
    register_parser,
)
from backend.services.artifacts.registry import ArtifactRegistry
from backend.services.artifacts.schemas import (
    ArtifactContentResponse,
    ArtifactContentUpdate,
    ArtifactContentUpdateResponse,
    ArtifactListResponse,
    ArtifactPinUpdate,
    ArtifactRead,
)

__all__ = [
    "ArtifactBlobStore",
    "ArtifactContentResponse",
    "ArtifactContentUpdate",
    "ArtifactContentUpdateResponse",
    "ArtifactDescriptor",
    "ArtifactListResponse",
    "ArtifactPinUpdate",
    "ArtifactRead",
    "ArtifactRegistry",
    "parse_tool_payload",
    "register_parser",
]
