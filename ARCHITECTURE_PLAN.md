# Alice ↔ Continuum — Piano Architetturale

> Documento indice. I dettagli operativi sono nei file `docs/architecture/phase{1,2,3}-*.md`.
> Continuum è un progetto **separato**: si trova temporaneamente in `./continuum/` solo per
> facilitare l'analisi. Il piano assume che a regime viva in una repo dedicata.

## Obiettivo finale

Due applicazioni desktop locali, indipendenti, profondamente integrate:

- **Alice (Omnia)** — agente runtime: conversazione, voce, automazione, generazione, tool execution.
  Detiene **memoria episodica/operativa** (chat history, working memory, tool state).
- **Continuum** — knowledge base personale: notes, embeddings, RAG, file, grafo.
  È **single source of truth** della conoscenza dichiarativa dell'utente.
- **Integrazione**: Alice consuma Continuum via API/MCP. Continuum non sa nulla di Alice.

## Principi non negoziabili

1. **Nessuna sincronizzazione bidirezionale di DB.** Continuum è autoritativo per la knowledge.
2. **Nessun accesso diretto al DB di Continuum** da Alice. Solo HTTP/MCP.
3. **Nessuna duplicazione di embeddings** sullo stesso contenuto. Un contenuto = un vettore = un sistema.
4. **Disaccoppiamento via Adapter/Façade.** Cambiare il trasporto (REST → MCP) non deve toccare i plugin.
5. **Migrazione incrementale (Strangler Fig).** Mai big-bang, sempre fallback attivo finché il nuovo path non è validato.
6. **Optionality first.** Astrazione `KnowledgeBackend` con doppia implementazione finché Continuum non è battle-tested.
7. **Continuum è giovane.** Si assume REST come trasporto reale per mesi; MCP è opportunistico.

## Reality check — stato verificato del codice (29 aprile 2026)

Questo piano è stato scritto **dopo** ispezione diretta del codice. Punti accertati:

| Affermazione | Verificato in | Stato |
|---|---|---|
| Alice usa **Qdrant** per memoria/note (non sqlite-vec) | [backend/services/qdrant_service.py](backend/services/qdrant_service.py), [backend/services/memory_service.py](backend/services/memory_service.py), [backend/services/note_service.py](backend/services/note_service.py), `data/qdrant/` | ✅ |
| Plugin `mcp_client` esiste | [backend/plugins/mcp_client/plugin.py](backend/plugins/mcp_client/plugin.py) | ✅ |
| Plugin discovery è **statico** via `PLUGIN_REGISTRY` (PyInstaller-friendly) | [backend/core/plugin_manager.py](backend/core/plugin_manager.py) | ✅ |
| Config Alice usa `pydantic-settings` + YAML + env `ALICE_*` | [backend/core/config.py](backend/core/config.py) | ✅ — il refactor layered va costruito sopra |
| Continuum routes attuali | [continuum/server/src/index.ts](continuum/server/src/index.ts) | `/api/ai`, `/api/notes`, `/api/links`, `/api/kinds` — **nessun prefisso `/v1`** |
| Continuum search `/api/notes/search` | [continuum/server/src/routes/notes.ts](continuum/server/src/routes/notes.ts) | ✅ hybrid semantic+lexical, già funzionante |
| Continuum chunking embeddings | [continuum/server/src/db/schema.ts](continuum/server/src/db/schema.ts) | ✅ tabella `embeddings` separata, N chunks per nota |
| Continuum `/api/links/graph` (nodes+edges) | [continuum/server/src/routes/links.ts](continuum/server/src/routes/links.ts) | ✅ già esiste |
| Continuum schema `notes` ha `metadata`/`source`/`embedded_at` | [continuum/server/src/db/schema.ts](continuum/server/src/db/schema.ts) | ❌ **mancano** — richiede drizzle migration in Fase 2 |
| Continuum tabella `documents` per Y.Doc | [continuum/server/src/db/schema.ts](continuum/server/src/db/schema.ts) | ✅ (Hocuspocus persistence) |
| Continuum Hocuspocus collab | [continuum/server/src/index.ts](continuum/server/src/index.ts) | ✅ già attivo (non era "futuro") |
| Continuum docker-compose | [continuum/docker-compose.yml](continuum/docker-compose.yml) | Solo Postgres + Redis + MinIO. **Il server Fastify NON è containerizzato** (gira con `pnpm dev`) |
| Endpoint `/assets`, `/health/deep` | — | **Da implementare** in Fase 2 (non esistono oggi; MinIO è nel compose ma nessun import S3 nel server) |
| Versioning API `/api/v1/...` | — | **Da introdurre** in Fase 2 (oggi è `/api/...` senza versione) |

**Conseguenze di questi accertamenti** (riflesse nelle fasi):
- L'adapter "legacy" si chiama **`QdrantBackend`**, non `SqliteVecBackend`.
- Fase 2 include esplicitamente **versionamento API** (`/api/` → `/api/v1/`) come breaking change pianificato e **containerizzazione del server Fastify**.
- Hocuspocus è già un servizio attivo che il packaging Continuum deve gestire (non è feature futura).

## Pattern architetturali scelti

| Tema | Pattern | Motivo |
|---|---|---|
| Confine memoria | **CQRS-light** (knowledge dichiarativa vs episodica separate) | Nature diverse, lifecycle diversi |
| Trasporto | **Adapter / Hexagonal** (`KnowledgeBackend` Protocol) | Switch REST↔MCP senza toccare i consumer |
| Migrazione | **Strangler Fig** | Rollback sempre possibile |
| Resilienza | **Circuit breaker + degraded mode** | Continuum offline ≠ Alice offline |
| Trasporto runtime | **REST-first, MCP-when-ready** | MCP non ancora pronto in Continuum |
| Eventi | **Pull-only (no pub/sub iniziale)** | Evita complessità prematura; Redis events solo quando arriva un caso d'uso reale |

## Le 3 fasi

### [FASE 1 — Finalizzazione Alice](docs/architecture/phase1-alice-finalization.md)
Alice diventa un **applicativo desktop installabile** con orchestrazione completa dei servizi
(LLM, STT, TTS, Trellis, ecc.), lifecycle robusto, configurazione centralizzata, build &
distribuzione. La memoria episodica viene formalizzata e ripulita; quella long-term viene
**isolata dietro un'astrazione** in vista della Fase 3 (non rimossa).

**Output**: installer Windows, Alice avviabile dall'utente finale, zero comandi manuali.

### [FASE 2 — Continuum standalone](docs/architecture/phase2-continuum-standalone.md)
Continuum evolve come **knowledge base generica multi-client**: API REST stabile e versionata,
MCP server opzionale, schema entity dichiarato, contratti pubblici, packaging Docker
auto-avviabile. Nessuna logica specifica di Alice dentro Continuum.

**Output**: Continuum installabile/avviabile in standalone, API contract congelato `v1`,
SDK TypeScript+Python generato dallo schema.

### [FASE 3 — Integrazione Alice ↔ Continuum](docs/architecture/phase3-integration.md)
Wiring tra i due sistemi tramite `KnowledgeBackend` (Protocol Python con due implementazioni:
`SqliteVecBackend` legacy + `ContinuumBackend` nuovo). Switch via config. Policy di memoria
esplicita (cosa va dove). Correlation ID end-to-end. Migrazione gated da uso reale, non da
calendario. Rimozione di `NoteService`/`MemoryService.long_term` solo dopo validazione.

**Output**: Alice usa Continuum come cervello dichiarativo, mantenendo full fallback locale.

## Decisioni architetturali chiave (riepilogo)

| Decisione | Scelta | Alternativa scartata | Motivo |
|---|---|---|---|
| Pattern integrazione | `KnowledgeBackend` Protocol + 2 impl | Continuum SSoT diretto | Optionality, rollback gratuito |
| Trasporto v1 | REST/HTTP+JSON | MCP-first | MCP non ancora esposto da Continuum |
| Trasporto v2 | MCP via plugin `mcp_client` | REST forever | Tool definitions automatiche, type-safe |
| Adapter "legacy" Alice | **`QdrantBackend`** (Qdrant esistente) | sqlite-vec | Rispetta tech in-use |
| `NoteService` Alice | **Rimosso** dopo migrazione | Mantenuto in parallelo | Duplicato esatto di Continuum |
| `MemoryService` long-term | **Refattorizzato** dietro `KnowledgeBackend` | Rimosso subito | Continuum giovane, serve fallback |
| `MemoryService` session/TTL | **Mantenuto** in Alice | Spostato in Continuum | È working memory dell'agente |
| `EmbeddingClient` | **Mantenuto** per query runtime | Rimosso | Serve per intent classification, no persist |
| Eventi | **Polling/pull**, no pub/sub | Redis events | Caso d'uso reale ancora assente |
| Deploy Continuum | Container auto-managed da Alice | Docker manuale utente | UX desktop, niente terminale |
| Repo | **Separate** (Continuum estratto) | Monorepo | Continuum riusabile da altri client |

## Glossario rapido

- **Memoria dichiarativa** — fatti/contenuti che l'utente vuole conservare e ritrovare (note, lore, progetti).
- **Memoria episodica** — eventi e stato dell'agente (conversazioni, tool calls, working memory).
- **Knowledge backend** — interfaccia astratta che Alice usa per leggere/scrivere knowledge.
- **Adapter** — implementazione concreta di `KnowledgeBackend` (es. `ContinuumBackend`, `SqliteVecBackend`).
- **Strangler Fig** — pattern di migrazione: il nuovo cresce attorno al vecchio finché può sostituirlo.

## Stato di lettura suggerito

1. Questo documento (panoramica e principi).
2. [Fase 1](docs/architecture/phase1-alice-finalization.md) — è prerequisito delle altre.
3. [Fase 2](docs/architecture/phase2-continuum-standalone.md) — può procedere in parallelo a Fase 1.
4. [Fase 3](docs/architecture/phase3-integration.md) — richiede output di Fase 1 e Fase 2.
