# Handoff — Rework settings-core (rework/settings-core)

**Data:** 2026-07-16 · **Branch:** `rework/settings-core` (21 commit su `394d8d4`, non mergiato)
**Spec:** `docs/superpowers/specs/2026-07-16-settings-core-rework-design.md`
**Piano:** `docs/superpowers/plans/2026-07-16-settings-core-rework.md` (15 task)
**Metodo:** subagent-driven — ogni task: implementer + review task-scoped (spec+quality) + fix loop;
review olistica finale sull'intero branch (modello top-tier) con triage dei finding differiti.
Ledger completo: `.superpowers/sdd/progress.md` (gitignored, locale).

## Stato: task 1–14 COMPLETI e approvati; task 15 quasi chiuso

Feature completa end-to-end: config a 5 layer con layer `preferences` formale (DB), tutti e sei
i segreti nel Credential Manager di Windows via SecretStore, PUT/PATCH sul motore unico
`set_many` + registry reazioni, migrazione one-shot idempotente, FE diff-save con flag derivati.
Il doppio sistema e lo split-brain sono morti strutturalmente (test di regressione dedicato).

### Cosa resta del task 16 (equivalente)

1. **Suite pytest integrale**: lanciata sul commit `cdf8b24` (pre-fix B1), in corso al momento
   dell'handoff; le suite mirate del fix B1 sono verdi. Esito da leggere.
2. **E2E con l'utente** (checklist al §E2E sotto) — mai eseguito su macchina reale.
3. **Merge in main** — verdetto review finale: **mergiabile** (dopo fix B1, commit `0f83e28`).

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

## Ticket di follow-up (dalla review finale — NON bloccanti, da aprire)

- **I1**: overlay in-place `plugins.enabled` (`bootstrap/platform.py` + `api/routes/plugins.py`)
  e `sync_model` (`config.py`) clobberati da OGNI rebuild (quindi da ogni PUT) — portarli nel
  merge dei layer o sul layer `runtime`.
- **Triage#1**: `ctx.secret_store is None` in `_apply_secret_updates` → 200 silenzioso senza
  persistenza; meglio 503 esplicito (2 righe).
- **Triage#4**: nel PUT misto, validare le pref PRIMA di committare i segreti (oggi un segreto
  valido + pref invalida salva il segreto ma salta le reazioni fino alla prossima scrittura).
- **M1**: `DELETE /settings/preferences` non ricarica il layer (una riga:
  `load_preferences_layer`).
- **M2**: body PUT a 3 livelli produce righe dict sovrapposte (documentare o rifiutare
  valori-dict in `_flatten_update_body`).
- Preesistenti già chippati: `test_plugins_enabled_list` stale (20 vs 21), guardia embedding
  dim≠384, capability bleed fuzzy match, divergenza costo live/persistito.

## E2E (da eseguire con l'utente, post-merge o su branch)

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
