# Handoff — Provider OpenRouter (feat/openrouter-provider)

**Data:** 2026-07-15 · **Aggiornato:** 2026-07-16 (audit post-merge)
**Branch:** `feat/openrouter-provider` — **MERGIATO in main** (`394d8d4`) **e pushato**
**Spec:** `docs/superpowers/specs/2026-07-15-openrouter-provider-design.md`
**Piano:** `docs/superpowers/plans/2026-07-15-openrouter-provider.md` (16 task)
**Metodo:** subagent-driven — ogni task: implementer + spec review + quality review; tutti i rilievi bloccanti risolti in-branch.

## Stato: MERGIATO; review olistica fatta, finding risolti (vedi §Post-merge)

Feature completa end-to-end nel codice: OpenRouter è il terzo provider LLM di pari rango
(catalogo con prezzi/capacità, saldo crediti, preferiti, costo per conversazione live+persistito,
switch provider a runtime, guardia embedding). Docs identità aggiornati (CLAUDE.md, README).

### Task 16 — stato post-audit (2026-07-16)

1. **`pytest tests/` COMPLETO**: rilanciato nell'audit del 2026-07-16 — esito annotato in §Post-merge.
   Tutti i sottoinsiemi mirati eseguiti per-task e per-fix sono verdi.
2. ~~ruff/mypy globali interrotti~~ → censiti nell'audit: **0 errori B904 su tutto il backend**
   (bonifica `185b371`); residuo preesistente aggiornato in §Debito sotto.
3. ~~Review finale olistica da rifare~~ → **FATTA** (2026-07-16): 4 finding, tutti risolti e
   mergiati (vedi §Post-merge).
4. **Verifica e2e con API key reale** (serve l'utente): ANCORA DA FARE — switch a openrouter →
   chiave → catalogo → crediti → messaggio in chat con chip costo → riavvio (persistenza) →
   ritorno a lmstudio intatto → log memoria solo fastembed.
5. ~~Push del branch + merge~~ → **FATTO**: merge `394d8d4`, tutto pushato su origin/main.

Gate già verdi a fine sessione: `lint-imports` (6 contratti kept), `check-contracts.ps1`,
`pytest tests/contracts/` (98), FE `typecheck`/`lint`/`vitest` (369/369).

## Post-merge (2026-07-16) — review olistica e fix

Review olistica sull'intero diff del branch eseguita il 2026-07-16: 4 finding, tutti risolti
con branch dedicati mergiati in main e pushati:

- **F1/F2 — divergenza costo live/persistito sui turni in errore** → `3368fe6` (merge `f8cf897`):
  `cost=None` sul frame `turn.finished` dei turni in errore (il chip live non somma costi che il
  reload non può confermare). Vedi gotcha 7 aggiornato.
- **F3 — guardia embedding openrouter+dim≠384** → `8657646` (merge `9d7811f`): stato degradato
  reso esplicito.
- **F4 — capability bleed nel fuzzy match del registry** → `2b00667` (merge `8070693`):
  **fix strutturale, gotcha 5 riscritto sotto** — il registry ora è namespaced per provider.
- **Bonifica B904 estesa** (nata dal chip su models.py) → `185b371` (merge `e9eb199`): chaining
  esplicito delle eccezioni su TUTTI i 22 siti del backend, `ruff --select B904` = 0.

Nota repo: GitHub ha rinominato il repository `devfrx/omnia` → `devfrx/alice`; il remote locale
punta ancora a `omnia` (il redirect funziona) — aggiornare con
`git remote set-url origin https://github.com/devfrx/alice.git`.

## Architettura implementata (dove guardare)

- **Config** (`backend/core/config.py`): campi `openrouter_*` su `LLMConfig` + property
  `effective_base_url` (openrouter → `https://openrouter.ai/api`, altrimenti `base_url`).
- **Layer LLM**: header Bearer costruiti in `LLMService.__init__`; `LLMClient` esclude il percorso
  nativo LM Studio e il folding del system prompt per openrouter; `ModelResolver.resolve()`
  early-return su `openrouter_model or "openrouter/auto"` (zero probe); context window dal
  capability registry (`get_cached_context_window`).
- **Costo**: il chunk SSE finale porta `usage.cost` (AUTOMATICO su OpenRouter — `usage:{include:true}`
  è DEPRECATO e no-op, verificato su doc ufficiale); accumulo su `TurnProgress.cost` (initial stream
  + tool loop), timbro unico in `DirectTurnExecutor._finish` via `dataclasses.replace`; frame
  `turn.finished` ha SEMPRE la chiave `cost` (None se non riportato). Persistenza su
  `messages.usage` (JSON) nel messaggio finale (e sul cancel_msg dei turni cancellati);
  `total_cost` = SUM on-read in `get_conversation`.
- **Catalogo/crediti**: `services/openrouter_service.py` (cache TTL 1h, double-checked lock,
  copia difensiva) + `api/routes/openrouter.py` (`/api/openrouter/models|credits`, response_model
  tipizzati, error mapping 400/401/502/503 incluso JSON malformato→502). Il catalogo semina il
  `ModelCapabilityRegistry` (`refresh_from_openrouter`).
- **Switch a runtime** (`api/routes/config.py`): `_apply_llm_provider_change` RICOSTRUISCE
  `ctx.llm_service` (pattern restart STT/TTS) su cambio provider/api key; `ws.py` ri-legge
  `ctx.llm_service` e ricostruisce il TurnAssembler PER OGNI TURNO (i socket aperti sopravvivono
  allo switch).
- **Embedding** (`services/embedding_client.py` + `bootstrap/knowledge.py`): `api_enabled=False`
  quando provider=openrouter → solo fastembed, deciso al bootstrap (switch a runtime ⇒ serve
  riavvio per cambiare backend embedding — documentato al call site).
- **FE**: `types/openrouter.ts`, `services/api/openrouter.ts`, settings store
  (`provider/openrouterModel/openrouterFavorites` + `openrouterKeyConfigured` + `setOpenrouterApiKey`),
  `stores/openrouter.ts` (filteredModels favorites-first), `OpenRouterManager.vue` (sezione
  "Provider" in SettingsView), `OpenRouterCatalog.vue` (lista editoriale), `ModelSelector.vue`
  provider-aware, chip costo in `ChatInput.vue`/`HorizonCockpit.vue` (`utils/formatCost.ts`).

## Gotchas scoperti in sessione (NON ripeterli)

1. **Suite pytest**: `tests/` intero dura 15-20+ min (test full-lifespan ~26s l'uno). MAI lanciarla
   da un subagent in foreground: usa run in background con timeout ampio, o sottoinsiemi mirati.
2. **Provider/header fissati alla costruzione**: `_is_openrouter`/`_is_ollama` e gli header httpx
   sono snapshot in `__init__` di LLMClient/ModelResolver/LLMService — ogni cambio passa dal rebuild.
3. **PUT /api/config persiste il BODY GREZZO** (`persist_from_update(body)`): ogni valore
   normalizzato va scritto back in `llm_updates` (che ALIASA `body["llm"]` — commento load-bearing
   nel codice). Bug reale trovato e fixato: la maschera `"***"` clobberava la chiave persistita.
4. **Maschera `"***"`**: mai sovrascrivere la chiave reale (né in memoria né nelle prefs); non
   esiste un percorso per CANCELLARE la chiave via API (deliberato, documentato).
5. **Registry namespaced per provider** (riscritto post-F4, `2b00667`): i profili vivono in due
   namespace (`local` = LM Studio/Ollama/KNOWN_MODELS, `openrouter` = catalogo). `get_profile`
   e i `mark_*` richiedono `namespace=` keyword-only; il fuzzy match esiste SOLO nel namespace
   local (tag Ollama ↔ path LM Studio), i lookup openrouter sono solo esatti. Gli id `org/model`
   che collidono tra i provider ora coesistono con profili indipendenti — il vecchio non-clobber
   su `source=="lmstudio_api"` NON esiste più. I campi runtime-learned restano preservati
   per-namespace nei refresh.
6. **`turn.finished`**: la chiave `cost` è sempre presente (None quando non riportato) — i test
   key-set in `test_turn_events.py` sono stati aggiornati; se aggiungi campi al frame, aggiornali.
7. **Sottostima nota del costo**: subagent, summarization/compaction e reflection non sono tracciati
   (solo le generazioni del turno principale). Etichetta UI tenuta generica apposta.
   Seconda classe (fix post-merge 2026-07-16): i turni che finiscono in **errore** vengono
   rollbackati da `_persist_final_turn` (niente in DB), quindi `DirectTurnExecutor._finish` manda
   `cost=None` sul frame `turn.finished` — il chip live non somma mai un costo che il reload non
   può confermare (il costo degli step intermedi è speso davvero ma entra nella sottostima).
   Restano due divergenze residue rare in cui il frame porta cost>0 non persistito: turno
   **cancellato senza contenuto** e turno **solo-tool senza messaggio finale** (i due
   `logger.debug` in `_persist.py`).
8. **FE**: la API key NON vive mai nello stato reattivo (solo `openrouterKeyConfigured` boolean);
   `useOpenrouterStore` è un singleton condiviso tra i ModelSelector llm/embedding (il clear della
   searchQuery è guardato con `isOpenrouterProvider` — non rimuovere il guard).
9. **UI kit**: leggere SEMPRE le prop reali (UiEmptyState usa `subtitle` non `description`;
   UiIconButton richiede `label`; icona `star` unica con `active`, non esiste `star-filled`).
10. **Line endings**: un Edit su file LF può produrre CRLF — controllare il diff prima di committare.

## Debito preesistente censito (aggiornato all'audit follow-up 2026-07-16 sera)

- ~~`test_plugins_enabled_list` rosso a baseline~~ **risolto** (`13a7bd0`): via il conteggio
  hardcoded, restano membership + invariante niente-duplicati.
- ~~ruff ~500 violazioni repo-wide senza gate~~ **bonifica COMPLETA a zero** + step
  **"Backend lint (ruff)"** in `contracts.yml` (branch fix/settings-followups-lint-gate,
  dettaglio in `docs/superpowers/audits/2026-07-16-followups-audit.md`). Eccezioni deliberate
  censite in `per-file-ignores` con motivazione. Gotcha operativo: `ruff --fix` riscrive i
  file con EOL nativi — il repo ha EOL misti per file (52 file CRLF), ripristinare l'EOL
  di HEAD dopo ogni bonifica.
- mypy: stub `types-PyYAML` ANCORA non installati; ~2.400 errori strict pre-esistenti
  (mypy non è gate in CI); `backend/dist/` inquina i run da root (candidato exclude).
- `get_active_context_window`: la nota T2 è quasi assorbita — ora termina su
  `get_cached_context_window`, che HA lo short-circuit openrouter; resta solo un probe LM Studio
  inutile quando provider=openrouter (nessun caller produttivo).

## Come riprendere

1. Leggi questo handoff, poi spec e piano (le deviazioni dal piano sono documentate nei messaggi
   di commit e sono tutte sanzionate dalle review).
2. Resta solo: **e2e con API key reale insieme all'utente** (punto 4 del task 16) e l'eventuale
   esito della pytest integrale se non annotato in §Post-merge.
3. Convenzioni vincolanti: endpoint nuovi con `response_model` (ratchet), frame WS nel vocabolario
   congelato, `gen-contracts.ps1` dopo ogni modifica contratto, import-linter, niente `any` FE,
   token-only styling dual-theme.
