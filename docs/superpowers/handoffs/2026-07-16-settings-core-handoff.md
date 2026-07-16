# Handoff — Rework settings-core (rework/settings-core)

**Data:** 2026-07-16 · **Aggiornato:** 2026-07-16 sera (audit follow-up, merge `410b84f`)
**Branch:** `rework/settings-core` — **MERGIATO in main** (`f24afe1`) **e pushato**
**Spec:** `docs/superpowers/specs/2026-07-16-settings-core-rework-design.md`
**Piano:** `docs/superpowers/plans/2026-07-16-settings-core-rework.md` (15 task)
**Metodo:** subagent-driven — ogni task: implementer + review task-scoped (spec+quality) + fix loop;
review olistica finale sull'intero branch (modello top-tier) con triage dei finding differiti.
Ledger completo: `.superpowers/sdd/progress.md` (gitignored, locale).

## Stato: CHIUSO — feature completa, e2e verificato, follow-up risolti

Feature completa end-to-end: config a 5 layer con layer `preferences` formale (DB), tutti e sei
i segreti nel Credential Manager di Windows via SecretStore, PUT/PATCH sul motore unico
`set_many` + registry reazioni, migrazione one-shot idempotente, FE diff-save con flag derivati.
Il doppio sistema e lo split-brain sono morti strutturalmente (test di regressione dedicato).

### Cosa resta del task 16 (equivalente) — stato finale (audit follow-up 2026-07-16 sera)

1. **Suite pytest integrale: non completabile su questa macchina** — si appende dopo un fail
   a ~91% in zona `test_voice_tool_calling.py`, identico anche sulla baseline di main
   (pre-esistente, AUD-008 aperto — vedi handoff OpenRouter, Task 16 punto 1, e
   `docs/superpowers/audits/2026-07-16-followups-audit.md`). Sottoinsiemi mirati tutti verdi.
2. ~~E2E con l'utente~~ → **VERIFICATO FUNZIONANTE dall'utente** (2026-07-16, checklist al
   §E2E sotto).
3. ~~Merge in main~~ → **FATTO** (`f24afe1`) e pushato.

## Gate verdi a fine sessione

`import-linter` 6/6 kept; contratti rigenerati senza drift (`gen-contracts` + verifica);
FE typecheck/lint/vitest 373/373 (+4 nuovi spec diff-save); ruff/mypy globali a parità con la
base (uniche aggiunte: annotazioni test-style nei nuovi file di test, debito spostato con gli
handler in `config_reactions.py`); ogni task con suite mirate verdi.

## Architettura implementata (dove guardare)

- **Layer**: `services/config_service.py` — `ConfigLayer.PREFERENCES` tra USER e RUNTIME;
  `load_preferences_layer(store)` (valida su tentative PRIMA di committare — fix B1);
  `set_many` batch atomico (una validazione, persistenza batch, un evento `config.changed`
  per path); `_hydrate` condiviso; `rebuild()`; `strip_paths_from_disk_layer`.
- **Store**: `services/preferences_service.py::PreferencesLayerStore` (load/save_paths/
  delete_paths/delete_all su `user_preferences`, righe dotted-path→JSON invariate).
- **Policy**: `services/config_policy.py` — UNICA fonte per path scrivibili (prefissi+esatti)
  e censimento SECRET_PATHS (6). Guardie dentro `set_many`: segreti rifiutati su OGNI layer.
- **SecretStore**: `services/secret_store.py` — `KeyringSecretStore` (servizio "alice", nome
  credenziale = path puntato, WinVaultKeyring pinnato esplicitamente per PyInstaller, cache
  sincrona per l'idratazione) + `InMemorySecretStore` (test/fallback). `ctx.secret_store`.
- **Idratazione**: `_rebuild()` inietta la cache segreti nel merged dict; env `ALICE_*` vince
  comunque (pydantic-settings). I 6 campi sono `SecretStr`; consumer su `.get_secret_value()`.
- **Migrazione**: `services/config_migration.py` — one-shot idempotente al boot: righe segrete
  DB→keyring, segreti YAML→keyring+riscrittura atomica, credenziale email legacy rinominata,
  righe morte/fuori-policy/schema-unknown POTATE (`_path_exists_in_schema` — fix B1).
- **Route**: `api/routes/config.py` — PUT: flatten (alias pc_automation, drop
  `_REMOVED_LEGACY_PATHS`) → partizione segreti/policy/rejected(400) → `_apply_secret_updates`
  (semantica: set/"***" e "" no-op/None delete, cap 512, rebuild finale) → `set_many` (422
  con `errors(include_url=False, include_context=False)`) → `diff_paths`+`apply_reactions` →
  risposta GET. PATCH: default layer preferences + reazioni. `response_model=ConfigResponse`
  (`api/routes/config_schemas.py`), ratchet stretto.
- **Reazioni**: `api/routes/config_reactions.py` — REACTIONS dichiarativo (stt/tts/email
  restart, llm rebuild su provider/api_key/openrouter_api_key, invalidazioni cache),
  `diff_paths` old/new, `ALL_REACTIVE_PATHS`. Handler `_apply_*` spostati qui invariati.
- **Vincoli**: sui modelli pydantic (`core/config.py`) — range/Literal/lunghezze + strip
  normalizations (`_strip_str`); clamping→rejection sui bound compressione (semantica route).
- **Bootstrap** (`core/bootstrap/platform.py`): secret store → cache → config service con
  provider → prefs (username) → migrazione → `load_preferences_layer` → plugin state.
  L'overlay legacy `apply_to_config` NON esiste più.
- **FE** (`stores/settings.ts`): `buildConfigPayload`/`diffConfigPayload` (pura, testata)/
  `applyConfigResponse`; `lastConfirmedPayload`; salvataggio SOLO dei path cambiati; flag
  (`openrouterKeyConfigured`, `passwordConfigured`) SOLO dalle risposte; password email fuori
  dallo snapshot (inviata quando non vuota, azzerata dopo); guard `_loadingSettings` con
  try/finally; `useKeyring` eliminato. `patchConfig(path, value, layer='preferences')`.

## Gotchas scoperti in sessione (NON ripeterli)

1. **Subagent + pytest in background = stallo**: i subagent che lanciano pytest in background
   restano in attesa di una notifica che non arriva. Imporre SEMPRE esecuzione foreground nei
   dispatch (successo solo parziale: ribadirlo in MAIUSCOLO e presto).
2. **Righe fossili nel DB prefs**: la policy a prefissi ammette path che lo schema non conosce
   più (es. `agent.enabled`). Ogni rimozione di campo config DEVE passare da
   `_REMOVED_LEGACY_KEYS`/`_REMOVED_LEGACY_PATHS` o affidarsi al prune schema-unknown della
   migrazione. Il layer valida su tentative proprio per questo (fix B1).
3. **Ordine bootstrap sacro**: migrazione e mount del layer PRIMA di qualsiasi overlay;
   un `rebuild()` scarta ogni mutazione in-place non ancora nei layer (Critical T6).
4. **In-place mutation = nemico**: restano DUE overlay in-place censiti (plugins.enabled,
   sync_model) — ticket I1, vedi sotto. Non aggiungerne altri.
5. **`npm ci` mentre l'app Electron gira** = node_modules mezzo distrutto (electron/dist
   locked). Chiudere l'app prima di qualsiasi install.
6. **PowerShell 5.1**: stderr dei comandi nativi (loguru DEBUG) fa exit 1 fasullo negli script
   (`check-contracts.ps1`) — verificare la sostanza (drift git) prima di credere al codice.
7. **`errors(include_url=False, include_context=False)`**: il ctx pydantic non è
   JSON-serializzabile — senza `include_context=False` il 422 diventa un 500.
8. **Lockfile**: `npm install` di riparazione pota entry opzionali dal package-lock —
   ripristinare con `git checkout -- frontend/package-lock.json` se non intenzionale.

## Ticket di follow-up — TUTTI RISOLTI (audit 2026-07-16 sera, branch fix/settings-followups-lint-gate)

Dettaglio completo in `docs/superpowers/audits/2026-07-16-followups-audit.md`.

- ~~I1~~ **RISOLTO** (`c8b58c0`): `sync_model` → layer preferences via `set_many` (non
  runtime: maschererebbe le scritture preferences successive di `llm.model`);
  `plugins.enabled` → layer runtime in bootstrap e toggle (la tabella `plugin_state` resta
  l'unica fonte persistita). Niente più overlay in-place censiti.
- ~~Triage#1~~ **RISOLTO** (`aeb4c34`): scrittura secreta con store assente → 503 esplicito,
  pre-flight PRIMA di ogni commit.
- ~~Triage#4~~ **RISOLTO** (`aeb4c34`): PUT misto all-or-nothing fino alla validazione —
  pre-flight segreti (503/400) → `set_many` atomico (422) → apply segreti → reazioni.
- ~~M1~~ **RISOLTO** (`2cbbdde`): il reset ricarica il layer e applica le reazioni; default
  vivi senza riavvio.
- ~~M2~~ **RISOLTO** (`889b36b`): semantica definita — PUT = merge per-foglia (flatten
  ricorsivo), PATCH = replace del sottoalbero, `save_paths` pruna i discendenti (autoescape),
  `load()` deterministico shallowest-first. NB: il rifiuto dei dict NON era percorribile
  (il FE PATCHa `agent.prompts.tier_guidance` come dict con semantica replace).
- Preesistenti già chippati — aggiornamento audit 2026-07-16: ~~guardia embedding dim≠384~~
  **risolto** (F3, `8657646`); ~~capability bleed fuzzy match~~ **risolto** (F4, `2b00667` —
  registry namespaced per provider, vedi handoff OpenRouter gotcha 5); ~~divergenza costo
  live/persistito~~ **risolto** (`3368fe6`); ~~`test_plugins_enabled_list` stale~~
  **risolto** (`13a7bd0`, audit 2026-07-16 sera: via il conteggio hardcoded, resta
  l'invariante niente-duplicati).

## E2E (ESEGUITO e verificato dall'utente il 2026-07-16 — checklist di riferimento)

1. Avvia backend+frontend. Al primo boot: log di migrazione (prune `agent.enabled`, eventuale
   migrazione key). Verifica che le preferenze siano intatte (provider openrouter, nome, email).
2. Incolla la API key OpenRouter → crediti visibili; `keyring get alice llm.openrouter_api_key`
   pieno; tabella `user_preferences` SENZA la key. Riavvia → key ancora configurata, chat OK.
3. Password email → Credential Manager `alice / email.password`; riavvia → servizio email su.
4. Cambia SOLO il tema → in `user_preferences` si aggiorna solo `ui.theme` (diff-save).
5. Persona agente → riavvia → conservata; provider intatto (regressione split-brain).
6. Torna a lmstudio → chat locale intatta.

## Convenzioni vincolanti (invariate)

Endpoint nuovi con `response_model` (ratchet); frame WS nel vocabolario congelato;
`gen-contracts.ps1` dopo ogni modifica contratto; import-linter; niente `any` FE;
mai segreti nei layer/DB/YAML/JSON — solo SecretStore.
