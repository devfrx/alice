# Handoff — Agent v2 Fase 1, Mossa 1: motore greenfield AgentEngine (feat/agent-engine-fase1)

**Data:** 2026-07-17
**Branch:** `feat/agent-engine-fase1` — **NON mergiato** (la fase chiude con Mossa 2, che
consuma lo stesso branch)
**Programma:** `docs/superpowers/specs/2026-07-16-agent-v2-program-design.md` (Agent v2 —
parità Claude Code, 9 fasi)
**Spec di fase:** `docs/superpowers/specs/2026-07-17-agent-engine-fase1-design.md`
**Piano Mossa 1:** `docs/superpowers/plans/2026-07-17-agent-engine-fase1-mossa1.md` (20 task)
**Ledger di esecuzione:** `.superpowers/sdd/progress.md`
**Baseline eval di riferimento:** `docs/superpowers/evals/2026-07-17-baseline-fase0/`
(23/23, 79/79)
**Metodo:** subagent-driven — ogni task: implementer + spec review + quality review (metodo
Fase 0); tutti i finding delle review risolti in-branch prima di chiudere il task.

## Stato: MOSSA 1 COMPLETA (task 1-19 eseguiti e chiusi + questo task 20 di chiusura)

Mossa 1 (motore, wire invariato via adapter di parità throwaway) è **completa**: il motore
greenfield `AgentEngine` è costruito, wired dietro flag, portato a parità eval, e il percorso
legacy è stato demolito. Il branch **resta aperto**: la fase (spec `2026-07-17-agent-engine-
fase1-design.md`) chiude solo a fine Mossa 2 (wire v2 + migrazione FE), che va pianificata
come prossimo passo su questo stesso branch.

## Cosa è stato costruito (task-by-task, in breve)

**T1-T11 — motore puro (45 test), zero riuso dal legacy (principio pilastro):**
- T1: package `backend/services/agent/` + contratto import-linter `agent ↛ turn`.
- T2: DTO (`TurnRequest`/`TurnOutcome`/`ToolInvocation`, normalizzazione ID).
- T3: vocabolario eventi interni tipizzati (`events.py`, v2 + diagnostici parity).
- T4: 7 `Protocol` delle porte (`ports.py`) + test double propri del motore; adjudicazione
  design — `confirm_tool` ritorna `DISCONNECTED` come dato (persist-prima-di-stop), solo
  client/`ask_user` sollevano.
- T5: dedup registry cross-step (`dedup.py`, hash normalizzato Windows-safe).
- T6: retry policy (`retry.py` — empty-response nudge, transient vs fail-fast).
- T7: budget tracker e `StopReason` con precedenza esplicita (`stop.py`).
- T8: `AgentEngine` — loop base senza tool (stream, retry, cancel, errore).
- T9: gate flow e batch tool paralleli con invarianti di persistenza.
- T10: loop multi-step — budget, disconnect, voice trim, costo accumulato.
- T11: compaction tra gli step via `ContextPort`, fail-open.

**T12-T14 — adapter piattaforma:**
- T12: `adapters/llm.py`, `permission.py`, `context.py`, `execution.py`. Divergenze
  contratto REALI documentate (tool_call chunks completi, error senza HTTP status,
  client_execution, `ExecutionContext` senza client_ip, `ToolResult` senza images, mapping
  posizionale di `ContextManager`). Bare tool name resolution unificata describe/permission.
- T13: `PersistencePort` su SQLModel con unit-of-work esplicite (`adapters/db.py`). Fix
  Critical: `register_artifacts` DOPO il checkpoint del batch (FK sempre su righe durevoli).
- T14: trasporto WS greenfield (`adapters/ws.py`) — read-pump unico, request correlate via
  `correlation_id`, disconnect handling. Adjudicazione: `WsInteractionPort` non emette
  eventi canonici (li possiede il motore).

**T15-T19 — parità, wiring, swap, demolizione:**
- T15: `adapters/parity.py` (translator throwaway) + harness di parità v1-vs-v2 sul wire
  attuale. Parità reale provata (usage counters, tool name, result verbatim, content_type,
  frame di conferma value-pinned). `KNOWN_DIFFERENCES` residue: 7 chiavi su 5 categorie,
  tutte adjudicate harmless.
- T16: wiring dietro flag `agent.engine` (default v1) — ws, headless, composition root
  (`runner.py`). `WsTransport` unico lettore in v2.
- T17: mappa invarianti spec§6 → test (15/15 coperti, 9 test nuovi); 18 file legacy mappati
  col destino; evals CLI de-linkato da `services.turn` (proprio `RecordingSink`).
- T18: **eval gate reale** — run `20260717-140314` su v2: **23/23 scenari, 79/79 check,
  ZERO variazioni vs baseline Fase 0, costo $0.3340** (OK esplicito dell'utente sulla spesa).
- T19: **demolizione** — swap default a v2, rimozione `services/turn/` + ramo v1 +
  reflection: **30 file / 8776 LOC morti** (`services/turn` 11 file, `_engine_bridge`, 18
  test). v2 è l'**unico percorso** rimasto. Persist/recovery/versioning migrati su
  `TurnRequest`/`TurnOutcome`. `_sink.py` resta **api-owned** (non nel package `agent`) col
  `chat_frame_validator` conservato. Flag `agent.engine` ridotto a `Literal["v2"]` (inerte).
  Smoke post-demolizione: **5/5**.

**T20 (questo task) — chiusura Mossa 1:**
- CLAUDE.md sezione "Tools & the turn executor" riscritta come "Tools & the AgentEngine":
  descrive `services/agent/` (engine, 7 porte, adapter, `runner.py` composition root, flag
  inerte, reflection rimossa, `parity.py` throwaway, `_sink.py` api-owned).
- `backend/api/ws_schema/guard.py`: docstring ammorbidita — `WsTransport` non è un
  chokepoint dei validator; la garanzia sul wire del motore è a livello unit
  (`test_parity.py` Part A, ogni frame validato contro la sua classe evento), mentre
  `WebSocketEventSink` (persist path) applica ancora il validator runtime.
- `backend/evals/trace.py:22-23`: prosa `TurnResult.finish_reason`/`TurnResult.cost` →
  `TurnOutcome.finish_reason`/`TurnOutcome.cost` (il tipo reale ritornato dal motore).

## Evidenza eval

- Run baseline Fase 0 (`2026-07-17-baseline-fase0/`): 23/23, 79/79, $0.2843.
- Run T18 su v2 (`20260717-140314`): **23/23, 79/79, NESSUNA variazione vs baseline**,
  $0.3340. La suite è satura alla baseline (Fase 0) — questo run conferma parità
  comportamentale del motore nuovo, non misura un miglioramento (misurarlo richiede scenari
  più difficili, fuori scope di questa fase).
- Smoke post-demolizione T19: 5/5.

## Demolizione — riepilogo

- **30 file rimossi / 8776 LOC morte**: tutto `backend/services/turn/` (11 file: `pipeline.py`,
  `channel.py`, `sink.py`, `tool_loop.py`, `direct_executor.py`, `reflective_executor.py`,
  `_reflection.py`, `factory.py`, ecc.), `_engine_bridge`, 18 file di test legacy.
- **v2 è l'unico percorso**: nessun branch v1 residuo, nessun flag funzionante da
  spegnere — `agent.engine` resta come campo config `Literal["v2"]` inerte, in attesa di
  rimozione a fine Mossa 2.
- Config `agent.reflection.*` uscita dal flag registry (feature eliminata, non solo
  disattivata — le guardie anti-degenerazione arrivano in Fase 3 dentro il motore).
- Mappatura test legacy → motore nuovo: nessun buco di copertura (T17, 15/15 invarianti
  spec §6 coperti da 9 test nuovi + i test del motore T1-T16).

## Processo di review per task

Ogni task del piano (1-20): **implementer subagent → spec review → quality review**
(metodo ereditato da Fase 0). Ogni finding di review è stato risolto in-branch prima di
chiudere il task (fix commit dedicati, es. `18b73ab fix(engine): confirm_tool ritorna
DISCONNECTED...`, `999f80f fix(engine): artifact registrati DOPO il checkpoint...`,
`a4c9b90 fix(engine): TurnOutcome.content = testo dell'ultimo step...`). Nessun task è stato
chiuso con finding Critical/Major aperti; i finding Minor non attuabili subito sono stati
esplicitamente annotati nel ledger come deliberati o rimandati.

## DEBITO CENSITO / residui deliberati (per Mossa 2 e oltre)

Estratto dal ledger (`.superpowers/sdd/progress.md`), voci "Minor da triage" più rilevanti:

1. **Frame wire del motore non validati a runtime**: `WsTransport` bypassa
   `chat_frame_validator`/`events_frame_validator` — la garanzia è solo a livello unit
   (`test_parity.py` Part A, ogni evento validato contro la sua classe Pydantic). Risolto
   concettualmente in Mossa 2 quando l'adapter WS definitivo scrive direttamente nel
   vocabolario v2 tipizzato.
2. **Prosa del risultato sintetico diverge sugli errori** (nota di release Mossa 1): il
   wording del chip cambia rispetto al legacy sui rami di errore sintetico — comportamento
   harmless-adjudicato, non un bug di parità dei dati.
3. **Echo single-step su terminazione anomala di un tool step**: residuo accettato in T16,
   il persist path nuovo lo risolve strutturalmente ma non è stato retro-portato come fix
   isolato in Mossa 1.
4. ~~Bare-name pass-through a rules/grants~~ — **RISOLTO** in `a006214` (fix wave
   post-review olistica): `decide()` riceve ora il nome risolto; rules/grants
   suffix-tolerant.
5. ~~Drift contratti pre-esistente~~ — **RISOLTO** in `5b6d673`: `gen-contracts`
   rieseguito e drift committato in commit separato; `check-contracts.ps1` verde. La
   Mossa 2 parte da baseline codegen pulita.
6. **`ask_user_required` senza value-pin**: il frame di interazione per `ask_user` non ha
   un test che ne fissa i valori (a differenza della conferma tool, value-pinned in T15) —
   da aggiungere quando quel path viene esercitato più a fondo.
7. **`KNOWN_DIFFERENCES` residue**: 7 chiavi su 5 categorie tra wire v1 e v2 (parity
   harness T15), tutte **harmless-adjudicate** — non bloccano lo swap, mappate una a una nel
   report di T15.

Altri minor annotati nel ledger (non ripetuti qui, vedi `progress.md` task-by-task):
`started_at` scalare nel double invece di keyed per call_id; label `"cancelled"` per
confirm-DISCONNECTED da valutare come label distinta; `parse_error` senza `tool.call`
(coerente col brief, non un bug); `MAX_STEPS` su step finale pulito invisibile in
`finish_reason`; `out_of_steps=False` hardcoded nel ramo failure (inerte per precedenza);
trim di compaction non forza step senza tool (candidato Fase 3).

## Gotcha di sessione

1. **2 crash API recuperati via SendMessage**: durante T14 e T16 la sessione dell'agente
   implementer è crashata a metà lavoro; recuperata riprendendo il thread via `SendMessage`
   sull'agent id invece di rilanciare da zero (evitato lavoro perso/duplicato).
2. **Trappola venv sbagliato**: un fixer ha lanciato pytest con `backend\.venv` invece del
   venv ROOT (`.\.venv\`) e ha ricevuto un falso `qdrant_client` mancante — SEMPRE il venv
   ROOT per qualunque comando in questo repo (ribadito qui perché si è ripetuto più volte
   nel corso della fase).
3. **Una violazione del pilastro loggata, zero contaminazione**: durante il fix di T16 un
   fixer ha letto `tool_loop.py` per conferma di un dettaglio comportamentale — vietato dal
   principio pilastro (zero influenza del legacy). Il reviewer ha verificato che il diff
   risultante non contiene traccia di codice/logica copiata; annotato nel ledger come
   promemoria per rinforzare il divieto nei dispatch successivi (nessuna azione correttiva
   sul codice necessaria).

## Gate verificati (chiusura sessione, 2026-07-17, HEAD `72125b8`+fix)

- `cd backend; pytest tests/agent/ tests/evals/ -q` → **150 passed** (111 agent + 39
  evals; verificato dal controller a fine sessione, foreground, venv ROOT).
- `cd backend; ruff check .` → 0 (fix wave finale inclusa).
- da repo root: `lint-imports --config backend/pyproject.toml` → 7 contratti KEPT
  (incluso `agent ↛ turn`, ancora attivo finché il contratto non si ritira in Mossa 2 —
  nota T1: il contratto lint copre solo `services/agent`, non `tests/agent`).
- `.\scripts\check-contracts.ps1` → verde (post `5b6d673`).
- Esiti puntuali: `.superpowers/sdd/task-20-report.md` (+ append fix wave finale).

## Prossimo passo del programma

**Scrivere il piano Mossa 2** con la skill `writing-plans`, partendo da:
- Spec `2026-07-17-agent-engine-fase1-design.md` §4 (vocabolario canonico v2 sul canale
  chat — `turn.started`, `turn.delta`, `turn.llm_step`, `tool.call/started/progress/
  result`, `interaction.requested/resolved`, `context.usage/compaction`, `turn.warning/
  error/usage/finished`) e §5 (migrazione FE — `agentRun` come unica fonte di verità del
  fold del turno, `ChatHandlerMap` esaustiva sui frame v2, tipi rigenerati via
  `gen-contracts.ps1`, mai a mano).
- Spec §7 punti 7-9 (sequenza operativa Mossa 2): vocabolario §4 in `api/ws_schema/` emesso
  dall'adapter WS definitivo con eliminazione di `adapters/parity.py`; migrazione FE;
  eval run finale 23/23 con baseline di fase committata in `docs/superpowers/evals/`.

Stesso branch `feat/agent-engine-fase1` — la fase chiude (ed eventualmente si merge) solo a
fine Mossa 2.

## Addendum — Review olistica di fine Mossa 1 (post-handoff)

Verdetto: **READY FOR MOSSA 2** (review whole-branch su modello top, dopo i 20 task).
Fix eseguiti in coda (commit `a006214`, `5b6d673`): nome risolto passato a rules/grants
nel PermissionPort; igiene docstring post-demolizione; riallineamento codegen contratti
(drift pre-esistente da bump pydantic/fastapi) in commit separato.

**Da portare ESPLICITAMENTE nel piano Mossa 2** (trovati dalla review olistica):

1. **Pipeline `tool_progress` orfana** (Important): la demolizione ha lasciato l'emitter
   ContextVar mai settato — i tool lunghi (cad_generator) non streammano più progresso.
   Re-wiring nell'adapter ExecutionPort → ToolProgressEvent, presto in Mossa 2.
   (Gap della checklist §6: il tool progress non era censito — lezione per le prossime fasi.)
2. `turn.finished` payload gap: `final_message_id` mai popolato dal motore; token hardcoded
   a 0 nel parity frame. Il vocabolario v2 richiede message_id/version/cost → decidere come
   il persist finale rientra nel motore (o feed-back del message id).
3. Ownership split dei frame `done`/`context_info`/compression (emessi da `_persist.py` su
   sink separato) da collassare: la "fonte unica di verità" FE presuppone UNO stream.
4. `InteractionRequestedEvent` più sottile della spec §4 (mancano args/reasoning/questions;
   ask_user/client non emettono requested/resolved) → arricchire per i dialog FE.
5. Test di integrazione WS live assente (solo headless è coperto end-to-end): aggiungere un
   test TestClient WS del percorso completo PRIMA di muovere il vocabolario.
6. Mismatch role del summary di compaction (system in-engine vs assistant
   `is_context_summary` in assembly) — check consapevole quando si tocca il contesto.

## Istruzioni operative per la prossima sessione (metodo e principi — NON derogare)

**Principi:**
1. **PRINCIPIO PILASTRO** (memoria utente + programma §3.1): il legacy non influenza il
   nuovo, né in logica né in professionalità. `services/turn` non esiste più, ma il
   principio resta per Mossa 2 e le fasi successive: niente scorciatoie, niente debiti non
   censiti, "la soluzione meno pigra e più professionale". Vale anche per i test double.
2. **Contratti**: ogni modifica al wire passa da `api/ws_schema/` (Pydantic) +
   `.\scripts\gen-contracts.ps1` + aggiornamento dei frozen test in
   `backend/tests/contracts/` + FE `ChatHandlerMap` esaustiva. MAI tipi TS a mano.
   La Mossa 2 È il cambio di contratto deliberato previsto dal programma.
3. **Eval come gate**: ogni milestone chiude con `python -m backend.evals run` (repo root,
   venv ROOT, key OpenRouter in keyring; costa pochi dollari → SEMPRE OK esplicito
   dell'utente prima). Gate: 23/23, zero regressioni vs baseline.

**Metodo (subagent-driven, skill superpowers):**
- `writing-plans` per il piano Mossa 2, poi `subagent-driven-development` per l'esecuzione:
  un implementer per task + task review (spec+quality) + fixer sui finding + re-review.
  Ledger in `.superpowers/sdd/progress.md` (quello attuale contiene tutta la Mossa 1 —
  archiviarlo e ripartire). Script: `task-brief` e `review-package` nella dir della skill.
- Modelli: implementer economico sui task meccanici con codice completo nel piano; medio
  sugli adapter/integrazione; top su motore/concorrenza/review ad alto rischio e sulla
  review olistica finale. SEMPRE specificare il modello nel dispatch.
- Review package con BASE = commit pre-implementer (mai HEAD~1). Diff giganti (demolizioni):
  pacchetto focalizzato (lista dei file morti + diff dei soli modificati).

**Gotcha macchina (si sono ripetuti — metterli nei dispatch):**
- pytest SEMPRE foreground nei dispatch subagent; MAI due pytest concorrenti; MAI la suite
  integrale (AUD-008) — solo sottoinsiemi mirati.
- SEMPRE venv ROOT (`C:\Users\zagor\Desktop\alice\.venv`), MAI `backend\.venv` (esiste e
  inganna: `qdrant_client` mancante, `ModuleNotFoundError: backend`). Comandi da repo root
  con `.\.venv\Scripts\Activate.ps1`, pytest da `backend/`.
- Console Windows cp1252: niente Unicode nei print delle CLI (già gestito nell'harness).
- Subagent che crasha per errore API o stallo: NON rilanciare da zero — riprendere con
  `SendMessage` sull'agent id (2 crash + 1 stallo recuperati così in questa sessione).
- Il remote è stato rinominato `devfrx/omnia` → `devfrx/alice` (push funziona via
  redirect; l'utente può aggiornare l'URL quando vuole).
