"""AL\\CE — Declarative startup stages (Fase 5, spec §5.1).

The lifespan in :mod:`backend.core.app` is an explicit, ordered sequence
of stages; each stage fills the service-group fields it owns on the
:class:`~backend.core.context.AppContext` and may rely only on what the
previous stages produced.  Hard ordering constraints (why the order is
what it is): ``memory ← qdrant+embedding``; ``knowledge ← memory +
continuum_client``; ``tool_registry ← plugin_manager``; ``rag_readiness
← tool_registry.refresh()``; ``permission_service ← scope + rules``;
``terminal ← scope``; the WS connection manager exists before the
sections that register broadcast callbacks (all guarded, but created
first anyway).

Service imports stay INSIDE the stage functions (deferred), exactly as
they were inside the lifespan — the composition root is the sanctioned
exception to the ``core ↛ services`` layering contract (see
``[tool.importlinter]``).
"""

from backend.core.bootstrap.conversation import stage_conversation
from backend.core.bootstrap.database import stage_database
from backend.core.bootstrap.inference import stage_inference
from backend.core.bootstrap.jarvis import stage_jarvis
from backend.core.bootstrap.knowledge import stage_knowledge
from backend.core.bootstrap.platform import stage_platform
from backend.core.bootstrap.plugins import stage_plugins
from backend.core.bootstrap.senses import stage_senses
from backend.core.bootstrap.shutdown import shutdown_services
from backend.core.bootstrap.surfaces import stage_surfaces
from backend.core.bootstrap.workspace import stage_workspace

__all__ = [
    "shutdown_services",
    "stage_conversation",
    "stage_database",
    "stage_inference",
    "stage_jarvis",
    "stage_knowledge",
    "stage_platform",
    "stage_plugins",
    "stage_senses",
    "stage_surfaces",
    "stage_workspace",
]
