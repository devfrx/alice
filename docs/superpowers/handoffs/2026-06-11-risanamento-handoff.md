# Handoff — Risanamento architetturale AL\CE (stato al 2026-06-11, sera, post-Fase 1b)

> Per la sessione che continua questo lavoro a contesto fresco/compattato. Contiene SOLO ciò che
> non è ricostruibile dal repo: stato, decisioni, gotchas pagati sul campo, recon da fare.
> Fonti di verità nel repo: spec e piani citati sotto. Questo file SOSTITUISCE la versione
> precedente (pre-1b); la storia è in git.

## Stato del programma

- **Spec normativa** (approvata): `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` — 8 fasi, principi §4, criteri §9. §6 aggiornata alla decisione envelope piatto. È LA fonte di verità.
- **Fase 1a (Contratti REST): COMPLETATA** — branch `arch/fase1a-contratti-rest` (head `a209957`), NON mergiato per scelta utente.
- **Fase 1b (Schema WS tipizzato): COMPLETATA** — branch `arch/fase1b-ws-schema` (figlio di 1a, 22+ commit, review finale "READY TO MERGE"), **NON mergiato per scelta utente** ("committa solo", branch tenuti così). Piano chiuso e veritiero con note di review per task: `docs/superpowers/plans/2026-06-11-fase1b-ws-schema.md` (in fondo: criteri di uscita + backlog).
- Piano 1a chiuso: `docs/superpowers/plans/2026-06-10-fase1a-contratti-rest.md`.
- Pending esterni: chip/task separato `task_6c67e5a8` (fix suite lenta); CI `contracts.yml` MAI eseguita (parte al primo push — sorvegliare la prima run); criterio di uscita 3 della 1b (verifica end-to-end ad app avviata) da spuntare al primo avvio dev.

## Cosa ha consegnato la 1b (mappa rapida, dettagli nel piano)

- `backend/api/ws_schema/`: `_base.py` (envelope piatto `WsFrame`: `origin` default per famiglia, `correlation_id?`, `extra="forbid"`), `events.py` (24 server + 3 client), `chat.py` (27 server + 4 client taggati + `WsUserMessage` SENZA `type`), `__init__.py` (TypeAdapters, vocabolari congelati `*_TYPES`, `WS_CONTRACT_ADAPTERS`, validatori), `guard.py` (warn in prod, raise sotto `ALICE_WS_STRICT_CONTRACTS=1`, settato in `tests/conftest.py`).
- `openapi_export.py::_inject_ws_schemas` inietta le 5 unioni come components → lo stesso `gen-contracts.ps1` di 1a genera le unioni TS discriminate.
- FE: i tipi WS in `types/{chat,turn,tasks,planDocument,scope,permission,terminal,email,artifacts}.ts` sono RE-EXPORT (`ApiSchema<'...'>`); `useEventsWebSocket.ts` = dispatcher esaustivo (`EventsHandlerMap`, chiave mancante = errore di compilazione) + `sendEventsMessage` tipizzato su `EventsClientMessage`.
- Guard iniettato per DI (mai import `api` da `services`): `WSConnectionManager.set_frame_validator` (wired in `core/app.py:531`), `WebSocketEventSink`/`WebSocketInteractionChannel` param `frame_validator` (wired in `api/routes/chat/ws.py:108,165`).
- `.github/workflows/contracts.yml`: pytest `tests/contracts/` + `check-contracts.ps1` + typecheck FE su windows-latest.
- Rinomina wire: `calendar_changed` → `calendar.changed`.
- Test: `backend/tests/contracts/` ora 82 test (export, ratchet response_model, wire permission, ws events/chat/guard). Gate verdi a fine fase: 109 mirati backend, typecheck FE 0, vitest 259/259, check-contracts verde.

## Decisioni registrate in 1b (non rilitigare)

1. **Envelope piatto**, NESSUN wrapper `payload` (spec §6 già emendata). `origin`/`correlation_id` hanno default: il filo attuale non li emette, i modelli restano veritieri; l'emissione di `origin` è burn-down fasi 2-6.
2. **`--default-non-nullable false`** nello script `gen:api:types` (senza: i campi con default diventano OBBLIGATORI nel TS → contratto falso). Non rimuoverlo.
3. **`WsPermissionModeUpdated.mode` è un Literal**, non l'enum (collisione `$defs` col component REST); il test `test_mode_literal_matches_enum` li tiene sincronizzati.
4. **I nomi legacy dei frame chat** (`token`, `done`, `tool_execution_*`…) restano fuori da `dominio.azione` fino alla Fase 6 (rinominarli ora = churn senza consumatori nuovi).
5. **`WsUserMessage` resta senza `type`** (il pump del channel tratta i frame non riconosciuti come messaggio utente — compat wire).
6. **Limite dichiarato del guard**: gli emettitori events passano da callback best-effort / bus con `return_exceptions=True` → il raise strict lì viene assorbito (resta il log). Enforcement primario = contract test; il wiring dei chokepoint non ha ancora copertura automatica (la avrà col primo test d'integrazione che attraversa `ws_chat` o il manager).

## Prossimo lavoro: Fase 2 — Persistenza (spec §5.2)

Da scrivere con `writing-plans` su branch `arch/fase2-persistenza` (figlio di `arch/fase1b-ws-schema`: le fasi si impilano finché l'utente non merge-a). Requisiti spec: SQLite unica fonte di verità; RIMOZIONE del mirror JSON automatico (`services/conversation_file_manager.py` + rebuild da JSON allo startup); al suo posto comando di export/backup esplicito (tool + voce UI); dati azzerabili, niente migrazioni. Le fasi 2-4 dipendono solo dalla 1; ordine consigliato 2→3→4.

### Recon da fare PRIMA di scrivere il piano 2 (non fatta, solo puntatori noti)

- `services/conversation_file_manager.py` (il mirror); `_sync_conversation_to_file` usato da `api/routes/chat/ws.py` e `_persist.py` (via `_helpers.py`); il rebuild JSON→DB nel lifespan di `core/app.py`; chi altro legge/scrive `data/conversations/`.
- Verificare a mano i fatti load-bearing (gli audit dei subagent Explore sbagliano i dettagli — gotcha storico).
- Il ratchet REST (94 voci baseline) va bruciato per i domini toccati dalla fase, con convenzione liste `{items,total}` (backlog 1a).

## Workflow collaudato (riusare così)

- Per fase: branch dedicato → skill `writing-plans` (piano con codice VERBATIM e comandi esatti) → skill `subagent-driven-development`: implementer (haiku per task meccanici mono-file, sonnet per multi-file/judgment) + spec reviewer (sonnet) + quality reviewer (modello top, SEMPRE) + fix loop → review finale di fase (modello top) → `finishing-a-development-branch`.
- Ogni fix di review aggiorna ANCHE il piano (il piano resta veritiero, sempre); i finding fuori task finiscono nel backlog del piano o nei task successivi.
- Le review trovano bug veri a quasi ogni task (in 1b: exit-code CI ingoiati, `defaultNonNullable`, tipo sfuggito alla migrazione, send path non tipizzato). NON saltare i cicli.
- Commit convenzionali + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Mai push senza richiesta.

## Gotchas (i vecchi restano validi + i nuovi della 1b)

1. **Suite backend completa IMPRATICABILE** (fixture `app` ~25s/test). Verifica di fase = test mirati: `tests/contracts/` + domini toccati (per 1b: + `test_interaction_channel.py`, `test_tool_loop.py`).
2. **`npm run lint` fallisce repo-wide** (pre-esistente) → gate FE = `npx eslint <file toccati>` (warnings prettier pre-esistenti ovunque: contare solo gli ERRORI) + `npm run typecheck` exit 0.
3. **ruff/mypy hanno errori pre-esistenti** in molti file `api/`/`services/` → scoped ai file/righe toccati; nuovi file sempre puliti.
4. **CRLF**: ogni file scritto da codice destinato al commit usa `newline="\n"`.
5. **MOJIBAKE PowerShell 5.1** (pagato in 1b): `Get-Content -Raw`/`Set-Content`/`WriteAllText` su file UTF-8 senza BOM li leggono come ANSI → MAI editare file con non-ASCII via PowerShell; usare il tool Edit o Bash+python (`io.open(..., encoding="utf-8", newline="")`). Se succede: `git checkout -- <file>` e rifare.
6. **Subagent haiku + here-string PowerShell** = marker `@'`/`'@` che finiscono nel messaggio di commit (successo 2 volte; il subject di `2cc996c` ha un "@ " residuo, cosmetico, lasciato). Nei prompt dare la forma `git commit -m "subject" -m "Co-Authored-By: ..."` e scrivere ESPLICITAMENTE "trailer exactly `Claude Fable 5`" (altrimenti firmano col proprio modello).
7. **`check-contracts.ps1` DOPO il commit** (untracked = dirty). Baseline ratchet: `$env:ALICE_REGEN_CONTRACT_BASELINE="1"` + pytest → fallisce APPOSTA, rilanciare senza env var.
8. **`TestClient(app)` senza context manager** = lifespan mai eseguito (rami difensivi; usato per wire test veloci).
9. **PowerShell 5.1**: niente `&&`; `2>$null` su exe native ingoia output; `$LASTEXITCODE` esplicito dopo ogni exe nativa negli script; sotto `shell: pwsh` in GitHub Actions solo l'ULTIMO comando propaga l'exit code (per questo gli if-check per riga nel workflow).
10. Ambiente: import `from backend.*`; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`; venv `.venv` alla radice; `python -m backend.api.openapi_export` dal root.
11. **Contratti WS d'ora in poi**: aggiungere/cambiare un frame = modello in `ws_schema` + vocabolario congelato nel test + frame rappresentativo + rigenerare contratti + handler nel dispatcher FE (il typecheck lo forza). `extra="allow"` SOLO dove documentato (`tool_progress`, `model_download_progress`, `WsTaskStep`).

## Backlog (oltre a quello in fondo ai piani 1a/1b)

1. Burn-down baseline ratchet REST (94 voci) + convenzione `{items,total}` nelle fasi 2-6, dominio per dominio.
2. `AgentTier` duplicato a mano in `frontend/.../types/settings.ts:171` (violazione §4 pre-esistente).
3. Il plugin calendar NON emette `calendar.changed` (i tool mutano senza broadcast; UI solo via polling) — chiudere quando si tocca il dominio calendar (§4).
4. Freshness gate vs dipendenze backend non pinnate (fastapi/pydantic `>=`): se il gate flappa, constraints file + parità versione Python (CI 3.11 vs dev 3.13).
5. Canale voice (`useVoice.ts`, `types/voice.ts`) hand-typed, fuori scope 1b.
6. Due narrowing `as` in `stores/services.ts:238,262` (contratto stringly-typed lato BE) — rivedere quando si tipizza il dominio services.
7. Docstring drift in `services/turn/events.py:200-205` (elenca `disconnected` mai emesso, omette `failed`).
8. Valutare `npm run test` (vitest) nella CI quando si dimostra stabile.

## Decisioni utente registrate (non rilitigare)

- Refactor incrementale, app sempre funzionante; dati azzerabili (no migrazioni); orb-era UI da eliminare (Horizon unica superficie); codegen completo; visione = runtime agentico locale stile Claude Desktop con Command Layer (invariante anti-escalation non negoziabile, spec §7).
- I branch di fase restano NON mergiati e NON pushati finché l'utente non decide diversamente; si impilano (1b sopra 1a, 2 sopra 1b).
