"""Risoluzione condivisa nome-tool -> ``ToolDefinition`` per gli adapter di piattaforma.

Mirror ESATTO della regola di fallback bare-name applicata dalla piattaforma in
``backend/core/tools/execution.py:240-256`` (``ToolExecutor.execute_tool``): un
LLM a volte emette il nome "nudo" di un tool (es. ``"remember"`` invece di
``"memory_remember"``), avendo lasciato cadere il prefisso ``<plugin>_``. La
piattaforma risolve per suffisso univoco:

1. match esatto sul catalogo -> usa quello;
2. altrimenti, tra tutti i nomi namespaced del catalogo, quelli che terminano
   con ``f"_{name}"`` -> se **esattamente uno**, usa quello;
3. zero o più di un candidato -> non risolvibile.

Usata da entrambi ``ToolRegistryAdapter`` (``execution.py``, per
``describe()``) e ``PermissionServiceAdapter`` (``permission.py``, per
recuperare la ``ToolDefinition`` da passare a ``PermissionService.decide``) —
prima di questo fix, il primo faceva solo match esatto (``describe()``
riportava ``exists=False`` per i bare name, difendendo il pre-gate errato in
``execute()``) e il secondo gated con ``tool_def=None`` per gli stessi nomi
(decisione più debole, priva di ``risk_level``/capability). Nessuno dei due
duplica più la regola: entrambi delegano qui.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.plugin_models import ToolDefinition
    from backend.core.tool_registry import ToolRegistry


def resolve_tool_definition(
    tool_registry: ToolRegistry, name: str,
) -> tuple[str, ToolDefinition] | None:
    """Risolve *name* a un tool registrato, tollerando nomi "nudi" (senza prefisso).

    Args:
        tool_registry: Il registro tool di piattaforma.
        name: Nome tool come emesso dal modello (namespaced o bare).

    Returns:
        Tupla ``(nome_namespaced_risolto, tool_def)``, oppure ``None`` se il
        nome non è risolvibile (sconosciuto, o suffisso ambiguo — più
        candidati che terminano con ``_<name>``).
    """
    tool_def = tool_registry.get_tool_definition(name)
    if tool_def is not None:
        return name, tool_def
    # Nessun accesso a stato privato: ``get_all_tools()`` (API pubblica) è
    # costruita dal catalogo sulle STESSE chiavi namespaced consultate da
    # ``execute_tool`` (``core/tools/catalog.py``: ``_openai_cache`` e
    # ``_tools`` sono popolati insieme, sia in ``refresh()`` che in
    # ``register_kernel_tool()``) — stesso universo di candidati.
    suffix = f"_{name}"
    candidates = [
        entry["function"]["name"]
        for entry in tool_registry.get_all_tools()
        if entry["function"]["name"].endswith(suffix)
    ]
    if len(candidates) != 1:
        return None
    resolved = candidates[0]
    resolved_def = tool_registry.get_tool_definition(resolved)
    if resolved_def is None:  # difesa: TOCTOU tra iterazione e lookup
        return None
    return resolved, resolved_def
