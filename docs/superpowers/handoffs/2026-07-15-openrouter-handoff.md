# Handoff — Provider OpenRouter (feat/openrouter-provider)

**Data:** 2026-07-15 · **Branch:** `feat/openrouter-provider` (27 commit su `abc3130`, NON pushato, non mergiato)
**Spec:** `docs/superpowers/specs/2026-07-15-openrouter-provider-design.md`
**Piano:** `docs/superpowers/plans/2026-07-15-openrouter-provider.md` (16 task)
**Metodo:** subagent-driven — ogni task: implementer + spec review + quality review; tutti i rilievi bloccanti risolti in-branch.

## Stato: task 1–15 COMPLETI e approvati, task 16 PARZIALE

Feature completa end-to-end nel codice: OpenRouter è il terzo provider LLM di pari rango
(catalogo con prezzi/capacità, saldo crediti, preferiti, costo per conversazione live+persistito,
switch provider a runtime, guardia embedding). Docs identità aggiornati (CLAUDE.md, README).

### Cosa resta del task 16 (verifica finale)

1. **`pytest tests/` COMPLETO mai portato a termine** — il processo è stato interrotto due volte
   (la suite integrale dura 15-20+ minuti). Tutti i sottoinsiemi mirati eseguiti per-task sono verdi
   (inclusi i lenti: branch_conversation/message_editing/models = 45 passed in 13 min).
2. **`ruff check backend/` e `mypy backend/` globali interrotti** — per-file verdi su ogni file toccato
   (zero errori NUOVI, debito preesistente censito sotto).
3. **Review finale olistica sull'intero diff** — dispatchata ma il risultato è andato perso per un
   errore interno; da rifare (`git diff abc3130..HEAD`).
4. **Verifica e2e con API key reale** (serve l'utente): switch a openrouter → chiave → catalogo →
   crediti → messaggio in chat con chip costo → riavvio (persistenza) → ritorno a lmstudio intatto →
   log memoria solo fastembed.
5. Push del branch + merge: da decidere dopo la sessione di fix.

Gate già verdi a fine sessione: `lint-imports` (6 contratti kept), `check-contracts.ps1`,
`pytest tests/contracts/` (98), FE `typecheck`/`lint`/`vitest` (369/369).

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
5. **Registry condiviso** LM Studio/OpenRouter: `refresh_from_openrouter` NON clobbera profili
   `source=="lmstudio_api"` e preserva i campi runtime-learned (id `org/model` collidono davvero).
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

## Debito preesistente censito (NON introdotto dal branch — non "fixarlo di straforo")

- `test_plugins_enabled_list` fallisce a baseline (conta 20 vs 21 plugin, hardcoded stale).
- ruff: `db/models.py` (Optional/UP045 diffusi), `api/routes/config.py` (11× B904),
  `api/routes/__init__.py` (I001/E501 sulla riga import lunga),
  `services/model_capability_registry.py` (F401 `field` inutilizzato), `tool_loop.py` (B905/E501/I001).
- mypy: stub `types-PyYAML` non installati.
- `get_active_context_window` non ha lo short-circuit openrouter (nessun caller produttivo; nota
  della review T2).

## Come riprendere

1. Leggi questo handoff, poi spec e piano (le deviazioni dal piano sono documentate nei messaggi
   di commit e sono tutte sanzionate dalle review).
2. Completa i 5 punti del task 16 sopra, POI affronta i fix che l'utente richiederà nella sessione.
3. Convenzioni vincolanti: endpoint nuovi con `response_model` (ratchet), frame WS nel vocabolario
   congelato, `gen-contracts.ps1` dopo ogni modifica contratto, import-linter, niente `any` FE,
   token-only styling dual-theme.
