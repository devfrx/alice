# AL\CE — Agente unico, fondazione professionale + esperienza "vero agente"

## Context

Oggi la input bar espone un toggle **Chat/Agente** (`agent.enabled`) che sceglie tra un path "lite" e quello agentico. L'utente vuole **eliminare la dualità**, tenere esclusivamente la via agentica e **perfezionarla** fino a un vero agente (stile pianificazione di Claude): il modello deve poter **fare domande all'utente** (risposta inline lato client), mostrare un **piano visibile come modulo del workspace**, e operare su **terminale/cartelle con scope** controllato.

Una revisione critica del codice ha però evidenziato che **costruire le feature sull'attuale fondazione non è professionale**: porterebbe a un loop monolitico, fragile e non modulare. L'utente ha scelto di fare la **fondazione completa prima delle feature** e di avere un **modello di turno/run canonico** per un'osservabilità ricca. Questo piano riflette quella scelta.

### Debiti strutturali rilevati (motivazione della fondazione)
1. **God-function di trasporto.** [`backend/api/routes/_tool_loop.py`](backend/api/routes/_tool_loop.py) è **1381 righe**, vive nel layer route e riceve un `WebSocket` grezzo; ogni capacità (conferma, client-exec) è un `if` inline. Aggiungere `ask_user`/terminale/scope come altri rami **viola la modularità**.
2. **Asimmetria I/O.** L'output è astratto (`WSEventSink` in [`services/turn/sink.py`](backend/services/turn/sink.py), con prod + test-double). L'input no: **4+ `receive_text()` concorrenti** sullo stesso socket (`_tool_loop.py:1146/1301/1366`, `direct_executor.py:444`, `chat/_shared.py:62`) — è la causa del workaround "v3-1 cancel reader". `ask_user` sarebbe il 5° lettore.
3. **Policy permessi mal-allocata.** Il flag conferme è `pc_automation.confirmations_enabled` (`_tool_loop.py:338`) e il timeout `pc_automation.confirmation_timeout_s` (`direct_executor.py:215`), ma gatano **tutti** i tool pericolosi. Lo scope nel disegno ingenuo è applicato **per-plugin** → footgun: un tool nuovo che dimentica il check evade la sandbox.
4. **Nessun modello di run canonico per il path model-driven.** Gli eventi strutturati (`AgentRun`, `agent.step_*`) sono in eliminazione; il loop model-driven emette solo `tool_execution_*` ad-hoc. Manca uno stream unico per piano live + attività + budget, e il piano persistito non viene re-iniettato tra turni.

### Decisioni dell'utente (confermate)
1. **Path unico — rip-out totale** (incluso il lite voce): un solo motore model-driven, niente toggle/`structured_mode`/bypass voce.
2. **Fondazione completa (A–E)** prima delle feature.
3. **Stream di eventi di turno canonico** (osservabilità ricca: timeline, budget, piano live, re-inject contesto).
4. **Domande inline in chat** via meta-tool `ask_user(question, options?)`.
5. **Piano = modulo di prima classe** persistito, "come gli altri moduli".
6. **Workspace scope**: una o più cartelle per-conversazione, mutabili **solo in idle**; **modulo Terminale** scoped; **fallback** sandbox effimera senza scope.

---

## Tassonomia delle capacità (riferimento per tutto il rework)

Ogni capacità va classificata in **una** categoria — niente ibridi impliciti.

| Categoria | Cos'è | Dove vive | Esecuzione | Namespace | Invocata da |
|---|---|---|---|---|---|
| **Engine / core** | Motore di turno, loop tool, sink, channel, middleware, servizi (Permission/Plan/Scope) | `backend/services/turn/`, `backend/services/` + DI in `core/context.py` | codice, transport-agnostic | — | il sistema |
| **Plugin nativo** | Capacità Alice che espone `ToolDefinition` + `execute_tool` | `backend/plugins/<name>/` (`PLUGIN_REGISTRY`) | server via `tool_registry.execute_tool` (dentro la pipeline) | `<plugin>_<tool>` | il modello |
| **Server MCP** | Tool **esterni** adattati | processo esterno via plugin `mcp_client` | RPC delegata | `mcp_<server>_<tool>` | il modello |
| **Meta-tool** | Tool del plugin `agent` che governa il loop (`update_plan`, `spawn_subagent`) | `backend/plugins/agent/` | server via `execute_tool` (blocking) | `agent_<tool>` | il modello |
| **Tool a interazione utente** | Tool che **sospende il loop** per input umano (`ask_user`) | `agent` plugin, tag `user_interaction` | **InteractionChannel** (no `execute_tool`) | `agent_<tool>` | modello chiede, utente risponde |
| **Tool client-executed** | Tool sullo stato UI vivo (continuum) | plugin nativo, `client_execution=True` | **InteractionChannel** (delega al client) | `<plugin>_<tool>` | modello chiama, client esegue |
| **Modulo frontend** | Pannello UI nel workspace | `composables/workspace/moduleRegistry.ts` | solo frontend; **non è un tool** | — | l'utente (apre) |
| **Comando `/` (futuro)** | UX di pre-parsing → risolve in tool-call/prompt/azione UI | seam predisposto (vedi §Comandi `/`) | non è un nuovo path | `/<command>` | l'utente |

**Regole applicate:** il **Terminale è un plugin nativo** (non MCP/non client/non modulo); il suo *modulo* è solo la UI. **`ask_user` è un tool a interazione utente** (categoria distinta). **Plan e Scope sono servizi core**: il modello tocca il piano solo via `update_plan`, e **non può impostare lo scope** (lo fa l'utente in idle) — fuori dal tool registry per sicurezza. Conferma/client-exec/`ask_user` diventano **lo stesso meccanismo** (InteractionChannel), non rami separati.

---

## Convenzioni (tutte le fasi)
- **Python**: `from __future__ import annotations`, type hints completi, async I/O, `pathlib`, `loguru`, docstring Google, 100 colonne, `ruff`/`mypy --strict`. Astrazioni come `Protocol` (come `WSEventSink`). Nuovi flag `ToolDefinition` default-`False`.
- **TS/Vue**: `<script setup lang="ts">`, Composition API, **no `any`**, scoped CSS, Pinia **setup-store**. Tipi che rispecchiano lo snake_case backend.
- **Contract consistency**: ogni nuovo frame WS / evento / DB model ha tipo TS + endpoint REST + store corrispondenti; nomi eventi centralizzati in `AliceEvent`.
- **Refactor sicuro**: le fasi di fondazione (1–3) sono **behavior-preserving** e si appoggiano alla rete di test esistente (`test_tool_loop.py`, `test_confirmation_toggle.py`, `test_direct_executor_*`, client-tool tests) adattata ai nuovi seam — nessun cambiamento di comportamento osservabile finché non arrivano le feature.

---

## Fase 0 — Path agentico unico (rip-out)

Obiettivo: `DirectTurnExecutor` unico motore; `ReflectiveTurnExecutor` solo wrapper opzionale via config; zero config/import morti.

**Eliminare**
- `backend/services/turn/agent_executor.py` (`AgentTurnExecutor`, `AnnotatingSink`).
- Pacchetto `backend/services/agent/` (classifier/planner/critic/runner/degeneration/prompts/models). **Eccezione:** `ReflectiveTurnExecutor` usa `CriticService` + `Verdict`/`VerdictAction` → estrarre il minimo in `backend/services/turn/_reflection_critic.py`, poi eliminare il resto.
- Test legati (`test_agent_executor_*`, `test_agent_critic_always_runs`, `_agent_helpers`).
- Frontend strutturato orfano (`useAgentRun.ts`, `AgentActivitySidebar.vue`, `AgentRunSummary`, `AgentPlanCard` legacy, `useAgentActivity`) — **verrà ricostruito pulito in Fase 3** sui nuovi eventi canonici.

**Modificare**
- `backend/services/turn/factory.py`: due esiti — `DirectTurnExecutor`, opzionalmente `ReflectiveTurnExecutor` se `agent.reflection.enabled`. Via `enabled`/`voice_mode_bypass`/`structured_mode`/`agent_components`.
- `backend/core/config.py::AgentConfig`: rimuovere `enabled`, `structured_mode`, `voice_mode_bypass` e i knob structured (`classifier`/`planner`/`critic`/`persistence` + timeout/retry/replan). **Tenere** `planning`, `delegation`, `reflection`, `subagent`.
- `backend/core/app.py`: eliminare il blocco "Agent Loop v2 components". `backend/core/context.py`: rimuovere `agent_components`.
- `backend/api/routes/config.py`: rimuovere lettura/validazione `agent.enabled`.
- Frontend: rimuovere il chip Agente da `components/chat/ChatToolControls.vue`; ripulire `stores/settings.ts` da `settings.agent.enabled` (grep i consumer prima).

**Voce (stesso motore, toolset ridotto)**
- Riusare il precedente `?scope=` (`chat/ws.py` → `continuum_scope`): `voice_scope`. In `chat/_assembly.py` un branch che **riduce il toolset** voce (escludi `spawn_subagent`, cap `agent.voice.max_tools` ~8). Niente bypass.

**Test:** riscrivere `test_turn_factory.py` (default→Direct; reflection→Reflective); nuovo `test_voice_scope_tools.py`.

---

## Fase 1 — Fondazione A+B: engine transport-agnostico + InteractionChannel

Obiettivo: estrarre il loop dal route e introdurre un **canale di interazione in ingresso** simmetrico al sink. **Comportamento invariato**, conferma e client-exec migrati sul canale.

**B — InteractionChannel (in, simmetrico a `WSEventSink`)**
- Nuovo `backend/services/turn/channel.py`:
  - `class InteractionChannel(Protocol)`: `async def request(self, kind, payload, *, execution_id, timeout_s, cancel_event) -> dict | None`, e un segnale `cancelled`.
  - `WebSocketInteractionChannel`: avvolge il WS con **un unico read-pump** (task) che legge i frame e li instrada: frame con `execution_id` pendente → risolve la future; frame `cancel` → set `cancel_event`; control-frame stale/ignoti → scartati. **Unifica** i 4+ `receive_text()` (incl. il cancel reader di `direct_executor.py:444` e `chat/_shared.py:62`).
  - `ScriptedInteractionChannel`: test-double (coda di risposte) — gemello di `RecordingEventSink`.

**A — Estrazione dell'engine**
- Spostare la logica del loop da `backend/api/routes/_tool_loop.py` a `backend/services/turn/tool_loop.py` (engine), che dipende da `EventSink` (out) + `InteractionChannel` (in) + `session` + servizi `ctx` — **mai** un `WebSocket` grezzo.
- `_request_confirmation` / `_execute_client_tool` diventano chiamate a `channel.request("tool_confirmation"|"client_tool_call", …)`. La persistenza/audit resta nell'engine.
- `direct_executor.py`: passare il `channel` invece di `sink._ws`; rimuovere il cancel reader dedicato (ora nel pump).
- `chat/ws.py` diventa **sottile**: costruisce `WebSocketEventSink` + `WebSocketInteractionChannel` attorno al socket e invoca l'engine; il main loop idle non compete più sul `receive` (lo fa il pump, che inoltra a `ws.py` i messaggi utente "non-interazione").
- `_tool_loop.py` resta come **shim sottile** di compat (o rimosso aggiornando gli import).

**Test:** adattare `test_tool_loop.py` / `test_confirmation_toggle.py` per usare `ScriptedInteractionChannel`; nuovo `test_interaction_channel.py` (routing per id, cancel, timeout, frame stale). Tutti i comportamenti pre-esistenti restano verdi.

---

## Fase 2 — Fondazione C+D: pipeline di middleware + PermissionService

Obiettivo: l'esecuzione di un tool passa per una **catena componibile**, e la policy permessi/scope è **centralizzata** (non per-plugin, non in `pc_automation`).

**C — Pipeline middleware**
- Nuovo `backend/services/turn/pipeline.py`: `class ToolMiddleware(Protocol)` con `async def handle(self, call, nxt) -> ToolResult`. Catena per ogni tool-call:
  1. `DedupMiddleware` (sposta la logica `seen`/hash da `_tool_loop.py`).
  2. `PermissionMiddleware` (forbidden/risk + confinamento scope → `PermissionService`).
  3. `ConfirmationMiddleware` (usa `InteractionChannel`).
  4. `InteractionMiddleware` (tool `client_execution`/`user_interaction` → `channel.request`, mai `execute_tool`).
  5. `ExecuteMiddleware` (`tool_registry.execute_tool`).
- L'engine (Fase 1) ora itera i tool-call **attraverso la pipeline**, niente più `if` inline. Ogni middleware è testabile in isolamento → la modularità torna.

**D — PermissionService (autorità centrale)**
- Nuovo `backend/services/permission_service.py` (DI in `AppContext`):
  - risk policy (forbidden→blocca; dangerous→conferma; ecc.);
  - **grant per-conversazione** ("always allow X in questo scope");
  - **confinamento scope**: dato un tool-call + i suoi argomenti-path + lo scope conversazione, decide allow/deny **by-construction**.
- **Capability tagging su `ToolDefinition`** (`backend/core/plugin_models.py`): nuovi campi opzionali `capabilities: tuple[str,...] = ()` (es. `"fs_read"`, `"fs_write"`, `"process_exec"`) e `path_args: tuple[str,...] = ()` (quali argomenti trasportano path). Così il guard è generico: qualsiasi tool taggato `fs_*` è confinato automaticamente — un tool nuovo che dimentica nulla **non** evade (deny-by-default se tocca path fuori scope).
- **Spostare la config conferme** da `pc_automation` a un blocco neutro `SecurityConfig`/`permissions` in `config.py` (`confirmations_enabled`, `confirmation_timeout_s`), con **migrazione retro-compatibile** delle vecchie chiavi (mappa legacy già presente nel pattern di `migrate_legacy_config_keys`). `pc_automation` continua a funzionare leggendo dal nuovo home.

**Test:** `test_pipeline.py` (ordine/short-circuit dei middleware), `test_permission_service.py` (risk/grant/scope deny-by-default), aggiornare `test_confirmation_toggle.py` al nuovo home config.

---

## Fase 3 — Fondazione E: stream di eventi di turno canonico + run UI + re-inject piano

Obiettivo: un **vocabolario unico** di eventi di turno per il path model-driven, consumato da una UI attività pulita; il piano persistito viene re-iniettato tra turni.

**Backend — eventi canonici (via sink)**
- Definire in `backend/services/turn/events.py` il vocabolario emesso dall'engine: `turn.started`, `turn.llm_step`, `tool.call`, `tool.result`, `interaction.requested`/`interaction.resolved`, `plan.updated`, `turn.usage` (token/step budget), `turn.finished`. (Riusa/normalizza i `tool_execution_*` esistenti dietro questi nomi.)
- `TurnRun` aggregate (opzionalmente persistito, tabella `turn_run` per timeline/audit) — un solo modello, non i frammenti structured eliminati.
- **Re-inject piano**: all'avvio turno l'engine carica il piano persistito (`PlanService`, Fase 5) e inietta `render_plan` nel contesto → il modello **continua** invece di ri-pianificare.

**Frontend — run store + attività (ricostruzione pulita)**
- `stores/agentRun.ts` (setup-store) che consuma i nuovi eventi canonici (sostituisce il `useAgentRun` strutturato eliminato in Fase 0).
- Componente attività (timeline step/tool + budget) — riusa lo stile del vecchio card, ma sui nuovi eventi. Budget step/token visibile.
- `composables/useChat.ts`: registrare i nuovi handler eventi; rimuovere i riferimenti agli eventi structured.

**Test:** `test_turn_events.py` (sequenza/coerenza eventi, budget), frontend `agentRun.store.spec.ts`.

---

## Fase 4 — Feature: meta-tool `ask_user` (inline, client-answered)

Sulla fondazione, è minimale.
- `backend/core/plugin_models.py`: flag `ToolDefinition.user_interaction: bool = False`. **Stesso file**: fissare il contratto futuro comandi `/` — dataclass `CommandDefinition {name, description, params_schema, kind}` (solo il tipo, vedi §Comandi `/`).
- `backend/plugins/agent/plugin.py`: tool `ask_user` (gate `agent.clarification`, default `True`), params `{question, options?}`, `user_interaction=True`, `risk_level="safe"`. Nessun `execute_tool`: lo gestisce `InteractionMiddleware` → `channel.request("ask_user", …)`.
- `chat/ws.py`/pump: il frame `ask_user_response` è instradato dal pump per `execution_id` (nessun ramo nuovo).
- Frontend: tipi `WsAskUserRequiredMessage`/`WsAskUserResponsePayload`; `stores/chat.ts` `pendingAskUser` legato al messaggio in streaming (render **inline**); nuovo `components/chat/AskUserPrompt.vue` (opzioni cliccabili + testo libero) → `respondToAskUser` (manda `ask_user_response`). Riusa il linguaggio visivo di `ToolConfirmationDialog.vue` ma inline.

**Test:** `test_ask_user_tool.py` (risposta→risultato tool e loop prosegue; timeout; cancel durante attesa via channel). Frontend `AskUserPrompt.spec.ts`.

---

## Fase 5 — Feature: piano come modulo persistito di prima classe

**Backend**
- DB model `ConversationPlan` (`conversation_id` PK/FK CASCADE unique, `steps` JSON `[{step,status}]`, `updated_at`). Auto-create.
- `backend/services/plan_service.py::PlanService` (async, `session_factory`, come `ArtifactRegistry`): `set_plan`/`get_plan`/`clear` (upsert). DI in `AppContext`.
- `backend/plugins/agent/plugin.py::_update_plan`: persiste via `PlanService` ed emette l'evento canonico `plan.updated` (Fase 3). L'engine lo re-inietta al turno successivo.
- REST `backend/api/routes/plans.py` (`GET /plans/{conversation_id}`).

**Frontend**
- `stores/plan.ts` (mirror `artifacts.ts`): `plansByConversation`, `fetch`/`ensureForConversation`/`applyPlanUpdated`.
- `composables/useEventsWebSocket.ts`: gestire `plan.updated`.
- `components/canvas/modules/PlanModule.vue` + entry `plan` in `moduleRegistry.ts` (`singleton`, `defaultZone:'right'`). Estrarre `PlanStepList.vue` presentational condiviso con la UI attività. Auto-open opzionale (gated da setting).
- Tipo canonico `PlanStep {step; status}` in `types/agent.ts`.

**Test:** `test_plan_service.py` (upsert/get/cascade/evento + re-inject). Frontend `plan.store.spec.ts`.

---

## Fase 6 — Feature: workspace scope + modulo Terminale

**6a — Scope service/stato/persistenza**
- DB model `ConversationScope` (`conversation_id` PK/FK CASCADE unique, `folders` JSON `list[str]`, `updated_at`).
- `backend/services/scope_service.py::ScopeService`: `get_scope`/`set_scope`/`clear_scope`/`validate_folder` (esiste, dir, no UNC/system — centralizza `validate_scope_root` riusando `pc_automation/security.py::validate_path` + `file_search/searcher.py::_validate_path`). DI in `AppContext`. **Il `PermissionMiddleware` (Fase 2) consuma lo scope** → confinamento centrale, niente check per-plugin.
- Config `WorkspaceScopeConfig` (`ALICE_SCOPE__`): `forbidden_paths`, `fallback_mode: "sandbox"|"disabled" = "sandbox"`, `sandbox_root: "data/workspaces"`, `current_dir` tracking per-conversazione (feeling shell tra comandi).

**6b — Guardia "solo in idle"**
- Registry busy per-conversazione (`set[str]` `_active_conversations` in `chat/_shared.py`), popolato prima di `engine.run(...)`, svuotato in `finally`. Le mutazioni scope verificano `conv_id not in _active_conversations` → altrimenti 409/`scope_locked`. Idle authoritative legato al ciclo di vita del turno.

**6c — API REST/WS**
- `backend/api/routes/scope.py`: `GET /scope/{id}` (folders + `is_idle`), `PUT /scope/{id}` (valida, 409 se busy, persiste, emette `SCOPE_UPDATED`), `DELETE /scope/{id}` (busy-guarded). `AliceEvent.SCOPE_UPDATED` bridge → broadcast.

**6d — Plugin Terminale (nativo, scoped, confermato, auditato)**
- Nuovo `backend/plugins/terminal/` (`PLUGIN_REGISTRY["terminal"]`, `plugin.py`, `security.py`, `executor.py`). `TerminalConfig` (`enabled=False`, `command_timeout_s`, `max_output_bytes`, `allow_network=False`).
- `ToolDefinition` `run_terminal_command` `{command, cwd?}`, `result_type="text"`, `risk_level="dangerous"`, `requires_confirmation=True`, **`capabilities=("process_exec","fs_write")`, `path_args=("cwd",)`** → il `PermissionMiddleware` lo confina **by-construction**; conferma+audit passano dalla pipeline (Fase 2), niente plumbing nuova.
- Confinamento (`terminal/security.py`): `resolve()` + `relative_to` contro gli scope root; rifiuta UNC/symlink-out/`..`/device Win32; esecuzione con `asyncio.create_subprocess_exec` (**no `shell=True`**), `cwd` pinnata, cap tempo/output, env ridotto, network off. Lockout post-screenshot **condiviso**: promuovere `ScreenshotLockout` in un modulo `core` di sicurezza usato da `pc_automation` e `terminal`.
- **Fallback senza scope (`sandbox`):** working-dir effimera `data/workspaces/{conversation_id}/` (creata lazy, confinata, disponibile). `fallback_mode="disabled"` → errore "no folder scope set".

**6e — Frontend**
- `stores/scope.ts`: `scopeByConversation`, `isIdle` (da `stores/chat.ts`), `fetch`/`setFolders`/`clear`/`applyScopeUpdated`. UI di mutazione disabilitata mentre genera.
- `components/.../ScopeManager.vue`: lista/aggiungi/rimuovi cartelle (folder picker via dialog Electron/preload), greyed-out con tooltip quando non idle.
- `components/canvas/modules/TerminalModule.vue` + entry `terminal` nel `moduleRegistry`. Apertura scoped via `openModule('terminal', { folder })`; output via eventi canonici `tool.call`/`tool.result`. `useEventsWebSocket.ts`: gestire `scope.updated`.

**Sicurezza (Fase 6):** confinamento by-construction (capability/scope nel middleware); rifiuto UNC/device/symlink/traversal; conferma+audit obbligatori; lockout condiviso; no `shell=True`; cap output/tempo; network off; mutazione scope solo in idle (anti privilege-escalation a turno in corso).

**Test:** `test_scope_service.py`, `test_scope_idle_guard.py` (409 se busy), `test_terminal_security.py` (traversal/UNC/symlink/timeout/lockout), `test_permission_scope_confinement.py` (un fs-tool fuori scope è negato dal middleware, non dal plugin). Frontend `scope.store.spec.ts`.

---

## Predisposizione comandi `/` (futuro, seam lasciato ora)

Oggi **non esiste nulla** (`ChatInput.vue` intercetta solo `Enter`). Principio: un comando `/` è **UX di pre-parsing** che risolve in tool-call/prompt/azione UI — **mai** un nuovo path. Seam minimo (solo contratto, nessuna UI) fissato in **Fase 4** (in `plugin_models.py`):
- **`CommandDefinition {name, description, params_schema, kind: "tool"|"prompt"|"ui"}`** + metodo opzionale `get_commands()` su `BasePlugin` (default `[]`): ogni plugin dichiara i propri alias `/` accanto ai tool.
- Futuro (non in questo piano): `CommandRegistry` (gemello di `ToolRegistry`) + `GET /api/commands`; frontend `ChatCommandPalette.vue` + `useCommandPalette.ts` + `stores/commands.ts`, agganciati in `ChatInput.vue::handleKeydown`.
- Esempi gratis una volta esistente: `/plan`→apre PlanModule; `/terminal <folder>`→TerminalModule scoped; `/scope add <folder>`→`PUT /scope` (idle); `/ask`→flusso `ask_user`. Tutti risolvono in capacità già definite → nessun sottosistema parallelo.

---

## Sequenza di rilascio
1. **Fase 0** rip-out — comportamento invariato per l'utente.
2. **Fasi 1–3 (fondazione)** — behavior-preserving, coperte dai test esistenti adattati; ognuna shippabile.
3. **Fase 4** `ask_user`, **Fase 5** piano, **Fase 6** scope+terminale — additive, ognuna shippabile (6 sotto-shippabile 6a-c → 6d → 6e).

La fondazione (1–3) **non cambia nulla per l'utente** ma rende le fasi 4–6 piccole e pulite, ed elimina i 4 debiti. È questo a rendere la fase agentica fluida e professionale.

---

## Verifica end-to-end
- **Backend** (da `backend/`): `ruff check .`, `mypy .`, `pytest tests/ -v`. Avvio: `python -m backend --reload --reload-dir backend`.
- **Frontend** (da `frontend/`): `npm run typecheck` (obbligatorio), `npm run lint`, `*.spec.ts`.
- **Manuale (dev)** con `scripts/start-dev.ps1`:
  - **Fase 0:** chat senza toggle; voce con toolset ridotto; nessun ref a `agent.enabled`.
  - **Fasi 1–3:** regressione verde (conferme/client-exec funzionano sul nuovo channel); cancel durante un'attesa di interazione è pulito (un solo reader); gli eventi canonici popolano la UI attività con budget step/token.
  - **Fase 4:** il modello chiama `ask_user` → prompt inline (opzioni+testo) → la risposta sblocca il loop; timeout e cancel gestiti.
  - **Fase 5:** `update_plan` apre/aggiorna il `PlanModule` live; il piano sopravvive a reload (`GET /plans/{id}`) e viene re-iniettato al turno dopo (il modello continua, non ri-pianifica).
  - **Fase 6:** scope impostabile solo in idle (409 se busy); `TerminalModule` scoped; un fs-tool/comando fuori cartella è **negato dal PermissionMiddleware**; senza scope si usa `data/workspaces/{id}/`; ogni comando richiede conferma e crea una riga di audit.
