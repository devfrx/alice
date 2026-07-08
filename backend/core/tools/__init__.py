"""AL\\CE — Tool registry components (Fase 5, spec §5.1).

The historical monolithic ``ToolRegistry`` is split by responsibility:

- :mod:`catalog` — WHAT EXISTS: definitions, validation, namespacing,
  dedup, lookups, the OpenAI-format cache.
- :mod:`availability` — WHAT IS REACHABLE: per-plugin connection-status
  probing with a TTL cache.
- :mod:`policy` — WHAT IS OFFERED: pure offer-shaping functions
  (limit/exclude/mode-policy).  User-permission gating is NOT here — it
  lives in ``services.permission_service`` (run-time gate).
- :mod:`execution` — dispatch: argument coercion, schema validation,
  timeout, sanitisation, events.
- :mod:`rag` — semantic tool retrieval (embedding + search).

``backend.core.tool_registry.ToolRegistry`` remains the facade every
consumer uses; its public API is unchanged.
"""

from backend.core.tools.availability import AvailabilityProbe
from backend.core.tools.catalog import ToolCatalog
from backend.core.tools.execution import ToolExecutor
from backend.core.tools.rag import ToolRag

__all__ = ["AvailabilityProbe", "ToolCatalog", "ToolExecutor", "ToolRag"]
