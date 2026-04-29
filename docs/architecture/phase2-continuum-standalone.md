# FASE 2 — Continuum standalone

> Obiettivo: Continuum diventa una **knowledge base generica multi-client**, indipendente da
> Alice. API stabile, schema entity dichiarato, packaging Docker auto-avviabile, contratti
> pubblici. Alice è uno dei tanti client possibili (CLI, web app, futuro mobile, altri agenti).

## 1. Posizionamento

Continuum NON è "il database di Alice". È un'app a sé:
- ha la sua UI (web + Electron) per consultare/editare la knowledge,
- ha le sue API che chiunque può consumare,
- non contiene **nessuna** logica specifica di Alice.

Conseguenza: lo sviluppo di Continuum non viene guidato dai bisogni di Alice. Alice si adatta a
quello che Continuum espone. Se Alice ha bisogno di qualcosa di specifico → lo costruisce
*sopra* le API di Continuum, non *dentro* Continuum.

## 2. Stato attuale verificato (29 aprile 2026)

Ispezione di [continuum/server/src/index.ts](../../continuum/server/src/index.ts):

**Già esistente** (verificato in [continuum/server/src/routes/notes.ts](../../continuum/server/src/routes/notes.ts), [routes/links.ts](../../continuum/server/src/routes/links.ts), [db/schema.ts](../../continuum/server/src/db/schema.ts)):
- Routes: `/api/ai/*`, `/api/notes` (CRUD), `/api/notes/search` **(hybrid semantic + lexical boost su titolo/tag)**, `/api/notes/:id/backlinks`, `/api/notes/admin/reembed`, `/api/links` (CRUD), **`/api/links/graph` (nodes + edges aggregati per visualizzazione)**, `/api/links/by-note/:id`, `/api/kinds` (CRUD con builtin protection).
- `/health` (basic).
- AI Provider Manager (LM Studio primario + Ollama fallback).
- pgvector + Drizzle ORM + **chunking** (tabella `embeddings` separata da `notes`, una nota ha N chunks; search con `DISTINCT ON (note_id)` per il best chunk).
- Auto-reembed fire-and-forget su `POST/PUT /api/notes`.
- **Tabella `kinds`** con builtin protection (kind `note` immutabile, altri user-defined con slug, color, icon).
- **Tabella `documents`** per Y.Doc binary state (Hocuspocus persistence).
- **Hocuspocus** già attivo (collab Y.js) — non è feature futura.
- `docker-compose.yml` con Postgres + Redis + MinIO.

**Schema `notes` attuale** (verificato in [db/schema.ts](../../continuum/server/src/db/schema.ts)):
```ts
{ id: uuid, title: text, kind: text='note', content: text='',
  contentJson: jsonb, tags: jsonb<string[]>=[], createdAt, updatedAt }
```
> **Importante**: lo schema **NON ha** `metadata`, `source`, `embedded_at`. L'entity `Note` proposta in questo piano (sezione 5) richiede una **drizzle migration** che aggiunga questi campi. Va pianificata come prima migration di Fase 2.

**Da costruire in Fase 2**:
- **Drizzle migration** per aggiungere a `notes`: `metadata jsonb`, `source jsonb`, `embedded_at timestamp` (necessari per supportare le convenzioni cross-app definite in Fase 3).
- Versioning API: migrazione `/api/...` → `/api/v1/...` (breaking change pianificato).
- Endpoint `/api/v1/assets/*` (MinIO è nel compose ma **nessun import S3 nel server**, da implementare da zero).
- `/api/v1/health/deep` (controllo Postgres+Redis+MinIO+AI provider).
- Filtri estesi su `/notes/search` (oggi accetta solo `query` + `limit`; aggiungere `tag`, `kind`, `date_range`).
- **Containerizzazione del server Fastify** stesso (oggi gira via `pnpm dev`, non in compose).
- SDK Python (`continuum-client-py`).
- OpenAPI spec auto-generata.

## 3. Scope esplicito

### IN scope (per arrivare a "v1 stabile")
- API REST `v1` versionata e congelata (contratto pubblico).
- Migrazione delle route attuali sotto `/api/v1/` con redirect/deprecation di `/api/` per ≥ 3 mesi.
- Schema entity dichiarato: `Note`, `Tag`, `Link`, `Asset`, `Kind`.
- RAG search esposta come endpoint dedicato (`POST /api/v1/notes/search`).
- File storage via MinIO con presigned URLs (nuovo).
- Health endpoints diagnostici (`/health`, `/api/v1/health/deep`).
- **Containerizzazione completa**: server Fastify aggiunto al compose (Dockerfile + service `continuum-server`).
- Packaging Docker Compose **auto-avviabile** (`docker compose up` = tutto pronto, **incluso** il server).
- SDK generato: `@continuum/client-ts` + `continuum-client-py`.
- Auth locale-only (token statico in `.env`) — sufficiente per uso desktop personale.

### OUT of scope (rinviato)
- Multi-utente, ACL fine-grained, cloud sync.
- MCP server (ottimizzazione: viene aggiunto **dopo** REST stabile).
- Editor TipTap (UI feature, non bloccante).
- Grafo Sigma frontend (UI feature; le API `/graph` sì, la UI no).
- Authentication OAuth/SSO.

## 4. Decisione: REST first, MCP poi (e perché)

**REST resta il trasporto canonico.** MCP arriva come **adapter aggiuntivo** che riusa le
stesse route Fastify internamente.

| Aspetto | REST | MCP |
|---|---|---|
| Maturità ecosystem | Universale | Giovane, in evoluzione |
| Client supportati | Qualunque | Solo client MCP |
| Type safety | OpenAPI/Zod | JSON-RPC + schema |
| Tool descriptions per LLM | Manuali | Automatiche |
| Streaming | SSE/WebSocket | Sì |
| Adatto a Alice | Sì | Sì (ottimo) |
| Adatto a CLI/scripts | Sì | Awkward |

**Conclusione**: REST è il contratto principale. MCP server espone un sottoinsieme delle route
REST come MCP tools, per benefit specifico ad Alice (tool definitions automatiche per LLM).

### Architettura interna Continuum

```
                ┌──────────────────┐
                │   Domain layer   │   (services: NoteService, EmbeddingService, …)
                └────────┬─────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
   ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
   │ REST API  │   │ MCP server│   │  CLI tool │
   │ (Fastify) │   │ (futuro)  │   │ (futuro)  │
   └───────────┘   └───────────┘   └───────────┘
```

Tutti i transport delegano allo stesso domain layer. Zero logica duplicata.

## 5. API REST — contratto v1

> **Stato**: la maggior parte delle route esistono già (`/api/notes` CRUD, `/api/notes/search` con hybrid+chunking, `/api/notes/:id/backlinks`, `/api/links`, `/api/kinds`, `/api/notes/admin/reembed`). Le **nuove** sono `/assets/*`, `/graph` aggregato, `/health/deep`, e i filtri estesi su `/notes/search`. La migrazione sotto `/api/v1/` è breaking ma necessaria per stabilità.

### Risorse principali

```
GET    /api/v1/notes                  ?tag=&kind=&q=&limit=&cursor=
POST   /api/v1/notes                  body: NoteCreate
GET    /api/v1/notes/:id
PUT    /api/v1/notes/:id              body: NotePatch (partial update)
DELETE /api/v1/notes/:id

POST   /api/v1/notes/search           body: { query, k, filters }   → RAG semantic
POST   /api/v1/notes/:id/links        body: { target_id, kind }
GET    /api/v1/notes/:id/backlinks

GET    /api/v1/tags
GET    /api/v1/graph                  ?root=&depth=                 → nodes + edges

POST   /api/v1/assets                 multipart upload → MinIO
GET    /api/v1/assets/:id             → presigned URL

GET    /api/v1/health
GET    /api/v1/health/deep            → DB, Redis, MinIO, embedding provider
```

### Schema entity (Zod / Drizzle)

**Stato attuale** (`notes` table in [db/schema.ts](../../continuum/server/src/db/schema.ts)):
```ts
{ id, title, kind, content, contentJson, tags, createdAt, updatedAt }
```

**Target v1** (richiede migration drizzle):
```ts
type Note = {
  id: string;                    // UUID v4 (già)
  kind: string;                  // FK → kinds.id (default 'note', già)
  title: string;
  content: string;               // Markdown
  contentJson: object | null;    // TipTap JSON (già)
  tags: string[];                // jsonb (già)
  metadata: Record<string, unknown>;        // **NUOVO** — free-form, campi riservati documentati
  source: { app: string; version: string; user_id?: string } | null;  // **NUOVO**
  embeddedAt: string | null;     // **NUOVO** — ultima reembed
  createdAt: string;             // già
  updatedAt: string;             // già
};
```

> Le route esistenti vanno aggiornate per accettare/restituire `metadata`, `source`, `embeddedAt`. Migration drizzle è **non-breaking** se i nuovi campi sono nullable.

### Versioning
- Path-based: `/api/v1/...`. Breaking change → `/api/v2/...`, `v1` mantenuta ≥ 6 mesi.
- Header `Continuum-Api-Version: 1` ritornato in ogni risposta.
- OpenAPI spec generata da Fastify, pubblicata in `/api/v1/openapi.json`.

### Errori normalizzati
```json
{ "error": { "code": "NOT_FOUND", "message": "...", "trace_id": "..." } }
```

## 6. Embeddings & RAG

- **Continuum è autoritativo per gli embeddings dei contenuti che ospita.**
- Provider configurabile (LM Studio primario, Ollama fallback — già implementato).
- Re-embedding triggers:
  - `POST /notes` o `PUT /notes/:id` con cambio di `content` (fire-and-forget, già gestito).
  - Cambio modello embedding → endpoint `POST /api/v1/notes/admin/reembed` (già esistente).
- Index: pgvector HNSW cosine (già scelto).
- **Chunking**: **già implementato** — tabella `embeddings` separata da `notes`, N chunk per nota; search con `DISTINCT ON (note_id)` per best chunk. In v1 nessun lavoro richiesto; tuning di size/overlap è ottimizzazione futura.
- Search: hybrid semantic (pgvector cosine) + boost lessicale su titolo/tag — vedi `/notes/search` esistente.

## 7. File storage (MinIO)

> **Stato**: MinIO è nel compose ma **nessuna route Fastify** lo usa ancora. Da costruire da zero.

- Bucket: `continuum-assets`.
- Asset linkati a note via `metadata.attachments: ["asset_id1", ...]`.
- Upload: client → presigned PUT URL ottenuto da `POST /api/v1/assets/intent`.
- Download: presigned GET URL con TTL breve (es. 5 min).

## 8. Eventi (futuro, non v1)

> **Nota**: Hocuspocus è già attivo per collab Y.js sui documenti. È un canale separato dagli "eventi knowledge" qui descritti, e resta com'è.

Continuum **non** espone bus pub/sub esterno in v1. Internamente Redis è usato per cache.
Se in Fase 3 servirà reattività (es. Alice notificata di nuove note), si esporrà:

```
GET /api/v1/events/stream  (SSE)   → eventi: note.created, note.updated, …
```

Decisione esplicita: **niente eventi finché non c'è un consumer concreto.**

## 9. Auth & multi-tenancy

- **v1**: single-user locale. Token statico in `.env`, header `Authorization: Bearer <token>`.
- **v2**: opzionale, OAuth/PKCE se Continuum diventa accessibile in rete locale (uso multi-device).

## 10. Packaging & deploy

### Obiettivo UX
> L'utente non deve sapere cosa è Docker.

### Implementazione
- **Continuum Desktop** (Electron) embedda:
  - L'UI web,
  - Un **process manager** che gestisce `docker compose up/down` per Postgres/Redis/MinIO **+ il server Fastify** (containerizzato in Fase 2),
  - Hocuspocus come servizio interno al container del server (già wired in `index.ts`).
- All'avvio: verifica Docker Desktop installato → se no, prompt con link installazione.
- `docker-compose.yml` shipato dentro l'app, volume in `%LOCALAPPDATA%\Continuum\data\`.

> **Nota su Docker Desktop**: dipendenza pesante (~500MB, richiede WSL2). Alternativa valutata: Podman Desktop o `nerdctl` ma rendono l'UX peggiore. Per v1 si accetta Docker Desktop come prerequisito documentato.

### Profilo "headless" (per Alice)
Alice può dipendere da Continuum in due modi:
- **(A) Continuum Desktop in esecuzione** — preferito, l'utente vede UI + dati.
- **(B) Solo backend Continuum**: container compose minimo lanciato da Alice come dipendenza.
  Caso d'uso: utente power non interessato alla UI di Continuum.

Configurazione Alice: `continuum.mode: ["desktop", "embedded", "external"]`.

## 11. SDK client

### TypeScript
- `@continuum/client-ts` — generato da OpenAPI con `openapi-typescript-codegen`.
- Pubblicato come pacchetto npm locale (workspace), poi su registry privato.

### Python
- `continuum-client-py` — generato con `openapi-python-client` o scritto a mano (≤ 300 righe).
- Path nel monorepo Continuum: `clients/python/`.
- Alice in Fase 3 dipenderà da questa libreria via `pip install -e ../continuum/clients/python`
  (durante sviluppo) o pacchetto wheel (a regime).

### Caratteristiche SDK
- Async-first.
- Retry con backoff su 5xx.
- Circuit breaker integrato.
- Propagazione `X-Trace-Id` header (vedi Fase 3, observability).

## 12. Observability lato Continuum

- Log strutturati (pino → JSON).
- Trace ID propagato: legge `X-Trace-Id` dall'header in ingresso, lo include nei log e nelle
  risposte (echo header).
- Metrics base: numero richieste per route, latenza p50/p95, embedding queue depth.
- Endpoint `/api/v1/health/deep` ritorna stato per ogni dipendenza (Postgres, Redis, MinIO, provider AI).

## 13. Definition of Done — Fase 2

- [ ] API `/api/v1/*` documentata via OpenAPI auto-generato.
- [ ] Vecchie route `/api/*` deprecate con header `Deprecation` e redirect → `/api/v1/*` (mantenute ≥ 3 mesi).
- [ ] Schema `Note` congelato e versionato (drizzle migration applicata).
- [ ] **Drizzle migration** applicata: `notes.metadata`, `notes.source`, `notes.embedded_at` aggiunti come nullable.
- [ ] Endpoint nuovi implementati: `/assets/*`, `/health/deep`.
- [ ] Filtri `tag`, `kind`, `date_range` aggiunti a `/notes/search`.
- [ ] Bucket MinIO `continuum-assets` creato automaticamente al boot del server.
- [ ] Test E2E: CRUD note, search RAG, upload/download asset, link/backlink.
- [ ] `docker compose up` parte da zero senza interventi manuali (initdb, migrations, bucket creation, **server containerizzato**).
- [ ] SDK TS + Python pubblicati e usati in almeno uno smoke test.
- [ ] Continuum Desktop installabile, gestisce ciclo Docker invisibile all'utente.
- [ ] Health endpoints completi.
- [ ] Trace ID end-to-end nei log (riceve `X-Trace-Id` o lo genera; lo include in tutte le response).

## 14. Trade-off espliciti

| Scelta | Pro | Contro |
|---|---|---|
| REST canonico, MCP secondario | Universale, debuggabile con curl | MCP arriva tardi (ma è ok) |
| Chunking già implementato | Buona recall su note lunghe out-of-the-box | Tuning size/overlap rinviato |
| Auth single-user token | Zero attrito | Non scalabile a multi-user (rinviato) |
| Continuum gestisce Docker dall'app | UX desktop pulita | Dipendenza pesante (Docker Desktop) |
| SDK generato da OpenAPI | Sempre allineato al server | Richiede pipeline di generazione |

## 15. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Schema Note instabile mentre arrivano feature | Marcare `metadata` come free-form, evolvere solo i campi top-level con migration |
| Re-embedding di tutto il vault è lento | Job asincrono con queue, progress endpoint |
| Docker Desktop non installato sull'utente | Detection + onboarding wizard con link; documentare prerequisito |
| Migrazione `/api/` → `/api/v1/` rompe client esistenti (incluso Alice in dev) | Periodo di overlap ≥ 3 mesi con header `Deprecation` + warning log |
| API v1 si rivela inadeguata | Mantenere v1 ≥ 6 mesi, introdurre v2 in parallelo |
| Containerizzare Fastify rompe l'accesso a `localhost:1234` (LM Studio) | Usare `host.docker.internal` (già documentato nel compose) + config `LMSTUDIO_BASE_URL` env |
| Performance pgvector con N grande | HNSW già configurato; quando servirà, partitioning per `kind` |
| Hocuspocus port (1234?) collide con LM Studio | Verificare config `HOCUSPOCUS_PORT` ≠ 1234; cambiarla se necessario |

## 16. Cosa Continuum NON deve fare (per restare neutrale)

- Non implementare logica di "agente" (no LLM tool loops, no tool execution).
- Non sapere chi è "Alice" — solo `source.app` come metadato opaco.
- Non fare classificazione automatica di tipo/categoria (lato client).
- Non gestire conversation history di chatbot (è memoria episodica, non knowledge).
