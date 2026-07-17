import hashlib
import json
from typing import Any

from backend.services.agent.models import ToolInvocation


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\\", "/")
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


class DedupRegistry:
    """Registro delle tool call già viste nel turno (invariante spec §6.8)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen_before(self, call: ToolInvocation) -> bool:
        payload = json.dumps(_normalize(call.args), sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(f"{call.name}:{payload}".encode()).hexdigest()
        if digest in self._seen:
            return True
        self._seen.add(digest)
        return False
