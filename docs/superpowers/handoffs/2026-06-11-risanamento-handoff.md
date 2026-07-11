# Handoff — Risanamento architetturale AL\CE (stato al 2026-06-11)

> Per la sessione che continua questo lavoro a contesto fresco. Contiene SOLO ciò che non è
> ricostruibile dal repo: stato, decisioni, gotchas scoperti sul campo, recon già fatta.
> Fonti di verità nel repo: spec e piani citati sotto.

## Stato del programma

- **Spec normativa** (approvata, committata): `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` — 8 fasi, principi §4, criteri §9. È LA fonte di verità.
- **Fase 1a (Contratti REST): COMPLETATA** — branch `arch/fase1a-contratti-rest`, 9 commit sopra `main` (base `a229774`, head `e4a9ef2`), review finale "ready to merge", **NON mergiata per scelta dell'utente** (tenere il branch così com'è).
- Piano 1a chiuso e veritiero: `docs/superpowers/plans/2026-06-10-fase1a-contratti-rest.md` (in fondo: banner di completamento + **backlog per 1b**).
- Pending: chip/task separato `task_6c67e5a8` per il fix della suite lenta (vedi gotchas).

## Prossimo lavoro: Piano 1b — schema WS tipizzato

Da scrivere con la skill `writing-plans` (brainstorming già fatto: la spec §6 È la decisione). Requisiti dalla spec:
- Modelli Pydantic per OGNI messaggio dei due canali WS in `backend/api/ws_schema/`; envelope piatto con `type` (Literal discriminante), `origin` (`user|agent|system`), `correlation_id?` — il formato wire attuale è piatto: NON introdurre wrapping `payload` (deciso in fase di design: stessa garanzia, zero migrazione doppia).
- Da Pydantic → JSON Schema → tipi TS come **unione discriminata su `type`** (pipeline analoga a `gen-contracts.ps1`; estendere lo script, non duplicarlo).
- Rinomina eventi alla convenzione `dominio.azione` (oggi convivono `calendar_changed` e `mcp.server.connected`).
- FE: `useEventsWebSocket.ts` diventa dispatcher tipizzato (mappa esaustiva `type → handler`).

### Recon WS già fatta (2026-06-10 — riverificare a campione i fatti load-bearing prima di scrivere il piano)

**Chat WS** (`/api/ws/chat`, handler `backend/api/routes/chat/ws.py`, sink `services/turn/sink.py`):
- Client→server: messaggio utente (`content`, `conversation_id?`, max 50k), `cancel`, `tool_confirmation_response`, `client_tool_result`, `ask_user_response` (tutti con `execution_id`; validati in `chat/channel.py` ~313-321).
- Server→client, 4 famiglie: legacy streaming da `llm_service.py` (`token`, `thinking`, `tool_call`, `usage`, `done`, `error`); eventi turno canonici da `services/turn/events.py` (`turn.started/llm_step/usage/finished`, `tool.call/result`, `interaction.requested/resolved`); tool-loop da `tool_loop.py`/`pipeline.py` (`tool_execution_start/done`, `tool_progress`, `context_compression_*`, `context_info`, `llm_requery`, `warning`); reflective (`agent.critic_invoked`, `agent.warning`).
- FE: unione `WsMessage` in `types/chat.ts` (~righe 483-499), manager `services/ws.ts` (dispatch su `data.type`).

**Events WS** (`/api/events/ws`, `backend/api/routes/events.py`):
- Client→server: `ping`, `terminal.input` (`conversation_id`, `session_id`, `data`), `terminal.resize` (+`rows`, `cols`).
- Server→client: enum `AliceEvent` (37 membri, `core/event_bus.py:28`) bridgiati nel lifespan di `app.py` (~533-638: `mcp.server.*`, `email.*`, `note.*`, `service.status`, `knowledge.status`); eventi terminal da `services/terminal/manager.py` (`terminal.session_opened/renamed/assigned/closed/output`); ad-hoc da callback (`artifact.created`, `tasks.updated`, `plan_document.updated`, `scope.updated`, `permission_mode.updated`, `calendar_changed`, `service.model_download_progress`); `heartbeat`/`pong`.
- FE: `composables/useEventsWebSocket.ts` — catena if/else su ~18 tipi (righe ~105-179) che smista a 11 store; `sendEventsMessage` usato SOLO da `stores/terminalSessions.ts` (~206-224).
- Tipi `Ws*Message` già a mano in `types/{tasks,planDocument,scope,permission,terminal}.ts` — in 1b diventano generati.

## Workflow collaudato (riusare così)

- **Per fase**: branch dedicato `arch/faseXx-...` → skill `subagent-driven-development`: implementer (haiku per task meccanici con codice verbatim nel piano, sonnet per multi-file/tooling) + spec reviewer + quality reviewer (modello top, sempre) + fix loop con re-review mirata → review finale di fase → skill `finishing-a-development-branch`.
- I piani contengono codice **verbatim** e comandi esatti; ogni fix di review aggiorna ANCHE il piano (il piano resta veritiero, sempre).
- Commit: messaggi convenzionali + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Mai push senza richiesta.
- Le review hanno trovato 3 bug veri in questa fase (CRLF, guardrail spegnibile, gate verde su errore git): NON saltare i cicli di review.

## Gotchas scoperti sul campo (costati tempo — non riscoprirli)

1. **Suite backend completa IMPRATICABILE**: la fixture `app` (conftest) costa ~25s di setup PER test (lifespan completo) → la suite intera richiede ore. Verifica di fase = test mirati (`tests/contracts/` + domini toccati). Misurato: `test_branch_conversation.py` 14 test = 6:41 min, tutti nel setup. Fix tracciato come task separato.
2. **`npm run lint` fallisce repo-wide per errori pre-esistenti** → gate FE = `npx eslint <file toccati>` + `npm run typecheck` (questo sì exit 0 obbligatorio).
3. **`ruff check api/` ha 56 errori pre-esistenti** → ruff scoped ai file toccati.
4. **Trappola CRLF su Windows**: ogni file scritto da codice e destinato al commit DEVE usare `newline="\n"` (`Path.write_text`). Già pagata due volte.
5. **`check-contracts.ps1` va eseguito DOPO il commit** (file untracked = dirty per il gate).
6. **Rigenerare la baseline ratchet** = `$env:ALICE_REGEN_CONTRACT_BASELINE="1"` + pytest → **fallisce apposta** dopo la scrittura (anti-leak); rilanciare senza env var.
7. **`TestClient(app)` senza context manager = lifespan MAI eseguito** → la route prende i rami difensivi (usato per il wire test; utile per test veloci senza i 25s).
8. **Gli audit dei subagent Explore sbagliano nei dettagli** (es. tabella response_model errata su scope/permission_mode): verificare a mano i fatti load-bearing prima di metterli in un piano.
9. **PowerShell 5.1**: niente `&&`; `2>$null` su exe native + pipe ingoia l'output (un run pytest è "sparito" così — usare Bash tool o log su file); `$LASTEXITCODE` va controllato esplicitamente dopo ogni exe nativa negli script.
10. Convenzioni d'ambiente: import `from backend.*`; pytest da `backend/`; venv `.venv` alla radice; `python -m backend.api.openapi_export` dal root del repo.

## Backlog immediato (dettagli in fondo al piano 1a)

1. **CI minima a inizio 1b** (pytest contracts + check-contracts su runner windows + typecheck) — i gate diventano reali solo in CI.
2. Request-side enum su `PermissionModeUpdateRequest.mode` (decisione 400-vs-422 quando si tocca l'endpoint).
3. `AgentTier` duplicato a mano in `frontend/.../types/settings.ts:171` (violazione §4 pre-esistente).
4. Burn-down della baseline ratchet (94 voci) dominio per dominio nelle fasi 2-6, con convenzione liste `{items,total}`.
5. Pin esatto `openapi-typescript` o nota "codegen solo via npm ci".

## Decisioni utente registrate (non rilitigare)

- Refactor incrementale, app sempre funzionante; dati azzerabili (no migrazioni); orb-era UI da eliminare (Horizon unica superficie); codegen completo; visione = runtime agentico locale stile Claude Desktop con Command Layer (l'agente pilota il programma, invariante anti-escalation non negoziabile, spec §7).
