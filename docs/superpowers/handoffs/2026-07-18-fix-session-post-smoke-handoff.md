# Handoff — Sessione di fix post-smoke Fase 1 (feat/agent-engine-fase1)

**Data:** 2026-07-18 (pomeriggio/sera — stessa giornata della chiusura Mossa 2)
**Branch:** `feat/agent-engine-fase1` — Fase 1 COMPLETA + 6 commit di fix post-smoke.
Il **merge in `main` resta a decisione dell'utente**, dopo lo smoke finale (sotto).
**Handoff precedente:** `docs/superpowers/handoffs/2026-07-18-agent-engine-fase1-mossa2-handoff.md`
(resta la referenza per l'architettura del wire v2 e il debito Mossa 2 — leggerlo PRIMA).
**Programma:** `docs/superpowers/specs/2026-07-16-agent-v2-program-design.md`
(la sezione **Fase 2 è stata ESTESA in questa sessione** col perimetro permessi MCP).
**Ledger locale:** `.superpowers/sdd/progress.md` (gitignored, solo su questa macchina) —
cronaca completa con root cause e "perché" di ogni scelta, sezione "SESSIONE DI FIX POST-SMOKE".

## Come si è svolta la sessione

Smoke manuale dell'utente su Horizon → 2 anomalie iniziali → investigazione root-cause
(2 Explore paralleli, citazioni a livello di riga) → fix su delega esplicita ("le opzioni
più professionali, prive di debiti, meno pigre e coerenti con le fasi del rework") →
smoke iterativo con l'utente che ha scoperto altri 2 difetti reali + 1 gap di design.
Metodo: systematic-debugging + TDD (rosso verificato prima di OGNI fix); il ponte MCP
(strutturale) è stato fatto subagent-driven con review indipendente del controller.

## I 6 commit della sessione (root cause → fix)

1. **`01fce84` — remember delle conferme persistito come regola.** La porta WS scartava
   il campo `remember` della `interaction.response` (FE e contratto v2 erano pronti; il
   consumatore BE non è MAI esistito — non una regressione). Ora: `ConfirmationResult`
   da `confirm_tool`, `PermissionPort.remember_approval` (best-effort, mai solleva),
   mapping `conversation` → `PermissionRule` allow per-conversazione / `persistent` →
   globale, keyed sul nome namespaced risolto (regola M1). **Contratto**: `RememberChoice`
   `"session"` → `"conversation"` (rituale completo: ws_schema → frozen test →
   gen-contracts → FE; etichetta dialogo "Questa conversazione").
2. **`bdc84da` — ponte scope workspace → MCP roots** (prima INESISTENTE: allowed dirs del
   filesystem server = arg CLI statici `~`). `McpSession.roots_provider` →
   `list_roots_callback` (roots = static CLI dirs ∪ unione globale degli scope, dedup,
   ordine deterministico); `AliceEvent.SCOPE_UPDATED` sul bus + **replay singolo
   post-`load_all`** (i server MCP si connettono in `stage_plugins`, PRIMA del load degli
   scope persistiti); il plugin notifica `roots/list_changed` a tutte le sessioni.
   Le static dirs DEVONO stare nelle roots: un server roots-capable SOSTITUISCE le CLI
   dirs (verificato sul sorgente di server-filesystem v2026.7.10). **VERIFICATO LIVE**:
   sia con un e2e contro il vero server npx, sia nello smoke dell'utente
   (`list_allowed_directories` di una sessione nuova include `E:\ALL` dal replay).
3. **`005eed3` — esiti remember mai silenziosi** (log warning su valore fuori vocabolario
   — es. `session` legacy da un FE stantio — e info a regola salvata).
4. **`04c1591` — "database is locked" sul salvataggio della regola.** Il MIO design del
   fix 1 chiamava `remember_approval` (sessione DB propria) subito dopo `save_audit`
   (flushato ma NON committato sulla UoW del turno): write-lock SQLite tenuto dalla
   stessa coroutine in attesa → collisione garantita, risolta solo dal busy timeout.
   Fix: `state.pending_remembers`, persistenza SOLO dopo il checkpoint del batch
   (stesso principio §6.15 di `register_artifacts`/T13). Pin d'ordine TDD.
5. **`71eb716` — errori LLM mai più silenziosi né inarrestabili.** Smoke con provider
   upstream saturo (ResourceExhausted): (a) il client controlla il cancel solo TRA i
   chunk SSE → stream MUTO = read bloccata fino a 600s (timeout deliberato per i
   reasoning model) e **Stop inefficace** → `engine._race_stream` mette ogni `__anext__`
   in gara con `cancel.wait()` (abort + `aclose` su cancel, chiusura CANCELLED col
   parziale); (b) retry su `LLMFailure` invisibili → `turn.warning(code=llm_retry)` per
   ogni tentativo (vocabolario esistente, zero cambi contratto); (c) FE: `turn.error`
   era un `console.error` → toast d'errore sempre; per gli errori PRE-turno (assembly/
   route, `turn_id` ASSENTE, nessun `turn.finished` a seguire) recovery locale
   (`agentRun.applyTurnError()` spegne la sentinella "avvio…" + `cancelStream()`);
   per gli errori del motore la chiusura resta a `turn.finished` (no teardown doppio).
6. **`77626b6` — docs: perimetro permessi MCP pianificato in Fase 2** (+ questo handoff
   e l'allineamento CLAUDE.md nello stesso commit di chiusura).

## Scoperta di sessione (dimostrata live, PIANIFICATA — non fixata, decisione utente)

In `strict`, una scrittura via `mcp_client_mcp_filesystem_write_file` è passata **senza
conferma** (zero righe di audit): i tool MCP non dichiarano `capabilities`/`path_args`/
`requires_confirmation` (default vuoti in `core/plugin_models.py`) → il gate salta sia il
confinement di scope (`is_fs=False`, `permission_service.py:306`) sia la conferma dei
tier. Il ponte roots amplia la superficie raggiungibile alle cartelle di scope. L'utente
ha scelto: **nessun tampone euristico ora**; il lavoro è scope esplicito della **Fase 2**
nella spec di programma (approccio annotations `readOnlyHint`/`destructiveHint` →
capability/risk/`requires_confirmation`, fallback conservativo, confinement
per-conversazione, sorte del layer grant in-memory). NON anticiparlo fuori fase.

## Stato dei gate (HEAD di chiusura, tutti riverificati a fine sessione)

- `pytest tests/agent/ tests/evals/ tests/contracts/` → **293 passed** (139 agent)
- `ruff check .` → 0; mypy: zero errori NUOVI sui file toccati (4 pre-esistenti censiti
  in `mcp_session.py`/`bootstrap/workspace.py`, identici a HEAD precedente)
- `lint-imports` → 6 kept, 0 broken; `check-contracts.ps1` → verde
- FE: typecheck 0, lint 0, vitest **381/381**
- **Eval a pagamento NON rieseguita** (deliberato: il percorso headless è invariato —
  `AutoDeclineInteractionPort` → REJECTED, remember NONE; la baseline di fase resta
  `docs/superpowers/evals/20260718-121940-baseline-fase1/`). Rieseguire SOLO con OK utente.

## Cosa resta da verificare live (smoke finale, PRIMA del merge)

1. **Fix remember end-to-end**: serve una conferma VERA → chiedere ad Alice di usare il
   tool NATIVO (`file_search_write_text_file`) — i tool MCP non confermano (gap sopra).
   Attesi: dialogo con "Questa conversazione" → log `Conferma ricordata: regola allow
   per '…'` → regola visibile in Impostazioni → Sicurezza (conversazione attiva) → il
   tool non richiede la stessa conferma nella stessa conversazione.
2. **Fix errori/cancel**: con provider saturo → toast warning per ogni retry, toast
   errore alla resa, Stop interrompe subito anche a stream muto.
3. Il ponte roots è già stato verificato live (non serve ripeterlo).

## DEBITO CENSITO (aggiornato — somma col handoff Mossa 2)

1. **Infra test WS/REST Windows** (priorità, invariato da Mossa 2): race cross-event-loop
   StaticPool aiosqlite, ~13 test skippati con reason. Primo candidato di manutenzione.
2. **Perimetro permessi MCP** → pianificato in Fase 2 (sezione dedicata nella spec di
   programma). Include la sorte del layer grant in-memory (`PermissionService.grant`/
   `is_granted`): oggi consumato dal gate ma SENZA scrittori di produzione.
3. **Archiviazione DB della compaction in-turn inerte** (invariato da Mossa 2): servono
   gli id messaggio in `TurnRequest.history`.
4. **Outcome interaction indistinto su timeout/cancel client** (invariato, deliberato).
5. **Primo-token senza watchdog**: il read timeout streaming resta 600s (deliberato per i
   reasoning model). Con `_race_stream` lo Stop ora funziona sempre e i retry sono
   visibili; un watchdog first-token configurabile è materiale Fase 3/4.
6. **FE minori** (invariati da Mossa 2): bolla vuota transiente su `message_id=""`,
   cost gating generation-only, `conversation_id` sui frame `context.*` come
   raffinamento wire futuro.

## Gotcha di sessione (i vecchi RESTANO validi — handoff Mossa 2 §Gotcha; nuovi:)

1. **Scritture su sessione DB propria invocate dal motore SOLO dopo un checkpoint** —
   mai tra un flush e il suo commit della UoW del turno (SQLite single-writer: collisione
   garantita, vedi commit 4). I double in-memory NON vedono i lock: per questa classe di
   bug serve il traceback live o un test su SQLite reale.
2. **HMR/finestre dev stantie**: il backend di `start-dev` ha `--reload` (si aggiorna da
   solo ai commit), il FE vive in una finestra separata con HMR che può NON ricaricare —
   dopo cambi FE fare riavviare `start-dev` all'utente prima di diagnosticare "bug".
3. **Provider upstream saturo** (`ResourceExhausted` da OpenRouter/Nvidia): sintomo =
   una sola riga ERROR nel log + turno percepito come appeso. Non è un bug nostro;
   ora produce warning/errore visibili e Stop funziona. LM Studio spento = nessun
   fallback locale.
4. Lo smoke può prendere strade impreviste: il modello sceglie LUI i tool (qui ha
   preferito MCP filesystem al tool nativo) — per verificare un flusso specifico,
   chiedere esplicitamente il tool nel prompt.
5. Macchina (invariati, si ripetono perché VITALI): venv SEMPRE con path assoluto
   (`& "C:\Users\Jays\Desktop\alice\alice\.venv\Scripts\Activate.ps1"`); MAI pytest
   concorrenti né in background; `-o faulthandler_timeout=N` per gli hang; i 4 file
   test WS legacy fuori dai gate di default.

## Prossima sessione (delega)

1. **Leggere PRIMA, nell'ordine**: questo handoff INTERO; l'handoff Mossa 2 (wire v2 +
   debito + gotcha); la spec di programma (in particolare la sezione **Fase 2 estesa**);
   CLAUDE.md "Tools & the AgentEngine" + "Scope & permission modes" (aggiornata).
2. **Primo atto**: supportare lo smoke finale dell'utente (punti sopra) e, a suo OK,
   il **merge di `feat/agent-engine-fase1` in `main`** (skill
   `finishing-a-development-branch`; la baseline eval si aggiorna al merge come da
   regole di programma).
3. **Solo DOPO il merge**: **Fase 2** del programma — spec di fase propria (brainstorming
   breve sulle decisioni aperte), piano subagent-driven, branch dedicato. Il perimetro
   permessi MCP fa parte della fase, non anticiparlo né lasciarlo cadere.
4. **Principi NON negoziabili invariati**: pilastro (soluzione meno pigra, zero debiti
   non censiti), contratti (ogni tocco al wire = ws_schema → frozen test → gen-contracts
   → ChatHandlerMap, MAI tipi TS a mano), eval a pagamento SOLO con OK esplicito
   dell'utente, TDD col rosso verificato prima, review indipendente sui fix strutturali.
