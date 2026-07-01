# Fase 4 — Conoscenza (KnowledgeService unico ingresso) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** il dominio conoscenza passa da 6 strati a 3 (*tools/route → KnowledgeService → backend componibili*, spec §5.2 terzo bullet): nasce `KnowledgeService` come UNICO punto d'accesso sopra il `CompositeKnowledgeBackend`; il plugin memory diventa un guscio sottile di tools; le route memory delegano allo stesso service; il `ContinuumClient` è istanziato UNA volta sola nel wiring. Burn-down ratchet: −19 endpoint (`/api/memory*` ×6, `/api/mcp/memory*` ×9, `/api/knowledge/readiness`, `/api/vector-store*` ×3).

**Architecture:** `KnowledgeService` (`services/knowledge/service.py`) incapsula il `KnowledgeBackend` kind-dispatched (composite quando Continuum è abilitato) più le due operazioni admin della memoria che il protocollo backend non modella (`stats`, `delete_all`). La costruzione dello stack vive SOLO nella factory `build_knowledge_service`, usata sia dal lifespan (`core/app.py`) sia dal re-wiring runtime (`services/knowledge_init.py`) — una sola implementazione (spec §4.1). `ctx.knowledge_backend` viene ELIMINATO dal contesto a fine fase; `ctx.memory_service`/`ctx.qdrant_service` restano come internals del wiring (nessun consumer fuori da wiring/readiness). `MemoryService` resta INVARIATO (storage impl).

**Tech Stack:** FastAPI + Pydantic (response models), Qdrant, plugin system AL\CE, openapi-typescript, Vue 3 + Pinia + vitest.

**Branch:** `arch/fase4-conoscenza` (figlio di `arch/fase3-contenuti`, già creato).

---

## Contesto verificato (recon 2026-07-01, a mano)

**Stato attuale del dominio (i 6 strati):**
- `services/knowledge/` = `protocol.py` (Protocol `KnowledgeBackend` kind-dispatched + dataclass `KnowledgeDoc/DocCreate/DocPatch/Hit/BackendHealth`, `KnowledgeKind = note|memory|fact`), `qdrant_backend.py` (adapter su `MemoryService`; `get`/`update` su kind memory = no-op documentati; `delete_by_filter` richiede filtro `scope`), `continuum_backend.py`, `composite_backend.py`, `continuum_client.py` (costruttore senza I/O, nessun metodo `close`), `services/knowledge_init.py` (re-wiring runtime per la CTA "Ripara/Reset").
- **`ContinuumClient` istanziato in TRE punti** (la duplicazione che la fase elimina): `core/app.py:288` (lifespan), `services/knowledge_init.py:111` (fallback se `ctx.continuum_client` è None), `plugins/continuum/plugin.py:94` (`shared or ContinuumClient(...)`).
- **Plugin memory** (`plugins/memory/plugin.py`): 5 tool; MISCHIA i due ingressi — `remember`/`recall`/`list_memories` via `ctx.knowledge_backend`, `forget`/`clear_session_memory` via `ctx.memory_service` diretto. Guardie su entrambi i campi; `check_dependencies` ritorna `["knowledge_backend"]`.
- **Plugin continuum**: note CRUD (`note_tools.py`, 6 tool) già via `ctx.knowledge_backend`; superfici strutturate via `self._client`. `execute_note_tool(ctx, ...)` prende il ctx del plugin.
- **Route**: `memory.py` usa `ctx.memory_service` diretto con `_serialize_entry` difensivo, lista risponde `{entries, total}`; `knowledge.py` legge `ctx.rag_readiness` e risponde dict; `vector_store.py` usa `ctx.qdrant_service` + `repair_vector_store` (admin infra — resta così, si tipizza soltanto); `mcp_memory.py` proxy verso il server MCP `memory` (knowledge graph — dominio ESTERNO al KnowledgeService, si tipizza soltanto).
- **Consumer nel turno**: `api/routes/chat/_assembly.py:440-463` chiama `ctx.memory_service.search(query=..., k=..., filter={"scope": "long_term"})`; `_format_memory_context` in `api/routes/chat/_helpers.py:285-302` consuma `[{entry, score}]` (nessun test esistente).
- **Ratchet**: 19 voci del dominio in `backend/tests/contracts/response_model_baseline.txt` (elenco esatto nei Task 6-8). Il test `test_response_models.py` fallisce ANCHE sulle voci "fixed" → le righe si eliminano NELLO STESSO task che tipizza la route.
- **WS**: `knowledge.status` e `note.created/updated/deleted` GIÀ tipizzati in `api/ws_schema/events.py` — nessun lavoro WS in fase 4.
- **`MemoryServiceProtocol`** (`core/protocols.py:455-513`) include `stats`/`delete_all`/`delete_by_scope`. `KnowledgeBackendProtocol` è un alias re-import (riga 524).
- **Test esistenti**: `test_memory_plugin.py` (fixture `mock_ctx` con `QdrantBackend` reale su `memory_service` mockato — le asserzioni sono sul mock del memory service e SOPRAVVIVONO alla migrazione), `test_memory_api.py` (app leggera con solo il router memory, `SimpleNamespace(memory_service=...)`), `test_continuum_notes.py` (fixture `ctx.knowledge_backend = AsyncMock()`, 28 usi), `test_continuum_plugin.py` (inietta `p._client` direttamente, NON testa `initialize` → non tocca il fallback), `test_rag_readiness.py`, `test_continuum_backend.py` (solo backend, invariato).

**Frontend (consumatori censiti):**
- `stores/memory.ts` (usa `data.entries` — cambierà in `items`), consumato da `MemoryManager.vue` (usa `entry.created_at` in `formatDate` ×2), `HomeSurface.vue`, `HomeColophon.vue`.
- `stores/mcpMemory.ts`: le mutazioni SCARTANO il body e fanno `loadGraph()` — normalizzare le risposte di mutazione è sicuro. Tipi hand-typed in `types/mcpMemory.ts` (`KGEntity/KGRelation/KGGraph` + payload di request).
- `types/memory.ts` hand-typed (5 interface); `types/settings.ts:121-134` ha `RagReadinessStatus`/`VectorStoreCollectionInfo`/`VectorStoreStats` hand-typed (consumati da `VectorStoreManager.vue` e `stores/services.ts:78`).
- `services/api.ts`: metodi memory (righe ~633-672), mcp memory (~686-744), vector store (~796-807).
- Idioma re-export fase 3: `import type { ApiSchema } from './generated'` + `export type X = ApiSchema<'XRead'>` (vedi `types/artifacts.ts`).

**Vincoli operativi (gotchas handoff, validi qui):** suite backend completa impraticabile → test mirati; `npm run lint` rotto repo-wide → `npx eslint <file toccati>` (solo ERRORI) + `npm run typecheck`; ruff/mypy scoped (file nuovi puliti, pre-esistenze confrontate con `git show arch/fase3-contenuti:<file>`); file scritti con `newline="\n"`; MAI editare file non-ASCII via cmdlet PowerShell (Edit tool o Bash+python); `check-contracts.ps1` DOPO il commit; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`; niente `&&` in PowerShell 5.1; `ToolResult.error()` riempie `error_message`, NON `content`; `test_openapi_export` si esegue SOLO nel task di regen (Task 10) e al gate finale.

---

## Decisioni di design della fase (registrate, non rilitigare durante l'esecuzione)

1. **`KnowledgeService` = facade, non re-implementazione**: delega 1:1 al backend le 8 operazioni del protocollo; aggiunge `memory_available` (property), `memory_stats()`, `delete_all_memories()` (le sole operazioni admin fuori protocollo — delegate a `MemoryService`). Espone la property `backend` SOLO per wiring/test (guardia grep nel Task 9: nessun consumer la usa).
2. **Factory `build_knowledge_service(continuum_enabled, memory_service, continuum_client)`**: unica implementazione della costruzione dello stack (qdrant-only o composite), usata da lifespan E repair. `continuum_enabled=True` senza client → qdrant-only con warning (mai costruzione di fallback).
3. **`ContinuumClient` costruito UNA volta**, in `core/app.py`, quando `config.continuum.enabled` (il costruttore non fa I/O → sempre disponibile prima di plugin e repair). `knowledge_init` e plugin continuum riusano `ctx.continuum_client`; i loro rami di costruzione fallback vengono ELIMINATI.
4. **`ctx.knowledge_service`** nuovo campo tipizzato su `KnowledgeServiceProtocol` (Protocol in `services/knowledge/protocol.py`, alias in `core/protocols.py` come già fatto per `KnowledgeBackendProtocol`). **`ctx.knowledge_backend` ELIMINATO nel Task 9** (nei task intermedi resta come alias `ctx.knowledge_service.backend` per non rompere l'app tra un task e l'altro). `ctx.memory_service`/`ctx.qdrant_service`/`ctx.rag_readiness` restano (internals di wiring/readiness/shutdown).
5. **Route `/api/memory`**: delegano a `knowledge_service` con `kind="memory"`; la lista adotta la convenzione `{items, total}` (spec §6 — BREAKING per il FE, allineato nel Task 10); la search resta `{results: [{entry, score}]}` (è una search, non una lista). Modelli Pydantic in `services/knowledge/schemas.py` (pattern fase 3: schema accanto al service). `_serialize_entry` muore (conversione tipizzata `MemoryEntryRead.from_doc`).
6. **`/api/knowledge/readiness` + `/api/vector-store*`**: SOLO tipizzazione (modelli nei moduli route; `RagReadinessResponse` definito in `knowledge.py` e importato da `vector_store.py` — stesso layer, import lecito). La logica qdrant/repair resta invariata.
7. **`/api/mcp/memory*`**: resta un proxy MCP (il knowledge graph del server MCP NON entra nel KnowledgeService). Solo burn-down: le letture (`graph`, `search`, `nodes`) → `KGGraphResponse` (validazione tollerante: shape inattesa → grafo vuoto + warning); le mutazioni → `KGMutationResponse {ok: true}` (verificato: il FE scarta i body di mutazione e ricarica il grafo).
8. **Parità di comportamento**: `recall`/`POST /memory/search` NON forzano filtro scope (come oggi); `clear_session_memory` passa da `delete_by_filter(kind="memory", filters={"scope": "session"})` (stesso effetto di `delete_by_scope("session")` via QdrantBackend); `delete_all` resta admin del service (`delete_all_memories`); messaggi tool invariati.
9. **Finestra transitoria accettata**: tra Task 6 e Task 10 le route hanno shape nuove ma il FE non è rigenerato (`entries` vs `items`) — runtime FE degradato sul pannello memoria, stato finale di fase è l'oggetto della review finale. Ogni task lascia verdi i test backend mirati.
10. **Docstring/commenti in codice in inglese** (convenzione del codebase); piano ed esiti in italiano.

---

### Task 1: `KnowledgeService` + factory + Protocol + campo context

**Files:**
- Create: `backend/services/knowledge/service.py`
- Modify: `backend/services/knowledge/protocol.py` (aggiungi `KnowledgeServiceProtocol`)
- Modify: `backend/core/protocols.py:524-526` (estendi l'alias re-import)
- Modify: `backend/core/context.py` (campo `knowledge_service`)
- Create: `backend/tests/test_knowledge_service.py`

- [ ] **Step 1: Scrivi il test (failing)**

Crea `backend/tests/test_knowledge_service.py`:

```python
"""Tests for backend.services.knowledge.service — KnowledgeService (Fase 4)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.services.knowledge import (
    CompositeKnowledgeBackend,
    ContinuumClient,
    KnowledgeDocCreate,
    KnowledgeDocPatch,
    QdrantBackend,
)
from backend.services.knowledge.service import (
    KnowledgeService,
    build_knowledge_service,
)


@pytest.fixture
def backend() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def memory() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(backend: AsyncMock, memory: AsyncMock) -> KnowledgeService:
    return KnowledgeService(backend=backend, memory_service=memory)


def _client() -> ContinuumClient:
    return ContinuumClient(
        base_url="http://localhost:9",
        api_token=None,
        timeout_s=1.0,
        folder_cache_ttl_s=1.0,
    )


class TestDelegation:
    """Every protocol operation delegates 1:1 to the wrapped backend."""

    @pytest.mark.asyncio
    async def test_search_delegates(self, service, backend):
        backend.search = AsyncMock(return_value=[])
        out = await service.search(
            "q", kind="memory", k=3, filters={"category": "fact"},
        )
        assert out == []
        backend.search.assert_awaited_once_with(
            "q", kind="memory", k=3, filters={"category": "fact"},
        )

    @pytest.mark.asyncio
    async def test_get_delegates(self, service, backend):
        backend.get = AsyncMock(return_value=None)
        assert await service.get("id1", kind="note") is None
        backend.get.assert_awaited_once_with("id1", kind="note")

    @pytest.mark.asyncio
    async def test_create_delegates(self, service, backend):
        doc = KnowledgeDocCreate(kind="memory", content="x")
        backend.create = AsyncMock(return_value="created")
        assert await service.create(doc) == "created"
        backend.create.assert_awaited_once_with(doc)

    @pytest.mark.asyncio
    async def test_update_delegates(self, service, backend):
        patch = KnowledgeDocPatch(title="t")
        backend.update = AsyncMock(return_value=None)
        assert await service.update("id1", patch, kind="note") is None
        backend.update.assert_awaited_once_with("id1", patch, kind="note")

    @pytest.mark.asyncio
    async def test_delete_delegates(self, service, backend):
        backend.delete = AsyncMock(return_value=True)
        assert await service.delete("id1", kind="memory") is True
        backend.delete.assert_awaited_once_with("id1", kind="memory")

    @pytest.mark.asyncio
    async def test_list_delegates(self, service, backend):
        backend.list = AsyncMock(return_value=([], 0))
        assert await service.list(kind="memory", limit=5, offset=2) == ([], 0)
        backend.list.assert_awaited_once_with(
            kind="memory", filters=None, limit=5, offset=2,
        )

    @pytest.mark.asyncio
    async def test_delete_by_filter_delegates(self, service, backend):
        backend.delete_by_filter = AsyncMock(return_value=4)
        out = await service.delete_by_filter(
            kind="memory", filters={"scope": "session"},
        )
        assert out == 4
        backend.delete_by_filter.assert_awaited_once_with(
            kind="memory", filters={"scope": "session"},
        )

    @pytest.mark.asyncio
    async def test_health_delegates(self, service, backend):
        backend.health = AsyncMock(return_value="ok")
        assert await service.health() == "ok"


class TestMemoryAdmin:
    """Admin operations outside the backend protocol."""

    def test_memory_available(self, backend, memory):
        assert KnowledgeService(
            backend=backend, memory_service=memory,
        ).memory_available is True
        assert KnowledgeService(
            backend=backend, memory_service=None,
        ).memory_available is False

    @pytest.mark.asyncio
    async def test_memory_stats_delegates(self, service, memory):
        memory.stats = AsyncMock(return_value={"total": 1})
        assert await service.memory_stats() == {"total": 1}

    @pytest.mark.asyncio
    async def test_memory_stats_raises_without_memory(self, backend):
        svc = KnowledgeService(backend=backend, memory_service=None)
        with pytest.raises(RuntimeError):
            await svc.memory_stats()

    @pytest.mark.asyncio
    async def test_delete_all_memories_delegates(self, service, memory):
        memory.delete_all = AsyncMock(return_value=7)
        assert await service.delete_all_memories() == 7

    @pytest.mark.asyncio
    async def test_delete_all_memories_raises_without_memory(self, backend):
        svc = KnowledgeService(backend=backend, memory_service=None)
        with pytest.raises(RuntimeError):
            await svc.delete_all_memories()


class TestFactory:
    """build_knowledge_service is the single wiring implementation."""

    def test_qdrant_only_when_continuum_disabled(self, memory):
        svc = build_knowledge_service(
            continuum_enabled=False,
            memory_service=memory,
            continuum_client=None,
        )
        assert isinstance(svc.backend, QdrantBackend)

    def test_composite_when_continuum_enabled(self, memory):
        svc = build_knowledge_service(
            continuum_enabled=True,
            memory_service=memory,
            continuum_client=_client(),
        )
        assert isinstance(svc.backend, CompositeKnowledgeBackend)

    def test_qdrant_only_when_client_missing(self, memory):
        svc = build_knowledge_service(
            continuum_enabled=True,
            memory_service=memory,
            continuum_client=None,
        )
        assert isinstance(svc.backend, QdrantBackend)

    def test_memory_available_flows_through(self):
        svc = build_knowledge_service(
            continuum_enabled=False,
            memory_service=None,
            continuum_client=None,
        )
        assert svc.memory_available is False
```

- [ ] **Step 2: Esegui il test per vederlo fallire**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_knowledge_service.py -v
```

Atteso: errore di import (`backend.services.knowledge.service` non esiste).

- [ ] **Step 3: Crea `backend/services/knowledge/service.py`**

```python
"""AL\\CE — Knowledge domain single entry point (Fase 4).

``KnowledgeService`` is the ONLY entry point tools and routes use for
persistent knowledge (notes, memories, facts): it wraps the composable
:class:`KnowledgeBackend` (composite when Continuum is enabled) plus the
raw ``MemoryService`` for the two admin operations the backend protocol
does not model (``stats`` and ``delete_all``).

Stack construction (qdrant backend + optional composite with Continuum)
lives ONLY in :func:`build_knowledge_service`, used both by the lifespan
(``core/app.py``) and by the runtime re-wiring
(``services/knowledge_init.py``) — one implementation (spec §4.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.services.knowledge.composite_backend import (
    CompositeKnowledgeBackend,
)
from backend.services.knowledge.continuum_backend import ContinuumBackend
from backend.services.knowledge.protocol import (
    BackendHealth,
    KnowledgeBackend,
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeDocPatch,
    KnowledgeHit,
    KnowledgeKind,
)
from backend.services.knowledge.qdrant_backend import QdrantBackend

if TYPE_CHECKING:
    from backend.core.protocols import MemoryServiceProtocol
    from backend.services.knowledge.continuum_client import ContinuumClient


class KnowledgeService:
    """Kind-dispatched facade over the composable knowledge backend.

    Args:
        backend: The backend (composite or qdrant-only) to delegate to.
        memory_service: The raw memory service, or ``None`` when memory
            is disabled/uninitialised.  Used ONLY for the admin
            operations not modelled by the backend protocol.
    """

    def __init__(
        self,
        *,
        backend: KnowledgeBackend,
        memory_service: MemoryServiceProtocol | None,
    ) -> None:
        self._backend = backend
        self._memory = memory_service
        self._log = logger.bind(component="KnowledgeService")

    # ------------------------------------------------------------------
    # Availability / introspection
    # ------------------------------------------------------------------

    @property
    def memory_available(self) -> bool:
        """True when memory/fact-kind operations can succeed."""
        return self._memory is not None

    @property
    def backend(self) -> KnowledgeBackend:
        """The wrapped backend — wiring/tests only, never for consumers."""
        return self._backend

    def _require_memory(self) -> MemoryServiceProtocol:
        if self._memory is None:
            raise RuntimeError("memory service is not available")
        return self._memory

    # ------------------------------------------------------------------
    # Backend delegation (kind-dispatched)
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        kind: KnowledgeKind,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeHit]:
        """Semantic/hybrid search restricted to ``kind``."""
        return await self._backend.search(query, kind=kind, k=k, filters=filters)

    async def get(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        """Fetch a single document by id (``None`` if absent)."""
        return await self._backend.get(doc_id, kind=kind)

    async def create(self, doc: KnowledgeDocCreate) -> KnowledgeDoc:
        """Create a document and return its materialised form."""
        return await self._backend.create(doc)

    async def update(
        self,
        doc_id: str,
        patch: KnowledgeDocPatch,
        *,
        kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        """Apply a partial update (``None`` if not found)."""
        return await self._backend.update(doc_id, patch, kind=kind)

    async def delete(self, doc_id: str, *, kind: KnowledgeKind) -> bool:
        """Delete a document; ``True`` on success."""
        return await self._backend.delete(doc_id, kind=kind)

    async def list(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeDoc], int]:
        """Paginated listing: ``(documents, total_count)``."""
        return await self._backend.list(
            kind=kind, filters=filters, limit=limit, offset=offset,
        )

    async def delete_by_filter(
        self, *, kind: KnowledgeKind, filters: dict[str, Any],
    ) -> int:
        """Bulk delete by filter; returns the number of removed docs."""
        return await self._backend.delete_by_filter(kind=kind, filters=filters)

    async def health(self) -> BackendHealth:
        """Health snapshot of the underlying backend."""
        return await self._backend.health()

    # ------------------------------------------------------------------
    # Memory admin (outside the backend protocol)
    # ------------------------------------------------------------------

    async def memory_stats(self) -> dict[str, Any]:
        """Aggregate memory statistics (raises if memory unavailable)."""
        return await self._require_memory().stats()

    async def delete_all_memories(self) -> int:
        """Delete every memory entry (raises if memory unavailable)."""
        return await self._require_memory().delete_all()


def build_knowledge_service(
    *,
    continuum_enabled: bool,
    memory_service: MemoryServiceProtocol | None,
    continuum_client: ContinuumClient | None,
) -> KnowledgeService:
    """Build the knowledge stack — the single wiring implementation.

    Args:
        continuum_enabled: Whether note knowledge is served by Continuum.
        memory_service: Shared memory service (or ``None`` when disabled).
        continuum_client: The ONE shared Continuum client, or ``None``.

    Returns:
        A ready :class:`KnowledgeService` (composite backend when
        Continuum is enabled AND a client is provided, qdrant-only
        otherwise).
    """
    qdrant_backend = QdrantBackend(memory_service=memory_service)
    backend: KnowledgeBackend = qdrant_backend
    if continuum_enabled and continuum_client is not None:
        backend = CompositeKnowledgeBackend(
            note_backend=ContinuumBackend(client=continuum_client),
            memory_backend=qdrant_backend,
        )
    elif continuum_enabled:
        logger.warning(
            "build_knowledge_service: continuum enabled but no client — "
            "notes disabled",
        )
    return KnowledgeService(backend=backend, memory_service=memory_service)
```

- [ ] **Step 4: Aggiungi `KnowledgeServiceProtocol` in `backend/services/knowledge/protocol.py`**

In coda al file (dopo la classe `KnowledgeBackend`):

```python
@runtime_checkable
class KnowledgeServiceProtocol(Protocol):
    """Single entry point to the knowledge domain (Fase 4).

    Facade over the composable :class:`KnowledgeBackend` plus the memory
    admin operations the backend protocol does not model.  Tools and
    routes depend on THIS — never on ``memory_service`` or a backend.
    """

    @property
    def memory_available(self) -> bool:
        """True when memory/fact-kind operations can succeed."""
        ...

    @property
    def backend(self) -> KnowledgeBackend:
        """The wrapped backend — wiring/tests only."""
        ...

    async def search(
        self,
        query: str,
        *,
        kind: KnowledgeKind,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeHit]: ...

    async def get(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> KnowledgeDoc | None: ...

    async def create(self, doc: KnowledgeDocCreate) -> KnowledgeDoc: ...

    async def update(
        self,
        doc_id: str,
        patch: KnowledgeDocPatch,
        *,
        kind: KnowledgeKind,
    ) -> KnowledgeDoc | None: ...

    async def delete(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> bool: ...

    async def list(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeDoc], int]: ...

    async def delete_by_filter(
        self, *, kind: KnowledgeKind, filters: dict[str, Any],
    ) -> int: ...

    async def health(self) -> BackendHealth: ...

    async def memory_stats(self) -> dict[str, Any]: ...

    async def delete_all_memories(self) -> int: ...
```

- [ ] **Step 5: Estendi alias in `core/protocols.py` e campo in `core/context.py`**

In `backend/core/protocols.py`, il re-import a riga 524-526 diventa:

```python
from backend.services.knowledge.protocol import (  # noqa: E402
    KnowledgeBackend as KnowledgeBackendProtocol,
    KnowledgeServiceProtocol,
)
```

In `backend/core/context.py`: aggiungi `KnowledgeServiceProtocol` all'import da `backend.core.protocols` (riga ~21, accanto a `KnowledgeBackendProtocol`) e, subito DOPO il campo `knowledge_backend` (riga ~70-73), aggiungi:

```python
    knowledge_service: KnowledgeServiceProtocol | None = None
    """Single entry point to the knowledge domain (Fase 4): facade over
    the composable backend + memory admin operations.  Tools and routes
    must use THIS — never ``memory_service`` or a backend directly."""
```

- [ ] **Step 6: Esegui i test**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_knowledge_service.py -v
```

Atteso: PASS (tutti).

- [ ] **Step 7: Lint/type-check scoped e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check backend/services/knowledge/service.py backend/services/knowledge/protocol.py backend/core/protocols.py backend/core/context.py tests/test_knowledge_service.py
..\.venv\Scripts\python.exe -m mypy backend/services/knowledge/service.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git add backend/services/knowledge/service.py backend/services/knowledge/protocol.py backend/core/protocols.py backend/core/context.py backend/tests/test_knowledge_service.py
git commit -m "feat(knowledge): KnowledgeService unico ingresso + factory build_knowledge_service" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Nota ruff: il comando va lanciato dalla root `backend/` con path relativi al repo — se i path sopra non risolvono, usa i path relativi a `backend/` (es. `services/knowledge/service.py`). Errori pre-esistenti nei file MODIFICATI si confrontano con `git show arch/fase3-contenuti:<file>`.

---

### Task 2: Wiring — lifespan e repair via factory, client Continuum unico

**Files:**
- Modify: `backend/core/app.py:265-311` (blocco knowledge backend + continuum)
- Modify: `backend/services/knowledge_init.py` (docstring + step 3)

- [ ] **Step 1: Sostituisci il blocco wiring in `core/app.py`**

Sostituisci TUTTO il blocco da `# -- Knowledge backend (Phase 1, Stream A) -----------------------------` (riga ~265) fino alla riga `logger.info("Knowledge backend wired (memory={}, notes=disabled)", ctx.memory_service is not None)` inclusa (riga ~311; il ramo `else` completo) con:

```python
    # -- Knowledge service (Fase 4) -----------------------------------------
    # ONE entry point to the knowledge domain: KnowledgeService wraps the
    # composable backend (composite with Continuum when enabled).  The
    # ContinuumClient is instantiated HERE and only here; knowledge_init
    # and the continuum plugin reuse ctx.continuum_client (no fallbacks).
    from backend.services.knowledge.service import build_knowledge_service

    if config.continuum.enabled:
        from backend.services.knowledge import ContinuumClient

        ctx.continuum_client = ContinuumClient(
            base_url=config.continuum.base_url,
            api_token=config.continuum.api_token,
            timeout_s=config.continuum.timeout_s,
            folder_cache_ttl_s=config.continuum.folder_cache_ttl_s,
        )
        logger.info(
            "Knowledge service wired (notes=continuum @ {}, memory={})",
            config.continuum.base_url,
            ctx.memory_service is not None,
        )
    else:
        logger.info(
            "Knowledge service wired (memory={}, notes=disabled)",
            ctx.memory_service is not None,
        )
    ctx.knowledge_service = build_knowledge_service(
        continuum_enabled=config.continuum.enabled,
        memory_service=ctx.memory_service,
        continuum_client=ctx.continuum_client,
    )
    # Fase 4 transition alias for not-yet-migrated consumers
    # (memory/continuum plugins).  Removed in Task 9.
    ctx.knowledge_backend = ctx.knowledge_service.backend
```

- [ ] **Step 2: Sostituisci lo step 3 di `repair_vector_store` in `knowledge_init.py`**

Sostituisci il blocco da `# 3. Re-wire the knowledge backend (preserving the continuum note side).` (riga ~98) fino a `ctx.knowledge_backend = qdrant_backend` inclusa (riga ~123) con:

```python
    # 3. Re-wire the knowledge service (reusing the shared Continuum client).
    from backend.services.knowledge.service import build_knowledge_service

    client = getattr(ctx, "continuum_client", None)
    if config.continuum.enabled and client is None:
        # The client is built once in the lifespan; if it is missing here
        # the wiring is broken — proceed memory-only, never build a second
        # client.
        logger.warning(
            "Repair: continuum enabled but no shared client — notes disabled",
        )
    ctx.knowledge_service = build_knowledge_service(
        continuum_enabled=config.continuum.enabled and client is not None,
        memory_service=ctx.memory_service,
        continuum_client=client,
    )
    # Fase 4 transition alias (removed in Task 9).
    ctx.knowledge_backend = ctx.knowledge_service.backend
```

Nel docstring del modulo (righe 1-15) sostituisci `re-initialises Qdrant + memory + the knowledge backend` con `re-initialises Qdrant + memory + the knowledge service` e `Plugins read ``ctx.knowledge_backend`` / ``ctx.memory_service`` lazily` con `Plugins read ``ctx.knowledge_service`` lazily`.

- [ ] **Step 3: Verifica import + regressioni mirate**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
..\.venv\Scripts\python.exe -m pytest tests/test_knowledge_service.py tests/test_rag_readiness.py tests/test_continuum_backend.py -v
```

Atteso: `app ok` + PASS.

- [ ] **Step 4: Commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add backend/core/app.py backend/services/knowledge_init.py
git commit -m "refactor(knowledge): wiring lifespan+repair via build_knowledge_service, ContinuumClient unico" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Plugin memory = guscio sottile su `knowledge_service`

**Files:**
- Modify: `backend/plugins/memory/plugin.py`
- Modify: `backend/tests/test_memory_plugin.py` (solo fixture)

- [ ] **Step 1: Aggiorna le fixture del test (test first)**

In `backend/tests/test_memory_plugin.py` sostituisci le fixture `mock_ctx` e `plugin_no_service` con:

```python
@pytest.fixture
def mock_ctx():
    """Mock AppContext with a real KnowledgeService over a mocked memory service."""
    from backend.core.context import AppContext
    from backend.services.knowledge import QdrantBackend
    from backend.services.knowledge.service import KnowledgeService

    ctx = MagicMock(spec=AppContext)
    ctx.memory_service = AsyncMock()
    ctx.knowledge_service = KnowledgeService(
        backend=QdrantBackend(memory_service=ctx.memory_service),
        memory_service=ctx.memory_service,
    )
    ctx.config = MagicMock()
    ctx.config.memory.embedding_model = "test-model"
    ctx.config.memory.session_ttl_hours = 24
    return ctx
```

```python
@pytest.fixture
def plugin_no_service(mock_ctx):
    """MemoryPlugin where the memory side of the knowledge service is unavailable."""
    from backend.plugins.memory.plugin import MemoryPlugin
    from backend.services.knowledge import QdrantBackend
    from backend.services.knowledge.service import KnowledgeService

    mock_ctx.memory_service = None
    mock_ctx.knowledge_service = KnowledgeService(
        backend=QdrantBackend(memory_service=None),
        memory_service=None,
    )
    p = MemoryPlugin()
    p._ctx = mock_ctx
    p._initialized = True
    return p
```

Le asserzioni esistenti sul mock del memory service (`add`/`search`/`delete`/`list`/`delete_by_scope`) NON cambiano: la catena service→backend→memory_service le raggiunge identiche (`delete_by_filter({"scope": "session"})` → `delete_by_scope("session")` in `QdrantBackend.delete_by_filter`).

- [ ] **Step 2: Esegui i test per vederli fallire**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_memory_plugin.py -v
```

Atteso: FAIL sui test `forget`/`clear_session` e `unavailable` (il plugin usa ancora `memory_service`/`knowledge_backend`; `MagicMock(spec=AppContext)` ha `knowledge_backend` auto-mockato non-None → i vecchi percorsi non matchano più le nuove fixture).

- [ ] **Step 3: Migra il plugin a `knowledge_service`**

In `backend/plugins/memory/plugin.py`:

1. Docstring modulo: sostituisci `that delegate to the\n:class:`MemoryServiceProtocol` on the application context.` con `that delegate to the\n:class:`KnowledgeServiceProtocol` on the application context (Fase 4:\nsingle entry point to the knowledge domain).`
2. In `initialize` sostituisci la condizione:

```python
        if ctx.knowledge_service is None or not ctx.knowledge_service.memory_available:
            self.logger.warning(
                "Knowledge service (memory) is not available "
                "— all memory tools will return errors"
            )
```

3. In `execute_tool` sostituisci la guardia iniziale:

```python
        svc = self._ctx.knowledge_service if self._ctx is not None else None
        if svc is None or not svc.memory_available:
            return ToolResult.error("Memory service not available")
```

4. `_handle_remember`: `self._ctx.knowledge_backend.create(` → `self._ctx.knowledge_service.create(` (resto invariato).
5. `_handle_recall`: `self._ctx.knowledge_backend.search(` → `self._ctx.knowledge_service.search(`.
6. `_handle_forget`: sostituisci `deleted = await self._ctx.memory_service.delete(memory_id)` con:

```python
            deleted = await self._ctx.knowledge_service.delete(
                memory_id, kind="memory",
            )
```

7. `_handle_list`: `self._ctx.knowledge_backend.list(` → `self._ctx.knowledge_service.list(`.
8. `_handle_clear_session`: sostituisci `deleted_count = await self._ctx.memory_service.delete_by_scope("session",)` con:

```python
            deleted_count = await self._ctx.knowledge_service.delete_by_filter(
                kind="memory", filters={"scope": "session"},
            )
```

9. `check_dependencies`:

```python
        if (
            self._ctx is None
            or self._ctx.knowledge_service is None
            or not self._ctx.knowledge_service.memory_available
        ):
            return ["knowledge_service"]
        return []
```

(aggiorna anche il docstring: `"knowledge_backend"` → `"knowledge_service"`).

10. `get_connection_status`:

```python
        if (
            self._ctx
            and self._ctx.knowledge_service is not None
            and self._ctx.knowledge_service.memory_available
        ):
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.ERROR
```

- [ ] **Step 4: Esegui i test**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_memory_plugin.py -v
```

Atteso: PASS (tutti, inclusi i 5 `unavailable`: `res.error_message` valorizzato).

- [ ] **Step 5: Lint scoped e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check plugins/memory/plugin.py tests/test_memory_plugin.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git add backend/plugins/memory/plugin.py backend/tests/test_memory_plugin.py
git commit -m "refactor(memory): plugin guscio sottile su KnowledgeService" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Continuum — note_tools su `knowledge_service`, plugin senza fallback client

**Files:**
- Modify: `backend/plugins/continuum/note_tools.py`
- Modify: `backend/plugins/continuum/plugin.py:78-99` (`initialize`)
- Modify: `backend/tests/test_continuum_notes.py` (rename mock)

- [ ] **Step 1: Aggiorna la fixture del test (test first)**

In `backend/tests/test_continuum_notes.py`, nella fixture `mock_ctx` sostituisci `ctx.knowledge_backend = AsyncMock()` con `ctx.knowledge_service = AsyncMock()`, poi rinomina TUTTE le altre occorrenze con Edit `replace_all`: `mock_ctx.knowledge_backend` → `mock_ctx.knowledge_service` (27 occorrenze restanti; verifica con `git diff --stat` che il file sia l'unico toccato).

- [ ] **Step 2: Esegui per vedere fallire**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_continuum_notes.py -v
```

Atteso: FAIL diffuso (note_tools legge ancora `ctx.knowledge_backend`, che su un `MagicMock` senza spec è un mock "vergine" le cui chiamate non sono quelle asserite).

- [ ] **Step 3: Migra `note_tools.py`**

In `backend/plugins/continuum/note_tools.py`:

1. Sostituisci la guardia in `execute_note_tool`:

```python
    if ctx.knowledge_service is None:
        return ToolResult.error("Note service not available")
```

2. Sostituisci OGNI `ctx.knowledge_backend.` con `ctx.knowledge_service.` (7 occorrenze: `create`, `get`, `update`, `delete`, `search`, `list` nei rispettivi handler — usa Edit `replace_all` su `ctx.knowledge_backend.`).
3. Docstring modulo: `They route through the application's\n:class:`~backend.services.knowledge.protocol.KnowledgeBackend` with\n``kind="note"``` → `They route through the application's\n:class:`~backend.services.knowledge.protocol.KnowledgeServiceProtocol`\nwith ``kind="note"``` e nel docstring di `execute_note_tool` sostituisci ``ctx``: Application context exposing ``knowledge_backend``,` con ``ctx``: Application context exposing ``knowledge_service``,`.

- [ ] **Step 4: Elimina il fallback client in `plugin.py`**

In `backend/plugins/continuum/plugin.py`, in `initialize`, sostituisci il blocco dal commento `# Reuse the client the knowledge backend already wired...` fino a `)` della costruzione fallback (righe ~88-99) con:

```python
        # Reuse THE shared client wired in the lifespan (core/app.py) so
        # the folder path↔id cache stays coherent across note placement
        # and the folder mutations this plugin performs.  There is no
        # fallback construction: one client per process (Fase 4).
        self._client = getattr(ctx, "continuum_client", None)
        if self._client is None:
            self.logger.warning(
                "Continuum enabled but no shared client on the context — "
                "tools will return errors (wiring bug?)"
            )
```

Rimuovi l'import ora inutilizzato `ContinuumClient` dalla riga `from backend.services.knowledge.continuum_client import (ContinuumClient, ContinuumError)` (lascia solo `ContinuumError`). Aggiorna il docstring del modulo: sostituisci la frase `The plugin owns its :class:`ContinuumClient` built from\n``config.continuum`` during :meth:`initialize`, reusing the instance the\nknowledge backend already wired so the folder path↔id cache stays\ncoherent.` con `The plugin reuses THE shared :class:`ContinuumClient` wired once in the\nlifespan (``ctx.continuum_client``) so the folder path↔id cache stays\ncoherent — it never builds its own (Fase 4).`

- [ ] **Step 5: Esegui i test**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_continuum_notes.py tests/test_continuum_plugin.py -v
```

Atteso: PASS (test_continuum_plugin inietta `p._client` direttamente e non testa `initialize` → invariato).

- [ ] **Step 6: Verifica il punto unico di costruzione e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "ContinuumClient(" -- backend | Select-String -NotMatch "tests|protocol|continuum_client.py"
```

Atteso: SOLO `backend/core/app.py` (la costruzione nel lifespan).

```powershell
git add backend/plugins/continuum/note_tools.py backend/plugins/continuum/plugin.py backend/tests/test_continuum_notes.py
git commit -m "refactor(continuum): note tools su KnowledgeService, client condiviso senza fallback" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Contesto memoria nel turno via `knowledge_service`

**Files:**
- Modify: `backend/api/routes/chat/_helpers.py:285-302` (`_format_memory_context`)
- Modify: `backend/api/routes/chat/_assembly.py:440-463` (retrieval memorie)
- Create: `backend/tests/test_chat_memory_context.py`

- [ ] **Step 1: Scrivi il test (failing)**

Crea `backend/tests/test_chat_memory_context.py`:

```python
"""Unit tests for _format_memory_context (Fase 4: KnowledgeHit-based)."""

from __future__ import annotations

from backend.api.routes.chat._helpers import _format_memory_context
from backend.services.knowledge import KnowledgeDoc, KnowledgeHit


def _hit(content: str, category: str | None = None) -> KnowledgeHit:
    return KnowledgeHit(
        doc=KnowledgeDoc(
            id="00000000-0000-0000-0000-000000000001",
            kind="memory",
            content=content,
            metadata={"category": category, "scope": "long_term"},
        ),
        score=0.9,
    )


def test_formats_hits_with_category():
    out = _format_memory_context([_hit("likes dark mode", "preference")], 1000)
    assert "[RELEVANT MEMORIES]" in out
    assert "- [preference] likes dark mode" in out


def test_category_fallback_general():
    out = _format_memory_context([_hit("a fact", None)], 1000)
    assert "- [general] a fact" in out


def test_truncates_at_max_chars():
    hits = [_hit("x" * 50, "a"), _hit("y" * 50, "b")]
    out = _format_memory_context(hits, 60)
    assert "x" * 50 in out
    assert "y" * 50 not in out
```

Esegui per vederlo fallire (la firma attuale consuma `[{entry, score}]`):

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_chat_memory_context.py -v
```

Atteso: FAIL (i `KnowledgeHit` non hanno `.get`).

- [ ] **Step 2: Riscrivi `_format_memory_context` in `_helpers.py`**

```python
def _format_memory_context(
    hits: list[KnowledgeHit], max_chars: int,
) -> str:
    """Serialize relevant memories into a text block for the system prompt."""
    lines = ["[RELEVANT MEMORIES]"]
    total = 0
    for hit in hits:
        doc = hit.doc
        cat = (doc.metadata or {}).get("category") or "general"
        line = f"- [{cat}] {doc.content}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)
```

Aggiungi `KnowledgeHit` agli import del file: se `_helpers.py` ha un blocco `if TYPE_CHECKING:` aggiungilo lì (`from backend.services.knowledge import KnowledgeHit`); il test lo importa a runtime dal package `backend.services.knowledge`, il modulo `_helpers` lo usa solo in annotazione (`from __future__ import annotations` presente).

- [ ] **Step 3: Migra il retrieval in `_assembly.py`**

Sostituisci il blocco righe ~440-463 (`# --- retrieve relevant memories (Phase 9) -----------------` incluso il `try/except`) con:

```python
        # --- retrieve relevant memories (Phase 9) -----------------
        aux_parts: list[str] = []
        if (
            ctx.knowledge_service is not None
            and ctx.knowledge_service.memory_available
            and ctx.config.memory.inject_in_context
            and memory_ok
        ):
            try:
                hits = await ctx.knowledge_service.search(
                    user_content,
                    kind="memory",
                    k=ctx.config.memory.top_k,
                    filters={"scope": "long_term"},
                )
                if hits:
                    aux_parts.append(
                        _format_memory_context(
                            hits,
                            ctx.config.memory.context_max_chars,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "Memory retrieval failed: {}", exc,
                )
```

- [ ] **Step 4: Esegui i test e verifica che non restino consumer diretti nel package chat**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_chat_memory_context.py -v
git grep -n "memory_service" -- api/routes/chat
```

Atteso: PASS; il grep NON deve restituire righe (l'unico consumer era `_assembly.py`).

- [ ] **Step 5: Commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add backend/api/routes/chat/_helpers.py backend/api/routes/chat/_assembly.py backend/tests/test_chat_memory_context.py
git commit -m "refactor(chat): contesto memorie del turno via KnowledgeService" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Route `/api/memory` tipizzate e deleganti (baseline −6)

**Files:**
- Create: `backend/services/knowledge/schemas.py`
- Rewrite: `backend/api/routes/memory.py`
- Modify: `backend/tests/test_memory_api.py`
- Modify: `backend/tests/contracts/response_model_baseline.txt` (−6 righe)

- [ ] **Step 1: Crea `backend/services/knowledge/schemas.py`**

```python
"""AL\\CE — Pydantic API models for the knowledge domain (``/api/memory``).

Response contracts of the memory REST routes (Fase 4).  They convert
:class:`~backend.services.knowledge.protocol.KnowledgeDoc` documents to
the public REST shape — the routes hold no serialisation logic.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.services.knowledge.protocol import KnowledgeDoc


class MemorySearchRequest(BaseModel):
    """Body for ``POST /api/memory/search``."""

    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(10, ge=1, le=50)
    category: str | None = None


class MemoryEntryRead(BaseModel):
    """Public representation of a memory entry."""

    id: str
    content: str
    scope: str
    category: str | None = None
    source: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    conversation_id: str | None = None

    @classmethod
    def from_doc(cls, doc: KnowledgeDoc) -> MemoryEntryRead:
        """Map a memory/fact ``KnowledgeDoc`` to the REST shape."""
        meta = doc.metadata or {}
        return cls(
            id=doc.id,
            content=doc.content,
            scope=str(meta.get("scope") or ""),
            category=meta.get("category"),
            source=meta.get("source"),
            created_at=doc.created_at,
            expires_at=meta.get("expires_at"),
            conversation_id=meta.get("conversation_id"),
        )


class MemoryListResponse(BaseModel):
    """Paginated memory list (``{items, total}`` convention, spec §6)."""

    items: list[MemoryEntryRead]
    total: int


class MemorySearchHit(BaseModel):
    """Search result: entry + similarity score."""

    entry: MemoryEntryRead
    score: float


class MemorySearchResponse(BaseModel):
    """Semantic search results."""

    results: list[MemorySearchHit]


class MemoryDeleteResponse(BaseModel):
    """Single-delete acknowledgement."""

    deleted: bool


class MemoryDeleteCountResponse(BaseModel):
    """Bulk-delete count."""

    deleted_count: int


class MemoryStatsResponse(BaseModel):
    """Aggregate memory statistics."""

    total: int
    by_scope: dict[str, int]
    by_category: dict[str, int]
    db_size_bytes: int
```

- [ ] **Step 2: Riscrivi `backend/api/routes/memory.py`**

Contenuto COMPLETO del nuovo file:

```python
"""AL\\CE — Memory management REST endpoints.

Every endpoint delegates to the :class:`KnowledgeServiceProtocol`
(single entry point to the knowledge domain, Fase 4) with
``kind="memory"`` — no domain logic lives here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger

from backend.core.protocols import KnowledgeServiceProtocol
from backend.services.knowledge.schemas import (
    MemoryDeleteCountResponse,
    MemoryDeleteResponse,
    MemoryEntryRead,
    MemoryListResponse,
    MemorySearchHit,
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryStatsResponse,
)

router = APIRouter(prefix="/memory", tags=["memory"])


def _get_knowledge_service(request: Request) -> KnowledgeServiceProtocol:
    """Extract the knowledge service from app context or raise 503."""
    ctx = request.app.state.context
    svc = getattr(ctx, "knowledge_service", None)
    if svc is None or not svc.memory_available:
        raise HTTPException(status_code=503, detail="Memory service not available")
    return svc


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    request: Request,
    scope: str | None = Query(None, description="Filter by scope"),
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> MemoryListResponse:
    """List memory entries with optional filters."""
    svc = _get_knowledge_service(request)

    filters: dict[str, str] = {}
    if scope is not None:
        filters["scope"] = scope
    if category is not None:
        filters["category"] = category

    docs, total = await svc.list(
        kind="memory", filters=filters or None, limit=limit, offset=offset,
    )
    return MemoryListResponse(
        items=[MemoryEntryRead.from_doc(d) for d in docs],
        total=total,
    )


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(
    request: Request,
    body: MemorySearchRequest,
) -> MemorySearchResponse:
    """Semantic search over stored memories."""
    svc = _get_knowledge_service(request)

    filters = {"category": body.category} if body.category is not None else None
    hits = await svc.search(body.query, kind="memory", k=body.limit, filters=filters)
    return MemorySearchResponse(
        results=[
            MemorySearchHit(entry=MemoryEntryRead.from_doc(h.doc), score=h.score)
            for h in hits
        ],
    )


@router.delete("/all", response_model=MemoryDeleteCountResponse)
async def delete_all_memory(request: Request) -> MemoryDeleteCountResponse:
    """Delete every memory entry (all scopes)."""
    svc = _get_knowledge_service(request)

    count = await svc.delete_all_memories()
    logger.info("Deleted all {} memories", count)
    return MemoryDeleteCountResponse(deleted_count=count)


@router.delete("/session", response_model=MemoryDeleteCountResponse)
async def delete_session_memory(request: Request) -> MemoryDeleteCountResponse:
    """Delete all session-scoped memories."""
    svc = _get_knowledge_service(request)

    count = await svc.delete_by_filter(kind="memory", filters={"scope": "session"})
    logger.info("Deleted {} session memories", count)
    return MemoryDeleteCountResponse(deleted_count=count)


@router.delete("/{memory_id}", response_model=MemoryDeleteResponse)
async def delete_memory(
    request: Request,
    memory_id: str,
) -> MemoryDeleteResponse:
    """Delete a single memory entry by ID."""
    svc = _get_knowledge_service(request)

    try:
        uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid memory ID format")

    deleted = await svc.delete(memory_id, kind="memory")
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")

    logger.info("Deleted memory {}", memory_id)
    return MemoryDeleteResponse(deleted=True)


@router.get("/stats", response_model=MemoryStatsResponse)
async def memory_stats(request: Request) -> MemoryStatsResponse:
    """Return memory usage statistics."""
    svc = _get_knowledge_service(request)
    return MemoryStatsResponse(**await svc.memory_stats())
```

- [ ] **Step 3: Aggiorna `test_memory_api.py`**

1. `_build_app` diventa (il parametro resta `memory_service` per non toccare le firme dei chiamanti):

```python
def _build_app(memory_service=None) -> FastAPI:
    """Lightweight FastAPI app with only the memory router mounted."""
    from backend.services.knowledge import QdrantBackend
    from backend.services.knowledge.service import KnowledgeService

    app = FastAPI()
    app.include_router(router, prefix="/api")
    knowledge_service = KnowledgeService(
        backend=QdrantBackend(memory_service=memory_service),
        memory_service=memory_service,
    )
    app.state.context = SimpleNamespace(
        memory_service=memory_service,
        knowledge_service=knowledge_service if memory_service is not None else None,
    )
    return app
```

2. Le asserzioni sulla shape della lista: sostituisci ogni accesso a `"entries"` con `"items"` nel corpo dei test (trova con `git grep -n "\"entries\"" -- tests/test_memory_api.py` e sostituisci puntualmente; il numero atteso di occorrenze è basso, tipicamente 2-4).
3. Le asserzioni sul mock (`svc.list/search/delete/delete_by_scope/stats/delete_all`) restano valide (stessa catena del Task 3). ATTENZIONE a un cambo di chiamata: la route ora chiama `svc.list(kind="memory", filters=..., limit=..., offset=...)` sul SERVICE, che si traduce in `memory_service.list(filter=..., limit=..., offset=...)` — se un test asserisce i kwargs esatti di `list`, la chiave resta `filter` (traduzione di `QdrantBackend._build_memory_filter`). Se un test asserisce `delete_by_scope`, resta chiamato con `"session"` posizionale.
4. Esegui:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_memory_api.py -v
```

Atteso: PASS. Se un'asserzione fallisce su una shape, adeguala alla nuova shape tipizzata (es. `created_at` ora serializzato da Pydantic in ISO-8601 — stringa equivalente).

- [ ] **Step 4: Brucia le 6 righe di baseline**

Da `backend/tests/contracts/response_model_baseline.txt` ELIMINA esattamente queste righe:

```
DELETE /api/memory/all
DELETE /api/memory/session
DELETE /api/memory/{memory_id}
GET /api/memory
GET /api/memory/stats
POST /api/memory/search
```

Poi:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/contracts/test_response_models.py -v
```

Atteso: PASS (NON eseguire `test_openapi_export` qui: resta rosso fino al Task 10).

- [ ] **Step 5: Lint scoped e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check services/knowledge/schemas.py api/routes/memory.py tests/test_memory_api.py
..\.venv\Scripts\python.exe -m mypy services/knowledge/schemas.py api/routes/memory.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git add backend/services/knowledge/schemas.py backend/api/routes/memory.py backend/tests/test_memory_api.py backend/tests/contracts/response_model_baseline.txt
git commit -m "refactor(memory): route deleganti a KnowledgeService, response tipizzate {items,total} (ratchet -6)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: `/api/knowledge/readiness` + `/api/vector-store*` tipizzate (baseline −4)

**Files:**
- Rewrite: `backend/api/routes/knowledge.py`
- Modify: `backend/api/routes/vector_store.py`
- Modify: `backend/tests/contracts/response_model_baseline.txt` (−4 righe)

- [ ] **Step 1: Riscrivi `backend/api/routes/knowledge.py`**

Contenuto COMPLETO:

```python
"""Knowledge/RAG readiness status route."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class RagReadinessResponse(BaseModel):
    """RAG/knowledge readiness verdict."""

    ready: bool
    reason: str
    memory_enabled: bool
    tool_rag_enabled: bool


@router.get(
    "/readiness",
    summary="RAG/knowledge readiness verdict",
    response_model=RagReadinessResponse,
)
async def readiness(request: Request) -> RagReadinessResponse:
    """Return the current RAG readiness verdict (or a not-initialized default)."""
    ctx = request.app.state.context
    rr = getattr(ctx, "rag_readiness", None)
    if rr is None:
        return RagReadinessResponse(
            ready=False,
            reason="not initialized",
            memory_enabled=False,
            tool_rag_enabled=False,
        )
    return RagReadinessResponse(
        ready=rr.ready,
        reason=rr.reason,
        memory_enabled=rr.memory_enabled,
        tool_rag_enabled=rr.tool_rag_enabled,
    )
```

- [ ] **Step 2: Tipizza `vector_store.py`**

In `backend/api/routes/vector_store.py`:

1. Aggiungi dopo gli import esistenti:

```python
from pydantic import BaseModel

from backend.api.routes.knowledge import RagReadinessResponse


class VectorStoreCollectionInfo(BaseModel):
    """Stats of a single Qdrant collection."""

    name: str
    points_count: int
    vectors_size: int


class VectorStoreStatsResponse(BaseModel):
    """Vector store status + effective RAG readiness."""

    mode: str
    connected: bool
    collections: list[VectorStoreCollectionInfo]
    rag: RagReadinessResponse


class ReembedToolsResponse(BaseModel):
    """Outcome of the tool re-embedding trigger."""

    status: str
```

2. `_rag_status` ritorna il modello (firma `-> RagReadinessResponse`); il corpo diventa:

```python
    rag = getattr(ctx, "rag_readiness", None)
    if rag is None:
        return RagReadinessResponse(
            ready=False,
            reason="not initialised",
            memory_enabled=False,
            tool_rag_enabled=False,
        )
    return RagReadinessResponse(
        ready=bool(rag.ready),
        reason=rag.reason,
        memory_enabled=bool(rag.memory_enabled),
        tool_rag_enabled=bool(rag.tool_rag_enabled),
    )
```

3. `_build_stats` (firma `-> VectorStoreStatsResponse`): i tre `return`/append diventano costruzioni dei modelli — `return VectorStoreStatsResponse(mode="unavailable", connected=False, collections=[], rag=_rag_status(ctx))` per il ramo senza qdrant; `collections_info: list[VectorStoreCollectionInfo] = []` con `collections_info.append(VectorStoreCollectionInfo(name=coll_name, points_count=count, vectors_size=dim if dim is not None else 0))` (e il ramo except con `points_count=0, vectors_size=0`); return finale `VectorStoreStatsResponse(mode=mode, connected=True, collections=collections_info, rag=_rag_status(ctx))`.
4. Decoratori/firme: `@router.get("/stats", response_model=VectorStoreStatsResponse)` con `-> VectorStoreStatsResponse`; `@router.post("/repair", response_model=VectorStoreStatsResponse)` con `-> VectorStoreStatsResponse`; `@router.post("/reembed-tools", response_model=ReembedToolsResponse)` con `-> ReembedToolsResponse` e `return ReembedToolsResponse(status="ok")`.
5. Rimuovi l'import `Any` se resta inutilizzato (ruff lo segnala).

- [ ] **Step 3: Brucia le 4 righe di baseline ed esegui il ratchet**

Da `response_model_baseline.txt` ELIMINA:

```
GET /api/knowledge/readiness
GET /api/vector-store/stats
POST /api/vector-store/reembed-tools
POST /api/vector-store/repair
```

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/contracts/test_response_models.py -v
..\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
```

Atteso: PASS + `app ok`.

- [ ] **Step 4: Lint scoped e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check api/routes/knowledge.py api/routes/vector_store.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git add backend/api/routes/knowledge.py backend/api/routes/vector_store.py backend/tests/contracts/response_model_baseline.txt
git commit -m "refactor(knowledge): readiness e vector-store tipizzate (ratchet -4)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: `/api/mcp/memory*` tipizzate (baseline −9)

**Files:**
- Modify: `backend/api/routes/mcp_memory.py`
- Create: `backend/tests/test_mcp_memory_models.py`
- Modify: `backend/tests/contracts/response_model_baseline.txt` (−9 righe)

- [ ] **Step 1: Scrivi il test dei modelli (failing)**

Crea `backend/tests/test_mcp_memory_models.py`:

```python
"""Unit tests for the /api/mcp/memory response models (Fase 4)."""

from __future__ import annotations

from backend.api.routes.mcp_memory import KGGraphResponse, _graph


def test_graph_parses_server_shape():
    data = {
        "entities": [
            {"name": "Ada", "entityType": "person", "observations": ["likes math"]},
        ],
        "relations": [
            {"from": "Ada", "to": "Babbage", "relationType": "knows"},
        ],
    }
    g = _graph(data)
    assert g.entities[0].name == "Ada"
    assert g.relations[0].from_entity == "Ada"


def test_graph_falls_back_to_empty_on_mismatch():
    g = _graph({"entities": "nope"})
    assert g.entities == []
    assert g.relations == []


def test_graph_falls_back_on_non_graph_payload():
    # _call() wraps non-JSON tool output as {"result": raw}.
    g = _graph({"result": "plain text"})
    assert g.entities == []
    assert g.relations == []


def test_graph_serializes_from_alias():
    data = {
        "entities": [],
        "relations": [{"from": "A", "to": "B", "relationType": "r"}],
    }
    dumped = _graph(data).model_dump(by_alias=True)
    assert dumped["relations"][0]["from"] == "A"
```

Esegui per vederlo fallire (import error):

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_mcp_memory_models.py -v
```

- [ ] **Step 2: Aggiungi modelli + helper in `mcp_memory.py`**

Dopo il blocco `# ── Request models ──...` (in coda ad esso, prima di `# ── Endpoints ──`), aggiungi:

```python
# ── Response models ────────────────────────────────────────────────────────


class KGEntityRead(BaseModel):
    """Entity node as returned by the MCP memory server."""

    name: str
    entityType: str  # MCP server field name (camelCase, as in EntityInput)
    observations: list[str]


class KGRelationRead(BaseModel):
    """Directed relation between two entities."""

    from_entity: str = Field(alias="from")
    to: str
    relationType: str  # MCP server field name (camelCase, as in RelationInput)

    model_config = {"populate_by_name": True}


class KGGraphResponse(BaseModel):
    """Knowledge-graph snapshot (entities + relations)."""

    entities: list[KGEntityRead]
    relations: list[KGRelationRead]


class KGMutationResponse(BaseModel):
    """Mutation acknowledgement (the client reloads the graph)."""

    ok: bool = True


def _graph(data: Any) -> KGGraphResponse:
    """Normalise an MCP tool result to a graph (empty on unexpected shape)."""
    try:
        return KGGraphResponse.model_validate(data)
    except ValidationError:
        logger.warning("MCP memory returned an unexpected graph shape")
        return KGGraphResponse(entities=[], relations=[])
```

Aggiungi `ValidationError` all'import pydantic: `from pydantic import BaseModel, Field, ValidationError`.

- [ ] **Step 3: Tipizza i 9 endpoint**

Le tre letture (decoratore + return):

```python
@router.get("/graph", response_model=KGGraphResponse)
async def read_graph(request: Request) -> KGGraphResponse:
    """Read the entire knowledge graph (entities + relations)."""
    session = _get_memory_session(request)
    return _graph(await _call(session, "read_graph", {}))
```

```python
@router.post("/search", response_model=KGGraphResponse)
async def search_nodes(request: Request, body: SearchRequest) -> KGGraphResponse:
    """Search entities by query across names, types, and observations."""
    session = _get_memory_session(request)
    return _graph(await _call(session, "search_nodes", {"query": body.query}))
```

```python
@router.post("/nodes", response_model=KGGraphResponse)
async def open_nodes(request: Request, body: OpenNodesRequest) -> KGGraphResponse:
    """Retrieve specific entities by name with their relations."""
    session = _get_memory_session(request)
    return _graph(await _call(session, "open_nodes", {"names": body.names}))
```

Le sei mutazioni: stesso pattern per tutte — decoratore `response_model=KGMutationResponse`, firma `-> KGMutationResponse`, il corpo esistente resta ma il `return await _call(...)` diventa `await _call(...)` seguito da `return KGMutationResponse()`. Esempio per `create_entities` (applicare identico a `delete_entities`, `create_relations`, `delete_relations`, `add_observations`, `delete_observations`):

```python
@router.post("/entities", response_model=KGMutationResponse)
async def create_entities(
    request: Request, body: CreateEntitiesRequest,
) -> KGMutationResponse:
    """Create new entities in the knowledge graph."""
    session = _get_memory_session(request)
    entities = [
        {
            "name": e.name,
            "entityType": e.entityType,
            "observations": e.observations,
        }
        for e in body.entities
    ]
    await _call(session, "create_entities", {"entities": entities})
    return KGMutationResponse()
```

- [ ] **Step 4: Test + baseline −9 + ratchet**

Da `response_model_baseline.txt` ELIMINA:

```
DELETE /api/mcp/memory/entities
DELETE /api/mcp/memory/observations
DELETE /api/mcp/memory/relations
GET /api/mcp/memory/graph
POST /api/mcp/memory/entities
POST /api/mcp/memory/nodes
POST /api/mcp/memory/observations
POST /api/mcp/memory/relations
POST /api/mcp/memory/search
```

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_mcp_memory_models.py tests/contracts/test_response_models.py -v
```

Atteso: PASS.

- [ ] **Step 5: Lint scoped e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check api/routes/mcp_memory.py tests/test_mcp_memory_models.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git add backend/api/routes/mcp_memory.py backend/tests/test_mcp_memory_models.py backend/tests/contracts/response_model_baseline.txt
git commit -m "refactor(mcp-memory): risposte tipizzate KGGraph/KGMutation (ratchet -9)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Eliminazione `ctx.knowledge_backend` + guardie grep

**Files:**
- Modify: `backend/core/context.py` (rimuovi campo + import)
- Modify: `backend/core/app.py` (rimuovi alias di transizione)
- Modify: `backend/services/knowledge_init.py` (rimuovi alias di transizione)

- [ ] **Step 1: Rimuovi il campo e gli alias**

1. `backend/core/context.py`: elimina il campo `knowledge_backend` col suo docstring (righe ~70-73); rimuovi `KnowledgeBackendProtocol` dall'import se non resta altro uso nel file.
2. `backend/core/app.py`: elimina le 3 righe dell'alias di transizione (commento `# Fase 4 transition alias...` + `ctx.knowledge_backend = ctx.knowledge_service.backend`).
3. `backend/services/knowledge_init.py`: idem (commento + assegnazione).
4. `backend/core/protocols.py`: se `git grep -n "KnowledgeBackendProtocol" -- backend` mostra SOLO la definizione dell'alias (nessun consumatore), riduci il re-import a:

```python
from backend.services.knowledge.protocol import (  # noqa: E402
    KnowledgeServiceProtocol,
)
```

(altrimenti lascialo e annota i consumatori residui nell'esito del task).

- [ ] **Step 2: Guardie grep (output atteso: vuoto o solo i path indicati)**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "knowledge_backend" -- backend ':!backend/services/knowledge' ':!backend/tests'
git grep -n "memory_service" -- backend/plugins backend/api/routes
git grep -n "knowledge_service.backend" -- backend ':!backend/services/knowledge' ':!backend/tests'
```

Atteso: (1) nessuna riga fuori da `services/knowledge/` e dai test (i test dei backend li esercitano legittimamente; i test dei CONSUMER sono già stati migrati nei Task 3-6 — se compare un file di test consumer, è un leftover da correggere); (2) nessuna riga (plugins e route non toccano più `memory_service`); (3) nessuna riga (la property `backend` è solo wiring/test — dopo lo Step 1 nemmeno il wiring la usa più: se compare, rimuovi l'uso).

- [ ] **Step 3: Regressione mirata del dominio**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_knowledge_service.py tests/test_memory_plugin.py tests/test_memory_api.py tests/test_continuum_notes.py tests/test_continuum_plugin.py tests/test_continuum_backend.py tests/test_rag_readiness.py tests/test_chat_memory_context.py tests/test_mcp_memory_models.py tests/contracts/test_response_models.py -v
..\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
```

Atteso: PASS + `app ok`.

- [ ] **Step 4: Lint scoped e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check core/context.py core/app.py services/knowledge_init.py core/protocols.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git add backend/core/context.py backend/core/app.py backend/services/knowledge_init.py backend/core/protocols.py
git commit -m "refactor(knowledge): rimozione ctx.knowledge_backend, KnowledgeService unico ingresso" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Regen contratti + migrazione FE + gate

**Files:**
- Regen: `.\scripts\gen-contracts.ps1` (openapi + `types/generated/`)
- Rewrite: `frontend/src/renderer/src/types/memory.ts`
- Modify: `frontend/src/renderer/src/types/mcpMemory.ts` (sezione tipi risposta)
- Modify: `frontend/src/renderer/src/types/settings.ts:121-134`
- Modify: `frontend/src/renderer/src/services/api.ts` (metodi memory)
- Modify: `frontend/src/renderer/src/stores/memory.ts` (`entries` → `items`)
- Modify: `frontend/src/renderer/src/components/settings/MemoryManager.vue` (fallback opzionali)

- [ ] **Step 1: Rigenera i contratti**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
.\scripts\gen-contracts.ps1
```

Poi verifica l'export OpenAPI:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/contracts/ -v
```

Atteso: PASS (incluso `test_openapi_export`, di nuovo verde dopo la regen).

- [ ] **Step 2: Riscrivi `types/memory.ts`**

Contenuto COMPLETO:

```ts
/**
 * memory.ts — Frontend types for the AL\CE memory domain.
 *
 * Re-exports of the GENERATED OpenAPI schemas (single source of truth:
 * backend/services/knowledge/schemas.py). Fields with backend defaults
 * (category, source, created_at, …) are OPTIONAL here — consumers must
 * use `??` fallbacks.
 */

import type { ApiSchema } from './generated'

/** Memory entry returned by the API. */
export type MemoryEntry = ApiSchema<'MemoryEntryRead'>

/** Search result with similarity score. */
export type MemorySearchResult = ApiSchema<'MemorySearchHit'>

/** Memory statistics. */
export type MemoryStats = ApiSchema<'MemoryStatsResponse'>

/** Memory list response ({items, total}). */
export type MemoryListResponse = ApiSchema<'MemoryListResponse'>

/** Memory search response. */
export type MemorySearchResponse = ApiSchema<'MemorySearchResponse'>

/** Single-delete acknowledgement. */
export type MemoryDeleteResponse = ApiSchema<'MemoryDeleteResponse'>

/** Bulk-delete count. */
export type MemoryDeleteCountResponse = ApiSchema<'MemoryDeleteCountResponse'>
```

- [ ] **Step 3: Re-export dei tipi risposta in `types/mcpMemory.ts` e `types/settings.ts`**

In `types/mcpMemory.ts` sostituisci le TRE interface `KGEntity`, `KGRelation`, `KGGraph` (righe ~11-28) con:

```ts
import type { ApiSchema } from './generated'

/** An entity node in the knowledge graph. */
export type KGEntity = ApiSchema<'KGEntityRead'>

/** A directed relation between two entities. */
export type KGRelation = ApiSchema<'KGRelationRead'>

/** The full knowledge graph structure (entities + relations). */
export type KGGraph = ApiSchema<'KGGraphResponse'>
```

(le interface dei payload di request restano hand-typed — sono request body, non risposte).

In `types/settings.ts` sostituisci le interface `RagReadinessStatus` (righe ~121-126), `VectorStoreCollectionInfo` e `VectorStoreStats` (righe ~128-134) con:

```ts
/** Effective RAG readiness (generated from the backend contract). */
export type RagReadinessStatus = ApiSchema<'RagReadinessResponse'>

/** Stats of a single Qdrant collection. */
export type VectorStoreCollectionInfo = ApiSchema<'VectorStoreCollectionInfo'>

/** Vector store status + effective RAG readiness. */
export type VectorStoreStats = ApiSchema<'VectorStoreStatsResponse'>
```

aggiungendo in testa al file (se assente) `import type { ApiSchema } from './generated'`.

- [ ] **Step 4: `api.ts` + `stores/memory.ts`**

In `services/api.ts` (metodi memory ~633-672): aggiungi `MemoryDeleteResponse, MemoryDeleteCountResponse` all'import da `../types/memory`; `deleteMemory` diventa `Promise<MemoryDeleteResponse>` (e `request<MemoryDeleteResponse>`); `clearSessionMemory`/`clearAllMemory` diventano `Promise<MemoryDeleteCountResponse>` (e `request<MemoryDeleteCountResponse>`). Gli altri metodi restano (i tipi importati ora sono i generati).

In `stores/memory.ts`, in `loadMemories` sostituisci `entries.value = data.entries` con `entries.value = data.items`.

- [ ] **Step 5: Typecheck + fix consumatori opzionali**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\frontend
npm run typecheck
```

Fix attesi (campi con default → opzionali nei tipi generati):
- `MemoryManager.vue`: le due chiamate `formatDate(result.entry.created_at)` / `formatDate(entry.created_at)` — adegua la firma di `formatDate` a `(iso?: string | null)` con `if (!iso) return ''` in testa (una modifica sola, due call-site invariati).
- `stores/mcpMemory.ts`: già difensivo (`graph.entities ?? []`); se il typecheck segnala accessi non-null su `KGEntity`/`KGRelation` in `KnowledgeGraphManager.vue` o nei dialog KG, aggiungi `?? ''`/`?? []` puntuali.
- Eventuali altri errori NUOVI segnalati dal typecheck nei file del dominio: correggili con fallback `??`; errori PRE-esistenti fuori dominio si lasciano (confronta con `git stash` se in dubbio).

Ripeti `npm run typecheck` fino a 0 errori nuovi.

- [ ] **Step 6: Gate FE + commit + check-contracts**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\frontend
npx eslint src/renderer/src/types/memory.ts src/renderer/src/types/mcpMemory.ts src/renderer/src/types/settings.ts src/renderer/src/services/api.ts src/renderer/src/stores/memory.ts src/renderer/src/components/settings/MemoryManager.vue
npx vitest run
```

Atteso: eslint senza ERRORI (warning tollerati), vitest tutti verdi (259+).

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add -A
git commit -m "feat(contracts): regen fase4 + FE memoria/KG/vector-store sui tipi generati" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
.\scripts\check-contracts.ps1
```

Atteso: check-contracts verde (eseguito DOPO il commit — untracked = dirty).

---

### Task 11: Smoke e2e + chiusura fase

**Files:**
- Modify: `CLAUDE.md` (bullet Qdrant/knowledge)
- Modify: questo piano (esiti per task)

- [ ] **Step 1: Smoke e2e reale**

Avvia il backend (da repo root, venv attivo o path esplicito):

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\python.exe -m backend
```

In una seconda shell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/knowledge/readiness | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/api/vector-store/stats | ConvertTo-Json -Depth 5
Invoke-RestMethod "http://127.0.0.1:8000/api/memory?limit=5" | ConvertTo-Json -Depth 5
```

Attesi: readiness JSON con i 4 campi tipizzati; stats con `collections[]` e `rag{}`; memoria `{items: [...], total: n}` (200) oppure 503 SOLO se lo stack RAG è giù (in quel caso verifica che `readiness.reason` lo spieghi). Se la memoria è attiva, verifica anche la search:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/memory/search -ContentType "application/json" -Body '{"query": "test"}' | ConvertTo-Json -Depth 5
```

Atteso: `{results: [...]}`. Chiudi il backend.

- [ ] **Step 2: Aggiorna CLAUDE.md (doc drift)**

Nel bullet «**Qdrant** is the vector store…» sostituisci la frase `Both sit behind the ``KnowledgeBackend`` abstraction (``services/knowledge/``) — ``QdrantBackend`` and ``ContinuumBackend`` composed by ``CompositeKnowledgeBackend``. Consume the backend, not the underlying services.` con: `Both sit behind **``KnowledgeService``** (``services/knowledge/service.py``) — the single entry point to the knowledge domain, wrapping ``QdrantBackend``/``ContinuumBackend`` composed by ``CompositeKnowledgeBackend``. Consume ``ctx.knowledge_service``, never the backends or ``memory_service`` directly.`

- [ ] **Step 3: Gate finale di fase**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_knowledge_service.py tests/test_memory_plugin.py tests/test_memory_api.py tests/test_memory_service.py tests/test_continuum_notes.py tests/test_continuum_plugin.py tests/test_continuum_backend.py tests/test_rag_readiness.py tests/test_chat_memory_context.py tests/test_mcp_memory_models.py tests/contracts/ -v
```

Atteso: tutti PASS. Poi:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\frontend
npm run typecheck
npx vitest run
```

- [ ] **Step 4: Commit di chiusura (piano aggiornato con esiti + CLAUDE.md)**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add CLAUDE.md docs/superpowers/plans/2026-07-01-fase4-conoscenza.md
git commit -m "docs: fase4 - CLAUDE.md su KnowledgeService, tick criteri di uscita" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Criteri di uscita della fase

- [ ] `KnowledgeService` unico ingresso: nessun consumer fuori da `services/knowledge/` tocca `knowledge_backend`/`memory_service` (guardie grep Task 9 verdi).
- [ ] `ContinuumClient` costruito in UN solo punto (`core/app.py`).
- [ ] Plugin memory = guscio sottile (5 tool, zero logica di persistenza propria); note tools continuum su `knowledge_service`.
- [ ] Route memory/knowledge/vector-store/mcp-memory tipizzate; baseline ratchet −19; regen + check-contracts verdi.
- [ ] FE su tipi generati per memoria, KG e vector store; typecheck 0; vitest verdi.
- [ ] App avviabile; smoke e2e del dominio (readiness, stats, lista/search memoria) verificato.

## Backlog emerso (fuori scope fase 4)

- `api/routes/mcp_memory.py` importa `McpClientPlugin` (TYPE_CHECKING) e pesca il plugin dal plugin_manager — violazione §4 "route ↛ plugin internals" da sanare in fase 5 con un service/protocol MCP.
- `MemoryService.list` con offset fa scroll O(offset) su Qdrant (pre-esistente); valutare cursor-based nella UI se le memorie crescono.
- `QdrantBackend.get/update` su kind memory sono no-op documentati: se servisse un `GET /api/memory/{id}`, aggiungere `retrieve` puntuale a MemoryService.
- Convenzione `{items,total}`: `MemorySearchResponse.results` e i payload dei tool (`memories`, `notes`) restano fuori convenzione (search/tool output, non liste REST) — riesaminare in fase 6 se si vuole uniformare anche lì.
