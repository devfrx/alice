# Fase 5 — Kernel (AppContext a gruppi, bootstrap a stage, split registry/LLM, flag, import-linter) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** il kernel diventa leggibile e vincolato (spec §5.1 + §9): `AppContext` decomposto in **5 gruppi coesi** con radice sottile compatibile; lifespan sostituito da un **bootstrap dichiarativo a stage**; `tool_registry` splittato in **catalogo vs policy** (package `core/tools/`); `llm_service` splittato in **client / prompt / capability** (package `services/llm/`); **censimento dei flag `enabled`** con rimozione dei morti e registro unico; **import-linter in CI** con i contratti del §4 (dopo aver sanato le violazioni note).

**Architecture:** i 5 gruppi (`InferenceServices`, `KnowledgeServices`, `WorkspaceServices`, `ConversationServices`, `PlatformServices`) sono i campi canonici; `AppContext` resta l'API pubblica tramite property piatte deleganti (get+set) così i ~80 file consumer e i ~20 test che costruiscono `AppContext(...)` con kwargs restano intatti — la migrazione dei consumer ai gruppi è fuori scope (backlog). Il bootstrap estrae le 30 sezioni del lifespan in 9 stage 1:1 con l'ordine ATTUALE (zero riordini) in `backend/core/bootstrap/`. Gli split registry/LLM sono facade-preserving: `ToolRegistry` e `LLMService` mantengono firma e API pubblica, i componenti interni diventano moduli. Il repair del vector store passa a **swap atomico del gruppo Knowledge** (chiude la finestra di concorrenza, backlog fase 4).

**Tech Stack:** FastAPI + dataclass/Protocol, import-linter (grimp), pytest mirati, openapi-typescript (solo Task 6).

**Branch:** `arch/fase5-kernel` (figlio di `arch/fase4-conoscenza`, già creato).

---

## Contesto verificato (recon 2026-07-08, agenti + verifica a mano)

**AppContext (`core/context.py`, 248 righe):** dataclass con 35 campi — 16 tipati Protocol, 13 `Any` (per rompere il ciclo core→services), 6 concreti; soli 2 required (`config`, `event_bus`); `plugin_local_state` con default_factory + metodi `get_plugin_state`/`set_plugin_state`. **~20 file di test costruiscono `AppContext(config=..., event_bus=..., <campo>=...)` direttamente, anche con `**overrides`** (es. `test_cad_generator_plugin.py:99` passa `lmstudio_manager=`, `test_weather_plugin.py` passa `**overrides`) → il nuovo costruttore DEVE accettare i kwargs piatti legacy.

**Lifespan (`core/app.py:50-801`):** 30 sezioni ordinate (mappa completa nel Task 2). Vincoli hard di ordine: `memory←qdrant+embedding`; `knowledge←memory+continuum_client`; `tool_registry←plugin_manager`; `rag_readiness←tool_registry.refresh()`; `permission_service←scope+rule`; `terminal←scope`; `ws_connection_manager` creato prima dei callback broadcast (sezioni 21-29, tutti con guardia lazy). Localismi: `config = ctx.config` alias risincronizzato dopo il config service (`app.py:100`); `testing` gate su prefs/plugin-seed; pre-bind dei locali per il `finally` (righe 57-64). Shutdown ordinato in 13 step (righe 732-801), ognuno in try/except isolato.

**Mutazioni ctx FUORI dal lifespan (da preservare):** `services/knowledge_init.py` `repair_vector_store` riassegna `qdrant_service`/`memory_service`/`knowledge_service`/`rag_readiness` (righe 67-128); `api/routes/config.py` riassegna `config` (161) e riavvia `stt_service` (757/776/787), `tts_service` (808/830/836), `email_service` (888/899); `api/routes/services.py:93` riassegna `config`.

**tool_registry (`core/tool_registry.py`, 1183 righe):** stato catalogo `_tools`/`_tool_to_plugin`/`_openai_cache` + `_lock`; availability `_status_cache` (TTL 30s, probe 3s); RAG `_qdrant`/`_embedder`/`_llm_config`. Classificazione: CATALOGO = `refresh` (211-318: validazione+namespacing+dedup+cache OpenAI), `get_all_tools`, `get_tool_plugin`, `get_tool_definition`, `get_tool_catalog`; POLICY di offerta = `limit_tools` (485-535), `exclude_disabled` (591-616), `apply_mode_policy` (648-713); AVAILABILITY = `clear_status_cache`, `_resolve_plugin_statuses`, `_probe_plugin_status`; RAG = `set_vector_backends`, `embed_tools` (719-802), `get_relevant_tools` (804-912); EXECUTION = `execute_tool` (975-1182), `_coerce_args`, helper modulo di sanitisation (43-158). MISTI (compongono catalogo+availability): `get_available_tools`, `get_tools_for_plugins`, `usage_guidance_for`. Il gating PERMESSI utente NON è qui (vive in `PermissionService.decide`); qui c'è solo la policy di offerta/selezione. Consumer POLICY concentrati in `chat/_assembly.py` e `chat/conversations.py`; dispatch in `turn/pipeline.py`, `tool_loop.py`, `_subagent.py`, `news/plugin.py`. Violazione layering: riga 21 importa `COLLECTION_TOOLS`, `PROJECT_NS` da `services/qdrant_service.py`. Test: `test_tool_registry.py` (~920 righe), `test_tool_status_caching.py`, `test_permission_mode_policy.py` (lega policy_for + apply_mode_policy).

**llm_service (`services/llm_service.py`, 1694 righe):** classificazione per lo split — CLIENT: `_sanitize_tool_calls` (28-60), `chat` (832-895), `_chat_lmstudio_native` (901-1063), `_stream_lmstudio_native_sse` (1069-1235), `_chat_openai_compat` (1241-1561), `complete_nonstreaming` (1567-1606), `close` (1688-1693); stato `_client` httpx, `_is_ollama`, `_response_ids(+max)`, `_supports_stream_options`, `_supports_response_format`. PROMPT: `normalize_history` (63-112), `_load_system_prompt` (434-481), `invalidate_system_prompt_cache`, `_temporal_block`, `_get_dynamic_system_prompt`, `get_system_prompt` (530-566), `_load_scoped_prompt`, `get_scoped_system_prompt` (596-626), `_fold_system_into_user` (632-700), `build_messages` (702-787), `build_continuation_messages` (789-826); stato `_system_prompt`, `_scoped_prompts`. CAPABILITY: statics `_is_embedding_model`/`_model_id`/`_is_loaded`/`_pick_chat_model_id` (176-248), `_get_model_profile`, `supports_vision`, `_resolve_model` (289-423), `invalidate_model_cache`, famiglia context-window (1608-1682); stato `_model_registry`, `_auto_model_cache(+ttl,lock)`, `_ctx_window_*`. I metodi di streaming scrivono sul registry (learning `mark_*`) — seam CLIENT→CAPABILITY da rendere esplicito. `LLMServiceProtocol` (protocols.py:34-109) NON dichiara `get_scoped_system_prompt`, `get_cached_context_window`, `invalidate_context_window_cache`, né i param `response_format`/`temperature` di `chat` — usati dai consumer reali. Satelliti già esistenti: `model_capability_registry.py` (profili+learning), `prompt_composer.py` (blocchi dinamici), `thinking_parser.py`, `context_manager.py`. Test: `test_llm_service.py` (PROMPT), `test_llm_model_resolution.py` (usa i privati `_resolve_model`/`_is_loaded`/`_is_embedding_model` sul service), `test_llm_preferred_name.py`, `test_context_window_cache.py`.

**Flag `enabled` (censimento completo):** 24 booleani; 21 VIVI, **3 MORTI**: `voice.voice_confirmation_enabled` (config.py:330, default.yaml:113, echo get/set in routes/config.py:302,608-613 — nessun consumatore BE/FE), `pc_automation.enabled` (config.py:347, default.yaml:116, echo routes/config.py:307,632-638 — il gate reale è `plugins.enabled`), `notifications.sound_enabled` (config.py:520, default.yaml:199 — il plugin non lo legge). **Ogni config model è `extra=forbid`** → la rimozione richiede strip legacy per-layer (pattern esistente `migrate_legacy_config_keys` + `_migrate_pc_automation_permissions`, config.py:1147-1230). `plugins.enabled` è una LISTA di nomi con seed+override DB (plugin_state_repo) — layer separato dai `<sezione>.enabled` (doppio gate by design). Affini fuori perimetro: `agent.planning`/`delegation`/`clarification` (rinominati da `*_enabled`).

**Layering (violazioni attuali, censimento grimp-equivalente):** (a) plugin↛plugin: NESSUNA; (b) route→plugin: `api/routes/calendar.py:17-18` (runtime: `CalendarEvent` + `MAX_OCCURRENCES`/`validate_rrule`), `api/routes/mcp.py:14` e `api/routes/mcp_memory.py:20` (TYPE_CHECKING `McpClientPlugin` — grimp li conta comunque); (c) services↛api: NESSUNA; (d) import `continuum`: NESSUNA; extra: services→plugins `services/terminal/manager.py:42` (`ensure_sandbox`, `validate_cwd_within_scope` da `plugins/terminal/security.py`, 288 righe, altri riferimenti solo in docstring/test); core→services: `tool_registry.py:21` (costanti), `protocols.py:524` (re-export Protocol), `managed_services/{lmstudio,stt,tts,vram}.py`, `context.py:37` (TYPE_CHECKING), `app.py` (composition root, import massicci services+api). Le route MCP usano SOLO: `get_status()`, `get_server_tools(name)`, `reconnect_server(name, config)` (mcp.py) e `get_session(name)` (mcp_memory.py); 503: `"Plugin manager not available"`, `"MCP client plugin not loaded"`, `"MCP server 'memory' not connected"`.

**Costanti qdrant:** `COLLECTION_MEMORY`/`COLLECTION_TOOLS`/`PROJECT_NS` in `qdrant_service.py:25-31`; solo `COLLECTION_TOOLS`+`PROJECT_NS` importate da core. `QdrantServiceProtocol` (protocols.py:257-294) NON dichiara `in_memory` (property concreta a qdrant_service.py:53; consumata da `vector_store.py:102` → mypy attr-defined, gap noto fase 4).

**CI / packaging:** unico workflow `.github/workflows/contracts.yml` (windows-latest, pwsh); aggancio import-linter dopo lo step "Contract tests". `import-linter` ASSENTE da `backend/pyproject.toml` (dev = pytest/pytest-asyncio/pytest-cov/ruff/mypy). Il package `backend` è importabile dalla REPO ROOT (`backend/__init__.py` esiste e applica un workaround: NON toccarlo); i test girano da `backend/` (conftest gestisce il path). → `lint-imports` va lanciato dalla repo root con `--config backend/pyproject.toml`.

**Vincoli operativi (gotchas handoff, validi qui):** suite backend completa impraticabile → test mirati; `npm run lint` rotto repo-wide → `npx eslint <file toccati>` (solo ERRORI) + `npm run typecheck`; ruff/mypy scoped (file nuovi puliti; pre-esistenze confrontate con `git show arch/fase4-conoscenza:<file>`); **EOL: verificare `git ls-files --eol <file>` al ritorno di ogni subagent** (due incidenti in fase 4); MAI cmdlet PowerShell su file non-ASCII; `check-contracts.ps1` DOPO il commit; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`; boot-check dalla REPO ROOT; niente `&&` in PowerShell 5.1; `test_openapi_export` si esegue SOLO nel task di regen (Task 6) e al gate finale.

---

## Decisioni di design della fase (registrate, non rilitigare durante l'esecuzione)

1. **I 5 gruppi sono quelli nominati dalla spec §5.1**, mappatura COMPLETA dei 35 campi (nessun campo resta orfano):
   - `InferenceServices` (8): `llm_service`, `stt_service`, `tts_service`, `lmstudio_manager`, `vram_monitor`, `model_registry`, `model_downloader`, `embedding_client` (la spec elenca "embedding" qui; il repair lo RIUSA senza ricrearlo).
   - `KnowledgeServices` (5): `knowledge_service`, `memory_service`, `qdrant_service`, `continuum_client`, `rag_readiness`.
   - `WorkspaceServices` (5): `scope_service`, `permission_service`, `permission_mode_service`, `permission_rule_service`, `terminal_session_manager`.
   - `ConversationServices` (6): `db`, `engine`, `context_manager`, `plan_service`, `plan_document_service`, `artifact_registry`.
   - `PlatformServices` (10): `event_bus`, `config_service`, `ws_connection_manager`, `plugin_manager`, `tool_registry`, `orchestrator`, `plugin_state_repo`, `preferences_service`, `email_service`, `plugin_local_state`.
   - `config` resta campo RADICE (è il dato risolto, non un servizio; riassegnato dal config service e da 2 route).
2. **Radice sottile con compatibilità totale**: `AppContext` diventa classe regolare (non più dataclass): campi = `config` + 5 gruppi; TUTTI i 34 nomi piatti legacy = property tipizzate get+set deleganti al gruppo; costruttore `__init__(config, event_bus=None, **services)` che accetta i kwargs piatti legacy (guardia: kwarg ignoto → `TypeError`). `create_context` invariato. **La migrazione dei consumer ai gruppi è FUORI scope** (backlog): le property SONO l'API di transizione.
3. **Stage di init ≠ gruppo di appartenenza**: un campo può essere creato in uno stage diverso dal suo gruppo (es. `context_manager` [Conversation] nasce nello stage inference; `rag_readiness` [Knowledge] nasce nello stage plugins). I gruppi modellano l'ownership, gli stage l'ordine.
4. **Bootstrap = estrazione 1:1, ZERO riordini**: 9 stage in `backend/core/bootstrap/` che rispecchiano l'ordine ATTUALE delle 30 sezioni (`database → platform → inference → knowledge → senses → plugins → surfaces → conversation → workspace`) + `shutdown_services`. Ogni stage apre con `config = ctx.config` (la sez. 3 riassegna `ctx.config`, quindi gli stage successivi leggono il risolto — semantica identica all'alias di `app.py:100`). Le guardie `if not testing` si spostano verbatim; `testing` entra nella firma SOLO degli stage che lo usano. I `finally` pre-bind spariscono: lo shutdown legge da `ctx` con guardie.
5. **Repair = swap atomico del gruppo**: `repair_vector_store` costruisce i servizi in locali, poi UNA assegnazione `ctx.knowledge = <nuovo KnowledgeServices>`; `rag_readiness` viene assegnato dopo (richiede il ctx già swappato + registry refresh) — la finestra si riduce da 5 scritture incoerenti a 1 swap coerente + 1 scrittura additiva. Test d'invariante nuovo (backlog fase 4 chiuso).
6. **Split `tool_registry` facade-preserving**: package `backend/core/tools/` (`catalog.py`, `availability.py`, `policy.py`, `execution.py`, `rag.py`); `ToolRegistry` resta in `core/tool_registry.py` con firma `__init__` e API pubblica IDENTICHE, delegando ai componenti; `ToolRegistryProtocol` e tutti i consumer invariati; l'intera suite `test_tool_registry.py`/`test_tool_status_caching.py`/`test_permission_mode_policy.py` deve passare SENZA modifiche (è il criterio di equivalenza). Costanti `COLLECTION_TOOLS`/`PROJECT_NS` spostate in `backend/core/vector_collections.py` (qdrant_service le importa da lì e le RI-ESPORTA per compat).
7. **Split `llm_service` facade-preserving**: package `backend/services/llm/` (`client.py`, `prompting.py`, `model_resolution.py`); `LLMService` resta in `services/llm_service.py` con API pubblica identica; il facade possiede l'`httpx.AsyncClient` condiviso e lo inietta in client e resolver (seam CLIENT→CAPABILITY esplicito: il client riceve `resolver` + `model_registry`). Il facade mantiene alias privati di compat (`_resolve_model`, `_is_loaded`, `_is_embedding_model`, `_pick_chat_model_id`, `_get_model_profile`) perché `test_llm_model_resolution.py` li usa — migrazione dei test ai moduli = backlog. `normalize_history` ri-esportato da `llm_service.py`. `LLMServiceProtocol` allineato (aggiunte: `get_scoped_system_prompt`, `get_cached_context_window`, `invalidate_context_window_cache`, param `response_format`/`temperature` su `chat`).
8. **Flag**: registro unico `docs/flag-registry.md` (tutti i 21 vivi con lettore e note); i 3 morti RIMOSSI da config model + default.yaml + echo get/set di routes/config.py, con **strip legacy per-layer** nel meccanismo `migrate_legacy_config_keys` (i modelli sono extra=forbid: una chiave stantia in system/user.yaml non deve far fallire il boot). Regen contracts nello stesso task.
9. **Layering sanato PRIMA del linter**: calendar → nuovo `backend/services/calendar_events.py` (modello `CalendarEvent` + `MAX_OCCURRENCES`/`validate_rrule` condivisi; il plugin li importa da lì); MCP → nuovo `backend/services/mcp_gateway.py` (`McpClientProtocol` strutturale + accessor con i tre 503 — chiude il backlog fase 4 "mcp_memory → service MCP"); terminal → `security.py` si SPOSTA in `services/terminal/` (il plugin lo re-importa da lì). Poi import-linter con 6 contratti: i 4 della spec §9 + services↛plugins + core↛services/api con ignore-list esplicita per composition root (`core.app`, `core.bootstrap.*`, `core.managed_services.*`, `core.protocols→services.knowledge.protocol`, `core.context/service_groups→services.rag_readiness`).
10. **Protocol gap**: `QdrantServiceProtocol.in_memory` aggiunto nel Task 3 (dominio knowledge).
11. **Nessun cambiamento di comportamento runtime osservabile**, con due eccezioni dichiarate: shape di GET/PUT `/api/config` senza i 3 flag morti (Task 6, regen inclusa) e ordine di chiusura invariato ma letto da ctx. Ogni task lascia l'app avviabile (boot check).
12. **Docstring/commenti in codice in inglese** (convenzione codebase); piano ed esiti in italiano. Commit convenzionali con trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` (due `-m`, mai here-string).

---

### Task 1: `service_groups.py` + `AppContext` radice sottile con property deleganti

> **Esito (2026-07-08):** DONE. Spec review: conforme (mappatura 34/34 verificata programmaticamente, bijezione FLAT_FIELDS↔gruppi, delega esaustiva; unica deviazione = riordino import di ruff). Quality review (top): "With fixes" — applicati dal controller in `c859291`: test plugin-state reso `async def` (get_event_loop deprecato, nota del piano il cui trigger era scattato), roundtrip test esteso con asserzione di PLACEMENT sul gruppo atteso (un typo cross-gruppo roundtrippava comunque — la mappatura del piano ora è eseguibile), type-args mypy-strict (`async_sessionmaker[AsyncSession]`, `dict[str, dict[str, Any]]`, `MappingProxyType[str, Any]`: mypy 7→0 sui due file core), docstring KnowledgeServices ancorata a "Task 3". Verifiche del reviewer: parità dataclass→classe su TUTTI i pattern consumer rischiosi (spec-mock, getattr-guard, nessun asdict/pickle/repr), design dello swap regge (nessun capture long-lived dei campi knowledge). Note per il futuro registrate nel backlog (snapshot di gruppo nel hot-path RAG; fixture spec-mock alla migrazione consumer). Gate: 39 test pass, ruff/mypy 0 sui file nuovi, boot ok, EOL i/lf. Commit `c1ce580` + `c859291`.

**Files:**
- Create: `backend/core/service_groups.py`
- Rewrite: `backend/core/context.py`
- Create: `backend/tests/test_context_groups.py`

- [ ] **Step 1: Scrivi il test (failing)**

Crea `backend/tests/test_context_groups.py`:

```python
"""Tests for backend.core.service_groups + AppContext thin root (Fase 5)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext, create_context
from backend.core.event_bus import EventBus
from backend.core.service_groups import (
    ConversationServices,
    InferenceServices,
    KnowledgeServices,
    PlatformServices,
    WorkspaceServices,
)


@pytest.fixture(scope="module")
def config():
    return load_config()


class TestConstruction:
    def test_create_context_builds_groups(self, config):
        ctx = create_context(config)
        assert isinstance(ctx.inference, InferenceServices)
        assert isinstance(ctx.knowledge, KnowledgeServices)
        assert isinstance(ctx.workspace, WorkspaceServices)
        assert isinstance(ctx.conversation, ConversationServices)
        assert isinstance(ctx.platform, PlatformServices)
        assert isinstance(ctx.event_bus, EventBus)
        assert ctx.config is config

    def test_legacy_kwargs_land_in_groups(self, config):
        lmstudio = MagicMock()
        ctx = AppContext(
            config=config, event_bus=EventBus(), lmstudio_manager=lmstudio,
        )
        assert ctx.inference.lmstudio_manager is lmstudio
        assert ctx.lmstudio_manager is lmstudio

    def test_db_kwarg_accepted(self, config):
        ctx = AppContext(config=config, event_bus=EventBus(), db=None)
        assert ctx.db is None
        assert ctx.conversation.db is None

    def test_unknown_kwarg_raises(self, config):
        with pytest.raises(TypeError):
            AppContext(config=config, event_bus=EventBus(), nonsense=1)


class TestFlatDelegation:
    """Every legacy flat name reads/writes through its group."""

    def test_flat_set_reaches_group(self, config):
        ctx = create_context(config)
        svc = MagicMock()
        ctx.llm_service = svc
        assert ctx.inference.llm_service is svc

    def test_group_set_reaches_flat(self, config):
        ctx = create_context(config)
        svc = MagicMock()
        ctx.knowledge.knowledge_service = svc
        assert ctx.knowledge_service is svc

    def test_event_bus_delegates_to_platform(self, config):
        ctx = create_context(config)
        assert ctx.event_bus is ctx.platform.event_bus

    def test_every_flat_field_roundtrips(self, config):
        ctx = create_context(config)
        for name in AppContext.FLAT_FIELDS:
            if name in ("event_bus", "plugin_local_state"):
                continue
            sentinel = object()
            setattr(ctx, name, sentinel)
            assert getattr(ctx, name) is sentinel, name


class TestGroupSwap:
    def test_knowledge_group_atomic_swap(self, config):
        ctx = create_context(config)
        ctx.qdrant_service = MagicMock()
        new_group = KnowledgeServices(qdrant_service=MagicMock())
        old_group = ctx.knowledge
        ctx.knowledge = new_group
        assert ctx.knowledge is new_group
        assert ctx.qdrant_service is new_group.qdrant_service
        assert old_group is not new_group


class TestPluginState:
    def test_get_set_plugin_state_still_work(self, config):
        import asyncio

        ctx = create_context(config)
        asyncio.get_event_loop().run_until_complete(
            ctx.set_plugin_state("demo", "k", 1),
        )
        assert dict(ctx.get_plugin_state("demo")) == {"k": 1}
        assert ctx.platform.plugin_local_state["demo"]["k"] == 1
```

Nota: se `asyncio.get_event_loop()` è deprecato nella versione in uso, rendi il test `async def` (asyncio_mode è `auto`).

- [ ] **Step 2: Esegui il test per vederlo fallire**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_context_groups.py -v
```

Atteso: errore di import (`backend.core.service_groups` non esiste).

- [ ] **Step 3: Crea `backend/core/service_groups.py`**

```python
"""AL\\CE — Cohesive service groups of the application context (Fase 5).

Spec §5.1: the flat 35-field ``AppContext`` is decomposed into five
cohesive, protocol-typed groups.  The groups are the CANONICAL storage;
:class:`backend.core.context.AppContext` stays as a thin root that
aggregates them and exposes flat delegating properties for
not-yet-migrated consumers.

Group membership models OWNERSHIP; the bootstrap stage a field is
created in models INIT ORDER — the two intentionally differ for a few
fields (e.g. ``context_manager`` is conversation-owned but built in the
inference stage).

Fields typed ``Any`` mirror the pre-existing flat fields: the concrete
class lives in ``backend.services`` and typing it here would create a
``core`` → ``services`` import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.core.event_bus import EventBus
from backend.core.protocols import (
    ContextManagerProtocol,
    EmbeddingClientProtocol,
    EmailServiceProtocol,
    KnowledgeServiceProtocol,
    LLMServiceProtocol,
    LMStudioManagerProtocol,
    MemoryServiceProtocol,
    PlanDocumentServiceProtocol,
    PluginManagerProtocol,
    PreferencesServiceProtocol,
    QdrantServiceProtocol,
    STTServiceProtocol,
    TTSServiceProtocol,
    ToolRegistryProtocol,
    VRAMMonitorProtocol,
    WSConnectionManagerProtocol,
)

if TYPE_CHECKING:
    from backend.services.rag_readiness import RagReadiness


@dataclass
class InferenceServices:
    """Model inference: LLM, voice models, embeddings, model management."""

    llm_service: LLMServiceProtocol | None = None
    stt_service: STTServiceProtocol | None = None
    tts_service: TTSServiceProtocol | None = None
    lmstudio_manager: LMStudioManagerProtocol | None = None
    vram_monitor: VRAMMonitorProtocol | None = None
    model_registry: Any = None
    """Dynamic per-model capability registry."""
    model_downloader: Any = None
    """STT/TTS model downloader with progress events."""
    embedding_client: EmbeddingClientProtocol | None = None
    """Shared embedding client for all vector operations."""


@dataclass
class KnowledgeServices:
    """Knowledge domain: single-entry service + its wiring internals.

    ``knowledge_service`` is the ONLY consumer-facing entry point (Fase 4);
    the other fields are wiring/readiness/shutdown internals.  The runtime
    repair path (:func:`backend.services.knowledge_init.repair_vector_store`)
    replaces this WHOLE group atomically (Fase 5)."""

    knowledge_service: KnowledgeServiceProtocol | None = None
    memory_service: MemoryServiceProtocol | None = None
    qdrant_service: QdrantServiceProtocol | None = None
    continuum_client: Any = None
    """The ONE shared Continuum REST client (``None`` when disabled)."""
    rag_readiness: RagReadiness | None = None
    """All-or-nothing RAG readiness verdict (``None`` until computed)."""


@dataclass
class WorkspaceServices:
    """Workspace confinement: scope, permission tiers/rules, terminal."""

    scope_service: Any = None
    permission_service: Any = None
    """Central tool-permission authority consulted by the turn engine."""
    permission_mode_service: Any = None
    permission_rule_service: Any = None
    terminal_session_manager: Any = None


@dataclass
class ConversationServices:
    """Conversation persistence and per-conversation artefacts."""

    db: async_sessionmaker | None = None
    engine: AsyncEngine | None = None
    context_manager: ContextManagerProtocol | None = None
    plan_service: Any = None
    plan_document_service: PlanDocumentServiceProtocol | None = None
    artifact_registry: Any = None


@dataclass
class PlatformServices:
    """Cross-cutting platform machinery: events, config, plugins, WS."""

    event_bus: EventBus = field(default_factory=EventBus)
    config_service: Any = None
    """Layered configuration service — canonical owner of the resolved
    ``AliceConfig`` (``ctx.config`` is updated after every mutation)."""
    ws_connection_manager: WSConnectionManagerProtocol | None = None
    plugin_manager: PluginManagerProtocol | None = None
    tool_registry: ToolRegistryProtocol | None = None
    orchestrator: Any = None
    plugin_state_repo: Any = None
    preferences_service: PreferencesServiceProtocol | None = None
    email_service: EmailServiceProtocol | None = None
    plugin_local_state: dict[str, dict] = field(default_factory=dict)
    """Per-plugin local state, keyed by plugin name."""
```

- [ ] **Step 4: Riscrivi `backend/core/context.py`**

Sostituisci l'INTERO file con:

```python
"""AL\\CE — Application context (thin root over cohesive service groups).

Fase 5 (spec §5.1): the canonical storage is the five service groups in
:mod:`backend.core.service_groups`; ``AppContext`` aggregates them and
keeps every legacy flat field name alive as a typed delegating property
(read AND write), so not-yet-migrated consumers — and the ~20 test
fixtures that construct ``AppContext(...)`` with flat kwargs — keep
working unchanged.  New code should prefer the group access
(``ctx.inference.llm_service``); the flat names are the transition API.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.core.config import AliceConfig
from backend.core.event_bus import EventBus
from backend.core.protocols import (
    ContextManagerProtocol,
    EmbeddingClientProtocol,
    EmailServiceProtocol,
    KnowledgeServiceProtocol,
    LLMServiceProtocol,
    LMStudioManagerProtocol,
    MemoryServiceProtocol,
    PlanDocumentServiceProtocol,
    PluginManagerProtocol,
    PreferencesServiceProtocol,
    QdrantServiceProtocol,
    STTServiceProtocol,
    TTSServiceProtocol,
    ToolRegistryProtocol,
    VRAMMonitorProtocol,
    WSConnectionManagerProtocol,
)
from backend.core.service_groups import (
    ConversationServices,
    InferenceServices,
    KnowledgeServices,
    PlatformServices,
    WorkspaceServices,
)

if TYPE_CHECKING:
    from backend.services.rag_readiness import RagReadiness


class AppContext:
    """Thin root aggregating the five cohesive service groups.

    Created once during application startup via :func:`create_context`
    and stored on ``app.state.context``.  Legacy flat field names are
    delegating properties over the groups (see module docstring).
    """

    #: Every legacy flat field name (delegating property) — used by the
    #: constructor kwargs guard and by tests.
    FLAT_FIELDS: tuple[str, ...] = (
        "db", "engine",
        "plugin_manager", "tool_registry", "llm_service", "stt_service",
        "tts_service", "lmstudio_manager", "vram_monitor", "model_registry",
        "preferences_service", "memory_service", "knowledge_service",
        "continuum_client", "email_service", "qdrant_service",
        "embedding_client", "rag_readiness", "ws_connection_manager",
        "context_manager", "plugin_state_repo", "config_service",
        "artifact_registry", "permission_service", "plan_service",
        "plan_document_service", "scope_service", "permission_mode_service",
        "permission_rule_service", "terminal_session_manager",
        "plugin_local_state", "orchestrator", "model_downloader",
        "event_bus",
    )

    def __init__(
        self,
        config: AliceConfig,
        event_bus: EventBus | None = None,
        **services: Any,
    ) -> None:
        self.config = config
        self.inference = InferenceServices()
        self.knowledge = KnowledgeServices()
        self.workspace = WorkspaceServices()
        self.conversation = ConversationServices()
        self.platform = PlatformServices(event_bus=event_bus or EventBus())
        for name, value in services.items():
            if name not in self.FLAT_FIELDS:
                raise TypeError(
                    f"AppContext got an unexpected field {name!r}"
                )
            setattr(self, name, value)

    # ------------------------------------------------------------------
    # Inference group
    # ------------------------------------------------------------------

    @property
    def llm_service(self) -> LLMServiceProtocol | None:
        return self.inference.llm_service

    @llm_service.setter
    def llm_service(self, value: LLMServiceProtocol | None) -> None:
        self.inference.llm_service = value

    @property
    def stt_service(self) -> STTServiceProtocol | None:
        return self.inference.stt_service

    @stt_service.setter
    def stt_service(self, value: STTServiceProtocol | None) -> None:
        self.inference.stt_service = value

    @property
    def tts_service(self) -> TTSServiceProtocol | None:
        return self.inference.tts_service

    @tts_service.setter
    def tts_service(self, value: TTSServiceProtocol | None) -> None:
        self.inference.tts_service = value

    @property
    def lmstudio_manager(self) -> LMStudioManagerProtocol | None:
        return self.inference.lmstudio_manager

    @lmstudio_manager.setter
    def lmstudio_manager(self, value: LMStudioManagerProtocol | None) -> None:
        self.inference.lmstudio_manager = value

    @property
    def vram_monitor(self) -> VRAMMonitorProtocol | None:
        return self.inference.vram_monitor

    @vram_monitor.setter
    def vram_monitor(self, value: VRAMMonitorProtocol | None) -> None:
        self.inference.vram_monitor = value

    @property
    def model_registry(self) -> Any:
        return self.inference.model_registry

    @model_registry.setter
    def model_registry(self, value: Any) -> None:
        self.inference.model_registry = value

    @property
    def model_downloader(self) -> Any:
        return self.inference.model_downloader

    @model_downloader.setter
    def model_downloader(self, value: Any) -> None:
        self.inference.model_downloader = value

    @property
    def embedding_client(self) -> EmbeddingClientProtocol | None:
        return self.inference.embedding_client

    @embedding_client.setter
    def embedding_client(self, value: EmbeddingClientProtocol | None) -> None:
        self.inference.embedding_client = value

    # ------------------------------------------------------------------
    # Knowledge group
    # ------------------------------------------------------------------

    @property
    def knowledge_service(self) -> KnowledgeServiceProtocol | None:
        return self.knowledge.knowledge_service

    @knowledge_service.setter
    def knowledge_service(self, value: KnowledgeServiceProtocol | None) -> None:
        self.knowledge.knowledge_service = value

    @property
    def memory_service(self) -> MemoryServiceProtocol | None:
        return self.knowledge.memory_service

    @memory_service.setter
    def memory_service(self, value: MemoryServiceProtocol | None) -> None:
        self.knowledge.memory_service = value

    @property
    def qdrant_service(self) -> QdrantServiceProtocol | None:
        return self.knowledge.qdrant_service

    @qdrant_service.setter
    def qdrant_service(self, value: QdrantServiceProtocol | None) -> None:
        self.knowledge.qdrant_service = value

    @property
    def continuum_client(self) -> Any:
        return self.knowledge.continuum_client

    @continuum_client.setter
    def continuum_client(self, value: Any) -> None:
        self.knowledge.continuum_client = value

    @property
    def rag_readiness(self) -> RagReadiness | None:
        return self.knowledge.rag_readiness

    @rag_readiness.setter
    def rag_readiness(self, value: RagReadiness | None) -> None:
        self.knowledge.rag_readiness = value

    # ------------------------------------------------------------------
    # Workspace group
    # ------------------------------------------------------------------

    @property
    def scope_service(self) -> Any:
        return self.workspace.scope_service

    @scope_service.setter
    def scope_service(self, value: Any) -> None:
        self.workspace.scope_service = value

    @property
    def permission_service(self) -> Any:
        return self.workspace.permission_service

    @permission_service.setter
    def permission_service(self, value: Any) -> None:
        self.workspace.permission_service = value

    @property
    def permission_mode_service(self) -> Any:
        return self.workspace.permission_mode_service

    @permission_mode_service.setter
    def permission_mode_service(self, value: Any) -> None:
        self.workspace.permission_mode_service = value

    @property
    def permission_rule_service(self) -> Any:
        return self.workspace.permission_rule_service

    @permission_rule_service.setter
    def permission_rule_service(self, value: Any) -> None:
        self.workspace.permission_rule_service = value

    @property
    def terminal_session_manager(self) -> Any:
        return self.workspace.terminal_session_manager

    @terminal_session_manager.setter
    def terminal_session_manager(self, value: Any) -> None:
        self.workspace.terminal_session_manager = value

    # ------------------------------------------------------------------
    # Conversation group
    # ------------------------------------------------------------------

    @property
    def db(self) -> async_sessionmaker | None:
        return self.conversation.db

    @db.setter
    def db(self, value: async_sessionmaker | None) -> None:
        self.conversation.db = value

    @property
    def engine(self) -> AsyncEngine | None:
        return self.conversation.engine

    @engine.setter
    def engine(self, value: AsyncEngine | None) -> None:
        self.conversation.engine = value

    @property
    def context_manager(self) -> ContextManagerProtocol | None:
        return self.conversation.context_manager

    @context_manager.setter
    def context_manager(self, value: ContextManagerProtocol | None) -> None:
        self.conversation.context_manager = value

    @property
    def plan_service(self) -> Any:
        return self.conversation.plan_service

    @plan_service.setter
    def plan_service(self, value: Any) -> None:
        self.conversation.plan_service = value

    @property
    def plan_document_service(self) -> PlanDocumentServiceProtocol | None:
        return self.conversation.plan_document_service

    @plan_document_service.setter
    def plan_document_service(
        self, value: PlanDocumentServiceProtocol | None,
    ) -> None:
        self.conversation.plan_document_service = value

    @property
    def artifact_registry(self) -> Any:
        return self.conversation.artifact_registry

    @artifact_registry.setter
    def artifact_registry(self, value: Any) -> None:
        self.conversation.artifact_registry = value

    # ------------------------------------------------------------------
    # Platform group
    # ------------------------------------------------------------------

    @property
    def event_bus(self) -> EventBus:
        return self.platform.event_bus

    @event_bus.setter
    def event_bus(self, value: EventBus) -> None:
        self.platform.event_bus = value

    @property
    def config_service(self) -> Any:
        return self.platform.config_service

    @config_service.setter
    def config_service(self, value: Any) -> None:
        self.platform.config_service = value

    @property
    def ws_connection_manager(self) -> WSConnectionManagerProtocol | None:
        return self.platform.ws_connection_manager

    @ws_connection_manager.setter
    def ws_connection_manager(
        self, value: WSConnectionManagerProtocol | None,
    ) -> None:
        self.platform.ws_connection_manager = value

    @property
    def plugin_manager(self) -> PluginManagerProtocol | None:
        return self.platform.plugin_manager

    @plugin_manager.setter
    def plugin_manager(self, value: PluginManagerProtocol | None) -> None:
        self.platform.plugin_manager = value

    @property
    def tool_registry(self) -> ToolRegistryProtocol | None:
        return self.platform.tool_registry

    @tool_registry.setter
    def tool_registry(self, value: ToolRegistryProtocol | None) -> None:
        self.platform.tool_registry = value

    @property
    def orchestrator(self) -> Any:
        return self.platform.orchestrator

    @orchestrator.setter
    def orchestrator(self, value: Any) -> None:
        self.platform.orchestrator = value

    @property
    def plugin_state_repo(self) -> Any:
        return self.platform.plugin_state_repo

    @plugin_state_repo.setter
    def plugin_state_repo(self, value: Any) -> None:
        self.platform.plugin_state_repo = value

    @property
    def preferences_service(self) -> PreferencesServiceProtocol | None:
        return self.platform.preferences_service

    @preferences_service.setter
    def preferences_service(
        self, value: PreferencesServiceProtocol | None,
    ) -> None:
        self.platform.preferences_service = value

    @property
    def email_service(self) -> EmailServiceProtocol | None:
        return self.platform.email_service

    @email_service.setter
    def email_service(self, value: EmailServiceProtocol | None) -> None:
        self.platform.email_service = value

    @property
    def plugin_local_state(self) -> dict[str, dict]:
        return self.platform.plugin_local_state

    @plugin_local_state.setter
    def plugin_local_state(self, value: dict[str, dict]) -> None:
        self.platform.plugin_local_state = value

    # ------------------------------------------------------------------
    # Plugin state helpers
    # ------------------------------------------------------------------

    def get_plugin_state(self, name: str) -> MappingProxyType:
        """Return a read-only view of a plugin's local state.

        Args:
            name: The plugin name.

        Returns:
            A ``MappingProxyType`` wrapping the plugin's state dict.
            Returns an empty read-only mapping if no state exists.
        """
        return MappingProxyType(self.platform.plugin_local_state.get(name, {}))

    async def set_plugin_state(
        self, plugin_name: str, key: str, value: Any,
    ) -> None:
        """Update a single key in a plugin's local state.

        Creates the plugin's state dict if it doesn't exist yet.

        Args:
            plugin_name: The plugin whose state to update.
            key: The state key to set.
            value: The new value.
        """
        state = self.platform.plugin_local_state
        if plugin_name not in state:
            state[plugin_name] = {}
        state[plugin_name][key] = value


def create_context(config: AliceConfig) -> AppContext:
    """Create a fresh application context.

    Args:
        config: The validated AL\\CE configuration.

    Returns:
        An ``AppContext`` wired with the config and a new ``EventBus``.
    """
    return AppContext(
        config=config,
        event_bus=EventBus(),
    )
```

- [ ] **Step 5: Verifica che nessuno tratti AppContext come dataclass**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "asdict\|astuple\|fields(AppContext)\|is_dataclass" -- backend
```

Atteso: nessun match riferito ad `AppContext` (match su altri tipi sono ok). Se `tests/test_context.py` asserisce che AppContext è una dataclass o itera i suoi field, aggiorna quelle asserzioni mantenendo la semantica (i campi ora sono property; usa `AppContext.FLAT_FIELDS`).

- [ ] **Step 6: Esegui i test**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_context_groups.py tests/test_context.py -v
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
```

Atteso: PASS + `app ok`.

- [ ] **Step 7: Lint/type-check scoped e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check core/service_groups.py core/context.py tests/test_context_groups.py
..\.venv\Scripts\python.exe -m mypy core/service_groups.py core/context.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git ls-files --eol backend/core/service_groups.py backend/core/context.py backend/tests/test_context_groups.py
git add backend/core/service_groups.py backend/core/context.py backend/tests/test_context_groups.py
git commit -m "feat(kernel): AppContext decomposto in 5 gruppi coesi con radice sottile compatibile" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

`git ls-files --eol`: atteso `i/lf` su tutti e tre.

---

### Task 2: Bootstrap dichiarativo a stage (`backend/core/bootstrap/`)

> **Esito (2026-07-09):** DONE. Spec review: fedeltà statement-level verificata (ordine, log, eventi, guardie byte-identici; 6 deviazioni dichiarate tutte neutrali; mypy/ruff a debito zero vs base) + UN finding vero NON dichiarato: il try/finally ora avvolge l'intera sequenza di stage → lo shutdown gira anche su failure a metà startup con ctx parziale (il vecchio codice non puliva NULLA in quel caso — repro empirico del reviewer). **Deviazione ACCETTATA dal controller come 7ª intenzionale** (origine: codice target del piano; miglioramento reale — engine/httpx non più leakati): `shutdown_services` verificato difensivo su ogni step + test di regressione `tests/test_bootstrap.py` (3 test: failure a metà startup invoca shutdown col ctx parziale; ctx parziale è no-op; None è no-op) in `366698e`. Quality review (top): "Ready: Yes" — audit di asimmetria shutdown PULITO (nessuna risorsa avviabile da uno stage che shutdown non copra); fix applicati dal controller in `3cce19e`: tipo `db` reso veritiero ALLA FONTE (`async_sessionmaker[SQLModelAsyncSession]` su create_engine_and_session/gruppo/property/plan_service → entrambi i cast e l'ignore morto ELIMINATI; mypy −2, zero nuovi), commento stantio platform.py. Minor non applicati (registrati): log "backend stopped" anche su startup abortito (fedeltà log preservata, cosmetico); variante test con engine reale disposato → backlog. Note per Task 3 registrate: tool_registry cattura qdrant/embedding alla COSTRUZIONE (il repair già re-punta via set_vector_backends ✓). Backlog: dedup closure broadcaster (`make_ws_broadcaster`). Gate: 47 test pass (test_app 2:07 min), boot ok, EOL i/lf su tutti. Commit `4c4e96a` + `366698e` + `3cce19e`. app.py: 883 → 152 righe.

**Files:**
- Create: `backend/core/bootstrap/__init__.py`
- Create: `backend/core/bootstrap/database.py`, `platform.py`, `inference.py`, `knowledge.py`, `senses.py`, `plugins.py`, `surfaces.py`, `conversation.py`, `workspace.py`, `shutdown.py`
- Modify: `backend/core/app.py` (lifespan → sequenza di stage; gli import dei services al top del file MIGRANO nei moduli stage)

**Mappa sezioni → stage** (righe di `core/app.py` PRIMA di questo task; è l'ordine ATTUALE, che gli stage replicano 1:1):

| Stage | Sezioni (righe app.py) | Cosa crea |
|---|---|---|
| `stage_database` | 66-81 (db url, engine, init_db; le assegnazioni ctx.db/engine) | `ctx.db`, `ctx.engine` |
| `stage_platform` | 83-172 (orchestrator; layered config + `_refresh_ctx_config`; model downloader + `_forward_download_progress`; preferences; plugin toggle states) | `orchestrator`, `config_service` (+ riassegna `ctx.config`), `model_downloader`, `preferences_service`, `plugin_state_repo` |
| `stage_inference` | 174-211 (model registry, LLM, context manager, LM Studio + listener) | `model_registry`, `llm_service`, `context_manager`, `lmstudio_manager` |
| `stage_knowledge` | 213-296 (embedding, qdrant, memory, ContinuumClient, knowledge service) | `embedding_client`, `qdrant_service`, `memory_service`, `continuum_client`, `knowledge_service` |
| `stage_senses` | 297-450 (email, STT, TTS, VRAM monitor, TRELLIS ×3, VRAM handlers) | `email_service`, `stt_service`, `tts_service`, `vram_monitor` |
| `stage_plugins` | 452-492 (plugin manager + `app.state.healthy`, tool registry, RAG readiness) | `plugin_manager`, `tool_registry`, `rag_readiness` |
| `stage_surfaces` | 494-609 (WS connection manager + validator, TUTTI i bridge eventi→WS) | `ws_connection_manager` |
| `stage_conversation` | 611-646 (artifact registry, plan service, plan document service) | `artifact_registry`, `plan_service`, `plan_document_service` |
| `stage_workspace` | 648-723 (scope, permission mode, permission rules, permission service, terminal) | `scope_service`, `permission_mode_service`, `permission_rule_service`, `permission_service`, `terminal_session_manager` |
| `shutdown_services` | 732-801 (i 13 step del finally) | — |

- [ ] **Step 1: Crea lo scheletro del package**

Crea `backend/core/bootstrap/__init__.py`:

```python
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
    "stage_knowledge",
    "stage_platform",
    "stage_plugins",
    "stage_senses",
    "stage_surfaces",
    "stage_workspace",
]
```

- [ ] **Step 2: Estrai gli stage UNO ALLA VOLTA (boot check dopo ognuno)**

Regole di estrazione (identiche per ogni stage; il corpo è la sezione ATTUALE spostata VERBATIM):

1. Firma: `async def stage_<nome>(ctx: AppContext) -> None`, con queste eccezioni: `stage_database(ctx: AppContext, *, testing: bool) -> None`, `stage_platform(ctx: AppContext, *, testing: bool) -> None` (prefs/plugin-seed hanno guardie `if not testing`), `stage_plugins(ctx: AppContext, app: FastAPI) -> None` (setta `app.state.healthy`). Se durante l'estrazione una sezione usa `testing` o `app` non previsti qui, AGGIUNGI il parametro allo stage invece di cambiarne la semantica.
2. Ogni stage apre con `config = ctx.config` (dopo `stage_platform` il locale è il config risolto — semantica identica all'alias di `app.py:100`, che muore).
3. `session_factory` → `ctx.db` (in `stage_database` assegna `ctx.db = session_factory` come oggi con lo stesso `# type: ignore[assignment]`; gli stage successivi leggono `ctx.db`).
4. Gli import deferred dentro le sezioni (`from backend.services...`) restano DENTRO la funzione stage, invariati. Gli import top-level di `app.py` che servivano solo al lifespan (`LLMService`, `LMStudioManager`, `ModelCapabilityRegistry`, `STTService`, `TTSService`, `VRAMMonitor`, `ServiceOrchestrator`, `PluginManager`, `ToolRegistry`, managed services, `create_engine_and_session`/`init_db`) MIGRANO nel modulo stage corrispondente (top-level del modulo stage va bene).
5. Le closure handler (`_refresh_ctx_config`, `_forward_download_progress`, i bridge di `stage_surfaces`, gli handler VRAM) si spostano dentro lo stage: catturano `ctx` — comportamento identico.
6. In `core/app.py` la sezione estratta è sostituita da `await stage_<nome>(ctx)` (o con i kwargs). NON riordinare: la sequenza di chiamate replica l'ordine delle sezioni.
7. Dopo OGNI stage estratto esegui il boot check (sotto). Se rosso, ripara PRIMA di estrarre il successivo.

Il lifespan finale (dopo l'ultimo stage) deve essere:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup / shutdown of the AL\\CE backend."""
    config: AliceConfig = app.state._config  # set by create_app
    testing: bool = app.state._testing

    ctx: AppContext | None = None
    try:
        ctx = create_context(config)

        # Declarative bootstrap (Fase 5, spec §5.1): explicit stage order.
        await stage_database(ctx, testing=testing)
        await stage_platform(ctx, testing=testing)
        await stage_inference(ctx)
        await stage_knowledge(ctx)
        await stage_senses(ctx)
        await stage_plugins(ctx, app)
        await stage_surfaces(ctx)
        await stage_conversation(ctx)
        await stage_workspace(ctx)

        app.state.context = ctx
        app.state.engine = ctx.engine

        logger.info("AL\\CE backend started")
        yield
    finally:
        # -- Shutdown -------------------------------------------------------
        await shutdown_services(ctx)
        logger.info("AL\\CE backend stopped")
```

(Conserva eventuali righe di log/setup del lifespan attuale non appartenenti a nessuna sezione — confronta con `git show arch/fase4-conoscenza:backend/core/app.py` per non perdere nulla; il pre-bind dei locali per il finally, righe 57-64, MUORE: lo shutdown legge da ctx.)

- [ ] **Step 3: Crea `backend/core/bootstrap/shutdown.py`**

```python
"""AL\\CE — Ordered service shutdown (Fase 5).

Mirrors the historical ``finally`` block of the lifespan: same order,
one isolated try/except per step, reading every service from the
context (with guards) instead of pre-bound locals.
"""

from __future__ import annotations

from loguru import logger

from backend.core.context import AppContext


async def shutdown_services(ctx: AppContext | None) -> None:
    """Close every started service in the historical order.

    Args:
        ctx: The application context, or ``None`` when startup failed
            before it was constructed (nothing to close).
    """
    if ctx is None:
        return
    ...
```

Il corpo dopo il guard è il blocco `finally` attuale (righe 732-801) spostato verbatim, con i locali sostituiti dai campi ctx (`plugin_manager` → `ctx.plugin_manager`, `lmstudio_manager` → `ctx.lmstudio_manager`, `llm_service` → `ctx.llm_service`, `engine` → `ctx.engine`; gli altri step usano già `ctx.<campo>`). Stesso ORDINE: orchestrator polling → terminal → plugin_manager → lmstudio → llm → stt → tts → vram → memory → email → qdrant → embedding → engine.dispose. Ogni step conserva il suo try/except + guardia `is not None`.

- [ ] **Step 4: Boot check + regressioni mirate**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_context.py tests/test_context_groups.py -v
```

Atteso: `app ok` + PASS. (Il boot check istanzia l'app; `tests/test_app.py` esercita il lifespan testing end-to-end.)

- [ ] **Step 5: Verifica residui e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "from backend.services" -- backend/core/app.py
```

Atteso: NESSUN match (gli import services vivono solo nei moduli bootstrap). `app.py` conserva gli import `backend.api.middleware.*` e l'import del router in `create_app` (composition root, in ignore-list del linter al Task 8).

```powershell
git ls-files --eol backend/core/bootstrap/ backend/core/app.py
git add backend/core/bootstrap backend/core/app.py
git commit -m "refactor(kernel): bootstrap dichiarativo a stage, lifespan sottile" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Repair a swap atomico del gruppo Knowledge + protocol gap `in_memory`

> **Esito (2026-07-09):** DONE. Spec review: conforme (parità semantica branch-by-branch verificata; UNA sola assegnazione `ctx.knowledge` + sola scrittura additiva `rag_readiness`; tear-down pre-swap; mai un secondo ContinuumClient; monkeypatch MemoryService correttamente sul modulo sorgente per l'import deferred). Quality review (top): "With fixes" — verdetto chiave del reviewer: NESSUN interleaving costruibile in cui un reader osserva uno stato peggiore del pre-Task-3; la finestra post-swap con `rag_readiness=None` è un MIGLIORAMENTO stretto (prima: verdetto stantio su servizi semi-ricablati). Fix applicati dal controller in `95c2b2c`: invariante del test esteso a TUTTI e 5 i campi del vecchio gruppo (una regressione a UNA sola scrittura in-place ora fallisce il test), 2 test nuovi (memoria fallita con qdrant sano + re-point tool-RAG sui backend NUOVI — la riga load-bearing dello step 4), locali tipizzati (`QdrantService | None` via widening esplicito, `MemoryService | None` con TYPE_CHECKING; mypy 0 reale sul file), clausola onesta nel commento 3b (il client qdrant del vecchio gruppo è già chiuso). Backlog: repair concorrente non serializzato (lock a livello route, pre-esistente) + `memory_service` vecchio non chiuso (parità pre-fase). Gate: 27 test pass, boot ok, EOL i/lf. Commit `0b17d59` + `95c2b2c`.

**Files:**
- Modify: `backend/services/knowledge_init.py` (repair su gruppo)
- Modify: `backend/core/protocols.py` (`QdrantServiceProtocol.in_memory`)
- Create: `backend/tests/test_knowledge_repair.py`

- [ ] **Step 1: Scrivi il test (failing)**

Crea `backend/tests/test_knowledge_repair.py`:

```python
"""Tests for repair_vector_store — atomic Knowledge group swap (Fase 5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.config import load_config
from backend.core.context import create_context
from backend.services import knowledge_init
from backend.services.rag_readiness import RagReadiness


@pytest.fixture
def ctx(monkeypatch):
    ctx = create_context(load_config())
    ctx.embedding_client = MagicMock()
    ctx.tool_registry = None

    qdrant = MagicMock()
    qdrant.initialize = AsyncMock()
    qdrant.close = AsyncMock()
    qdrant.clear_embedded_data = MagicMock()
    monkeypatch.setattr(
        knowledge_init, "QdrantService", MagicMock(return_value=qdrant),
    )

    readiness = RagReadiness(
        ready=False, reason="test", memory_enabled=False,
        tool_rag_enabled=False,
    )
    monkeypatch.setattr(
        knowledge_init, "check_rag_readiness",
        AsyncMock(return_value=readiness),
    )
    return ctx


async def test_repair_swaps_knowledge_group_atomically(ctx):
    old_group = ctx.knowledge
    await knowledge_init.repair_vector_store(ctx)
    assert ctx.knowledge is not old_group
    # The OLD group is left untouched (readers holding it stay coherent).
    assert old_group.qdrant_service is None
    assert old_group.rag_readiness is None
    # The new group is fully wired.
    assert ctx.qdrant_service is not None
    assert ctx.knowledge_service is not None
    assert ctx.rag_readiness is not None


async def test_repair_reuses_shared_continuum_client(ctx):
    sentinel = MagicMock()
    ctx.continuum_client = sentinel
    await knowledge_init.repair_vector_store(ctx)
    assert ctx.continuum_client is sentinel


async def test_repair_qdrant_failure_leaves_memory_disabled(ctx, monkeypatch):
    failing = MagicMock()
    failing.initialize = AsyncMock(side_effect=RuntimeError("boom"))
    failing.close = AsyncMock()
    failing.clear_embedded_data = MagicMock()
    monkeypatch.setattr(
        knowledge_init, "QdrantService", MagicMock(return_value=failing),
    )
    await knowledge_init.repair_vector_store(ctx)
    assert ctx.qdrant_service is None
    assert ctx.memory_service is None
    assert ctx.knowledge_service is not None  # memory-unavailable facade
```

Se il costruttore di `RagReadiness` ha campi diversi, allineali leggendo `backend/services/rag_readiness.py` (il test deve costruire un verdetto qualunque valido). Verifica anche che `config.memory.enabled`/`config.continuum.enabled` nel config di default non facciano imboccare rami che richiedono servizi reali: se `memory.enabled` è true nel YAML, monkeypatcha anche `knowledge_init.MemoryService`... l'import di MemoryService è deferred dentro la funzione: monkeypatcha allora `backend.services.memory_service.MemoryService` con un mock che ha `initialize`/`close` AsyncMock.

Esegui per vederlo fallire:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_knowledge_repair.py -v
```

Atteso: FAIL su `test_repair_swaps_knowledge_group_atomically` (oggi il repair muta i campi in place: `ctx.knowledge is old_group`).

- [ ] **Step 2: Riscrivi i passi 1-3 e 5 di `repair_vector_store`**

In `backend/services/knowledge_init.py`, aggiungi l'import top-level:

```python
from backend.core.service_groups import KnowledgeServices
```

e sostituisci il corpo di `repair_vector_store` dai passi 1-5 (righe 55-134) con la versione a swap: i passi 1-3 costruiscono in LOCALI (`qdrant_service: QdrantService | None`, `memory_service`, `knowledge_service`) con la stessa identica logica/logging di oggi (tear-down del vecchio client incluso, che legge `ctx.qdrant_service` PRIMA dello swap), poi:

```python
    # 3b. Swap the WHOLE knowledge group atomically: readers holding the
    # old group keep a coherent (stale) view; readers dereferencing ctx
    # see only the fully-wired new group.  This closes the partial-state
    # window the in-place rewiring had (Fase 4 review backlog).
    ctx.knowledge = KnowledgeServices(
        knowledge_service=knowledge_service,
        memory_service=memory_service,
        qdrant_service=qdrant_service,
        continuum_client=client,
        rag_readiness=None,
    )
```

Il passo 4 (tool-RAG re-point + refresh) resta identico (ora legge i campi nuovi via property). Il passo 5 resta identico: `readiness = await check_rag_readiness(ctx)` poi `ctx.rag_readiness = readiness` (scrittura additiva sul gruppo NUOVO — documenta nel commento che readiness richiede il ctx già swappato e il registry refreshato). Aggiorna il docstring del modulo: `re-wires the context in place` → `atomically swaps the knowledge service group`.

- [ ] **Step 3: Aggiungi `in_memory` a `QdrantServiceProtocol`**

In `backend/core/protocols.py`, dentro `QdrantServiceProtocol` (riga ~257, dopo la docstring):

```python
    @property
    def in_memory(self) -> bool:
        """True when the embedded store fell back to in-memory mode."""
        ...
```

Poi in `backend/api/routes/vector_store.py` verifica con mypy che l'attr-defined su `in_memory` (riga 102) sia sparito:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m mypy api/routes/vector_store.py
```

Confronta gli errori residui con `git show arch/fase4-conoscenza:backend/api/routes/vector_store.py` (devono essere ≤ dei pre-esistenti; l'attr-defined su `in_memory` deve essere sparito).

- [ ] **Step 4: Esegui i test e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_knowledge_repair.py tests/test_rag_readiness.py tests/test_knowledge_service.py -v
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
git ls-files --eol backend/services/knowledge_init.py backend/core/protocols.py backend/tests/test_knowledge_repair.py
git add backend/services/knowledge_init.py backend/core/protocols.py backend/tests/test_knowledge_repair.py backend/api/routes/vector_store.py
git commit -m "refactor(knowledge): repair a swap atomico del gruppo + QdrantServiceProtocol.in_memory" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(`vector_store.py` va nel commit solo se è stato toccato per il protocol fix.)

---

### Task 4: Split `tool_registry` — catalogo vs policy (package `core/tools/`)

> **Esito (2026-07-09):** DONE. Split committato in `300495e`; la sessione si è interrotta a metà del fix-loop della prima quality review (report perso) con i fix già applicati nel working tree — committati in `059f0eb` (dedup `_get_available_tools` → `compose_available_tools` condivisa in availability.py, `USABLE_STATUSES` unico, `llm_config` nel costruttore di `ToolRag` invece del poke sul privato `_llm_config`, docstring `refresh` veritiera — lo skip-con-warning dei duplicati era GIÀ il comportamento del monolite, la vecchia docstring "raise ValueError" era falsa: fix solo documentale, verificato byte-per-byte). **Re-review completa (top) a contesto fresco: "Ready: Yes", zero fix** — evidenze: suite di equivalenza 60/60 SENZA modifiche ai file di test (vincolo del piano, `git diff --stat -- backend/tests` vuoto); confini di lock preservati su tutte le sezioni critiche (refresh/get_available_tools/get_tools_for_plugins/execute_tool/embed_tools/get_relevant_tools — le due acquisizioni sequenziali non annidate restano tali, nessun deadlock); i 5 call-site di compose_available_tools avevano già semantica identica nel monolite; alias test-compat ESATTI ai tre usati dai test (`_tools`, `_tool_to_plugin`, `_status_probe_timeout`); repair runtime re-punta correttamente (set_vector_backends → clear_status_cache → refresh); layering pulito (core/tools non importa services); ruff/mypy a debito ZERO vs base (SIM105, B905, N806×2, jsonschema import-untyped+unused-ignore, 4 type-arg — tutti pre-esistenti spostati verbatim; qdrant_service migliora: F401 risolto). Nit registrato non-azionabile: re-export compat `COLLECTION_TOOLS`/`PROJECT_NS` in qdrant_service.py:20 oggi senza consumatori (shim difensivo richiesto dal task, innocuo). Gate: 108 test pass (equivalenza + tool_loop + pipeline), boot ok, EOL i/lf. Commit `300495e` + `059f0eb`.

**Files:**
- Create: `backend/core/vector_collections.py`
- Create: `backend/core/tools/__init__.py`, `catalog.py`, `availability.py`, `policy.py`, `execution.py`, `rag.py`
- Rewrite: `backend/core/tool_registry.py` (facade)
- Modify: `backend/services/qdrant_service.py` (costanti importate da core + re-export)

**Criterio di equivalenza (vincolante):** `tests/test_tool_registry.py`, `tests/test_tool_status_caching.py`, `tests/test_permission_mode_policy.py` devono passare **SENZA alcuna modifica** — l'API pubblica e la semantica del facade sono identiche.

- [ ] **Step 1: Sposta le costanti condivise in core**

Crea `backend/core/vector_collections.py`:

```python
"""AL\\CE — Shared vector-store collection names and namespaces.

Single source for the identifiers that BOTH the qdrant service layer and
the core tool-RAG components need — defined in ``core`` so the tools
package never imports from ``services`` (layering contract §4).
"""

from __future__ import annotations

import uuid

# Tool-RAG collection (semantic tool retrieval).
COLLECTION_TOOLS = "alice_tools"

# Stable namespace for deterministic tool-embedding point ids.
PROJECT_NS = uuid.UUID("a1c3e5f7-0000-4000-8000-000000000000")
```

(Copia i VALORI esatti da `services/qdrant_service.py:28-31` — quelli sopra sono i valori verificati in recon; se differiscono, vincono quelli del file.) In `backend/services/qdrant_service.py` sostituisci le due definizioni con:

```python
from backend.core.vector_collections import COLLECTION_TOOLS, PROJECT_NS  # noqa: F401  (re-export: pre-Fase 5 import site kept working)
```

lasciando `COLLECTION_MEMORY` dov'è. Verifica che ogni import esistente resti verde:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "COLLECTION_TOOLS\|PROJECT_NS" -- backend
```

- [ ] **Step 2: Crea i componenti del package `core/tools/`**

Regole: i CORPI dei metodi si spostano VERBATIM da `tool_registry.py` (righe in recon/tabella §Contesto); cambiano solo i riferimenti allo stato (`self._tools` → componente proprietario). Struttura:

`backend/core/tools/__init__.py`:

```python
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
```

`catalog.py` — `class ToolCatalog`: stato `self._tools: dict[str, ToolDefinition]`, `self._tool_to_plugin: dict[str, str]`, `self._openai_cache: list[dict]`, `self._lock = asyncio.Lock()`. Metodi (corpi da tool_registry.py): `refresh(plugin_manager)` (da righe 211-311: validazione nome/descrizione/schema, namespacing, dedup, build cache OpenAI — SENZA la coda `embed_tools`, che orchestrerà il facade), `get_all_tools` (346-354), `get_tool_plugin` (537-546), `get_tool_definition` (548-557), `get_tool_catalog` (559-589), più gli accessor che gli altri componenti usano: `definition(ns_name)`, `plugin_of(ns_name)`, property `tools` (view read-only del dict). Helper modulo `_validate_json_schema` (144-158) si sposta qui.

`availability.py` — `class AvailabilityProbe`: `__init__(plugin_manager)`; stato `_status_cache`, `_status_cache_ttl = 30.0`, `_status_probe_timeout = 3.0`; metodi `clear_status_cache` (333-340), `resolve_plugin_statuses` (356-393, era `_resolve_plugin_statuses`), `_probe_plugin_status` (395-421).

`policy.py` — funzioni modulo PURE (nessuno stato): `limit_tools(tools, max_tools, *, catalog: ToolCatalog, priority_plugins=None)` (corpo da 485-535), `exclude_disabled(tools, disabled_names)` (591-616), `apply_mode_policy(tools, *, catalog: ToolCatalog, drop_capabilities=frozenset(), priority_plugins=())` (648-713). Dove il corpo leggeva `self._tools[...]`/`self._tool_to_plugin` usa `catalog.definition(...)`/`catalog.plugin_of(...)`. Docstring di modulo: chiarire che questa è la policy di OFFERTA (select-time) e che il gate run-time è `PermissionService.decide`.

`execution.py` — `class ToolExecutor`: `__init__(catalog, plugin_manager, event_bus)`; metodi `execute_tool` (975-1182), `_coerce_args` (static, 918-973); helper modulo `_format_schema_error`, `_sanitise_dict`, `_deep_copy_content`, `_sanitise_content` + le tre regex (43-141) si spostano qui.

`rag.py` — `class ToolRag`: `__init__(catalog, availability)`; stato `_qdrant`, `_embedder`, `_llm_config`; metodi `set_vector_backends` (320-331), `embed_tools` (719-802), `get_relevant_tools` (804-912). Import costanti: `from backend.core.vector_collections import COLLECTION_TOOLS, PROJECT_NS`.

- [ ] **Step 3: Riscrivi `core/tool_registry.py` come facade**

`ToolRegistry` conserva ESATTAMENTE la firma `__init__` attuale (righe 177-205: stessi parametri, stessi default) e costruisce i componenti: `self._catalog = ToolCatalog()`, `self._availability = AvailabilityProbe(plugin_manager)`, `self._executor = ToolExecutor(self._catalog, plugin_manager, event_bus)`, `self._rag = ToolRag(self._catalog, self._availability)` (+ `set_vector_backends` iniziale se il costruttore attuale riceve i backend). Ogni metodo pubblico delega:

- `refresh` → `await self._catalog.refresh(self._plugin_manager)` seguito dalla coda embed ATTUALE (righe 313-318 verbatim, su `self._rag.embed_tools()`);
- `get_all_tools`/`get_tool_plugin`/`get_tool_definition`/`get_tool_catalog` → catalogo;
- `clear_status_cache` → availability;
- `limit_tools`/`exclude_disabled`/`apply_mode_policy` → `policy.<fn>(..., catalog=self._catalog, ...)`;
- `set_vector_backends`/`embed_tools`/`get_relevant_tools` → rag;
- `execute_tool` → executor;
- `get_available_tools` (423-454), `get_tools_for_plugins` (456-483), `usage_guidance_for` (618-646): i corpi restano nel facade (compongono catalogo+availability), con gli accessi allo stato rimappati sugli accessor dei componenti.

Se un test accede a stato privato del registry (es. `registry._tools`), NON aggiungere shim: verifica prima con `git grep -n "_tools\b\|_status_cache\|_openai_cache" -- backend/tests/test_tool_registry.py backend/tests/test_tool_status_caching.py`; se ci sono accessi privati, il facade espone alias di compat SOLO per quelli effettivamente usati dai test (documentati "test-compat, backlog: migrare").

- [ ] **Step 4: Esegui la suite di equivalenza**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_tool_registry.py tests/test_tool_status_caching.py tests/test_permission_mode_policy.py tests/test_tool_loop.py tests/test_pipeline.py -v
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
```

Atteso: PASS integrale senza modifiche ai file di test (salvo il caso accessi-privati documentato) + `app ok`.

- [ ] **Step 5: Lint scoped e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check core/tools core/tool_registry.py core/vector_collections.py services/qdrant_service.py
..\.venv\Scripts\python.exe -m mypy core/tools core/vector_collections.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git ls-files --eol backend/core/tools/ backend/core/tool_registry.py backend/core/vector_collections.py
git add backend/core/tools backend/core/tool_registry.py backend/core/vector_collections.py backend/services/qdrant_service.py
git commit -m "refactor(kernel): split tool_registry in catalogo/availability/policy/execution/rag, facade invariata" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Split `llm_service` — client / prompt / capability (package `services/llm/`)

> **Esito (2026-07-09):** DONE. Split in `399714d`: facade 1694 → ~310 righe; `client.py` (853), `prompting.py` (527), `model_resolution.py` (311). **5 deviazioni dichiarate, tutte verificate legittime dalla spec review**: (1) `self._client` resta l'httpx grezzo sul facade (i test patchano `svc._client.get`/`.stream` — vincolo del piano stesso), LLMClient in `self._llm_client`; (2) famiglia context-window RIMASTA sul facade (test_context_window_cache usa `LLMService.__new__` e setta `_ctx_window_*` sull'istanza — la delega al resolver darebbe AttributeError); (3) `_sanitize_tool_calls` in prompting.py, non client.py (unico chiamante è normalize_history; in client sarebbe stato un import circolare); (4) `PromptBuilder.build_messages` riceve `supports_vision: bool` iniettato dal facade (letto da `resolver.supports_vision` nello STESSO punto del monolite — timing verificato in parità); (5) `close()` via collaboratori. Spec review: "Conforme con note" — diff automatizzato statement-level sui metodi rischiosi byte-identico salvo rimappature dichiarate; nit applicati dal controller in `2760135` (`clear_response_ids()` pubblico su LLMClient invece del reach nel privato, `_is_ollama` annotato come derivato-non-stato). Quality review (top): "Ready: Yes" — lifecycle httpx verificato (UNICA costruzione in bootstrap/inference.py, routes/config.py invalida solo cache, mai ricostruzione → nessun use-after-close), finestra di concorrenza NON allargata (response_ids/flag/lock byte-identici), seam registry guardato su tutti i mark_*, protocol esteso senza debito nuovo, mypy 4 errori = baseline fase4 uno-a-uno; nit docstring package applicato in `89b53cd`. Backlog registrato: iniezione `_client` per riferimento = footgun se un futuro hot-reload riassegnasse `svc._client` (oggi non esercitato; fix = ricostruire l'intero LLMService come stt/tts). Gate: 50/50 suite di equivalenza SENZA modifiche ai test, boot ok, ruff nuovi puliti, EOL i/lf. Commit `399714d` + `2760135` + `89b53cd`.

**Files:**
- Create: `backend/services/llm/__init__.py`, `client.py`, `prompting.py`, `model_resolution.py`
- Rewrite: `backend/services/llm_service.py` (facade)
- Modify: `backend/core/protocols.py:34-109` (`LLMServiceProtocol` allineato)

**Criterio di equivalenza (vincolante):** `tests/test_llm_service.py`, `tests/test_llm_model_resolution.py`, `tests/test_llm_preferred_name.py`, `tests/test_context_window_cache.py` passano SENZA modifiche (il facade mantiene gli alias privati che i test usano — decisione 7).

- [ ] **Step 1: Crea i tre moduli**

Regole: corpi VERBATIM da `llm_service.py` (righe nella tabella §Contesto); cambia solo il binding dello stato. Il facade possiede l'`httpx.AsyncClient` e lo inietta.

`backend/services/llm/__init__.py`:

```python
"""AL\\CE — LLM service components (Fase 5, spec §5.1).

The historical monolithic ``LLMService`` is split by responsibility:

- :mod:`client` — the HTTP/streaming client (LM Studio native SSE +
  OpenAI-compatible SSE, non-streaming completion).
- :mod:`prompting` — system-prompt composition and message building.
- :mod:`model_resolution` — capability selection: ``"auto"`` model
  resolution and the context-window cache, collaborating with
  :class:`~backend.services.model_capability_registry.ModelCapabilityRegistry`.

``backend.services.llm_service.LLMService`` remains the facade every
consumer (turn engine, chat assembly, routes) uses; its public API is
unchanged.
"""

from backend.services.llm.client import LLMClient
from backend.services.llm.model_resolution import ModelResolver
from backend.services.llm.prompting import PromptBuilder, normalize_history

__all__ = ["LLMClient", "ModelResolver", "PromptBuilder", "normalize_history"]
```

`model_resolution.py` — `class ModelResolver`: `__init__(config: LLMConfig, model_registry: ModelCapabilityRegistry | None, http: httpx.AsyncClient)`; stato `_auto_model_cache`/`_auto_model_ttl`/`_auto_model_lock` + famiglia `_ctx_window_*` (valori iniziali identici a `LLMService.__init__`, righe 149-152 e 163-170). Metodi (verbatim): statics `_is_embedding_model` (176-190), `_model_id` (192-195), `_is_loaded` (197-209), `_pick_chat_model_id` (211-248); `get_model_profile` (254-268, era `_get_model_profile`), `supports_vision` property (274-287), `resolve` (289-423, era `_resolve_model`; `self._client` → `self._http`), `invalidate_model_cache` (425-432), `get_cached_context_window` (1608-1642), `_refresh_context_window` (1644-1669), `invalidate_context_window_cache` (1671-1675), `get_active_context_window` (1677-1682).

`prompting.py` — funzione modulo `normalize_history` (63-112, verbatim) + `class PromptBuilder`: `__init__(config: LLMConfig)`; stato `_system_prompt = None`, `_scoped_prompts: dict[str, str] = {}`. Metodi (verbatim): `_load_system_prompt` (434-481), `invalidate_system_prompt_cache` (483-486), `_temporal_block` (488-512), `_get_dynamic_system_prompt` (514-528), `get_system_prompt` (530-566), `_load_scoped_prompt` (568-594), `get_scoped_system_prompt` (596-626), `_fold_system_into_user` static (632-700), `build_messages` (702-787), `build_continuation_messages` (789-826).

`client.py` — funzione modulo `_sanitize_tool_calls` (28-60, verbatim) + `class LLMClient`: `__init__(config: LLMConfig, http: httpx.AsyncClient, resolver: ModelResolver, model_registry: ModelCapabilityRegistry | None, prompts: PromptBuilder)`; stato `_is_ollama`, `_response_ids`/`_response_ids_max`, `_supports_stream_options`, `_supports_response_format` (init identico a righe 141-160). Metodi (verbatim): `chat` (832-895), `_chat_lmstudio_native` (901-1063), `_stream_lmstudio_native_sse` (1069-1235), `_chat_openai_compat` (1241-1561), `complete_nonstreaming` (1567-1606). Rimappature nello spostamento: `self._client` → `self._http`; `self._resolve_model()` → `self._resolver.resolve()`; `self._get_model_profile(...)` → `self._resolver.get_model_profile(...)`; le chiamate learning `self._model_registry.mark_*` restano su `self._model_registry` (iniettato — è il seam esplicito CLIENT→CAPABILITY); i riferimenti a metodi PROMPT (es. `_fold_system_into_user`, `build_messages` dentro `_chat_lmstudio_native` se presenti) → `self._prompts.<metodo>`.

- [ ] **Step 2: Riscrivi `services/llm_service.py` come facade**

`LLMService.__init__(config, model_registry=None)` INVARIATO nella firma; costruisce:

```python
        self._config = config
        self._model_registry = model_registry
        self._http = httpx.AsyncClient(timeout=...)  # identico ai timeout attuali (righe 133-140)
        self._resolver = ModelResolver(config, model_registry, http=self._http)
        self._prompts = PromptBuilder(config)
        self._client = LLMClient(
            config, http=self._http, resolver=self._resolver,
            model_registry=model_registry, prompts=self._prompts,
        )
```

Deleghe pubbliche 1:1: `chat`, `complete_nonstreaming` → `self._client`; `get_system_prompt`, `get_scoped_system_prompt`, `build_messages`, `build_continuation_messages`, `invalidate_system_prompt_cache` → `self._prompts`; `supports_vision` (property), `invalidate_model_cache`, `get_cached_context_window`, `invalidate_context_window_cache`, `get_active_context_window` → `self._resolver`. `close()`: `await self._http.aclose()` + svuotamento cache come oggi (1688-1693). Alias privati di compat per i test (decisione 7):

```python
    # -- test-compat aliases (backlog: migrate tests to ModelResolver) ------
    async def _resolve_model(self) -> str:
        return await self._resolver.resolve()

    _is_embedding_model = staticmethod(ModelResolver._is_embedding_model)
    _model_id = staticmethod(ModelResolver._model_id)
    _is_loaded = staticmethod(ModelResolver._is_loaded)
```

(se `test_llm_model_resolution.py` tocca ANCHE `_pick_chat_model_id`/`_get_model_profile`/attributi di cache privati come `_auto_model_cache`, aggiungi gli alias/property corrispondenti — verifica con `git grep -n "svc\._\|service\._\|llm\._" -- backend/tests/test_llm_model_resolution.py backend/tests/test_context_window_cache.py` e copri ESATTAMENTE quelli usati). Ri-esporta in coda al modulo: `from backend.services.llm.prompting import normalize_history  # noqa: E402,F401` (verifica i consumer con `git grep -n "normalize_history" -- backend`).

- [ ] **Step 3: Allinea `LLMServiceProtocol`**

In `backend/core/protocols.py:34-109` aggiungi al Protocol (firme identiche al concreto):

```python
    def get_scoped_system_prompt(
        self,
        base_prompt_path: str,
        memory_context: str | None = None,
    ) -> str:
        """Compose the system prompt for a scoped (workspace) turn."""
        ...

    def get_cached_context_window(self, lmstudio_manager: Any = None) -> int:
        """Non-blocking context-window read (background refresh)."""
        ...

    def invalidate_context_window_cache(self) -> None:
        """Drop the cached context window (next read re-probes)."""
        ...
```

e nella firma di `chat` aggiungi i keyword param `response_format: dict | None = None` e `temperature: float | None = None` (in coda, come nel concreto — copia la firma esatta da `llm_service.py:832-846`).

- [ ] **Step 4: Esegui la suite di equivalenza**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_llm_service.py tests/test_llm_model_resolution.py tests/test_llm_preferred_name.py tests/test_context_window_cache.py tests/test_tool_calling.py tests/test_direct_executor_streaming.py -v
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
```

Atteso: PASS senza modifiche ai test + `app ok`.

- [ ] **Step 5: Lint scoped e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check services/llm services/llm_service.py core/protocols.py
..\.venv\Scripts\python.exe -m mypy services/llm
Set-Location C:\Users\Jays\Desktop\alice\alice
git ls-files --eol backend/services/llm/ backend/services/llm_service.py
git add backend/services/llm backend/services/llm_service.py backend/core/protocols.py
git commit -m "refactor(llm): split in client/prompting/model_resolution, facade e protocol allineati" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Censimento flag — registro unico + rimozione dei 3 morti + regen

> **Esito (2026-07-10):** DONE. Implementazione in `1c39ef6`: `docs/flag-registry.md` (21 flag vivi verificati cella per cella dall'implementer, zero correzioni necessarie vs piano; 3 rimossi documentati), rimozione dei 3 morti da config model + default.yaml + echo REST (nessun echo `sound_enabled` esisteva — verificato), `_REMOVED_LEGACY_KEYS` + `_strip_removed_legacy_keys` agganciato in `migrate_legacy_config_keys`, test dello strip. **Regen contracts: NESSUN diff** (GET/PUT config sono dict senza response_model, i flag non erano mai negli schemi; check-contracts verde). Spec review: "Conforme con note" — morte dei 3 flag confermata indipendentemente (zero consumatori BE/FE/continuum), censimento 21/21 senza omissioni (enumerazione programmatica dei bool `enabled` del config model), strip cablato nel punto giusto (per-layer in `config_service.py:250-256` PRIMA del merge + model_validator before su AliceConfig = nessun bypass), fail pre-esistente `test_plugins_enabled_list` (21 vs 20) riprodotto su worktree a `1c39ef6~1`; fix minor applicato dal controller: esempio YAML stantio in `plugins/pc_automation/README.md`. Quality review (top): "Ready: Yes" — percorsi runtime verificati EMPIRICAMENTE: boot con chiavi stantie nei layer ok, PUT config a whitelist ignora silenziosamente i flag rimossi (no 422/500), env stantie `ALICE_*__*` stripate dal validator senza rompere il boot, layer su disco auto-sanante alla prima `set()`; fix minor applicato dal controller in `af6daf7`: test end-to-end `test_stale_flag_survives_full_aliceconfig_construction` (extra=forbid + strip su costruzione diretta). INCIDENTE EOL n.3 del programma: il fix del README ha flippato l'intero file a CRLF nel commit `af6daf7` — smascherato con `--ignore-cr-at-eol --stat` (1 riga reale su 169 apparenti), ripristinato LF in `58e76d5`. Backlog: guardia anti-drift per flag-registry.md (test che enumeri i bool `enabled` del model e verifichi la presenza nel registro); commento stantio in default.yaml:119-120 su terminal.enabled (pre-esistente). Gate: test_config 24/25 (1 fail pre-esistente dichiarato), boot ok, ruff/mypy debito zero vs base, check-contracts verde, EOL i/lf. Commit `1c39ef6` + `af6daf7` + `58e76d5`.

**Files:**
- Create: `docs/flag-registry.md`
- Modify: `backend/core/config.py` (rimozione 3 campi + strip legacy)
- Modify: `config/default.yaml` (righe 113, 116, 199)
- Modify: `backend/api/routes/config.py` (echo get/set dei 3 flag)
- Regen: `backend/openapi.json` + `frontend/src/renderer/src/types/generated/*` (se diff)

- [ ] **Step 1: Crea `docs/flag-registry.md`**

```markdown
# Registro dei flag `enabled` (Fase 5 — censimento spec §5.1)

Fonte di verità sui flag booleani di abilitazione della config backend.
Regola: un flag entra qui quando nasce; un flag mai letto si elimina.
I default indicati sono quelli EFFETTIVI a runtime (YAML `config/default.yaml`,
che vince sul default pydantic).

## Il doppio gate dei plugin

`plugins.enabled` è una LISTA di nomi (seed da YAML, override persistente
per-utente nel DB via `plugin_states`): decide quali plugin vengono CARICATI.
I flag `<sezione>.enabled` qui sotto sono un SECONDO gate indipendente letto
dal plugin stesso (tool nascosti/erroranti finché false). Per accendere una
feature servono ENTRAMBI.

## Flag vivi

| Flag | Default runtime | Letto da | Note |
|---|---|---|---|
| `llm.system_prompt_enabled` | true | `services/llm/prompting.py` | salta il system prompt |
| `llm.tools_enabled` | true | `chat/_assembly.py`, `chat/conversations.py` | gate globale invio tool |
| `llm.tool_rag_enabled` | true | `chat/_assembly.py`, `rag_readiness.py` | Tool RAG vs toolset pieno |
| `llm.context_compression_enabled` | true | `chat/_assembly.py`, `turn/tool_loop.py`, `chat/_persist.py` | compaction |
| `stt.enabled` | true | bootstrap (`stage_senses`) | avvia STTService |
| `tts.enabled` | true | bootstrap (`stage_senses`) | avvia TTSService |
| `permissions.confirmations_enabled` | true | `turn/tool_loop.py`, `turn/pipeline.py` | conferme tool pericolosi |
| `terminal.enabled` | true | plugin terminal, route terminal/events | doppio gate col plugin |
| `vram.monitoring_enabled` | true | bootstrap (`stage_senses`) | |
| `memory.enabled` | true | bootstrap (`stage_knowledge`), `knowledge_init.py` | doppio gate col plugin `memory` |
| `continuum.enabled` | true | bootstrap (`stage_knowledge`), `knowledge_init.py` | doppio gate col plugin `continuum` |
| `chart.enabled` | true | plugin `chart_generator` | doppio gate |
| `whiteboard.enabled` | true | plugin `whiteboard` | doppio gate |
| `email.enabled` | false | bootstrap (`stage_senses`), plugin, route email | doppio gate |
| `email.imap_idle_enabled` | true | `services/email_service.py` | task IMAP IDLE |
| `trellis.enabled` | true | bootstrap (`stage_senses`), route services | microservizio 3D |
| `trellis2.enabled` | true | bootstrap (`stage_senses`), plugin `cad_generator` | |
| `trellis2multiview.enabled` | true | bootstrap (`stage_senses`), plugin `cad_generator` | |
| `agent.reflection.enabled` | false | `turn/factory.py` | ReflectiveTurnExecutor |
| `agent.reflection.degeneration_detector_enabled` | true | `turn/_reflection.py` | |
| `mcp.servers[].enabled` | true (per server) | plugin `mcp_client`, `chat/_helpers.py`, route mcp | per-server |

Affini fuori convenzione: `agent.planning` / `agent.delegation` /
`agent.clarification` (gate dei meta-tool; rinominati dai legacy `*_enabled`).

## Flag rimossi in Fase 5 (morti: mai letti da alcun consumatore)

| Flag | Perché era morto |
|---|---|
| `voice.voice_confirmation_enabled` | esposto in GET/PUT config, nessun consumatore BE/FE |
| `pc_automation.enabled` | il gate reale è `plugins.enabled` (toggle DB); il flag non gate-ava nulla |
| `notifications.sound_enabled` | il plugin legge solo `default_timeout_s`/`app_id`/`max_active_timers` |

Le chiavi stantie nei layer `system.yaml`/`user.yaml` vengono eliminate dal
migratore legacy (`migrate_legacy_config_keys`, i modelli sono extra=forbid).
```

Dopo il Task 2 i "Letto da" con `bootstrap (...)` sono corretti; se questo task viene eseguito PRIMA del Task 2 (non previsto), usare `core/app.py`.

- [ ] **Step 2: Rimuovi i 3 campi dai config model**

In `backend/core/config.py`:
1. Rimuovi `voice_confirmation_enabled: bool = True` (riga ~330, con l'eventuale docstring).
2. Rimuovi `enabled: bool = False` dalla `PcAutomationConfig` (riga ~347, con docstring).
3. Rimuovi `sound_enabled: bool = True` dalla `NotificationsConfig` (riga ~520, con docstring).
4. Accanto a `_LEGACY_PC_AUTOMATION_PERMISSION_KEYS` (riga ~1165) aggiungi:

```python
# Dead flags removed in Fase 5 (never read by any consumer).  Stale keys
# persisted in system.yaml/user.yaml must be dropped per layer because
# every config model forbids unknown fields.
_REMOVED_LEGACY_KEYS: tuple[tuple[str, str], ...] = (
    ("voice", "voice_confirmation_enabled"),
    ("pc_automation", "enabled"),
    ("notifications", "sound_enabled"),
)


def _strip_removed_legacy_keys(data: dict[str, Any]) -> None:
    """Drop config keys removed in Fase 5 from a raw layer dict, in place."""
    for section, key in _REMOVED_LEGACY_KEYS:
        block = data.get(section)
        if isinstance(block, dict) and key in block:
            block.pop(key)
            logger.info(
                "Dropped removed legacy config key '{}.{}'", section, key,
            )
```

5. In `migrate_legacy_config_keys` aggiungi la chiamata `_strip_removed_legacy_keys(data)` accanto a `_migrate_pc_automation_permissions(data)` (stesso punto del flusso, così agisce per-layer E sul validator di `AliceConfig`).

- [ ] **Step 3: Rimuovi i flag da `config/default.yaml` e dall'echo REST**

In `config/default.yaml` elimina le righe `voice_confirmation_enabled: true` (113), `enabled: false` sotto `pc_automation:` (116), `sound_enabled: true` (199). In `backend/api/routes/config.py`: rimuovi `"voice_confirmation_enabled": cfg.voice.voice_confirmation_enabled,` (riga ~302) e `"enabled": cfg.pc_automation.enabled,` (riga ~307) dai dict di risposta; rimuovi il blocco di validazione/set di `voice_confirmation_enabled` (righe ~608-613) e il blocco `enabled` dentro l'update `pc_automation` (righe ~632-638, SOLO la gestione di `enabled` — le altre chiavi del blocco restano); se GET/PUT config espongono `notifications.sound_enabled`, rimuovi anche quelle righe (verifica con `git grep -n "sound_enabled" -- backend/api`).

- [ ] **Step 4: Verifica residui, test e boot**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "voice_confirmation_enabled\|sound_enabled" -- backend config frontend/src
```

Atteso: nessun match di produzione (restano solo eventuali match storici in docs/test da aggiornare — aggiorna i test che li referenziano, se esistono). `pc_automation` come PLUGIN continua a esistere (non toccarlo).

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_layered_config.py -v
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
```

(se `tests/test_config.py`/`test_layered_config.py` non esistono con questi nomi, individua i test della config con `Get-ChildItem backend\tests -Filter "*config*"` e lancia quelli). Aggiungi al file di test della config un caso per lo strip:

```python
def test_removed_legacy_keys_are_stripped():
    from backend.core.config import migrate_legacy_config_keys

    data = {
        "voice": {"wake_word": "alice", "voice_confirmation_enabled": True},
        "pc_automation": {"enabled": False, "command_timeout_s": 30},
        "notifications": {"sound_enabled": True, "app_id": "AL\\CE"},
    }
    migrate_legacy_config_keys(data)
    assert "voice_confirmation_enabled" not in data["voice"]
    assert "enabled" not in data["pc_automation"]
    assert "sound_enabled" not in data["notifications"]
    assert data["pc_automation"]["command_timeout_s"] == 30
```

- [ ] **Step 5: Commit, poi regen contracts**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add docs/flag-registry.md backend/core/config.py config/default.yaml backend/api/routes/config.py backend/tests/
git commit -m "feat(config): censimento flag enabled - registro unico, rimozione 3 flag morti con strip legacy" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
.\scripts\gen-contracts.ps1
git status --porcelain
```

Se la regen produce diff (openapi.json / api.d.ts — atteso se i model config compaiono negli schemi): verifica il diff (SOLO rimozioni dei 3 flag), poi:

```powershell
cd frontend; npm run typecheck; cd ..
git add backend/openapi.json frontend/src/renderer/src/types/generated
git commit -m "chore(contracts): regen post rimozione flag morti" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
.\scripts\check-contracts.ps1
```

Se la regen NON produce diff, esegui comunque `.\scripts\check-contracts.ps1` (atteso verde) e prosegui.

---

### Task 7: Sanare il layering — calendar, MCP gateway, terminal security

> **Esito (2026-07-10):** DONE. Implementazione in `37d5e7d` (14 file, +184/−131): `services/calendar_events.py` (CalendarEvent + validate_rrule verbatim, utils.py del plugin eliminato — conteneva SOLO ciò che è stato spostato), `services/mcp_gateway.py` (McpClientProtocol strutturale + get_mcp_client + require_mcp_session coi 3 503 byte-identici e in STESSO ordine), `security.py` → services/terminal (similarity 100%, puro rename). Deviazione dichiarata accettata: ruff --fix (UP017/I001) sui soli file nuovi. Spec review: "Conforme con note" — verbatim calendar verificato campo per campo (uniche diff = le 2 fix stilistiche dichiarate), firme protocol combacianti (mypy 0), semantica route invariata (puro rename di _get_mcp_plugin), test toccati SOLO negli import; F1 minor applicato dal controller: I001 introdotto in `services/terminal/manager.py` dal rename dell'import (plugins<services alfabeticamente). Quality review (top): "Ready: Yes" — doppia registrazione SQLModel esclusa (1 sola class CalendarEvent, stessa classe importata ovunque), zero import runtime services→plugins (grep esaustivo; le occorrenze residue sono docstring), nessun buco di tipo (protocol dichiara `list[ToolDefinition]`, `object` contravariante corretto), plugin calendar pulito post-svuotamento, mypy 1 solo errore dateutil pre-esistente (era mascherato dalla cache incrementale sul plugin); nit applicato dal controller: `isinstance(plugin, McpClientProtocol)` in get_mcp_client (il runtime_checkable ora è sfruttato: un rename futuro dà 503 pulito invece di AttributeError; cast ridondante rimosso per narrowing). Fix di review in `4fdc201`. Backlog: debito ruff cosmetico pre-esistente in routes/calendar.py e plugins/calendar/plugin.py (UP017/B904/SIM105/I001/F401); incoerenza stilistica datetime.now(UTC) vs timezone.utc tra calendar_events e plugin. Gate: 136 pass + 1 skip (calendar 43, mcp 74, terminal 63+1skip — numeri implementer; re-run reviewer 77+1skip e 41 concordi), boot ok, EOL i/lf, `--ignore-cr-at-eol` = stat identico (no flip). Commit `37d5e7d` + `4fdc201`.

**Files:**
- Create: `backend/services/calendar_events.py`
- Modify: `backend/plugins/calendar/plugin.py`, delete `backend/plugins/calendar/utils.py`, modify `backend/api/routes/calendar.py`, `backend/tests/test_calendar_plugin.py`
- Create: `backend/services/mcp_gateway.py`
- Modify: `backend/api/routes/mcp.py`, `backend/api/routes/mcp_memory.py`
- Move: `backend/plugins/terminal/security.py` → `backend/services/terminal/security.py` (+ import updates)

- [ ] **Step 1: Calendar — modello e validazione condivisi in services**

Crea `backend/services/calendar_events.py` contenente, VERBATIM:
1. la classe `CalendarEvent` da `backend/plugins/calendar/plugin.py:45-73` (con i suoi import: `uuid`, `datetime`/`timezone`, `sqlalchemy as sa`, `SQLModel`/`Field` da sqlmodel);
2. `MAX_OCCURRENCES`, `_ALLOWED_FREQUENCIES` e `validate_rrule` da `backend/plugins/calendar/utils.py` (righe 13-50);
3. docstring modulo:

```python
"""AL\\CE — Shared calendar domain model and RRULE validation.

``CalendarEvent`` (the SQLModel table) and the RRULE validation helpers
are shared between the calendar plugin (tools) and the calendar REST
routes — defined at the services layer so routes never import plugin
internals (layering contract §4).  The plugin still OWNS the table
lifecycle via ``get_db_models``.
"""
```

Poi:
- in `backend/plugins/calendar/plugin.py`: rimuovi la definizione di `CalendarEvent` e l'import da `utils`, importa `from backend.services.calendar_events import MAX_OCCURRENCES, CalendarEvent, validate_rrule` (il plugin continua a restituire `CalendarEvent` in `get_db_models` — invariato);
- elimina `backend/plugins/calendar/utils.py` (`git rm`);
- in `backend/api/routes/calendar.py:17-21`: sostituisci i due import plugin con `from backend.services.calendar_events import MAX_OCCURRENCES, CalendarEvent, validate_rrule`;
- in `backend/tests/test_calendar_plugin.py:18`: `from backend.plugins.calendar.plugin import CalendarPlugin` + `from backend.services.calendar_events import CalendarEvent`.

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_calendar_plugin.py -v
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "plugins.calendar" -- backend/api
```

Atteso: PASS; grep vuoto.

- [ ] **Step 2: MCP — gateway con Protocol strutturale in services**

Crea `backend/services/mcp_gateway.py`:

```python
"""AL\\CE — Typed access to the MCP client plugin for REST routes.

Routes must not import plugin internals (layering contract §4).  This
module gives them a STRUCTURAL protocol of the (few) ``McpClientPlugin``
methods they use plus accessors that normalise the unavailable states
into the canonical 503s.  The plugin satisfies the protocol implicitly;
nothing here imports from ``backend.plugins``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import HTTPException

if TYPE_CHECKING:
    from backend.core.context import AppContext
    from backend.services.mcp_session import McpSession


@runtime_checkable
class McpClientProtocol(Protocol):
    """The surface of the MCP client plugin consumed by REST routes."""

    async def get_status(self) -> dict[str, str]:
        """Connection status per configured server."""
        ...

    def get_server_tools(self, server_name: str) -> list:
        """Tool definitions currently exposed by a server."""
        ...

    async def reconnect_server(self, server_name: str, server_config: object):
        """Tear down and re-establish a server session."""
        ...

    def get_session(self, server_name: str) -> "McpSession | None":
        """The live session for a server, or ``None`` if not connected."""
        ...


def get_mcp_client(ctx: AppContext) -> McpClientProtocol | None:
    """The MCP client plugin as a protocol, or ``None`` if not loaded."""
    if ctx.plugin_manager is None:
        return None
    plugin = ctx.plugin_manager.get_plugin("mcp_client")
    if plugin is None:
        return None
    return plugin  # structural: McpClientPlugin satisfies the protocol


def require_mcp_session(ctx: AppContext, server_name: str) -> "McpSession":
    """The live MCP session for ``server_name`` or the canonical 503s.

    Raises:
        HTTPException: 503 when the plugin manager, the MCP client plugin
            or the server session is unavailable.
    """
    if ctx.plugin_manager is None:
        raise HTTPException(503, "Plugin manager not available")
    client = get_mcp_client(ctx)
    if client is None:
        raise HTTPException(503, "MCP client plugin not loaded")
    session = client.get_session(server_name)
    if session is None:
        raise HTTPException(503, f"MCP server '{server_name}' not connected")
    return session
```

(se mypy segnala il return `plugin` non-conforme, usa `cast("McpClientProtocol", plugin)` con commento "structural".) Poi:
- `backend/api/routes/mcp.py`: elimina il blocco `if TYPE_CHECKING` (righe 13-14) e la funzione `_get_mcp_plugin` (19-27); importa `from backend.services.mcp_gateway import get_mcp_client`; sostituisci ogni `_get_mcp_plugin(ctx)` con `get_mcp_client(ctx)` (3 occorrenze; le annotazioni `McpClientPlugin` diventano `McpClientProtocol` o si tolgono).
- `backend/api/routes/mcp_memory.py`: elimina l'import TYPE_CHECKING di `McpClientPlugin` (riga 20); riscrivi `_get_memory_session` come:

```python
def _get_memory_session(request: Request) -> McpSession:
    """Retrieve the live MCP 'memory' session (503 when unavailable)."""
    ctx: AppContext = request.app.state.context
    return require_mcp_session(ctx, _SERVER_NAME)
```

con `from backend.services.mcp_gateway import require_mcp_session` (l'import TYPE_CHECKING di `McpSession` resta).

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_mcp_client_plugin.py tests/contracts/test_ws_schema_events.py -v
..\.venv\Scripts\python.exe -m mypy services/mcp_gateway.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "plugins.mcp_client" -- backend/api
```

Atteso: PASS, mypy 0 sul file nuovo, grep vuoto. Se esistono test delle route mcp/mcp_memory (`Get-ChildItem backend\tests -Filter "*mcp*"`), lanciali tutti.

- [ ] **Step 3: Terminal — security si sposta nel service layer**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git mv backend/plugins/terminal/security.py backend/services/terminal/security.py
git grep -n "plugins.terminal.security\|plugins\.terminal import security" -- backend
```

Aggiorna OGNI sito trovato (noti: `services/terminal/manager.py:42` import runtime; riferimenti in docstring di `services/terminal/{manager,__init__}.py`; `tests/test_terminal_security.py:19`; eventuali import DENTRO `backend/plugins/terminal/` — es. `plugin.py`/`executor.py`: sostituisci con `from backend.services.terminal.security import ...`, plugins→services è lecito). Aggiorna il docstring di modulo di `security.py` se cita il vecchio path.

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_terminal_security.py tests/test_terminal_plugin.py tests/test_terminal_executor.py tests/test_terminal_agent_mirror.py -v
```

Atteso: PASS.

- [ ] **Step 4: Boot check e commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
git ls-files --eol backend/services/calendar_events.py backend/services/mcp_gateway.py backend/services/terminal/security.py
git add -A backend/services backend/plugins/calendar backend/plugins/terminal backend/api/routes/calendar.py backend/api/routes/mcp.py backend/api/routes/mcp_memory.py backend/tests
git commit -m "refactor(layering): calendar/MCP/terminal senza import route->plugin e services->plugin" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: import-linter — contratti §4 in locale e in CI

> **Esito (2026-07-10):** DONE, eseguito direttamente dal controller (configurazione a contenuto prescritto, gate auto-verificante). `import-linter==2.13`/`grimp==3.15` installati via uv (il venv non ha pip — usare `uv pip install`). Due aggiustamenti rispetto al TOML del piano, entrambi nel perimetro approvato: (1) l'entry `backend.core.bootstrap.* -> backend.api.*` inizialmente RIMOSSA per il fail "No matches" (nota c del piano), poi RIPRISTINATA con wildcard corretto — il problema era la sintassi, non l'assenza dell'import (bootstrap.surfaces importa `api.ws_schema.guard`); (2) i wildcard `*` di grimp matchano UN solo livello: gli import reali sono più profondi (`api.middleware.exception_handler`, `services.knowledge.service`) → `backend.core.app -> backend.api.**`, `bootstrap.* -> services.**`, `bootstrap.* -> api.**` (ricorsivi); `managed_services.* -> services.*` resta a un livello (sufficiente, verificato dal linter stesso). **Risultato: `Analyzed 454 files, 2605 dependencies — Contracts: 6 kept, 0 broken`**. Step CI inserito in contracts.yml tra "Contract tests" e "Generated artifacts are fresh" (import-linter arriva dal gruppo dev già installato dallo step venv). EOL i/lf. Commit `ef900ff`.

**Files:**
- Modify: `backend/pyproject.toml` (dev dep + `[tool.importlinter]`)
- Modify: `.github/workflows/contracts.yml` (nuovo step)

- [ ] **Step 1: Dipendenza e configurazione**

In `backend/pyproject.toml`, aggiungi a `[project.optional-dependencies] dev`:

```toml
    "import-linter>=2.1",
```

e in coda al file:

```toml
[tool.importlinter]
root_packages = ["backend"]
include_external_packages = true

# §4.1 — a plugin never imports another plugin.
[[tool.importlinter.contracts]]
name = "plugins are independent"
type = "independence"
modules = ["backend.plugins.*"]

# §4.2 — routes never import plugin internals (they go through
# ctx.plugin_manager / services-layer protocols).
[[tool.importlinter.contracts]]
name = "api does not import plugins"
type = "forbidden"
source_modules = ["backend.api"]
forbidden_modules = ["backend.plugins"]

# §4.3 — services never import the api layer.
[[tool.importlinter.contracts]]
name = "services do not import api"
type = "forbidden"
source_modules = ["backend.services"]
forbidden_modules = ["backend.api"]

# §4 (dipendenze solo verso il basso) — services never import plugins.
[[tool.importlinter.contracts]]
name = "services do not import plugins"
type = "forbidden"
source_modules = ["backend.services"]
forbidden_modules = ["backend.plugins"]

# §4.4 — Continuum is a separate project consumed over HTTP only.
[[tool.importlinter.contracts]]
name = "no imports from the continuum project"
type = "forbidden"
source_modules = ["backend"]
forbidden_modules = ["continuum"]

# §4 — core depends only on protocols; the composition root
# (app + bootstrap stages), the managed-service adapters and two
# documented protocol re-exports are the sanctioned exceptions.
[[tool.importlinter.contracts]]
name = "core does not import services or api"
type = "forbidden"
source_modules = ["backend.core"]
forbidden_modules = ["backend.services", "backend.api"]
ignore_imports = [
    "backend.core.app -> backend.api.*",
    "backend.core.bootstrap.* -> backend.services.*",
    "backend.core.bootstrap.* -> backend.api.*",
    "backend.core.managed_services.* -> backend.services.*",
    "backend.core.protocols -> backend.services.knowledge.protocol",
    "backend.core.context -> backend.services.rag_readiness",
    "backend.core.service_groups -> backend.services.rag_readiness",
]
```

Note per l'implementer: (a) se la versione installata non supporta i wildcard nei `modules` dell'independence contract, elenca esplicitamente i package presenti (`Get-ChildItem backend\plugins -Directory | Select-Object -ExpandProperty Name` → `backend.plugins.<nome>` ciascuno); (b) se `lint-imports` segnala import residui non in lista (es. un import dimenticato in `core/app.py`), NON allargare l'ignore-list: sposta l'import nel modulo bootstrap giusto o segnala il finding — l'ignore-list sopra è il perimetro APPROVATO; le uniche aggiunte ammesse senza review sono varianti puntuali della stessa famiglia (es. `backend.core.app -> backend.core...` non serve, è intra-core); (c) import-linter FALLISCE su una entry `ignore_imports` che non matcha alcun import reale — se una entry risulta inutilizzata, RIMUOVILA (non è un errore del piano: significa che quell'import non esiste più).

- [ ] **Step 2: Installa ed esegui in locale**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pip install "import-linter>=2.1"
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\lint-imports --config backend\pyproject.toml
```

Atteso: `Contracts: 6 kept, 0 broken.` (il comando gira dalla REPO ROOT: il package `backend` è importabile da lì). Se un contratto è rotto, il fix appartiene ai Task 4/7 (o è un import sfuggito): correggi lì, non nell'ignore-list.

- [ ] **Step 3: Step CI**

In `.github/workflows/contracts.yml`, tra lo step "Contract tests" e "Generated artifacts are fresh" inserisci:

```yaml
      - name: Import layering (import-linter)
        run: |
          .\.venv\Scripts\lint-imports --config backend/pyproject.toml
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

(gira dalla repo root, coerente con lo step locale; import-linter è installato dallo step venv perché è nel gruppo `dev`.)

- [ ] **Step 4: Commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add backend/pyproject.toml .github/workflows/contracts.yml
git commit -m "feat(ci): import-linter con i contratti di layering della spec (4 + services/core)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Gate finale di fase + documentazione

> **Esito (2026-07-10):** DONE (gate eseguiti dal controller). **Step 1 — gate backend mirato**: 22 file di test (lista del piano + test_bootstrap + test_config) = **420 pass, 1 skip, 1 fail** — l'unico fail è `test_plugins_enabled_list` (21 vs 20), VERIFICATO pre-esistente sulla base `arch/fase4-conoscenza` via worktree temporaneo (fallisce identico) → ereditato, backlog, fuori scope fase; `tests/contracts/` incluso e verde (test_openapi_export ok con la regen del Task 6). **Step 2**: lint-imports `6 kept, 0 broken` (454 file, 2605 dipendenze); `create_app(testing=True)` ok; typecheck FE 0; check-contracts verde post-commit. **Step 3 — smoke e2e reale** (`python -m backend`): boot completo ZERO errori nei log degli stage; `GET /api/health` 200 `{"status":"ok"}`; turno chat WS reale: assembly completa (context_info con finestra dal resolver), `turn.started`, `turn.llm_step 1`, e con LM Studio SPENTO chiusura pulita con frame `{"type":"error","content":"LLM error"}` — parità col degrado pre-fase, nessun crash; `POST /api/vector-store/repair` (swap atomico del gruppo Knowledge) ok — qdrant embedded riconnesso, collections preservate (alice_memory 2 punti, alice_tools 251), `GET /api/knowledge/readiness` not-ready SOLO per embedding API irraggiungibile (LM Studio giù = degrado ambientale, parità). **Criterio §9.5** verificato: zero `from backend.services` in core/app.py (151 righe totali). **Step 4**: CLAUDE.md aggiornato (gruppi+bootstrap nel punto 1, facade tools nel punto 3, facade LLM in Data&external, layering+flag-registry in Conventions). Commit di questo step + review finale di fase registrata sotto.

**Files:**
- Modify: `CLAUDE.md` (sezione backend architecture)
- Modify: questo piano (esiti per task) — a cura del controller durante l'esecuzione

- [ ] **Step 1: Gate backend completo (mirato)**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_context.py tests/test_context_groups.py tests/test_app.py tests/test_knowledge_repair.py tests/test_knowledge_service.py tests/test_rag_readiness.py tests/test_tool_registry.py tests/test_tool_status_caching.py tests/test_permission_mode_policy.py tests/test_tool_loop.py tests/test_pipeline.py tests/test_llm_service.py tests/test_llm_model_resolution.py tests/test_llm_preferred_name.py tests/test_context_window_cache.py tests/test_calendar_plugin.py tests/test_terminal_security.py tests/test_terminal_plugin.py tests/test_mcp_client_plugin.py tests/contracts/ -v
```

Atteso: PASS integrale (incluso `test_openapi_export`, ora che la regen del Task 6 è committata).

- [ ] **Step 2: Layering, boot, contracts, FE**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\lint-imports --config backend\pyproject.toml
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('app ok')"
.\scripts\check-contracts.ps1
cd frontend; npm run typecheck; cd ..
```

Atteso: 6 contratti kept; `app ok`; contracts fresh; typecheck 0.

- [ ] **Step 3: Smoke e2e reale (feature di riferimento del dominio toccato, spec §9)**

Avvia il backend reale (`python -m backend`) e verifica: (1) boot completo senza errori nei log degli stage; (2) `GET /api/health` ok; (3) un turno chat semplice via UI o WS (esercita facade LLM + tool registry); (4) `POST /api/vector-store/repair` (esercita lo swap del gruppo knowledge) seguito da `GET /api/knowledge/readiness`. Registra l'esito nel piano. Se LM Studio/modelli non sono disponibili, registra il degrado osservato e confrontalo con il comportamento pre-fase (parità = ok).

- [ ] **Step 4: Aggiorna `CLAUDE.md`**

Nella sezione "Backend architecture", aggiorna il punto 1 (`AppContext`) e aggiungi le novità di fase — testo prescritto:
- punto 1: dopo la frase sul DI container, aggiungi: «Da Fase 5 i campi canonici sono 5 gruppi coesi (`core/service_groups.py`: `inference`/`knowledge`/`workspace`/`conversation`/`platform`); i nomi piatti (`ctx.llm_service`, …) restano come property deleganti. Il lifespan è una sequenza di stage dichiarativi in `core/bootstrap/` (ordine esplicito, shutdown in `bootstrap/shutdown.py`).»
- punto 3 (tools): aggiungi: «`core/tool_registry.py` è una facade sui componenti di `core/tools/` (catalogo/availability/policy-di-offerta/execution/RAG); il gate permessi run-time resta in `services/permission_service.py`.»
- nel paragrafo su `services/llm_service.py` (sezione "Data & external services"): «`LLMService` è una facade sui moduli di `services/llm/` (client streaming, prompting, model resolution).»
- in "Conventions": «Layering vincolato da import-linter in CI (`lint-imports --config backend/pyproject.toml` dalla repo root): plugin indipendenti, api↛plugins, services↛api, services↛plugins, ban `continuum`, core↛services/api (eccezioni: composition root). I flag di config sono censiti in `docs/flag-registry.md`.»

- [ ] **Step 5: Commit finale**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add CLAUDE.md docs/superpowers/plans/2026-07-08-fase5-kernel.md
git commit -m "docs: fase5 - CLAUDE.md su gruppi/bootstrap/split/linter, esiti e gate finale" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Review finale di fase (2026-07-10, modello top, range `arch/fase4-conoscenza..HEAD`)

> **Verdetto: «Phase ready with notes» — zero fix richiesti.** Angolo cross-task: (1) gruppi/bootstrap/repair coerenti — nessuna referenza stale oltre lo swap (ToolRag ri-puntato dal repair via set_vector_backends; continuum_client costruito UNA volta nel bootstrap e riusato; embedding_client in Inference = stabile per costruzione); (2) facade registry vs facade LLM: divergenza di ownership dello stato (registry delega tutto, LLM tiene la context-window cache) GIUSTIFICATA dai vincoli di test binding su entrambi i lati → backlog di armonizzazione quando i test migreranno; (3) tutte le 7 ignore di import-linter VIVE, catene import di core/tools e services/llm rispettano lo spirito §4; (4) flag-registry e CLAUDE.md accurati vs codice; (5) zero morti (ruff F,E9 pulito sui file rifattorizzati; normalize_history re-export vivo; protocol allineati); (6) 59 file nel range, tutti attinenti, trailer su tutti i commit. Verifiche eseguite dal reviewer: lint-imports 6 kept, 18 test cross-task pass, boot 122 route.

## Criteri di uscita della fase (spec §9)

1. Test mirati verdi su tutti i domini toccati (lista Task 9) + `tests/contracts/` verdi.
2. `lint-imports`: 6 contratti kept, 0 broken — in locale e come step CI.
3. App avviabile (`create_app(testing=True)` + boot reale) e smoke e2e del Task 9 Step 3.
4. Typecheck FE 0 + `check-contracts.ps1` verde (regen del Task 6 committata).
5. `AppContext`: gruppi canonici + property compat; `ctx.knowledge` swappato atomicamente dal repair; nessun `from backend.services` in `core/app.py`.
6. Registro flag pubblicato; i 3 flag morti irraggiungibili (grep vuoto) e con strip legacy testato.

## Backlog (fuori scope fase 5, da riportare nell'handoff)

1. **Migrazione dei consumer ai gruppi** (`ctx.llm_service` → `ctx.inference.llm_service`, sweep per dominio; le property piatte restano l'API di transizione fino ad allora). Include la migrazione delle fixture di test.
2. Migrare `test_llm_model_resolution.py`/`test_context_window_cache.py` da alias privati del facade ai moduli `services/llm/` (rimuovendo gli alias di compat).
3. Unificare la costante duplicata `{fs_write, process_exec}` tra `permission_mode_policy._READ_ONLY_BLOCKED_CAPABILITIES` e `permission_service.decide` step 5 (oggi allineate solo da un commento).
4. Valutare lo spostamento di `usage_guidance_for` dal facade registry al prompt assembly (è composizione prompt, non catalogo).
5. `mcp.py`: tipizzare le route MCP (`response_model`) e assorbire il burn-down ratchet del dominio (fasi 5-6 backlog fase 4, voce 1).
6. Ereditati dalle fasi precedenti (handoff): 500→503 search a embedding giù; `MemoryService.list` offset O(n); eventi bulk delete artifacts; live-update whiteboard; CAD `export_url` (fase 6); export conversazioni a modello; `AgentTier` duplicato FE; vitest in CI; orb-era UI da eliminare (fase 6).
7. (review finale) Armonizzare l'ownership dello stato dei due facade (registry delega tutto ai componenti, LLM tiene la context-window cache in proprio) quando i test vincolanti saranno migrati ai moduli — stessa voce dei punti 2 di questo backlog.
8. (review finale) Le 4 lint di stile pre-esistenti spostate verbatim nei moduli nuovi (`SIM105`×2, `B905` in core/tools, `UP041` in bootstrap/senses) — pulizia opportunistica da una riga ciascuna, non più coperte dall'alibi "monolite legacy".
9. (task 6) Guardia anti-drift per `docs/flag-registry.md` (test che enumeri i bool `enabled` del config model e ne verifichi la presenza nel registro); `test_plugins_enabled_list` rosso ereditato (21 plugin reali vs 20 attesi — fallisce identico sulla base fase 4, aggiornare l'atteso).
10. (task 5, quality review) Footgun latente: `_client` httpx iniettato per riferimento in resolver/client — se un futuro hot-reload riassegnasse `svc._client`, ricostruire l'intero LLMService (come stt/tts), mai riassegnare il campo.
