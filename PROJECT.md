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
| `memory_updated` | 9 | S→C | `{memory_id, operation}` |

---

### Fase 9 — Memory Service (Agente con Memoria Persistente)

- [x] EmbeddingClient (OpenAI + fastembed fallback) — §9.2
- [x] MemoryConfig in config.py + default.yaml — §9.3
- [x] MemoryServiceProtocol in protocols.py — §9.1
- [x] AppContext.memory_service field — §9.1
- [x] MemoryService (sqlite-vec CRUD + vector search) — §9.1
- [x] App lifespan (startup init + shutdown close) — §9.1
- [x] MemoryPlugin (5 tools: remember/recall/forget/list/clear) — §9.4
- [x] LLM context injection (build_messages + chat.py) — §9.5
- [x] Tool loop memory_context passthrough — §9.5
- [x] REST API /api/memory (5 endpoints) — §9.7
- [x] System prompt memory guidelines — §9.9
- [x] Frontend types + Pinia store + MemoryManager.vue — §9.8
- [x] Test suite (4 files, 46+ test cases) — §9.11
- [x] Dependencies (sqlite-vec, fastembed optional) — §9.10

> **Obiettivo**: trasformare OMNIA da assistente reattivo a agente con memoria semantica persistente.
> Ogni informazione rilevante può essere salvata esplicitamente (tool call) o recuperata
> automaticamente al momento opportuno, senza che l'utente debba ripetersi tra sessioni.

---

#### 9.0 — Analisi Vincoli e Scelte Architetturali

**Perché NON usare ChromaDB o altri vector store esterni:**
- ChromaDB richiede un processo server separato o embedding model dedicato (VRAM extra)
- Su RTX 5080 con Qwen 3.5 9B + Whisper già in esecuzione, ogni GB di VRAM conta
- Dipendenza esterna → possibile rottura a upgrade, setup complesso per packaging PyInstaller
- **Soluzione scelta**: `sqlite-vec` — estensione SQLite (già in uso come DB principale) per ricerca vettoriale.
  - Zero processi extra, zero VRAM dedicata, compatibile con PyInstaller, file unico in `data/`
  - Embedding generati localmente da un modello leggero CPU-only (vedi §9.2)

**Perché NON usare sentence-transformers direttamente:**
- `sentence-transformers` importa PyTorch (~2 GB disco) — inutile se Ollama/LM Studio già gestisce embedding
- **Soluzione scelta**: embedding via LM Studio/Ollama OpenAI-compatible `/v1/embeddings` endpoint
  - Stesso backend già useato per chat → zero overhead aggiuntivo
  - Modello embedding: `nomic-embed-text` (~274 MB VRAM, piccolo) o qualsiasi modello già caricato
  - Fallback CPU: se LM Studio offline → `fastembed` (pure Python, ~50 MB, CPU-only, nessun PyTorch)

**Perché il Memory Service è un `BaseService`, NON un plugin:**
- La memoria è infrastruttura del core (come `LLMService`, `STTService`), non una feature opzionale
- Va iniettata in `AppContext` e usata dal tool loop e dal prompt builder
- I tool `remember`/`recall`/`forget` vengono esposti tramite un **plugin dedicato** (`memory` plugin)
  che si appoggia al service — separazione responsabilità pulita

**Strategia contesto LLM (nessuna regressione):**
- La memoria viene iniettata come blocco `[MEMORIA RILEVANTE]` nel system prompt rebuild,
  **PRIMA** della chiamata LLM ma **DOPO** la costruzione del contesto esistente
- Zero modifica a `LLMService.build_messages()` — la memoria è solo un parametro opzionale
  aggiuntivo passato dalla route WebSocket
- Il prompt inject è parametrico e disattivabile per test

---

#### 9.1 — MemoryService (`backend/services/memory_service.py`)

**Ruolo**: layer di accesso ai ricordi. Non conosce tool, LLM o plugin — solo CRUD vettoriale.

```
MemoryService
├── initialize(ctx)         — apre DB, crea tabella, carica embedding client
├── add(content, metadata)  — embed + insert in sqlite-vec
├── search(query, k, filter) — embed query + cosine similarity search
├── delete(memory_id)       — rimozione per ID
├── list(filter, limit)     — listing con filtri (scope, category, created_after)
└── close()                 — chiude connessione DB e embedding client
```

- `MemoryService` implementa il Protocol `MemoryServiceProtocol` (aggiunto a `protocols.py`)
- Registrato in `AppContext` come `memory_service: MemoryServiceProtocol | None = None`
- Creato in `core/app.py` lifespan, **dopo** DB init e **prima** dei plugin (i plugin possono usarlo)
- `initialize()` è idempotente (safe da chiamare su restart hot-reload)

**Startup** (aggiunta in `app.py` lifespan, dopo `await init_db(engine)` e prima di `PluginManager`):
```python
if config.memory.enabled:
    from backend.services.memory_service import MemoryService
    memory_service = MemoryService(config.memory)
    try:
        await memory_service.initialize()
        ctx.memory_service = memory_service
        logger.info("Memory service started")
    except Exception as exc:
        logger.warning("Memory service failed to start: {}", exc)
```

**Shutdown** (aggiunta in `app.py` lifespan, nella sezione `# -- Shutdown --`, accanto agli altri servizi):
```python
if ctx.memory_service:
    try:
        await ctx.memory_service.close()
    except Exception as exc:
        logger.error("Memory service shutdown error: {}", exc)
```

**DB Model** (`backend/db/models.py`, tabella nativa SQLite, non SQLModel — sqlite-vec usa sintassi custom):

```sql
-- Tabella metadati (SQLModel normale)
CREATE TABLE memory_entries (
    id          TEXT    PRIMARY KEY,   -- uuid4 stringa
    content     TEXT    NOT NULL,      -- testo originale (per display)
    scope       TEXT    NOT NULL DEFAULT 'long_term',  -- 'long_term' | 'session'
    category    TEXT,                  -- tag libero ('preference','fact','skill',...)
    source      TEXT    NOT NULL DEFAULT 'llm',        -- 'llm' | 'user' | 'system'
    created_at  TEXT    NOT NULL,      -- ISO 8601 UTC
    expires_at  TEXT,                  -- ISO 8601 UTC, NULL = permanente
    conversation_id TEXT,             -- UUID conversazione origine (nullable)
    embedding_model TEXT NOT NULL     -- nome modello usato per l'embedding
);

-- Tabella vettori (sqlite-vec sintassi virtuale)
CREATE VIRTUAL TABLE memory_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[768]              -- dimensione vettore del modello scelto
);
```

`MemoryEntry` SQLModel model — usa `uuid.UUID` come PK con `_new_uuid` factory, **coerentemente con `Conversation`, `Message`, `Attachment` e `ToolConfirmationAudit`**:

```python
class MemoryEntry(SQLModel, table=True):
    __tablename__ = "memory_entries"
    id: uuid.UUID = Field(default_factory=_new_uuid, primary_key=True)  # ← uuid.UUID, come tutti gli altri modelli
    content: str
    scope: str = Field(default="long_term")
    category: str | None = None
    source: str = Field(default="llm")
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None
    conversation_id: uuid.UUID | None = None  # ← UUID, non str
    embedding_model: str
```

**Nota JOIN sqlite-vec**: il service layer converte `str(entry.id)` quando inserisce e legge dalla tabella virtuale `memory_vectors`, il cui schema usa `TEXT PRIMARY KEY`. La DDL SQL sopra riflette il tipo fisico SQLite (UUID serializzato come text); il SQLModel Python usa `uuid.UUID` per uniformità con gli altri modelli.

**Nota `memory_vectors` (tabella virtuale)**: creata da `MemoryService.initialize()` via `conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS ...")` dopo aver caricato l'estensione `sqlite-vec`. Non è un SQLModel model perché le tabelle virtuali non sono compatibili con SQLAlchemy reflection.

---

#### 9.2 — EmbeddingClient (`backend/services/embedding_client.py`)

**Ruolo**: genera embedding vettoriali. Astratto con due implementazioni concrete.

```python
class EmbeddingClientProtocol(Protocol):
    async def encode(self, text: str) -> list[float]: ...
    async def encode_batch(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimensions(self) -> int: ...
    async def close(self) -> None: ...
```

**Implementazioni**:

1. **`OpenAIEmbeddingClient`** (primario):
   - Chiama `POST /v1/embeddings` sullo stesso backend LM Studio/Ollama già configurato
   - Modello configurabile: `memory.embedding_model = "nomic-embed-text"` (default)
   - Usa `httpx.AsyncClient` persistente (pool condiviso — non crea nuove connessioni per ogni embed)
   - Timeout: 10s (embedding è veloce — non attendere oltre)
   - **Nessuna dipendenza aggiuntiva** — stessa URL di `LLMConfig.base_url`

2. **`FastEmbedClient`** (fallback CPU-only):
   - `fastembed.TextEmbedding` — pure Python, CPU, nessun PyTorch
   - Lazy import: `try: from fastembed import TextEmbedding`
   - Usato automaticamente se `OpenAIEmbeddingClient.encode()` fallisce con `ConnectError`
   - Modello default: `"BAAI/bge-small-en-v1.5"` (33 MB, 384 dim)
   - Caching in-process del modello (non ricaricare ad ogni chiamata)

**Selezione automatica**:

```python
class EmbeddingClient:
    """Facade con fallback automatico OpenAI → fastembed."""
    async def encode(self, text: str) -> list[float]:
        try:
            return await self._openai.encode(text)
        except (ConnectError, TimeoutError):
            logger.warning("Embedding API unreachable, falling back to fastembed")
            return await self._fastembed.encode(text)
```

**Coerenza dimensioni**: quando il modello embedding cambia (es. switch da 768 a 384 dim), il `MemoryService` rileva la mismatch alla creazione della tabella vettoriale e lancia `MemoryDimensionMismatchError` con istruzione chiara: `"Run: omnia memory migrate --reembed"` (script futuro).

---

#### 9.3 — MemoryConfig (`backend/core/config.py`)

```python
class MemoryConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OMNIA_MEMORY__")

    enabled: bool = False
    """Abilita il Memory Service. False di default (opt-in esplicito)."""

    db_path: str = "data/memory.db"
    """Path del file SQLite dedicato alla memoria (separato da omnia.db)."""

    embedding_model: str = "nomic-embed-text"
    """Nome modello embedding per LM Studio/Ollama /v1/embeddings."""

    embedding_dim: int = 768
    """Dimensione vettori embedding del modello scelto."""

    embedding_fallback: bool = True
    """Se True, usa fastembed CPU se LLM embedding API non disponibile."""

    top_k: int = 5
    """Numero massimo di ricordi recuperati per injection nel contesto."""

    similarity_threshold: float = 0.75
    """Score minimo coseno per includere un ricordo (0.0–1.0)."""

    inject_in_context: bool = True
    """Se True, ricordi rilevanti vengono iniettati nel system prompt."""

    context_max_chars: int = 2000
    """Massimo caratteri iniettati dal memory context nel prompt."""

    session_ttl_hours: int = 24
    """TTL per ricordi di scope 'session'. Dopo scadenza vengono ignorati."""

    auto_cleanup_days: int = 90
    """Rimuovi automaticamente ricordi non acceduti da N giorni (0 = disabilitato)."""
```

Aggiunta a `OmniaConfig`:
```python
memory: MemoryConfig = Field(default_factory=MemoryConfig)
```

Config YAML entry (`config/default.yaml`) — due sezioni da aggiungere:

```yaml
# In plugins.enabled, aggiungere (commentato per default-off, come home_automation):
plugins:
  enabled:
    # ...lista esistente...
    # - memory  # abilitare con memory.enabled: true

# Nuova sezione memory:
memory:
  enabled: false
  embedding_model: "nomic-embed-text"
  embedding_dim: 768
  top_k: 5
  similarity_threshold: 0.75
  inject_in_context: true
  context_max_chars: 2000
  session_ttl_hours: 24
  auto_cleanup_days: 90
```

---

#### 9.4 — Memory Plugin (`backend/plugins/memory/`)

**Ruolo**: espone i tool LLM per interagire con la memoria. Non contiene logica vettoriale — delega tutto a `MemoryService` tramite `AppContext`.

```
backend/plugins/memory/
├── __init__.py          — import + PLUGIN_REGISTRY["memory"] = MemoryPlugin
└── plugin.py            — MemoryPlugin(BasePlugin)
```

Pattern `__init__.py` identico a tutti gli altri plugin (es. `web_search/__init__.py`):

```python
"""O.M.N.I.A. — Memory plugin package.

Importing this module registers MemoryPlugin in the static PLUGIN_REGISTRY.
"""
from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.memory.plugin import MemoryPlugin  # noqa: F401

PLUGIN_REGISTRY["memory"] = MemoryPlugin
```

**Pattern**: identico agli altri plugin esistenti — `BasePlugin` con `get_tools()` e `execute_tool()`.

```python
class MemoryPlugin(BasePlugin):
    plugin_name = "memory"
    plugin_version = "1.0.0"
    plugin_description = (
        "Persist and retrieve long-term memories. "
        "Use remember() to save facts and recall() to search them."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 90  # Si inizializza prima degli altri (Kahn's algo, reverse=True — ordine caricamento, non disponibilità)

    async def initialize(self, ctx: AppContext) -> None:
        await super().initialize(ctx)
        if ctx.memory_service is None:
            logger.warning("MemoryPlugin: memory_service not available in context")
```

**Tool definitions**:

| Tool | risk_level | requires_confirmation | Descrizione |
|---|---|---|---|
| `remember` | `safe` | `False` | Salva un fatto/preferenza nella memoria a lungo termine |
| `recall` | `safe` | `False` | Cerca ricordi rilevanti tramite similarità semantica |
| `forget` | `medium` | `True` | Cancella un ricordo specifico per ID |
| `list_memories` | `safe` | `False` | Elenca ricordi con filtri opzionali |
| `clear_session_memory` | `medium` | `True` | Cancella tutti i ricordi di scope `session` |

**Schema tool `remember`**:
```json
{
  "type": "object",
  "properties": {
    "content": {"type": "string", "description": "Il fatto o preferenza da memorizzare. Sii conciso e preciso.", "maxLength": 1000},
    "category": {"type": "string", "description": "Categoria opzionale ('preference', 'fact', 'skill', 'context')", "enum": ["preference", "fact", "skill", "context"]},
    "scope": {"type": "string", "description": "Durata: 'long_term' (permanente) o 'session' (solo questa sessione)", "enum": ["long_term", "session"], "default": "long_term"},
    "expires_hours": {"type": "integer", "description": "Ore di validità (opzionale, null = permanente)", "minimum": 1, "maximum": 8760}
  },
  "required": ["content"]
}
```

**Schema tool `recall`**:
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "Cosa cercare nella memoria", "maxLength": 500},
    "category": {"type": "string", "description": "Filtra per categoria (opzionale)"},
    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20}
  },
  "required": ["query"]
}
```

**Regola `requires_confirmation=False` per `remember`/`recall`**: entrambi sono operazioni non distruttive e frequenti — richiedere conferma ogni volta renderebbe l'esperienza utente insopportabile. `forget` richiede conferma perché è irreversibile.

---

#### 9.5 — Context Injection (modifica `backend/api/routes/chat.py`)

**Dove**: nella route WebSocket in `backend/api/routes/chat.py`, PRIMA della chiamata `llm.build_messages()` (attualmente a riga ~363), DOPO il pre-load degli attachment. Il file corretto è `chat.py` — non esiste `ws_chat.py`.

**Pattern**: aggiunta di un parametro opzionale `memory_context: str | None` a `LLMService.build_messages()` **e al corrispondente** `LLMServiceProtocol.build_messages()` in `protocols.py` — zero breaking change (default `None`).

```python
# In chat.py, prima di llm.build_messages(...)
memory_context: str | None = None
if ctx.memory_service and ctx.config.memory.inject_in_context:
    relevant = await ctx.memory_service.search(
        query=user_content,
        k=ctx.config.memory.top_k,
        filter={"scope": "long_term"},  # solo memoria permanente nel contesto
    )
    if relevant:
        memory_context = _format_memory_context(relevant, ctx.config.memory.context_max_chars)

messages = llm.build_messages(
    user_content,
    history=history[:-1],  # invariato rispetto al codice attuale
    attachments=attachment_info or None,
    memory_context=memory_context,  # nuovo parametro opzionale
)
```

**`_format_memory_context()`** (funzione modulo-level in `chat.py`):

```python
def _format_memory_context(memories: list[MemoryEntry], max_chars: int) -> str:
    """Serializza i ricordi rilevanti in un blocco testo per il system prompt."""
    lines = ["[RICORDI RILEVANTI]"]
    total = 0
    for m in memories:
        line = f"- [{m.category or 'generale'}] {m.content}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)
```

**Modifica `LLMService.build_messages()` e `LLMServiceProtocol.build_messages()`**:

L'attuale signature in `llm_service.py` usa la variabile locale `sys_prompt = self._get_dynamic_system_prompt()`. La modifica corretta è:

```python
def build_messages(
    self,
    user_content: str,
    history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, str]] | None = None,
    memory_context: str | None = None,   # ← nuovo, default None
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    sys_prompt = self._get_dynamic_system_prompt()  # ← variabile locale, non self._system_prompt
    if memory_context and sys_prompt:
        # Appendi DOPO il prompt dinamico (con data/ora), come sezione separata
        sys_prompt = f"{sys_prompt}\n\n{memory_context}"
    elif memory_context:
        sys_prompt = memory_context
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    ...
```

**Aggiornare anche `LLMServiceProtocol`** in `backend/core/protocols.py` con lo stesso parametro `memory_context: str | None = None` per mantenere il contratto di tipo coerente con `AppContext`.

**Garanzia no-regression**: `memory_context=None` (default) → comportamento identico a prima. Tutti i test esistenti passano invariati.

---

#### 9.6 — Session Memory e Cleanup

**Session memory**: ricordi con `scope="session"` vengono creati automaticamente dal plugin con `expires_at = now() + timedelta(hours=session_ttl_hours)`. Alla ricerca, `MemoryService.search()` filtra via `WHERE expires_at IS NULL OR expires_at > NOW()`.

**Cleanup automatico**: `MemoryService` schedula un task background asincrono `_cleanup_loop()` che gira ogni 6 ore:

```python
async def _cleanup_loop(self) -> None:
    while True:
        await asyncio.sleep(6 * 3600)
        expired = await self._delete_expired()
        if expired > 0:
            logger.info("Memory cleanup: removed {} expired entries", expired)
        if self._config.auto_cleanup_days > 0:
            old = await self._delete_old_unaccessed(self._config.auto_cleanup_days)
            if old > 0:
                logger.info("Memory cleanup: removed {} stale entries", old)
```

Il task viene creato in `MemoryService.initialize()` via `asyncio.create_task()` e cancellato in `MemoryService.close()` — identico al pattern `TimerManager` in Fase 7.5.2.

---

#### 9.7 — REST API (`backend/api/routes/memory.py`)

Endpoint per la UI di gestione memoria (Fase 9 frontend):

```
GET  /api/memory                        — lista ricordi (paginazione + filtri)
POST /api/memory/search                 — ricerca semantica manuale (per UI)
DELETE /api/memory/{memory_id}          — cancella ricordo singolo
DELETE /api/memory/session              — cancella tutta la session memory
GET  /api/memory/stats                  — conteggio per scope/categoria, dimensione DB
```

Pattern identico agli endpoint esistenti (`/api/audit/confirmations`, `/api/chat/conversations`).

---

#### 9.8 — Frontend: Memory Manager UI

**Componente**: `MemoryManager.vue` — accessibile da Settings panel.

- Lista ricordi (paginata, filtrabile per categoria/scope)
- Pulsante "Dimentica" per cancellazione singola (con confirm dialog)
- Pulsante "Cancella sessione" per pulizia session memory
- Stats: N ricordi totali, dimensione DB, ultimo cleanup
- **Badge in ChatView**: piccola indicazione visiva quando ricordi rilevanti sono stati iniettati (opzionale, configurabile)

**Stato Pinia** (`memory` store):
```typescript
interface MemoryState {
  entries: MemoryEntry[]
  total: number
  stats: MemoryStats | null
  loading: boolean
}
```

**Nessuna modifica a store Pinia esistenti** — `memory` è uno store nuovo, standalone.

---

#### 9.9 — System Prompt Update (`config/system_prompt.md`)

Aggiungere regola di utilizzo memoria nella sezione `tools`:

```yaml
memory:
  remember: usa quando l'utente esprime preferenze, fornisce fatti su sé stesso, o chiede esplicitamente di ricordare qualcosa. NON salvare dati transitori (comandi singoli, risultati di ricerca).
  recall: usa SOLO se il contesto iniettato automaticamente non è sufficiente e hai bisogno di cercare qualcosa di specifico. Non chiamare recall per ogni messaggio.
  forget: usa SOLO su richiesta esplicita dell'utente.
  scope: usa 'session' per informazioni valide solo nella conversazione corrente; 'long_term' per tutto il resto.
```

---

#### 9.10 — Dipendenze e Compatibilità

**Nuove dipendenze** in `pyproject.toml`:

```toml
"sqlite-vec >= 0.1.6",       # SQLite vector extension (wheel per Windows incluso)
"fastembed >= 0.3",          # Fallback CPU embedding, no PyTorch
```

**Compatibilità PyInstaller** (Fase 8): `sqlite-vec` distribuisce wheel precompilati per Windows (`.dll`). L'estensione viene caricata con `sqlite3.load_extension(path)`. Il path dell'estensione deve essere risolto correttamente sia in dev (`importlib.resources`) che in PyInstaller bundle (`sys._MEIPASS`). Questo è documentato nel `MemoryService` code come `_resolve_vec_extension_path()`.

**Requisito Windows — `enable_load_extension`**: il modulo `sqlite3` standard di Python su Windows richiede una chiamata esplicita prima del load:
```python
conn.enable_load_extension(True)
conn.load_extension(str(_resolve_vec_extension_path()))
conn.enable_load_extension(False)  # re-disable per sicurezza
```
Se Python è compilato senza `SQLITE_ENABLE_LOAD_EXTENSION` (es. distributori che lo rimuovono per sicurezza), `MemoryService.initialize()` cattura `AttributeError` e fallisce con un errore diagnostico chiaro: `"sqlite-vec non caricabile: ricompilare Python con SQLITE_ENABLE_LOAD_EXTENSION=1 o usare il wheel uv/conda"`. Il wheel Python distribuito con `uv` (usato nel progetto) include il flag — nessun problema in pratica.

**DB separato**: `MemoryService` apre la propria connessione `aiosqlite` su `data/memory.db` (vedi `MemoryConfig.db_path`), separata da `data/omnia.db` (DB principale). Questo evita contaminazione delle migration SQLAlchemy con le tabelle virtuali sqlite-vec e permette di cancellare/ricreare la memoria senza toccare il DB principale.

**VRAM impact**:

| Configurazione | VRAM aggiuntiva |
|---|---|
| OpenAI embedding via LM Studio | 0 MB (modello già caricato o ~274 MB per nomic-embed-text) |
| fastembed fallback CPU | 0 MB VRAM (CPU-only) |
| sqlite-vec operazioni | 0 MB VRAM (SQLite CPU) |

**Budget VRAM aggiornato** (aggiornare tabella §VRAM):

| Componente | VRAM |
|---|---|
| ... (invariato) | ... |
| MemoryService (embedding via LM Studio) | ~0–274 MB (condiviso con LLM server) |

---

#### 9.11 — Test Suite Fase 9

- **Test `MemoryService`** (`tests/test_memory_service.py`):
  - `test_add_and_search`: add entry → search con query semantica → risultato trovato
  - `test_similarity_threshold`: entry poco rilevante → non restituita sotto threshold
  - `test_session_expiry`: entry session con `expires_at` passato → non restituita
  - `test_cleanup_expired`: mock clock → cleanup rimuove expired entries
  - `test_dimension_mismatch`: cambio `embedding_dim` → `MemoryDimensionMismatchError` chiaro
  - `test_disabled_service`: `memory.enabled=False` → service non inizializzato → nessun crash nel tool loop

- **Test `EmbeddingClient`** (`tests/test_embedding_client.py`):
  - `test_openai_success`: mock httpx → embedding restituito correttamente
  - `test_openai_failure_fastembed_fallback`: mock httpx `ConnectError` → fallback fastembed
  - `test_dimensions_consistent`: tutti i call sullo stesso modello restituiscono stessa dim

- **Test `MemoryPlugin`** (`tests/test_memory_plugin.py`):
  - `test_remember_tool`: chiama `remember` → `MemoryService.add()` chiamato con dati corretti
  - `test_recall_tool`: chiama `recall` → `MemoryService.search()` → risultati restituiti
  - `test_forget_requires_confirmation`: `forget` tool ha `requires_confirmation=True`
  - `test_memory_service_unavailable`: `ctx.memory_service = None` → tool restituisce errore graceful

- **Test context injection** (`tests/test_websocket.py` — estensione del file esistente):
  - `test_memory_injected_in_prompt`: memory_service con risultati → system prompt contiene `[RICORDI RILEVANTI]`
  - `test_no_injection_when_disabled`: `inject_in_context=False` → prompt invariato
  - `test_no_injection_when_no_results`: ricerca senza risultati → prompt invariato

- **Test REST API** (`tests/test_memory_api.py`):
  - List, search, delete, stats — pattern identico a `test_confirmation_audit.py`

- **Verifica no-regression** (eseguita PRIMA di ogni PR sulla fase 9):
  - tutta la suite esistente deve passare invariata (38 web_search + 24 pc_automation + 15 confirmation + ...)

---

#### 9.12 — File Structure Fase 9

```
backend/
├── services/
│   ├── memory_service.py      ← MemoryService (layer DB vettoriale)
│   └── embedding_client.py   ← EmbeddingClient (OpenAI + fastembed fallback)
├── plugins/
│   └── memory/
│       ├── __init__.py        ← import + PLUGIN_REGISTRY["memory"] = MemoryPlugin
│       └── plugin.py          ← MemoryPlugin con 5 tool
├── api/
│   └── routes/
│       └── memory.py          ← REST /api/memory/*
├── core/
│   ├── config.py              ← + MemoryConfig + OmniaConfig.memory field
│   ├── protocols.py           ← + MemoryServiceProtocol
│   └── app.py                 ← + MemoryService init nel lifespan
├── db/
│   └── models.py              ← + MemoryEntry SQLModel
└── tests/
    ├── test_memory_service.py
    ├── test_embedding_client.py
    ├── test_memory_plugin.py
    └── test_memory_api.py

frontend/src/renderer/src/
├── components/settings/
│   └── MemoryManager.vue
└── stores/
    └── memory.ts
```

---

#### 9.13 — Ordine di Implementazione Consigliato

1. **`EmbeddingClient`** — unit testabile in isolamento, zero dipendenze da resto
2. **`MemoryEntry` DB model** — aggiunta pura a `models.py`, zero modifica all'esistente
3. **`MemoryConfig`** — aggiunta a `config.py` e `default.yaml`
4. **`MemoryService`** — dipende da `EmbeddingClient` + DB
5. **Registrazione in `AppContext` e `app.py`** — wiring (dopo tutto il resto è pronto)
6. **`MemoryPlugin`** — dipende da `MemoryService` tramite context
7. **Context injection in `chat.py`** — modifica minimale, parametro opzionale in `build_messages()` + `LLMServiceProtocol`
8. **REST `/api/memory`** — endpoint CRUD (pattern già consolidato)
9. **Frontend `MemoryManager.vue`** — UI (indipendente dal backend)
10. **Test suite completa** — scritti in parallelo ai passi 1–9

---

#### 9.14 — Verifiche Fase 9

| Scenario | Comportamento atteso |
|---|---|
| "Ricorda che preferisco il terminale a Powershell" | LLM chiama `remember(content="...", category="preference")` → salvato |
| Sessione successiva: "Apri il terminale" | Context injection include preferenza → LLM apre correttamente senza ripetere la preferenza |
| "Dimentica le mie preferenze" | LLM chiama `recall(query="preferenze")` → trova le voci → chiama `forget()` per ognuna con conferma → rimosse |
| `memory.enabled=False` (default) | MemoryService non avviato (`ctx.memory_service = None`); i tool del plugin restituiscono `"Memory Service non attivo"` se il plugin è caricato, context injection saltata automaticamente; zero impatto su tutti i test esistenti |
| `memory` non in `plugins.enabled` | Tool LLM non disponibili; MemoryService può comunque girare (es. per future UI dirette); i due flag sono indipendenti |
| LM Studio offline durante embed | Fallback fastembed automatico, log warning, nessun crash |
| Cambio modello embedding (768→384 dim) | `MemoryDimensionMismatchError` con messaggio chiaro, nessuna corruzione dati |
| Conversazione di test senza `remember` | Nessun dato in memoria, zero inquinamento |

---

---

### Fase 10 — Autonomous Task Runner (Agente Proattivo)

> **Obiettivo**: trasformare OMNIA da assistente reattivo a agente proattivo capace di eseguire
> task in background — schedulati o event-driven — senza input utente in tempo reale.
> Con Fase 9 (memoria) + Fase 10 (autonomia) OMNIA diventa un agente vero.

- [x] AgentTask DB model — §10.1
- [x] TaskSchedulerConfig in config.py + default.yaml — §10.2
- [x] TaskScheduler service (asyncio loop) — §10.3
- [x] run_agent_task() headless runner — §10.4
- [x] AgentTaskPlugin (4 tool: schedule/cancel/list/get_result) — §10.5
- [x] WSConnectionManager service — §10.6
- [x] Endpoint /api/ws/events — §10.7
- [x] REST API /api/tasks — §10.8
- [x] OmniaEvent TASK_* events — §10.9
- [x] System prompt updates — §10.11
- [x] Frontend types/tasks.ts + stores/tasks.ts + useEventsWebSocket.ts + TaskManager.vue — §10.12
- [x] Wiring in app.py (WSConnectionManager + TaskScheduler + EventBus bridge) — §10.3/10.6
- [x] Routes registration (events + tasks) — §10.7/10.8
- [x] Protocols (TaskSchedulerProtocol + WSConnectionManagerProtocol) + AppContext fields — §10.6
- [ ] Test suite completa — §10.15

---

#### 10.0 — Analisi Vincoli e Scelte Architetturali

**Perché NON usare APScheduler, Celery o altri task runner esterni:**
- Il progetto usa esclusivamente `asyncio` low-level (VRAMMonitor, calendar reminder loop, TimerManager)
- APScheduler introduce dipendenze pesanti, processo separato con Celery, complessità di serializzazione
- **Soluzione scelta**: `TaskScheduler` service con `asyncio.create_task(_scheduler_loop())` — identico al pattern `VRAMMonitor` già nel codebase. Zero nuove dipendenze.

**Perché NON riusare il WebSocket di chat per il push background:**
- Il WS `/api/ws/chat` è per-messaggio: aperto durante una conversazione, non persistente
- Un task che finisce alle 3:00 non ha nessun WS di chat aperto a cui pushare
- **Soluzione scelta**: endpoint `/api/ws/events` — canale push persistente separato, connesso da frontend all'avvio. Completamente separato dal flusso chat. Pattern: server emette eventi `EventBus → WSConnectionManager.broadcast()`.

**Perché NON riadattare `run_tool_loop()` per i task:**
- `run_tool_loop()` richiede `websocket: WebSocket` — non ha senso creare un WebSocket fittizio
- Farlo violerebbe il contratto della funzione e introdurrebbe coupling nascosto
- **Soluzione scelta**: `run_agent_task()` — funzione dedicata, senza WebSocket, che esegue il tool loop LLM in modo headless e salva il risultato nel DB. Chiama direttamente `llm.chat()` e `tool_registry.execute_tool()` (che sono già standalone asyncio).

**Strategia trigger (senza dependency esterna):**
- `once_at: datetime` — una tantum, run al momento specificato
- `interval_seconds: int` — ricorrente, `next_run_at = last_run_at + timedelta(seconds=interval_seconds)`
- Nessuna espressione cron per v1 (evitare `croniter` per ora)
- Il `_scheduler_loop()` sveglia ogni `poll_interval_s` (default 30s) e controlla `WHERE status='pending' AND next_run_at <= NOW()`

**Concorrenza task:**
- `max_concurrent_tasks: int = 2` — non saturare LLM con richieste parallele
- `asyncio.Semaphore(max_concurrent_tasks)` nel loop di esecuzione
- Task che supera `task_timeout_s` viene cancellato con `asyncio.wait_for`

---

#### 10.1 — AgentTask DB Model (`backend/db/models.py`)

Aggiunta pura a `models.py`, zero modifica ai modelli esistenti. Pattern: `uuid.UUID` PK, `_new_uuid()`/`_utcnow()` factories, `CheckConstraint`, indici per query frequenti.

```python
class AgentTask(SQLModel, table=True):
    """A scheduled or one-shot background task executed autonomously by the agent."""

    __tablename__ = "agent_tasks"
    __table_args__ = (
        sa.CheckConstraint(
            "trigger_type IN ('once_at', 'interval', 'manual')",
            name="ck_task_trigger_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_task_status",
        ),
        sa.Index("ix_agent_task_status_next_run", "status", "next_run_at"),
        sa.Index("ix_agent_task_created_at", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=_new_uuid, primary_key=True)

    prompt: str = Field(
        description="Natural language instruction for the agent to execute.",
    )
    """What the agent must do when this task fires."""

    trigger_type: str = Field(
        description="once_at | interval | manual",
    )

    # -- Trigger scheduling ------------------------------------------------
    run_at: datetime | None = Field(
        default=None,
        description="For trigger_type='once_at': absolute UTC datetime to run.",
    )
    interval_seconds: int | None = Field(
        default=None,
        description="For trigger_type='interval': repeat every N seconds.",
    )
    next_run_at: datetime | None = Field(
        default=None,
        description="UTC datetime of the next scheduled execution. NULL = not yet scheduled.",
    )
    max_runs: int | None = Field(
        default=None,
        description="Max executions for interval tasks. NULL = unlimited.",
    )

    # -- Execution state ---------------------------------------------------
    status: str = Field(default="pending")
    run_count: int = Field(default=0)
    last_run_at: datetime | None = None

    # -- Result ------------------------------------------------------------
    result_summary: str | None = Field(
        default=None,
        description="LLM-generated summary of what the task accomplished.",
    )
    error_message: str | None = None

    # -- Context -----------------------------------------------------------
    conversation_id: uuid.UUID | None = Field(
        default=None,
        description="Optional: conversation from which this task was created.",
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
```

**Indice composito `(status, next_run_at)`**: la query del scheduler è `WHERE status='pending' AND next_run_at <= :now` — questo indice la rende O(log n).

---

#### 10.2 — TaskSchedulerConfig (`backend/core/config.py`)

```python
class TaskSchedulerConfig(BaseSettings):
    """Background task scheduler configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_TASK_SCHEDULER__")

    enabled: bool = False
    """Abilita il TaskScheduler. False di default (opt-in)."""

    poll_interval_s: float = 30.0
    """Secondi tra ogni check DB per task da eseguire."""

    max_concurrent_tasks: int = 2
    """Task eseguibili contemporaneamente. Limita la pressione sull'LLM."""

    task_timeout_s: int = 300
    """Timeout massimo per singolo task (5 minuti). Superato: status → 'failed'."""

    max_task_prompt_chars: int = 2000
    """Lunghezza massima del prompt di un task (sicurezza)."""

    max_runs_safety_cap: int = 1000
    """Cap di sicurezza per max_runs su task interval (evita loop infiniti)."""

    result_retention_days: int = 30
    """Giorni di retention per task completati/falliti prima della pulizia."""
```

Aggiunta a `OmniaConfig`:
```python
task_scheduler: TaskSchedulerConfig = Field(default_factory=TaskSchedulerConfig)
```

Config YAML (`config/default.yaml`):
```yaml
task_scheduler:
  enabled: false
  poll_interval_s: 30.0
  max_concurrent_tasks: 2
  task_timeout_s: 300

# In plugins.enabled, aggiungere (commentato per default-off):
# - agent_task  # abilitare con task_scheduler.enabled: true
```

---

#### 10.3 — TaskScheduler Service (`backend/services/task_scheduler.py`)

**Ruolo**: service core che gira in background, trova task pronti e li esegue. Pattern identico a `VRAMMonitor` (start/stop + `_poll_task: asyncio.Task | None`).

```
TaskScheduler
├── __init__(config)     — solo config; NESSUNA I/O (pattern VRAMMonitor)
├── start(ctx)           — salva ctx, inizializza Semaphore + _queued_ids, avvia loop
├── stop()               — cancella il task, raccoglie errori (contextlib.suppress)
├── _scheduler_loop()    — asyncio.sleep(poll_interval_s) → _tick()
├── _tick()              — query DB → filtra _queued_ids → asyncio.create_task
├── _execute_task(task)  — Semaphore + wait_for + run_agent_task() + discard _queued_ids
├── _mark_done(task)     — aggiorna status/result/next_run_at in DB
└── _queued_ids          — set[uuid.UUID]: guard anti-doppio-dispatch tra tick consecutivi
```

**`TaskSchedulerProtocol` e costruttore** (da aggiungere a `protocols.py` e `task_scheduler.py`):

```python
# backend/core/protocols.py
class TaskSchedulerProtocol(Protocol):
    """Protocol for the background autonomous task scheduler."""
    async def start(self, ctx: Any) -> None: ...
    async def stop(self) -> None: ...
    async def schedule(self, task: Any) -> str: ...  # returns task_id str
    async def cancel(self, task_id: str) -> bool: ...

# backend/services/task_scheduler.py — costruttore
class TaskScheduler:
    def __init__(self, config: TaskSchedulerConfig) -> None:
        self._config = config
        self._ctx: Any = None                        # set lazily in start()
        self._poll_task: asyncio.Task[None] | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._queued_ids: set[uuid.UUID] = set()     # anti-double-dispatch

    async def start(self, ctx: Any) -> None:
        self._ctx = ctx
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_tasks)
        self._poll_task = asyncio.create_task(
            self._scheduler_loop(), name="task-scheduler",
        )

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
```

**Implementazione `_scheduler_loop()`** (segue esattamente il pattern VRAMMonitor):

```python
async def _scheduler_loop(self) -> None:
    """Check for due tasks and execute them, forever."""
    while True:
        try:
            await self._tick()
        except asyncio.CancelledError:
            raise  # SEMPRE propagare CancelledError — regola del progetto
        except Exception:
            logger.opt(exception=True).error("TaskScheduler tick error")
        await asyncio.sleep(self._config.poll_interval_s)

async def _tick(self) -> None:
    """Find all pending tasks due <= now and dispatch them."""
    now = datetime.now(timezone.utc)
    async with self._ctx.db() as session:
        result = await session.exec(
            select(AgentTask)
            .where(AgentTask.status == "pending")
            .where(AgentTask.next_run_at <= now)
            .order_by(AgentTask.next_run_at)
            .limit(self._config.max_concurrent_tasks * 2)
        )
        due_tasks = result.all()

    for task in due_tasks:
        if task.id in self._queued_ids:
            continue  # guard: previene doppio-dispatch tra tick consecutivi
        self._queued_ids.add(task.id)
        asyncio.create_task(
            self._execute_task(task),
            name=f"agent-task-{task.id}",
        )
```

**`_execute_task()`** — usa `asyncio.Semaphore` per concorrenza + `asyncio.wait_for` per timeout:

```python
async def _execute_task(self, task: AgentTask) -> None:
    async with self._semaphore:  # max_concurrent_tasks
        # Mark as running
        await self._update_status(task.id, "running")

        _final_status = "failed"  # track real outcome for finally (task.status is stale)
        try:
            summary = await asyncio.wait_for(
                run_agent_task(self._ctx, task),
                timeout=self._config.task_timeout_s,
            )
            _final_status = "completed"
            await self._mark_done(task, success=True, summary=summary)
        except asyncio.TimeoutError:
            await self._mark_done(task, success=False,
                                  error=f"Task timed out after {self._config.task_timeout_s}s")
        except asyncio.CancelledError:
            _final_status = "cancelled"
            await self._mark_done(task, success=False, error="Task cancelled")
            raise
        except Exception as exc:
            await self._mark_done(task, success=False, error=str(exc))
        finally:
            self._queued_ids.discard(task.id)  # libera il guard
            # Emit EventBus event → WSConnectionManager broadcasts to /ws/events clients
            await self._ctx.event_bus.emit(
                OmniaEvent.TASK_COMPLETED,
                task_id=str(task.id),
                status=_final_status,
            )
```

**`_mark_done()`** — aggiorna DB e calcola `next_run_at` per task interval:

```python
async def _mark_done(self, task: AgentTask, success: bool, summary: str = "", error: str = "") -> None:
    async with self._ctx.db() as session:
        db_task = await session.get(AgentTask, task.id)
        db_task.status = "completed" if success else "failed"
        db_task.result_summary = summary
        db_task.error_message = error if not success else None
        db_task.last_run_at = datetime.now(timezone.utc)
        db_task.run_count += 1
        db_task.updated_at = datetime.now(timezone.utc)

        if task.trigger_type == "interval" and success and task.interval_seconds is not None:
            # Check max_runs cap (interval_seconds must not be None here — guard defensivo)
            if task.max_runs is None or db_task.run_count < task.max_runs:
                db_task.status = "pending"
                db_task.next_run_at = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=task.interval_seconds)
                )

        await session.commit()
```

**Startup in `app.py`** (dopo `plugin_manager.startup()` — il task scheduler ha bisogno del tool_registry):

```python
if config.task_scheduler.enabled:
    from backend.services.task_scheduler import TaskScheduler
    task_scheduler = TaskScheduler(config.task_scheduler)
    try:
        await task_scheduler.start(ctx)
        ctx.task_scheduler = task_scheduler
        logger.info("Task scheduler started (poll={}s)", config.task_scheduler.poll_interval_s)
    except Exception as exc:
        logger.warning("Task scheduler failed to start: {}", exc)

# Aggiunto in shutdown:
if ctx.task_scheduler:
    try:
        await ctx.task_scheduler.stop()
    except Exception as exc:
        logger.error("Task scheduler shutdown error: {}", exc)
```

---

#### 10.4 — run_agent_task() (`backend/services/task_runner.py`)

**Ruolo**: esegue un singolo `AgentTask` in modo headless (senza WebSocket). Funzione standalone, non un metodo del service, per facilitare i test unitari.

```python
async def run_agent_task(ctx: AppContext, task: AgentTask) -> str:
    """Execute an agent task headlessly and return a result summary.

    Runs a full LLM + tool loop without a WebSocket. Results are
    returned as a natural-language summary string.

    Args:
        ctx: Application context with llm_service and tool_registry.
        task: The AgentTask to execute.

    Returns:
        Natural language summary of what the agent accomplished.

    Raises:
        RuntimeError: If LLM service is unavailable.
        asyncio.TimeoutError: Propagated from caller (TaskScheduler).
        asyncio.CancelledError: Propagated — never swallowed.
    """
    if ctx.llm_service is None:
        raise RuntimeError("LLM service not available")

    tools = await ctx.tool_registry.get_available_tools() if ctx.tool_registry else []

    messages = ctx.llm_service.build_messages(
        user_content=task.prompt,
        history=None,
    )

    conversation_buf: list[dict[str, Any]] = list(messages)
    final_content = ""
    max_iterations = ctx.config.llm.max_tool_iterations

    for iteration in range(max_iterations):
        tool_calls: list[dict[str, Any]] = []
        content_parts: list[str] = []

        async for event in ctx.llm_service.chat(
            conversation_buf,
            tools=tools if tools else None,
        ):
            if event["type"] == "token":
                content_parts.append(event["content"])
            elif event["type"] == "tool_call":
                tool_calls.append(event)
            elif event["type"] == "done":
                break

        final_content = "".join(content_parts)

        if not tool_calls:
            break  # LLM non ha richiesto tool → risposta finale

        # Append assistant message with tool_calls
        conversation_buf.append({
            "role": "assistant",
            "content": final_content,
            "tool_calls": [tc["tool_call"] for tc in tool_calls],
        })

        # Execute all tool calls
        for tc in tool_calls:
            tc_id = tc["tool_call"]["id"]
            name = tc["tool_call"]["function"]["name"]
            args = json.loads(tc["tool_call"]["function"].get("arguments", "{}"))

            execution_ctx = ExecutionContext(
                session_id=f"task-{task.id}",
                conversation_id=str(task.id),
                execution_id=str(uuid.uuid4()),
            )

            try:
                result = await ctx.tool_registry.execute_tool(name, args, execution_ctx)
                tool_content = result.content if isinstance(result.content, str) else json.dumps(result.content)
            except Exception as exc:
                tool_content = f"Error: {exc}"

            conversation_buf.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": tool_content,
            })
    else:
        logger.warning("Task {} hit max_iterations={}", task.id, max_iterations)

    return final_content or "(no output)"
```

**Nota sicurezza**: `run_agent_task` NON supporta tool con `requires_confirmation=True` — i tool richiedenti conferma vengono saltati con un messaggio di errore nel risultato. I task autonomi devono usare solo tool `risk_level="safe"` o `"low"`. Questo è enforced nel plugin (vedi §10.5).

---

#### 10.5 — AgentTask Plugin (`backend/plugins/agent_task/`)

**Ruolo**: espone 4 tool LLM per creare/gestire task autonomi. Pattern identico a tutti gli altri plugin.

```
backend/plugins/agent_task/
├── __init__.py   — import + PLUGIN_REGISTRY["agent_task"] = AgentTaskPlugin
└── plugin.py     — AgentTaskPlugin(BasePlugin)
```

**Tool definitions**:

| Tool | risk_level | requires_confirmation | Descrizione |
|---|---|---|---|
| `schedule_task` | `safe` | `False` | Crea un task autonomo da eseguire in background |
| `cancel_task` | `medium` | `True` | Cancella un task attivo o pianificato |
| `list_tasks` | `safe` | `False` | Elenca i task con filtri opzionali |
| `get_task_result` | `safe` | `False` | Recupera il risultato di un task completato |

> **Nota**: `"low"` non è un valore valido per `ToolDefinition.risk_level` (valori: `"safe"`, `"medium"`, `"dangerous"`, `"forbidden"`). `schedule_task` è `"safe"` perché crea solo un record DB — nessun side effect esterno immediato.

**Schema `schedule_task`**:
```json
{
  "type": "object",
  "properties": {
    "prompt": {
      "type": "string",
      "description": "Istruzione completa per il task. Deve essere auto-esplicativa (l'agente non avrà contesto aggiuntivo al momento dell'esecuzione).",
      "maxLength": 2000
    },
    "trigger_type": {
      "type": "string",
      "enum": ["once_at", "interval", "manual"],
      "description": "once_at: esegui una volta a una data/ora precisa. interval: ripeti ogni N secondi. manual: esegui solo su richiesta esplicita."
    },
    "run_at": {
      "type": "string",
      "description": "ISO 8601 UTC datetime. Obbligatorio se trigger_type='once_at'.",
      "format": "date-time"
    },
    "interval_seconds": {
      "type": "integer",
      "description": "Intervallo in secondi. Obbligatorio se trigger_type='interval'. Min: 60 (1 minuto).",
      "minimum": 60
    },
    "max_runs": {
      "type": "integer",
      "description": "Numero massimo di esecuzioni per task interval. Null = illimitato.",
      "minimum": 1
    }
  },
  "required": ["prompt", "trigger_type"]
}
```

**Validazione in `execute_tool`**:
- `trigger_type='once_at'` senza `run_at` → errore descrittivo
- `trigger_type='interval'` senza `interval_seconds` → errore descrittivo
- `interval_seconds < 60` → errore: "Intervallo minimo: 60 secondi"
- `prompt` > `max_task_prompt_chars` → errore: "Prompt troppo lungo"
- `task_scheduler.enabled=False` → errore: "Task scheduler non attivo"

---

#### 10.6 — WSConnectionManager (`backend/services/ws_connection_manager.py`)

**Ruolo**: mantiene i client connessi a `/api/ws/events` e consente `broadcast()`. Separato dal chat WS. Usato da `TaskScheduler` per fare push dei task completati.

```python
class WSConnectionManager:
    """Manages persistent event WebSocket connections for background push."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}  # session_id → ws
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[session_id] = ws

    async def disconnect(self, session_id: str) -> None:
        async with self._lock:
            self._connections.pop(session_id, None)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Send event to all connected clients. Silently drops disconnected ones.

        Snapshots connections under the lock, then sends OUTSIDE it — holding
        an asyncio.Lock during `await send_json()` would cause starvation if
        any client is slow to receive.
        """
        async with self._lock:
            snapshot = list(self._connections.items())  # O(n) snapshot, lock released
        dead: list[str] = []
        for sid, ws in snapshot:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(sid)
        if dead:
            async with self._lock:
                for sid in dead:
                    self._connections.pop(sid, None)

    async def send_to(self, session_id: str, event: dict[str, Any]) -> None:
        """Send event to a specific session. No-op if disconnected."""
        async with self._lock:
            ws = self._connections.get(session_id)  # read under lock
        if ws:
            try:
                await ws.send_json(event)
            except Exception:
                async with self._lock:  # cleanup under lock
                    self._connections.pop(session_id, None)
```

`WSConnectionManager` viene creato UNA VOLTA nel lifespan di `app.py` e assegnato a `ctx.ws_connection_manager`. Il `TaskScheduler` riceve `ctx` nel costruttore e chiama `ctx.ws_connection_manager.broadcast(...)` dopo ogni task.

**Registrazione in `AppContext`** (nuovo campo):
```python
ws_connection_manager: WSConnectionManagerProtocol | None = None
```

Aggiunto anche in `protocols.py` (`WSConnectionManagerProtocol`).

**EventBus bridge** (in `app.py` lifespan, dopo la creazione del `ws_connection_manager`):
```python
async def _on_task_completed(**kwargs):
    if ctx.ws_connection_manager:
        await ctx.ws_connection_manager.broadcast({
            "type": "task_completed",
            "task_id": kwargs["task_id"],
            "status": kwargs["status"],
        })
ctx.event_bus.subscribe(OmniaEvent.TASK_COMPLETED, _on_task_completed)
```

---

#### 10.7 — Endpoint `/api/ws/events` (`backend/api/routes/events.py`)

Router con prefix e tag coerenti col resto del progetto (pattern di `audit.py`):

```python
router = APIRouter(prefix="/events", tags=["events"])

@router.websocket("/ws")
async def ws_events(websocket: WebSocket) -> None:
    """Persistent push channel for background task events.

    Clients connect once at startup and receive push events whenever
    a background task completes, fails, or changes status.
    """
    # Pattern coerente con chat.py: ctx via websocket.app.state.context
    ctx: AppContext = websocket.app.state.context
    if ctx.ws_connection_manager is None:
        await websocket.close(code=1011, reason="Events service not available")
        return

    session_id = f"events-{uuid.uuid4().hex[:12]}"
    await ctx.ws_connection_manager.connect(session_id, websocket)

    try:
        # Keep connection alive; client sends ping {"type": "ping"}
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=60.0)
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send keep-alive
                await websocket.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                break
    finally:
        await ctx.ws_connection_manager.disconnect(session_id)
```

**URL effettivo** (per il frontend): `/api/events/ws` — derivato da prefix `/api` (root) + `/events` (router) + `/ws` (endpoint).

**Registrazione in `routes/__init__.py`**:
```python
from backend.api.routes import audit, calendar, chat, config, events, models, plugins, settings, tasks, voice

router.include_router(events.router)
router.include_router(tasks.router)
```

Router di `tasks.py`:
```python
router = APIRouter(prefix="/tasks", tags=["tasks"])
```

---

#### 10.8 — REST API (`backend/api/routes/tasks.py`)

Pattern identico a `audit.py` (già noto nel progetto):

```
GET    /api/tasks                     — lista task (filtri: status, trigger_type, limit, offset)
GET    /api/tasks/{task_id}           — dettaglio singolo task
POST   /api/tasks                     — crea task manuale (bypass tool loop)
DELETE /api/tasks/{task_id}           — cancella task
PATCH  /api/tasks/{task_id}/run       — trigger manuale immediato (task manual)
GET    /api/tasks/stats               — count per status
```

**Request body `POST /api/tasks`** (`TaskCreateRequest` Pydantic model):
```python
class TaskCreateRequest(BaseModel):
    prompt: str = Field(max_length=2000)
    trigger_type: Literal["once_at", "interval", "manual"]
    run_at: datetime | None = None
    interval_seconds: int | None = Field(default=None, ge=60)
    max_runs: int | None = Field(default=None, ge=1)
```

---

#### 10.9 — OmniaEvent Updates (`backend/core/event_bus.py`)

Aggiunta dei nuovi event al `OmniaEvent` StrEnum (senza modificare quelli esistenti):

```python
# Task events (Phase 10)
TASK_SCHEDULED = "task.scheduled"
TASK_STARTED = "task.started"
TASK_COMPLETED = "task.completed"
TASK_FAILED = "task.failed"
TASK_CANCELLED = "task.cancelled"
```

---

#### 10.10 — WebSocket Protocol Updates

Nuovi messaggi S→C su `/api/events/ws` (URL derivato da prefix `/api` + `/events` + `/ws`):

> **Frontend**: il composable `useEventsWebSocket.ts` si connette a `ws://localhost:8000/api/events/ws`.
> All'opposte, la chat WS è su `ws://localhost:8000/api/ws/chat` (definita in `chat.py` con `@router.websocket("/ws/chat")` senza prefix).

Nuovi messaggi S→C su `/api/events/ws`:

| Type | Struttura | Quando |
|---|---|---|
| `task_scheduled` | `{task_id, trigger_type, next_run_at, prompt_preview}` | Task creato/pianificato |
| `task_started` | `{task_id, started_at}` | Inizio esecuzione |
| `task_completed` | `{task_id, status, result_summary, duration_ms}` | Fine esecuzione (ok o fail) |
| `task_failed` | `{task_id, error_message}` | Esecuzione fallita |
| `task_cancelled` | `{task_id}` | Cancellato da utente |
| `heartbeat` | `{}` | Keep-alive ogni 60s |
| `pong` | `{}` | Risposta a `ping` |

Nuovi messaggi **su `/api/ws/chat`** (già esistente) — aggiunta minima:
```json
{"type": "task_created", "task_id": "uuid", "trigger_type": "once_at", "next_run_at": "ISO"}
```
Inviato da `chat.py` quando l'LLM chiama lo strumento `schedule_task` durante una conversazione, così l'utente vede feedback immediato.

---

#### 10.11 — System Prompt Updates (`config/system_prompt.md`)

Aggiungere sezione dedicata nella sezione `tools`:

```yaml
agent_task:
  use: usa SOLO per compiti che l'utente vuole eseguire in modo autonomo in futuro o ricorrente. MAI per compiti one-shot immediati (eseguili subito invece).
  rules:
    - il prompt del task deve essere completamente auto-esplicativo: l'agente non avrà contesto aggiuntivo al momento dell'esecuzione
    - specifica sempre trigger_type in modo esplicito ('once_at', 'interval', 'manual')
    - per 'once_at': usa sempre ISO 8601 UTC, converti l'orario locale dell'utente
    - per 'interval': intervallo minimo 60 secondi; usa valori ragionevoli (es. 3600 per ogni ora)
    - MAI creare task che creano altri task (ricorsione vietata)
    - MAI schedulare task per ambienti non disponibili (es. Home Assistant se offline)
    - CONFERMA sempre orario e frequenza prima di schedulare: "Vuoi che lo esegua ogni giorno alle 8:00?"
    - i task autonomi possono usare SOLO tool non-distruttivi (risk_level='safe')
```

---

#### 10.12 — Frontend

**Nuovo Pinia store `tasks.ts`**:

```typescript
interface AgentTask {
  id: string
  prompt: string
  triggerType: 'once_at' | 'interval' | 'manual'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  runAt: string | null
  intervalSeconds: number | null
  nextRunAt: string | null
  runCount: number
  resultSummary: string | null
  errorMessage: string | null
  createdAt: string
}

interface TasksState {
  tasks: AgentTask[]
  total: number
  loading: boolean
  recentActivity: TaskActivityEvent[]  // push events da /ws/events
}

// actions:
loadTasks(filters?)       // GET /api/tasks
cancelTask(id)            // DELETE /api/tasks/{id}
triggerManual(id)         // PATCH /api/tasks/{id}/run
createTask(req)           // POST /api/tasks
onTaskEvent(event)        // handler per push events da WSEventsManager
```

**Nuovo composable `useEventsWebSocket.ts`**:

```typescript
// Connessione persistente a /api/ws/events, avviata in App.vue
// Gestisce reconnect (stesso pattern di WebSocketManager per /ws/chat)
// Distribuisce eventi al tasks store via tasksStore.onTaskEvent()
// Heartbeat ogni 30s per mantenere connessione viva
```

**Componente `TaskManager.vue`** (in `components/settings/`):
- Lista task attivi/pianificati con countdown a `next_run_at`
- Badge "in esecuzione" animato
- Pulsante "Esegui ora" per task manual
- Pulsante "Cancella" (con confirm dialog)
- Log degli ultimi N task completati con risultato espandibile

**Notifica toast** (in `App.vue`) quando arriva evento `task_completed` via `/ws/events` — non-invasiva, angolo bottom-right, scompare dopo 5s.

---

#### 10.13 — Dipendenze e Compatibilità

**Nessuna nuova dipendenza** — tutto usa librerie già nel progetto:
- `asyncio` (già usato ovunque)
- `sqlmodel` + `aiosqlite` (già usato)
- `fastapi` WebSocket (già usato)

**VRAM impact**: zero — il `TaskScheduler` non carica modelli. Usa `ctx.llm_service` già in memoria. Se LM Studio è offline durante l'esecuzione del task, `run_agent_task()` solleva `RuntimeError` e il task va in `status='failed'` con messaggio chiaro.

**Sicurezza**:
- Tool con `requires_confirmation=True` vengono bloccati in `run_agent_task()` (nessuna conferma utente possibile in background) con messaggio nel risultato: `"Tool '{name}' richiede conferma utente — non eseguibile in task autonomi"`
- Tool con `risk_level='dangerous'` o `'forbidden'` vengono bloccati allo stesso modo
- `max_task_prompt_chars` previene prompt injection eccessivamente elaborati
- Il prompt del task è salvato in DB as-is e mostrato nella UI prima dell'esecuzione

---

#### 10.14 — File Structure Fase 10

```
backend/
├── services/
│   ├── task_scheduler.py           ← TaskScheduler (asyncio loop, VRAMMonitor pattern)
│   ├── task_runner.py              ← run_agent_task() headless function
│   └── ws_connection_manager.py   ← WSConnectionManager (broadcast + per-session send)
├── plugins/
│   └── agent_task/
│       ├── __init__.py             ← PLUGIN_REGISTRY["agent_task"] = AgentTaskPlugin
│       └── plugin.py              ← AgentTaskPlugin con 4 tool
├── api/
│   └── routes/
│       ├── events.py              ← /api/ws/events WebSocket endpoint
│       └── tasks.py               ← REST /api/tasks/*
├── core/
│   ├── config.py                  ← + TaskSchedulerConfig + OmniaConfig.task_scheduler
│   ├── protocols.py               ← + TaskSchedulerProtocol + WSConnectionManagerProtocol
│   ├── context.py                 ← + task_scheduler + ws_connection_manager fields
│   ├── event_bus.py               ← + TASK_* events in OmniaEvent
│   └── app.py                     ← + wiring TaskScheduler + WSConnectionManager
├── db/
│   └── models.py                  ← + AgentTask SQLModel
└── tests/
    ├── test_task_scheduler.py
    ├── test_task_runner.py
    ├── test_agent_task_plugin.py
    ├── test_tasks_api.py
    └── test_ws_events.py

frontend/src/renderer/src/
├── stores/
│   └── tasks.ts
├── composables/
│   └── useEventsWebSocket.ts
├── types/
│   └── tasks.ts                   ← AgentTask, TaskActivityEvent TypeScript types
└── components/settings/
    └── TaskManager.vue
```

---

#### 10.15 — Test Suite Fase 10

- **`test_task_runner.py`**:
  - `test_run_agent_task_no_tools`: LLM risponde senza tool call → `result_summary` contiene la risposta
  - `test_run_agent_task_with_tool_call`: mock tool registry + mock LLM con tool_call → tool eseguito, risultato in conversazione
  - `test_run_agent_task_llm_unavailable`: `ctx.llm_service = None` → `RuntimeError` propagato
  - `test_run_agent_task_blocks_dangerous_tools`: tool con `risk_level='dangerous'` → bloccato con messaggio nel risultato
  - `test_run_agent_task_cancelled`: `asyncio.CancelledError` propagato correttamente
  - `test_run_agent_task_max_iterations`: loop LLM con tool calls continui → stop a `max_iterations`

- **`test_task_scheduler.py`** (pattern identico a `test_vram_monitor.py`):
  - `test_start_creates_background_task`: `scheduler.start(ctx)` → `scheduler._poll_task` non è None
  - `test_stop_cancels_background_task`: `start()` → `stop()` → `_poll_task is None`
  - `test_tick_finds_due_tasks`: DB con task pending + `next_run_at = past` → `_tick()` lo trova
  - `test_tick_ignores_future_tasks`: `next_run_at = future` → non eseguito
  - `test_interval_task_rescheduled`: task interval completato → `next_run_at` aggiornato, `status = 'pending'`
  - `test_once_task_not_rescheduled`: task `once_at` completato → `status = 'completed'`, nessun `next_run_at`
  - `test_max_concurrent_semaphore`: `max_concurrent_tasks=1` + 3 task simultanei → al più 1 in running
  - `test_task_timeout`: `task_timeout_s=1` + `run_agent_task` che dura 5s → `asyncio.TimeoutError → status='failed'`
  - `test_scheduler_disabled`: `task_scheduler.enabled=False` → non avviato, zero impatto

- **`test_agent_task_plugin.py`**:
  - `test_schedule_once_at`: chiama `schedule_task` con `trigger_type='once_at'` → `AgentTask` in DB
  - `test_schedule_interval_min_60s`: `interval_seconds=30` → errore descrittivo
  - `test_cancel_task_requires_confirmation`: `cancel_task` ha `requires_confirmation=True`
  - `test_list_tasks`: `list_tasks()` → query DB → risultati formattati
  - `test_schedule_without_required_field`: `once_at` senza `run_at` → errore chiaro

- **`test_ws_events.py`**:
  - `test_ws_events_connect_keepalive`: connect → ping → pong ricevuto
  - `test_ws_events_broadcast`: `manager.broadcast(event)` → tutti i client connessi ricevono
  - `test_ws_events_dead_connection_removed`: client la cui WS fallisce → rimosso da `_connections`

- **`test_tasks_api.py`** (pattern identico a `test_confirmation_audit.py`):
  - CRUD completo via `AsyncClient`
  - Filtri per status
  - `PATCH /tasks/{id}/run` su task manual

- **Verifica no-regression** (pre-PR): tutta la suite esistente deve passare invariata

---

#### 10.16 — Ordine di Implementazione Consigliato

1. **`AgentTask` DB model** — aggiunta pura a `models.py`
2. **`TaskSchedulerConfig`** — aggiunta a `config.py` + `default.yaml`
3. **`OmniaEvent` task events** — aggiunta a `event_bus.py`
4. **`WSConnectionManager`** — nuovo file, zero dipendenze
5. **`WSConnectionManagerProtocol`** + campo `AppContext` + wiring in `app.py`
6. **`/api/ws/events` endpoint** — `events.py` route
7. **`run_agent_task()`** — `task_runner.py`, unit testabile in isolamento
8. **`TaskScheduler`** + `TaskSchedulerProtocol` + campo `AppContext` + wiring in `app.py`
9. **`AgentTaskPlugin`** — dipende da `TaskScheduler` tramite `AppContext`
10. **REST `/api/tasks`** — `tasks.py` route
11. **Frontend `tasks.ts` store + `useEventsWebSocket.ts` + `TaskManager.vue`**
12. **Test suite completa**

---

#### 10.17 — Verifiche Fase 10

| Scenario | Comportamento atteso |
|---|---|
| "Ogni mattina alle 8:00 mandami un briefing meteo + notizie" | LLM chiama `schedule_task(trigger_type='interval', interval_seconds=86400, run_at='...')` → task in DB → alle 8:00 `run_agent_task` esegue news + weather tool → risultato push via `/ws/events` |
| "Cancella il briefing mattutino" | LLM chiama `list_tasks` → trova task → chiama `cancel_task(task_id)` con confirm → status='cancelled' |
| Task fallisce (LM Studio offline) | status='failed', `error_message="LLM service not available"`, push event al frontend, task interval resta in pending per il prossimo ciclo |
| Task tenta tool con `requires_confirmation=True` | Bloccato da `run_agent_task()` con messaggio nel risultato, non crashato |
| `task_scheduler.enabled=False` (default) | Backend avvia normalmente, tool `schedule_task` restituisce errore chiaro, zero impatto su test esistenti |
| 3 task in DB tutti in scadenza contemporaneamente con `max_concurrent_tasks=2` | Solo 2 vengono eseguiti in parallelo; il terzo attende che si liberi un slot |
| Task interval con `max_runs=5` che ha già girato 5 volte | `status='completed'`, non rischedulato, stop definitivo |
| Frontend disconnesso quando task termina | `broadcast()` fallisce silenziosamente per quella sessione, rimossa da `_connections`, nessun crash |
| Restart backend con task interval in pending | Al riavvio `_tick()` trova `next_run_at <= NOW()` → esegue immediatamente |

---

### Fase 11 — MCP Client (Strumenti Esterni via Model Context Protocol)

> **Obiettivo**: permettere a OMNIA di connettersi a qualsiasi server MCP esterno
> (filesystem, database, git, browser, motori di ricerca, ecc.) tramite il
> Model Context Protocol. I tool esposti dai server MCP entrano automaticamente
> nel `ToolRegistry` esistente e diventano disponibili all'LLM — senza modifiche
> al flusso chat, al tool loop o a qualsiasi layer esistente.

- [x] `McpServerConfig` + `McpConfig` in `config.py` + `default.yaml` — §11.1
- [x] `McpSession` service (stdio + SSE transport) — §11.2
- [x] `McpClientPlugin` (aggregazione + dispatch) — §11.3
- [x] Tool namespacing `mcp_{server}_{tool}` — §11.4
- [x] `OmniaEvent.MCP_SERVER_CONNECTED` + `MCP_SERVER_DISCONNECTED` — §11.5
- [x] Dipendenza `mcp` in `pyproject.toml` — §11.6
- [x] File structure — §11.7
- [x] Test suite (2 file, 14+ test case) — §11.8

---

#### 11.0 — Analisi Vincoli e Scelte Architetturali

**Perché un Plugin, non un Service:**
- Il pattern "esponi tool all'LLM" è esattamente il contratto di `BasePlugin`
- `get_tools()` + `execute_tool()` è l'interfaccia perfetta per aggregare tool remoti
- Il `PluginManager` gestisce già lifecycle (init/cleanup), crash isolation e health check
- Il `ToolRegistry` aggrega già i tool da tutti i plugin — zero modifiche necessarie
- `AppContext` non richiede nuovi campi — il plugin vive in `plugin_manager` come gli altri

**Perché un Plugin unico (`McpClientPlugin`) e non un plugin per server:**
- Il `PLUGIN_REGISTRY` è statico (popolato a import-time per compatibilità PyInstaller)
- Creare plugin dinamicamente da config violerebbe questo pattern fondamentale
- Un singolo plugin che gestisce N sessioni è il compromesso corretto:
  config-driven, lifecycle unificato, crash isolation a livello di singola sessione

**Perché il SDK ufficiale `mcp` e non raw JSON-RPC:**
- `mcp` è il package ufficiale Anthropic, mantenuto attivamente
- Gestisce transport abstraction (stdio/SSE), capabilities negotiation e framing messaggi
- Riduce il codice OMNIA a ~150 LOC totali senza duplicare logica di protocollo
- Usa `httpx` (già presente) per SSE e `anyio`/`asyncio` per subprocess stdio

**Tool namespacing — `mcp_{server}_{tool}`:**
- I plugin nativi OMNIA usano `{plugin_name}_{tool_name}` (es. `system_info_get_cpu_usage`)
- I tool MCP vengono prefissati `mcp_{server_name}_{tool_name}` da `McpClientPlugin.get_tools()`; il `ToolRegistry` aggiunge il prefisso `mcp_client_` → l’LLM vede `mcp_client_mcp_{server}_{tool}` (es. `mcp_client_mcp_filesystem_read_file`)
- Nessuna collisione possibile: il prefisso `mcp_` non è mai usato da plugin nativi
- Parsing inverso deterministico: iterare le sessioni cercando il prefisso corrispondente

**Nessuna modifica ai layer esistenti:**
- `LLMService`: invariato — il LLM riceve tool in formato OpenAI e li chiama per nome
- `ToolRegistry`: invariato — aggrega `get_tools()` da tutti i plugin incluso `McpClientPlugin`
- `ChatRoute` + `_tool_loop.py`: invariati — `tool_registry.execute_tool(name, args)` funziona già
- `AppContext`: nessun nuovo campo
- Frontend: il plugin card `mcp_client` appare automaticamente nell'UI plugin esistente

**Nessun endpoint REST dedicato (v1):**
- I server MCP si configurano via `config/default.yaml`
- Lo stato è visibile tramite `/api/plugins` (health check esistente)
- Una UI per gestire dinamicamente i server MCP è rinviata a v2

---

#### 11.1 — McpConfig (`backend/core/config.py`)

Nuove classi aggiunte in `config.py`, dopo `MemoryConfig`:

```python
class McpServerConfig(BaseModel):
    """Configuration for a single MCP server connection."""

    name: str
    """Unique identifier (lowercase_snake_case). Used in tool prefix: mcp_{name}_*."""

    transport: Literal["stdio", "sse"] = "stdio"
    """Connection transport: 'stdio' for subprocess, 'sse' for HTTP/SSE."""

    command: list[str] | None = None
    """[stdio only] Command + args to launch the MCP server subprocess.
    Example: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/docs"]
    """

    url: str | None = None
    """[sse only] Full URL of the SSE endpoint.
    Example: "http://localhost:3000/sse"
    """

    env: dict[str, str] = {}
    """Extra environment variables injected into the subprocess (stdio only)."""

    enabled: bool = True
    """Set to false to skip this server without removing it from config."""

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> McpServerConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError(
                f"MCP server '{self.name}': stdio transport requires 'command'"
            )
        if self.transport == "sse" and not self.url:
            raise ValueError(
                f"MCP server '{self.name}': sse transport requires 'url'"
            )
        return self


class McpConfig(BaseSettings):
    """MCP client configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_MCP__")

    servers: list[McpServerConfig] = Field(default_factory=list)
    """List of MCP servers to connect at startup. Empty by default (opt-in)."""
```

Campo aggiunto a `OmniaConfig` (dopo `memory`):

```python
mcp: McpConfig = Field(default_factory=McpConfig)
```

Aggiunta in `config/default.yaml` (in fondo, dopo la sezione `memory`):

```yaml
mcp:
  servers: []
  # Esempi di server MCP disponibili (decommentare e configurare per abilitare):
  #
  # - name: filesystem
  #   transport: stdio
  #   command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "C:/Users/utente/documenti"]
  #   enabled: true
  #
  # - name: git
  #   transport: stdio
  #   command: ["uvx", "mcp-server-git", "--repository", "C:/progetti/mio-repo"]
  #   enabled: true
  #
  # - name: brave_search
  #   transport: sse
  #   url: "http://localhost:3001/sse"
  #   enabled: true
```

Il plugin `mcp_client` è **opt-in**: non è nella lista `plugins.enabled` di default.
Per attivarlo: aggiungere `"mcp_client"` a `plugins.enabled` e configurare almeno un server.

---

#### 11.2 — McpSession (`backend/services/mcp_session.py`)

**Ruolo**: gestisce il ciclo di vita di una singola connessione MCP. Non conosce il
plugin, il context OMNIA né il ToolRegistry. Si occupa solo di connettersi, listare
tool e fare dispatch delle chiamate.

```
McpSession
├── start()         — connette al server, invia initialize, chiama tools/list (popola cache)
├── stop()          — chiude la connessione, rilascia subprocess/HTTP client
├── get_tools()     — restituisce la lista ToolDefinition cached (sincrono, post-start)
├── call_tool()     — esegue tools/call e restituisce il testo del risultato
├── status          — CONNECTED | DISCONNECTED | ERROR (property sincrona)
└── server_name     — nome del server (da config.name)
```

Sketch implementativo:

```python
class McpSession:
    """Manages the lifecycle of a single MCP server connection.

    Uses the official `mcp` SDK for transport abstraction (stdio/SSE).
    The tool list is cached after start() to allow synchronous get_tools().

    Args:
        config: The server configuration (name, transport, command/url, env).
    """

    def __init__(self, config: McpServerConfig) -> None:
        self._config = config
        self._status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self._cached_tools: list[ToolDefinition] = []
        self._session: mcp.ClientSession | None = None
        self._exit_stack: contextlib.AsyncExitStack | None = None

    async def start(self) -> None:
        """Connect, initialize handshake, and cache the tool list.

        Raises:
            RuntimeError: If connection or initialization fails.
        """
        stack = contextlib.AsyncExitStack()
        try:
            if self._config.transport == "stdio":
                read, write = await stack.enter_async_context(
                    mcp.client.stdio.stdio_client(
                        mcp.StdioServerParameters(
                            command=self._config.command[0],
                            args=self._config.command[1:],
                            env={**os.environ, **self._config.env},
                        )
                    )
                )
            else:  # sse
                read, write = await stack.enter_async_context(
                    mcp.client.sse.sse_client(self._config.url)
                )
            session = await stack.enter_async_context(mcp.ClientSession(read, write))
            await session.initialize()
            tools_response = await session.list_tools()
            self._cached_tools = [
                ToolDefinition(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=tool.inputSchema or {"type": "object", "properties": {}},
                )
                for tool in tools_response.tools
            ]
            self._session = session
            self._exit_stack = stack
            self._status = ConnectionStatus.CONNECTED
        except Exception:
            await stack.aclose()
            self._status = ConnectionStatus.ERROR
            raise

    async def stop(self) -> None:
        """Disconnect and release all resources."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._session = None
        self._status = ConnectionStatus.DISCONNECTED
        self._cached_tools = []

    def get_tools(self) -> list[ToolDefinition]:
        """Return cached tool definitions (populated after start())."""
        return self._cached_tools

    async def call_tool(self, tool_name: str, args: dict) -> str:
        """Execute a tools/call request and return the string result.

        Args:
            tool_name: Original tool name (without mcp_ prefix).
            args: Tool arguments dict.

        Returns:
            String content of the tool result (text blocks joined by newline).

        Raises:
            RuntimeError: If the session is not connected.
        """
        if self._session is None or self._status != ConnectionStatus.CONNECTED:
            raise RuntimeError(
                f"MCP server '{self._config.name}' is not connected"
            )
        result = await self._session.call_tool(tool_name, args)
        return "\n".join(
            block.text for block in result.content if hasattr(block, "text")
        )

    @property
    def status(self) -> ConnectionStatus:
        return self._status

    @property
    def server_name(self) -> str:
        return self._config.name
```

**Nota sul ciclo di vita**: `start()` usa `AsyncExitStack` per gestire i context manager
del SDK MCP senza mantenere attivi blocchi `with`. `stop()` chiude lo stack, propagando
le chiusure al trasporto e al processo subprocess.

---

#### 11.3 — McpClientPlugin (`backend/plugins/mcp_client/plugin.py`)

**Ruolo**: plugin OMNIA che gestisce N sessioni MCP, aggrega i loro tool nel ToolRegistry
e fa dispatch delle esecuzioni alla sessione corretta.

```
McpClientPlugin
├── initialize(ctx)   — avvia tutte le sessioni enabled (crash-isolated per sessione)
├── cleanup()         — ferma tutte le sessioni ordinatamente
├── get_tools()       — aggrega ToolDefinition da tutte le sessioni CONNECTED
├── execute_tool()    — parsing prefisso → dispatch a McpSession.call_tool()
├── get_connection_status()  — CONNECTED se tutte ok, DEGRADED se alcune, ERROR se nessuna
└── get_status()      — dict {server_name: status} per health detail
```

```python
class McpClientPlugin(BasePlugin):
    """Bridges OMNIA to external MCP servers.

    At startup, connects to every enabled server in config.mcp.servers.
    Each server's tools are namespaced as mcp_{server_name}_{tool_name}
    and exposed via get_tools(), making them available to the LLM.
    """

    plugin_name = "mcp_client"
    plugin_version = "1.0.0"
    plugin_description = (
        "Bridges OMNIA to external MCP servers "
        "(filesystem, git, browser, search engine, …)"
    )

    def __init__(self) -> None:
        super().__init__()
        self._sessions: dict[str, McpSession] = {}

    async def initialize(self, ctx: AppContext) -> None:
        await super().initialize(ctx)
        for server_cfg in ctx.config.mcp.servers:
            if not server_cfg.enabled:
                continue
            session = McpSession(server_cfg)
            try:
                await session.start()
                self._sessions[server_cfg.name] = session
                self.logger.info(
                    "MCP '{}' connesso ({} tool)",
                    server_cfg.name,
                    len(session.get_tools()),
                )
                await ctx.event_bus.emit(
                    OmniaEvent.MCP_SERVER_CONNECTED, server=server_cfg.name,
                )
            except Exception as exc:
                self.logger.error("MCP '{}' fallito: {}", server_cfg.name, exc)
                await ctx.event_bus.emit(
                    OmniaEvent.MCP_SERVER_DISCONNECTED,
                    server=server_cfg.name,
                    reason=str(exc),
                )

    async def cleanup(self) -> None:
        for session in self._sessions.values():
            try:
                await session.stop()
            except Exception as exc:
                self.logger.warning(
                    "Errore chiusura MCP '{}': {}", session.server_name, exc,
                )
        self._sessions.clear()

    def get_tools(self) -> list[ToolDefinition]:
        tools: list[ToolDefinition] = []
        for server_name, session in self._sessions.items():
            if session.status != ConnectionStatus.CONNECTED:
                continue
            for tool in session.get_tools():
                tools.append(ToolDefinition(
                    name=f"mcp_{server_name}_{tool.name}",
                    description=f"[{server_name}] {tool.description}",
                    parameters=tool.parameters,
                ))
        return tools

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext,
    ) -> ToolResult:
        for server_name, session in self._sessions.items():
            prefix = f"mcp_{server_name}_"
            if tool_name.startswith(prefix):
                original = tool_name[len(prefix):]
                try:
                    content = await session.call_tool(original, args)
                    return ToolResult(success=True, content=content)
                except Exception as exc:
                    return ToolResult(success=False, error_message=str(exc))
        return ToolResult(
            success=False,
            error_message=f"Tool MCP non trovato: {tool_name}",
        )

    async def get_connection_status(self) -> ConnectionStatus:
        if not self._sessions:
            return ConnectionStatus.CONNECTED  # nessun server configurato ≠ errore
        connected = sum(
            1 for s in self._sessions.values()
            if s.status == ConnectionStatus.CONNECTED
        )
        if connected == len(self._sessions):
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.DEGRADED if connected > 0 else ConnectionStatus.ERROR

    async def get_status(self) -> dict[str, str]:
        """Return per-server connection status for health reporting."""
        return {name: s.status.value for name, s in self._sessions.items()}
```

`backend/plugins/mcp_client/__init__.py` — registrazione nel registry statico:

```python
from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.mcp_client.plugin import McpClientPlugin

PLUGIN_REGISTRY["mcp_client"] = McpClientPlugin
```

---

#### 11.4 — Tool Namespacing

| MCP Server | Tool originale | Nome in `get_tools()` | Nome visibile all'LLM (ToolRegistry) |
|---|---|---|---|
| `filesystem` | `read_file` | `mcp_filesystem_read_file` | `mcp_client_mcp_filesystem_read_file` |
| `filesystem` | `write_file` | `mcp_filesystem_write_file` | `mcp_client_mcp_filesystem_write_file` |
| `git` | `git_log` | `mcp_git_git_log` | `mcp_client_mcp_git_git_log` |
| `brave_search` | `brave_web_search` | `mcp_brave_search_brave_web_search` | `mcp_client_mcp_brave_search_brave_web_search` |
| `postgres` | `query` | `mcp_postgres_query` | `mcp_client_mcp_postgres_query` |

**Regola di parsing in `execute_tool`**: il `ToolRegistry` passa a `plugin.execute_tool()` il
`tool_def.name` originale (es. `mcp_filesystem_read_file`), non il nome completo con prefisso
esterno (`mcp_client_mcp_filesystem_read_file`). Il plugin itera le sessioni cercando il server
il cui `f"mcp_{name}_"` è un prefisso di `tool_name`, quindi estrae il nome MCP originale.

**Collisioni impossibili per construction**: il prefisso `mcp_` non è mai usato nei
plugin nativi OMNIA (tutti usano `{plugin_name}_` senza tale prefisso).

**Nome server con caratteri speciali**: il `name` deve essere `lowercase_snake_case`
(validato da `McpServerConfig`). Nomi come `brave-search` devono essere scritti come
`brave_search` nella config.

---

#### 11.5 — OmniaEvent (`backend/core/event_bus.py`)

Due nuovi eventi aggiunti all'enum `OmniaEvent`:

```python
MCP_SERVER_CONNECTED = "mcp.server.connected"
"""Emesso con server=str quando un server MCP si connette con successo."""

MCP_SERVER_DISCONNECTED = "mcp.server.disconnected"
"""Emesso con server=str, reason=str quando un server MCP fallisce o si disconnette."""
```

---

#### 11.6 — Dipendenza (`pyproject.toml`)

```toml
[project.dependencies]
mcp = ">=1.0"
```

Nessun'altra dipendenza. Il SDK `mcp` usa internamente:
- `httpx` — già presente nel progetto (per SSE transport)
- `anyio` — già presente come dipendenza transitiva di FastAPI (per subprocess stdio)

---

#### 11.7 — File Structure Fase 11

```
backend/
├── services/
│   └── mcp_session.py              ← McpSession (connessione singolo server MCP)
├── plugins/
│   └── mcp_client/
│       ├── __init__.py             ← PLUGIN_REGISTRY["mcp_client"] = McpClientPlugin
│       └── plugin.py              ← McpClientPlugin (aggregazione N sessioni)
├── core/
│   ├── config.py                  ← + McpServerConfig + McpConfig + OmniaConfig.mcp
│   └── event_bus.py               ← + MCP_SERVER_CONNECTED + MCP_SERVER_DISCONNECTED
└── tests/
    ├── test_mcp_session.py        ← unit test McpSession (mock mcp SDK)
    └── test_mcp_client_plugin.py  ← unit test McpClientPlugin (mock McpSession)

config/
└── default.yaml                   ← + sezione mcp.servers (lista vuota default)
```

Nessun file modificato nei layer esistenti: `app.py`, `protocols.py`, `context.py`,
`tool_registry.py`, `plugin_manager.py`, `routes/`, frontend.

---

#### 11.8 — Test Suite

**`backend/tests/test_mcp_session.py`**:
- `test_start_stdio_success`: mock `stdio_client` + `ClientSession` → `start()` → status CONNECTED, tool cache popolata
- `test_start_sse_success`: mock `sse_client` → stesso flusso con `url` come parametro
- `test_start_failure_sets_error_status`: eccezione in `session.initialize()` → status ERROR, `_cached_tools == []`
- `test_start_failure_closes_exit_stack`: eccezione → `AsyncExitStack.aclose()` chiamato (no resource leak)
- `test_call_tool_success`: sessione CONNECTED → `call_tool("read_file", {...})` → stringa risultato
- `test_call_tool_disconnected_raises`: sessione DISCONNECTED → `call_tool(...)` → `RuntimeError`
- `test_stop_resets_state`: `start()` → `stop()` → `status == DISCONNECTED`, `get_tools() == []`

**`backend/tests/test_mcp_client_plugin.py`**:
- `test_initialize_starts_all_enabled_sessions`: 2 server enabled + 1 disabled → 2 sessioni avviate
- `test_initialize_isolates_session_failure`: server A ok, server B crash → plugin inizializzato, A in `_sessions`, B escluso
- `test_initialize_emits_events`: server connesso → `MCP_SERVER_CONNECTED` emesso; server fallito → `MCP_SERVER_DISCONNECTED` emesso
- `test_get_tools_aggregates_from_connected`: 2 sessioni 3 tool ciascuna → 6 tool con prefisso `mcp_{server}_`
- `test_get_tools_skips_disconnected`: sessione con status ERROR → tool non inclusi
- `test_execute_tool_dispatches_to_correct_session`: `mcp_filesystem_read_file` → sessione `filesystem`
- `test_execute_tool_unknown_returns_failure`: tool senza prefisso valido → `ToolResult(success=False)`
- `test_get_connection_status_all_connected`: tutte le sessioni CONNECTED → `ConnectionStatus.CONNECTED`
- `test_get_connection_status_partial`: 1 su 2 CONNECTED → `ConnectionStatus.DEGRADED`
- `test_get_connection_status_none_connected`: zero sessioni CONNECTED → `ConnectionStatus.ERROR`
- `test_get_connection_status_no_servers`: `_sessions` vuoto → `ConnectionStatus.CONNECTED`
- `test_cleanup_stops_all_sessions`: `cleanup()` → `stop()` chiamato su ogni sessione

**Verifica no-regression** (pre-PR): tutta la suite esistente deve passare invariata.

---

#### 11.9 — Ordine di Implementazione

1. `McpServerConfig` + `McpConfig` in `config.py` + `default.yaml`
2. `OmniaEvent.MCP_SERVER_CONNECTED` + `MCP_SERVER_DISCONNECTED` in `event_bus.py`
3. `mcp >= 1.0` in `pyproject.toml` + `uv pip install -e ".[dev]"` ← dipendenza SDK necessaria prima di `mcp_session.py`
4. `McpSession` service (`backend/services/mcp_session.py`)
5. `McpClientPlugin` (`backend/plugins/mcp_client/__init__.py` + `plugin.py`)
6. Test suite completa
7. Aggiungere `"mcp_client"` a `plugins.enabled` in `default.yaml` + configurare almeno un server per il test manuale

---

#### 11.10 — Verifiche Fase 11

| Scenario | Comportamento atteso |
|---|---|
| `mcp.servers: []` (default) | Plugin si carica, `get_tools()` restituisce `[]`, `get_connection_status()` CONNECTED, zero impatto su test esistenti |
| Server stdio con NPX filesystem | Subprocess lanciato, tool listati, `mcp_client_mcp_filesystem_*` disponibili all'LLM |
| LLM chiama `mcp_client_mcp_filesystem_read_file` con path valido | Dispatch a `McpSession.call_tool("read_file", {...})` → contenuto file come `ToolResult` |
| LLM chiama tool con path fuori directory permessa | Il server MCP restituisce errore → `ToolResult(success=False, error_message=...)` → messaggio user-friendly |
| Server SSE non raggiungibile all'avvio | Status ERROR, evento `MCP_SERVER_DISCONNECTED` emesso, altri plugin e chat funzionanti |
| Un server crasha durante `initialize()` | Solo quel server escluso; altri server connessi normalmente; plugin inizializzato |
| Tool call verso sessione ERROR | `ToolResult(success=False)` con error_message, nessun crash plugin |
| `GET /api/plugins` | Plugin card `mcp_client` presente con status CONNECTED/DEGRADED/ERROR |
| `mcp_client` non in `plugins.enabled` | Plugin non caricato, zero tool MCP nel ToolRegistry, zero overhead |

---

---

### Fase 12 — CAD 3D Generativo + Documentazione MCP

> **Obiettivo**: permettere a OMNIA di generare modelli 3D da linguaggio naturale
> tramite [build123d](https://github.com/gumyr/build123d) (motore OCCT Python) in esecuzione
> nel container Docker `cad-agent`, visualizzare i modelli interattivamente con Three.js,
> e fornire all'LLM accesso alla documentazione tecnica (PDF/EPUB) tramite
> [ebook-mcp](https://github.com/onebirdrocks/ebook-mcp).
>
> Fase 12 = **due feature distinte**, architetture complementari, zero overlap:
> 1. **Documentazione** — puro config: `ebook-mcp` registrato come server MCP nel plugin
>    `mcp_client` esistente (Fase 11). Zero codice.
> 2. **CAD 3D** — nuovo plugin `cad_generator` (HTTP client verso Docker) + route proxy
>    `/api/cad/` + viewer Three.js nel frontend.

- [ ] 12.1 — Documentazione MCP (`ebook-mcp`) — config-only
- [ ] 12.2 — `CadGeneratorConfig` in `config.py` + `default.yaml`
- [ ] 12.3 — `CadAgentClient` (`backend/plugins/cad_generator/client.py`)
- [ ] 12.4 — `CadGeneratorPlugin` (2 tool: `cad_generate` + `cad_list_models`)
- [ ] 12.5 — REST proxy `backend/api/routes/cad.py` (`/api/cad/`)
- [ ] 12.6 — Frontend: `CADViewer.vue` (Three.js + STLLoader)
- [ ] 12.7 — Frontend: estensione `ToolExecutionIndicator.vue` + `types/chat.ts`
- [ ] 12.8 — System prompt update (`config/system_prompt.md`)
- [ ] 12.9 — Test suite (3 file, 20+ test case)

---

#### 12.0 — Analisi Vincoli e Scelte Architetturali

**Perché `cad-agent` via HTTP e non via MCP:**

`cad-agent` (Svetlana-DAO-LLC/cad-agent) espone sia un'API HTTP REST (FastAPI, porta
configurabile) sia un'interfaccia MCP stdio. Usare il plugin `mcp_client` esistente per
accedere ai tool CAD tramite MCP sarebbe tecnicamente possibile, ma presenterrebbe un
problema strutturale: i tool MCP restituiscono solo blocchi di testo. Per i modelli 3D
serve trasmettere un riferimento al file binario (STL), non il file stesso in base64 (troppo
grande per la pipeline WebSocket). La soluzione corretta è un plugin dedicato che:

1. Chiama il cad-agent HTTP API per creare il modello e fare l'export
2. Salva il file STL localmente (directory temporanea)
3. Restituisce un `ToolResult` con `content_type = "application/vnd.omnia.cad-model+json"`
   e un JSON payload con l'URL di download (`/api/cad/models/{name}/export`)
4. Il frontend carica il file STL direttamente via HTTP nella route proxy e lo renderizza
   con Three.js — nessun trasferimento binario via WebSocket

Questo mechanism `content_type` è già completamente implementato in `_tool_loop.py` e
nel frontend (`ToolExecutionIndicator.vue`) — Phase 5 lo ha introdotto per gli screenshot.
Zero modifiche alla pipeline esistente.

**Perché `ebook-mcp` via plugin `mcp_client` esistente (puro config):**

`ebook-mcp` è un server MCP stdio puro: legge PDF/EPUB e restituisce testo Markdown.
Le sue risposte sono sempre testo — esattamente il caso d'uso per cui il plugin `mcp_client`
è stato costruito in Fase 11. Aggiungere `ebook-mcp` a `config.mcp.servers` è tutto quello
che serve. Zero codice.

**Perché STL e non GLB:**

`cad-agent` esporta nativamente in STL, STEP e 3MF. Three.js supporta STLLoader
(disponibile in `three/examples/jsm/loaders/STLLoader`). Aggiungere la conversione
STL → GLB richiederebbe `trimesh` o `open3d` — dipendenze pesanti e non giustificate per v1.
L'STL è un subset del dominio (solo mesh, nessun materiale), sufficiente per la
visualizzazione 3D interattiva richiesta.

**Perché un docker health-check non-bloccante:**

Docker non è sempre disponibile su ogni macchina (es. sviluppo su macchine leggere, CI).
`CadGeneratorPlugin.initialize()` chiama `health_check()` all'avvio: se cad-agent non
risponde, il plugin si segna come `DISCONNECTED` (non `ERROR`) e i tool restituiscono
un messaggio chiaro con istruzioni per avviare Docker — identico al pattern adottato
dai plugin STT/TTS con fallback graceful.

**Nessuna modifica a layer esistenti (solo aggiunte pure):**

| Layer | Modificato | Motivo |
|---|---|---|
| `_tool_loop.py` | NO | `content_type` già propagato a WS per tutti i tool result |
| `chat.py` | NO | nessuna dispatch speciale necessaria |
| `plugin_models.py` | NO | `ToolResult.content_type` già esiste |
| `protocols.py` | NO | nessun nuovo service da iniettare in `AppContext` |
| `context.py` | NO | plug-in gestito da `PluginManager` come tutti gli altri |
| `app.py` | NO | plugin registrato nel `PLUGIN_REGISTRY` statico |
| `plugin_manager.py` | NO | nessuna modifica |

---

#### 12.1 — Documentazione MCP (`ebook-mcp`) — Config-Only

`ebook-mcp` (onebirdrocks/ebook-mcp, Apache 2.0, installabile via `uvx`) è un server MCP
stdio che legge PDF e EPUB e ne espone il contenuto come tool. Aggiungere un'entry a
`config/default.yaml` nella sezione `mcp.servers` (introdotta in Fase 11) è l'unica
azione necessaria.

**Tool esposti all'LLM una volta configurato:**

| Tool MCP | Nome visibile all'LLM (via ToolRegistry) |
|---|---|
| `get_all_epub_files` | `mcp_client_mcp_build123d_docs_get_all_epub_files` |
| `get_metadata` | `mcp_client_mcp_build123d_docs_get_metadata` |
| `get_toc` | `mcp_client_mcp_build123d_docs_get_toc` |
| `get_chapter_markdown` | `mcp_client_mcp_build123d_docs_get_chapter_markdown` |
| `get_all_pdf_files` | `mcp_client_mcp_build123d_docs_get_all_pdf_files` |
| `get_pdf_metadata` | `mcp_client_mcp_build123d_docs_get_pdf_metadata` |
| `get_pdf_toc` | `mcp_client_mcp_build123d_docs_get_pdf_toc` |
| `get_pdf_page_text` | `mcp_client_mcp_build123d_docs_get_pdf_page_text` |
| `get_pdf_page_markdown` | `mcp_client_mcp_build123d_docs_get_pdf_page_markdown` |
| `get_pdf_chapter_content` | `mcp_client_mcp_build123d_docs_get_pdf_chapter_content` |

**Aggiunta a `config/default.yaml`** (nella sezione `mcp.servers` esistente):

```yaml
mcp:
  servers:
    # ... server esistenti ...
    #
    # - name: build123d_docs
    #   transport: stdio
    #   # Installa ebook-mcp con: uvx ebook-mcp
    #   # Posiziona i PDF/EPUB in una cartella (es. models/docs/)
    #   command: ["uvx", "ebook-mcp", "--folder", "C:/Users/zagor/Desktop/omnia/models/docs"]
    #   enabled: true
    #   # Usa `get_toc` su ogni documento prima di leggere capitoli specifici con get_chapter_markdown
```

**Configurazione utente** (passo manuale one-shot):

```powershell
# 1. Installa ebook-mcp (verifica che uvx/uv sia disponibile — già usato dal progetto)
uvx ebook-mcp --version  # verifica funzionamento

# 2. Crea la cartella documenti e posiziona i PDF/EPUB
New-Item -ItemType Directory -Path "C:\Users\zagor\Desktop\omnia\models\docs" -Force
# Copiare qui: build123d docs, CadQuery docs, ecc.

# 3. Decommentare la voce nel default.yaml e aggiornare il path
# 4. Aggiungere "mcp_client" a plugins.enabled se non già presente
```

**Dipendenze:** `ebook-mcp` richiede `uvx` (già disponibile) — zero nuove dipendenze nel
`pyproject.toml` di OMNIA. L'installazione avviene nell'ambiente isolato di `uvx`.

---

#### 12.2 — CadGeneratorConfig (`backend/core/config.py`)

Nuova classe aggiunta in `config.py`, dopo `McpConfig`:

```python
class CadGeneratorConfig(BaseSettings):
    """CAD generator plugin configuration — connects to the cad-agent Docker container."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_CAD_GENERATOR__")

    enabled: bool = False
    """Abilita il plugin. Richiede Docker + cad-agent in esecuzione."""

    docker_url: str = "http://localhost:8080"
    """URL base del container cad-agent. Deve puntare a un HTTP endpoint locale."""

    request_timeout_s: int = 60
    """Timeout per le richieste al cad-agent (la generazione CAD può richiedere tempo)."""

    default_export_format: Literal["stl", "step", "3mf"] = "stl"
    """Formato di export default. STL: mesh-only (Three.js STLLoader). STEP/3MF: per CAD avanzato."""

    max_model_size_mb: int = 50
    """Dimensione massima accettata per i file STL/STEP (protezione da modelli enormi)."""

    model_ttl_hours: int = 24
    """TTL stimato dei modelli nel cad-agent (usato solo a scopo documentativo — il cleanup
    è responsabilità del container cad-agent stesso)."""
```

Aggiunta a `OmniaConfig` (dopo `mcp`):

```python
cad_generator: CadGeneratorConfig = Field(default_factory=CadGeneratorConfig)
```

Aggiunta a `config/default.yaml` (in fondo, dopo la sezione `mcp:`):

```yaml
# ──────────────────────────────────────────────────
# Fase 12 — CAD 3D Generativo
# ──────────────────────────────────────────────────
cad_generator:
  enabled: false
  # Avviare il container cad-agent prima di abilitare il plugin:
  #   docker pull ghcr.io/svetlana-dao-llc/cad-agent:latest
  #   docker run -d -p 8080:8000 ghcr.io/svetlana-dao-llc/cad-agent:latest
  docker_url: "http://localhost:8080"
  request_timeout_s: 60
  default_export_format: "stl"
  max_model_size_mb: 50

# In plugins.enabled, aggiungere (commentato per default-off):
#   - cad_generator  # abilitare con cad_generator.enabled: true
```

**SSRF protection**: `docker_url` deve essere un URL locale. La validazione è enforced in
`CadAgentClient.__init__()` tramite la funzione `validate_url_ssrf()` di `http_security.py`
— identica al pattern adottato da `WeatherPlugin`, `NewsPlugin` e `WebSearchPlugin`.

---

#### 12.3 — CadAgentClient (`backend/plugins/cad_generator/client.py`)

**Ruolo**: client HTTP asincrono verso l'API REST del container cad-agent.
Non conosce il plugin, il context OMNIA né il ToolRegistry — solo I/O HTTP.

```python
"""CAD Agent HTTP client.

Wraps the cad-agent Docker REST API with typed async methods.
See https://github.com/Svetlana-DAO-LLC/cad-agent for API docs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from loguru import logger

from backend.core.config import CadGeneratorConfig
from backend.core.http_security import validate_url_ssrf


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Lightweight model descriptor returned by list_models()."""

    name: str
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Binary export result from the cad-agent."""

    model_name: str
    format: str          # "stl" | "step" | "3mf"
    content_bytes: bytes
    size_bytes: int


class CadAgentClient:
    """Async HTTP client for the cad-agent Docker container REST API.

    The client holds a persistent httpx.AsyncClient to avoid per-request
    connection overhead. Call close() to release it.

    Args:
        config: CadGeneratorConfig with docker_url, timeouts, etc.

    Raises:
        RuntimeError: On construction if docker_url fails SSRF validation.
    """

    def __init__(self, config: CadGeneratorConfig) -> None:
        # Validate SSRF guard: docker_url must be localhost / RFC-1918
        # sse transport urls point to localhost; same check as WeatherPlugin
        validate_url_ssrf(config.docker_url)
        self._base_url = config.docker_url.rstrip("/")
        self._timeout = config.request_timeout_s
        self._max_bytes = config.max_model_size_mb * 1_048_576
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout),
        )

    async def health_check(self) -> bool:
        """Return True if the cad-agent container is reachable.

        Uses a lightweight GET /health or GET / probe. Does not raise.
        """
        try:
            r = await self._client.get("/health", timeout=5.0)
            return r.status_code < 500
        except Exception:
            return False

    async def create_model(self, build123d_code: str, model_name: str) -> str:
        """Execute build123d code on the cad-agent and create a named model.

        Args:
            build123d_code: Valid Python code using the build123d library.
            model_name: Unique identifier for the model (alphanumeric + underscore).

        Returns:
            The model name as confirmed by the server (may be sanitised).

        Raises:
            httpx.HTTPStatusError: If cad-agent returns a 4xx/5xx status.
            RuntimeError: If the response JSON is missing expected fields.
        """
        payload = {"name": model_name, "code": build123d_code}
        r = await self._client.post("/model/create", json=payload)
        r.raise_for_status()
        data = r.json()
        return data.get("name", model_name)

    async def export_model(
        self,
        model_name: str,
        fmt: str = "stl",
    ) -> ExportResult:
        """Export a previously created model as a binary file.

        Args:
            model_name: Name of the model to export (must exist on cad-agent).
            fmt: Export format: "stl" | "step" | "3mf".

        Returns:
            ExportResult with binary content_bytes.

        Raises:
            httpx.HTTPStatusError: On HTTP error from cad-agent.
            ValueError: If the exported file exceeds max_model_size_mb.
        """
        r = await self._client.post(
            "/export",
            json={"name": model_name, "format": fmt},
        )
        r.raise_for_status()
        raw = r.content
        if len(raw) > self._max_bytes:
            raise ValueError(
                f"Exported model '{model_name}' exceeds max size "
                f"({len(raw) // 1_048_576} MB > {self._max_bytes // 1_048_576} MB)"
            )
        logger.debug(
            "CAD export '{}' ({}) — {} bytes", model_name, fmt, len(raw)
        )
        return ExportResult(
            model_name=model_name,
            format=fmt,
            content_bytes=raw,
            size_bytes=len(raw),
        )

    async def list_models(self) -> list[ModelInfo]:
        """List all models currently stored in the cad-agent container.

        Returns:
            List of ModelInfo. Returns empty list if none exist.
        """
        r = await self._client.get("/model/list")
        r.raise_for_status()
        data = r.json()
        models = data if isinstance(data, list) else data.get("models", [])
        return [
            ModelInfo(
                name=m.get("name", str(m)) if isinstance(m, dict) else str(m),
                created_at=m.get("created_at") if isinstance(m, dict) else None,
            )
            for m in models
        ]

    async def close(self) -> None:
        """Release the underlying httpx.AsyncClient connection pool."""
        await self._client.aclose()
```

**Nota sicurezza `validate_url_ssrf`**: questa funzione è in `backend/core/http_security.py`
(introdotta in Fase 7.3). Blocca URL che puntano a IP privati RFC-1918, loopback remoto
e link-local. **Eccezione**: `http://localhost` e `http://127.0.0.1` sono permessi perché
`CadGeneratorConfig.docker_url` deve per forza essere locale (il container Docker gira
sulla stessa macchina). La validazione blocca comunque qualsiasi IP non locale nel caso
l'utente configuri un URL di rete interna remoto (es. Docker su NAS) — coerente con il
principio di sicurezza del progetto.

**Nota `validate_url_ssrf` per localhost**: verificare che la funzione permetta
`localhost` / `127.0.0.1` nella sua logica (attualmente usata da weather e news per
URL remoti pubblici). Se blocca anche localhost, aggiungere il parametro opzionale
`allow_localhost: bool = False` con default retrocompatibile.

---

#### 12.4 — CadGeneratorPlugin (`backend/plugins/cad_generator/plugin.py`)

**Ruolo**: plugin OMNIA che espone 2 tool LLM per generare modelli 3D e listarli.
Gestisce il ciclo di vita del `CadAgentClient` e produce `ToolResult` con
`content_type = "application/vnd.omnia.cad-model+json"` per i modelli generati.

```
backend/plugins/cad_generator/
├── __init__.py     ← import + PLUGIN_REGISTRY["cad_generator"] = CadGeneratorPlugin
├── plugin.py       ← CadGeneratorPlugin(BasePlugin) — 2 tool
└── client.py       ← CadAgentClient — HTTP I/O verso Docker
```

**`__init__.py`** — pattern identico a tutti gli altri plugin:

```python
"""O.M.N.I.A. — CAD Generator plugin package.

Importing this module registers CadGeneratorPlugin in the static PLUGIN_REGISTRY.
Requires the cad-agent Docker container running on cad_generator.docker_url.
See https://github.com/Svetlana-DAO-LLC/cad-agent for setup instructions.
"""
from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.cad_generator.plugin import CadGeneratorPlugin  # noqa: F401

PLUGIN_REGISTRY["cad_generator"] = CadGeneratorPlugin
```

**`plugin.py`** — `CadGeneratorPlugin(BasePlugin)`:

```python
class CadGeneratorPlugin(BasePlugin):
    """Generates 3D CAD models from build123d Python code via the cad-agent Docker API.

    Uses the cad-agent HTTP REST API (not MCP) to: execute build123d code on the
    server, export the resulting model as STL, and return a ToolResult with
    content_type='application/vnd.omnia.cad-model+json' so the Electron frontend
    can render it with Three.js via the /api/cad/ proxy route.
    """

    plugin_name = "cad_generator"
    plugin_version = "1.0.0"
    plugin_description = (
        "Genera modelli 3D da codice build123d tramite container Docker cad-agent. "
        "I modelli vengono visualizzati interattivamente nel frontend via Three.js."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 20

    def __init__(self) -> None:
        super().__init__()
        self._client: CadAgentClient | None = None

    async def initialize(self, ctx: AppContext) -> None:
        """Start the CadAgentClient and check Docker availability."""
        await super().initialize(ctx)
        cfg = ctx.config.cad_generator
        self._client = CadAgentClient(cfg)
        reachable = await self._client.health_check()
        if not reachable:
            logger.warning(
                "CadGeneratorPlugin: cad-agent non raggiungibile a {}. "
                "I tool CAD restituiranno un errore descrittivo finché Docker non avvia il container.",
                cfg.docker_url,
            )
            # Nota: NON impostiamo status=ERROR — il plugin carica correttamente.
            # La connessione viene controllata ad ogni tool call.

    async def cleanup(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
        await super().cleanup()

    async def get_connection_status(self) -> ConnectionStatus:
        if self._client is None:
            return ConnectionStatus.DISCONNECTED
        healthy = await self._client.health_check()
        return ConnectionStatus.CONNECTED if healthy else ConnectionStatus.DISCONNECTED
```

**Tool definitions** (restituite da `get_tools()`):

| Tool | risk_level | requires_confirmation | timeout_ms | Descrizione |
|---|---|---|---|---|
| `cad_generate` | `safe` | `False` | 90000 | Genera un modello 3D da codice build123d, visualizzabile nel frontend |
| `cad_list_models` | `safe` | `False` | 10000 | Elenca i modelli correntemente nel container cad-agent |

**Schema tool `cad_generate`**:

```json
{
  "type": "object",
  "properties": {
    "build123d_code": {
      "type": "string",
      "description": "Codice Python valido che usa la libreria build123d per creare un solido 3D. Deve terminare con una variabile di tipo Shape/Compound assegnata a 'result' (es. `result = Box(10, 20, 30)`).",
      "maxLength": 8000
    },
    "model_name": {
      "type": "string",
      "description": "Nome identificativo del modello (solo lettere, numeri, underscore). Se omesso, viene generato automaticamente da timestamp.",
      "pattern": "^[a-zA-Z0-9_]{1,64}$"
    },
    "export_format": {
      "type": "string",
      "enum": ["stl", "step", "3mf"],
      "description": "Formato di export. Usa 'stl' per visualizzazione 3D nel browser (default). Usa 'step' per modifica in CAD tradizionale.",
      "default": "stl"
    }
  },
  "required": ["build123d_code"]
}
```

**Implementazione `execute_tool("cad_generate", args, ctx)`**:

```python
async def _execute_cad_generate(self, args: dict, context: ExecutionContext) -> ToolResult:
    if self._client is None:
        return ToolResult(success=False, error_message="CadGeneratorPlugin non inizializzato.")

    code: str = args["build123d_code"]
    fmt: str = args.get("export_format", self._ctx.config.cad_generator.default_export_format)
    # Genera nome univoco se non fornito
    raw_name = args.get("model_name") or f"model_{context.execution_id[:8]}"
    # Sanitizza il nome (il container potrebbe rifiutare caratteri speciali)
    name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name)[:64]

    # 1. Verifica connessione Docker (non bloccante: prima call after init può riuscire)
    if not await self._client.health_check():
        return ToolResult(
            success=False,
            error_message=(
                f"cad-agent non raggiungibile a {self._ctx.config.cad_generator.docker_url}. "
                "Assicurarsi che Docker sia avviato e il container cad-agent in esecuzione:\n"
                "  docker run -d -p 8080:8000 ghcr.io/svetlana-dao-llc/cad-agent:latest"
            ),
        )

    # 2. Crea modello sul container
    try:
        confirmed_name = await self._client.create_model(code, name)
    except httpx.HTTPStatusError as exc:
        # Errore build123d (codice non compilabile, eccezione Python, ecc.)
        error_detail = exc.response.text[:500] if exc.response else str(exc)
        return ToolResult(
            success=False,
            error_message=f"Errore creazione modello: {error_detail}",
        )

    # 3. Export (restituisce solo URL — il file binario viene servito da /api/cad/)
    export_url = f"/api/cad/models/{confirmed_name}/export?format={fmt}"
    payload = {
        "model_name": confirmed_name,
        "export_url": export_url,
        "format": fmt,
    }

    return ToolResult(
        success=True,
        content=json.dumps(payload),
        content_type="application/vnd.omnia.cad-model+json",
    )
```

**Perché l'URL e non i bytes**: il tool restituisce solo il JSON con l'URL al file —
il front-end carica il binario STL direttamente dalla route proxy `/api/cad/` tramite
una normale richiesta HTTP GET. Questo evita di passare file potenzialmente da decine
di MB attraverso il WebSocket, mantenendo il canale WebSocket per soli messaggi di
controllo leggeri.

**Schema tool `cad_list_models`** (`parameters: {"type": "object", "properties": {}}`):

Restituisce JSON array: `[{"name": "...", "created_at": "ISO"?}, ...]`.

---

#### 12.5 — REST Proxy `/api/cad/` (`backend/api/routes/cad.py`)

**Ruolo**: espone il file binario STL/STEP generato dal container cad-agent al frontend
Electron. Il proxy è necessario perché il container Docker gira su una porta interna
non direttamente accessibile dal browser web nel renderer Electron senza CSP issues.

Router con prefix e tag coerenti (pattern `tasks.py`, `memory.py`):

```python
router = APIRouter(prefix="/cad", tags=["cad"])
```

**Endpoint esposti:**

```
GET  /api/cad/models/{model_name}/export    — stream file STL/STEP dal cad-agent
GET  /api/cad/models                        — lista modelli dal cad-agent
GET  /api/cad/health                        — health check del container Docker
```

**Implementazione `/api/cad/models/{model_name}/export`**:

```python
@router.get("/models/{model_name}/export")
async def export_model(
    model_name: str,
    format: Literal["stl", "step", "3mf"] = "stl",
    request: Request = None,
) -> StreamingResponse:
    """Proxy the CAD model binary export from the cad-agent Docker container.

    Args:
        model_name: CAD model identifier (alphanumeric + underscore only).
        format: Export format (default: stl).

    Returns:
        StreamingResponse with the binary model file.

    Raises:
        HTTPException 404: If model not found on cad-agent.
        HTTPException 503: If cad-agent container is unreachable.
    """
    # Input validation anti-path-traversal
    if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", model_name):
        raise HTTPException(status_code=400, detail="Nome modello non valido.")

    ctx: AppContext = request.app.state.context
    plugin: CadGeneratorPlugin | None = (
        ctx.plugin_manager.get_plugin("cad_generator")
        if ctx.plugin_manager else None
    )
    if plugin is None or plugin._client is None:
        raise HTTPException(
            status_code=503, detail="Plugin cad_generator non attivo."
        )

    try:
        result = await plugin._client.export_model(model_name, format)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Modello '{model_name}' non trovato.")
        raise HTTPException(status_code=502, detail="Errore dal container cad-agent.")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"cad-agent non raggiungibile: {exc}")

    content_type_map = {
        "stl": "model/stl",
        "step": "application/octet-stream",
        "3mf": "model/3mf",
    }
    media_type = content_type_map.get(format, "application/octet-stream")
    filename = f"{model_name}.{format}"

    return StreamingResponse(
        content=iter([result.content_bytes]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

**Registrazione in `backend/api/routes/__init__.py`**:

```python
from backend.api.routes import audit, cad, calendar, chat, config, events, models, plugins, settings, tasks, voice

router.include_router(cad.router)  # /api/cad/*
```

**Sicurezza**:

- Validazione `model_name` con regex `[a-zA-Z0-9_]{1,64}` — previene path traversal
  (`../../etc/passwd`) e command injection
- Il proxy chiama solo `config.cad_generator.docker_url` (configurato dall'amministratore
  di sistema, non dall'utente), quindi non è possibile SSRF arbitrario
- Nessuna autenticazione richiesta per v1 (OMNIA gira in locale — coerente con il resto delle API)

---

#### 12.6 — Frontend: `CADViewer.vue` (Three.js + STLLoader)

**Dipendenze da aggiungere a `frontend/package.json`**:

```bash
cd frontend
npm install three
npm install --save-dev @types/three
```

**Componente `frontend/src/renderer/src/components/chat/CADViewer.vue`**:

Il componente è lazy-loaded (`defineAsyncComponent`) per non aumentare il bundle iniziale
dell'app (Three.js pesa ~600KB gzip).

```vue
<script setup lang="ts">
/**
 * Interactive 3D CAD model viewer using Three.js + STLLoader.
 *
 * Renders a CAD model exported as STL from the cad-agent Docker container.
 * Supports: orbit controls (drag/scroll/right-drag), zoom, auto-rotate toggle,
 * wireframe toggle, and model download.
 *
 * Props:
 *   modelUrl - Relative URL to the STL file (e.g. /api/cad/models/xxx/export?format=stl)
 *   modelName - Display name for the model (used in download filename)
 */
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as THREE from 'three'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

const props = defineProps<{
  modelUrl: string
  modelName?: string
}>()

const containerRef = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const wireframe = ref(false)
const autoRotate = ref(false)

let renderer: THREE.WebGLRenderer | null = null
let frameId: number | null = null
let controls: InstanceType<typeof OrbitControls> | null = null
let mesh: THREE.Mesh | null = null

async function initScene(): Promise<void> {
  const container = containerRef.value
  if (!container) return

  const w = container.clientWidth
  const h = container.clientHeight || 320

  // Scene
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x1a1a2e)

  // Camera
  const camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 10000)
  camera.position.set(0, 0, 200)

  // Lighting
  const ambient = new THREE.AmbientLight(0xffffff, 0.6)
  scene.add(ambient)
  const dir = new THREE.DirectionalLight(0xffffff, 0.8)
  dir.position.set(1, 2, 3)
  scene.add(dir)

  // Renderer
  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(w, h)
  renderer.setPixelRatio(window.devicePixelRatio)
  container.appendChild(renderer.domElement)

  // Controls
  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.05
  controls.autoRotate = autoRotate.value

  // Load STL
  const loader = new STLLoader()
  try {
    const geometry = await new Promise<THREE.BufferGeometry>((resolve, reject) => {
      loader.load(props.modelUrl, resolve, undefined, reject)
    })
    geometry.computeVertexNormals()
    geometry.center()

    const material = new THREE.MeshPhongMaterial({
      color: 0x4fc3f7,
      specular: 0x111111,
      shininess: 80,
      wireframe: wireframe.value,
    })
    mesh = new THREE.Mesh(geometry, material)

    // Auto-fit camera to bounding box
    const box = new THREE.Box3().setFromObject(mesh)
    const size = box.getSize(new THREE.Vector3()).length()
    camera.position.set(0, 0, size * 1.5)
    camera.far = size * 10
    camera.updateProjectionMatrix()
    controls.target.set(0, 0, 0)
    controls.update()

    scene.add(mesh)
    loading.value = false

    // Render loop
    const animate = (): void => {
      frameId = requestAnimationFrame(animate)
      controls!.autoRotate = autoRotate.value
      controls!.update()
      renderer!.render(scene, camera)
    }
    animate()
  } catch (err) {
    error.value = `Impossibile caricare il modello: ${err}`
    loading.value = false
  }

  // Resize observer
  const resizeObserver = new ResizeObserver(() => {
    if (!container || !renderer || !camera) return
    const nw = container.clientWidth
    const nh = container.clientHeight || 320
    camera.aspect = nw / nh
    camera.updateProjectionMatrix()
    renderer.setSize(nw, nh)
  })
  resizeObserver.observe(container)
}

function toggleWireframe(): void {
  wireframe.value = !wireframe.value
  if (mesh) (mesh.material as THREE.MeshPhongMaterial).wireframe = wireframe.value
}

function download(): void {
  const link = document.createElement('a')
  link.href = props.modelUrl
  link.download = `${props.modelName ?? 'model'}.stl`
  link.click()
}

function resetCamera(): void {
  controls?.reset()
}

onMounted(initScene)

onUnmounted(() => {
  if (frameId !== null) cancelAnimationFrame(frameId)
  renderer?.dispose()
  controls?.dispose()
})
</script>

<template>
  <div class="cad-viewer-wrapper">
    <div class="cad-viewer-toolbar">
      <span class="cad-viewer-title">
        🧊 {{ modelName ?? 'Modello 3D' }}
      </span>
      <div class="cad-viewer-actions">
        <button @click="autoRotate = !autoRotate" :class="{ active: autoRotate }" title="Auto-rotazione">⟳</button>
        <button @click="toggleWireframe" :class="{ active: wireframe }" title="Wireframe">⬡</button>
        <button @click="resetCamera" title="Reset vista">⌖</button>
        <button @click="download" title="Scarica STL">⬇</button>
      </div>
    </div>
    <div ref="containerRef" class="cad-viewer-canvas" :style="{ height: '360px' }">
      <div v-if="loading" class="cad-viewer-overlay">Caricamento modello 3D…</div>
      <div v-if="error" class="cad-viewer-overlay cad-viewer-error">{{ error }}</div>
    </div>
  </div>
</template>

<style scoped>
.cad-viewer-wrapper {
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(79, 195, 247, 0.2);
  background: #1a1a2e;
  margin: 8px 0;
}
.cad-viewer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.05);
  font-size: 13px;
  color: #b0bec5;
}
.cad-viewer-title { font-weight: 500; color: #4fc3f7; }
.cad-viewer-actions { display: flex; gap: 8px; }
.cad-viewer-actions button {
  background: none;
  border: 1px solid rgba(255,255,255,0.15);
  color: #b0bec5;
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
}
.cad-viewer-actions button:hover { border-color: #4fc3f7; color: #4fc3f7; }
.cad-viewer-actions button.active { border-color: #4fc3f7; color: #4fc3f7; background: rgba(79,195,247,0.1); }
.cad-viewer-canvas { position: relative; width: 100%; }
.cad-viewer-overlay {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  color: #b0bec5; font-size: 14px; background: rgba(26, 26, 46, 0.8);
}
.cad-viewer-error { color: #ef5350; }
</style>
```

**Lazy loading in `ToolExecutionIndicator.vue`** — usando il pattern `defineAsyncComponent`
già adottato nel progetto per i plugin UI:

```typescript
// In ToolExecutionIndicator.vue <script setup>
import { defineAsyncComponent } from 'vue'

const CADViewer = defineAsyncComponent(
  () => import('./CADViewer.vue')
)
```

---

#### 12.7 — Frontend: Estensione `ToolExecutionIndicator.vue` + `types/chat.ts`

**`frontend/src/renderer/src/types/chat.ts`** — aggiunta dell'interfaccia `CadModelPayload`:

```typescript
/**
 * Payload JSON del ToolResult con content_type='application/vnd.omnia.cad-model+json'.
 * Generato da CadGeneratorPlugin.cad_generate().
 */
export interface CadModelPayload {
  model_name: string
  /** URL relativo della route proxy: /api/cad/models/{name}/export?format=stl */
  export_url: string
  /** Formato di export: "stl" | "step" | "3mf" */
  format: string
}
```

**`frontend/src/renderer/src/components/chat/ToolExecutionIndicator.vue`** — aggiunta del
caso `application/vnd.omnia.cad-model+json` nel template di rendering del risultato. Questo
viene aggiunto in parallelo alla gestione `image/*` già presente:

La gestione nel componente segue il pattern esistente:

```typescript
// Nella sezione <script setup> — helper per parsare e validare il payload
function parseCadPayload(result: string): CadModelPayload | null {
  try {
    const parsed = JSON.parse(result) as CadModelPayload
    if (typeof parsed.model_name === 'string' && typeof parsed.export_url === 'string') {
      return parsed
    }
    return null
  } catch {
    return null
  }
}
```

Nel `<template>`, nel blocco che renderizza il risultato per ogni `exec in executions`,
aggiungere il caso CAD model accanto al caso image esistente:

```vue
<!-- caso immagini (già esistente) -->
<img
  v-if="exec.result && exec.contentType?.startsWith('image/')"
  :src="`data:${exec.contentType};base64,${exec.result}`"
  class="tool-result-image"
/>
<!-- caso modello 3D CAD (aggiunto in Fase 12) -->
<template v-else-if="exec.contentType === 'application/vnd.omnia.cad-model+json' && exec.result">
  <CADViewer
    :model-url="parseCadPayload(exec.result)?.export_url ?? ''"
    :model-name="parseCadPayload(exec.result)?.model_name"
  />
</template>
```

**Nessuna modifica a:**

- `useChat.ts` — già passa `content_type` a `store.completeToolExecution()` senza dispatch speciale
- `chat.ts` Pinia store — già memorizza `contentType?: string` in `ToolExecution`
- `ws.ts` WebSocket manager — invariato
- `MessageBubble.vue` — i tool result nelle conversazioni caricate da DB non hanno `contentType`
  (non persistito in DB) → nessun `CADViewer` in storico (comportamento accettabile per v1,
  coerente con screenshot che stessa limitazione presentano)

---

#### 12.8 — System Prompt Update (`config/system_prompt.md`)

Aggiungere una sezione `cad_generator` alla sezione `tools`:

```yaml
cad_generator:
  description: >
    Genera modelli 3D da linguaggio naturale usando build123d (Python, OCCT-based).
    Il modello viene automaticamente visualizzato nel frontend con Three.js.
  rules:
    - usa SEMPRE cad_generate() per creare un modello quando l'utente chiede un oggetto fisico
      da stampare in 3D, visualizzare o esportare in CAD
    - il parametro build123d_code deve essere Python valido che usa la libreria build123d
    - assegna il risultato finale alla variabile 'result' (es. `result = Box(10, 20, 30)`)
    - usa model_name descrittivo e in inglese (es. "tennis_handle", "bracket_v1")
    - NON usare 'stl' per modelli che l'utente vuole modificare in CAD: usa 'step' invece
    - se build123d_code genera un errore, correggilo e riprova con cad_generate()
    - usa cad_list_models() per controllare i modelli già generati in sessione
    - coordinate: build123d usa mm per default; crea solo geometrie positive (no z negativo)
  build123d_patterns: |
    from build123d import *
    # Solido semplice:
    result = Box(larghezza_mm, altezza_mm, profondita_mm)
    # Rivoluzione (es. manico cilindrico):
    with BuildPart() as p:
        with BuildSketch(Plane.XZ):
            RectangleRounded(5, 120, 2)
        revolve(axis=Axis.Z)
    result = p.part
    # L-profile:
    result = extrude(RectangleRounded(50, 30, 2), amount=100) - extrude(RectangleRounded(40, 20, 2), amount=110)

documentation_access:
  description: >
    Accesso in lettura a documenti PDF/EPUB tramite server MCP ebook-mcp (se configurato).
    Usare per consultare documentazione build123d, CadQuery, o qualsiasi altro manuale tecnico.
  rules:
    - usa get_toc() per ottenere la struttura del documento prima di leggere capitoli specifici
    - usa get_chapter_markdown() per leggere capitoli specifici — evita di leggere tutto il doc
    - usa questa capability per trovare l'API build123d corretta prima di scrivere build123d_code
```

---

#### 12.9 — Dipendenze e Compatibilità

**Backend — nessuna nuova dipendenza:**

Il plugin `cad_generator` usa solo `httpx` (già presente) e `json` (stdlib). La libreria
`build123d` gira nel container Docker di `cad-agent` — non viene installata in OMNIA.

**Frontend — dipendenze Three.js:**

```json
{
  "dependencies": {
    "three": "^0.170.0"
  },
  "devDependencies": {
    "@types/three": "^0.170.0"
  }
}
```

Installazione: `cd frontend && npm install three && npm install --save-dev @types/three`

**Docker — requisito esterno:**

| Componente | Requisito |
|---|---|
| Docker Desktop | ≥ 4.x (Windows) |
| cad-agent image | `ghcr.io/svetlana-dao-llc/cad-agent:latest` |
| Pull command | `docker pull ghcr.io/svetlana-dao-llc/cad-agent:latest` |
| Run command | `docker run -d -p 8080:8000 ghcr.io/svetlana-dao-llc/cad-agent:latest` |
| Verifica | `curl http://localhost:8080/health` |

Docker non è un requisito hard di OMNIA: se assente, il plugin si carica, mostra status
`DISCONNECTED` nella UI plugin, e i tool CAD restituiscono un messaggio di errore
descrittivo con le istruzioni di avvio. Il resto dell'app funziona normalmente.

**VRAM Impact (tabella aggiornata):**

| Componente | VRAM |
|---|---|
| Invariati (LLM, STT, TTS, Memory) | come prima |
| cad-agent (Docker) | 0 MB VRAM da OMNIA — il container gestisce la propria allocazione |
| Three.js viewer (Electron GPU) | < 100 MB GPU RAM (non VRAM dedicata) |
| ebook-mcp (uv subprocess) | 0 MB VRAM — CPU only |

---

#### 12.10 — Test Suite Fase 12

**`backend/tests/test_cad_agent_client.py`**:

- `test_health_check_success`: mock httpx GET /health → `True`
- `test_health_check_failure_returns_false`: `ConnectError` → `False` (no raise)
- `test_create_model_success`: mock POST /model/create → nome modello restituito
- `test_create_model_http_error`: mock 422 → `HTTPStatusError` propagato
- `test_export_model_success`: mock POST /export → `ExportResult` con bytes
- `test_export_model_exceeds_size`: mock 60MB response → `ValueError` con dimensioni
- `test_list_models`: mock GET /model/list → lista `ModelInfo`
- `test_ssrf_validation_rejects_remote_url`: URL `http://192.168.1.200:8080` → `RuntimeError` al costruttore
- `test_ssrf_validation_allows_localhost`: `http://localhost:8080` → nessun errore al costruttore

**`backend/tests/test_cad_generator_plugin.py`**:

- `test_initialize_reachable`: mock health_check True → plugin status CONNECTED
- `test_initialize_unreachable_no_crash`: mock health_check False → plugin carica,
  warning loggato, nessun crash (graceful degradation)
- `test_cad_generate_tool_definition`: `get_tools()` restituisce `ToolDefinition` per
  `cad_generate` con `risk_level="safe"`, `requires_confirmation=False`, `timeout_ms=90000`
- `test_cad_generate_success`: mock create_model success → `ToolResult.success=True`,
  `content_type="application/vnd.omnia.cad-model+json"`, `content` è JSON valido con
  `model_name` e `export_url`
- `test_cad_generate_docker_offline`: mock health_check False → `ToolResult.success=False`,
  `error_message` contiene istruzioni Docker
- `test_cad_generate_build123d_error`: mock create_model → `HTTPStatusError` 422 →
  `ToolResult.success=False`, errore descrittivo
- `test_cad_generate_auto_name`: `model_name` assente negli args → nome generato da
  `execution_id` (non crash, non nome vuoto)
- `test_cad_generate_sanitizes_name`: `model_name = "test-model/v2"` →
  nome sanitizzato `"test_model_v2"` (no path traversal)
- `test_cad_list_models`: mock list_models → `ToolResult.success=True`, JSON array di nomi
- `test_cleanup_closes_client`: `cleanup()` → `client.close()` chiamato

**`backend/tests/test_cad_proxy_route.py`**:

Pattern identico a `test_confirmation_audit.py` (pytest-asyncio + `AsyncClient`):

- `test_export_model_proxied`: GET `/api/cad/models/test_cube/export?format=stl` →
  mock CadAgentClient.export_model → `200 OK`, `Content-Type: model/stl`
- `test_export_model_not_found`: mock `HTTPStatusError(404)` → `404` risposta OMNIA
- `test_export_model_docker_offline`: mock `ConnectError` → `503` con messaggio
- `test_export_model_invalid_name`: `model_name = "../../etc/passwd"` → `400 Bad Request`
  (path traversal bloccato dalla regex)
- `test_export_model_plugin_not_active`: plugin disabilitato → `503`
- `test_cad_health`: GET `/api/cad/health` → mock health_check True → `200 {"status": "ok"}`
- `test_cad_model_list`: GET `/api/cad/models` → mock list_models → JSON array

**Verifica no-regression** (pre-PR): tutta la suite esistente deve passare invariata.
In particolare, verificare che `_tool_loop.py` (non modificato) soddisfi ancora i test
esistenti, che `ToolResult` con `content_type` diverso da `image/*` segua il path normale
(non viene troncato, non genera placeholder in DB), e che le route chat e voice siano invariate.

---

#### 12.11 — File Structure Fase 12

```
backend/
├── plugins/
│   └── cad_generator/
│       ├── __init__.py                  ← PLUGIN_REGISTRY["cad_generator"] = CadGeneratorPlugin
│       ├── plugin.py                    ← CadGeneratorPlugin (BasePlugin, 2 tool)
│       └── client.py                   ← CadAgentClient (httpx, Docker HTTP API)
├── api/
│   └── routes/
│       ├── cad.py                       ← REST /api/cad/* (proxy → Docker)
│       └── __init__.py                  ← + cad.router
├── core/
│   └── config.py                        ← + CadGeneratorConfig + OmniaConfig.cad_generator
└── tests/
    ├── test_cad_agent_client.py
    ├── test_cad_generator_plugin.py
    └── test_cad_proxy_route.py

config/
└── default.yaml                         ← + cad_generator: section + ebook-mcp in mcp.servers (commentato)

frontend/
├── package.json                         ← + three, @types/three
└── src/renderer/src/
    ├── components/
    │   └── chat/
    │       ├── CADViewer.vue            ← THREE.js + STLLoader + OrbitControls (nuovo)
    │       └── ToolExecutionIndicator.vue  ← + caso content_type cad-model
    └── types/
        └── chat.ts                      ← + CadModelPayload interface
```

---

#### 12.12 — Ordine di Implementazione Consigliato

1. **`CadGeneratorConfig`** in `config.py` + `default.yaml` entry — zero dipendenze, testabile subito
2. **`CadAgentClient`** + test unitari `test_cad_agent_client.py` — layer I/O isolabile con mock httpx
3. **`CadGeneratorPlugin`** + `__init__.py` + test `test_cad_generator_plugin.py`
4. **`cad.py` route** + registrazione in `routes/__init__.py` + test `test_cad_proxy_route.py`
5. **`types/chat.ts`** — aggiunta `CadModelPayload` (frontend, zero rischio)
6. **`CADViewer.vue`** — componente Three.js (frontend, standalone)
7. **`ToolExecutionIndicator.vue`** — aggiunta caso CAD (frontend, minimale)
8. **`config/system_prompt.md`** — aggiunta sezioni `cad_generator` e `documentation_access`
9. **`default.yaml`** — aggiunta entry `ebook-mcp` commentata in `mcp.servers`
10. **Test manuale**: avviare Docker + cad-agent → attivare plugin → "crea un cubo di 30mm" →
    verificare Three.js viewer nel frontend

---

#### 12.13 — Verifiche Fase 12

| Scenario | Comportamento atteso |
|---|---|
| "Crea un supporto per la racchetta da tennis, 200x50x30mm con slot centrale" | LLM scrive build123d_code → chiama `cad_generate` → plugin OK → `ToolResult(content_type="application/vnd.omnia.cad-model+json", content="{model_name, export_url}")` → frontend mostra `CADViewer.vue` con modello 3D interattivo |
| Utente ruota il modello | OrbitControls Three.js funzionanti — drag/scroll/pinch |
| Utente clicca "⬇ Scarica STL" | `GET /api/cad/models/{name}/export?format=stl` → download file |
| Docker non avviato | `health_check()` → False → `ToolResult(success=False, error_message="cad-agent non raggiungibile... docker run ...")` — nessun crash, messaggio descrittivo |
| build123d_code errato (sintassi) | cad-agent restituisce 422 → `ToolResult(success=False, error_message="...")` — l'LLM vede l'errore e può correggere |
| `cad_generator.enabled: false` (default) | Plugin non caricato, zero overhead; altri plugin e chat invariati |
| LLM chiede consultare docs build123d | Se `ebook-mcp` configurato: chiama `mcp_client_mcp_build123d_docs_get_toc` → tabella contenuti → `get_chapter_markdown` per sezione specifica → risponde con API corretta |
| `ebook-mcp` non configurato | `mcp_client` non ha quel server; tool ebook non nel ToolRegistry; zero impatto |
| `model_name = "../../../etc"` via tool | Sanitizzato a `"______etc"` dal plugin prima di passare al cad-agent |
| GET `/api/cad/models/../../passwd/export` | Regex `[a-zA-Z0-9_]{1,64}` → `400 Bad Request` |
| Modello STL > `max_model_size_mb` (default 50MB) | `export_model()` → `ValueError` → `ToolResult(success=False, error_message="... supera 50 MB")` |
| Conversazione ricaricata da DB | `CADViewer` non compare (content_type non persistito in DB, coerente con screenshot) — comportamento documentato, accettabile v1 |
| `GET /api/plugins` | Card `cad_generator` con status CONNECTED (se Docker up) o DISCONNECTED (se Docker down) |

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
| 11 | Server MCP filesystem configurato → LLM chiama `mcp_client_mcp_filesystem_read_file` → contenuto file in risposta |
| 11 (edge) | Server MCP offline all'avvio → plugin degraded, chat funzionante; server non configurato → zero impatto |
| 12 | "Crea un supporto 200x50x30mm" → `cad_generate(build123d_code)` → ToolResult con `content_type=cad-model+json` → CADViewer Three.js nel frontend; ebook-mcp configurato → LLM legge documentazione build123d PDF |
| 12 (edge) | Docker non avviato → errore descrittivo con istruzioni; build123d_code errato → errore 422 → LLM corregge; `model_name="../../../etc"` → sanitizzato; modello > 50MB → ValueError; conversazione ricaricata da DB → viewer non compare (comportamento noto v1) |
