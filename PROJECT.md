# O.M.N.I.A. — Orchestrated Modular Network for Intelligent Automation

> Assistente AI personale, 100% locale, modulare e estensibile.

---

## Overview

OMNIA è un assistente AI personale ispirato a Jarvis (Iron Man), costruito per funzionare interamente in locale senza dipendenze da servizi cloud a pagamento. L'architettura è modulare (plugin-based) e progettata per essere spostabile su un server dedicato in futuro.

## Hardware Target

| Componente | Spec |
|---|---|
| GPU | NVIDIA RTX 5080 16GB VRAM |
| CPU | AMD Ryzen 9 9950X3D |
| RAM | 32GB DDR5 |
| OS | Windows |

## Stack Tecnologico

| Componente | Tecnologia |
|---|---|
| LLM locale | LM Studio / Ollama (OpenAI-compatible) + Qwen 3.5 9B (~6GB VRAM, vision nativo) + Thinking (QwQ, DeepSeek R1) |
| STT | faster-whisper large-v3 (~1.5GB VRAM) |
| TTS | Piper TTS (primario, CPU) + XTTS v2 (opzionale, voice cloning) |
| Backend | Python — FastAPI + uvicorn (ASGI) |
| Frontend | Electron + Vue 3 + TypeScript + Pinia (via electron-vite) |
| Comunicazione | WebSocket (streaming) + REST API (CRUD) |
| Database | SQLite + SQLModel |
| PC Automation | pywinauto + pyautogui + pywin32 |
| IoT | Home Assistant REST API + MQTT (paho-mqtt) |
| Ricerca Web | duckduckgo-search (o SearXNG self-hosted) |
| Python Deps | uv |
| Node Deps | npm |

## Architettura

```
┌─────────────────────────────────────────────────────────┐
│               ELECTRON + VUE 3 (Frontend)               │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────────┐ │
│  │ Voice UI │  │ Chat UI  │  │ Plugin UIs (dinamiche) │ │
│  └────┬─────┘  └────┬─────┘  └────────────┬───────────┘ │
│       │ audio        │ json                │ json       │
│       └──────────WebSocket / REST──────────┘            │
└──────────────────────┬──────────────────────────────────┘
                       │  ws://localhost:8000
┌──────────────────────┼───────────────────────────────────┐
│                      ▼      FASTAPI BACKEND              │
│  ┌─────────┐ ┌─────────────┐                             │
│  │ STT Svc │ │ LLM Svc     │──→ LMStudio (:1234)         │
│  │(whisper)│ │(es. Qwen9B) │←── streaming tokens         │
│  └────┬────┘ └────┬────────┘                             │
│       │ text      │ tool calls                           │
│       ▼           ▼                                      │
│  ┌──────────────────────────────┐   ┌─────────┐          │
│  │      Plugin Manager          │   │ TTS Svc │→Speaker  │
│  │ ┌─────┐┌─────┐┌──────┐┌───┐  │   │ (Piper) │          │
│  │ │ PC  ││ IoT ││Search││Cal│  │   └─────────┘          │
│  │ └──┬──┘└──┬──┘└──┬───┘└─┬─┘  │                        │
│  └────┼──────┼──────┼──────┼────┘                        │
└───────┼──────┼──────┼──────┼─────────────────────────────┘
        ▼      ▼      ▼      ▼
     Windows  Home   DDG/   SQLite
     OS APIs  Asst.  SearXNG
              MQTT
```

### Persistenza Conversazioni

```
data/conversations/
├── {uuid}.json          # Una conversazione completa (metadata + messaggi)
├── {uuid}.json
└── ...
```

Ogni conversazione è salvata come file JSON atomico, sincronizzato automaticamente ad ogni modifica. Questo layer fornisce:
- **Durabilità**: i dati sopravvivono a corruzione del DB SQLite
- **Portabilità**: export/import di conversazioni come singoli file JSON
- **Recovery**: ricostruzione completa del DB da file
- **Leggibilità**: formato JSON human-readable per debug e backup

## Budget VRAM/RAM

| Componente | VRAM | RAM |
|---|---|---|
| Qwen 3.5 9B (Ollama, vision nativo) | ~6 GB | ~1 GB |
| Thinking models (swap: QwQ, DeepSeek R1) | ~6-10 GB (shared) | ~1 GB |
| faster-whisper large-v3 | ~1.5 GB | ~0.5 GB |
| Piper TTS | 0 | ~0.1 GB |
| FastAPI + Plugin | 0 | ~0.5 GB |
| Electron + Vue | 0 | ~0.3 GB |
| **Totale** | **~7.5 / 16 GB** | **~2.4 / 32 GB** |

## Roadmap

### Fase 0 — Setup Progetto e Toolchain
- [x] Struttura monorepo
- [x] Backend Python (pyproject.toml, venv, deps)
- [x] Frontend Electron + Vue 3 + TS
- [x] Script di setup/dev
- [x] Git init + .gitignore

### Fase 1 — Core Backend + Chat Testuale
- [x] Config system (Pydantic Settings + YAML)
- [x] AppContext (DI container)
- [x] Event Bus asincrono
- [x] FastAPI app factory
- [x] Ollama + Qwen 3.5 9B setup (vision nativo)
- [x] LLM Service con streaming
- [x] WebSocket chat endpoint
- [x] REST chat history
- [x] Database (SQLite + SQLModel)

### Fase 1.5 — Supporto Multimodale + Thinking

- [x] Thinking model support (QwQ, DeepSeek R1) — parsing `<think>` tags + reasoning_content delta
- [x] Thinking token streaming via WebSocket (`type: "thinking"`)
- [x] Frontend thinking display (collapsible reasoning block)
- [x] Vision model support (LLaVA, Qwen2-VL) — multimodal content format
- [x] Image upload endpoint (POST /chat/upload)
- [x] Image attachment UI (paste, drag-drop, file picker)
- [x] Image display in message bubbles
- [x] Attachment DB model + file storage

### Fase 1.6 — Persistenza Conversazioni su File
- [x] ConversationFileManager service (salvataggio atomico JSON)
- [x] Struttura file: `data/conversations/{id}.json`
- [x] Auto-sync DB → file su ogni mutazione (create, message, delete, rename)
- [x] REST: `POST /api/chat/conversations` (creazione immediata)
- [x] REST: `GET /api/chat/conversations/{id}/export` (export JSON)
- [x] REST: `POST /api/chat/conversations/import` (import JSON)
- [x] Recovery DB da file JSON
- [x] Frontend: persistenza immediata conversazioni
- [x] Frontend: sync su riconnessione WebSocket
- [x] Frontend: export/import conversazioni
- [x] Edge case: backend offline, stream parziali, conversazioni orfane

### Fase 1.7 — Code Block con Syntax Highlighting e Copia
- [x] Syntax highlighting via highlight.js (25+ linguaggi: JS, TS, Python, Java, C#, C++, Go, Rust, Ruby, PHP, SQL, HTML, CSS, JSON, YAML, Bash, etc.)
- [x] Header code block con label linguaggio
- [x] Pulsante "Copia" nel header con feedback visivo ("Copiato!")
- [x] Copia raw code nella clipboard al click
- [x] Tema syntax highlighting warm-gold coerente con estetica OMNIA
- [x] Supporto in MessageBubble (messaggi completati)
- [x] Supporto in StreamingIndicator (risposte in streaming)

### Fase 2 — Frontend Base + Chat UI
- [x] Electron window frameless + custom title bar
- [x] WebSocket manager
- [x] LLM stream composable
- [x] Pinia chat store
- [x] Chat UI components (ChatView, MessageBubble, ChatInput, StreamingIndicator)

### Fase 2.5 — Hardening & Debito Tecnico Pre-Plugin

> Correzioni necessarie prima di iniziare Fase 3. Riducono debito tecnico e prevengono regressioni.

#### 2.5.1 — Backend Hardening
- [x] **Tipizzazione AppContext**: sostituire `Any` con Protocol/tipo concreto per `llm_service`, `stt_service`, `tts_service`, `plugin_manager`
- [x] **BaseService Protocol**: creare `BaseService` con `async start()`, `async stop()`, `async health_check()` — tutti i service futuri lo implementano
- [x] **Config immutabilità**: rimuovere `object.__setattr__` mutation; costruire config come frozen Pydantic model, ricreare istanza se serve
- [x] **Event bus enum**: convertire event names da magic strings (`"llm.response"`) a `enum.StrEnum` (type-safe, refactoring-safe)
- [x] **N+1 query fix**: riscrivere lista conversazioni con `SELECT COUNT(*) GROUP BY` invece di N query separate
- [x] **Connection pool config**: aggiungere `pool_size`, `max_overflow`, `pool_pre_ping` a `create_async_engine()`
- [x] **File upload security**:
  - Max file size (50 MB) in config + validazione
  - Validazione `conversation_id` come UUID (anti path-traversal)
  - Verifica magic bytes per tipo file (non solo MIME type)
  - Cleanup file orfani se transazione DB fallisce
- [x] **URL generation safe**: sostituire `str.split("data/uploads/")` con `pathlib.Path.relative_to()` + `urllib.parse.quote()`
- [x] **Timeout LLM configurabile**: spostare `httpx.AsyncClient(timeout=120.0)` in config, con override per-request
- [x] **Rate limiting minimo**: `slowapi` middleware su REST + max WS connections per IP

#### 2.5.2 — Frontend Hardening
- [x] **Memory leak blob URL**: revocare `URL.createObjectURL()` su cleanup/re-render in `ChatInput.vue`
- [x] **Race condition conversation switch**: dedup richieste, cancellare stream al cambio conversazione
- [x] **Backpressure WebSocket**: buffer check prima di send; coda con limite
- [x] **Virtualizzazione ConversationList**: `vue-virtual-scroller` o simile per 1000+ conversazioni
- [x] **Estrazione componente condiviso**: eliminare duplicazione 100+ righe tra `MessageBubble` e `StreamingIndicator`
- [x] **Error boundary**: componente Vue `<ErrorBoundary>` per isolare crash plugin UI futuri
- [x] **Accessibilità base**: ARIA labels su pulsanti, focus indicators, keyboard navigation sidebar

#### 2.5.3 — Sicurezza Electron
- [x] **Sandbox attivo**: `sandbox: true` + `nodeIntegration: false` + `contextIsolation: true` in `BrowserWindow`
- [x] **CSP header**: `Content-Security-Policy` in `index.html` — `default-src 'self'; connect-src ws://localhost:8000 http://localhost:8000; img-src 'self' blob: data: http://localhost:8000`
- [x] **CORS produzione**: rimuovere `"null"` da `cors_origins` e usare whitelist specifica per environment (dev vs prod)

#### 2.5.4 — Test Coverage Gap
- [x] Test WebSocket: connessione, invio messaggio, ricezione stream, disconnessione, riconnessione
- [x] Test file upload: validazione tipo, size limit, path traversal rejection
- [x] Test ConversationFileManager: file corrotto, disco pieno, permessi mancanti
- [x] Test concurrent: 10+ WS simultanei, race condition su stessa conversazione

---

### Fase 3 — Plugin System

#### 3.1 — BasePlugin ABC + PluginManager
- [x] `BasePlugin` ABC con interfaccia completa:
  - `plugin_name: str` — nome univoco del plugin (match chiave `PLUGIN_REGISTRY`)
  - `plugin_version: str` — semver (es. `"1.0.0"`)
  - `PLUGIN_API_VERSION: str` — semver API contract (per compatibilità retroattiva)
  - `plugin_dependencies: list[str]` — nomi plugin da cui dipende (per load order)
  - `plugin_priority: int = 50` — ordine esecuzione 0-100 (più alto = priorità maggiore)
  - `requires_user_confirmation: bool = False` — override in plugin distruttivi (Fase 5)
  - `async def initialize(ctx: AppContext)` / `async def cleanup()` (I/O deferred, no side-effects in `__init__`)
  - `async def on_app_startup()` / `async def on_app_shutdown()` (per plugin stateful: MQTT, HA)
  - `def get_tools() -> list[ToolDefinition]` — restituisce le definizioni tool (può essere vuoto)
  - `async def execute_tool(tool_name: str, args: dict, context: ExecutionContext) -> ToolResult`
  - `async def cancel_tool(tool_name: str, execution_id: str)` — default no-op
  - `async def pre_execution_hook(tool_name, args) -> bool` (canary per conferma utente)
  - `def check_dependencies() -> list[str]` (segnala dipendenze opzionali mancanti senza crash)
  - `async def get_connection_status() -> ConnectionStatus` — `connected|disconnected|degraded|error` (default `UNKNOWN`)
  - `async def on_dependency_status_change(plugin_name: str, status: ConnectionStatus)` — notifica cambio stato dipendenza
  - `@classmethod def get_config_schema() -> dict` — JSON Schema per config plugin-specifica (UI auto-generata Fase 8)
  - `@classmethod def get_db_models() -> list[type[SQLModel]]` — modelli DB plugin-specifici (tabelle create a startup)
  - `@classmethod async def migrate_config(from_version, old_config, to_version) -> dict` — migrazione config tra versioni
  - `@property def logger` — logger pre-configurato con `bind(plugin=self.plugin_name)`
- [x] `ToolDefinition` dataclass:
  - `name: str` — nome tool (`^[a-zA-Z0-9_-]{1,64}$`)
  - `description: str` — max 1024 caratteri
  - `parameters: dict` — JSON Schema per argomenti
  - `result_type: Literal["string", "json", "binary_base64"]` — tipo risultato
  - `supports_cancellation: bool = False`
  - `timeout_ms: int = 30000` — timeout esecuzione
  - `requires_confirmation: bool = False` — richiede approvazione utente (Fase 5)
  - `risk_level: Literal["safe", "medium", "dangerous", "forbidden"] = "safe"`
- [x] `ToolResult` dataclass:
  - `success: bool`
  - `content: str | dict | None` — risultato principale (string per OpenAI compat)
  - `content_type: str` — `"text/plain"`, `"application/json"`, `"image/png"`, etc.
  - `execution_time_ms: float`
  - `truncated: bool = False` — True se risultato tagliato per dimensione
  - `error_message: str | None`
- [x] `ExecutionContext` dataclass:
  - `user_id: str | None = None` — forward-compat Fase 8 JWT
  - `session_id: str`
  - `conversation_id: str`
  - `execution_id: str` — UUID per tracciamento/audit
- [x] `ConnectionStatus` enum: `UNKNOWN`, `CONNECTED`, `DISCONNECTED`, `DEGRADED`, `ERROR`
- [x] `PluginManager` con:
  - Registro **statico** (`PLUGIN_REGISTRY` dict) per compatibilità PyInstaller (Fase 8)
  - Flag env `OMNIA_PLUGIN_DISCOVERY=dynamic` per scan `importlib` in dev
  - **Risoluzione dipendenze**: topological sort (algoritmo di Kahn) con cycle detection
  - **Load order deterministico**: dipendenze prima, poi per `plugin_priority`
  - Isolamento crash per ogni plugin: `ImportError`, `SyntaxError`, `AttributeError` non abbattono il server
  - Gestione stub vuoti (`__init__.py` privi di classe `BasePlugin`) senza eccezioni
  - `asyncio.Lock` per thread-safety su registry (accesso concorrente da più WS)
  - Deduplicazione nomi plugin (collision detection al load)
  - `startup()` / `shutdown()` che chiamano i lifecycle hooks su tutti i plugin attivi (in ordine dipendenze)
  - `reload_plugin(name)`: freeze new calls → wait in-flight → cleanup → re-import → re-init → update registry
  - Creazione tabelle DB plugin-specifiche a startup (`get_db_models()` → `SQLModel.metadata.create_all`)
  - Health aggregation: `get_all_status() -> dict[str, ConnectionStatus]`
  - Emissione eventi EventBus: `plugin.loaded`, `plugin.failed`, `plugin.status_changed`
- [x] `AppContext` esteso: `plugin_manager: PluginManager | None = None`, `tool_registry: ToolRegistry | None = None` (opzionali, backward-compat con test pre-Fase 3)
- [x] FastAPI lifespan: wrap PluginManager init con `try/except` + flag `app.state.healthy` se plugin critici falliscono

#### 3.2 — ToolRegistry
- [x] Aggregazione tool descriptions (OpenAI format) da tutti i plugin attivi
- [x] Validazione nome: regex `^[a-zA-Z0-9_-]{1,64}$` (compatibilità OpenAI/Ollama)
- [x] **Namespacing opzionale**: nomi tool salvati come `plugin_name + "_" + tool_name` per evitare collisioni (escape dot in underscore)
- [x] Validazione description: max 1024 caratteri (warning se > 512)
- [x] Validazione `parameters`: JSON Schema valido (fallback a schema vuoto `{"type": "object"}`, non crash)
- [x] Collision detection: tool con stesso nome da plugin diversi → errore esplicito al load
- [x] Lookup `O(1)` per tool_call dispatch (dict)
- [x] Thread-safe read (RW-compatible con `asyncio.Lock`)
- [x] **Tool availability dinamica**: `get_available_tools()` filtra per `plugin.get_connection_status() != ERROR`
- [x] **Tool timeout enforcement**: `asyncio.wait_for()` wrapper su ogni `execute_tool()` con `tool.timeout_ms`
- [x] **Tool result truncation**: se `content` > 4096 chars, troncare + `truncated=True` + log warning
- [x] **Tool result sanitization**: strip eccezioni Python, path interni, PII prima di inviare a LLM
- [x] **Errore strutturato** per tool non trovato: `ToolResult(success=False, error_message="Tool 'X' not available: plugin Y disabled")"

#### 3.3 — Tool Calling Loop + History Fix
- [x] **Refactor `build_messages()`**: normalizza `Message` DB → OpenAI-compatible includendo `tool_calls` (per `role:"assistant"`) e `tool_call_id` (per `role:"tool"`)
- [x] **Refactor history fetch** in `ws_chat`: usare normalizzatore invece di `{"role", "content"}` solo
- [x] Tool calling loop in `ws_chat`:
  - `MAX_TOOL_ITERATIONS = 10` (anti-loop-infinito, configurabile)
  - `asyncio.gather` per parallel tool_calls nella stessa risposta LLM
  - **Ogni tool_call**: `asyncio.wait_for(execute, timeout=tool.timeout_ms/1000)` con `TimeoutError` handling
  - Error handling per tool execution: errori formattati come `{"role": "tool", "content": "Error: ..."}` — l'LLM riceve errori strutturati, non eccezioni Python
  - Salvataggio in DB di messaggi `role:"tool"` con `tool_call_id` dopo ogni esecuzione
  - Sync file JSON dopo ogni round di tool execution
  - **Recovery**: se WS si chiude mid-loop, cleanup tool in-flight + salva stato parziale
  - **Dedup**: se LLM chiama stesso tool con stessi args nella stessa iterazione, skip e log warning
- [x] **Confirmation flow (async)**: se `tool.requires_confirmation`:
  1. Invia `{"type": "tool_confirmation_required", "tool_name": ..., "args": ..., "execution_id": ...}` al client
  2. Attendi risposta `{"type": "tool_confirmation_response", "execution_id": ..., "approved": bool}` con timeout 60s
  3. Se approvato → esegui; se rifiutato o timeout → `ToolResult(success=False, error_message="User rejected")`
- [x] `ExecutionContext` dataclass: `user_id=None`, `session_id`, `conversation_id`, `execution_id` — forward-compat con Fase 8 JWT multi-user
- [x] **Audit trail**: emetti `EVENT_TOOL_EXECUTION_START`, `EVENT_TOOL_EXECUTION_SUCCEEDED`, `EVENT_TOOL_EXECUTION_FAILED` su EventBus

#### 3.4 — Plugin system_info (esempio)
- [x] `psutil` con lazy import (`try/except ImportError` + `check_dependencies()`)
- [x] Tool: `get_system_info()` → CPU%, RAM%, disco, OS — output whitelist (no path utente, no processi privati)
- [x] Tool: `get_process_list()` → lista processi (filtrata, no PID sensibili)
- [x] Schema JSON Schema per parametri e validazione argomenti prima dell'esecuzione
- [x] `risk_level: "safe"` per entrambi i tool (nessuna conferma richiesta)
- [x] Test unitari: mock psutil, verifica output schema, verifica whitelist campi

#### 3.5 — ConversationFileManager: schema versioning
- [x] `schema_version: int` nei file JSON (v1 = pre-Fase 3, v2 = con tool_calls)
- [x] Migration v1→v2 al caricamento (aggiunge `tool_calls: null`, `tool_call_id: null` ai messaggi legacy)
- [x] Serializzazione corretta di `role:"tool"` e `tool_calls` array nei nuovi file
- [x] **Sharding futuro**: preparare struttura `data/conversations/` per eventuale sotto-directory per user (`data/conversations/{user_id}/`)

#### 3.6 — Frontend: tool call UI
- [x] Nuovi tipi WS protocol:
  - `{"type": "tool_execution_start", "tool_name": "...", "execution_id": "..."}`
  - `{"type": "tool_execution_done", "tool_name": "...", "result": "...", "execution_id": "..."}`
  - `{"type": "tool_confirmation_required", "tool_name": "...", "args": {...}, "execution_id": "..."}`
  - `{"type": "tool_confirmation_response", "execution_id": "...", "approved": bool}` (client → server)
- [x] Loading state intermedio visibile (spinner/badge tra token LLM e risposta finale)
- [x] `MessageBubble`: visualizzazione tool calls eseguiti (collapsible, come il thinking block)
- [x] **ToolConfirmationDialog**: modale per approvazione/rifiuto azioni con risk_level ≥ medium
- [x] **Chat store**: gestione stato `pendingConfirmations: Map<execution_id, ConfirmationRequest>`

#### 3.7 — Inter-Plugin Communication + EventBus Extension
- [x] Nuovi eventi standard:
  - `plugin.loaded`, `plugin.failed`, `plugin.status_changed`
  - `tool.execution_start`, `tool.execution_succeeded`, `tool.execution_failed`
- [x] **Plugin local state**: `AppContext.plugin_local_state: dict[str, dict]` — ogni plugin aggiorna il proprio stato, read-only per gli altri via `ctx.get_plugin_state(name)`
- [x] **Circuit breaker** su EventBus: se handler fallisce N volte consecutive, disabilitare temporaneamente (evita log flood)

#### 3.8 — Test Suite Fase 3
- [x] Test BasePlugin: lifecycle (init → startup → tool_call → shutdown → cleanup)
- [x] Test PluginManager: load order, collision, crash isolation, reload
- [x] Test ToolRegistry: validazione nome, collision, lookup, thread-safety, timeout
- [x] Test tool calling loop: max iterations, parallel calls, error recovery, confirmation flow
- [x] Test system_info plugin: mock psutil, output schema
- [x] Test ConversationFileManager: migration v1→v2, serializzazione tool_calls

---

### Fase 4 — Voce (STT + TTS)

#### 4.1 — STT Service (faster-whisper)
- [x] `STTService` implementa `BaseService` protocol (`start`, `stop`, `health_check`)
- [x] faster-whisper large-v3 + Silero VAD per voice activity detection
- [x] Lazy VRAM allocation: carica modello STT solo quando voice è attivata (non a startup)
- [x] **Audio buffer validation**: max durata 5 minuti, max size 50 MB, formato supportato (wav, mp3, ogg, flac) con magic bytes check
- [x] **Timeout trascrizione**: `asyncio.wait_for(transcribe, timeout=durata_audio * 1.5)`
- [x] Config: `voice.stt.enabled: bool`, `voice.stt.model`, `voice.stt.language`, `voice.stt.vad_threshold`

#### 4.2 — TTS Service (Piper + opzionale XTTS v2)
- [x] `TTSService` implementa `BaseService` protocol
- [x] Piper TTS primario (CPU-only, ~0.1 GB RAM) — voci italiane
- [x] Opzionale: XTTS v2 per voice cloning (GPU, ~1-2 GB VRAM)
- [x] Config: `voice.tts.engine: Literal["piper", "xtts"]`, `voice.tts.voice`, `voice.tts.speed`
- [x] **Output audio streaming**: genera audio chunk-by-chunk, non attendere fine sintesi

#### 4.3 — WebSocket Voice Protocol
- [x] **Endpoint separato** `/ws/voice` (non mescolare con `/ws/chat` per evitare complessità multiplexing)
- [x] Protocollo binario + JSON su stesso WS:
  - Client → Server: binary frames (audio PCM/opus) + JSON `{"type": "voice_start"/"voice_stop"}`
  - Server → Client: binary frames (audio TTS) + JSON `{"type": "transcript", "text": "..."}`
- [x] **Head-of-line blocking prevention**: se arrivano audio + text simultanei, coda prioritizzata (text ha priorità sulla voice)
- [x] **Auto-cancellation**: se utente invia nuovo messaggio voice mentre LLM sta rispondendo, cancellare risposta precedente

#### 4.4 — Audio Capture Frontend
- [x] `useVoice` composable: `startListening()`, `stopListening()`, `isListening`, `transcript`
- [x] `navigator.mediaDevices.getUserMedia()` con config ottimale per Whisper (16kHz, mono)
- [x] **Push-to-talk** (default) + wake word opzionale
- [x] **Visual indicator**: icona microfono animata durante recording, badge durante processing
- [x] **Audio playback**: `AudioContext` per riproduzione risposte TTS, coda audio per chunk multipli
- [x] **Permessi**: richiesta esplicita permesso microfono con UX chiara; gestione denied gracefully

#### 4.5 — Voice + Tool Calling Interazione
- [x] Se voice input attiva tool call → TTS legge risposta finale (non i tool results intermedi)
- [x] **Confirmation vocale**: per tool `requires_confirmation`, sintetizzare domanda TTS + attendere risposta voice "sì/no"
- [x] Fallback: se TTS/STT non disponibili, degradare silenziosamente a text-only

#### 4.6 — VRAM Budget Manager
- [x] `VRAMMonitor` service: monitora VRAM usata via `nvidia-smi` o `pynvml`
- [x] **Budget tracking**: registra VRAM allocata per componente (LLM ~6GB, STT ~1.5GB, TTS ~0-2GB)
- [x] **Graceful degradation**: se VRAM > 14GB (su 16GB disponibili):
  - Disattiva STT VAD (usa solo push-to-talk)
  - Scalare modello STT a `medium` o `small`
  - Se XTTS attivo, fallback a Piper (CPU)
- [x] Alert via EventBus: `vram.warning`, `vram.critical`

#### 4.7 — Voice Data Privacy
- [x] Audio temporaneo: file WAV salvati in `tempfile.gettempdir()` con auto-delete dopo 60s
- [x] Nessun salvataggio permanente di audio (solo transcript in chat history)
- [x] UI: indicatore chiaro "microfono attivo" + facile disabilitazione

#### 4.8 — Test Suite Fase 4
- [x] Test STT: mock faster-whisper, verifica transcript, timeout, formati invalidi
- [x] Test TTS: mock Piper, verifica output audio, streaming chunk
- [x] Test WS voice: connessione, send audio, ricevi transcript + audio risposta
- [x] Test VRAM monitor: mock nvidia-smi, graceful degradation trigger
- [x] Test voice + tool calling: voice input → tool call → voice output completo

---

### Fase 5 — Plugin: PC Automation

> **Stato architettura attuale**: Il framework di base per risk level, conferme e tool execution è già funzionante (Fase 3). Il plugin `pc_automation` è implementato con security framework completo: whitelists (app, comandi, keys, path), post-screenshot lockout, FORBIDDEN enforcement, reasoning in conferma, audit trail DB + REST endpoint. 109 test dedicati.

#### 5.1 — Security Framework (PREREQUISITO — questa è la fase più critica per sicurezza)
- [x] `risk_level`: già implementato come `Literal["safe", "medium", "dangerous", "forbidden"]` in `ToolDefinition` (`plugin_models.py`)
- [x] `requires_confirmation: bool` già in `ToolDefinition` — gate nel tool loop (`_tool_loop.py`)
- [x] **Enforcement FORBIDDEN**: check esplicito in `_tool_loop.py` — tool con `risk_level="forbidden"` vengono bloccati e loggati nell'audit
- [x] **Whitelist comandi**: dizionario comandi pre-approvati in `constants.py` (ipconfig, systeminfo, tasklist, etc.)
- [x] **Subprocess sicuro**: `shell=False`, argomenti come lista, `timeout=30s`, output troncato a 500 chars (`validators.py`)
- [x] **Path validation**: file target non in directory di sistema (`C:\Windows`, `C:\Program Files`, etc.) — `security.py:validate_path()`
- [x] **Reasoning in conferma**: `thinking_content` passato nel payload WS `tool_confirmation_required` come `reasoning`
- [x] **Post-screenshot lockout**: dopo screenshot, `execute_command` bloccato per 60s (anti-exfiltration) — `ScreenshotLockout` class
- [x] **Confirmation timing attack prevention**: rimosso `asyncio.gather()` per tool con conferma pendente

#### 5.2 — Tool Definitions (plugin `pc_automation` — `backend/plugins/pc_automation/plugin.py`)
- [x] `open_application(app_name: str)` — risk: `medium`, `requires_confirmation: True`, whitelist app names
- [x] `close_application(app_name: str)` — risk: `medium`, `requires_confirmation: True`
- [x] `type_text(text: str)` — risk: `medium`, `requires_confirmation: True`
- [x] `press_keys(keys: list[str])` — risk: `medium`, `requires_confirmation: True`, whitelist combinazioni
- [x] `take_screenshot() -> base64_png` — risk: `medium`, `requires_confirmation: True`, `timeout_ms: 10000`
- [x] `get_active_window() -> str` — risk: `safe`, `requires_confirmation: False`
- [x] `get_running_apps() -> list[str]` — risk: `safe`, `requires_confirmation: False`
- [x] `execute_command(command: str)` — risk: `dangerous`, `requires_confirmation: True`, solo whitelist
- [x] `move_mouse(x, y)` / `click(x, y)` — risk: `medium`, `requires_confirmation: True`
- [x] Registrazione plugin: `PLUGIN_REGISTRY["pc_automation"] = PcAutomationPlugin` + `config/default.yaml` plugins.enabled

#### 5.3 — Executor (async wrapper)
- [x] Pattern `asyncio.to_thread()` già consolidato nel codebase (usato in `stt_service`, `tts_service`, `system_info`, `conversation_file_manager`, ecc.)
- [x] Timeout per-tool già supportato via `ToolDefinition.timeout_ms` + `asyncio.wait_for()` in `tool_registry.execute_tool()`
- [x] Output sanitization (rimozione traceback, path) + troncamento a 4096 chars già in `tool_registry.py`
- [x] Applicare `asyncio.to_thread()` a tutte le chiamate blocking nel plugin (`executor.py`)
- [x] Error handling specifico: `ValueError`/`RuntimeError`/`OSError` catturate → `ToolResult.error()` con messaggi user-friendly
- [x] **Screenshot**: downscale automatico se > 2MP, `result_type: "binary_base64"`, lockout post-screenshot

#### 5.4 — Confirmation UI (parzialmente implementata — completare gap)
- [x] Modale `ToolConfirmationDialog.vue` esistente con: tool name badge, args JSON formattato, risk level badge colorato (warning/error/error-severe), pulsanti Approva/Rifiuta
- [x] **Keyboard shortcut**: Enter = approva, Esc = rifiuta — già implementati
- [x] Auto-approve per tool `safe` senza mostrare dialog (`useChat.ts`)
- [x] Backend: `_request_confirmation()` con timeout server-side via `config.llm.confirmation_timeout_s`
- [x] **Reasoning display**: campo `reasoning` nel payload WS e tipo TS `WsToolConfirmationRequiredMessage` — sezione collassabile nel dialog
- [x] **Timer visuale 60s**: countdown live nel dialog frontend con cambio colore + auto-reject
- [x] **Log azioni (audit trail)**: DB model `ToolConfirmationAudit` + log su ogni approvazione/rifiuto + endpoint `GET /api/audit/confirmations`
- [x] **Attiva/Disattiva approvazione**: config setting + toggle in Settings UI + warning safety

#### 5.5 — Test Suite Fase 5
- [x] Test security: tool `forbidden` non eseguibile, path traversal bloccato, shell injection bloccato, whitelist comandi (33 test in `test_security_framework.py`)
- [x] Test confirmation flow: approval, rejection, timeout, reasoning nel payload (9 test in `test_confirmation_audit.py`)
- [x] Test executor: mock pyautogui/pywinauto, `asyncio.to_thread()` wrapping (23 test in `test_pc_executor.py`)
- [x] Test screenshot: downscale, post-screenshot lockout, thread safety (9 test in `test_screenshot.py`)
- [x] Test audit trail: persistenza approvazioni/rifiuti, query endpoint, model validation
- [x] Test plugin lifecycle: attributi, init, tool definitions, risk levels (18 test in `test_pc_automation.py`)
- [x] Test validators: safe subprocess, input sanitization (15 test in `test_pc_validators.py`)

---

<!-- ### Fase 6 — Plugin: Domotica / IoT

#### 6.1 — Home Assistant Client
- [ ] `HomeAssistantService`: singleton con persistent `httpx.AsyncClient` (connection pool, non nuova connessione per ogni tool call)
- [ ] REST API: `GET /api/states`, `POST /api/services/{domain}/{service}` con retry + backoff
- [ ] WebSocket HA: subscribe state changes (real-time device updates)
- [ ] **Credential management**: `SecretStr` per token HA; config attuale usa plaintext → migrare; ideale: OS keyring (`keyring` library)
- [ ] **Connectivity validation**: test connessione a startup, emit `plugin.status_changed` se offline
- [ ] **Rate limiting**: max 10 req/s verso HA API (evitare flood)

#### 6.2 — MQTT Client
- [ ] `MQTTService`: `paho-mqtt` con persistent connection + auto-reconnect (backoff esponenziale)
- [ ] **TLS obbligatorio di default**: porta 8883, verifica certificato, TLS 1.2+
- [ ] **Credenziali sicure**: `SecretStr` per password MQTT; no plaintext in config YAML
- [ ] **QoS 1** (at least once) per comandi dispositivi
- [ ] Background task per `loop_start()` — non bloccare event loop
- [ ] **Command validation whitelist**: solo comandi conosciuti per tipo dispositivo (light, switch, lock, climate, sensor)
- [ ] **IoT command sanitization**: no caratteri speciali (`;`, `|`, `&`, backtick) nei parametri

#### 6.3 — Device Registry
- [ ] DB model: `Device(id, name, device_type, area, capabilities, protocol, last_seen, state)`
- [ ] Sync automatico da Home Assistant → device registry locale
- [ ] Filtro per area/tipo → tool descriptions contestuali per LLM
- [ ] **Device access control**: lista dispositivi "protetti" non controllabili da LLM (es. serrature, telecamere di sicurezza, allarme)
- [ ] Config: `iot.protected_devices: list[str]` — nomi/ID dispositivi mai auto-controllabili

#### 6.4 — Event-Driven Updates
- [ ] **Unsolicited messages**: quando un dispositivo cambia stato, inviare al frontend:
  - `{"type": "iot_state_update", "device_id": "...", "new_state": "...", "changed_by": "external|omnia"}`
- [ ] **Notification vs message**: gli update IoT NON finiscono nella chat history; sono notifiche separate
- [ ] Frontend: notification toast per state changes (opzionale, configurabile per dispositivo)

#### 6.5 — Test Suite Fase 6
- [ ] Test HA client: mock httpx, autenticazione, retry su errore, rate limiting
- [ ] Test MQTT: mock paho-mqtt, TLS, reconnect, QoS
- [ ] Test command validation: whitelist, sanitization, device access control
- [ ] Test device registry: sync, filtro, dispositivi protetti

--- -->

### Fase 7 — Plugin: Ricerca Web + Calendario + Meteo

> **Struttura file per ogni plugin** (pattern consolidato dal codebase):
> `backend/plugins/{name}/__init__.py` — import + `PLUGIN_REGISTRY["{name}"] = XxxPlugin`
> `backend/plugins/{name}/plugin.py` — `BasePlugin` subclass con `get_tools()` e `execute_tool()`
> File aggiuntivi (client.py, executor.py, etc.) se il plugin ha >150 righe di logica

#### 7.1 — Web Search Plugin (`backend/plugins/web_search/`)
- [x] `WebSearchPlugin(BasePlugin)` — `plugin_name = "web_search"`, `plugin_version = "1.0.0"`, `plugin_priority = 40`
- [x] `plugin_dependencies: list[str] = []` — standalone, nessun altro plugin richiesto
- [x] `WebSearchConfig(BaseSettings)` in `backend/core/config.py`:
  - `enabled: bool = False`
  - `max_results: int = 5`
  - `cache_ttl_s: int = 300` (5 min)
  - `request_timeout_s: int = 10`
  - `rate_limit_s: float = 10.0` (min secondi fra richieste DDG)
  - `proxy_http: str | None = None`, `proxy_https: str | None = None`
- [x] Entry in `config/default.yaml`: `web_search:` section + `web_search` nella lista `plugins.enabled` (disabled by default)
- [x] `backend/plugins/web_search/client.py`:
  - `WebSearchClient` — singleton su `httpx.AsyncClient` persistente (connection pool, non ricreare per ogni call, stesso pattern di HA client pianificato in Fase 6)
  - Lazy DDG import: `try: from duckduckgo_search import DDGS` con `check_dependencies()` se mancante
  - Rate limiting: `asyncio.Lock` + timestamp ultima richiesta (evita ban DDG)
  - Result caching: `functools.lru_cache` con TTL manuale (dict `{query_hash: (timestamp, results)}`)
  - `async def search(query, max_results) -> list[dict]` — `asyncio.to_thread(ddg.text, ...)` (DDG sync)
  - `async def scrape(url) -> str` — `await client.get(url, timeout=10)` → `BeautifulSoup(html, "html.parser").get_text()` → tronca a 50KB
- [x] **SSRF prevention** in `client.py` (`_validate_url(url: str) -> None`):
  - Bloccare schemi non-HTTPS/HTTP: `file://`, `ftp://`, `ssh://`, etc.
  - Risolvere hostname via `socket.getaddrinfo()` in thread (async-safe) — bloccare IP privati: `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`, `fc00::/7`
  - Bloccare `localhost` e varianti (case-insensitive)
  - Stessa funzione riusata da `weather` client (7.3) e `news` reader (7.6)
- [x] Tool `web_search`: `risk_level="safe"`, `timeout_ms=15000`, `result_type="json"` — `max_results` validato: 1–20
- [x] Tool `web_scrape`: `risk_level="medium"`, `requires_confirmation=True`, `timeout_ms=15000` — URL validata con `_validate_url()` prima dell'esecuzione
- [x] Sanitizzazione output: strip tag HTML residui + normalizzazione whitespace + tronca a 4096 chars (già gestito da `ToolRegistry`)
- [x] `get_config_schema()` per auto-generazione form Settings (Fase 8)

#### 7.2 — Calendario Plugin (`backend/plugins/calendar/`)
- [x] `CalendarPlugin(BasePlugin)` — `plugin_name = "calendar"`, `plugin_priority = 30`
- [x] `plugin_dependencies: list[str] = []` — standalone
- [x] DB models via `get_db_models()` — tabella creata da `PluginManager` a startup (già supportato):
  - `CalendarEvent(SQLModel, table=True)`: `id: uuid`, `title: str`, `description: str | None`, `start_time: datetime` (UTC), `end_time: datetime` (UTC), `recurrence_rule: str | None` (RRULE RFC 5545), `reminder_minutes: int | None`, `created_by: str = "llm"`, `created_at: datetime`
- [x] `CalendarConfig(BaseSettings)` in `config.py`:
  - `enabled: bool = False`
  - `timezone: str = "Europe/Rome"` (IANA timezone)
  - `reminder_check_interval_s: int = 60`
- [x] `on_app_startup()`: avvia `asyncio.create_task(_reminder_loop())` — background task con `asyncio.sleep(reminder_check_interval_s)`, cerca eventi con `reminder_minutes` entro la finestra, emette `calendar.reminder` su EventBus
- [x] `on_app_shutdown()`: cancella il task del reminder loop
- [x] Dipendenza: `python-dateutil ≥ 2.9` in `pyproject.toml` per RRULE parsing + `pytz` per timezone
- [x] Tool `create_event`: `risk_level="safe"`, validazione start < end, parse `start`/`end` come ISO 8601 con `dateutil.parser.parse()`, converti a UTC prima di salvare
- [x] Tool `list_events`: `risk_level="safe"`, filtra per range UTC, converti risultati a timezone utente prima di restituire
- [x] Tool `update_event`: `risk_level="safe"`, stesso processo di validazione di `create_event`
- [x] Tool `delete_event`: `risk_level="medium"`, `requires_confirmation=True`
- [x] Tool `get_today_summary`: `risk_level="safe"`, restituisce eventi di oggi (da mezzanotte a mezzanotte utente timezone)
- [x] **Edge case**: se `start_time` e `end_time` sono nello stesso fuso orario passato come stringa ISO 8601 con offset (es. `2026-03-08T15:00:00+01:00`), preservare intent senza convertire a UTC e riconvertire (usare `dateutil.parser.parse()` che mantiene tzinfo)
- [x] **Futura integrazione esterna**: colonna `external_id: str | None` + `external_source: str | None` per CalDAV/Google Calendar

#### 7.3 — Weather Plugin (`backend/plugins/weather/`)
> **Dipendenza Fase 7.1**: riusa `_validate_url()` da `web_search/client.py` — importare come utility condivisa. Alternativa (più pulita): copiare la logica in un modulo `backend/core/http_security.py` condiviso tra i plugin che fanno fetch HTTP (web_search, weather, news). **Scelta consigliata**: creare `backend/core/http_security.py` con `validate_url_ssrf(url: str) -> None` usato da tutti e tre.

- [x] **Prerequisito**: creare `backend/core/http_security.py` (SSRF check centralizzato) — rimuovere logica duplicata da web_search/client.py e usare solo questo modulo
- [x] `WeatherPlugin(BasePlugin)` — `plugin_name = "weather"`, `plugin_priority = 35`, `plugin_dependencies: list[str] = []`
- [x] Backend dati: **open-meteo.com** (free, no API key, HTTPS only) — URL: `https://api.open-meteo.com/v1/forecast`
  - Zero dipendenze cloud a pagamento, conforme al vincolo di progetto
  - Geocoding: `https://geocoding-api.open-meteo.com/v1/search` per nome città → lat/lon
- [x] `WeatherConfig(BaseSettings)` in `config.py`:
  - `enabled: bool = False`
  - `default_city: str = "Rome"` (usata se tool chiamato senza `city`)
  - `units: Literal["metric", "imperial"] = "metric"`
  - `lang: str = "it"`
  - `cache_ttl_s: int = 600` (10 min — meteo non cambia al secondo)
  - `request_timeout_s: int = 8`
- [x] `backend/plugins/weather/client.py`:
  - `WeatherClient` — `httpx.AsyncClient` persistente (non ricreare per ogni call)
  - `async def get_coordinates(city: str) -> tuple[float, float]` — geocoding con caching in `plugin_local_state`
  - `async def get_current(lat, lon, units, lang) -> dict`
  - `async def get_forecast(lat, lon, days, units, lang) -> list[dict]`
  - Caching: `{(city, units, lang): (timestamp, data)}` dict in memory — invalidato dopo `cache_ttl_s`
  - `validate_url_ssrf()` da `backend/core/http_security.py` prima di ogni fetch
- [x] Tool `get_weather(city?: str)` → `risk_level="safe"`, `timeout_ms=10000`, `result_type="json"`:
  - Output: `{city, temperature, feels_like, humidity, wind_speed, condition, uv_index, timestamp}`
  - Se `city` omesso → usa `config.weather.default_city`
- [x] Tool `get_weather_forecast(city?: str, days: int = 3)` → `risk_level="safe"`, `timeout_ms=10000`:
  - `days` validato: 1–7 (limite open-meteo free tier)
  - Output: lista di `{date, temp_max, temp_min, condition, precipitation_prob}`
- [x] `initialize()`: crea `WeatherClient`, registra in `plugin_local_state["weather"]["client"]`
- [x] `cleanup()`: chiude `httpx.AsyncClient` (`await client.aclose()`)
- [x] **Edge case**: città non trovata → `ToolResult.error("City not found: ...")` (non eccezione Python raw)
- [x] **Edge case**: open-meteo offline → `ToolResult.error("Weather service unavailable")` + emit `ConnectionStatus.DISCONNECTED` via `get_connection_status()`

#### 7.4 — Plugin UI (Vue components)
- [x] **Strategia**: plugin components bundled nel frontend (Option A — semplice per Electron; Option B con fetch remoto in Fase 8)
- [x] `defineAsyncComponent()` per lazy loading componenti plugin
- [x] **Plugin component registry**: `PluginManager.get_frontend_components()` → REST endpoint `GET /api/plugins/components` → frontend carica async
- [x] **Mount points** per plugin UI: `sidebar`, `modal`, `toolbar`, `settings-panel`
- [x] Componente `CalendarView.vue`: vista settimanale/mensile base, CRUD eventi
- [x] Componente `SearchResultsPanel.vue`: risultati ricerca in sidebar collassabile
- [x] Componente `WeatherWidget.vue`: widget compatto per toolbar (temperatura + icona condizione)

#### 7.5 — Dipendenze e Config Changes per Fase 7
- [x] `pyproject.toml` — nuove dipendenze:
  - `duckduckgo-search >= 6.0` (web_search)
  - `beautifulsoup4 >= 4.12` (web_search scrape)
  - `python-dateutil >= 2.9` (calendar RRULE)
  - `pytz >= 2024.1` (calendar timezone — alternativa: `zoneinfo` stdlib Python 3.9+, preferibile)
  - Nessuna nuova dep per weather (httpx già in core)
- [x] `backend/core/config.py`:
  - Aggiungere `WebConfig`, `CalendarConfig`, `WeatherConfig` come `BaseSettings` subclass
  - Aggiungere a `OmniaConfig` come campi: `web: WebConfig`, `calendar: CalendarConfig`, `weather: WeatherConfig`
- [x] `config/default.yaml`:
  - Sezioni `web_search:`, `calendar:`, `weather:` con tutti i defaults
  - `plugins.enabled` rimane `[system_info, pc_automation]` — gli altri `enabled: false` individualmente per safety

#### 7.6 — Test Suite Fase 7
- [x] Test web_search: mock `DDGS.text()` via `asyncio.to_thread`, rate limiting (token bucket), SSRF blocking su 127.0.0.1/10.x/192.168.x, caching LRU hit/miss
- [x] Test web_scrape: mock `httpx.AsyncClient.get()`, max size truncation (>50KB), timeout, URL SSRF validation
- [x] Test calendar: CRUD eventi, RRULE parsing, reminder trigger (mock `asyncio.sleep`), conversione UTC↔timezone, edge: start > end, event non trovato
- [x] Test weather: mock httpx responses open-meteo, geocoding caching, città non trovata, servizio offline → ConnectionStatus.DISCONNECTED
- [x] Test `http_security.py`: ogni categoria IP privato bloccata, schema non-HTTP bloccato, URL pubblica valida passa
- [x] Test plugin UI loading: `defineAsyncComponent()`, mount points

---

### Fase 7.5 — Plugin: Media Control + Notifiche + Clipboard

> **Ordine di implementazione consigliato**: clipboard (più semplice, zero nuove dep) → notifications (timer stateful) → media_control (COM/Windows = più complesso). Tutti e tre sono standalone senza dipendenze da altri plugin.

#### 7.5.1 — Clipboard Plugin (`backend/plugins/clipboard/`)
- [x] `ClipboardPlugin(BasePlugin)` — `plugin_name = "clipboard"`, `plugin_priority = 20`, `plugin_dependencies: list[str] = []`
- [x] Dipendenza: **`pyperclip >= 1.9`** in `pyproject.toml` (cross-platform; su Windows usa `win32clipboard` da pywin32 già presente come dep di pc_automation — ma `pyperclip` è più semplice come api)
- [x] Lazy import: `try: import pyperclip` con `check_dependencies()` se mancante
- [x] `ClipboardConfig(BaseSettings)` in `config.py`:
  - `enabled: bool = False`
  - `max_content_chars: int = 4000` (tronca prima di inviare a LLM — evita context flooding)
- [x] Tool `get_clipboard()` → `risk_level="safe"`, `timeout_ms=3000`:
  - `asyncio.to_thread(pyperclip.paste)` — API sync, sempre thread
  - Output: `{content: str, truncated: bool, length: int}`
  - **Edge case**: clipboard contiene binario (immagine/file) → `pyperclip.PyperclipException` → `ToolResult.error("Clipboard contains non-text content")`
  - **Edge case**: clipboard vuota → `{content: "", truncated: false, length: 0}`
- [x] Tool `set_clipboard(text: str)` → `risk_level="medium"`, `requires_confirmation=True`, `timeout_ms=3000`:
  - `asyncio.to_thread(pyperclip.copy, text)`
  - Validazione: `len(text) <= 1_000_000` (anti–memory bomb se LLM genera testo enorme)
  - **Edge case**: `pyperclip` non disponibile (headless server senza display) → `ToolResult.error("Clipboard not available in headless environment")`
- [x] File structure: solo `__init__.py` + `plugin.py` (plugin < 80 righe, nessun executor separato)
- [x] Test: mock pyperclip.paste/copy, testo binario → errore, testo lungo > max → truncated flag, pyperclip non disponibile

#### 7.5.2 — Notifications Plugin (`backend/plugins/notifications/`)
- [x] `NotificationsPlugin(BasePlugin)` — `plugin_name = "notifications"`, `plugin_priority = 25`, `plugin_dependencies: list[str] = []`
- [x] Dipendenza Windows: **`winotify >= 1.1`** in `pyproject.toml` per Windows 10/11 toast native
  - Fallback headless (no display): log warning + `ToolResult.ok("Notification queued (no display)")` — non crashare
  - Lazy import: `try: from winotify import Notification, audio as WinAudio`
- [x] `NotificationsConfig(BaseSettings)` in `config.py`:
  - `enabled: bool = False`
  - `app_id: str = "OMNIA"` (nome app nelle notifiche Windows)
  - `sound_enabled: bool = True`
  - `default_timeout_s: int = 5`
  - `max_active_timers: int = 20` (anti DoS per richieste timer dal LLM)
- [x] `backend/plugins/notifications/timer_manager.py`:
  - `TimerManager` (non singleton — istanziato in `NotificationsPlugin.initialize()`)
  - `_timers: dict[str, asyncio.Task]` — mapping `timer_id → Task`
  - `async def create_timer(timer_id: str, label: str, duration_s: int, callback: Callable) -> None`
  - `def cancel_timer(timer_id: str) -> bool` — `task.cancel()` + rimozione dal dict
  - `async def shutdown()` — cancella tutti i task attivi (chiamato da `cleanup()`)
  - **Persistenza timers**: DB model `ActiveTimer(SQLModel, table=True)`: `id: str (uuid)`, `label: str`, `fires_at: datetime`, `created_at: datetime`, `status: Literal["pending", "fired", "cancelled"]`
  - `on_app_startup()`: carica timers `status="pending"` con `fires_at > now()` dal DB, ri-crea i task `asyncio` corrispondenti (sopravvivono a restart del backend)
  - **Edge case**: se `fires_at` è nel passato al reload → inviare notifica immediately + aggiornare status a "fired"
- [x] Tool `send_notification(title: str, message: str, timeout_s?: int)` → `risk_level="safe"`, `timeout_ms=5000`:
  - `asyncio.to_thread(_send_win_notification, title, message, timeout_s)`
  - Fallback: se winotify non disponibile → solo log (non errore)
- [x] Tool `set_timer(label: str, duration_seconds: int)` → `risk_level="safe"`, `timeout_ms=3000`:
  - Valida `1 <= duration_seconds <= 86400` (max 24h)
  - Valida `len(active_timers) < max_active_timers`
  - Genera `timer_id = uuid4()`, crea task + salva in DB
  - Return: `{timer_id, label, fires_at_iso}`
- [x] Tool `cancel_timer(timer_id: str)` → `risk_level="safe"`, `timeout_ms=3000`
- [x] Tool `list_active_timers()` → `risk_level="safe"`, `timeout_ms=3000`:
  - Legge dal DB (source of truth), non da dict in-memory
- [x] EventBus: `timer.fired` event con `{timer_id, label}` quando scatta
- [x] **Integrazione calendar**: se `calendar` plugin è attivo e `calendar.reminder` EventBus event arriva, `notifications` può iscriversi a quell'evento per inviare toast — ma NON dichiara `plugin_dependencies=["calendar"]` (soft coupling via EventBus, non hard dep)
- [x] Test: mock winotify, timer create/fire/cancel, persistence/reload su restart, max_active_timers limit, duration fuori range, winotify non disponibile

#### 7.5.3 — Media Control Plugin (`backend/plugins/media_control/`)
- [x] `MediaControlPlugin(BasePlugin)` — `plugin_name = "media_control"`, `plugin_priority = 30`, `plugin_dependencies: list[str] = []`
- [x] **Windows-only** — `check_dependencies()` verifica OS + disponibilità COM:
  - `import sys; sys.platform == "win32"` — se non Windows → tutti i tool restituiscono `ToolResult.error("Media control is Windows-only")`
  - Lazy import: `try: from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume` (COM interface)
- [x] Dipendenze in `pyproject.toml`:
  - **`pycaw >= 20230407`** (Windows Core Audio API wrapper via `comtypes`)
  - `comtypes >= 1.4` (già installato come dep di pycaw, COM interop)
  - `pywin32 >= 306` — già presente come dep di pc_automation (Windows media key simulation)
  - Nessuna collisione: pywin32 è già in pyproject.toml
- [x] `MediaControlConfig(BaseSettings)` in `config.py`:
  - `enabled: bool = False`
  - `volume_step: int = 10` (% per increment/decrement)
  - `brightness_step: int = 10`
- [x] `backend/plugins/media_control/executor.py`:
  - Tutte le funzioni **DEVONO** usare `asyncio.to_thread()` — le API COM sono blocking e non thread-safe sull'event loop
  - `_get_volume_interface()` — inizializza `IAudioEndpointVolume` via `pycaw.pycaw.AudioUtilities.GetSpeakers()`; cache in modulo (reinizializzare se COM disconnessa)
  - `async def exec_get_volume() -> int` — range 0–100 (normalizza da 0.0–1.0 della COM API)
  - `async def exec_set_volume(level: int) -> str` — valida `0 <= level <= 100`, `SetMasterVolumeLevelScalar(level/100)`
  - `async def exec_media_play_pause()` — `win32api.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)` via pywin32
  - `async def exec_media_next() / exec_media_prev()` — idem con `VK_MEDIA_NEXT_TRACK / VK_MEDIA_PREV_TRACK`
  - `async def exec_get_current_media() -> dict` — legge Windows SMTC via `winrt` (opzionale, fallback: `GetForegroundWindow()` + titolo finestra come approssimazione)
  - `async def exec_set_brightness(level: int) -> str` — WMI query `SELECT * FROM WmiMonitorBrightnessMethods`; `asyncio.to_thread` obbligatorio
- [x] Tool `get_volume()` → `risk_level="safe"`, `timeout_ms=3000`
- [x] Tool `set_volume(level: int)` → `risk_level="medium"`, `requires_confirmation=False` (non distruttivo, invertibile), `timeout_ms=3000`
  - **Nota design**: volume NON richiede confirmation per esperienza Jarvis fluida (come abbassare volume fisicamente)
- [x] Tool `volume_up() / volume_down()` → `risk_level="safe"`, usa `volume_step` da config
- [x] Tool `mute() / unmute()` → `risk_level="safe"`
- [x] Tool `media_play_pause() / media_next() / media_previous()` → `risk_level="safe"` (controllo media non distruttivo)
- [x] Tool `get_current_media()` → `risk_level="safe"`, `timeout_ms=3000` — output: `{title?, artist?, album?, app?}`
- [x] Tool `set_brightness(level: int)` → `risk_level="medium"`, `requires_confirmation=False`, `timeout_ms=5000`
  - WMI blocking → sempre `asyncio.to_thread`
  - **Edge case**: monitor non supporta WMI brightness (monitor esterno) → `ToolResult.error("Brightness control not supported for this display")`
- [x] `get_connection_status()`: verifica se COM disponibile → `CONNECTED` / `ERROR`
- [x] **Edge case**: COM interface invalida (es. device audio rimosso) → reinizializza `_get_volume_interface()` al prossimo call invece di crashare
- [x] Test: mock pycaw COM via `unittest.mock`, mock win32api keybd_event, non-Windows → error graceful, COM device rimosso → reinit

#### 7.5.4 — Config e Dipendenze Fase 7.5
- [x] `pyproject.toml` nuove dipendenze:
  - `pyperclip >= 1.9` (clipboard)
  - `winotify >= 1.1` (notifications, Windows only)
  - `pycaw >= 20230407` (media_control, Windows only)
  - `comtypes >= 1.4` (media_control, transitiva di pycaw)
- [x] `config/default.yaml`: sezioni `clipboard:`, `notifications:`, `media_control:` con tutti i defaults
- [x] `backend/core/config.py`: `ClipboardConfig`, `NotificationsConfig`, `MediaControlConfig` + aggiunta a `OmniaConfig`

#### 7.5.5 — Test Suite Fase 7.5
- [x] Test clipboard: get/set successo, clipboard binaria → errore, testo > max → truncated, pyperclip assente → errore graceful
- [x] Test notifications (winotify): mock `Notification.show()`, timer create→fire→callback, timer cancel, list_active, max_active_timers exceeded, persistence al restart, `fires_at` nel passato al reload
- [x] Test media_control: mock pycaw `IAudioEndpointVolume`, mock win32api `keybd_event`, non-Windows → errori graceful, volume bounds (0–100), COM device rimosso → reinit
- [x] Test config: env var override (`OMNIA_MEDIA_CONTROL__ENABLED=true`), defaults

---

### Fase 7.6 — Plugin: Ricerca File + Notizie/Briefing

> **Ordine di implementazione consigliato**: file_search (zero nuove dep obbligatorie) → news (richiede feedparser + soft dep su weather/calendar). `file_search` non dipende da nessun altro plugin. `news.get_daily_briefing()` ha soft dependency su weather e calendar (via `ctx.plugin_manager`, non hard dep).

#### 7.6.1 — File Search Plugin (`backend/plugins/file_search/`)
- [x] `FileSearchPlugin(BasePlugin)` — `plugin_name = "file_search"`, `plugin_priority = 25`, `plugin_dependencies: list[str] = []`
- [x] **Zero nuove dipendenze obbligatorie** — usa stdlib: `os`, `pathlib`, `mimetypes`, `stat`
  - Dipendenze opzionali per lettura file avanzata (lazy import con `check_dependencies()`):
    - `pdfplumber >= 0.11` per lettura PDF
    - `python-docx >= 1.1` per lettura DOCX
    - Se mancanti: `read_text_file` restituisce errore specifico (`"PDF reading requires: pip install pdfplumber"`)
- [x] `FileSearchConfig(BaseSettings)` in `config.py`:
  - `enabled: bool = False`
  - `allowed_paths: list[str] = []` — default calcolato dinamicamente in `initialize()`: `[Path.home(), Path.home()/"Desktop", Path.home()/"Documents", Path.home()/"Downloads"]`
  - `forbidden_paths: list[str]` — PATH di sistema bloccati: `["C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)", "C:\\ProgramData"]` (Windows); `/etc`, `/sys`, `/proc`, `/dev` (Linux/macOS)
  - `max_results: int = 50`
  - `max_file_size_read_bytes: int = 1_048_576` (1 MB — limite lettura file)
  - `max_content_chars: int = 8000` (tronca testo prima di inviare a LLM)
  - `follow_symlinks: bool = False` (anti path-traversal via symlink)
- [x] `backend/plugins/file_search/searcher.py`:
  - `async def search_files(query, roots, extensions, max_results, forbidden) -> list[dict]`:
    - `asyncio.to_thread(_sync_walk, ...)` — `os.walk()` è blocking
    - `_sync_walk`: case-insensitive `query in filename.lower()`, filtra per estensione se specificato
    - Ogni risultato: `{path, name, size_bytes, modified_iso, extension}`
    - `_validate_path(path, allowed, forbidden)`: controlla che il path reale (risolto, no symlink if `follow_symlinks=False`) stia dentro un allowed root e non in un forbidden path
    - Timeout di sicurezza: max 5 secondi per walk (anti-freeze su directory enormi) via `asyncio.wait_for`
    - **Edge case**: `PermissionError` su singola directory → log warning + continua (non interrompe l'intera ricerca)
- [x] `backend/plugins/file_search/readers.py`:
  - `async def read_text_file(path: str, max_bytes: int) -> str`
  - Dispatcher per estensione: `.txt/.md/.py/.js/.ts/.json/.yaml/.csv` → `open(encoding="utf-8", errors="replace")`
  - `.pdf` → `pdfplumber.open(path)` + `asyncio.to_thread`
  - `.docx` → `python-docx` + `asyncio.to_thread`
  - Resto → `ToolResult.error("Unsupported file type for reading: .{ext}")`
  - Rispetta `max_bytes` — legge solo i primi N bytes
- [x] Tool `search_files(query: str, path?: str, extensions?: list[str], max_results?: int = 20)` → `risk_level="safe"`, `timeout_ms=10000`:
  - `path` opzionale: se fornito, validato contro `allowed_paths`; se omesso → cerca in tutti gli `allowed_paths`
  - `extensions` opzionale: `[".pdf", ".docx"]` — normalizzate a lowercase con punto
- [x] Tool `get_file_info(path: str)` → `risk_level="safe"`, `timeout_ms=3000`:
  - Solo metadata: `{name, size_bytes, modified_iso, created_iso, extension, mime_type}`
  - **NO** contenuto file — metadata è sempre safe
  - Valida path contro `allowed_paths`
- [x] Tool `read_text_file(path: str, max_chars?: int)` → `risk_level="medium"`, `requires_confirmation=True`, `timeout_ms=15000`:
  - Il contenuto di file personali è sensibile → confirmation obbligatoria
  - Valida path + legge tramite `readers.py`
  - Output include `{content, truncated, chars_read, path}`
- [x] Tool `open_file(path: str)` → `risk_level="medium"`, `requires_confirmation=True`, `timeout_ms=5000`:
  - `asyncio.to_thread(os.startfile, path)` — apre con app associata di Windows
  - Valida path contro `allowed_paths` + forbidden antes
  - **Edge case**: file non esiste → `ToolResult.error("File not found: ...")`
  - **Edge case**: `os.startfile` non disponibile (non-Windows) → fallback a `subprocess.Popen(["xdg-open", path])` (Linux) o `subprocess.Popen(["open", path])` (macOS)
- [x] **Edge case generale**: UNC paths (`\\server\share`) → bloccare (potenziale SSRF-equivalente su reti condivise)
- [x] Test: mock os.walk, file trovato/non trovato, PermissionError continua, UNC path bloccato, symlink con follow=False, timeout 5s walk, read PDF senza pdfplumber → errore, path fuori allowed_paths, forbidden path bloccato

#### 7.6.2 — News / Briefing Plugin (`backend/plugins/news/`)
- [x] `NewsPlugin(BasePlugin)` — `plugin_name = "news"`, `plugin_priority = 15`, `plugin_dependencies: list[str] = []`
  - **Soft dependency** (non hard) su `weather` e `calendar`: in `get_daily_briefing()`, controllare `ctx.plugin_manager.get_plugin("weather")` — se disponibile e connected → aggiungere dati meteo al briefing; se no → procedere senza
- [x] Dipendenza: **`feedparser >= 6.0`** in `pyproject.toml` (RSS/Atom parsing — puro Python, zero dep native)
- [x] `NewsConfig(BaseSettings)` in `config.py`:
  - `enabled: bool = False`
  - `feeds: list[str]` — default: feed RSS pubblici selezionati (BBC World, ANSA, Repubblica):
    ```
    - "https://feeds.bbci.co.uk/news/world/rss.xml"
    - "https://www.ansa.it/sito/notizie/tecnologia/rss.xml"
    - "https://www.repubblica.it/rss/homepage/rss2.0.xml"
    ```
  - `max_articles: int = 10` (per feed)
  - `cache_ttl_minutes: int = 15`
  - `request_timeout_s: int = 10`
  - `default_lang: str = "it"`
- [x] `backend/plugins/news/feed_reader.py`:
  - `FeedReader` — `httpx.AsyncClient` persistente (pattern shared con weather/web_search)
  - `async def fetch_feed(url: str) -> list[dict]`:
    - `validate_url_ssrf(url)` da `backend/core/http_security.py` — **stessa utility di weather e web_search**
    - `response = await client.get(url, timeout=config.request_timeout_s)`
    - `asyncio.to_thread(feedparser.parse, response.text)` (feedparser è CPU-bound, non async)
    - Ogni articolo normalizzato: `{title, summary, link, published_iso, source}`
  - Cache: `{url: (timestamp, articles)}` in memory — TTL `cache_ttl_minutes`
  - `async def fetch_all_feeds(urls, max_per_feed) -> list[dict]`: `asyncio.gather(*[fetch_feed(u) for u in urls])` — fetch paralleli
- [x] Tool `get_news(topic?: str, lang?: str, max_results?: int = 10)` → `risk_level="safe"`, `timeout_ms=20000`:
  - Fetch tutti i feed configurati in parallelo
  - Se `topic`: filtra titoli/sommari contenenenti il termine (case-insensitive)
  - Output: `{articles: [{title, summary, link, published_iso, source}], total, cached: bool}`
- [x] Tool `get_daily_briefing()` → `risk_level="safe"`, `timeout_ms=30000`:
  - Aggrega sincronicamente:
    1. **Data e ora corrente** (sempre disponibile)
    2. **Top news** (da `fetch_all_feeds`) — prime 5 notizie
    3. **Meteo** (soft dep): se `weather` plugin disponibile e `ConnectionStatus.CONNECTED` → chiama `ctx.tool_registry.execute_tool("weather_get_weather", {}, context)` — non import diretto (evita accoppiamento)
    4. **Agenda del giorno** (soft dep): se `calendar` plugin disponibile → chiama `ctx.tool_registry.execute_tool("calendar_get_today_summary", {}, context)`
  - Output strutturato: `{date_iso, weather?: {...}, today_events?: [...], top_news: [...]}`
  - **Edge case**: se uno dei servizi soft-dep fallisce → includi solo i dati disponibili, non fail tutto il briefing
- [x] `initialize()`: crea `FeedReader`, registra in `plugin_local_state["news"]["reader"]`
- [x] `cleanup()`: chiude `httpx.AsyncClient`
- [x] Test: mock httpx.AsyncClient + feedparser, parallel fetch, caching hit/miss, SSRF blocking su feed URL custom, topic filter, daily briefing con weather/calendar assenti (graceful), weather online → incluso nel briefing

#### 7.6.3 — Config e Dipendenze Fase 7.6
- [x] `pyproject.toml` nuove dipendenze:
  - `feedparser >= 6.0` (news)
  - `pdfplumber >= 0.11` (file_search, optional — lazy import)
  - `python-docx >= 1.1` (file_search, optional — lazy import)
  - Nessuna nuova dep per file_search base (stdlib)
- [x] `backend/core/config.py`: `FileSearchConfig`, `NewsConfig` + aggiunta a `OmniaConfig`
- [x] `config/default.yaml`: sezioni `file_search:`, `news:` con defaults

#### 7.6.4 — Test Suite Fase 7.6
- [x] Test file_search: mock os.walk, path validation (allowed/forbidden/UNC/symlink), PermissionError continuazione, timeout walk, read_text_file con mock pdfplumber/docx, open_file cross-platform (Windows startfile, Linux xdg-open)
- [x] Test news: mock httpx + feedparser, parallel fetch, cache TTL, SSRF su URL feed custom, filtro topic, daily briefing con/senza weather/calendar, soft dep non disponibile → partial result
- [x] Test `backend/core/http_security.py` (riusato da weather + web_search + news): copertura completa IP privati RFC 1918 + loopback + link-local + IPv6 private

---

### Riepilogo Dipendenze tra Fasi 7, 7.5, 7.6

```
backend/core/http_security.py   ← creato in Fase 7.3 (weather)
     ↑ usato da: web_search (7.1), weather (7.3), news (7.6.2)

calendar (7.2) ── soft dep ──→ notifications (7.5.2) [EventBus: calendar.reminder]
weather  (7.3) ── soft dep ──→ news briefing (7.6.2) [ctx.tool_registry call]
calendar (7.2) ── soft dep ──→ news briefing (7.6.2) [ctx.tool_registry call]

Ordine implementazione consigliato:
  1. http_security.py (utility condivisa, richiesta da weather + news)
  2. web_search (7.1) + calendar (7.2) [parallelo, no inter-dep]
  3. weather (7.3) [dopo http_security.py]
  4. clipboard (7.5.1) [standalone, più semplice]
  5. notifications (7.5.2) [standalone + EventBus subscription opzionale]
  6. media_control (7.5.3) [standalone, più complesso per COM Windows]
  7. file_search (7.6.1) [standalone]
  8. news (7.6.2) [dopo weather + calendar per briefing completo]
```

---

### Fase 8 — Polish e Server-readiness

#### 8.1 — System Prompt & Settings
- [ ] System prompt personalizzabile da UI Settings
- [ ] Editor system prompt con preview (markdown)
- [ ] Settings UI completa: modello LLM, temperatura, max tokens, lingua, tema, plugin on/off
- [ ] **Settings persistence**: salvare su file `config/user.yaml` (overlay su `default.yaml`)
- [ ] REST: `GET/PUT /api/config` per leggere/scrivere settings
- [ ] **Plugin settings**: auto-generate form dalla `get_config_schema()` di ogni plugin
- [ ] Global hotkey: `Ctrl+Shift+O` → attivazione finestra OMNIA (Electron `globalShortcut`)

#### 8.2 — Auth JWT per Deployment Remoto
- [ ] `AuthConfig`: `enabled: bool = False` (local: off), `jwt_secret: SecretStr`, `jwt_algorithm: str = "HS256"`, `token_expiry: int = 3600`
- [ ] Middleware FastAPI: validazione JWT su tutte le route REST quando `auth.enabled = True`
- [ ] **WebSocket auth**: dopo `accept()`, primo messaggio dev'essere `{"type": "auth", "token": "..."}` — timeout 5s, altrimenti `close(403)`
- [ ] Login endpoint: `POST /api/auth/login` → JWT token
- [ ] **Secret management per produzione**: JWT secret da env var `OMNIA_JWT_SECRET`, MAI in config file

#### 8.3 — Multi-User Isolation
- [ ] `Conversation.user_id: str | None` — nullable per backward compat (local = tutti None)
- [ ] Filtro `WHERE user_id = ?` su tutte le query quando auth attivo
- [ ] File conversazioni: `data/conversations/{user_id}/{conv_id}.json` (migrazione path da flat)
- [ ] Plugin context: `ExecutionContext.user_id` propagato a ogni tool call
- [ ] **Isolamento plugin state**: `plugin_local_state` scoped per user quando multi-user attivo
- [ ] **PC Automation + multi-user**: disabilitare se multi-user attivo (chi controlla il PC di chi?)
- [ ] **Voice + multi-user**: una sola sessione voice alla volta (chi parla?)

#### 8.4 — Database Migrations
- [ ] **Alembic** per schema migrations (non `create_all` manual)
- [ ] Script migration: v1 (pre-Fase3) → v2 (tool_calls) → v3 (user_id) → v4 (plugin tables)
- [ ] Auto-migration a startup se version mismatch detected
- [ ] Backup automatico DB prima di migration

#### 8.5 — Packaging
- [ ] **Backend**: PyInstaller con static `PLUGIN_REGISTRY` (no importlib dinamico in prod)
  - `--hidden-import` per ogni plugin
  - Data files: `config/`, `data/`, modelli Piper
  - Test: built executable funziona identico a dev
- [ ] **Frontend**: electron-builder per Windows (`nsis`), macOS (`dmg`), Linux (`appimage`)
  - Auto-update: `electron-updater` con GitHub Releases
  - **Backend spawn**: Electron spawna processo Python bundled come child process
  - Shared data directory: `%APPDATA%\OMNIA` (Win), `~/Library/Application Support/OMNIA` (macOS), `~/.config/omnia` (Linux)
- [ ] **Crash handling**: unhandled exception → salva log + notifica utente; restart automatico backend
- [ ] **Versioning coordinato**: backend version + frontend version in sync (semver, tag Git)

#### 8.6 — Observability & Logging
- [ ] Log strutturati (JSON) in produzione (loguru con JSON sink)
- [ ] **Trace ID** per ogni request/WS session: propagato attraverso tool calls, plugin, DB
- [ ] Performance metrics via EventBus: tool execution time, LLM latency, WebSocket round-trip
- [ ] Health endpoint arricchito: `GET /api/health` → `{status, plugins: {name: status}, vram_usage, db_ok, uptime}`

#### 8.7 — Test Suite Fase 8
- [ ] Test JWT: login, token validation, expiry, WS auth flow
- [ ] Test multi-user: isolation conversazioni, plugin state scoping, migration path file
- [ ] Test packaging: PyInstaller build → smoke test; electron-builder → smoke test
- [ ] Test migrations: Alembic upgrade/downgrade, backup/restore
- [ ] E2E: Electron app avviato, connessione backend, chat funzionante, plugin attivi

---

## Requisiti Cross-Cutting (Tutte le Fasi)

### Gestione VRAM
| Configurazione | Componenti | VRAM Stimata |
|---|---|---|
| Solo chat | Qwen 3.5 9B | ~6 GB |
| Chat + voice | Qwen + faster-whisper | ~7.5 GB |
| Chat + voice + XTTS | Qwen + whisper + XTTS v2 | ~9.5 GB |
| Chat + vision (screenshot) | Qwen + immagine in contesto | ~6.2 GB |
| Thinking model | QwQ / DeepSeek R1 (swap Qwen) | ~6-10 GB |
| **Massimo simultaneo** | Qwen + whisper + Piper(CPU) | **~7.5 / 16 GB** |

**Regola**: non superare 14 GB allocati (2 GB headroom per OS + driver). `VRAMMonitor` emette alert.

### Error Handling Standard
```
ToolError → { tool_name, error_type (timeout|permission|network|logic|internal), message, suggestions[] }
```
- Errori plugin: loggati con trace ID, non esposti raw all'utente
- Errori LLM: retry automatico 1 volta, poi errore user-friendly
- Errori DB: log + alert, fallback read-only se possibile
- Errori WS: riconnessione automatica con exponential backoff (max 30s, non 8+ minuti)

### WebSocket Protocol Completo (Evoluzione per Fase)
| Type | Fase | Direzione | Payload |
|---|---|---|---|
| `token` | 1 | S→C | `{content}` |
| `thinking` | 1.5 | S→C | `{content}` |
| `done` | 1 | S→C | `{message}` |
| `error` | 1 | S→C | `{content}` |
| `tool_call` | 3 | S→C | `{id, function: {name, arguments}}` |
| `tool_execution_start` | 3 | S→C | `{tool_name, execution_id}` |
| `tool_execution_done` | 3 | S→C | `{tool_name, result, execution_id}` |
| `tool_confirmation_required` | 3 | S→C | `{tool_name, args, risk_level, reasoning, execution_id}` |
| `tool_confirmation_response` | 3 | C→S | `{execution_id, approved}` |
| `voice_start` / `voice_stop` | 4 | C→S | `{}` |
| `transcript` | 4 | S→C | `{text}` |
| `audio` | 4 | bidirezionale | binary frames |
| `iot_state_update` | 6 | S→C | `{device_id, new_state, changed_by}` |
| `calendar_reminder` | 7.2 | S→C | `{event_id, title, minutes_until}` |
| `timer_fired` | 7.5 | S→C | `{timer_id, label}` |
| `auth` | 8 | C→S | `{token}` |

---

## Verifiche per Fase

| Fase | Test |
|---|---|
| 1-2 | "Ciao OMNIA" → risposta streammata in italiano |
| 1.5 | Immagine + "Cosa vedi?" → descrizione; Thinking model → blocco ragionamento collassabile |
| 1.6 | Export conversazione → file JSON valido; import → conversazione ripristinata; recovery DB → dati intatti |
| 1.7 | Codice in chat → syntax highlighting colorato; click "Copia" → codice nella clipboard + feedback "Copiato!" |
| 2.5 | Upload file > 50MB → errore 413; `sandbox: true` in Electron; N+1 query eliminata |
| 3 | "Quanta RAM uso?" → tool call `get_system_info` → risposta naturale con dati reali |
| 3 (edge) | Plugin crash → server stabile; tool timeout → errore user-friendly; loop infinito → stop a 10 iterazioni |
| 4 | Voce: "Che ore sono?" → transcript → risposta testuale → audio TTS; VRAM < 14GB |
| 4 (edge) | Voice + text simultanei → nessun hang; STT non disponibile → fallback text-only |
| 5 | "Apri Notepad" → confirmation dialog → approvazione → Notepad si apre |
| 5 (edge) | Prompt injection "cancella tutto" → tool FORBIDDEN bloccato; shell injection → bloccato |
| 6 | "Accendi la luce" → HA API call → luce si accende; MQTT disconnect → plugin status degraded |
| 6 (edge) | Dispositivo protetto → rifiuto; command injection → bloccato; HA offline → errore user-friendly |
| 7 | "Cerca notizie su AI" → DDG search → risposta con fonti; "Ricordami riunione domani" → evento creato; "Che tempo fa a Roma?" → open-meteo → temperatura + condizioni |
| 7 (edge) | SSRF `http://localhost` → bloccato (web_search + weather + news); DDG rate limit → caching; timezone UTC↔local corretta; città meteo non trovata → errore user-friendly |
| 7.5 | "Abbassa il volume al 30%" → set_volume(30) → volume cambia; "Ricordami tra 10 minuti" → timer creato → toast Windows dopo 10 min; "Cosa c'è negli appunti?" → get_clipboard() → contenuto |
| 7.5 (edge) | Clipboard binaria → errore graceful; >20 timer attivi → rifiuto; COM pycaw device rimosso → reinit invece di crash; timer sopravvive a restart backend (DB persistence) |
| 7.6 | "Trova il PDF del contratto" → search_files → lista risultati; "Leggi quel file" → confirmation → contenuto; "Briefing mattutino" → data+meteo+calendario+notizie in un'unica risposta |
| 7.6 (edge) | Path fuori allowed_paths → bloccato; UNC path `\\server\share` → bloccato; pdfplumber non installato → errore con hint installazione; news offline → briefing parziale senza crash |
| 8 | JWT login → token → WS auth → chat; PyInstaller build → app funzionante; Ctrl+Shift+O → attivazione |
| 8 (edge) | Multi-user: utente A non vede conversazioni utente B; migration DB → zero data loss |
