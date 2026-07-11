"""AL\\CE — LLM service components (Fase 5, spec §5.1).

The historical monolithic ``LLMService`` is split by responsibility:

- :mod:`client` — the HTTP/streaming client (LM Studio native SSE +
  OpenAI-compatible SSE, non-streaming completion).
- :mod:`prompting` — system-prompt composition and message building.
- :mod:`model_resolution` — capability selection: ``"auto"`` model
  resolution and the per-model capability profile, collaborating with
  :class:`~backend.services.model_capability_registry.ModelCapabilityRegistry`.

``backend.services.llm_service.LLMService`` remains the facade every
consumer (turn engine, chat assembly, routes) uses; its public API is
unchanged.
"""

from backend.services.llm.client import LLMClient
from backend.services.llm.model_resolution import ModelResolver
from backend.services.llm.prompting import PromptBuilder, normalize_history

__all__ = ["LLMClient", "ModelResolver", "PromptBuilder", "normalize_history"]
