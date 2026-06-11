# Risanamento architetturale di AL\CE — Design

**Data:** 2026-06-10
**Stato:** approvato dall'utente (conversazione di brainstorming), in attesa di piano di implementazione
**Scope:** intero programma (backend + frontend); `continuum/` e i server Trellis restano progetti separati consumati via HTTP

---

## 1. Contesto e problema

Il programma è cresciuto bottom-up, feature per feature, senza un disegno d'insieme: ogni
feature ha portato la propria persistenza, le proprie route, il proprio store e i propri tipi.
I singoli componenti sono solidi (turn engine, permessi/scope, sistema plugin), ma la **colla**
tra loro manca di disegno. Un audit del codebase (2026-06-10) ha individuato le incoerenze
strutturali; le cinque più gravi:

1. **Tre sistemi paralleli di "artefatti"** — chart (`plugins/chart_generator/chart_store.py`),
   whiteboard (`plugins/whiteboard/store.py`) e modelli 3D (`services/artifacts/registry.py`)
   hanno ciascuno store, route REST e tipi frontend propri. Nessun modello unificato di contenuto.
2. **`AppContext` god object** — 61 campi piatti (`core/context.py`); lifespan di avvio da 900+
   righe (`core/app.py`) con ordine di inizializzazione implicito e fragile.
3. **Conversazioni in due posti** — SQLite **e** mirror JSON automatico
   (`services/conversation_file_manager.py`), senza coordinamento transazionale.
4. **Memoria/conoscenza su 6 strati** — `memory_service`, plugin memory, route REST memory,
   `CompositeKnowledgeBackend`, `ContinuumBackend`, plugin continuum; nessun punto d'ingresso unico.
5. **Confine FE↔BE tenuto a mano** — 18 file di tipi TS che rispecchiano a mano modelli Pydantic
   sparsi in 34 file di route; `api.ts` piatto da ~1.000 righe; due WebSocket senza schema condiviso.
   Ogni feature richiede 4 modifiche sincronizzate senza alcuna verifica automatica.

Debiti secondari censiti: `tool_registry.py` (1.182 righe: catalogo + dedup + policy permessi
mescolati), `llm_service.py` (1.693 righe: client + composizione prompt + selezione capability),
40+ flag `enabled` in config di cui diversi morti, naming eventi WS incoerente
(`calendar_changed` vs `mcp.server.connected`), route che importano internals dei plugin
(es. `api/routes/mcp.py` importa `McpClientPlugin`), UI orb-era legacy che convive con Horizon.

## 2. Obiettivi e vincoli (decisioni prese)

| Decisione | Scelta |
|---|---|
| Obiettivo | Sistemico: estensibilità + affidabilità + coerenza concettuale |
| Modalità | **Incrementale**: app funzionante e mergiabile a ogni fase, nessun freeze |
| Dati esistenti | **Azzerabili**: niente migrazioni di dati (conversazioni, memorie, artefatti) |
| UI legacy | **Eliminata**: Horizon unica superficie assistente |
| Contratti FE↔BE | **Codegen completo**: tipi REST generati da OpenAPI + schema generato per i WS |
| Visione prodotto | **Runtime agentico locale** stile Claude Desktop: lavori agentici e comportamenti Jarvis-like; l'agente può invocare le funzioni del programma stesso, nei limiti consentiti |

## 3. Visione

AL\CE è un **runtime agentico locale**: un kernel che esegue turni (LLM + tool loop + permessi
+ scope) e, attorno, periferiche che gli danno:

- **capacità** — plugin/tools;
- **sensi** — eventi (email, calendario, voce, sistema);
- **memoria** — knowledge service;
- **superfici** — Horizon, voce, notifiche;
- **mani sul programma stesso** — il Command Layer (l'agente pilota la UI e le funzioni dell'app).

Tutto ciò che non è il kernel è una periferica del kernel. Ogni scelta architetturale si giudica
con questo criterio.

## 4. Principi normativi (la "costituzione")

Ogni futura PR si giudica contro questi principi. Le regole di enforcement (§9) li rendono
vincoli meccanici, non convenzioni.

1. **Una capability = un plugin = una sola implementazione.** I tools sono l'interfaccia primaria
   di ogni capability. Le route REST esistono solo per ciò che la UI deve fare fuori dal turno
   (gestione, CRUD, pannelli) e **delegano allo stesso service del plugin** — mai due
   implementazioni della stessa logica.
2. **Contratti generati, mai duplicati a mano.** Ogni route dichiara `response_model`; ogni
   messaggio WS è un modello Pydantic; ogni comando UI ha uno schema; i tipi TS sono artefatti
   generati. Il drift è un errore di compilazione.
3. **Una fonte di verità per ogni dato.** Niente mirror automatici; gli export sono comandi
   espliciti dell'utente.
4. **Dipendenze solo verso il basso e verso i protocolli.** `api → services → core`; i plugin
   dipendono dai `Protocol` del core, mai da altri plugin né da classi concrete; le route non
   importano internals dei plugin; nessun import da `continuum/` (solo `ContinuumClient` HTTP);
   Trellis solo via orchestrator.
5. **Autonomia sempre dentro i guardrail.** Qualunque comportamento proattivo/autonomo (trigger,
   voce, subagent, comandi app) passa dagli stessi gate (scope + permission mode + audit) di un
   turno richiesto dall'utente. Nessun percorso privilegiato.

## 5. Architettura target — backend

### 5.1 Kernel agentico

Il kernel = turn engine (`DirectTurnExecutor` + `tool_loop`), tool registry, permission/scope,
event bus. Interventi:

- **`AppContext` decomposto in 5 gruppi coesi**, tipati su protocolli:
  - `InferenceServices` — llm, stt, tts, embedding, model registry/downloader, vram monitor
  - `KnowledgeServices` — knowledge service, qdrant, memoria
  - `WorkspaceServices` — scope, permission mode/rules/service, terminal
  - `ConversationServices` — db, persistenza conversazioni, context manager
  - `PlatformServices` — event bus, config service, ws manager, plugin manager, orchestrator
  `AppContext` resta come radice sottile che aggrega i gruppi; i consumatori dichiarano il gruppo
  che usano, rendendo leggibili le dipendenze reali.
- **Bootstrap dichiarativo**: il lifespan diventa una sequenza di *stage* espliciti
  (config → db → inference → knowledge → workspace → plugins → routes), ognuno una funzione che
  riceve ciò che lo stage precedente ha prodotto. L'ordine di init smette di essere implicito.
- **Split di `tool_registry`**: *catalogo* (cosa esiste: definizioni, lookup, dedup) separato
  dalla *policy* (cosa è permesso: capability tag, gating). Il Command Layer (§7) si aggancia
  alla policy.
- **Split di `llm_service`**: client LLM, composizione prompt e selezione capability diventano
  moduli distinti.
- **Censimento flag**: i 40+ booleani `enabled` in config vengono censiti; i morti (sempre
  true/mai letti) eliminati, i vivi registrati in un registro flag unico.

### 5.2 Persistenza e contenuti

- **SQLite unica fonte di verità** per conversazioni e metadati. Il mirror JSON automatico
  (`ConversationFileManager`) viene rimosso; al suo posto un comando di export/backup esplicito
  (tool + voce UI). I dati esistenti si azzerano (deciso, niente migrazioni).
- **Modello unificato dei contenuti**: chart, whiteboard, modelli 3D/CAD e futuri output diventano
  *kind* di un solo `Artifact` — metadati nel DB (id, kind, titolo, conversazione di origine,
  timestamps), blob su disco in `data/artifacts/<kind>/`. Un solo registry (generalizzazione
  dell'`ArtifactRegistry` esistente), una sola famiglia di route `/api/artifacts`, un solo store
  frontend con viewer per kind. `ChartStore` e `WhiteboardStore` vengono assorbiti ed eliminati.
- **Conoscenza con un solo ingresso**: `KnowledgeService` come unico punto d'accesso (sopra il
  `CompositeKnowledgeBackend`). Il plugin memory diventa un guscio sottile di tools; le route
  memory delegano allo stesso service; il client Continuum è istanziato una volta sola nel wiring.
  Da 6 strati a 3: *tools/route → KnowledgeService → backend componibili*.

## 6. Contratti e comunicazione FE↔BE

- **REST**: ogni endpoint con modelli Pydantic espliciti (request e `response_model`), raccolti
  per dominio. Convenzione di risposta unica per le liste — `{items: [...], total: int}` — al
  posto degli idiomi attuali misti (`entries`/`items`/`data`).
  Pipeline: script che genera `openapi.json` **offline** (importa la factory FastAPI, nessun
  server in esecuzione richiesto) → `openapi-typescript` → `types/generated/api.d.ts` →
  `npm run gen:api`.
- **WS**: restano **due canali con ruoli netti** — `chat` (streaming del turno: token, thinking,
  tool call) ed `events` (asincrono di background). **Envelope unico per entrambi fin dal giorno
  1**: piatto — `{type, origin, correlation_id?, ...campi}` con `origin ∈ {user, agent, system}`
  (deciso in 1b: nessun wrapper `payload`, stessa garanzia e zero migrazione doppia).
  Ogni messaggio è un modello Pydantic in `backend/api/ws_schema/`; da lì JSON Schema → tipi TS
  come **unione discriminata su `type`**. Naming eventi migrato alla convenzione unica
  `dominio.azione`.
- **Frontend**: `api.ts` sostituito da client per dominio (`services/api/<dominio>.ts`) sui tipi
  generati; `useEventsWebSocket` diventa un dispatcher tipizzato (mappa esaustiva
  `type → handler`: evento non gestito = errore di compilazione).

## 7. Command Layer — l'agente pilota il programma

Pattern VS Code: **ogni funzione del programma è un comando** con nome, schema parametri tipizzato
e *capability tag* (`navigation` | `read` | `mutate` | `destructive`), registrato in un
**Command Registry** nel frontend (`view.switch`, `panel.open`, `conversation.open`,
`artifact.show`, `settings.get`, …). UI e agente invocano **gli stessi comandi**: una sola
implementazione per funzione.

Catena di esecuzione:

1. **Frontend** registra i comandi; all'avvio (e a ogni cambiamento) invia al backend il
   **manifest** dei comandi disponibili — un contratto validato, nella stessa pipeline di schemi
   generati (§6).
2. **Backend** espone il tool `app_command(name, args)` (di proprietà del kernel, non di un plugin
   qualsiasi): inoltra al frontend via events-WS con `correlation_id`, attende la risposta con
   timeout, restituisce un normale `ToolResult` al loop.
3. **Gating**: i comandi passano dagli stessi guardrail dei tool — permission mode (in `plan`
   solo `read`/`navigation`; `mutate` con conferma in `strict`; ecc.), allowlist configurabile
   per comando, audit nel turn engine.

### Punti critici chiusi by-design

- **RPC backend→frontend è un seam nuovo** (oggi i WS sono push-only): correlation id, timeout e
  semantica di fallimento esplicita. Se la UI è chiusa/minimizzata (turni autonomi), il tool
  ritorna "UI non disponibile" come risultato pulito, non un'eccezione.
- **Invariante anti-escalation (non negoziabile)**: l'agente **non può mai alzare i propri
  permessi**. I comandi che toccano permission mode, scope, allowlist, conferme e config dei
  guardrail sono **strutturalmente esclusi** dal manifest esposto all'agente — non registrabili
  come agent-callable, non semplicemente vietati da config.
- **Loop di eco**: ogni evento e comando porta `origin`; il TriggerService (§8) ignora di default
  ciò che origina dall'agente. Circuit breaker autopilot già esistente.
- **Drift del manifest**: il manifest è il *terzo contratto* (oltre REST e WS) e vive nella stessa
  pipeline di generazione/validazione.

## 8. Fondamenta Jarvis (punti di estensione agentici)

Si posano le interfacce, non le implementazioni ricche — quelle arrivano dopo il risanamento:

- **`TriggerService`**: avvia turni autonomi da (a) schedulazioni cron-like, (b) eventi del bus
  (email arrivata, evento calendario imminente), (c) hotword/voce. Un turno autonomo è un turno
  normale: stessa pipeline, scope e permission mode della conversazione a cui appartiene. Filtro
  di default su `origin=agent` per evitare auto-innesco.
- **Task in background osservabili**: subagent e piani esistono già; si formalizza il *task in
  background* con eventi tipizzati di avanzamento, osservabile da Horizon (store `tasks`).
- **`AttentionService`**: unico punto di decisione per l'iniziativa verso l'utente (interrompere,
  notificare, accodare) — il "Jarvis che parla da solo" ha un controllo centrale e disattivabile.
- **Voce e subagent** passano dallo stesso tool/command gating del turno normale (oggi la voce ha
  cap separati, es. `voice.max_tools`: vanno ricondotti alla stessa policy).

## 9. Enforcement e testing (trasversale, non fase finale)

**Regola di processo: ogni fase consegna anche le proprie regole di enforcement.** Rimandare i
vincoli alla fine significa reintrodurre violazioni durante il refactor.

- **Layering Python**: `import-linter` in CI con i contratti del §4 (plugin↛plugin,
  route↛plugin-internals, services↛api, ban import `continuum/`).
- **Contratti**: job CI che rigenera tipi/schemi e fallisce se `git diff` non è pulito;
  `npm run typecheck` come gate; test che ogni endpoint dichiari `response_model`.
- **Errori**: gerarchia unica di eccezioni di dominio nel core, mappata in un punto solo dal
  middleware; gli eventi di errore WS seguono lo stesso schema tipizzato.
- **Criteri di uscita per ogni fase**: test verdi, typecheck FE, app avviabile, feature di
  riferimento del dominio toccato funzionante end-to-end.

## 10. Roadmap (8 fasi, ognuna mergiabile)

| # | Fase | Contenuto | Dipende da |
|---|---|---|---|
| 1 | **Contratti** | Codegen REST offline; `ws_schema` con envelope unico (`origin`, `correlation_id`); rinomina eventi a `dominio.azione`; gate CI codegen | — |
| 2 | **Persistenza** | SQLite unica fonte; rimozione mirror JSON; comando export esplicito | 1 |
| 3 | **Contenuti unificati** | `Artifact` generalizzato (kind); assorbimento chart/whiteboard; route e store unici | 1 |
| 4 | **Conoscenza** | `KnowledgeService` unico ingresso; plugin memory sottile; route deleganti | 1 |
| 5 | **Kernel** | AppContext in gruppi; bootstrap a stage; split tool_registry (catalogo/policy) e llm_service; censimento flag; import-linter | 1 |
| 6 | **Frontend** | Rimozione orb-era (Horizon unica superficie); client per dominio; dispatcher tipizzato; **Command Registry** (azioni UI come comandi) | 1, 3 |
| 7 | **Command Bridge** | Tool `app_command`; manifest come contratto; RPC correlation/timeout; gating + invariante anti-escalation | 5, 6 |
| 8 | **Fondamenta Jarvis** | `TriggerService` (filtro `origin`), `AttentionService`, task in background osservabili | 5, 7 |

Le fasi 2-4 sono parallele in linea di principio (tutte dipendono solo dalla 1); l'ordine elencato
è quello consigliato per leva e rischio crescente.

## 11. Fuori scope

- Internals di Continuum e dei server Trellis (progetti separati; si irrigidisce solo il confine).
- Nuove feature utente durante il risanamento (le fondamenta Jarvis definiscono interfacce, non
  comportamenti ricchi).
- Migrazioni dei dati esistenti (azzerabili per decisione).
- Riscrittura di logica di dominio funzionante (si sposta/consolida, non si riscrive).
