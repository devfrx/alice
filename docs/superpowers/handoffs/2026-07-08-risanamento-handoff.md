# Handoff — Risanamento architetturale AL\CE (stato al 2026-07-08, post-Fase 4)

> Per la sessione che continua questo lavoro a contesto fresco/compattato. Contiene SOLO ciò che
> non è ricostruibile dal repo: stato, decisioni, gotchas pagati sul campo, recon da fare.
> Fonti di verità nel repo: spec e piani citati sotto. Questo file SOSTITUISCE la versione
> precedente (post-fase3, `2026-06-12-risanamento-handoff.md`); la storia è in git.

## Stato del programma

- **Spec normativa** (approvata): `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` — 8 fasi, principi §4, criteri §9. È LA fonte di verità.
- **Fasi 1a, 1b, 2, 3, 4: COMPLETE** — branch impilati NON mergiati e NON pushati per decisione utente
  (4 su 3 su 2 su 1b su 1a): `arch/fase1a-contratti-rest` → `arch/fase1b-ws-schema` →
  `arch/fase2-persistenza` → `arch/fase3-contenuti` → `arch/fase4-conoscenza` (24 commit).
- **Fase 4 (Conoscenza): COMPLETATA** — review finale di fase «Phase ready with notes», zero fix
  richiesti. Piano chiuso e veritiero con esiti review per task + verdetto finale + backlog:
  `docs/superpowers/plans/2026-07-01-fase4-conoscenza.md`.
- Pending esterni: chip/task `task_6c67e5a8` (fix suite lenta); CI `contracts.yml` MAI eseguita (parte al primo push).

## Cosa ha consegnato la Fase 4 (mappa rapida, dettagli nel piano)

- **Dominio conoscenza da 6 strati a 3**: *tools/route → KnowledgeService → backend componibili*.
  `KnowledgeService` (`services/knowledge/service.py`, export dal package): facade kind-dispatched sul
  `KnowledgeBackend` + 2 op admin memoria (`memory_stats`, `delete_all_memories`); property
  `memory_available` (pre-check per i 503) e `backend` (SOLO test di shape della factory).
  `KnowledgeServiceProtocol` in `services/knowledge/protocol.py`, alias in `core/protocols.py`.
- **Factory unica** `build_knowledge_service(continuum_enabled, memory_service, continuum_client)`:
  usata da lifespan (`core/app.py`) E repair runtime (`knowledge_init.py`). `ContinuumClient` costruito
  SOLO in `core/app.py:275`; fallback di knowledge_init e plugin continuum ELIMINATI.
- **`ctx.knowledge_backend` NON ESISTE PIÙ** (campo + alias `KnowledgeBackendProtocol` rimossi, Task 9);
  guardie grep provano l'invariante. `ctx.memory_service`/`ctx.qdrant_service` restano come internals
  di wiring/readiness/shutdown/tool-RAG (MAI consumati da plugin o route del dominio).
- **Plugin memory e note tools continuum**: gusci sottili; pattern uniforme "handler con
  `svc: KnowledgeServiceProtocol` narrowed dalla guardia" (11 handler, mypy 0 su entrambi i plugin).
- **Ratchet −19 (burn-down dominio COMPLETO)**: `/api/memory*` tipizzate e deleganti al service, lista
  `{items,total}` (schemi in `services/knowledge/schemas.py`, `MemoryEntryRead.from_doc`);
  `/api/knowledge/readiness` + `/api/vector-store*` tipizzate (modelli nei moduli route,
  `RagReadinessResponse` importato route→route); `/api/mcp/memory*` resta proxy MCP ma tipizzato
  (letture → `KGGraphResponse` tollerante con fallback grafo-vuoto+warning diagnostico; mutazioni →
  `KGMutationResponse {ok}` — il FE scarta i body e ricarica il grafo, verificato).
- **FE sui tipi generati**: `types/memory.ts` interamente re-export; `KGEntity/KGRelation/KGGraph` e
  `RagReadinessStatus/VectorStoreStats` re-export; `stores/memory.ts` su `items`; `formatDate`
  null-safe; `EntityCard` con `?? []`. Regen + check-contracts verdi.
- Gate di fase: 228 test mirati backend + contracts, typecheck FE 0, vitest 259/259, smoke e2e reale
  (readiness/stats/lista memoria con dati veri; search 500 solo a embedding giù = parità pre-fase).

## Decisioni registrate in Fase 4 (non rilitigare)

1. **`MemoryService` INVARIATO** (storage impl interno); admin ops passano dal service, non dal protocol backend.
2. **Lista REST = `{items,total}`; search resta `{results:[{entry,score}]}`** (convenzione §6 solo per liste).
3. **mcp_memory resta proxy MCP** fuori dal KnowledgeService (dominio esterno); mutazioni ack-only.
4. **503 SEMPRE dal pre-check `memory_available`**, mai dal RuntimeError del service.
5. **vector_store resta su `ctx.qdrant_service`** (admin infra, non dominio conoscenza).
6. Il 500 di `POST /api/memory/search` a embedding giù è parità pre-fase (la UI gate su readiness) → backlog.

## Prossimo lavoro: Fase 5 — Kernel (spec §5.1)

Da scrivere con `writing-plans` su branch `arch/fase5-kernel` (figlio di `arch/fase4-conoscenza`).
Requisiti spec: **AppContext decomposto in 5 gruppi coesi** (Inference/Knowledge/Workspace/Conversation/
Platform) con radice sottile; **bootstrap dichiarativo a stage**; **split `tool_registry`**
(catalogo vs policy) e **split `llm_service`** (client/prompt/capability); **censimento 40+ flag
`enabled`**; **import-linter in CI** (§9: plugin↛plugin, route↛plugin-internals, services↛api,
ban import `continuum/`).

Messaggio di kickoff della sessione (copiare tale e quale):
«leggi specs, piano ed handoff della skill superpowers e continuiamo l'implementazione. /using-superpowers»

### Recon fase 5 — note VERIFICATE dalla review finale di fase 4 (2026-07-08)

- **Consumer laterali di `memory_service`/`qdrant_service`** da piazzare nei gruppi:
  `rag_readiness.py:42` legge memory_service; `qdrant_service` letto da `vector_store.py`,
  `chat/_assembly.py:391` (gate tool-RAG), `chat/conversations.py:275`; shutdown chiude
  memory_service in `app.py:~776`. Un sotto-contesto "RAG-infra" è il fit naturale.
- **`repair_vector_store` muta 5 campi ctx in place** (`knowledge_init.py`): se la fase 5
  congela/namespace-izza i campi, questo percorso deve continuare a funzionare; uno swap atomico del
  sub-container chiuderebbe anche la finestra di concorrenza del repair (backlog fase 4, review finale).
- **`ctx.continuum_client`**: campo laterale (plugin continuum + knowledge_init); httpx per-request,
  nessun lifecycle di shutdown — solo placement.
- **`mcp_memory.py` → plugin_manager** (violazione §4 route↛plugin-internals, backlog fase 4): il
  service/protocol MCP di fase 5 dovrebbe assorbire anche i tre messaggi 503 di quella route.
- **`QdrantServiceProtocol` senza `in_memory`** (mypy attr-defined in vector_store) — protocol gap da
  chiudere quando si toccano i protocol.
- Il lifespan di `core/app.py` è ~800 righe con numerazione di fase storica nei commenti — il
  bootstrap a stage la sostituisce.

## Workflow collaudato (riusare così; raffinamenti fase 4 inclusi)

- Per fase: branch dedicato → `writing-plans` (codice VERBATIM, comandi esatti) → `subagent-driven-development`:
  implementer (sonnet; haiku per fix meccanici da prescrizione esatta) + spec reviewer (sonnet) + quality
  reviewer (modello top, SEMPRE) + fix loop → review finale di fase (modello top, range intero, angolo =
  coerenza cross-task) → branch resta impilato, handoff aggiornato.
- **Raffinamento fase 4**: i nit banali delle quality review (1-5 righe) li applica il CONTROLLER
  direttamente, verificando coi gate scoped — un fix-agent solo per fix multi-parte. Ha funzionato bene.
- Ogni fix di review aggiorna ANCHE il piano (esito per task, sempre); finding fuori task → backlog del piano.
- Le review hanno trovato cose vere anche in fase 4 (fixture 503 che testava il ramo inesistente in
  produzione, tipo FE falso su createKG*, mypy union-attr azzerabili col pattern svc, 2 incidenti EOL).
  NON saltare i cicli.
- Commit convenzionali + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Mai push senza richiesta.

## Gotchas (validi anche dopo la fase 4)

1. **Suite backend completa IMPRATICABILE** (fixture `app` ~25s/test). Verifica di fase = test mirati per
   dominio + `tests/contracts/`. Subagent avvisati di NON killare run lente (timeout 600s).
2. **`npm run lint` rotto repo-wide** → gate FE = `npx eslint <file toccati>` (solo ERRORI) + `npm run typecheck`.
3. **ruff/mypy con errori pre-esistenti** → scoped; file nuovi puliti; confrontare con `git show <base>:file`.
   N815 è ATTIVA (i camelCase MCP richiedono noqa mirati sui campi NUOVI, mai sui pre-esistenti).
4. **EOL: DUE incidenti in fase 4** (implementer ha flippato test_memory_api.py a CRLF; Write tool ha
   flippato mcpMemory.ts). Il repo è `i/lf` in index (con eccezioni). SEMPRE verificare
   `git ls-files --eol <file toccati>` al ritorno dei subagent; diff sospettosamente grande = flip EOL
   (`git diff --ignore-cr-at-eol --stat` per smascherarlo). MAI cmdlet PowerShell su file non-ASCII.
5. **Subagent**: prescrizioni ESATTE ai fix-agent e VERIFICARE IL DIFF al ritorno (`git show`); commit con
   due `-m`, trailer esatto, niente here-string.
6. **`check-contracts.ps1` DOPO il commit** (untracked = dirty). Regen SOLO nel task previsto: tra un task
   che cambia route e la regen, `test_openapi_export` resta rosso — non eseguirlo nei task intermedi.
7. **PowerShell 5.1**: niente `&&`; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`;
   il boot-check (`create_app`) va lanciato dalla REPO ROOT, non da `backend/`.
8. **`ToolResult.error()` riempie `error_message`, NON `content`** — i test sugli errori asserzionano
   `res.error_message`.
9. **Campi generati opzionali**: i tipi `ApiSchema` rendono OPZIONALI i campi con default backend →
   fallback `??` nei consumer, mai tipi a mano. I campi SENZA default restano required (usalo per pilotare
   l'opzionalità FE dal modello Pydantic).
10. **Contratti WS**: regole 1b invariate (modello in ws_schema + vocabolario congelato + dispatcher FE esaustivo).
11. **Session limit dei subagent**: un reviewer è morto a metà con output vuoto (limite sessione) — se il
    result non contiene verifiche concrete, RILANCIARE con lo stesso mandato.

## Backlog (in fondo ai piani 1a/1b/2/3/4; voci fase 4 principali)

1. Burn-down ratchet residuo nelle fasi 5-6 per gli altri domini (`{items,total}` per le liste).
2. (fase 4) Test invariante repair; finestra di concorrenza repair (fix strutturale in fase 5);
   gate `_client` sui note tool; `RagReadinessResponse.from_readiness` + grafie; `memory.spec.ts`;
   mutazioni KG tipizzate `KGMutationResponse` in api.ts; 500→503 search a embedding giù;
   `mcp_memory` → service MCP (fase 5); `MemoryService.list` offset O(n).
3. (fasi precedenti) Eventi bulk delete artifacts + invalidazione FE; live-update whiteboard;
   CAD `export_url` → `/artifacts/{id}/download` (fase 6); export conversazioni a modello;
   `AgentTier` duplicato FE; vitest in CI.

## Decisioni utente registrate (non rilitigare)

- Refactor incrementale, app sempre funzionante; dati azzerabili (no migrazioni); orb-era UI da eliminare
  (Horizon unica superficie); codegen completo; visione = runtime agentico locale con Command Layer
  (invariante anti-escalation non negoziabile, spec §7).
- I branch di fase restano NON mergiati e NON pushati finché l'utente non decide diversamente; si impilano
  (4 sopra 3 sopra 2 sopra 1b sopra 1a).
