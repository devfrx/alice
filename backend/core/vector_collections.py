"""AL\\CE — Shared vector-store collection names and namespaces.

Single source for the identifiers that BOTH the qdrant service layer and
the core tool-RAG components need — defined in ``core`` so the tools
package never imports from ``services`` (layering contract §4).
"""

from __future__ import annotations

import uuid

# Tool-RAG collection (semantic tool retrieval).
COLLECTION_TOOLS = "alice_tools"
"""Tool definition embeddings (Tool RAG)."""

# Stable namespace for deterministic tool-embedding point ids.
PROJECT_NS = uuid.UUID("a1c3e5f7-0000-4000-8000-000000000000")
"""Namespace UUID for deterministic tool IDs via uuid5."""
