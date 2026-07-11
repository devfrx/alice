# Handoff — Risanamento architetturale AL\CE (stato al 2026-07-11, post-Fase 6)

> Per la sessione che continua questo lavoro a contesto fresco/compattato. Contiene SOLO ciò che
> non è ricostruibile dal repo: stato, decisioni, gotchas pagati sul campo, recon da fare.
> Fonti di verità nel repo: spec e piani citati sotto. Questo file SOSTITUISCE la versione
> precedente (post-fase5, `2026-07-10-risanamento-handoff.md`); la storia è in git.

## Stato del programma

- **Spec normativa** (approvata): `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` — 8 fasi, principi §4, criteri §9. È LA fonte di verità.
- **Fasi 1a, 1b, 2, 3, 4, 5, 6: COMPLETE** — branch impilati NON mergiati e NON pushati per decisione
  utente (6 su 5 su 4 su 3 su 2 su 1b su 1a): `arch/fase1a-contratti-rest` → `arch/fase1b-ws-schema`
  → `arch/fase2-persistenza` → `arch/fase3-contenuti` → `arch/fase4-conoscenza` →
  `arch/fase5-kernel` → `arch/fase6-frontend`.
- **Fase 6 (Frontend): COMPLETATA** — review finale di fase «Phase ready with notes», finding
  applicati sul branch. Piano chiuso e veritiero con esiti review per task + verdetto finale +
  backlog consolidato: `docs/superpowers/plans/2026-07-10-fase6-frontend.md`.
- Pending esterni: chip/task `task_6c67e5a8` (fix suite lenta); CI `contracts.yml` MAI eseguita
  (parte al primo push) — ora include anche `npm run lint` e `npm test` per il FE.
- **Smoke funzionale interattivo (npm run dev) NON eseguito in fase 6** — da fare alla prima
  apertura dell'app (checklist nel gate finale del piano: apre su /assistant, /terminal funziona,
  deep-link legacy redirigono, conversazione dalla sidebar via command layer).

## Cosa ha consegnato la Fase 6 (mappa rapida, dettagli nel piano)

- **Horizon unica superficie**: TUTTO lo stack Workspace rimosso (~5.600 righe: WorkspaceView,
  home/*, canvas/* + 6 moduli tile, composables/workspace/*, stores/workspace, ChatPanel e la sua
  catena MessageBubble/ChatInput/StreamingIndicator/ReasoningThread/TaskStrip + terza ondata) +
  dead code orb (ModeSwitcher, orbVisible/ambientEnabled, keyframes, icone). Il TERMINALE è salvo
  come route standalone `/terminal` (`views/TerminalPageView.vue`, voce sidebar). Router: tutti i
  redirect legacy (`/`, `/home`, `/workspace`, `/hybrid`, catch-all) → `/assistant`; niente più
  `UIMode`/`MODE_ROUTES` — la rotta È la fonte di verità. `stores/ui.ts` = solo
  sidebarOpen+sidebarWidth; `DockedSidebar` spostato in `components/sidebar/`.
- **Client REST per dominio**: `services/api.ts` (988 righe) → package `services/api/` (`http.ts`
  core + 17 moduli dominio + barrel `index.ts`). 93/93 metodi mossi verbatim, 39 importer migrati
  (spec inclusi, mock per namespace), NESSUN oggetto `api` legacy. Unica modifica: 6 mutazioni KG
  tipizzate `KGMutationResponse`. Il PATH `services/api` resta valido (directory index).
- **Dispatcher chat-WS esaustivo** (`useChat.ts`): `ChatHandlerMap` mapped-type su
  `ChatServerMessage['type']` (27 chiavi), zero cast nei corpi. `WebSocketManager` ha `onFrame`/
  `offFrame` tipizzati; l'emitter generico a stringhe RESTA per il secondo instance del canale
  VOCE (`useVoice.ts`, vocabolario fuori contratto) ma è SOPPRESSO sul singleton chat quando c'è
  un frame-handler (altrimenti un frame `error` corrompeva connectionStatus — fix da review).
- **Command Registry** (`src/renderer/src/commands/`): CommandDefinition con capability tag §7 +
  `exposeToAgent` default-false (seam anti-escalation, TESTATO); 5 core commands (view.switch,
  conversation.open/new, sidebar.toggle, artifact.show); install IDEMPOTENTE da App.vue (unregister
  + register: un guard di presenza terrebbe closure stantie sotto HMR); AppSidebar E ArtifactCard
  passano dal registry. Manifest/app_command = fase 7.
- **Eventi artifacts**: frame `artifact.bulk_deleted` (`WsArtifactBulkDeleted`, conversation_id
  nullable = wipe totale) emesso da delete_for_conversation (anche su soli pinned-detach) e
  delete_all; FE `applyBulkDeleted` (rimozione + detach pinned locale). `artifact.updated` ora
  invalida ANCHE la cache contenuti (`applyArtifactUpdated`) → live-update whiteboard, con fix
  critici da review in TldrawCanvas: fallback via store (non api raw), debounce 1500ms CANCELLATO
  all'unmount (rischio revert silenzioso degli edit agente), recheck post-mount, echo-guard JSON.
- **CAD**: `export_url` rimosso dai METADATA artifact (derivabile da `download_url` computed);
  payload live del turno e route legacy `/api/cad/models/{name}` INVARIATI (l'artifact id nasce
  solo in tool_loop.py:636). `AgentTier` = alias `ApiSchema<'PermissionMode'>`.
- **Lint SANATO**: `npm run lint` = exit 0 con 0 errori e 0 warning. `endOfLine: auto`,
  riformattazione completa (169 file), override triple-slash per `*.d.ts`, 12 errori veri corretti
  (parametri provati morti rimossi: `_strokeWidth`, `_userMessageId`), 3 `v-html` giustificati con
  verifica del pipeline (markdown-it `html:false`). CI: `npm run lint` + `npm test` in
  contracts.yml. Suite vitest: 21 file / 162 test (nuovi: commands 10, memory store 9).

## Decisioni registrate in Fase 6 (non rilitigare)

1. **La rotta è l'unica fonte di verità della superficie** — niente store `mode`; Horizon è
   l'unica chat surface, le altre feature sono route standalone (whiteboard, board, terminal…).
2. **Niente barrel di compatibilità `api`**: i consumer usano i namespace di dominio; `BASE_URL`
   e `request` sono interni al package (non nel barrel).
3. **L'emitter generico di WebSocketManager sopravvive SOLO per il canale voce** (deviazione
   accettata: la premessa "useChat unico registrante" valeva per il singleton, non per la classe);
   migrare la voce e ritirarlo è backlog.
4. **Install dei comandi idempotente** (mai presence-guard: closure stantie sotto HMR);
   `exposeToAgent` default false; nessun comando guardrail sarà MAI exposable (invariante §7).
5. **Dati azzerabili confermati**: nessuna migrazione localStorage (nuova chiave
   `alice_sidebar_width`, le vecchie chiavi restano orfane).
6. **Orphan-state whiteboard allargato agli errori di rete** (più sicuro del canvas bianco che
   rischiava PATCH di snapshot quasi-vuoto su contenuto reale).
7. Docstring/commenti in inglese; piano ed esiti in italiano.

## Prossimo lavoro: Fase 7 — Command Bridge (spec §7, riga 216)

Da scrivere con `writing-plans` su branch `arch/fase7-command-bridge` (figlio di
`arch/fase6-frontend`). Requisiti spec: tool `app_command(name, args)` di proprietà del kernel;
manifest dei comandi come TERZO contratto (stessa pipeline di generazione/validazione); RPC
backend→frontend con correlation_id + timeout + "UI non disponibile" come risultato pulito;
gating permission-mode sui capability tag; **invariante anti-escalation strutturale** (comandi
guardrail non registrabili come agent-callable). Dipende da fasi 5 e 6 (entrambe complete).

Messaggio di kickoff della sessione (copiare tale e quale):
«leggi specs, piano ed handoff della skill superpowers e continuiamo l'implementazione. /using-superpowers»

### Recon fase 7 — note utili già verificate in fase 6

- Il registry FE è pronto come seam: metadata serializzabili (name/title/capability/argsSchema/
  exposeToAgent), `run` escluso naturalmente dalla proiezione manifest. MANCANO (backlog fase 6,
  da piazzare nella fase): validazione runtime `argsSchema` nel bridge (execute NON valida — gli
  args agente sono JSON non fidato) e campo `description` machine-facing per il manifest LLM.
- L'events-WS ha già correlation_id nell'envelope (1b); il seam RPC backend→FE è NUOVO (oggi i WS
  sono push-only): servono richiesta con correlation_id, attesa con timeout lato tool, risposta
  client→server (il vocabolario client events oggi ha solo ping/terminal.* — andrà esteso).
- `WsSendPayload` (frame invio chat) è senza `type` nel vocabolario client (decisione 1b):
  se la fase 7 tocca il protocollo client→server, valutare la promozione a frame tipizzato.
- Il circuito eventi FE è esaustivo compile-time: ogni frame nuovo → regen → chiave obbligatoria
  nel dispatcher (garanzia collaudata due volte in fase 6).

## Workflow collaudato (riusare così; raffinamenti fase 6 inclusi)

- Per fase: branch dedicato → `writing-plans` (codice VERBATIM, comandi esatti) → `subagent-driven-development`:
  implementer (sonnet) + spec reviewer (sonnet) + quality reviewer (modello top, SEMPRE) IN
  PARALLELO dopo verifica del diff → fix loop → review finale di fase (modello top, range intero,
  angolo = coerenza cross-task) → branch impilato, handoff aggiornato.
- I nit banali e i fix enumerati con precisione li applica il CONTROLLER direttamente (gate scoped);
  i fix che richiedono lettura/giudizio tornano all'IMPLEMENTER via SendMessage (mantiene il
  contesto). Task di pura configurazione con gate auto-verificante → controller direttamente.
- **Raffinamento fase 6**: nei prompt dei reviewer scrivere ESPLICITAMENTE "READ-ONLY, mai
  npm install/ci" (un reviewer ha corrotto node_modules a metà fase); ai reviewer di RE-review
  passare la lista puntata di cosa verificare per finding.
- Ogni fix di review aggiorna ANCHE il piano (esito per task, sempre); finding fuori task → backlog.
- Le review trovano cose VERE anche a fase matura: in fase 6 un crash reale della superficie
  primaria (RouterLink a route rinominata — MATCHER_NOT_FOUND al mount), una regressione di stato
  (frame error → connectionStatus), un buco funzionale (live-update mai attiva su percorso
  Horizon) e un rischio data-loss (debounce non cancellato). NON saltare i cicli, né la review
  FINALE (ha colto il bypass del registry e una promessa di task caduta nel vuoto).
- Commit convenzionali + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Mai push senza richiesta.

## Gotchas (validi anche dopo la fase 6)

1. **Suite backend completa IMPRATICABILE** (fixture `app` ~25s/test). Verifica di fase = test mirati
   per dominio + `tests/contracts/`. Subagent avvisati di NON killare run lente (timeout 600s).
2. **`npm run lint` ORA È VERDE (exit 0, 0/0) ed è gate CI** — non è più tollerato introdurre
   errori O warning; `npm test` (vitest, 21 file/162 test, <1s) idem. Il gate FE completo è:
   typecheck + lint + test.
3. **ruff/mypy con errori pre-esistenti** → scoped; file nuovi puliti; confrontare con `git show <base>:file`.
4. **EOL: CINQUE incidenti nel programma** (2 in fase 4, 1 in fase 5, 2 in fase 6: flip CRLF di
   5 store nel Task 3 sanato dal controller; flip non-riproducibile di 2 file durante un
   `eslint --fix .` nel Task 7, colto in corsa). `endOfLine: auto` ora protegge prettier, ma
   SEMPRE verificare `git ls-files --eol` PRIMA e DOPO ogni commit; diff sospettosamente grande =
   flip (`git diff --ignore-cr-at-eol --stat` per smascherarlo). MAI cmdlet PowerShell su file
   non-ASCII. Restano 4 file `i/lf w/crlf` storici (documentati nel backlog).
5. **Subagent**: prescrizioni ESATTE e VERIFICARE IL DIFF al ritorno (`git show`); reviewer
   READ-ONLY espliciti; un reviewer morto/troncato (limite sessione) → rilanciare con SendMessage
   chiedendo di COMPLETARE, non ripartire.
6. **`check-contracts.ps1` DOPO il commit** (untracked = dirty). Regen SOLO nel task previsto.
   NB PS 5.1: redirigere stderr (`2>&1`) su script che loggano via loguru produce falsi exit 1.
7. **PowerShell 5.1**: niente `&&`; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`;
   boot-check e lint-imports dalla REPO ROOT.
8. **Il venv NON ha pip** → `uv pip install`.
9. **`ToolResult.error()` riempie `error_message`, NON `content`**.
10. **Campi generati opzionali**: fallback `??` nei consumer, mai tipi a mano.
11. **Contratti WS**: modello in ws_schema + vocabolario congelato + dispatcher FE esaustivo
    (ora su ENTRAMBI i canali). Il frame server si aggiunge in 4 punti: classe, union, frozen
    vocab test, handler FE (il typecheck FORZA il quarto dopo la regen).
12. **`test_plugins_enabled_list` è ROSSO ereditato** (21 vs 20): non è una regressione.
13. **import-linter**: dalla REPO ROOT; wildcard `*` un livello, `**` ricorsivo; ignore
    non-matchante = run fallito.
14. **File "modified since read"**: dopo che un subagent tocca un file che il controller aveva
    letto, ri-Read prima di Edit (il tracking del harness lo impone).

## Backlog (in fondo ai piani 1a/1b/2/3/4/5/6; voci fase 6 principali)

1. Per fase 7: validazione argsSchema al bridge; `description` machine-facing; promozione
   WsSendPayload; router-link → comandi; board che consuma `?artifact=`.
2. Migrare useVoice a pattern tipizzato e ritirare l'emitter generico; hasOwnProperty anche nel
   dispatcher events; bridge client_tool_call; validazione runtime frame WS (zod/valibot).
3. `.gitattributes` con `*.ts text eol=lf` + normalizzare i 4 file `w/crlf` storici.
4. CAD: unificazione payload live su endpoint artifacts (richiede artifact id nel tool result).
5. TldrawCanvas: orphan dead-end pre-esistente; camera/undo reset su update esterno (manca
   loadSnapshot incrementale); copy "deleted" per errori di rete.
6. `auditApi` morto pre-fase (cablare UI audit o rimuovere modulo+endpoint); ~15 icone senza
   consumatori; a11y tabs terminale.
7. Ereditati (fasi 1-5): migrazione consumer ai gruppi ctx; test LLM/registry via moduli;
   guardia anti-drift flag-registry; route MCP tipizzate + ratchet; 500→503 search; offset O(n);
   export conversazioni a modello; dedup broadcaster.

## Decisioni utente registrate (non rilitigare)

- Refactor incrementale, app sempre funzionante; dati azzerabili (no migrazioni); orb-era E
  Workspace eliminati (Horizon unica superficie, terminale salvato standalone — decisione
  2026-07-10 "la soluzione più professionale, senza debiti"); lint sanato A FONDO con reformat
  completo e gate CI (stessa decisione); codegen completo; visione = runtime agentico locale con
  Command Layer (invariante anti-escalation non negoziabile, spec §7).
- I branch di fase restano NON mergiati e NON pushati finché l'utente non decide diversamente;
  si impilano (6 sopra 5 sopra 4 sopra 3 sopra 2 sopra 1b sopra 1a).
