"""AL\\CE — Tool payload → :class:`ArtifactDescriptor` parsers.

A *parser* takes the JSON payload returned by a tool and converts it
into an :class:`ArtifactDescriptor`, which carries the minimal fields
required to persist a row in the ``artifacts`` table.

New parsers are registered via :func:`register_parser` (decorator
syntax also supported) so this module stays open for extension and
closed for modification.  If no parser is registered for a tool name,
:func:`parse_tool_payload` returns ``None`` and the tool result is
silently ignored by the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from loguru import logger

from backend.db.models import ArtifactKind


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ArtifactDescriptor:
    """In-memory description of an artifact, before DB persistence.

    Attributes:
        kind: One of :class:`ArtifactKind`.
        title: Human-readable label (truncated to fit ``Artifact.title``).
        file_path: Absolute or relative path on disk.
        mime: IANA media type (e.g. ``model/gltf-binary``).
        size_bytes: File size in bytes (zero if unknown).
        metadata: Free-form JSON-serialisable metadata.
    """

    kind: ArtifactKind
    title: str
    file_path: str
    mime: str
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parser registry
# ---------------------------------------------------------------------------


ParserFn = Callable[[dict[str, Any], str | None], ArtifactDescriptor | None]
"""Signature: ``(payload, content_type) -> ArtifactDescriptor | None``."""


_PARSERS: dict[str, ParserFn] = {}


def register_parser(tool_name: str) -> Callable[[ParserFn], ParserFn]:
    """Decorator: register *fn* as the parser for *tool_name*.

    Example::

        @register_parser("my_tool")
        def _parse(payload, content_type):
            ...
    """

    def _decorator(fn: ParserFn) -> ParserFn:
        _PARSERS[tool_name] = fn
        return fn

    return _decorator


def parse_tool_payload(
    tool_name: str,
    payload: dict[str, Any],
    content_type: str | None,
) -> ArtifactDescriptor | None:
    """Parse a tool result into an :class:`ArtifactDescriptor`.

    Returns ``None`` (without raising) when:

    * no parser is registered for *tool_name*; or
    * the registered parser returns ``None`` (malformed payload).
    """
    parser = _PARSERS.get(tool_name)
    if parser is None:
        return None
    try:
        return parser(payload, content_type)
    except Exception as exc:  # never propagate — registry must stay silent
        logger.warning(
            "Artifact parser '{}' failed: {}", tool_name, exc,
        )
        return None


def _truncate_title(text: str, limit: int = 80) -> str:
    """Return *text* clipped to *limit* chars (with ellipsis if needed)."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text or "(untitled)"
    return text[: limit - 1].rstrip() + "\u2026"


# ---------------------------------------------------------------------------
# Built-in parsers — CAD / 3D
# ---------------------------------------------------------------------------


_GLB_MIME = "model/gltf-binary"


@register_parser("cad_generate")
def _parse_cad_generate(
    payload: dict[str, Any],
    _content_type: str | None,
) -> ArtifactDescriptor | None:
    """Parser for ``cad_generate`` (TRELLIS text-to-3D).

    Refuses payloads carrying ``source_image`` or ``pipeline_type`` —
    those belong to :func:`_parse_cad_generate_from_image`.
    """
    file_path = payload.get("file_path")
    if not file_path:
        return None
    if payload.get("source_image") or payload.get("pipeline_type"):
        return None
    description = (payload.get("description") or "").strip()
    model_name = payload.get("model_name") or "model"
    # Prefer the human-written description, fall back to model_name when
    # the tool didn't record one (older generations, retroactive backfill).
    title_source = description or model_name
    return ArtifactDescriptor(
        kind=ArtifactKind.CAD_3D_TEXT,
        title=_truncate_title(title_source),
        file_path=str(file_path),
        mime=_GLB_MIME,
        size_bytes=int(payload.get("size_bytes", 0) or 0),
        metadata={
            "model_name": model_name,
            "format": payload.get("format"),
            "export_url": payload.get("export_url"),
            "description": description,
        },
    )


@register_parser("cad_generate_from_image")
def _parse_cad_generate_from_image(
    payload: dict[str, Any],
    _content_type: str | None,
) -> ArtifactDescriptor | None:
    """Parser for ``cad_generate_from_image`` (TRELLIS.2 image-to-3D).

    Requires ``source_image`` *or* ``pipeline_type`` to be present so
    the parser cannot be confused with text-to-3D payloads.
    """
    file_path = payload.get("file_path")
    if not file_path:
        return None
    if not (payload.get("source_image") or payload.get("pipeline_type")):
        return None
    model_name = payload.get("model_name") or "model"
    source_image = payload.get("source_image") or ""
    return ArtifactDescriptor(
        kind=ArtifactKind.CAD_3D_IMAGE,
        title=_truncate_title(model_name),
        file_path=str(file_path),
        mime=_GLB_MIME,
        size_bytes=int(payload.get("size_bytes", 0) or 0),
        metadata={
            "model_name": model_name,
            "format": payload.get("format"),
            "export_url": payload.get("export_url"),
            "source_image": source_image,
            "pipeline_type": payload.get("pipeline_type"),
            "seed": payload.get("seed"),
        },
    )
