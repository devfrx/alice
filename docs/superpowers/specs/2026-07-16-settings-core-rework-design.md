# Spec — Rework del sistema impostazioni: config unificata + segreti nel keyring

**Data:** 2026-07-16 · **Stato:** approvato (design validato in sessione)
**Branch di lavoro previsto:** `rework/settings-core` (da `main`, DOPO il merge di `feat/openrouter-provider`)
**Piano:** `docs/superpowers/plans/2026-07-16-settings-core-rework.md` (da scrivere)

---

## 1. Problema

Tre difetti alla radice, diagnosticati e riprodotti in sessione (2026-07-16):

1. **Split-brain config.** Convivono due sistemi di persistenza mai riconciliati:
   `PUT /api/config` muta `ctx.config` in-place (`object.__setattr__`) e persiste su
   `user_preferences` (DB) via `PreferencesService.persist_from_update`; `PATCH /api/config`
   scrive nei layer YAML del `LayeredConfigService`. Ogni `config.changed` (es. persona agente
   via PATCH, `settings.ts:280`) fa `ctx.config = config_service.get_resolved()`
   (`bootstrap/platform.py:49`): una config ricostruita dai **soli layer YAML**, senza
   l'overlay DB. Da quel momento provider, API key, impostazioni email e ogni preferenza DB
   spariscono dalla config viva fino al riavvio. Stesso clobber in `POST /config/reload` e
   `api/routes/services.py:93`.
2. **Segreti in chiaro o volatili.** `llm.openrouter_api_key` persistita in chiaro in SQLite;
   password email in sola RAM quando `email.use_keyring=false`; altri quattro segreti
   (`llm.api_token`, `home_assistant.token`, `mqtt.password`, `continuum.api_token`)
   affidati a YAML in chiaro o env var, senza percorso di scrittura dalla UI.
3. **Valori avvelenati auto-perpetuanti.** Lo store FE (`stores/settings.ts`) fa bulk-save
   con deep-watch + debounce: ri-persiste TUTTO lo stato a ogni modifica, inclusi valori
   che nessuna UI espone più (`email.use_keyring=false`, introdotto come default FE dal
   commit `85f61a5`, incastrato in DB per sempre). I flag come `openrouterKeyConfigured`
   sono ottimistici (impostati a `true` su qualunque 200, anche se il backend ha scartato
   la chiave in silenzio — è esattamente ciò che è successo con la key OpenRouter su `main`).

## 2. Obiettivo e principi

- **Una fonte di verità**: la resolved config è sempre e solo il merge dei layer del
  `LayeredConfigService`. Nessun overlay applicato "a mano" fuori dal merge.
- **Un percorso di scrittura**: ogni mutazione passa da `config_service` (validazione
  pydantic, persistenza, evento) — PUT e PATCH sono facciate sullo stesso motore.
- **Zero segreti su disco in chiaro**: mai in YAML, mai in DB, mai in JSON di risposta.
  Casa unica: keyring di Windows (Credential Manager), via un `SecretStore` astratto.
- **Zero drop silenziosi**: path sconosciuti → 400. Zero valori incastrati: il FE salva
  solo ciò che è cambiato.
- Niente rattoppi: i meccanismi che violano i principi vengono sostituiti, non decorati.

## 3. Architettura

### 3.1 Layer (cinque, ordine di precedenza crescente)

```
defaults (config/default.yaml, bundled)
  < system   (%LOCALAPPDATA%/Alice/config/system.yaml — admin/install)
  < user     (%LOCALAPPDATA%/Alice/config/user.yaml — modifica manuale power-user)
  < preferences (DB, tabella user_preferences — TUTTE le scritture della UI)
  < runtime  (RAM, effimero per design)
```

- Nuovo `ConfigLayer.PREFERENCES = "preferences"` in `services/config_service.py`;
  `_LAYER_ORDER` aggiornato.
- Il layer è persistito nella tabella **esistente** `user_preferences` (chiave puntata →
  JSON): le righe attuali sono già nel formato giusto e NON migrano.
- `LayeredConfigService` riceve uno store asincrono per il layer preferences
  (l'attuale `PreferencesService` ridotto a `PreferencesLayerStore`: `load() -> dict`,
  `save_paths(dict[str, Any])`, `delete_paths(...)`). Caricamento nel lifespan
  (`stage_platform`, dopo `stage_database`) via nuovo metodo asincrono
  `load_preferences_layer(store)`; da quel momento ogni `_rebuild()` include il layer.
- **Muoiono**: `PreferencesService.apply_to_config`, `persist_from_update`,
  `PERSISTABLE_SECTIONS`, `PERSISTABLE_LLM_KEYS`, `SENSITIVE_PREFERENCE_KEYS`.
- **Policy di scrivibilità** (nuovo modulo `services/config_policy.py`): unico registro di
  (a) path/prefissi scrivibili nel layer preferences dalla UI (successore delle vecchie
  allowlist), (b) censimento dei **path segreti** (§3.2). `config_service.set/set_many`
  rifiuta con `ValueError` scritture fuori policy sul layer preferences e scritture di
  path segreti su QUALSIASI layer (difesa in profondità).
- La UI scrive sempre e solo `layer=preferences`. La persona/prompt agente
  (oggi PATCH → `user.yaml`) migra a preferences: il FE (`settings.ts:280,292`) passa
  `layer: "preferences"`; i valori esistenti in `user.yaml` restano validi come base
  (precedenza inferiore) e vengono sovrascritti alla prima modifica dalla UI.
- `_refresh_ctx_config` resta com'è: con il merge completo il clobber è impossibile
  per costruzione.

### 3.2 SecretStore

- Nuovo `services/secret_store.py`:
  - `SecretStoreProtocol` (in `core/protocols.py`): `async get(name) -> str | None`,
    `async set(name, value)`, `async delete(name)`, `async load_cache() -> dict[str, str]`.
  - `KeyringSecretStore`: backend produzione, servizio keyring `"alice"`, nome credenziale
    = path puntato del campo (es. `llm.openrouter_api_key`). Su Windows usa
    `keyring.backends.Windows.WinVaultKeyring` **fissato esplicitamente** (niente
    discovery via entry_points: fragile sotto PyInstaller). Chiamate keyring via
    `asyncio.to_thread` (API sync).
  - `InMemorySecretStore`: per i test e come fallback se il keyring non è disponibile
    (log warning una volta; i segreti restano validi per la sessione).
  - Campo `secret_store` su `AppContext` (gruppo `platform`).
- **Censimento segreti** (chiuso, in `config_policy.py`):

  | Path | Campo attuale | Nuovo tipo |
  |---|---|---|
  | `llm.api_token` | `str` | `SecretStr` |
  | `llm.openrouter_api_key` | `str` | `SecretStr` |
  | `home_assistant.token` | `str` | `SecretStr` |
  | `mqtt.password` | `str` | `SecretStr` |
  | `continuum.api_token` | `str \| None` | `SecretStr \| None` |
  | `email.password` | `SecretStr` | `SecretStr` (invariato) |

  Tutti i consumer aggiornati a `.get_secret_value()` (censimento dei call-site nel piano).
- **Idratazione**: il SecretStore mantiene una cache in-memory caricata una volta al
  bootstrap (`load_cache()`) e aggiornata a ogni `set/delete`. `LayeredConfigService`
  riceve la cache (callable sincrona) e la inietta nei kwargs del merge dentro
  `_rebuild()`: così OGNI resolved config (bootstrap, PATCH, PUT, reload) è idratata,
  senza I/O nel percorso sincrono. Le env var `ALICE_*` vincono comunque
  (pydantic-settings: `env_settings` prima di `init_settings`) — override headless/CI gratis.
- **Scrittura segreti** (semantica PUT, uniforme per i sei path):
  - stringa non vuota ≠ `"***"` → `SecretStore.set` + rebuild + reazione;
  - `"***"` (maschera) o `""` → no-op;
  - `null` → `SecretStore.delete` + rebuild + reazione (nuova capacità: oggi non esiste
    un percorso di cancellazione).
- **Lettura**: mai. La redaction attuale (`_redact`, `_REDACT_KEYS`) resta sulle route
  diagnostiche; `GET /config` espone solo flag derivati `*_configured`
  (`openrouter_api_key_configured`, `email.password_configured` — gli altri quattro
  quando/se la UI li gestirà, YAGNI).
- `EmailService` non importa più `keyring`: riceve la password idratata dalla config
  (`_resolve_password` muore). **`email.use_keyring` eliminato dallo schema**
  (`EmailConfig`), da `GET /config`, dal FE store; `migrate_legacy_config_keys` scarta
  la chiave residua nei YAML; la migrazione (§4) elimina la riga DB.

### 3.3 Percorso di scrittura unificato

- Nuova API batch su `LayeredConfigService`:
  `async set_many(changes: dict[str, Any], layer) -> AliceConfig` — mutazione tentativa
  del layer, **una** validazione `AliceConfig(**merged)`, **un** commit, **una**
  persistenza batch, **un** rebuild; emette un evento `config.changed` per ogni path
  (vocabolario WS invariato: frame `{type, path, value|"***", layer}`), dopo il rilascio
  del lock. `set()` diventa il caso particolare a un elemento.
- **`PUT /api/config`** mantiene il contratto esterno (stesso body accettato, stessa
  shape di risposta = `GET /config`), ma internamente:
  1. flatten del body in path puntati; alias legacy gestiti in un unico punto
     (`pc_automation.confirmations_enabled` → `permissions.confirmations_enabled`);
  2. partizione: path segreti → SecretStore (§3.2); path in policy → `set_many(...,
     layer=preferences)`; path sconosciuti/fuori policy → **400** con l'elenco dei path
     rifiutati;
  3. reazioni (§3.4);
  4. risposta = shape attuale di `GET /config`.
- Le ~400 righe di validazione a mano nella route **muoiono**: i vincoli diventano
  `Field(ge=..., le=..., max_length=...)` / validator sui modelli pydantic in
  `core/config.py` (valgono così anche per YAML ed env var). Errori di validazione →
  **422** con `exc.errors()` (il FE oggi logga e basta: nessun adattamento richiesto;
  i messaggi 400 custom sopravvivono solo per path sconosciuti).
- **`PATCH /api/config`** invariato nel contratto (path/value/layer); default layer
  → `preferences`; `user`/`system`/`runtime` restano selezionabili; `defaults` read-only.
- `POST /config/reload` rilegge i layer disco e ricostruisce: con il layer preferences
  nel merge non clobbera più nulla.

### 3.4 Reazioni ai cambi (registry dichiarativo)

Nuovo modulo `api/routes/config_reactions.py`: registry ordinato
`(prefissi | predicato) → handler async(ctx, changed_paths)`, invocato una volta per
richiesta PUT/PATCH dopo il commit, con l'elenco dei path effettivamente cambiati
(confronto old/new resolved, non il body richiesto):

| Trigger | Handler (esistente, riusato) |
|---|---|
| `stt.enabled\|model\|device` | `_apply_stt_changes` + `push_voice_ready` |
| `tts.*` (campi restart) | `_apply_tts_changes` + `push_voice_ready` |
| `email.*` | `_apply_email_changes` |
| `llm.provider`, `llm.openrouter_api_key`, `llm.api_token` | `_apply_llm_provider_change` (rebuild `LLMService`) |
| `llm.model` | invalidate model cache |
| `llm.openrouter_model` | invalidate model + context window cache |
| `llm.user_preferred_name` | invalidate system prompt cache |

I gotcha noti restano rispettati: header/flag provider fissati alla costruzione ⇒ ogni
cambio passa dal rebuild; i socket chat aperti rileggono `ctx.llm_service` a ogni turno.

## 4. Migrazione (one-shot, idempotente, in `stage_platform`)

Nuovo `services/config_migration.py`, eseguito dopo il caricamento del layer preferences
e l'init del SecretStore:

1. Riga DB `llm.openrouter_api_key` presente → `SecretStore.set` + delete riga.
2. Password email nel keyring legacy (`keyring.get_password("alice", <username>)`) →
   copiata nel nuovo nome (`email.password`); la credenziale legacy viene rimossa.
3. Segreti trovati nei YAML `user.yaml`/`system.yaml` (i sei path) → `SecretStore.set` +
   riscrittura atomica del file senza il valore + log INFO.
4. Righe DB morte eliminate: `email.use_keyring`, eventuali chiavi non più in policy.
5. Ogni passo è no-op se non c'è nulla da migrare; errori keyring → warning, non-fatale
   (il valore resta dov'è, si ritenta al prossimo avvio).

## 5. Frontend (meccanica dello store, UI intatta)

- `stores/settings.ts`:
  - via il deep-watch bulk-save; si tiene uno snapshot `lastConfirmed` (stato al load e
    dopo ogni risposta di salvataggio) e il debounce invia **solo i path cambiati**
    (diff per sezione → body PUT parziale, stessa shape annidata di oggi);
  - flag derivati SOLO dalle risposte backend: `openrouterKeyConfigured` da
    `llm.openrouter_api_key_configured` della risposta (il setter dedicato smette di
    fare `= true` ottimistico), `passwordConfigured`/`serviceRunning` già conformi;
  - `useKeyring` rimosso da tipi, default e payload;
  - persona/prompt agente: `patchConfig(path, value, layer="preferences")`.
- `services/api/config.ts`: `patchConfig` accetta il layer; tipi rigenerati.
- Nessun cambiamento ai componenti UI (il restyle estetico in stash resta indipendente).

## 6. Contratti, test, qualità

- Route config con `response_model` pydantic tipizzati (`ConfigResponse`,
  `ResolvedConfigResponse` redatta, `ConfigLayersResponse`) — ratchet contratti soddisfatto;
  `.\scripts\gen-contracts.ps1` dopo ogni modifica; frame WS `config.changed` invariato.
- Test backend (pytest, stile esistente):
  - unit `SecretStore` (in-memory + contract test del protocol; keyring mockato);
  - `LayeredConfigService`: precedenza a 5 layer, `set_many` atomica (validazione fallita
    ⇒ nessun commit parziale), policy (path fuori policy/segreti nei layer → errore);
  - endpoint-level: PUT parziale, segreti (set/maschera/`""`/`null`), path sconosciuti →
    400 con elenco, 422 pydantic, reazioni (rebuild LLM su provider/key, restart email);
  - migrazione: DB+YAML seminati vecchio stile → segreti nel fake store, righe/chiavi
    rimosse, YAML riscritto; idempotenza (secondo run no-op);
  - regressione split-brain: PATCH persona → la resolved config conserva le preferences
    (il test che oggi sarebbe rosso).
- Test FE (vitest): diff-save (solo path cambiati nel body), flag non ottimistici,
  nessun ri-salvataggio di valori mai toccati.
- Gate: `ruff`, `mypy` (zero errori nuovi), `lint-imports` (nessun nuovo contratto:
  reactions in `api/`, store/policy in `services/`), `check-contracts.ps1`,
  FE `typecheck`/`lint`/`vitest`.

## 7. Fasi (ciascuna shippabile)

- **F1 — SecretStore e segreti** (`SecretStr` sui sei campi + consumer, store keyring +
  in-memory, idratazione nel rebuild, migrazione §4, PUT segreti via store).
- **F2 — Layer preferences e write path** (layer formale + policy, `set_many`, PUT/PATCH
  sul motore unico, vincoli sui modelli pydantic, registry reazioni, morte di
  `apply_to_config`/allowlist, response_model tipizzati, regen contratti).
- **F3 — FE diff-save** (snapshot/diff, flag derivati, rimozione `useKeyring`, persona →
  preferences, vitest).

Ordine vincolato: F1 → F2 → F3. Prerequisito: merge di `feat/openrouter-provider`
(task 16 del relativo piano) — questo spec viene committato come primo commit di
`rework/settings-core`.

## 8. Rischi e mitigazioni

- **Keyring sotto PyInstaller**: backend fissato esplicitamente (no entry_points);
  smoke-test nel bundle in F1.
- **SecretStr nei consumer**: un call-site dimenticato produce `"**********"` negli
  header — mypy segnala i mismatch `str`/`SecretStr`; censimento call-site nel piano +
  test per ogni consumer.
- **FE più vecchio contro backend nuovo** (o viceversa) durante lo sviluppo: il contratto
  PUT resta compatibile; l'unico breaking è `use_keyring` (campo ignorato → 400 da
  policy). Mitigazione: F3 rimuove il campo dal FE nello stesso branch; su `main`
  arrivano insieme.
- **Valori legacy fuori policy nel DB**: la migrazione li elimina (§4.4) così il layer
  preferences non contiene mai path non scrivibili.

## 9. Fuori scope (esplicito)

- Restyle UI della pagina Settings (lavoro separato già in stash su `main`).
- Nuove sezioni UI per i quattro segreti oggi senza interfaccia.
- Rotazione/scadenza segreti, cifratura addizionale, multi-utente.
- Cost tracking e ogni altro item del piano OpenRouter (task 16 resta nel suo piano).
