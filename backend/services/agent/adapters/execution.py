"""Adapter ``ExecutionPort`` -> ``ToolRegistry`` (piattaforma).

Consuma ``ToolRegistry.get_tool_definition`` / ``ToolRegistry.execute_tool``
(``backend/core/tool_registry.py`` — facade su ``backend/core/tools/``, in
particolare ``backend/core/tools/execution.py:209`` per ``execute_tool`` e
``backend/core/plugin_models.py`` per ``ExecutionContext``/``ToolResult``/
``ToolDefinition``).

Divergenze note dal brief (documentate qui, non "corrette" silenziosamente —
la Port è fissa per questo task):

- Il campo della piattaforma è ``ToolDefinition.client_execution`` (non
  ``client_executed`` come scritto nel brief) — mappato 1:1 su
  ``ToolMeta.client_executed``.
- ``ExecutionContext`` (``backend/core/plugin_models.py:226``) richiede
  ``session_id`` e non ha alcun campo ``client_ip``. La porta
  ``ExecutionPort.execute`` riceve ``client_ip``/``conversation_id`` ma NON
  ``session_id``/``user_id``/``workspace_root``. Questo adapter:
    * usa ``conversation_id`` anche come ``session_id`` (nessun concetto di
      sessione WS esiste a questo confine di porta);
    * usa ``call.call_id`` (già un UUID univoco normalizzato, vedi
      ``backend/services/agent/models.py``) come ``execution_id``;
    * lascia ``user_id`` e ``workspace_root`` a ``None`` — ``client_ip`` non
      viene consumato (non esiste un campo corrispondente su
      ``ExecutionContext``).
  **Nota per fasi successive**: i tool a capability ``fs_*``/``process_exec``
  che leggono ``context.workspace_root`` come sandbox non lo riceveranno
  finché il motore non inietta lo scope della conversazione in questo
  adapter (fuori scope per Task 12 — la Port è fissa; la scope confinement
  by-construction resta comunque applicata a monte dal gate dei permessi,
  che valida gli argomenti-path contro lo scope PRIMA che l'esecuzione
  arrivi qui).
- ``ToolResult`` (``backend/core/plugin_models.py:169``) non ha un campo
  ``images``: ``ToolExecutionOutput.images`` resta sempre ``()`` da questo
  adapter. Contenuti binari (es. immagini) viaggiano oggi via
  ``content_type`` + payload base64 dentro ``content``, non come lista
  separata.
- ``content`` di ``ToolExecutionOutput`` è tipizzato ``str`` (non
  opzionale): un ``ToolResult.content`` dict/list viene serializzato JSON;
  il dict originale (quando è un dict) è comunque preservato in
  ``payload`` per i consumer che vogliono la struttura.

Fix review T12 (bare tool name): ``describe()`` faceva match esatto soltanto,
quindi un nome "nudo" (es. ``"remember"`` per ``"memory_remember"``) veniva
riportato come ``exists=False`` — e ``execute()`` usava quell'esito come
pre-gate, ritornando "non trovato" PRIMA di provare ``execute_tool``, che
invece risolve internamente per suffisso univoco
(``core/tools/execution.py:240-256``). Questo vanificava la tolleranza della
piattaforma ai bare name (il motore emetteva "tool sconosciuto" per una call
che la piattaforma avrebbe eseguito con successo). Fix: ``describe()`` ora
applica la stessa regola di risoluzione (``_tool_lookup.resolve_tool_definition``,
condivisa con ``PermissionServiceAdapter``); ``execute()`` non pre-gate più su
``exists`` — delega sempre a ``execute_tool``, che non solleva mai e ritorna
un ``ToolResult`` d'errore pulito per i nomi davvero sconosciuti/ambigui.
``describe()`` resta consultato in ``execute()`` solo per l'hint di timeout
per-tool (fallback al default quando il tool non è risolvibile).
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from backend.core.plugin_models import ExecutionContext
from backend.core.tool_progress import current_progress_emitter
from backend.services.agent.adapters._tool_lookup import resolve_tool_definition
from backend.services.agent.models import ToolInvocation, ToolMeta
from backend.services.agent.ports import ProgressCallback, ToolExecutionOutput

if TYPE_CHECKING:
    from backend.core.tool_registry import ToolRegistry


class ToolRegistryAdapter:
    """Implementa ``ExecutionPort`` sopra ``ToolRegistry``."""

    def __init__(
        self, tool_registry: ToolRegistry, *, default_timeout_s: float,
    ) -> None:
        """Inizializza l'adapter.

        Args:
            tool_registry: Il registro tool di piattaforma.
            default_timeout_s: Timeout di default (secondi) applicato quando
                la ``ToolDefinition`` non specifica un timeout per-tool
                (tipicamente ``ctx.config.llm.tool_execution_timeout``).
        """
        self._tool_registry = tool_registry
        self._default_timeout_s = default_timeout_s

    def describe(self, name: str) -> ToolMeta:
        """Descrive un tool dal catalogo (senza eseguirlo).

        Risolve *name* come farebbe la piattaforma in ``execute_tool``: match
        esatto, altrimenti unique-suffix fallback per i bare name (vedi
        ``_tool_lookup.resolve_tool_definition``).
        """
        resolved = resolve_tool_definition(self._tool_registry, name)
        if resolved is None:
            return ToolMeta(exists=False)
        resolved_name, tool_def = resolved
        interactive = (
            "ask_user" if resolved_name.endswith("_ask_user") or resolved_name == "ask_user"
            else None
        )
        return ToolMeta(
            exists=True,
            client_executed=tool_def.client_execution,
            interactive=interactive,
            timeout_s=tool_def.timeout_ms / 1000.0,
        )

    async def execute(
        self, call: ToolInvocation, *, client_ip: str | None, conversation_id: str,
        on_progress: ProgressCallback | None = None,
    ) -> ToolExecutionOutput:
        """Esegue un tool server-side con timeout esterno; non solleva mai.

        Nessun pre-gate su ``describe().exists``: delega sempre a
        ``execute_tool``, che risolve i bare name internamente (stessa regola
        di ``describe()``) e ritorna un ``ToolResult`` d'errore pulito per i
        nomi davvero sconosciuti o ambigui — non solleva mai.
        ``describe()`` è comunque consultato per l'hint di timeout per-tool
        (fallback al default quando il tool non è risolvibile).

        Quando ``on_progress`` è fornito, l'adapter lo pubblica nel ContextVar
        ``core.tool_progress.current_progress_emitter`` per la durata
        dell'invocazione: i tool lunghi (es. ``cad_generate_from_image``) che
        chiamano ``emit_tool_progress`` streammano così il progresso attraverso
        la callback del motore. Il ContextVar è token-based e viene resettato
        SEMPRE (anche su timeout); ``asyncio.gather`` esegue ogni call in un
        Task figlio, quindi l'emitter è isolato per-call.
        """
        meta = self.describe(call.name)
        timeout_s = meta.timeout_s if meta.timeout_s is not None else self._default_timeout_s
        exec_ctx = ExecutionContext(
            session_id=conversation_id,
            conversation_id=conversation_id,
            execution_id=call.call_id,
        )
        token = None
        if on_progress is not None:
            token = current_progress_emitter.set(on_progress)
        try:
            try:
                result = await asyncio.wait_for(
                    self._tool_registry.execute_tool(call.name, dict(call.args), exec_ctx),
                    timeout=timeout_s,
                )
            except TimeoutError:
                return ToolExecutionOutput(
                    ok=False, content="", error=f"timeout dopo {timeout_s}s",
                )
        finally:
            if token is not None:
                current_progress_emitter.reset(token)

        content: str
        payload: dict[str, Any] | None = None
        if result.content is None:
            content = ""
        elif isinstance(result.content, str):
            content = result.content
        elif isinstance(result.content, dict):
            payload = result.content
            content = json.dumps(result.content, ensure_ascii=False)
        else:
            content = json.dumps(result.content, ensure_ascii=False)

        return ToolExecutionOutput(
            ok=result.success,
            content=content,
            error=result.error_message,
            payload=payload,
            content_type=result.content_type,
        )
