# Audit — Follow-up settings-core + debito lint (fix/settings-followups-lint-gate)

**Data:** 2026-07-16 · **Base:** main @ `415d649` · **Modalità:** report + fix
**Scope concordato:** i finding già censiti dagli handoff post-merge (ticket settings-core
I1/Triage#1/Triage#4/M1/M2, `test_plugins_enabled_list` stale, bonifica ruff + gate CI).
L'e2e con API key reale (punto 1 dell'handoff OpenRouter) è stato verificato funzionante
dall'utente e NON fa parte di questo audit.

## Copertura dichiarata

- **Incluso:** `backend/` (route config/settings/plugins, config service/policy/migration,
  preferences store, bootstrap platform, tutto il debito ruff backend-wide), workflow CI.
- **Escluso:** `frontend/` (nessun file toccato; contratti generati verificati senza drift),
  `continuum/`, `trellis*_server/`, script PowerShell, il debito mypy pre-esistente non
  introdotto dal branch (censito sotto), l'incoerenza EOL del repo (censita sotto).

## Finding e remediation

### [AUD-001] Triage#1 — secret store assente = 200 silenzioso — ALTO (correttezza)
**Dove:** `backend/api/routes/config.py::_apply_secret_updates`
**Causa radice:** il guard `if ctx.secret_store is None: return changed` degradava un
fallimento infrastrutturale a no-op invisibile.
**Fix (applicato):** pre-flight nel PUT: qualsiasi scrittura secreta con store assente → 503
esplicito, PRIMA di ogni commit. `_apply_secret_updates` ora asserisce l'invariante.
**Verifica:** `test_secret_update_without_store_returns_503` (include: neanche le pref del
body misto atterrano).

### [AUD-002] Triage#4 — commit dei segreti prima della validazione pref — ALTO (correttezza)
**Dove:** `backend/api/routes/config.py::update_config`
**Causa radice:** due commit sequenziali senza validazione congiunta: un segreto valido +
pref invalida persisteva il segreto e saltava le reazioni (rebuild LLM) fino alla scrittura
successiva.
**Fix (applicato):** pre-flight puro dei segreti (`_validate_secret_updates`: 400 su
lunghezza) → `set_many` (validazione+commit atomici, 422 senza commit) → apply segreti
(non può più fallire a metà richiesta) → reazioni.
**Verifica:** `test_mixed_put_invalid_pref_does_not_commit_secret`,
`test_mixed_put_oversize_secret_does_not_commit_pref` + 18 test di regressione del flusso
segreti/provider verdi.

### [AUD-003] M1 — DELETE /settings/preferences non ricaricava il layer — MEDIO (correttezza)
**Dove:** `backend/api/routes/settings.py::reset_preferences`
**Causa radice:** il reset cancellava le righe DB ma il layer in memoria restava montato
("Restart to apply").
**Fix (applicato):** reload del layer dallo store svuotato + `apply_reactions` sul diff dei
path reattivi: i default sono vivi subito (incluso rebuild LLM se cambia provider).
**Verifica:** `TestResetPreferences` (2 test, incluso il rebuild del servizio).

### [AUD-004] M2 — righe dict sovrapposte alle righe foglia — MEDIO (correttezza/dati)
**Dove:** `backend/api/routes/config.py::_flatten_update_body`,
`backend/services/preferences_service.py`
**Causa radice:** due semantiche di scrittura convivevano senza definizione: PUT a 3+ livelli
creava righe dict che si sovrapponevano alle righe foglia dello stesso sottoalbero, e
`load()` le materializzava in ordine di inserimento (non deterministico). Il rifiuto secco
dei dict NON era percorribile: il FE PATCHa `agent.prompts.tier_guidance` come dict con
semantica replace (il pruning dei tier dipende dalla sostituzione della riga).
**Fix (applicato, alla radice):** semantica definita e resa deterministica —
PUT = merge per-foglia (flatten ricorsivo); PATCH = replace del sottoalbero (valore as-is);
`save_paths` rende il path autoritativo sul sottoalbero (prune dei discendenti, `autoescape`
perché `_` nei path è wildcard LIKE); `load()` materializza shallowest-first (il più
specifico vince sulle righe legacy sovrapposte).
**Verifica:** 3 test store (replace-subtree, escape wildcard, determinismo su righe legacy)
+ 5 test route (flatten unit + endpoint con probe sulla riga foglia).

### [AUD-005] I1 — overlay in-place clobberati da ogni rebuild — ALTO (correttezza)
**Dove:** `backend/api/routes/config.py::sync_model`,
`backend/core/bootstrap/platform.py`, `backend/api/routes/plugins.py::toggle_plugin`
**Causa radice:** mutazioni in-place del config risolto (`object.__setattr__`, assegnazione
lista) invece di scritture sui layer: ogni rebuild (quindi ogni PUT) le cancellava.
**Fix (applicato):**
- `sync-model` → layer **preferences** via `set_many` (non runtime: un override runtime su
  `llm.model` maschererebbe le scritture preferences successive; ed è lo stesso valore che
  il FE persisterebbe comunque al prossimo diff-save del suo snapshot).
- `plugins.enabled` → layer **runtime** in bootstrap e nel toggle (la tabella `plugin_state`
  resta l'unica fonte di verità persistita; la lista config è una proiezione derivata
  per-boot — scriverla nelle preferences creerebbe una seconda fonte divergente).
- Il rollback del toggle su load fallito sparisce: il layer non viene toccato prima del
  successo.
**Verifica:** `test_sync_model_survives_config_rebuild`,
`test_plugin_toggle_survives_config_rebuild` + lifecycle/manager plugin (52 test).

### [AUD-006] test_plugins_enabled_list rosso a baseline — BASSO (test)
**Dove:** `backend/tests/test_config.py`
**Causa radice:** change-detector (`len == 20` hardcoded) che invecchia a ogni plugin
aggiunto senza proteggere nulla (era rosso da quando i plugin sono 21).
**Fix (applicato):** rimosso il conteggio esatto; restano le membership dei plugin chiave +
invariante reale (niente duplicati).

### [AUD-007] Debito ruff (504 violazioni) senza gate CI — MEDIO (manutenibilità)
**Dove:** backend-wide; `.github/workflows/contracts.yml`
**Causa radice:** ruff configurato ma mai eseguito in CI → riaccumulo costante.
**Fix (applicato):** bonifica a **zero violazioni** in tre passate (autofix sicuri 370;
unsafe-fix revisionati a mano 37; ~100 fix manuali/delegati con review) + nuovo step
**"Backend lint (ruff)"** in `contracts.yml`. Fix non meccanici degni di nota:
`zip(strict=True)` sui 3 siti a lunghezza garantita, costante fuori posto in
`cad_generator/plugin.py` (radice degli 11 E402), import `loguru` fuori posto in
`tts_service.py`, F841 nei test risolti rafforzando le asserzioni, F821 via TYPE_CHECKING,
temp file con context manager (SIM115). Eccezioni deliberate censite in
`per-file-ignores` con motivazione (script `sys.path`, contratto wire MCP camelCase,
hook plugin opzionali B027, parametri `filter`/`id` A002). Zero `noqa` inline aggiunti.
Rimosso `backend/debug_test.py` (scratch autodescritto, mai importato).
**Verifica:** `ruff check backend` = All checks passed; suite dei moduli toccati verdi
(500+ test mirati); mypy a parità con main sui file toccati (3 errori nuovi introdotti e
richiusi; il confronto normalizzato branch-vs-main esclude gli artefatti `backend/dist/`).

### [AUD-008] Suite pytest integrale non completabile — MEDIO (test) — APERTO

**Dove:** `backend/tests/test_voice_tool_calling.py` (e possibile interazione col resto
della suite).
**Cosa:** su questa macchina la suite integrale (`pytest tests/`) si APPENDE
deterministicamente dopo un fail a ~91%. Riprodotto IDENTICO sulla baseline di main
(`415d649`, pre-fix) e sull'albero finale → **pre-esistente, non introdotto dal branch**.
Dettaglio dal run verboso del singolo file:
`TestVoiceTranscription::test_no_stt_service_returns_empty` fallisce su
`assert stopped["empty"] is True` (arriva `empty=False`); l'hang della suite si manifesta
più avanti (zona TTS/WS — sospetta attesa WebSocket/TestClient senza timeout).
Contesto ambientale rilevante: l'extra voice NON è installato in questo venv
(`faster-whisper` assente → STT degradato al boot del test-lifespan) e il data dir Qdrant
può risultare lockato da altre istanze (fallback in-memory) — il fail/hang è quindi
probabilmente ambiente-dipendente, non necessariamente riproducibile in CI. Due run
pytest concorrenti contendono sul data dir e si bloccano a vicenda: mai in parallelo.
**Fix:** APERTO con piano — sessione dedicata: riprodurre con extra voice installato e
data dir libero; isolare l'hang con `-v -x` dal test incriminato in poi; valutare
`pytest-timeout` come guardrail di suite.
**Mitigazione attuale:** verifica per sottoinsiemi mirati (tutti verdi in questo audit).

## Debito censito NON in scope (dichiarato, non toccato)

- **EOL misti per file:** 52 file backend sono CRLF in HEAD, il resto LF; nessuna
  normalizzazione di straforo (diff enorme + decisione `.gitattributes` da prendere a parte).
  Nota operativa: `ruff --fix` riscrive i file con EOL nativi — dopo ogni bonifica va
  ripristinato l'EOL per-file di HEAD.
- **mypy pre-esistente:** ~2.400 errori strict (stub terze parti mancanti, annotazioni test,
  `type-arg`); `types-PyYAML` ancora non installato. mypy non è gate in CI.
- **`backend/dist/`** (build PyInstaller) inquina i run mypy locali da root — candidato
  exclude in `[tool.mypy]`.
- Divergenze residue rare del chip costo (turno cancellato senza contenuto, turno solo-tool):
  già censite nell'handoff OpenRouter, invariate.

## Tracciabilità commit

| Finding | Commit |
|---------|--------|
| AUD-004 (M2) | `889b36b` |
| AUD-001/002 (Triage#1/#4) | `aeb4c34` |
| AUD-003 (M1) | `2cbbdde` |
| AUD-005 (I1) | `c8b58c0` |
| AUD-006 (test stale) | `13a7bd0` |
| AUD-007 (bonifica+gate) | `2349be2`, `1fa5d28`, `9e0bab9`, `f801635` |

**Gate finali:** ruff = 0 · import-linter 6/6 kept · contratti generati senza drift ·
mypy a parità con main sui file toccati · pytest: ~550 test mirati verdi su tutti i moduli
toccati; la suite INTEGRALE non è completabile su questa macchina per l'hang pre-esistente
AUD-008 (riprodotto identico sulla baseline di main — vedi sopra).
