# Handoff — Risanamento architetturale AL\CE (stato al 2026-07-11, post-Fase 7)

> Per la sessione che continua questo lavoro a contesto fresco/compattato. Contiene SOLO ciò che
> non è ricostruibile dal repo: stato, decisioni, gotchas pagati sul campo, recon da fare.
> Fonti di verità nel repo: spec e piani citati sotto. Questo file SOSTITUISCE la versione
> precedente (post-fase6, stesso path); la storia è in git.

## Stato del programma

- **Spec normativa** (approvata): `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` — 8 fasi, principi §4, criteri §9. È LA fonte di verità.
- **Fasi 1a, 1b, 2, 3, 4, 5, 6: COMPLETE e MERGIATE in `main`** (merge sequenziali `--no-ff`,
  ultimo `5aa2660`; correzione Workspace `bbd05cb` = HEAD di main). Branch `arch/fase*` anche su origin.
- **Fase 7 (Command Bridge): COMPLETA su `arch/fase7-command-bridge`** (base `bbd05cb` = main,
  HEAD `a55bc1f`) — **NON pushata, NON mergiata**: la politica di merge la decide l'utente volta
  per volta. Review finale di fase: «Phase ready with notes», note applicate. Piano chiuso e
  veritiero con esiti review per task + verdetto finale + backlog:
  `docs/superpowers/plans/2026-07-11-fase7-command-bridge.md`.
- Pending esterni: CI `contracts.yml` da verificare su GitHub per i push di main del 2026-07-11;
  chip/task `task_6c67e5a8` (fix suite lenta); **smoke funzionale interattivo MAI eseguito**
  (né fase 6 né 7): alla prima `npm run dev` fare ENTRAMBE le checklist (gate finale piano fase 6
  + step 9.6 piano fase 7).

## Cosa ha consegnato la Fase 7 (mappa rapida, dettagli e esiti review nel piano)

- **Contratto WS Command Layer**: frame `command.request` (server→client, `origin="agent"`,
  `correlation_id` OBBLIGATORIO — primo consumatore reale del campo riservato in 1b),
  `command.result` e `command.manifest` (client→server) + `CommandManifestEntry` in
  `api/ws_schema/events.py`; vocabolari congelati aggiornati; il manifest è il TERZO contratto
  e viaggia nella stessa pipeline codegen (nessuna modifica alla pipeline: hoisting automatico
  via unioni).
- **Kernel tools**: meccanismo generico in `core/tools/` — `ToolCatalog.register_kernel_tool`
  (nome BARE, owner fittizio `KERNEL_TOOL_OWNER="kernel"` in `plugin_models.py`, sopravvive ai
  refresh e vince le collisioni), probe availability short-circuit su owner kernel, dispatch
  dedicato nell'executor (stessa pipeline timeout/validazione/sanitizzazione), facade+protocol.
- **`CommandBridgeService`** (`services/command_bridge.py`, gruppo `workspace`): manifest store
  con **anti-escalation STRUTTURALE** (grammatica `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$` +
  NFKC+strip PRIMA del check sui domini guardrail `permission|permissions|permission_mode|scope|
  guardrail|guardrails`; capability fuori vocabolario respinte; `commands.disabled_commands`);
  RPC pending-future su `correlation_id` (broadcast → `wait_for` con `commands.rpc_timeout_s`,
  default 10s < `timeout_ms` 30s del tool); OGNI fallimento è un risultato pulito ("UI not
  available", "Unknown command…", timeout) — mai eccezioni; a bridge disabilitato il manifest è
  IGNORATO (early-return: niente ingestione né registrazione tool). A ogni manifest il tool
  `app_command` viene RI-registrato con enum dei nomi nei parameters (l'executor valida gratis)
  e `usage_guidance` che elenca i comandi.
- **Gating**: `PermissionService.decide` step "2-bis" — tag statico `ui_command`, capability
  EFFETTIVA per-call risolta via `command_capability_provider` (= `bridge.capability_of`).
  Matrice §7: navigation/read ALLOW ovunque (plan incluso); mutate/destructive DENY in plan,
  CONFIRM in strict; auto_edits ALLOW mutate / CONFIRM destructive; autopilot ALLOW; ignoto →
  destructive (fail-conservative). Un IBRIDO `ui_command`+fs/exec NON prende il ramo: cade nel
  confinamento scope (il tag non scavalca mai il guard by-construction).
- **Wiring**: `WorkspaceServices.command_bridge_service` + property ctx; bridge creato in
  `stage_workspace` PRIMA di PermissionService; `app_command` registrato al boot con manifest
  vuoto se `commands.enabled`; route events valida l'inbound con `validate_events_client` e
  smista manifest/result al bridge (frame invalidi = drop loggato, mai socket giù).
- **Frontend**: `commands/bridge.ts` (proiezione manifest SOLO `exposeToAgent===true` + doppio
  check a esecuzione — anti-escalation su entrambi i lati), `commands/validate.ts` (validatore
  JSON-Schema-subset senza dipendenze, semantica own-property contro prototype-chain tricks,
  fallback "no-args" per comandi senza schema), handler `command.request` nel dispatcher
  esaustivo, manifest inviato a OGNI onopen. 4 comandi core esposti con `description`
  machine-facing: `view.switch`, `conversation.open`, `conversation.new`, `artifact.show`
  (`sidebar.toggle` resta UI-only). Config: `commands.{enabled,rpc_timeout_s,disabled_commands}`.

## Decisioni registrate in Fase 7 (non rilitigare)

1. **Tool kernel via catalogo, non plugin**: la spec impone "di proprietà del kernel"; nessun
   plugin fittizio — meccanismo kernel-tools nel catalogo con owner `kernel`.
2. **Gating dinamico dentro `decide()`** (provider iniettato), NON middleware dedicato; la
   conferma riusa ConfirmationMiddleware standard.
3. **RPC via broadcast** sul canale events (app single-window; primo `command.result` vince,
   duplicati no-op). `origin` di `command.result` resta default `user` (decisione contratto).
4. **Validatore FE fatto in casa** (subset noto, zero dipendenze — niente ajv).
5. Il test fase-6 "tutti exposeToAgent false" è stato DELIBERATAMENTE sostituito dal test
   "insieme esposto == {i 4 core}" (fase 7 è la fase che espone).
6. `always_offered=True` su `app_command`: superficie di protocollo; a manifest vuoto il tool
   esiste e risponde pulito.

## Prossimo lavoro: Fase 8 — Fondamenta Jarvis (spec §8, riga 217)

Da scrivere con `writing-plans` su branch `arch/fase8-fondamenta-jarvis` (base: decisa
dall'utente — main post-merge fase 7, o impilato su fase 7). Requisiti spec: `TriggerService`
(turni autonomi da cron/eventi bus/hotword; filtro default su `origin=agent` contro
l'auto-innesco), `AttentionService` (punto unico di decisione dell'iniziativa verso l'utente),
task in background osservabili (eventi tipizzati di avanzamento, store `tasks`); voce e
subagent ricondotti alla stessa policy di gating. Si posano INTERFACCE, non implementazioni
ricche. Dipende da fasi 5 e 7 (entrambe complete).

### Recon fase 8 — note utili già verificate in fase 7

- L'`origin` è su OGNI frame di entrambi i canali (default per classe base); `command.request`
  porta già `origin="agent"` — il filtro anti-eco del TriggerService ha il dato che gli serve.
- Lo store FE `tasks` + frame `tasks.updated` esistono già (agent run); il "task in background
  osservabile" formalizzato è da disegnare sopra.
- L'event bus (`core/event_bus.py`, `AliceEvent`) è il punto di aggancio dei trigger; i bridge
  bus→WS vivono in `bootstrap/surfaces.py`, i callback di servizio in conversation/workspace.
- Un turno autonomo "è un turno normale": l'ingresso oggi è solo il WS chat
  (`api/routes/chat/ws.py` + `_assembly.py`); serve un seam per avviare turni senza socket chat
  (l'`InteractionChannel` ha semantica di disconnessione — attenzione a conferme/ask_user in
  turni headless: oggi la conferma richiede il canale chat; la fase 7 ha già il precedente
  "UI not available" come risultato pulito).
- Backlog fase 7 rilevante per fase 8: grant per-COMANDO, capability nel frame di conferma,
  esenzione dedup per ui_command, hook change-notification del registry per il manifest.

## Workflow collaudato (riusare così; raffinamenti fase 7 inclusi)

- Per fase: branch dedicato → `writing-plans` (codice VERBATIM, comandi esatti) →
  `subagent-driven-development`: implementer (sonnet) per task; spec review = CONTROLLER quando
  il diff è verbatim-dal-piano (gate auto-verificanti); quality review (modello top) per i task
  core/security; review FINALE di fase (top, range intero, angolo cross-task) SEMPRE.
- I fix enumerati con precisione li applica il CONTROLLER direttamente; i fix che richiedono
  giudizio tornano all'implementer via SendMessage. Task di pura configurazione con gate
  auto-verificante → controller direttamente (fase 7: Task 7 regen).
- **Raffinamento fase 7**: implementer e reviewer possono girare IN PARALLELO se su file
  disgiunti; ma il controller NON committa mentre un implementer è attivo nello stesso worktree
  (race sull'index git: un `git add` concorrente può far inghiottire file altrui al commit) —
  applicare gli edit subito, DIFFERIRE il commit al rientro dell'agente. Dire agli agent di
  IGNORARE (mai stage-are) i file altrui modificati nel working tree, e al reviewer di ignorare
  le modifiche uncommitted.
- Ogni fix di review aggiorna ANCHE il piano (esito per task, sempre); finding fuori task → backlog.
- Le review trovano cose VERE anche in fase matura — fase 7: bypass unicode/prototype-chain su
  ENTRAMTI i validatori (BE nomi manifest, FE args), ibrido `ui_command`+fs che saltava il
  confinamento scope, master-switch che non spegneva davvero il tool. NON saltare i cicli né la
  review finale.
- Commit convenzionali + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Mai push/merge senza richiesta.

## Gotchas (validi anche dopo la fase 7)

1. **Suite backend completa IMPRATICABILE** (fixture `app` ~25s/test). Verifica di fase = test
   mirati per dominio + `tests/contracts/`. Subagent avvisati di NON killare run lente.
2. **Gate FE completo = typecheck + lint (0 err/0 warn) + vitest** (ora 29 file / 301 test, <1s).
3. **ruff/mypy con errori pre-esistenti** → scoped; file NUOVI puliti (`ruff --fix` sui test
   nuovi); `protocols.py` ha 3 errori storici (A002 ×2, I001) fuori dal codice fase 7.
4. **EOL**: nessun incidente in fase 7 (prima fase pulita). SEMPRE `git ls-files --eol` /
   `git diff --stat` prima dei commit; `.gitignore` è `i/mixed` STORICO (pre-programma).
5. **Subagent**: prescrizioni ESATTE e VERIFICARE IL DIFF al ritorno; reviewer READ-ONLY
   espliciti (mai npm install/ci); un agente morto → SendMessage per COMPLETARE, non ripartire.
6. **`check-contracts.ps1` DOPO il commit** (untracked = dirty). Regen SOLO nel task previsto.
7. **PowerShell 5.1**: niente `&&`; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`;
   boot-check e lint-imports dalla REPO ROOT (`.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml`).
8. **Il venv NON ha pip** → `uv pip install`.
9. **`ToolResult.error()` riempie `error_message`, NON `content`** (il loop rende error_message al modello).
10. **Campi generati opzionali**: fallback `??` nei consumer; ma i campi narrowed-required
    (es. `correlation_id` sui frame RPC) sono REQUIRED anche nel TS — narrowing pydantic
    sull'envelope è il pattern giusto PRIMA della regen.
11. **Contratti WS**: frame server nuovo = 4 punti (classe, union, frozen vocab test, handler FE
    post-regen — il typecheck FORZA il quarto). Frame client nuovo = classe + union + frozen
    vocab + branch nel receive loop della route (validare con `validate_events_client`).
12. **`test_plugins_enabled_list` è ROSSO ereditato** (21 vs 20): non è una regressione.
13. **File "modified since read"**: dopo che un subagent tocca un file letto dal controller,
    ri-Read prima di Edit.
14. **`Object.hasOwn` / semantica own-property** nei validatori TS di input non fidato — `in` e
    lookup nudi attraversano la prototype chain.

## Backlog (in fondo al piano fase 7 le voci complete; principali)

1. **Fase 7 → fase 8**: grant per-COMANDO (`app_command:{name}` in ConfirmationMiddleware);
   capability per-call nei metadata del frame di conferma (oggi mostra `safe` anche per
   destructive); esenzione DedupMiddleware per tool `ui_command`; short-circuit del confirm
   nella finestra manifest-vuoto; hook change-notification sul registry FE → re-invio manifest;
   cap su `usage_guidance`; clamp `rpc_timeout_s` vs `timeout_ms`; multi-window (broadcast
   esegue ovunque) se mai arriverà.
2. Ereditati fase 6: migrare useVoice a pattern tipizzato e ritirare l'emitter generico;
   `.gitattributes` + normalizzare i 4 file `w/crlf` storici; `auditApi` morto; CAD payload
   live su artifacts; TldrawCanvas orphan/camera; workspace store: stato sidebar morto;
   dedup GET whiteboard; `/` → `/workspace` vs `alice_ui_mode` persistito.
3. Ereditati fasi 1-5: migrazione consumer ai gruppi ctx; guardia anti-drift flag-registry;
   route MCP tipizzate + ratchet; 500→503 search; offset O(n); export conversazioni a modello;
   dedup broadcaster.

## Decisioni utente registrate (non rilitigare)

- Refactor incrementale, app sempre funzionante; dati azzerabili (no migrazioni); DUE superfici
  chat di prodotto (Workspace `/workspace` primaria + Horizon `/assistant`) — il Workspace NON
  si rimuove MAI (visione Jarvis); lint sanato a fondo con gate CI; codegen completo; visione =
  runtime agentico locale con Command Layer (invariante anti-escalation non negoziabile, §7).
- Push e merge SOLO su richiesta esplicita dell'utente, volta per volta. La fase 7 è locale su
  `arch/fase7-command-bridge` in attesa di decisione.
