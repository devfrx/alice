# FASE 3 — Integrazione Alice ↔ Continuum

> Obiettivo: Alice consuma Continuum come **memoria dichiarativa** mantenendo intatta la propria
> memoria episodica/runtime. Migrazione **gated da uso reale**, non da calendario. Rollback
> sempre possibile finché il nuovo path non è validato.
>
> Prerequisiti: Fase 1 (`KnowledgeBackend` Protocol esiste in Alice) + Fase 2 (Continuum espone
> API v1 stabile + SDK Python).

## 1. Pattern architetturale scelto

**Knowledge Abstraction Layer (`KnowledgeBackend` Protocol) con doppia implementazione, switch
via config.**

Motivo della scelta vs alternative:

| Alternativa | Scartata perché |
|---|---|
| **SSoT diretto su Continuum subito** | Continuum è giovane. Accoppiare la stabilità di Alice alla maturità di Continuum è rischio non necessario. |
| **MCP-first** | Continuum non espone ancora MCP. Aspettare = bloccare l'integrazione. |
| **Sync bidirezionale DB** | Anti-pattern. Esplicitamente vietato dai principi. |
| **Monorepo unico** | I due progetti hanno lifecycle e audience diversi. |

Risultato pratico:
- Una sola interfaccia che i plugin di Alice consumano.
- Due implementazioni intercambiabili: **`QdrantBackend`** (legacy esistente, wrappa `MemoryService`+`NoteService` su Qdrant) e **`ContinuumBackend`** (target, HTTP→Continuum).
- Switch a runtime: `config.knowledge.backend: "continuum" | "qdrant"`.
- **Routing per kind** opzionale: es. `notes`→Continuum, `session_memory`→sempre Qdrant locale.

## 2. Confine memoria — policy esplicita

### Tabella di routing autoritativa

| Tipo dato | Backend | Motivo |
|---|---|---|
| Note utente (manuali) | **Continuum** | Knowledge dichiarativa, UI in Continuum |
| Lore/personaggi/campagne D&D | **Continuum** | Knowledge dichiarativa con backlink |
| Documenti, progetti | **Continuum** | Knowledge dichiarativa |
| File/immagini allegate | **Continuum** (MinIO) | Storage strutturato |
| **Fatti utente persistenti** ("preferisco caffè senza zucchero") | **Continuum** kind=`fact` | Devono sopravvivere a reinstall di Alice |
| **Riassunti di conversazione** salvati esplicitamente dall'utente | **Continuum** kind=`note`, source=`alice` | Promozione esplicita |
| Conversation history (messaggi raw) | **Alice** (`alice.db` SQLModel) | Episodico, voluminoso, no valore knowledge |
| Working memory di sessione | **Alice** (`MemoryService` scope=`session`, Qdrant locale) | Effimero, TTL 24h |
| Tool execution state | **Alice** (in-memory) | Runtime puro |
| Cancel events, audit log | **Alice** | Runtime/sicurezza |
| Embedding di query effimere (intent classification) | **Alice** (`EmbeddingClient`, no persist) | Computazione runtime, non contenuto |
| Cache di risultati search | **Alice** (in-memory, TTL breve) | Performance |

### Regole decisionali (per LLM e per codice)

Quando un nuovo dato deve essere salvato, applicare in ordine:

1. **È un contenuto curato dall'utente o dichiarato persistente?** → Continuum.
2. **L'utente lo ritroverà mai navigando?** → Sì = Continuum, No = Alice.
3. **Sopravvive a un reinstall di Alice?** → Sì = Continuum, No = Alice.
4. **È runtime/operativo dell'agente?** → Alice.
5. **In dubbio?** → **NON salvare**. Il LLM chiede conferma all'utente prima di promuovere a knowledge.

### Convenzioni metadati per contenuti generati da Alice

Per evitare "inquinamento" del vault:

```json
{
  "source": { "app": "alice", "version": "1.x.x", "user_id": "local" },
  "metadata": {
    "alice_kind": "auto_summary" | "user_fact" | "extracted_entity",
    "alice_conversation_id": "uuid",
    "alice_confidence": 0.0-1.0,
    "alice_user_confirmed": true | false
  },
  "tags": ["alice/auto", "alice/<kind>", ...user_tags]
}
```

> **Prerequisito di Fase 2**: i campi `metadata` e `source` **non esistono** oggi nello schema `notes` di Continuum (verificato in [continuum/server/src/db/schema.ts](../../continuum/server/src/db/schema.ts) — colonne attuali: `id, title, kind, content, contentJson, tags, createdAt, updatedAt`). La drizzle migration che li aggiunge è **task bloccante di Fase 2** prima che Fase 3 possa partire.
>
> **Fallback se la migration slitta**: codifica tutto nei `tags` esistenti (`alice/source:auto`, `alice/kind:user_fact`, `alice/confirmed:false`, `alice/conv:<uuid>`). Meno strutturato ma 0-migration. Da preferire la versione strutturata appena la migration è in produzione.

- Tutto ciò che Alice scrive ha tag `alice/auto` → **filtrabile/deletabile in massa** se diventa rumore.
- `alice_user_confirmed: false` → mostrato in una "inbox" di Continuum per review.
- Continuum non interpreta questi campi: sono opachi per lui (rispetto del confine).

## 3. Componenti — destino dei pezzi attuali in Alice

| Componente attuale | Decisione | Note |
|---|---|---|
| `backend/services/note_service.py` | **Rimosso** dopo migrazione | Funzionalità interamente in Continuum |
| `backend/services/memory_service.py` (scope=`session`) | **Mantenuto** | Working memory, niente migrazione |
| `backend/services/memory_service.py` (scope=`long_term`/`user_fact`) | **Refattorizzato** dietro `KnowledgeBackend` | Diventa adapter sqlite-vec |
| `backend/services/embedding_client.py` | **Mantenuto** | Serve per query effimere (no contenuti) |
| `backend/plugins/notes/` | **Refattorizzato** come thin wrapper su `KnowledgeBackend` | ≤ 100 righe |
| `backend/plugins/memory/` | **Refattorizzato** come thin wrapper su `KnowledgeBackend` | Distingue scope=session vs persist |
| `backend/plugins/mcp_client/` | **Potenziato** | Quando Continuum esporrà MCP, diventa il trasporto |
| `data/qdrant/` (collezioni `memory`, `notes`) | **Mantenute** finché backend=`qdrant` è attivo per qualcuno | Collezioni `notes` e `memory` long-term droppate post-rimozione formale; `memory` con scope=session resta sempre |
| `backend/services/conversation_file_manager.py` | **Mantenuto** | Conversation è episodica |

## 4. Architettura del wiring

```
┌─────────────────────────────────────────────────────────────┐
│                     ALICE (process)                         │
│                                                             │
│  Plugins (notes, memory, mcp_client, ...)                   │
│       │                                                     │
│       ▼                                                     │
│  KnowledgeBackend  ◄──── (Protocol)                         │
│       │                                                     │
│       ├─────► QdrantBackend     ──► data/qdrant/            │
│       │                                                     │
│       └─────► ContinuumBackend  ──┐                         │
│                                   │                         │
│  MemoryService (session)          │   HTTP / MCP            │
│  EmbeddingClient (runtime)        │                         │
│  Conversation history             │                         │
└───────────────────────────────────┼─────────────────────────┘
                                    │
                                    ▼
              ┌──────────────────────────────────┐
              │     CONTINUUM (process)          │
              │  Fastify API v1 (+ MCP server)   │
              │  Postgres+pgvector / Redis / MinIO│
              └──────────────────────────────────┘
```

### `ContinuumBackend` — implementazione

```python
# backend/services/knowledge/continuum_backend.py
class ContinuumBackend:
    name = "continuum"

    def __init__(self, config: ContinuumConfig, http: httpx.AsyncClient,
                 breaker: CircuitBreaker, trace: TraceContext) -> None: ...

    async def search(self, query, *, k=5, filters=None) -> list[KnowledgeHit]:
        # POST /api/v1/notes/search con trace header
        # circuit breaker apre dopo N failures consecutive
        # se aperto → solleva BackendUnavailable (handled upstream)
        ...
```

### Routing avanzato (opzionale)

```yaml
knowledge:
  default_backend: continuum
  routes:
    - kind: ["session_memory", "tool_cache"]
      backend: qdrant          # mai a Continuum (working memory)
    - kind: ["note", "fact", "lore"]
      backend: continuum
  fallback:
    on_unavailable: degrade    # alternative: "fail" | "fallback_qdrant"
```

`KnowledgeRouter` decide a quale backend inviare ogni operazione, basandosi su `kind`.

## 5. Trasporto — REST oggi, MCP appena disponibile

### Fase 3a — REST
- `ContinuumBackend` chiama `httpx.AsyncClient` → API v1 di Continuum.
- Auth via token statico (Fase 2).
- Retry/backoff/circuit breaker integrati nel SDK Python (Fase 2).

### Fase 3b — MCP (quando Continuum lo esporrà)
- Si aggiunge `ContinuumMcpBackend` come terza implementazione di `KnowledgeBackend`.
- Riusa il plugin `mcp_client` esistente per gestire la connessione.
- Tool definitions esposte da Continuum vengono tradotte in `KnowledgeBackend.search/get/...`
  oppure registrate **direttamente** nel `ToolRegistry` di Alice (bypass del backend).
- Switch via config: `knowledge.transport: "rest" | "mcp"`.

**Decisione importante**: anche con MCP attivo, alcune operazioni continueranno a usare REST
(es. upload file, bulk import) perché MCP non è ottimale per binary/streaming.

## 6. Observability end-to-end

### Correlation ID
- Generato in Alice all'ingresso di ogni request utente (WebSocket message, HTTP request).
- Propagato:
  - Nei log loguru (`extra={"trace_id": ...}`).
  - Negli eventi WebSocket verso il frontend.
  - **Header `X-Trace-Id`** verso Continuum (echo nel response, incluso nei log Continuum).
  - Nei tool execution events (`event_bus`).
- Formato: ULID (timestamp + entropy).

### Log unificato (per debugging)
- Entrambi i processi loggano JSON in `%LOCALAPPDATA%\Alice\logs\` e `%LOCALAPPDATA%\Continuum\logs\`.
- Tool CLI in Alice: `python -m backend.scripts.trace <trace_id>` → aggrega log da entrambe le directory.
- Visualizzazione opzionale: pannello "Logs" nel frontend con filter per trace_id.

### Metriche
- Alice esporta su `/api/metrics` (Prometheus-compatible se serve in futuro):
  - `knowledge_requests_total{backend,operation,status}`,
  - `knowledge_request_duration_seconds`,
  - `knowledge_circuit_breaker_state`.

## 7. Resilienza — Continuum offline

### Strategie configurabili

```yaml
knowledge:
  on_unavailable:
    search: "degrade"          # ritorna [] + warning UI
    create: "queue"            # accumula in outbox locale, retry automatico
    update: "queue"
    delete: "queue"
    get:    "fail"             # errore esplicito (no senso degradare)
```

### Outbox pattern per scritture
- Quando `ContinuumBackend.create/update/delete` fallisce e policy è `queue`:
  - Scrittura va in `data/continuum_outbox.db` (sqlite locale).
  - Worker background ritenta con backoff esponenziale.
  - UI mostra badge "N modifiche in pending sync".
  - Quando Continuum torna up → flush ordinato.

### Degraded mode UX
- Banner in alto: "Continuum non raggiungibile — knowledge sola lettura".
- Funzionalità Alice non-knowledge (chat, voice, tool execution) restano operative.

## 8. Migration plan — gated da uso reale

> **Niente date.** Si procede solo quando le metriche del passo precedente sono verdi per
> almeno 2-4 settimane di uso reale.

### Step 0 — Prerequisiti
- Fase 1 done: `KnowledgeBackend` esiste, `QdrantBackend` funziona e tutti i plugin lo consumano.
- Fase 2 done: Continuum API v1 stabile, SDK Python disponibile, server containerizzato.

### Step 1 — Spike di validazione (giorni)
- Script Python isolato che:
  - Crea 100 note via API,
  - Esegue 50 search,
  - Misura latenza p50/p95.
- Gate: latenza search ≤ 200ms p95 in locale.

### Step 2 — `ContinuumBackend` implementato (settimana)
- Adapter completo con circuit breaker, trace ID, outbox per le scritture.
- Suite test contro Continuum reale (in CI: docker-compose up + tests).

### Step 3 — Shadow mode (settimane)
- Config `knowledge.shadow_backend: "continuum"`.
- Ogni read va a `qdrant` (autoritativo) **e** in parallelo a Continuum.
- I risultati vengono confrontati e diff loggato (no impatto utente).
- Gate: zero divergenze inattese per 1 settimana.

### Step 4 — Dual write (settimane)
- Le scritture vanno a entrambi i backend.
- Le letture restano su `qdrant`.
- Permette di popolare Continuum senza rischio.
- **Importante**: contenuti già esistenti in Qdrant vanno migrati con script one-shot (`backend/scripts/migrate_qdrant_to_continuum.py`) — non auto-migrati al volo per evitare carichi imprevedibili.
- Gate: nessun errore di scrittura per 2 settimane + migrazione one-shot completata.

### Step 5 — Switch primary (con fallback)
- `knowledge.default_backend: "continuum"`.
- `knowledge.fallback.on_unavailable: "fallback_qdrant"`.
- `qdrant` resta come hot standby (write+read in shadow).
- Gate: ≥ 4 settimane di uso reale senza regressioni → procedi a Step 6.

### Step 6 — Rimozione legacy
- Disabilita `QdrantBackend` per i `kind` migrati (note, memory long-term, fact).
- **`QdrantBackend` resta attivo SOLO per `session_memory`** (working memory dell'agente — non va in Continuum).
- Marca `note_service.py` e parte long-term di `MemoryService` come deprecated.
- Una release dopo: rimuovi codice, droppa collezioni Qdrant `notes` e parte long-term di `memory`. La collezione `memory` resta per session-scope.

### Rollback
A qualunque step, rollback = cambio della config `knowledge.default_backend`.
Niente è irreversibile fino allo Step 6.

## 9. Cambiamenti contrattuali nel codice Alice

### Plugin `notes` — esempio post-refactor

```python
# backend/plugins/notes/plugin.py (semplificato)
class NotesPlugin(BasePlugin):
    async def execute_tool(self, tool: str, args: dict, ctx) -> ToolResult:
        kb: KnowledgeBackend = ctx.knowledge   # iniettato da AppContext
        if tool == "create_note":
            doc = await kb.create(KnowledgeDocCreate(
                kind="note",
                title=args["title"],
                content=args["content"],
                tags=args.get("tags", []),
                metadata={"alice_user_confirmed": True},
            ))
            return ToolResult.ok({"id": doc.id})
        if tool == "search_notes":
            hits = await kb.search(args["query"], k=args.get("k", 5))
            return ToolResult.ok({"hits": [h.to_dict() for h in hits]})
        ...
```

### `AppContext` esteso

```python
@dataclass
class AppContext:
    config: Config
    event_bus: EventBus
    plugin_manager: PluginManager
    tool_registry: ToolRegistry
    llm: LLMService
    # nuovo:
    knowledge: KnowledgeBackend           # iniettato dal router
    knowledge_router: KnowledgeRouter     # se routing per kind attivo
```

### Memory injection nel system prompt
- Sostituire la chiamata `memory_service.search(...)` nella chat route con `knowledge.search(...)`.
- Filtri: `kind in ["fact", "memory", "note"]` per restare in tema knowledge.
- Conversation history continua a leggere da SQLModel (NON cambia).

## 10. UX desktop dell'integrazione

### Scenario quotidiano
1. Utente avvia **Alice Desktop** (icona app).
2. Alice lancia (se config `continuum.mode: "embedded"`) il backend Continuum in background via Docker.
3. Alice fa health check su Continuum, mostra LED verde nel service panel.
4. Se Continuum down → banner "Knowledge offline", chat funziona comunque.
5. L'utente può aprire **Continuum Desktop** (icona separata) per editare note ricche, vedere grafo, ecc.
6. Modifiche fatte in Continuum → Alice le vede live (search aggiornata) perché legge dal DB autoritativo.
7. Modifiche fatte da Alice (es. "ricordati che X") → compaiono in Continuum filtrabili per `tag:alice/auto`.

### Settings UI Alice
Sezione "Knowledge":
- Toggle backend (Continuum / sqlite-vec / disabled).
- URL Continuum (default `http://localhost:3001`).
- Token auth.
- Health badge.
- Bottone "Test connection".
- Slider `similarity_threshold`, `top_k`.
- Lista pending in outbox (se ci sono scritture queued).

## 11. Definition of Done — Fase 3

- [ ] `KnowledgeBackend` ha 2 implementazioni testate (`QdrantBackend`, `ContinuumBackend`).
- [ ] `KnowledgeRouter` instrada per `kind` come da config.
- [ ] Plugin `notes` e `memory` consumano solo `KnowledgeBackend`.
- [ ] Outbox pattern per scritture, con retry automatico.
- [ ] Trace ID end-to-end nei log di entrambi i sistemi.
- [ ] Circuit breaker funzionante (test: spegni Continuum, verifica degraded mode).
- [ ] Migration completata fino a Step 5 (Continuum primary, sqlite-vec hot standby).
- [ ] UX: utente non vede mai un crash quando Continuum è offline.
- [ ] Documentazione policy memoria pubblicata + presente nel system prompt LLM.

## 12. Trade-off espliciti

| Scelta | Pro | Contro |
|---|---|---|
| `KnowledgeBackend` con 2 impl | Optionality, rollback gratuito | Astrazione in più, codice ~+15% |
| Migration gated da uso reale | Rischio minimo | Tempi non prevedibili |
| Outbox pattern per scritture | Niente perdita dati se Continuum cade | Complessità aggiuntiva, sync resolution |
| Trace ID custom (no OpenTelemetry) | Zero dipendenze pesanti | Migrazione a OTel futura richiede refactor |
| Routing per `kind` | Granularità fine (cosa va dove) | Config più complessa |
| Continuum gestito da Alice in modalità embedded | UX seamless | Alice diventa "process supervisor" |

## 13. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Latenza HTTP fa rallentare la chat | Cache search in-memory (TTL 30s); precompute per query ripetute |
| Schema Note di Continuum cambia | Versioning API + SDK rigenerato + test contract; manteniamo solo v1 finché stabile |
| Outbox accumula troppe scritture (Continuum down per giorni) | Cap dimensione + alert utente + dump esportabile |
| Embeddings divergono (Alice e Continuum usano modelli diversi) | Continuum è autoritativo per gli embed dei contenuti che ospita; Alice non re-embedda |
| Trace ID non propagato da qualche path | Test E2E che verifica presenza header in ogni route |
| Conflitto tra modifiche Alice-side e Continuum-side | Last-write-wins sul `updated_at`; UI conflict resolution rinviata |
| L'LLM scrive troppe note auto | Filtro `metadata.alice_user_confirmed=true` come default per la search ufficiale; il resto va in "inbox" |

## 14. Cosa resta esplicitamente fuori da Fase 3

- **Sync conversation history in Continuum**: voluto in futuro per "ricerca semantica sulle chat"
  ma è Fase 4. Richiede entity dedicata in Continuum.
- **Multi-device sync**: presuppone Continuum esposto in rete + auth multi-utente.
- **Embeddings condivisi cross-app** (Alice usa stessi embed di altre app): non utile finché Alice è l'unico client.
- **Real-time pub/sub**: rinviato finché non c'è caso d'uso (es. notifiche push da Continuum).

## 15. Checklist sintetica di verifica architetturale

- ✅ Sistemi separati (repo, processi, lifecycle).
- ✅ Continuum non sa di Alice (Alice è source-app opaco).
- ✅ Nessun accesso DB diretto.
- ✅ Nessuna sync bidirezionale.
- ✅ Embeddings: un contenuto, un sistema, un vettore.
- ✅ Astrazione `KnowledgeBackend` permette swap implementazione.
- ✅ Migrazione reversibile fino allo Step 6.
- ✅ Degraded mode robusto (Continuum offline ≠ Alice offline).
- ✅ Trace ID end-to-end.
- ✅ Policy di routing dichiarata in config + nel system prompt.
- ✅ UX desktop: utente non tocca Docker/CLI.
