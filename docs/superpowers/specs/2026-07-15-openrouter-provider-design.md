# OpenRouter come provider paritario — Design

**Data:** 2026-07-15
**Stato:** approvato (brainstorming con l'utente)
**Branch previsto:** `feat/openrouter-provider`

## Obiettivo

Aggiungere OpenRouter (https://openrouter.ai) come **terzo provider LLM di pari rango**
accanto a LM Studio e Ollama. "Paritario" significa: UX di prima classe (catalogo
modelli con prezzi, saldo crediti, preferiti, costo per conversazione), non un
campo base_url nascosto nelle impostazioni. L'identità del progetto passa da
"100% locale" a "local-first con provider cloud opzionale di pari rango"
(CLAUDE.md/README da aggiornare di conseguenza).

**Convivenza a runtime:** un solo provider attivo alla volta (`llm.provider`),
come oggi. Lo switch è globale e avviene dalle impostazioni. Niente routing
per-conversazione o per-ruolo (valutato e rimandato).

## Decisione SDK (esito ricerca doc ufficiale)

- **API REST** `https://openrouter.ai/api/v1` — OpenAI-compatible (chat
  completions SSE, tool calling, structured output). **È quella che usiamo.**
- **Client SDK** (`openrouter` PyPI, `@openrouter/sdk` npm, Go) — wrapper sottile
  type-safe auto-generato sulla REST. **Non adottato**: il nostro `LLMClient`
  (`backend/services/llm/client.py`) è già un client OAI-compatible maturo
  (SSE con cancellazione, parsing `<think>`, probing capacità, tool-call
  streaming). L'SDK richiederebbe un secondo percorso di streaming o una
  riscrittura, per ottenere in cambio un header di auth e due GET.
- **Agent SDK** (`@openrouter/agent`, TypeScript-only) — framework di agent loop.
  **Non adottato**: duplica il cuore di Alice (`run_tool_loop`, meta-tool agent,
  permission gate). La stessa doc OpenRouter indirizza chi ha già il proprio
  loop verso l'API diretta.

Ciò che OpenRouter richiede in più rispetto a LM Studio/Ollama:
`Authorization: Bearer <key>`, header di attribution opzionali (`HTTP-Referer`,
`X-Title`), e due endpoint ancillari (`GET /models`, `GET /key`).

## 1. Backend — provider e streaming

- `LLMConfig.provider` accetta `"openrouter"` come terzo valore.
- Nuova sezione config `OpenRouterConfig` (pydantic-settings, env prefix
  `ALICE_OPENROUTER__`): `api_key: str = ""`, `base_url: str =
  "https://openrouter.ai/api/v1"`. Flag censiti in `docs/flag-registry.md`.
- `LLMClient`: con provider `openrouter` si usa **solo** il percorso
  OAI-compat esistente (`/chat/completions`; il percorso nativo LM Studio è
  già gated su `use_native`). Vengono aggiunti gli header `Authorization` +
  attribution. Le opzioni Ollama-specifiche (`num_ctx`, `num_gpu`,
  `keep_alive`) restano ignorate.
- `ModelResolver`: ramo dedicato — per OpenRouter non esiste "modello caricato";
  il modello attivo è `config.llm.model` (es. `anthropic/claude-sonnet-5`),
  nessun probing di `/v1/models` locale.
- **Capacità auto-derivate:** `supported_parameters` (tools, reasoning, …) e
  `architecture.modality` (vision) dal catalogo alimentano il
  `ModelCapabilityRegistry`. Con OpenRouter i flag manuali
  `supports_vision`/`supports_thinking` non vengono consultati.
- **Guardia embedding** (punto critico): oggi
  `backend/core/bootstrap/knowledge.py` costruisce `EmbeddingClient` su
  `config.llm.base_url`. Con provider `openrouter` il backend remoto viene
  saltato e si usa direttamente fastembed (CPU, locale). La memoria non tocca
  mai il cloud; le dimensioni dei vettori Qdrant restano stabili; nessun costo
  nascosto.

## 2. Backend — catalogo e crediti

- Nuovo servizio `backend/services/openrouter_service.py` (solo httpx, zero
  dipendenze nuove):
  - `GET {base_url}/models` — catalogo (~400 modelli) con `id`, `name`,
    `pricing` (prompt/completion per token), `context_length`,
    `architecture.modality`, `supported_parameters`. Cache in-process TTL ~1h,
    invalidabile.
  - `GET {base_url}/key` — stato chiave: `limit`, `limit_remaining`, `usage`
    (+ breakdown daily/weekly/monthly).
- Nuove route `backend/api/routes/openrouter.py` (prefisso `/api/openrouter`):
  - `GET /api/openrouter/models` — catalogo serializzato, `response_model`
    Pydantic (gate contracts).
  - `GET /api/openrouter/credits` — saldo/uso, `response_model` Pydantic.
  - Errori puliti quando la chiave manca o non è valida (401 → messaggio
    actionable, non stacktrace).
- **Preferiti:** lista `openrouter.favorites: list[str]` persistita nel layer
  utente del `LayeredConfigService` (stesso pattern di `llm.disabled_tools`).
  Mutazione via `PUT /api/config` esistente — nessun endpoint dedicato.

## 3. Costo per conversazione

- Le richieste streaming verso OpenRouter includono `usage: {include: true}`;
  l'ultimo chunk SSE riporta prompt/completion tokens e **costo in crediti**
  della generazione.
- Persistenza: nuova colonna nullable `usage` (JSON:
  `{prompt_tokens, completion_tokens, cost}`) su `Message` — affianca il
  `token_count` esistente senza toccarlo. Migrazione additiva (colonna
  nullable).
- Costo per conversazione = SUM on-read sui messaggi (niente contatori
  duplicati sulla conversazione).
- Il frame WS di fine turno si estende con il costo (campo opzionale):
  aggiornamento modello in `backend/api/ws_schema/`, rigenerazione contratti,
  handler nel dispatcher esaustivo FE (`useEventsWebSocket.ts` o il canale
  chat, a seconda del frame).

## 4. Frontend — UX paritaria

- **Switcher provider** nelle impostazioni modelli: LM Studio / Ollama /
  OpenRouter come scelte di pari rango. Per OpenRouter: campo API key
  (input masked, salvataggio via `PUT /api/config`), stato connessione.
- **Catalogo** — nuovo componente `OpenRouterCatalog.vue` accanto a
  `ModelManager.vue`: ricerca, filtri per capacità (tools/vision/reasoning) e
  fascia di prezzo, ordinamento; card modello con prezzo in/out per Mtok,
  context window, badge capacità, stella preferito, azione "usa questo
  modello". Preferiti in cima al selettore rapido (`ModelSelector.vue`).
- **Saldo crediti** nell'header del catalogo e nelle impostazioni, refresh
  on-demand (bottone), non polling.
- **Costo conversazione** mostrato nella chat accanto agli indicatori di
  contesto esistenti, solo quando il provider attivo è OpenRouter.
- Stato FE: estensione dello store `settings` (provider, api key masked,
  favorites) e nuovo modulo API `services/api/openrouter.ts`; catalogo e
  crediti possono vivere in uno store dedicato `openrouter.ts` se lo stato
  supera il locale-al-componente.
- Design secondo la skill frontend-design ma **dentro il linguaggio Horizon**
  (token dual-theme, kit del rework UI/UX): superficie editoriale coerente,
  non un pezzo estraneo.

## 5. Sicurezza chiave API

- La chiave è **inserita a runtime dalla UI** e applicata immediatamente
  (rebuild config via `LayeredConfigService`, publish `config.changed`,
  nessun riavvio).
- Persistita nel **file di config utente locale in chiaro** (stessa politica
  dell'`api_token` LM Studio esistente; macchina personale, trade-off
  accettato esplicitamente). Override possibile via env
  `ALICE_OPENROUTER__API_KEY`.
- **Masking obbligatorio:** nessuna risposta API (`GET /api/config` incluso)
  restituisce mai la chiave in chiaro — formato `sk-or-…xxxx`. Il backend
  riconosce il valore masked in scrittura e non sovrascrive la chiave reale
  con la maschera.

## 6. Test e gate

- **Unit backend:** header auth nel client (httpx mock), guardia embedding
  (provider openrouter → fastembed), parsing catalogo/crediti, masking della
  chiave, persistenza `usage` e SUM per conversazione.
- **Contract:** `response_model` sulle nuove route (ratchet), frame WS nuovi
  nel vocabolario congelato, `.\scripts\gen-contracts.ps1` +
  `check-contracts.ps1`.
- **Qualità:** `ruff check`, `mypy` (strict), `lint-imports` (il servizio sta
  in `services/`, le route in `api/` — nessun nuovo accoppiamento),
  `npm run typecheck`, `npm run lint`.

## Fuori scope (segnalato, non incluso)

- Routing automatico locale/cloud o per-ruolo (chat cloud + summarization locale).
- Preset "veloce/economico/potente".
- Wizard di primo avvio locale-vs-cloud.
- Embeddings via OpenRouter (la memoria resta locale by design).
- Provisioning chiavi / gestione account OpenRouter via API.
