# Handoff — Risanamento architetturale AL\CE (stato al 2026-07-11, post-Fase 8)

> Per la sessione che continua questo lavoro a contesto fresco/compattato. Contiene SOLO ciò che
> non è ricostruibile dal repo: stato, decisioni, gotchas pagati sul campo, pending. Fonti di
> verità nel repo: spec e piani citati sotto. Questo file SOSTITUISCE la versione precedente
> (post-fase-7, stesso path); la storia è in git.

## Stato del programma: TUTTE LE 8 FASI IMPLEMENTATE

- **Spec normativa** (approvata): `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` — 8 fasi, principi §4, criteri §9.
- **Fasi 1a-7: COMPLETE, PUSHATE e MERGIATE in `main`** (fase 7 Command Bridge: merge `1e91a00`; docs allineate in `5b0cb8b`).
- **Fase 8 «Fondamenta Jarvis»: COMPLETA su branch `arch/fase8-fondamenta-jarvis`** (17 commit,
  `32ce1e9..d3e5420` + chiusura docs; figlio di `main` @ `5b0cb8b`). **NON mergiata, NON pushata**
  — push e merge SOLO su richiesta esplicita dell'utente (decisione permanente).
- Review finale fase 8: **«Phase ready with notes»** (nessun finding bloccante; note N1-N4 nel
  backlog del piano). Piano chiuso e veritiero con esiti review per task + verdetto + backlog:
  `docs/superpowers/plans/2026-07-11-fase8-fondamenta-jarvis.md`.
- **Era l'ULTIMA fase del programma.** Il seguito naturale è il backlog del piano fase 8 (16 voci,
  molte ereditate dalle fasi precedenti) e le implementazioni ricche sopra le interfacce Jarvis.

## Pending esterni (verificare alla prossima occasione)

1. **Smoke funzionale interattivo (`npm run dev`) MAI eseguito per le fasi 6, 7 E 8**: alla prima
   apertura fare le TRE checklist (gate finale piano 6; step 9.6 piano 7; fase 8: toast attention
   forzando un `attention.raised` dal backend, store `backgroundTasks` popolato da uno
   spawn_subagent, turno voce con toolset ridotto nei log).
2. CI `contracts.yml` sui push di main del 2026-07-11 (fasi 1-6 + fase 7 `1e91a00`): esito mai
   verificato su GitHub. Il branch fase 8 non è pushato, quindi nessuna CI per ora.
3. Chip/task `task_6c67e5a8` (fix suite lenta) ancora aperto.

## Cosa ha consegnato la Fase 8 (mappa rapida; dettagli nel piano)

- **Contratti WS**: frame events `background_task.updated` (snapshot COMPLETO del task,
  `origin="agent"`) e `attention.raised` (origin default `system`); campo opzionale
  `source: "text"|"voice"` su `WsUserMessage` (per-messaggio, NON query param). Regen committata.
- **`BackgroundTaskService`** (`services/background_tasks.py`, gruppo `platform`): registry
  in-memory di task osservabili (start/update/complete/fail → emit bus → bridge in
  `surfaces.py` → frame WS → store FE `backgroundTasks`). I chiamanti DEVONO raggiungere uno
  stato terminale (i running non vengono mai prunati). Subagent e turni autonomi vi transitano.
- **`AttentionService`** (`services/attention_service.py`): punto unico disattivabile
  dell'iniziativa agente→utente; enum `interrupt|notify|queue|drop` (v1 emette solo NOTIFY/DROP,
  cooldown anti-spam, urgent bypassa); `attention.raised` → toast FE (`useToast`).
- **`TriggerService`** (`services/trigger_service.py`): `TriggerSpec(kind=schedule|event|manual)`;
  schedule = interval loop asyncio (NESSUNA dipendenza nuova); event = subscribe bus con
  anti-eco `origin=="agent"` di default (+ rifiuto strutturale di trigger su `trigger.fired`);
  manual/`fire()` = seam hotword futuro. Ogni fire = background task osservabile + attention a
  fine turno. NESSUN trigger registrato di default e NESSUNA superficie di registrazione
  (tool/REST) — interfacce, non comportamenti (spec §8).
- **Turno headless** (`api/routes/chat/headless.py::run_headless_turn`): un turno autonomo È un
  turno normale — riusa `TurnAssembler` (reso `websocket: WebSocket | None`, 7 send guardate) +
  executor + `_persist_final_turn`, stessa pipeline/mode/scope. `NullEventSink` (sink.py) +
  `HeadlessInteractionChannel` (channel.py: `request()`→None ⇒ conferme REJECTED, `connected=True`);
  `_strip_ui_tools` toglie `client_execution` E `user_interaction` (ask_user) dall'offerta.
  Iniettato nel TriggerService da `bootstrap/jarvis.py` (`stage_jarvis`, DECIMO e ultimo stage;
  shutdown del trigger PRIMO in `shutdown.py`).
- **Subagent nella policy centrale**: `PermissionService.explain_denial(...)` (ALLOW→None,
  NEEDS_CONFIRMATION→negazione pulita, mode None→STRICT); `_subagent.py` gate per-call via ctx
  duck-typed (plugin non importa services) + **enforcement `offered_names` al punto di
  esecuzione** (fix F1: un nome allucinato, incl. i meta-tool bloccati, viene rifiutato anche se
  il modello lo emette) + `progress_cb` → background task in `_spawn_subagent`.
- **Voce**: seam morto `agent.voice.max_tools` ATTIVATO — `_apply_voice_trim` in `_assembly.py`
  quando `data["source"]=="voice"`; FE invia `{source:'voice'}` SOLO sull'auto-send del
  transcript STT (HorizonView:317). Stessa policy di gating, superficie ridotta.
- **Config**: `attention.{enabled,cooldown_s}`, `triggers.{enabled,max_concurrent_turns}`;
  flag censiti in `docs/flag-registry.md`. Default tutti true ma zero comportamento nuovo
  out-of-the-box (nessun trigger registrato).

## Decisioni registrate in Fase 8 (non rilitigare — dettagli nel piano, sez. «Decisioni di design»)

1. Tre service kernel in `services/`, campi `Any` in `PlatformServices` (niente Protocol dedicati).
2. Runner headless in api (l'assembly vive lì); iniettato via bootstrap (eccezione whitelisted
   `backend.core.bootstrap.* -> backend.api.**`). Spostare assembly in services = backlog 4.
3. Superfici mancanti = esiti puliti (filosofia fase 7), mai eccezioni.
4. NESSUNA dipendenza nuova (niente APScheduler); cron/RRULE ricchi = backlog.
5. Convenzione kwarg `origin` sugli eventi bus posata ORA; disciplina degli emettitori = backlog 13.
6. Osservabilità unificata: turni autonomi e subagent = background task; store FE nuovo
   `backgroundTasks` (WS-only, niente REST = backlog 2).
7. AttentionService v1 minimale; interrupt/queue riservati.
8. Voce per-messaggio (`source` su WsUserMessage), non per-connessione.

## Workflow collaudato (riusare così; raffinamenti fase 8 inclusi)

- Per fase: branch dedicato → `writing-plans` (codice VERBATIM) → `subagent-driven-development`:
  implementer (sonnet) per task; spec review = CONTROLLER su diff verbatim; quality review (top)
  per i task core/security; review FINALE di fase (top, range intero, angolo cross-task) SEMPRE.
- **Raffinamento fase 8 (anti-race, più forte della regola fase 7): gli implementer NON toccano
  git** (nessun add/commit) — committa SOLO il controller, con path espliciti, al rientro di ogni
  agente, dopo spec-check del diff. Così più implementer girano in parallelo su file disgiunti
  senza race sull'index, e il controller può committare mentre altri lavorano.
- **Agente morto (session-limit/API error) → SendMessage per COMPLETARE dal transcript, non
  ripartire** (fase 8: 4 agenti interrotti dal limite sessione, tutti ripresi con successo).
- I fix di review enumerati con precisione li applica il CONTROLLER (con test di regressione se
  behavioral: fase 8 → F1/F3/F4 hanno test dedicati); i fix che richiedono giudizio tornano
  all'implementer. Ogni esito/fix aggiorna ANCHE il piano; finding fuori task → backlog.
- Le review trovano cose VERE anche a fase matura — fase 8: subagent eseguiva tool MAI offerti
  (bypass del blocklist anti-ricorsione via nome allucinato), schedule loop che moriva in
  silenzio, task fantasma su CancelledError. NON saltare i cicli né la review finale.
- Commit convenzionali + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
  Mai push/merge senza richiesta esplicita.

## Gotchas (aggiornati post-fase 8)

1. **Suite backend completa IMPRATICABILE** (fixture `app` ~25s/test; `test_app.py` = 129s per
   5 test). Verifica di fase = test mirati + `tests/contracts/`. NON killare run lenti.
2. **Gate FE completo = typecheck + lint (0/0) + vitest** (ora 30 file / 304 test, <1s).
3. **ruff/mypy pre-esistenti** → scoped sui file toccati; `core/event_bus.py` ha 2 errori storici
   (UP035, B905 — backlog 8); file NUOVI puliti.
4. **EOL**: MAI usare `Add-Content`/`Out-File` PowerShell per appendere a file di codice — scrive
   CRLF (incidente fase 8 su `test_trigger_service.py`, rilevato con `git ls-files --eol`
   [`w/mixed`] e normalizzato con `sed -i 's/\r$//'` PRIMA del commit). Usare gli edit tool.
   SEMPRE `git ls-files --eol` prima dei commit.
5. **Subagent**: prescrizioni ESATTE, perimetro file esplicito, «ignora le modifiche uncommitted
   altrui», e VERIFICARE IL DIFF al ritorno; reviewer READ-ONLY espliciti (mai npm install).
6. **`check-contracts.ps1` DOPO il commit** (untracked = dirty). Regen SOLO nel task previsto;
   tra regen e task FE il typecheck FE fallisce BY DESIGN (dispatcher esaustivo).
7. **PowerShell 5.1**: niente `&&`; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`;
   lint-imports dalla REPO ROOT. Occhio alla cwd persistente tra chiamate (un `cd backend` resta).
8. **Il venv NON ha pip** → `uv pip install`.
9. **`ToolResult.error()` riempie `error_message`, NON `content`**.
10. **Contratti WS**: frame server nuovo = 4 punti (classe, union, frozen vocab test, handler FE
    post-regen). `WsUserMessage` è UNTAGGED (fuori dall'union client): il pump chat NON valida
    Pydantic i frame utente inbound a runtime — i campi extra sopravvivono nel dict raw (è così
    che `source` arriva all'assembler).
11. **`test_plugins_enabled_list` rosso ereditato** (21 vs 20): non è una regressione.
12. **File "modified since read"**: dopo che un subagent tocca un file letto dal controller,
    ri-Read prima di Edit.
13. **pytest asyncio_mode=auto** nel backend: i marker `@pytest.mark.asyncio` sono ridondanti ma
    innocui e coerenti coi test esistenti.

## Backlog (voci complete in fondo al piano fase 8; principali)

1. Superficie di registrazione trigger (tool + REST + persistenza) e cron/RRULE reali.
2. REST `GET /api/background-tasks` per idratazione store (oggi WS-only).
3. Provenance/origin su `Message` (DB) per distinguere i turni autonomi in UI.
4. Spostare `TurnAssembler`/`_persist_final_turn` da api a services/turn.
5. AttentionService ricco (code+drain, INTERRUPT reale, preferenze per-sorgente); UI Horizon per
   i background task.
6. **(Sicurezza, PRE-esistente, condiviso col turno normale)** bypass bare-name del gate: risolvere
   il nome tool PRIMA di `decide()` o gateare post-risoluzione in `execute_tool` (piano, voce 12).
7. Test integrato «headless + confirmation-required → REJECTED» che inchioda §4.5 (voce 10).
8. Ereditati fasi 1-7: grant per-comando, capability nel frame di conferma, esenzione dedup
   ui_command, hook change-notification manifest; migrare useVoice a pattern tipizzato;
   `.gitattributes`; migrazione consumer ai gruppi ctx; ecc. (vedi piani fase 6/7).

## Decisioni utente registrate (non rilitigare)

- Refactor incrementale, app sempre funzionante; dati azzerabili; DUE superfici chat di prodotto
  (Workspace `/workspace` primaria + Horizon `/assistant`) — il Workspace NON si rimuove MAI;
  visione = runtime agentico locale con Command Layer (invariante anti-escalation §7) e
  fondamenta Jarvis §8 (autonomia SEMPRE dentro i guardrail, §4.5).
- Push e merge SOLO su richiesta esplicita dell'utente, volta per volta. Il branch
  `arch/fase8-fondamenta-jarvis` attende la decisione dell'utente.
