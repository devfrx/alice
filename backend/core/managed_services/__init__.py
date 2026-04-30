"""AL\\CE — Concrete :class:`ManagedService` adapters.

Each adapter wraps an existing service (LM Studio, STT, TTS, VRAM
monitor, TRELLIS) so the :class:`ServiceOrchestrator` can manage them
through a uniform Protocol without coupling to their internals.
"""

from backend.core.managed_services.lmstudio import LMStudioManagedService
from backend.core.managed_services.stt import STTManagedService
from backend.core.managed_services.trellis import TrellisManagedService
from backend.core.managed_services.tts import TTSManagedService
from backend.core.managed_services.vram import VRAMManagedService

__all__ = [
    "LMStudioManagedService",
    "STTManagedService",
    "TTSManagedService",
    "TrellisManagedService",
    "VRAMManagedService",
]
