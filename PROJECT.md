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

### Fase 12 — Generazione 3D Neurale (TRELLIS) + Documentazione MCP

> **Obiettivo**: permettere a OMNIA di generare modelli 3D da linguaggio naturale
> tramite [TRELLIS-for-windows](https://github.com/sdbds/TRELLIS-for-windows)
> (Microsoft TRELLIS, rete neurale image-to-3D) come microservizio separato,
> visualizzare i modelli interattivamente con Three.js (GLTFLoader), e fornire
> all'LLM accesso alla documentazione tecnica (PDF/EPUB) tramite
> [ebook-mcp](https://github.com/onebirdrocks/ebook-mcp).
>
> **Cambio di paradigma** rispetto all'approccio build123d precedentemente tentato:
> l'LLM NON genera più codice CAD (fase fallita perché il modello linguistico non
> riesce a produrre geometrie spazialmente corrette). Ora l'LLM descrive l'oggetto
> in linguaggio naturale → TRELLIS genera direttamente la mesh 3D come file `.glb`
> con texture. La qualità dipende dalla rete neurale addestrata, non dalla capacità
> dell'LLM di scrivere codice build123d.
>
> Fase 12 = **due feature distinte**, architetture complementari, zero overlap:
> 1. **Documentazione** — puro config: `ebook-mcp` registrato come server MCP nel plugin
>    `mcp_client` esistente (Fase 11). Zero codice.
> 2. **Generazione 3D** — TRELLIS microservizio (Python 3.10-3.12 separato) + plugin
>    `cad_generator` (HTTP client) + route proxy `/api/cad/` + viewer Three.js (GLTFLoader).

- [x] 12.1 — Documentazione MCP (`ebook-mcp`) — config-only
- [x] 12.2 — `TrellisServiceConfig` in `config.py` + `default.yaml`
- [x] 12.3 — TRELLIS Microservizio (`trellis_server/`)
- [x] 12.4 — `TrellisClient` (`backend/plugins/cad_generator/client.py`)
- [x] 12.5 — Orchestrazione VRAM (unload/reload LLM automatico)
- [x] 12.6 — `CadGeneratorPlugin` (1 tool primario: `cad_generate`)
- [x] 12.7 — REST proxy `backend/api/routes/cad.py` (`/api/cad/`)
- [x] 12.8 — Frontend: `CADViewer.vue` (Three.js + GLTFLoader)
- [x] 12.9 — Frontend: estensione `ToolExecutionIndicator.vue` + `types/chat.ts`
- [x] 12.10 — System prompt update (`config/system_prompt.md`)
- [x] 12.11 — Test suite (3+ file, 25+ test case)

---

#### 12.0 — Analisi Vincoli e Scelte Architetturali

**Perché TRELLIS neurale e non build123d code generation:**

L'approccio precedente (build123d code generation via Docker cad-agent) è stato implementato
e revertato perché l'LLM non riesce a generare codice build123d spazialmente corretto:
maniglie fuori posizione, intersezioni casuali di poligoni, geometrie impossibili. Il
problema è intrinseco — i language model non hanno comprensione spaziale 3D sufficientemente
precisa per scrivere codice CAD parametrico corretto al primo tentativo.

TRELLIS (Microsoft Research, MIT license) è una rete neurale image-to-3D che genera
mesh 3D direttamente da un'immagine di input. L'LLM descrive l'oggetto → (opzionalmente)
un modello T2I genera un'immagine di riferimento → TRELLIS produce un file GLB con
texture. La qualità dipende dalla rete neurale pre-addestrata (1.2B parametri), non dalla
capacità dell'LLM di scrivere codice procedurale.

**Perché TRELLIS-for-windows (fork sdbds) e non TRELLIS upstream:**

TRELLIS upstream (Microsoft) è solo Linux. Il fork
[sdbds/TRELLIS-for-windows](https://github.com/sdbds/TRELLIS-for-windows) è un port
Windows completo con installer PowerShell, gestione dipendenze via `uv`, supporto CUDA
12.4, e wheel precompilate per le dipendenze problematiche (flash-attn, kaolin, etc.).
Requisiti: Python 3.10-3.12, CUDA 12.4+, VS Studio 2022 C++ build tools.

**Perché un microservizio separato e non integrato nel backend OMNIA:**

| Vincolo | Motivo |
|---|---|
| **Python 3.14 vs 3.10-3.12** | OMNIA usa Python 3.14; TRELLIS richiede 3.10-3.12 (dipendenze: flash-attn, kaolin, spconv non compilano su 3.14). Impossibile coesistere nello stesso venv. |
| **Dipendenze pesanti** | TRELLIS porta ~8GB di dipendenze (PyTorch, kaolin, flash-attn, xformers, spconv, etc.). Mescolarle nel venv OMNIA creerebbe conflitti e fragilità. |
| **Isolamento fault** | Se TRELLIS crasha (OOM, CUDA error), il backend OMNIA resta stabile. Il microservizio può essere riavviato indipendentemente. |
| **VRAM esclusiva** | TRELLIS-image-large ha bisogno di ≥16GB VRAM esclusivi; TRELLIS-text-large ~10-12GB. LLM ha bisogno di ~10GB. Non possono coesistere. Il microservizio si avvia on-demand e rilascia VRAM quando finisce. |

Il microservizio TRELLIS è un processo Python 3.10-3.12 separato con un proprio venv, che
espone una mini API HTTP (FastAPI, porta 8090). Il plugin OMNIA `cad_generator` lo chiama
via `httpx` — identico al pattern cad-agent Docker della spec precedente, ma senza Docker.

**Perché VRAM swap (unload LLM → TRELLIS → reload LLM):**

Con 16GB VRAM totali (RTX 5080), LLM (~10GB) + TRELLIS-image-large (~15GB) non possono coesistere.
Il flusso è:

```
1. Utente: "Crea un modello 3D di un vaso decorativo"
2. LLM genera risposta + tool_call cad_generate(description="...")
3. === TOOL EXECUTION WINDOW (LLM è idle, aspetta risultato) ===
4.   a) Plugin chiama LM Studio POST /api/v1/models/unload → LLM scaricato, ~10GB VRAM liberi
5.   b) Plugin chiama TRELLIS microservice /generate → TRELLIS carica modello, genera GLB
6.   c) TRELLIS rilascia VRAM (processo rimane in standby o si chiude)
7.   d) Plugin chiama LM Studio POST /api/v1/models/load → LLM ricaricato
8. === FINE TOOL EXECUTION ===
9. LLM riceve ToolResult con URL al .glb → completa la risposta all'utente
```

Questo è possibile perché nel tool loop (`_tool_loop.py`), tra il momento in cui l'LLM
emette la `tool_call` (step 2) e riceve il `ToolResult` (step 9), l'LLM è completamente
idle — non ha bisogno della VRAM. La finestra è naturale e non richiede hack.

LM Studio espone sia `POST /api/v1/models/unload` (per `instance_id`) sia
`POST /api/v1/models/load` — confermato dall'esplorazione del servizio `lmstudio_service.py`
che già wrappa queste API.

**Perché GLB e non STL:**

TRELLIS genera nativamente mesh in formato GLB (glTF Binary) con texture UV-mapped.
Three.js supporta `GLTFLoader` come loader principale (più performante di STLLoader,
supporta materiali PBR, animazioni, compressione Draco). GLB è lo standard de facto per
3D sul web.

**Flusso opzionale T2I per qualità migliore:**

Il README di TRELLIS raccomanda: "It is always recommended to do text to 3D generation
by first generating images using text-to-image models and then using TRELLIS-image models
for 3D generation." Il flusso a due step (text → immagine → 3D) produce risultati più
dettagliati e creativi. Per v1, il T2I è opzionale: se configurato, il plugin lo usa;
altrimenti passa il testo direttamente a TRELLIS-text (qualità inferiore ma funzionante).

**Nessuna modifica a layer esistenti (solo aggiunte pure):**

| Layer | Modificato | Motivo |
|---|---|---|
| `_tool_loop.py` | NO | `content_type` già propagato a WS per tutti i tool result |
| `chat.py` | NO | nessuna dispatch speciale necessaria |
| `plugin_models.py` | NO | `ToolResult.content_type` già esiste |
| `protocols.py` | NO | nessun nuovo protocol necessario (LMStudioManagerProtocol già esiste) |
| `context.py` | NO | plug-in gestito da `PluginManager` come tutti gli altri |
| `app.py` | NO | plugin registrato nel `PLUGIN_REGISTRY` statico |
| `plugin_manager.py` | NO | nessuna modifica |
| `lmstudio_service.py` | NO | API unload/load già esposte |
| `vram_monitor.py` | NO | il plugin gestisce il budget VRAM autonomamente |

---

#### 12.1 — Documentazione MCP (`ebook-mcp`) — Config-Only

`ebook-mcp` (onebirdrocks/ebook-mcp, Apache 2.0, installabile via `uvx`) è un server MCP
stdio che legge PDF e EPUB e ne espone il contenuto come tool. Aggiungere un'entry a
`config/default.yaml` nella sezione `mcp.servers` (introdotta in Fase 11) è l'unica
azione necessaria.

**Tool esposti all'LLM una volta configurato:**

| Tool MCP | Nome visibile all'LLM (via ToolRegistry) |
|---|---|
| `get_all_epub_files` | `mcp_client_mcp_3d_docs_get_all_epub_files` |
| `get_metadata` | `mcp_client_mcp_3d_docs_get_metadata` |
| `get_toc` | `mcp_client_mcp_3d_docs_get_toc` |
| `get_chapter_markdown` | `mcp_client_mcp_3d_docs_get_chapter_markdown` |
| `get_all_pdf_files` | `mcp_client_mcp_3d_docs_get_all_pdf_files` |
| `get_pdf_metadata` | `mcp_client_mcp_3d_docs_get_pdf_metadata` |
| `get_pdf_toc` | `mcp_client_mcp_3d_docs_get_pdf_toc` |
| `get_pdf_page_text` | `mcp_client_mcp_3d_docs_get_pdf_page_text` |
| `get_pdf_page_markdown` | `mcp_client_mcp_3d_docs_get_pdf_page_markdown` |
| `get_pdf_chapter_content` | `mcp_client_mcp_3d_docs_get_pdf_chapter_content` |

**Aggiunta a `config/default.yaml`** (nella sezione `mcp.servers` esistente):

```yaml
mcp:
  servers:
    # ... server esistenti ...
    #
    # - name: 3d_docs
    #   transport: stdio
    #   # Installa ebook-mcp con: uvx ebook-mcp
    #   # Posiziona i PDF/EPUB di documentazione 3D nella cartella models/docs/
    #   command: ["uvx", "ebook-mcp", "--folder", "C:/Users/zagor/Desktop/omnia/models/docs"]
    #   enabled: true
    #   # Usa `get_toc` su ogni documento prima di leggere capitoli specifici
```

**Configurazione utente** (passo manuale one-shot):

```powershell
# 1. Installa ebook-mcp (verifica che uvx/uv sia disponibile — già usato dal progetto)
uvx ebook-mcp --version  # verifica funzionamento

# 2. Crea la cartella documenti e posiziona i PDF/EPUB
New-Item -ItemType Directory -Path "C:\Users\zagor\Desktop\omnia\models\docs" -Force
# Copiare qui: documentazione 3D, manuali tecnici, ecc.

# 3. Decommentare la voce nel default.yaml e aggiornare il path
# 4. Aggiungere "mcp_client" a plugins.enabled se non già presente
```

**Dipendenze:** `ebook-mcp` richiede `uvx` (già disponibile) — zero nuove dipendenze nel
`pyproject.toml` di OMNIA. L'installazione avviene nell'ambiente isolato di `uvx`.

---

#### 12.2 — TrellisServiceConfig (`backend/core/config.py`)

Nuova classe aggiunta in `config.py`, dopo `McpConfig`:

```python
class TrellisServiceConfig(BaseSettings):
    """TRELLIS 3D generation microservice configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_TRELLIS__")

    enabled: bool = False
    """Abilita il plugin cad_generator. Richiede il microservizio TRELLIS installato."""

    service_url: str = "http://localhost:8090"
    """URL base del microservizio TRELLIS (processo Python 3.10-3.12 separato)."""

    request_timeout_s: int = 120
    """Timeout per la generazione 3D (può richiedere 30-90s a seconda della complessità)."""

    max_model_size_mb: int = 100
    """Dimensione massima accettata per i file GLB generati."""

    model_output_dir: str = "data/3d_models"
    """Directory locale dove salvare i file GLB generati (relativa a PROJECT_ROOT)."""

    auto_vram_swap: bool = True
    """Se True, scarica automaticamente l'LLM da VRAM prima della generazione 3D
    e lo ricarica dopo. Necessario su GPU con < 20GB VRAM."""

    trellis_model: str = "TRELLIS-image-large"
    """Modello TRELLIS da caricare nel microservizio. Opzioni:
    - TRELLIS-image-large (1.2B) — image-to-3D, qualità migliore, raccomandato;
    - TRELLIS-text-xlarge (2.0B) — text-to-3D, massima qualità, richiede > 16GB VRAM;
    - TRELLIS-text-large (1.1B) — text-to-3D, buona qualità, ~12GB VRAM;
    - TRELLIS-text-base (342M) — text-to-3D, veloce, ~8GB VRAM.
    Nota: tutti i VAE sono inclusi nel repo TRELLIS-image-large su HuggingFace."""

    use_t2i: bool = False
    """Se True, usa un modello text-to-image intermedio per generare l'immagine di
    riferimento prima di passarla a TRELLIS. Migliora creatività e dettaglio.
    Richiede un modello T2I configurato nel microservizio TRELLIS."""

    seed: int = -1
    """Seed per la generazione. -1 = random. Impostare un valore fisso per riproducibilità."""
```

Aggiunta a `OmniaConfig` (dopo `mcp`):

```python
trellis: TrellisServiceConfig = Field(default_factory=TrellisServiceConfig)
```

Aggiunta a `config/default.yaml` (in fondo, dopo la sezione `mcp:`):

```yaml
# ──────────────────────────────────────────────────
# Fase 12 — Generazione 3D Neurale (TRELLIS)
# ──────────────────────────────────────────────────
trellis:
  enabled: false
  # Installare TRELLIS-for-windows prima di abilitare:
  #   0. [Admin PS] Set-ExecutionPolicy Unrestricted
  #   1. git clone --recurse-submodules https://github.com/sdbds/TRELLIS-for-windows.git trellis_server
  #   2. cd trellis_server && .\1、install-uv-qinglong.ps1
  #   3. Avviare con: .venv\Scripts\python.exe server.py --port 8090
  service_url: "http://localhost:8090"
  request_timeout_s: 120
  max_model_size_mb: 100
  model_output_dir: "data/3d_models"
  auto_vram_swap: true
  trellis_model: "TRELLIS-image-large"
  # Modelli disponibili (da HuggingFace JeffreyXiang/):
  # - TRELLIS-image-large (1.2B) — image-to-3D, qualità migliore (raccomandato con T2I)
  # - TRELLIS-text-large (1.1B) — text-to-3D, buona qualità, ~10-12GB VRAM
  # - TRELLIS-text-base (342M) — text-to-3D, veloce, ~8GB VRAM
  # NOTA: su sistemi con 16GB VRAM e STT caricato, preferire TRELLIS-text-large
  use_t2i: false
  seed: -1

# In plugins.enabled, aggiungere (commentato per default-off):
#   - cad_generator  # abilitare con trellis.enabled: true
```

**SSRF protection**: `service_url` deve essere un URL locale. La validazione è enforced in
`TrellisClient.__init__()` tramite `validate_url_ssrf()` di `http_security.py` —
identica al pattern adottato da `WeatherPlugin`, `NewsPlugin` e `WebSearchPlugin`.

---

#### 12.3 — TRELLIS Microservizio (`trellis_server/`)

**Ruolo**: processo Python 3.10-3.12 separato che wrappa TRELLIS-for-windows ed espone una
mini API HTTP per la generazione 3D. Completamente isolato dal backend OMNIA.

**Directory structure**:

```
trellis_server/                          ← root del microservizio (gitignored, clonato da fork)
├── 1、install-uv-qinglong.ps1           ← ★ installer PowerShell dal fork (--recurse-submodules)
├── 2、run_gui.ps1                       ← launcher Gradio demo opzionale
├── server.py                            ← ★ Mini FastAPI server (scritto da noi, ~150 righe)
├── .venv/                               ← venv Python 3.11/3.12 isolato (creato dall'installer)
└── ... (file TRELLIS-for-windows)       ← repo clonata con submoduli
```

**`trellis_server/server.py`** — Mini FastAPI server (~100 righe):

```python
"""TRELLIS microservice — minimal FastAPI wrapper for 3D generation.

Runs as a separate Python 3.10-3.12 process, isolated from the OMNIA backend.
Exposes /generate, /unload, /health, and /models/{name} on port 8090.

Usage:
    cd trellis_server
    .venv/Scripts/python.exe server.py [--model TRELLIS-image-large] [--port 8090]

Model selection:
    TRELLIS-image-large  (1.2B) — image-to-3D, best quality, recommended
    TRELLIS-text-large   (1.1B) — text-to-3D, lower quality, no image required
    TRELLIS-text-base    (342M) — text-to-3D, fastest, 16GB VRAM constraint
"""
from __future__ import annotations

import argparse
import gc
import io
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

# Must be set before importing any trellis module — disables auto-benchmarking
# so the first run doesn't spend 30-60s selecting optimal CUDA kernels.
os.environ.setdefault("SPCONV_ALGO", "native")

import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image

app = FastAPI(title="TRELLIS Microservice", version="1.0.0")

# Set by __main__ — determines which pipeline class to load.
_pipeline = None
_model_name: str = "TRELLIS-image-large"
_output_dir: Path = Path(tempfile.gettempdir()) / "trellis_output"


def _is_image_model() -> bool:
    """Return True for TRELLIS-image-* models, False for TRELLIS-text-*."""
    return "image" in _model_name.lower()


def _load_pipeline():
    """Lazy-load the correct TRELLIS pipeline on first request.

    TRELLIS-image-* uses TrellisImageTo3DPipeline (image input required).
    TRELLIS-text-*  uses TrellisTextTo3DPipeline (text prompt input).
    Both pipelines export identical outputs dict: gaussian / mesh / radiance_field.
    """
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    if _is_image_model():
        from trellis.pipelines import TrellisImageTo3DPipeline
        _pipeline = TrellisImageTo3DPipeline.from_pretrained(_model_name)
    else:
        from trellis.pipelines import TrellisTextTo3DPipeline
        _pipeline = TrellisTextTo3DPipeline.from_pretrained(_model_name)
    _pipeline.cuda()
    return _pipeline


def _unload_pipeline():
    """Release TRELLIS model from VRAM."""
    global _pipeline
    if _pipeline is not None:
        _pipeline.to("cpu")
        del _pipeline
        _pipeline = None
        gc.collect()
        torch.cuda.empty_cache()


@app.get("/health")
async def health():
    """Health check. Returns GPU availability and VRAM status."""
    gpu_available = torch.cuda.is_available()
    vram_free = 0
    if gpu_available:
        vram_free = torch.cuda.mem_get_info()[0] // (1024 * 1024)
    return {
        "status": "ok",
        "gpu_available": gpu_available,
        "vram_free_mb": vram_free,
        "model_loaded": _pipeline is not None,
        "model_name": _model_name,
    }


@app.post("/generate")
async def generate(
    image: UploadFile = File(None),
    prompt: str = Form(""),
    seed: int = Form(-1),
    output_name: str = Form(""),
):
    """Generate a 3D GLB model from an image or text prompt.

    Routes to TrellisImageTo3DPipeline or TrellisTextTo3DPipeline based on
    the loaded model. Image-to-3D produces significantly better results —
    always prefer TRELLIS-image-large with a T2I-generated image when possible.

    Raises:
        HTTPException 400: If image-model loaded but no image provided.
        HTTPException 500: On TRELLIS generation or export failure.
    """
    from trellis.utils import postprocessing_utils

    if not image and not prompt:
        raise HTTPException(400, "Provide either 'image' or 'prompt'.")
    if _is_image_model() and not image:
        raise HTTPException(
            400,
            f"Model '{_model_name}' requires an image input. "
            "Either provide an image or switch to a TRELLIS-text-* model.",
        )

    pipeline = _load_pipeline()
    actual_seed = seed if seed >= 0 else int(time.time()) % (2**32)
    name = output_name or f"model_{uuid.uuid4().hex[:8]}"
    _output_dir.mkdir(parents=True, exist_ok=True)
    out_path = _output_dir / f"{name}.glb"

    try:
        if image:
            # Image-to-3D: RGBA input recommended per TRELLIS docs
            img_bytes = await image.read()
            pil_image = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
            outputs = pipeline.run(pil_image, seed=actual_seed)
        else:
            # Text-to-3D: requires TRELLIS-text-* model (set via --model flag)
            outputs = pipeline.run(prompt, seed=actual_seed)

        # Fuse Gaussian + Mesh into a single textured GLB.
        # simplify=0.95 reduces triangle count while preserving shape.
        # texture_size=1024 gives good quality without excessive file size.
        glb = postprocessing_utils.to_glb(
            outputs["gaussian"][0],
            outputs["mesh"][0],
            simplify=0.95,
            texture_size=1024,
        )
        glb.export(str(out_path))

    except Exception as exc:
        raise HTTPException(500, f"Generation failed: {exc}")

    return JSONResponse({
        "model_name": name,
        "file_path": str(out_path),
        "format": "glb",
        "size_bytes": out_path.stat().st_size,
    })


@app.post("/unload")
async def unload():
    """Unload the TRELLIS model from VRAM to free memory for the LLM."""
    _unload_pipeline()
    return {"status": "unloaded"}


@app.get("/models/{model_name}")
async def get_model(model_name: str):
    """Download a previously generated GLB file by name."""
    if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", model_name):
        raise HTTPException(400, "Invalid model name.")
    path = _output_dir / f"{model_name}.glb"
    if not path.exists():
        raise HTTPException(404, f"Model '{model_name}' not found.")
    return FileResponse(path, media_type="model/gltf-binary", filename=f"{model_name}.glb")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TRELLIS 3D generation microservice")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument(
        "--model", type=str, default="TRELLIS-image-large",
        help=(
            "TRELLIS model name or local HuggingFace cache path. "
            "TRELLIS-image-large (1.2B, image-to-3D, recommended), "
            "TRELLIS-text-large (1.1B, text-to-3D), "
            "TRELLIS-text-base (342M, text-to-3D, lower VRAM)."
        ),
    )
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    _model_name = args.model
    if args.output_dir:
        _output_dir = Path(args.output_dir)

    uvicorn.run(app, host="127.0.0.1", port=args.port)
```

**Installazione TRELLIS-for-windows** (passo manuale one-shot):

```powershell
# 0. [UNA VOLTA, come Amministratore] Abilita execution policy per script non firmati.
#    Aprire PowerShell come Amministratore ed eseguire:
#      Set-ExecutionPolicy Unrestricted
#    Rispondere A (Yes to All) → chiudere la finestra.

# 1. Clona il fork Windows dalla root del progetto OMNIA.
#    OBBLIGATORIO: --recurse-submodules (il repo include submoduli CUDA)
git clone --recurse-submodules https://github.com/sdbds/TRELLIS-for-windows.git trellis_server

# 2. Entra nella directory
cd trellis_server

# 3. Esegui lo script di installazione del fork.
#    Crea un venv Python 3.11/3.12, installa PyTorch CUDA 12.4 + kaolin + spconv +
#    flash-attn + xformers + nvdiffrast e tutte le altre dipendenze.
#    (il nome del file include un carattere CJK — usare .\ per eseguire da PS)
.\1、install-uv-qinglong.ps1

# 4. Copia server.py nella directory (creato durante l'implementazione di Fase 12)

# 5. Verifica funzionamento
.venv\Scripts\python.exe server.py --port 8090
# In un altro terminale:
curl http://localhost:8090/health
```

**Requisiti sistema TRELLIS-for-windows:**

| Requisito | Dettaglio |
|---|---|
| Python | 3.10-3.12 (gestito dal venv del fork; non condiviso con OMNIA Python 3.14) |
| CUDA | 12.4 (versione usata dal fork; installare CUDA Toolkit 12.4 a sistema) |
| VS Studio | 2022 con workload "Desktop development with C++" (richiesto per compilare submoduli CUDA) |
| VRAM | **≥ 16GB** per TRELLIS-image-large (1.2B, requisito verificato su A100/A6000); su sistemi con 16GB usare TRELLIS-text-large (1.1B) o TRELLIS-text-base (342M) che richiedono ~8-10GB |
| RAM | ≥ 16GB sistema |
| Disco | ~8GB dipendenze + ~10GB HuggingFace model cache |
| GPU | NVIDIA con compute capability ≥ 7.5 (RTX 20xx+) |

**Aggiunta a `.gitignore`:**

```
trellis_server/
data/3d_models/
```

---

#### 12.4 — TrellisClient (`backend/plugins/cad_generator/client.py`)

**Ruolo**: client HTTP asincrono verso il microservizio TRELLIS.
Non conosce il plugin, il context OMNIA né il ToolRegistry — solo I/O HTTP.

```python
"""TRELLIS microservice HTTP client.

Wraps the TRELLIS server.py API with typed async methods.
Isolated from OMNIA internals — only does HTTP I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
from loguru import logger

from backend.core.config import TrellisServiceConfig
from backend.core.http_security import validate_url_ssrf


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Result from TRELLIS 3D generation."""

    model_name: str
    format: str          # always "glb" for now
    size_bytes: int
    remote_path: str     # path on microservice filesystem


class TrellisClient:
    """Async HTTP client for the TRELLIS microservice.

    Holds a persistent httpx.AsyncClient. Call close() to release.

    Args:
        config: TrellisServiceConfig with service_url, timeouts, etc.

    Raises:
        RuntimeError: On construction if service_url fails SSRF validation.
    """

    def __init__(self, config: TrellisServiceConfig) -> None:
        validate_url_ssrf(config.service_url)
        self._base_url = config.service_url.rstrip("/")
        self._timeout = config.request_timeout_s
        self._max_bytes = config.max_model_size_mb * 1_048_576
        self._model = config.trellis_model
        self._seed = config.seed
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout),
        )

    async def health_check(self) -> bool:
        """Return True if the TRELLIS microservice is reachable."""
        try:
            r = await self._client.get("/health", timeout=5.0)
            return r.status_code < 500
        except Exception:
            return False

    async def generate_from_image(
        self,
        image_bytes: bytes,
        model_name: str,
        seed: int = -1,
    ) -> GenerationResult:
        """Generate a 3D GLB model from an image.

        Args:
            image_bytes: PNG/JPEG image bytes.
            model_name: Unique name for the output model.
            seed: Random seed (-1 = random).

        Returns:
            GenerationResult with metadata.

        Raises:
            httpx.HTTPStatusError: On HTTP error from microservice.
        """
        actual_seed = seed if seed >= 0 else self._seed
        files = {"image": ("input.png", image_bytes, "image/png")}
        data = {"seed": str(actual_seed), "output_name": model_name}

        r = await self._client.post("/generate", files=files, data=data)
        r.raise_for_status()
        result = r.json()

        logger.debug(
            "TRELLIS generation '{}' — {} bytes", model_name, result.get("size_bytes", 0)
        )
        return GenerationResult(
            model_name=result["model_name"],
            format=result.get("format", "glb"),
            size_bytes=result.get("size_bytes", 0),
            remote_path=result.get("file_path", ""),
        )

    async def generate_from_text(
        self,
        prompt: str,
        model_name: str,
        seed: int = -1,
    ) -> GenerationResult:
        """Generate a 3D GLB model from a text prompt.

        Requires the TRELLIS microservice to be running a TRELLIS-text-* model
        (start with: .venv/Scripts/python.exe server.py --model TRELLIS-text-large).
        The TRELLIS-image-* models do NOT accept text input — the server returns
        HTTP 400 if called with a text-only request while an image model is loaded.

        Prefer generate_from_image() when possible: TRELLIS-image models produce
        significantly more creative and detailed results (per upstream TRELLIS docs:
        "text-conditioned models are less creative and detailed due to data limitations").

        Args:
            prompt: Text description of the 3D object.
            model_name: Unique name for the output model.
            seed: Random seed (-1 = random).

        Returns:
            GenerationResult with metadata.
        """
        actual_seed = seed if seed >= 0 else self._seed
        data = {"prompt": prompt, "seed": str(actual_seed), "output_name": model_name}

        r = await self._client.post("/generate", data=data)
        r.raise_for_status()
        result = r.json()

        logger.debug(
            "TRELLIS text generation '{}' — {} bytes",
            model_name,
            result.get("size_bytes", 0),
        )
        return GenerationResult(
            model_name=result["model_name"],
            format=result.get("format", "glb"),
            size_bytes=result.get("size_bytes", 0),
            remote_path=result.get("file_path", ""),
        )

    async def download_model(self, model_name: str) -> bytes:
        """Download a generated GLB file from the microservice.

        Args:
            model_name: Name of the model to download.

        Returns:
            Raw GLB bytes.

        Raises:
            httpx.HTTPStatusError: On HTTP error.
            ValueError: If file exceeds max_model_size_mb.
        """
        r = await self._client.get(f"/models/{model_name}")
        r.raise_for_status()
        if len(r.content) > self._max_bytes:
            raise ValueError(
                f"Model '{model_name}' exceeds max size "
                f"({len(r.content) // 1_048_576} MB > {self._max_bytes // 1_048_576} MB)"
            )
        return r.content

    async def unload_model(self) -> None:
        """Ask the microservice to unload TRELLIS from VRAM."""
        try:
            r = await self._client.post("/unload", timeout=10.0)
            r.raise_for_status()
            logger.info("TRELLIS model unloaded from VRAM")
        except Exception as exc:
            logger.warning("Failed to unload TRELLIS model: {}", exc)

    async def close(self) -> None:
        """Release the underlying httpx.AsyncClient connection pool."""
        await self._client.aclose()
```

**Nota sicurezza `validate_url_ssrf`**: identica alla nota del 12.3 precedente. `localhost`
e `127.0.0.1` devono essere permessi (il microservizio TRELLIS gira sulla stessa macchina).

---

#### 12.5 — Orchestrazione VRAM (unload/reload LLM automatico)

**Ruolo**: durante l'esecuzione del tool `cad_generate`, il plugin deve liberare VRAM
scaricando il modello LLM da LM Studio, eseguire la generazione TRELLIS, e poi ricaricare
il modello LLM per permettergli di completare la risposta.

L'orchestrazione avviene interamente dentro `CadGeneratorPlugin._execute_cad_generate()`,
usando le API già esposte da `LMStudioService`:

```python
async def _vram_swap_generate(
    self,
    description: str,
    model_name: str,
) -> tuple[GenerationResult | None, str | None]:
    """Execute TRELLIS generation with VRAM swap if configured.

    Steps:
        1. Get current LLM model info from LM Studio
        2. Unload LLM from VRAM via LM Studio API
        3. Wait for VRAM to be freed (short sleep for GPU driver)
        4. Call TRELLIS microservice /generate
        5. Ask TRELLIS to unload its model from VRAM
        6. Reload LLM via LM Studio API
        7. Return generation result

    Args:
        description: Natural language description of the 3D object.
        model_name: Name for the generated model.

    Returns:
        Tuple of (GenerationResult or None, error_message or None).
    """
    cfg = self._ctx.config.trellis
    lmstudio: LMStudioManagerProtocol = self._ctx.lmstudio_manager
    client = self._client

    # Step 1: Capture current LLM state for reload
    llm_model_id = None
    if cfg.auto_vram_swap:
        try:
            loaded_models = await lmstudio.list_loaded_models()
            if loaded_models:
                llm_model_id = loaded_models[0].get("id") or loaded_models[0].get("instance_id")
                # Unload LLM
                logger.info("VRAM swap: unloading LLM '{}'", llm_model_id)
                await lmstudio.unload_model(llm_model_id)
                # Brief pause for GPU driver to fully release memory
                await asyncio.sleep(2)
        except Exception as exc:
            logger.warning("VRAM swap: failed to unload LLM: {}", exc)
            # Continue anyway — TRELLIS might still work if enough VRAM

    # Step 2: Generate with TRELLIS
    gen_result = None
    gen_error = None
    try:
        gen_result = await client.generate_from_text(description, model_name)
    except httpx.HTTPStatusError as exc:
        gen_error = f"TRELLIS generation error: {exc.response.text[:500]}"
    except Exception as exc:
        gen_error = f"TRELLIS generation failed: {exc}"

    # Step 3: Unload TRELLIS model from VRAM
    try:
        await client.unload_model()
    except Exception:
        pass  # Best-effort — LLM reload is more important

    # Step 4: Reload LLM
    if cfg.auto_vram_swap and llm_model_id:
        try:
            logger.info("VRAM swap: reloading LLM '{}'", llm_model_id)
            await lmstudio.load_model(llm_model_id)
            # Wait for model to be fully loaded
            for _ in range(30):  # max 30s wait
                await asyncio.sleep(1)
                loaded = await lmstudio.list_loaded_models()
                if any(m.get("id") == llm_model_id for m in loaded):
                    break
        except Exception as exc:
            logger.error("VRAM swap: CRITICAL — failed to reload LLM: {}", exc)
            gen_error = (gen_error or "") + f" [WARNING: LLM reload failed: {exc}]"

    return gen_result, gen_error
```

**Garanzie di sicurezza:**

1. **LLM reload è always-attempted**: anche se TRELLIS fallisce, il blocco `finally` di
   `_execute_cad_generate()` tenta il reload dell'LLM. L'utente non si ritrova mai senza LLM.
2. **Timeout**: il reload ha un loop di max 30 iterazioni × 1s = 30s. Se supera, continua
   con un warning nel risultato.
3. **Fallback senza swap**: se `auto_vram_swap: false`, il plugin chiama TRELLIS direttamente
   senza toccare l'LLM (utile su GPU con ≥ 24GB VRAM dove entrambi possono coesistere).

---

#### 12.6 — CadGeneratorPlugin (`backend/plugins/cad_generator/plugin.py`)

**Ruolo**: plugin OMNIA che espone il tool LLM `cad_generate` per generare modelli 3D.
Gestisce il ciclo di vita del `TrellisClient`, l'orchestrazione VRAM, e il salvataggio
locale del file GLB.

```
backend/plugins/cad_generator/
├── __init__.py     ← import + PLUGIN_REGISTRY["cad_generator"] = CadGeneratorPlugin
├── plugin.py       ← CadGeneratorPlugin(BasePlugin) — tool + VRAM orchestration
└── client.py       ← TrellisClient — HTTP I/O verso microservizio
```

**`__init__.py`** — pattern identico a tutti gli altri plugin:

```python
"""O.M.N.I.A. — CAD Generator plugin package (TRELLIS neural 3D generation).

Importing this module registers CadGeneratorPlugin in the static PLUGIN_REGISTRY.
Requires the TRELLIS microservice running on trellis.service_url.
See https://github.com/sdbds/TRELLIS-for-windows for setup instructions.
"""
from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.cad_generator.plugin import CadGeneratorPlugin  # noqa: F401

PLUGIN_REGISTRY["cad_generator"] = CadGeneratorPlugin
```

**`plugin.py`** — `CadGeneratorPlugin(BasePlugin)`:

```python
class CadGeneratorPlugin(BasePlugin):
    """Generates 3D models from natural language via the TRELLIS neural network.

    Uses the TRELLIS microservice (separate Python 3.10-3.12 process) to convert
    text descriptions or images into GLB 3D models. Manages VRAM orchestration
    (LLM unload → TRELLIS generate → LLM reload) automatically when configured.

    The generated GLB file is saved locally and served via /api/cad/ proxy route.
    The frontend renders it with Three.js GLTFLoader.
    """

    plugin_name = "cad_generator"
    plugin_version = "1.0.0"
    plugin_description = (
        "Genera modelli 3D da descrizioni in linguaggio naturale tramite TRELLIS. "
        "I modelli vengono visualizzati interattivamente nel frontend via Three.js."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 20  # bassa priorità: operazione pesante, non essenziale

    def __init__(self) -> None:
        super().__init__()
        self._client: TrellisClient | None = None

    async def initialize(self, ctx: AppContext) -> None:
        """Start the TrellisClient and check microservice availability."""
        await super().initialize(ctx)
        cfg = ctx.config.trellis
        self._client = TrellisClient(cfg)

        # Ensure local output directory exists
        output_dir = Path(cfg.model_output_dir)
        if not output_dir.is_absolute():
            output_dir = Path(ctx.config.project_root) / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir = output_dir

        reachable = await self._client.health_check()
        if not reachable:
            logger.warning(
                "CadGeneratorPlugin: TRELLIS microservice non raggiungibile a {}. "
                "I tool CAD restituiranno un errore finché il servizio non è avviato.",
                cfg.service_url,
            )

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

**Tool definition** (restituita da `get_tools()`):

| Tool | risk_level | requires_confirmation | timeout_ms | Descrizione |
|---|---|---|---|---|
| `cad_generate` | `safe` | `False` | 180000 | Genera un modello 3D da una descrizione testuale, visualizzabile nel frontend |

**Schema tool `cad_generate`**:

```json
{
  "type": "object",
  "properties": {
    "description": {
      "type": "string",
      "description": "Descrizione in linguaggio naturale dell'oggetto 3D da generare. Più dettagliata è la descrizione, migliore sarà il risultato. Es: 'un vaso decorativo con motivi floreali in rilievo, alto circa 30cm, stile Art Nouveau'",
      "maxLength": 2000
    },
    "model_name": {
      "type": "string",
      "description": "Nome identificativo del modello (solo lettere, numeri, underscore). Se omesso, viene generato automaticamente.",
      "pattern": "^[a-zA-Z0-9_]{1,64}$"
    }
  },
  "required": ["description"]
}
```

**Implementazione `execute_tool("cad_generate", args, ctx)`**:

```python
async def _execute_cad_generate(self, args: dict, context: ExecutionContext) -> ToolResult:
    if self._client is None:
        return ToolResult.error("CadGeneratorPlugin non inizializzato.")

    description: str = args["description"]
    raw_name = args.get("model_name") or f"model_{context.execution_id[:8]}"
    name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name)[:64]

    # 1. Verifica connessione microservizio
    if not await self._client.health_check():
        return ToolResult.error(
            f"TRELLIS microservice non raggiungibile a "
            f"{self._ctx.config.trellis.service_url}. "
            "Assicurarsi che il microservizio sia avviato:\n"
            "  cd trellis_server && .venv\\Scripts\\python.exe server.py"
        )

    # 2. VRAM swap + generazione
    try:
        gen_result, gen_error = await self._vram_swap_generate(description, name)
    except Exception as exc:
        return ToolResult.error(f"Errore generazione 3D: {exc}")

    if gen_error and gen_result is None:
        return ToolResult.error(gen_error)

    # 3. Download GLB dal microservizio e salva localmente
    try:
        glb_bytes = await self._client.download_model(gen_result.model_name)
        local_path = self._output_dir / f"{gen_result.model_name}.glb"
        local_path.write_bytes(glb_bytes)
    except Exception as exc:
        error_msg = f"Errore download modello: {exc}"
        if gen_error:
            error_msg = f"{gen_error}; {error_msg}"
        return ToolResult.error(error_msg)

    # 4. Restituisci URL per il frontend
    export_url = f"/api/cad/models/{gen_result.model_name}"
    payload = {
        "model_name": gen_result.model_name,
        "export_url": export_url,
        "format": "glb",
        "size_bytes": gen_result.size_bytes,
        "description": description,
    }

    warning = ""
    if gen_error:
        warning = f" (avviso: {gen_error})"

    return ToolResult(
        success=True,
        content=json.dumps(payload),
        content_type="application/vnd.omnia.cad-model+json",
    )
```

**Perché l'URL e non i bytes**: il tool restituisce solo il JSON con l'URL al file —
il front-end carica il binario GLB direttamente dalla route proxy `/api/cad/` tramite
una normale richiesta HTTP GET. Questo evita di passare file potenzialmente da decine
di MB attraverso il WebSocket, mantenendo il canale WebSocket per soli messaggi di
controllo leggeri. Pattern identico a quello usato per gli screenshot in Phase 5.

---

#### 12.7 — REST Proxy `/api/cad/` (`backend/api/routes/cad.py`)

**Ruolo**: serve i file GLB generati dal microservizio TRELLIS al frontend Electron.
Il proxy è necessario per mantenere il file serving sotto il dominio OMNIA (localhost:8000),
evitando problemi CSP nel renderer Electron.

Router con prefix e tag coerenti (pattern `tasks.py`, `memory.py`):

```python
router = APIRouter(prefix="/cad", tags=["cad"])
```

**Endpoint esposti:**

```
GET  /api/cad/models/{model_name}    — serve file GLB dal filesystem locale
GET  /api/cad/models                 — lista modelli generati (dal filesystem locale)
GET  /api/cad/health                 — health check del microservizio TRELLIS
```

**Implementazione `/api/cad/models/{model_name}`**:

```python
@router.get("/models/{model_name}")
async def get_model(
    model_name: str,
    request: Request,
) -> FileResponse:
    """Serve a generated GLB 3D model file.

    Args:
        model_name: Model identifier (alphanumeric + underscore only).

    Returns:
        FileResponse with the GLB binary file.

    Raises:
        HTTPException 400: Invalid model name.
        HTTPException 404: Model not found.
    """
    # Input validation anti-path-traversal
    if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", model_name):
        raise HTTPException(status_code=400, detail="Nome modello non valido.")

    ctx: AppContext = request.app.state.context
    output_dir = Path(ctx.config.trellis.model_output_dir)
    if not output_dir.is_absolute():
        output_dir = Path(ctx.config.project_root) / output_dir

    file_path = output_dir / f"{model_name}.glb"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Modello '{model_name}' non trovato.")

    # Verify the resolved path is within the output directory (symlink protection)
    if not file_path.resolve().is_relative_to(output_dir.resolve()):
        raise HTTPException(status_code=400, detail="Path non valido.")

    return FileResponse(
        path=file_path,
        media_type="model/gltf-binary",
        filename=f"{model_name}.glb",
    )
```

**Registrazione in `backend/api/routes/__init__.py`**:

```python
from backend.api.routes import audit, cad, calendar, chat, config, events, models, plugins, settings, tasks, voice

router.include_router(cad.router)  # /api/cad/*
```

**Sicurezza**:

- Validazione `model_name` con regex `[a-zA-Z0-9_]{1,64}` — previene path traversal
- `file_path.resolve().is_relative_to()` — protezione aggiuntiva contro symlink
- I file vengono serviti dal filesystem locale (`data/3d_models/`), non dal microservizio TRELLIS
  in tempo reale — nessun proxy HTTP-to-HTTP con rischi SSRF
- Nessuna autenticazione per v1 (OMNIA gira in locale — coerente con il resto delle API)

---

#### 12.8 — Frontend: `CADViewer.vue` (Three.js + GLTFLoader)

**Dipendenze da aggiungere a `frontend/package.json`**:

```bash
cd frontend
npm install three
npm install --save-dev @types/three
```

**CSP update in `frontend/src/main/index.ts`**:

Aggiungere `'wasm-unsafe-eval'` a `script-src` nella Content Security Policy per permettere
la decompressione Draco (opzionale per GLB, ma Three.js la usa se disponibile):

```typescript
// In webPreferences o CSP header:
// script-src 'self' 'wasm-unsafe-eval';
```

**Componente `frontend/src/renderer/src/components/chat/CADViewer.vue`**:

Il componente è lazy-loaded (`defineAsyncComponent`) per non aumentare il bundle iniziale
dell'app (Three.js pesa ~600KB gzip).

```vue
<script setup lang="ts">
/**
 * Interactive 3D model viewer using Three.js + GLTFLoader.
 *
 * Renders a GLB model generated by TRELLIS via the /api/cad/ proxy route.
 * Supports: orbit controls (drag/scroll/right-drag), zoom, auto-rotate toggle,
 * wireframe toggle, and model download.
 *
 * Props:
 *   modelUrl - Relative URL to the GLB file (e.g. /api/cad/models/xxx)
 *   modelName - Display name for the model (used in download filename)
 */
import { ref, onMounted, onUnmounted } from 'vue'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { resolveBackendUrl } from '@/services/api'

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
let scene: THREE.Scene | null = null
let frameId: number | null = null
let controls: InstanceType<typeof OrbitControls> | null = null
let loadedModel: THREE.Group | null = null

async function initScene(): Promise<void> {
  const container = containerRef.value
  if (!container) return

  const w = container.clientWidth
  const h = container.clientHeight || 360

  // Scene
  scene = new THREE.Scene()
  scene.background = new THREE.Color(0x1a1a2e)

  // Camera
  const camera = new THREE.PerspectiveCamera(50, w / h, 0.01, 10000)
  camera.position.set(0, 1.5, 3)

  // Lighting (PBR-friendly setup for GLB materials)
  const ambient = new THREE.AmbientLight(0xffffff, 0.4)
  scene.add(ambient)
  const dir1 = new THREE.DirectionalLight(0xffffff, 1.0)
  dir1.position.set(5, 10, 7)
  dir1.castShadow = true
  scene.add(dir1)
  const dir2 = new THREE.DirectionalLight(0xffffff, 0.3)
  dir2.position.set(-3, 5, -5)
  scene.add(dir2)
  // Environment hemisphere for natural fill
  const hemi = new THREE.HemisphereLight(0xddeeff, 0x0f0e0d, 0.5)
  scene.add(hemi)

  // Grid helper for spatial reference
  const grid = new THREE.GridHelper(10, 20, 0x333355, 0x222244)
  scene.add(grid)

  // Renderer
  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(w, h)
  renderer.setPixelRatio(window.devicePixelRatio)
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.0
  container.appendChild(renderer.domElement)

  // Controls
  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.05
  controls.autoRotate = autoRotate.value
  controls.autoRotateSpeed = 2.0

  // Load GLB
  const loader = new GLTFLoader()
  const fullUrl = resolveBackendUrl(props.modelUrl)

  try {
    const gltf = await new Promise<{ scene: THREE.Group }>((resolve, reject) => {
      loader.load(fullUrl, resolve, undefined, reject)
    })
    loadedModel = gltf.scene

    // Auto-fit camera to model bounding box
    const box = new THREE.Box3().setFromObject(loadedModel)
    const center = box.getCenter(new THREE.Vector3())
    const size = box.getSize(new THREE.Vector3()).length()

    loadedModel.position.sub(center)  // center the model at origin
    camera.position.set(0, size * 0.5, size * 1.5)
    camera.far = size * 10
    camera.updateProjectionMatrix()
    controls.target.set(0, 0, 0)
    controls.update()

    scene.add(loadedModel)
    loading.value = false

    // Render loop
    const animate = (): void => {
      frameId = requestAnimationFrame(animate)
      controls!.autoRotate = autoRotate.value
      controls!.update()
      renderer!.render(scene!, camera)
    }
    animate()
  } catch (err) {
    error.value = `Impossibile caricare il modello: ${err}`
    loading.value = false
  }

  // Resize observer
  const resizeObserver = new ResizeObserver(() => {
    if (!container || !renderer) return
    const nw = container.clientWidth
    const nh = container.clientHeight || 360
    camera.aspect = nw / nh
    camera.updateProjectionMatrix()
    renderer.setSize(nw, nh)
  })
  resizeObserver.observe(container)
}

function toggleWireframe(): void {
  wireframe.value = !wireframe.value
  if (loadedModel) {
    loadedModel.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const mat = child.material as THREE.MeshStandardMaterial
        mat.wireframe = wireframe.value
      }
    })
  }
}

function download(): void {
  const link = document.createElement('a')
  link.href = resolveBackendUrl(props.modelUrl)
  link.download = `${props.modelName ?? 'model'}.glb`
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
        <button @click="autoRotate = !autoRotate" :class="{ active: autoRotate }"
                title="Auto-rotazione">⟳</button>
        <button @click="toggleWireframe" :class="{ active: wireframe }"
                title="Wireframe">⬡</button>
        <button @click="resetCamera" title="Reset vista">⌖</button>
        <button @click="download" title="Scarica GLB">⬇</button>
      </div>
    </div>
    <div ref="containerRef" class="cad-viewer-canvas" :style="{ height: '360px' }">
      <div v-if="loading" class="cad-viewer-overlay">
        <div class="cad-viewer-spinner" />
        Generazione modello 3D in corso…
      </div>
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
.cad-viewer-actions button.active {
  border-color: #4fc3f7; color: #4fc3f7; background: rgba(79,195,247,0.1);
}
.cad-viewer-canvas { position: relative; width: 100%; }
.cad-viewer-overlay {
  position: absolute; inset: 0;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 12px;
  color: #b0bec5; font-size: 14px; background: rgba(26, 26, 46, 0.9);
}
.cad-viewer-error { color: #ef5350; }
.cad-viewer-spinner {
  width: 32px; height: 32px;
  border: 3px solid rgba(79, 195, 247, 0.2);
  border-top-color: #4fc3f7;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
```

**Lazy loading in `ToolExecutionIndicator.vue`** — usando `defineAsyncComponent`:

```typescript
import { defineAsyncComponent } from 'vue'

const CADViewer = defineAsyncComponent(
  () => import('./CADViewer.vue')
)
```

---

#### 12.9 — Frontend: Estensione `ToolExecutionIndicator.vue` + `types/chat.ts`

**`frontend/src/renderer/src/types/chat.ts`** — aggiunta dell'interfaccia `CadModelPayload`:

```typescript
/**
 * Payload JSON del ToolResult con content_type='application/vnd.omnia.cad-model+json'.
 * Generato da CadGeneratorPlugin.cad_generate().
 */
export interface CadModelPayload {
  model_name: string
  /** URL relativo della route proxy: /api/cad/models/{name} */
  export_url: string
  /** Formato: sempre "glb" per TRELLIS */
  format: string
  /** Dimensione file in bytes */
  size_bytes?: number
  /** Descrizione originale usata per la generazione */
  description?: string
}
```

**`ToolExecutionIndicator.vue`** — aggiunta del caso `application/vnd.omnia.cad-model+json`
nel template. La gestione segue il pattern esistente per `image/*`:

```typescript
// Nella sezione <script setup> — helper per parsare il payload
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
<!-- caso modello 3D (aggiunto in Fase 12) -->
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
  coerente con screenshot che presentano la stessa limitazione)

---

#### 12.10 — System Prompt Update (`config/system_prompt.md`)

Aggiungere una nuova sezione per il tool `cad_generate`:

```markdown
### Generazione 3D (cad_generate)

Quando l'utente chiede di creare, visualizzare o generare un oggetto 3D:

- Usa `cad_generate(description="...")` con una descrizione DETTAGLIATA dell'oggetto
- Più dettagliata è la descrizione, migliore sarà il risultato (forma, dimensioni,
  materiale apparente, stile, dettagli decorativi)
- Il modello 3D verrà generato automaticamente e visualizzato nel frontend
- NON scrivere codice CAD — il sistema usa una rete neurale image-to-3D (TRELLIS)
- Usa `model_name` descrittivi in inglese (es. "decorative_vase", "phone_stand")
- Se il risultato non soddisfa l'utente, riprova con una descrizione più precisa
- Avvisa l'utente che la generazione richiede 30-90 secondi

Esempi di buone descrizioni:
- "A sleek modern phone stand with curved edges, matte black finish, minimalist design"
- "A decorative vase, tall and slender, with Art Nouveau floral relief patterns"
- "A small gear mechanism with 12 teeth, industrial style, metallic appearance"

### Documentazione (ebook-mcp)

Se configurato, puoi consultare documenti PDF/EPUB:
- Usa `get_toc` per la struttura del documento prima di leggere sezioni specifiche
- Usa `get_chapter_markdown` per leggere solo i capitoli necessari
```

---

#### 12.11 — Dipendenze e Compatibilità

**Backend — nessuna nuova dipendenza Python:**

Il plugin `cad_generator` usa solo `httpx` (già presente) e `json` (stdlib).
TRELLIS e tutte le sue dipendenze pesanti (PyTorch, kaolin, flash-attn, xformers, spconv)
vivono nel venv isolato del microservizio `trellis_server/` — mai installate nel
venv OMNIA.

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

**Microservizio TRELLIS — processo separato:**

| Componente | Dettaglio |
|---|---|
| Repository | `sdbds/TRELLIS-for-windows` (MIT license) |
| Python | 3.10-3.12 (venv isolato, non condiviso con OMNIA) |
| CUDA | 12.4+ (toolkit installato a sistema) |
| VS Studio | 2022 con "Desktop development with C++" |
| Installer | `1、install-uv-qinglong.ps1` nella directory clonata |
| Run command | `.venv\Scripts\python.exe server.py --port 8090` |
| Verifica | `curl http://localhost:8090/health` |

Il microservizio TRELLIS non è un requisito hard di OMNIA: se non installato/avviato,
il plugin si carica, mostra status `DISCONNECTED` nella UI plugin, e il tool `cad_generate`
restituisce un messaggio di errore descrittivo con istruzioni di setup. Il resto dell'app
funziona normalmente.

**VRAM Budget (tabella aggiornata):**

| Componente | VRAM | Note |
|---|---|---|
| LLM (Qwen 3.5 9B, Q4) | ~10 GB | Scaricato durante generazione 3D (`auto_vram_swap`) |
| STT (faster-whisper) | ~1.5 GB | Rimane caricato — contribuisce al footprint totale |
| TTS (Piper) | ~200 MB | CPU-only per default |
| TRELLIS-image-large (1.2B) | ~12-16 GB | Caricato on-demand, scaricato dopo generazione |
| TRELLIS-text-large (1.1B) | ~10-12 GB | Alternativa consigliata su sistemi con 16GB per flusso text-only |
| Three.js viewer (GPU) | < 100 MB | GPU RAM del renderer Electron, non VRAM dedicata |
| ebook-mcp (uv) | 0 MB | CPU only |

**Flusso VRAM durante generazione 3D (con `auto_vram_swap: true`):**

```
Stato normale:              LLM (10GB) + STT (1.5GB)                         = ~11.5 GB
Tool execution (image-lg):  LLM unloaded + TRELLIS (15GB) + STT (1.5GB)    = ~16.5 GB  ← margine stretto su RTX 5080
Tool execution (text-lg):   LLM unloaded + TRELLIS (11GB) + STT (1.5GB)    = ~12.5 GB  ✓ sicuro
Post-generation:            TRELLIS unloaded + LLM (10GB) + STT (1.5GB)    = ~11.5 GB  (stato normale)
```

**Nota VRAM per RTX 5080 (16GB)**: TRELLIS-image-large richiede fino a 16GB per i
picchi di generazione (buffers intermedi inclusi). Su sistemi con esattamente 16GB e
STT caricato (~1.5GB), potrebbe verificarsi OOM. Opzioni:
1. Usare `TRELLIS-text-large` (1.1B, ~10-12GB) per flusso text-only — sempre sicuro
2. Aggiungere `stop_stt_during_generation: true` alla configurazione (implementazione futura)
3. Usare `TRELLIS-image-large` accettando il rischio di OOM occasionale

---

#### 12.12 — Test Suite Fase 12

**`backend/tests/test_trellis_client.py`**:

- `test_health_check_success`: mock httpx GET /health → `True`
- `test_health_check_failure_returns_false`: `ConnectError` → `False` (no raise)
- `test_generate_from_image_success`: mock POST /generate con file → `GenerationResult`
- `test_generate_from_text_success`: mock POST /generate con prompt → `GenerationResult`
- `test_generate_http_error`: mock 500 → `HTTPStatusError` propagato
- `test_download_model_success`: mock GET /models/{name} → bytes
- `test_download_model_exceeds_size`: mock 120MB response → `ValueError`
- `test_unload_model`: mock POST /unload → success, no raise
- `test_ssrf_validation_rejects_remote_url`: URL `http://192.168.1.200:8090` → `RuntimeError`
- `test_ssrf_validation_allows_localhost`: `http://localhost:8090` → nessun errore

**`backend/tests/test_cad_generator_plugin.py`**:

- `test_initialize_reachable`: mock health_check True → plugin status CONNECTED
- `test_initialize_unreachable_no_crash`: mock health_check False → plugin carica,
  warning loggato, nessun crash (graceful degradation)
- `test_cad_generate_tool_definition`: `get_tools()` restituisce `ToolDefinition` per
  `cad_generate` con `risk_level="safe"`, `timeout_ms=180000`
- `test_cad_generate_success`: mock generazione + download → `ToolResult.success=True`,
  `content_type="application/vnd.omnia.cad-model+json"`, content è JSON valido con
  `model_name` e `export_url`
- `test_cad_generate_microservice_offline`: mock health_check False →
  `ToolResult.success=False`, errore con istruzioni setup
- `test_cad_generate_generation_error`: mock generate 500 → `ToolResult.success=False`
- `test_cad_generate_auto_name`: `model_name` assente → nome generato da execution_id
- `test_cad_generate_sanitizes_name`: `model_name="test-model/v2"` → `"test_model_v2"`
- `test_vram_swap_unload_reload`: mock LM Studio list_loaded + unload + load →
  sequenza corretta di chiamate verificata
- `test_vram_swap_disabled`: `auto_vram_swap=false` → nessuna chiamata unload/load
- `test_vram_swap_reload_after_trellis_failure`: TRELLIS fallisce → LLM viene
  comunque ricaricato (garanzia di sicurezza)
- `test_cleanup_closes_client`: `cleanup()` → `client.close()` chiamato

**`backend/tests/test_cad_proxy_route.py`**:

- `test_get_model_success`: GET `/api/cad/models/test_cube` → mock file exists →
  `200 OK`, `Content-Type: model/gltf-binary`
- `test_get_model_not_found`: file non esiste → `404`
- `test_get_model_invalid_name`: `model_name="../../etc/passwd"` → `400 Bad Request`
- `test_get_model_plugin_not_active`: plugin disabilitato → config trellis assente → `404`
- `test_cad_health`: GET `/api/cad/health` → mock health_check True → `200 {"status": "ok"}`
- `test_cad_model_list`: GET `/api/cad/models` → listing directory locale → JSON array

**Verifica no-regression**: tutta la suite esistente deve passare invariata. In particolare,
verificare che `_tool_loop.py` (non modificato) gestisca correttamente il timeout esteso
(180s) del tool `cad_generate` e che `ToolResult` con `content_type` diverso da `image/*`
segua il path normale senza troncamenti.

---

#### 12.13 — File Structure Fase 12

```
trellis_server/                              ← microservizio separato (Python 3.10-3.12, gitignored)
├── server.py                                ← Mini FastAPI server (porta 8090)
├── 1、install-uv-qinglong.ps1                ← installer dal fork sdbds
├── .venv/                                   ← venv Python 3.10-3.12 isolato
└── ... (repo TRELLIS-for-windows)

backend/
├── plugins/
│   └── cad_generator/
│       ├── __init__.py                      ← PLUGIN_REGISTRY["cad_generator"]
│       ├── plugin.py                        ← CadGeneratorPlugin + VRAM orchestration
│       └── client.py                        ← TrellisClient (httpx → microservizio)
├── api/
│   └── routes/
│       ├── cad.py                           ← REST /api/cad/* (serve GLB locali)
│       └── __init__.py                      ← + cad.router
├── core/
│   └── config.py                            ← + TrellisServiceConfig + OmniaConfig.trellis
└── tests/
    ├── test_trellis_client.py
    ├── test_cad_generator_plugin.py
    └── test_cad_proxy_route.py

config/
├── default.yaml                             ← + trellis: section + ebook-mcp in mcp.servers
└── system_prompt.md                         ← + sezione cad_generate + documentazione

frontend/
├── package.json                             ← + three, @types/three
└── src/
    ├── main/
    │   └── index.ts                         ← + 'wasm-unsafe-eval' in CSP (per Draco)
    └── renderer/src/
        ├── components/
        │   └── chat/
        │       ├── CADViewer.vue            ← Three.js + GLTFLoader (nuovo)
        │       └── ToolExecutionIndicator.vue ← + caso content_type cad-model
        └── types/
            └── chat.ts                      ← + CadModelPayload interface

data/
└── 3d_models/                               ← file GLB generati (gitignored)
```

---

#### 12.14 — Ordine di Implementazione Consigliato

1. **`TrellisServiceConfig`** in `config.py` + `default.yaml` entry — zero dipendenze
2. **`trellis_server/server.py`** — microservizio standalone, testabile indipendentemente
3. **`TrellisClient`** + test `test_trellis_client.py` — layer I/O isolabile con mock
4. **`CadGeneratorPlugin`** + `__init__.py` + VRAM orchestration + test `test_cad_generator_plugin.py`
5. **`cad.py` route** + registrazione in `routes/__init__.py` + test `test_cad_proxy_route.py`
6. **`types/chat.ts`** — aggiunta `CadModelPayload` (frontend, zero rischio)
7. **`CADViewer.vue`** — componente Three.js GLTFLoader (frontend, standalone)
8. **`ToolExecutionIndicator.vue`** — aggiunta caso CAD (frontend, minimale)
9. **CSP update** — `'wasm-unsafe-eval'` in `index.ts` (1 riga)
10. **`config/system_prompt.md`** — aggiunta sezioni generazione 3D e documentazione
11. **`default.yaml`** — aggiunta entry `ebook-mcp` commentata in `mcp.servers`
12. **Test manuale**: installare TRELLIS-for-windows → avviare microservizio →
    attivare plugin → "crea un vaso decorativo" → verificare Three.js viewer nel frontend

---

#### 12.15 — Verifiche Fase 12

| Scenario | Comportamento atteso |
|---|---|
| "Crea un vaso decorativo Art Nouveau con rilievi floreali" | LLM scrive description → chiama `cad_generate` → VRAM swap (LLM unload) → TRELLIS genera GLB → VRAM swap (LLM reload) → `ToolResult(content_type="application/vnd.omnia.cad-model+json")` → frontend mostra `CADViewer.vue` con modello 3D interattivo |
| Utente ruota il modello | OrbitControls Three.js funzionanti — drag/scroll/pinch |
| Utente clicca "⬇ Scarica GLB" | `GET /api/cad/models/{name}` → download file .glb |
| TRELLIS microservizio non avviato | `health_check()` → False → `ToolResult(success=False, error_message="TRELLIS non raggiungibile... cd trellis_server && ...")` — nessun crash |
| Generazione 3D fallisce (CUDA OOM) | TRELLIS restituisce 500 → ToolResult error → LLM comunque ricaricato (garanzia) |
| `trellis.enabled: false` (default) | Plugin non caricato, zero overhead; altri plugin e chat invariati |
| auto_vram_swap: LLM unload + reload | LLM scaricato prima di TRELLIS, ricaricato dopo — verificare che risposta LLM continui correttamente |
| auto_vram_swap: LLM reload fallisce | Warning nel log + warning nel ToolResult → utente informato, può ricaricare manualmente |
| LLM chiede consultare docs | Se `ebook-mcp` configurato: tool MCP `get_toc` → capitoli → `get_chapter_markdown` |
| `ebook-mcp` non configurato | Zero impatto, tool non nel ToolRegistry |
| `model_name="../../../etc"` via tool | Sanitizzato a `"______etc"` dal plugin |
| GET `/api/cad/models/../../passwd` | Regex `[a-zA-Z0-9_]{1,64}` → `400 Bad Request` |
| Modello GLB > `max_model_size_mb` | `download_model()` → `ValueError` → ToolResult error |
| Conversazione ricaricata da DB | `CADViewer` non compare (content_type non persistito) — comportamento noto v1 |
| `GET /api/plugins` | Card `cad_generator` con status CONNECTED/DISCONNECTED |
| GPU con ≥ 24GB VRAM, `auto_vram_swap: false` | LLM e TRELLIS coesistono — nessun unload/reload |

---

### Fase 13 — Note System (Obsidian-like)

> **Obiettivo**: aggiungere a OMNIA un sistema di note personali ispirato a Obsidian.
> Radicalmente distinto dal Memory Service (Fase 9): la memoria è automatica, semantica
> e invisibile all'utente (accumulata in background, iniettata nell'LLM context). Le
> **note** sono documenti Markdown intenzionalmente creati dall'utente o dall'LLM su
> esplicita istruzione, organizzati in cartelle e tag, con wikilinks ed editing diretto
> nella UI. Con Fase 13 OMNIA diventa anche un **vault di conoscenza personale** al
> fianco dell'assistente conversazionale.

- [x] NotesConfig in config.py + default.yaml — §13.1
- [x] NoteServiceProtocol in protocols.py — §13.2
- [x] AppContext.note_service field — §13.2
- [x] NoteService (aiosqlite + FTS5 + sqlite-vec CRUD) — §13.3
- [x] App lifespan wiring (startup init + shutdown close) — §13.3
- [x] NotesPlugin (6 tool, schemi JSON completi) — §13.4
- [x] REST API /api/notes (7 endpoint) — §13.5
- [x] OmniaEvent NOTE_* events in event_bus.py — §13.6
- [x] System prompt guidelines — §13.7
- [x] Frontend types/notes.ts + stores/notes.ts — §13.8
- [x] services/api.ts aggiornato (metodi notes) — §13.8
- [x] NotesPageView.vue + NotesBrowser.vue + NoteEditor.vue + NotesBacklinks.vue — §13.8
- [x] Router entry /notes + sidebar link (AppSidebar.vue) — §13.8
- [ ] Test suite (4 file, 40+ test case) — §13.9
- [x] Dependencies (sqlite-vec + fastembed già in pyproject.toml) — §13.10

---

#### 13.0 — Analisi Vincoli e Scelte Architetturali

**Perché il Note System è un `BaseService` e NON un plugin standalone:**
- Le note sono infrastruttura di conoscenza personale, con REST API indipendente e UI
  dedicata — esattamente come `MemoryService` o `TaskScheduler`
- Il service gestisce il DB direttamente, viene iniettato in `AppContext` e può essere
  consumato sia dal plugin che dagli endpoint REST
- Il plugin `notes` delega tutta la logica a `ctx.note_service` senza conoscere SQL o
  embedding — separazione responsabilità pulita, identica al pattern Fase 9

**Perché DB separato `data/notes.db` e non `data/omnia.db`:**
- La tabella virtuale FTS5 (`note_fts`) usa `content=note_entries` (external content FTS5),
  che richiede trigger DDL per il sync; SQLAlchemy non gestisce trigger né tabelle virtuali
- Le tabelle sqlite-vec (`note_vectors`) sono incompatibili con `SQLModel.metadata.create_all`
- Identica motivazione di `data/memory.db` — nessuna contaminazione delle migration Alembic
- `NoteService` apre la propria connessione `aiosqlite` su `data/notes.db` separata

**Perché `NoteEntry` è un `__slots__` dataclass e non un SQLModel:**
- Identica motivazione a `MemoryEntry` (Fase 9): il service usa raw `aiosqlite` + SQL,
  la rappresentazione Python è separata dallo schema SQLite (che include tabelle virtuali)
- SQLModel su DB separato richiederebbe un secondo engine SQLAlchemy — overhead inutile
- `NoteEntry` è usata solo come return type del service — nessuna feature ORM necessaria

**Perché sia FTS5 (full-text) sia sqlite-vec (semantico):**
- FTS5: ricerche precise (titolo, parole chiave esatte, filtri tag) — zero latency, zero embedding
- sqlite-vec: ricerche concettuali ("trova note su machine learning" anche senza la parola esatta)
  — richiede embedding, ma è opzionale (`embedding_enabled: bool` in config)
- Le due ricerche si fondono: FTS results first (più precisi), poi vec (più ampi),
  con dedup per ID — massima coverage senza duplicati

**Distinzione note vs memoria:**

| Aspetto          | Memory Service (Fase 9)       | Note System (Fase 13)                |
|------------------|-------------------------------|--------------------------------------|
| Origine          | Automatica (LLM decide)       | Intenzionale (utente/LLM su comando) |
| Formato          | Fatti brevi (≤ 1000 char)     | Documenti Markdown lunghi            |
| Organizzazione   | Categoria + scope             | Folder + tag + wikilinks             |
| UI               | MemoryManager (gestione)      | NoteEditor (editing Markdown diretto)|
| Ricerca          | Solo semantica                | Full-text + semantica                |
| LLM context      | Iniettato automaticamente     | Mai iniettato (solo su esplicit tool)|
| Lifecycle        | Auto-cleanup (TTL + days)     | Permanente fino a delete esplicito   |

---

#### 13.1 — NotesConfig (`backend/core/config.py`)

```python
class NotesConfig(BaseSettings):
    """Note system (Obsidian-like vault) configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_NOTES__")

    enabled: bool = False
    """Abilita il Note System. False di default (opt-in esplicito)."""

    db_path: str = "data/notes.db"
    """Path del file SQLite dedicato alle note (separato da omnia.db e memory.db)."""

    embedding_enabled: bool = True
    """Abilita ricerca semantica tramite EmbeddingClient (richiede LM Studio online
    o fastembed installato). Se False, solo FTS5 full-text search."""

    embedding_model: str = "nomic-embed-text"
    """Nome modello embedding per /v1/embeddings (stessa logica di MemoryConfig)."""

    embedding_dim: int = 768
    """Dimensione vettori embedding. Deve corrispondere al modello scelto."""

    embedding_fallback: bool = True
    """Se True, usa fastembed (CPU) come fallback se l'API embedding LM Studio non è disponibile
    (identico al campo `embedding_fallback` in `MemoryConfig`)."""

    max_content_chars_llm: int = 8000
    """Massimo caratteri del contenuto di una nota inviato all'LLM."""

    semantic_threshold: float = 0.70
    """Score minimo coseno per includere un risultato semantico (0.0–1.0)."""

    max_search_results: int = 20
    """Massimo risultati per query di ricerca (FTS + semantica combinata)."""
```

Aggiunta a `OmniaConfig` (dopo il campo `memory`):
```python
notes: NotesConfig = Field(default_factory=NotesConfig)
```

Config YAML entry (`config/default.yaml`):
```yaml
# Nuova sezione notes (dopo memory:):
notes:
  enabled: false
  db_path: "data/notes.db"
  embedding_enabled: true
  embedding_model: "nomic-embed-text"
  embedding_dim: 768
  embedding_fallback: true
  max_content_chars_llm: 8000
  semantic_threshold: 0.70
  max_search_results: 20

# In plugins.enabled, aggiungere (commentato per default-off):
# - notes  # abilitare con notes.enabled: true
```

---

#### 13.2 — NoteServiceProtocol + AppContext

Aggiunta in `backend/core/protocols.py` (dopo `MemoryServiceProtocol`):

```python
@runtime_checkable
class NoteServiceProtocol(Protocol):
    """Protocol for the Note Service (Obsidian-like note vault)."""

    async def initialize(self) -> None: ...
    async def create(
        self,
        title: str,
        content: str,
        folder_path: str = "",
        tags: list[str] | None = None,
    ) -> "NoteEntry": ...
    async def get(self, note_id: str) -> "NoteEntry | None": ...
    async def update(
        self,
        note_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        folder_path: str | None = None,
        tags: list[str] | None = None,
        pinned: bool | None = None,
    ) -> "NoteEntry | None": ...
    async def delete(self, note_id: str) -> bool: ...
    async def search(
        self,
        query: str,
        folder: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list["NoteEntry"]: ...
    async def list(
        self,
        folder: str | None = None,
        tags: list[str] | None = None,
        pinned_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> "tuple[list[NoteEntry], int]": ...
    async def close(self) -> None: ...
```

Aggiunta in `backend/core/context.py` (campo opzionale, dopo `memory_service`):
```python
note_service: NoteServiceProtocol | None = None
```

---

#### 13.3 — NoteService (`backend/services/note_service.py`)

**Ruolo**: layer di accesso alle note. Non conosce tool, LLM o plugin — solo CRUD con
FTS5 + sqlite-vec. Pattern identico a `MemoryService` (Fase 9).

**`NoteEntry` dataclass**:
```python
@dataclasses.dataclass(slots=True)
class NoteEntry:
    """In-memory representation of a single note. NOT a SQLModel table."""
    id: str               # uuid str
    title: str
    content: str          # Markdown
    folder_path: str      # es. "lavoro/progetti" (default "")
    tags: list[str]       # es. ["python", "ai"]
    wikilinks: list[str]  # estratti automaticamente da [[Titolo]] nel content
    pinned: bool
    created_at: str       # ISO 8601 UTC
    updated_at: str       # ISO 8601 UTC
```

**Estrazione wikilinks**: `NoteService` include un metodo privato
`_extract_wikilinks(content: str) -> list[str]` che usa regex `\[\[(.+?)\]\]`
per estrarre i titoli referenziati. Viene chiamato automaticamente in `create()` e
`update()` ogni volta che il contenuto cambia — nessuna interazione LLM richiesta.
I wikilinks estratti vengono salvati nella colonna `wikilinks` come JSON array.

> **Nota v1**: `wikilinks` sono estratti e persistiti ma non risolti in link navigabili
> nell'editor. La navigazione via click su `[[Titolo]]` e il pannello backlinks
> appartengono alla UI (§13.8). La Graph View è §13.14 (v2 feature).

**Schema DB** (creato da `NoteService.initialize()` via raw SQL — non SQLAlchemy):

```sql
-- Tabella principale
CREATE TABLE IF NOT EXISTS note_entries (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    folder_path TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]',     -- JSON array
    wikilinks   TEXT NOT NULL DEFAULT '[]',     -- JSON array, auto-extracted via regex
    pinned      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_note_folder  ON note_entries(folder_path);
CREATE INDEX IF NOT EXISTS ix_note_pinned  ON note_entries(pinned);
CREATE INDEX IF NOT EXISTS ix_note_updated ON note_entries(updated_at);

-- Tabella vettori (sqlite-vec, creata solo se embedding_enabled)
CREATE VIRTUAL TABLE IF NOT EXISTS note_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[768] distance_metric=cosine
);

-- FTS5 external content (keyword search)
CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
    title, content,
    content=note_entries,
    content_rowid=rowid
);
-- Trigger per sync automatico FTS ↔ note_entries
CREATE TRIGGER IF NOT EXISTS note_fts_insert AFTER INSERT ON note_entries BEGIN
    INSERT INTO note_fts(rowid, title, content)
    VALUES (NEW.rowid, NEW.title, NEW.content);
END;
CREATE TRIGGER IF NOT EXISTS note_fts_update AFTER UPDATE ON note_entries BEGIN
    INSERT INTO note_fts(note_fts, rowid, title, content)
    VALUES ('delete', OLD.rowid, OLD.title, OLD.content);
    INSERT INTO note_fts(rowid, title, content)
    VALUES (NEW.rowid, NEW.title, NEW.content);
END;
CREATE TRIGGER IF NOT EXISTS note_fts_delete AFTER DELETE ON note_entries BEGIN
    INSERT INTO note_fts(note_fts, rowid, title, content)
    VALUES ('delete', OLD.rowid, OLD.title, OLD.content);
END;
```

**Struttura `NoteService`**:
```
NoteService
├── __init__(config, llm_base_url)  — config + LLM base URL; NESSUNA I/O (identico a MemoryService)
├── initialize()                — carica sqlite-vec se enabled, crea tabelle e indici,
│                                 crea EmbeddingClient (OpenAI + fastembed fallback)
├── create(title, content, ...) → NoteEntry — insert + embed + FTS auto (trigger)
├── get(note_id)                → NoteEntry | None
├── update(note_id, **fields)   → NoteEntry | None — UPDATE + RE-embed se content cambia
├── delete(note_id)             → bool — DELETE cascades a note_vectors e FTS (trigger)
├── search(query, folder, tags, limit) → list[NoteEntry]
│   ├── _fts_search(query)      → list[str]          — IDs da FTS5 MATCH
│   └── _vec_search(query, k)   → list[str]          — IDs da note_vectors MATCH
│   ─── merge(fts_ids, vec_ids) → list[NoteEntry]    — union + dedup (FTS first) + filter
├── list(folder, tags, pinned_only, limit, offset) → (list[NoteEntry], int)
└── close()                     — chiude connessione aiosqlite
```

**`NoteService.search()` — fusione FTS + semantico (identico al pattern MemoryService.search)**:

```python
async def search(
    self,
    query: str,
    folder: str | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[NoteEntry]:
    seen_ids: set[str] = set()
    merged: list[NoteEntry] = []

    # 1. FTS5 full-text search (preciso, zero latency)
    fts_ids = await self._fts_search(query, limit)
    for note_id in fts_ids:
        entry = await self.get(note_id)
        if entry and self._matches_filters(entry, folder, tags):
            seen_ids.add(note_id)
            merged.append(entry)

    # 2. Semantic search (opzionale, se embedding disponibile)
    if self._embedding and len(merged) < limit:
        try:
            vec = await self._embedding.encode(query)
            vec_ids = await self._vec_search(vec, limit * 2)
            for note_id in vec_ids:
                if note_id in seen_ids:
                    continue
                entry = await self.get(note_id)
                if entry and self._matches_filters(entry, folder, tags):
                    seen_ids.add(note_id)
                    merged.append(entry)
                    if len(merged) >= limit:
                        break
        except Exception as exc:
            logger.warning("NoteService semantic search failed: {}", exc)

    return merged[:limit]
```

**`_resolve_vec_extension_path()`**: identica a `MemoryService` — gestisce dev vs PyInstaller bundle.

**`initialize()`** — abilita e carica sqlite-vec (solo se `embedding_enabled`):
```python
async def initialize(self) -> None:
    async with aiosqlite.connect(self._db_path) as conn:
        if self._config.embedding_enabled:
            conn.enable_load_extension(True)
            conn.load_extension(str(_resolve_vec_extension_path()))
            conn.enable_load_extension(False)
        # Create tables, indexes, triggers
        await conn.executescript(_SCHEMA_SQL)
        await conn.commit()
    # EmbeddingClient: same pattern as MemoryService (OpenAI + fastembed fallback)
    if self._config.embedding_enabled:
        self._embedding = EmbeddingClient(
            base_url=self._llm_base_url,  # stored in __init__(config, llm_base_url)
            model=self._config.embedding_model,
            dim=self._config.embedding_dim,
        )
```

**Startup in `app.py`** (dopo `MemoryService` init, prima di `PluginManager`):
```python
if config.notes.enabled:
    from backend.services.note_service import NoteService
    note_service = NoteService(config.notes, config.llm.base_url)
    try:
        await note_service.initialize()
        ctx.note_service = note_service
        logger.info("Note service started")
    except Exception as exc:
        logger.warning("Note service failed to start: {}", exc)
        await note_service.close()  # cleanup parziale (identico a MemoryService)
```

**Shutdown** (nella sezione shutdown, accanto a `memory_service`):
```python
if ctx.note_service:
    try:
        await ctx.note_service.close()
    except Exception as exc:
        logger.error("Note service shutdown error: {}", exc)
```

---

#### 13.4 — NotesPlugin (`backend/plugins/notes/`)

**Ruolo**: espone 6 tool LLM per interagire con le note. Non contiene logica DB — delega
tutto a `ctx.note_service`. Pattern identico a `MemoryPlugin` (Fase 9).

```
backend/plugins/notes/
├── __init__.py    — import + PLUGIN_REGISTRY["notes"] = NotesPlugin
└── plugin.py      — NotesPlugin(BasePlugin)
```

`__init__.py`:
```python
"""O.M.N.I.A. — Notes plugin package.

Importing this module registers NotesPlugin in the static PLUGIN_REGISTRY.
"""
from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.notes.plugin import NotesPlugin  # noqa: F401

PLUGIN_REGISTRY["notes"] = NotesPlugin
```

**Tool definitions**:

| Tool | risk_level | requires_confirmation | Descrizione |
|---|---|---|---|
| `create_note` | `safe` | `False` | Crea una nuova nota Markdown con titolo, contenuto, cartella e tag |
| `read_note` | `safe` | `False` | Legge il contenuto completo di una nota per ID |
| `update_note` | `safe` | `False` | Aggiorna titolo, contenuto, cartella, tag o stato pinned di una nota |
| `delete_note` | `medium` | `True` | Elimina una nota in modo permanente (irreversibile) |
| `search_notes` | `safe` | `False` | Ricerca FTS5 + semantica nelle note |
| `list_notes` | `safe` | `False` | Elenca note con filtri opzionali per cartella, tag, pinned |

**Schema tool `create_note`**:
```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "description": "Titolo conciso della nota.",
      "maxLength": 255
    },
    "content": {
      "type": "string",
      "description": "Corpo della nota in formato Markdown.",
      "maxLength": 50000
    },
    "folder_path": {
      "type": "string",
      "description": "Cartella di destinazione (es. 'lavoro/progetti'). Default: root.",
      "default": ""
    },
    "tags": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Lista tag per categorizzare la nota.",
      "default": []
    }
  },
  "required": ["title", "content"]
}
```

**Schema tool `search_notes`**:
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Testo da cercare nelle note (full-text e semantico).",
      "maxLength": 500
    },
    "folder": {
      "type": "string",
      "description": "Filtra per cartella (opzionale)."
    },
    "tags": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Filtra per tag (opzionale, AND logic)."
    },
    "limit": {
      "type": "integer",
      "default": 10,
      "minimum": 1,
      "maximum": 20
    }
  },
  "required": ["query"]
}
```

**Schema tool `read_note`**:
```json
{
  "type": "object",
  "properties": {
    "note_id": {
      "type": "string",
      "description": "UUID della nota da leggere (ottenuto tramite search_notes o list_notes)."
    }
  },
  "required": ["note_id"]
}
```

**Schema tool `update_note`**:
```json
{
  "type": "object",
  "properties": {
    "note_id": {
      "type": "string",
      "description": "UUID della nota da aggiornare."
    },
    "title": {
      "type": "string",
      "description": "Nuovo titolo (opzionale, invariato se omesso).",
      "maxLength": 255
    },
    "content": {
      "type": "string",
      "description": "Nuovo corpo Markdown (opzionale, invariato se omesso).",
      "maxLength": 50000
    },
    "folder_path": {
      "type": "string",
      "description": "Nuova cartella di destinazione (opzionale)."
    },
    "tags": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Nuova lista tag completa, sostituisce quella esistente (opzionale)."
    },
    "pinned": {
      "type": "boolean",
      "description": "Nuovo stato pinned (opzionale)."
    }
  },
  "required": ["note_id"]
}
```

**Schema tool `delete_note`**:
```json
{
  "type": "object",
  "properties": {
    "note_id": {
      "type": "string",
      "description": "UUID della nota da eliminare definitivamente."
    }
  },
  "required": ["note_id"]
}
```

**Schema tool `list_notes`**:
```json
{
  "type": "object",
  "properties": {
    "folder": {
      "type": "string",
      "description": "Filtra per cartella (opzionale, es. 'lavoro/progetti')."
    },
    "tags": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Filtra per tag (opzionale, AND logic — deve avere TUTTI i tag)."
    },
    "pinned_only": {
      "type": "boolean",
      "description": "Se true, restituisce solo le note pinnate.",
      "default": false
    },
    "limit": {
      "type": "integer",
      "description": "Massimo risultati (1–50). Default: 20.",
      "default": 20,
      "minimum": 1,
      "maximum": 50
    }
  }
}
```

**Regola `requires_confirmation=False` per operazioni non distruttive**: `create_note`,
`read_note`, `update_note`, `search_notes`, `list_notes` sono tutte reversibili o
read-only — richiedere conferma ogni volta renderebbe l'esperienza insopportabile.
`delete_note` è irreversibile → `requires_confirmation=True`, `risk_level="medium"`.

**Edge case**: se `ctx.note_service is None` (servizio non avviato o `notes.enabled=False`) →
tutti i tool restituiscono `ToolResult(success=False, error_message="Note Service non attivo.
Abilitare notes.enabled: true in config.")`.

---

#### 13.5 — REST API (`backend/api/routes/notes.py`)

Endpoint per la UI di gestione note (pattern identico a `/api/memory`):

```
GET    /api/notes                  — lista note (filtri query string: folder, tags, pinned, q, limit, offset)
POST   /api/notes                  — crea nota
GET    /api/notes/{note_id}        — dettaglio nota singola
PUT    /api/notes/{note_id}        — aggiorna nota
DELETE /api/notes/{note_id}        — elimina nota
POST   /api/notes/search           — ricerca semantica + FTS (body JSON)
GET    /api/notes/folders          — lista cartelle con conteggio note
```

```python
router = APIRouter(prefix="/notes", tags=["notes"])
```

Registrazione in `backend/api/routes/__init__.py`:
```python
# 1. Aggiungere 'notes' all'import esistente (unica riga con tutti i moduli):
from backend.api.routes import audit, cad, calendar, chat, config, events, mcp, mcp_memory, memory, models, notes, plugins, settings, voice

# 2. Aggiungere include_router dopo memory.router:
router.include_router(notes.router)  # dopo: router.include_router(memory.router)
```

> **⚠️ Ordine definizione endpoint critico**: in FastAPI, `GET /api/notes/folders`
> (path statico) **deve essere definito prima** di `GET /api/notes/{note_id}` (path dinamico)
> nel file `notes.py`, altrimenti FastAPI matcha `"folders"` come `note_id`.

Ogni endpoint usa `ctx: AppContext = Depends(get_context)` e restituisce `503` se
`ctx.note_service is None`. Valida `note_id` come stringa UUID (anti-IDOR).

---

#### 13.6 — OmniaEvent Updates (`backend/core/event_bus.py`)

Tre nuovi eventi aggiunti al `OmniaEvent` StrEnum (senza modificare quelli esistenti):

```python
# Note events (Phase 13)
NOTE_CREATED = "note.created"
"""Emesso con note_id=str, title=str alla creazione di una nota."""

NOTE_UPDATED = "note.updated"
"""Emesso con note_id=str, title=str all'aggiornamento di una nota."""

NOTE_DELETED = "note.deleted"
"""Emesso con note_id=str alla cancellazione di una nota."""
```

Gli eventi vengono emessi dal plugin `notes` dopo ogni tool call write (come il pattern
`calendar.reminder` in `CalendarPlugin`). Il plugin non ha dipendenze dirette sull'EventBus —
li emette tramite `ctx.event_bus.emit(OmniaEvent.NOTE_CREATED, note_id=entry.id, ...)`.

---

#### 13.7 — System Prompt Update (`config/system_prompt.md`)

Aggiungere sezione nella sezione `tools`:

```yaml
notes:
  distinction: "Le NOTE sono documenti Markdown intenzionali creati su richiesta esplicita.
    DIVERSO dal remember() che salva fatti brevi automaticamente. Usa le note per contenuti
    lunghi, strutturati, che l'utente vorrà rivedere e modificare direttamente nell'UI."
  create_note: "usa quando l'utente vuole creare un documento (ricetta, riassunto, schema,
    piano di progetto, ecc.). Scegli titolo chiaro e folder_path coerente con il contenuto."
  read_note: "usa per leggere/riepilogare una nota specifica. Prima usa search_notes per
    trovare l'ID corretto se non lo conosci."
  update_note: "usa per aggiornare contenuto di una nota esistente. MAI creare una nota
    duplicata se la nota già esiste — usa update_note invece."
  search_notes: "usa prima di read o update per trovare note per tema. Restituisce titoli
    e ID — poi leggi con read_note solo se serve il contenuto completo."
  delete_note: "usa SOLO su richiesta esplicita dell'utente. Richiede conferma utente."
  list_notes: "usa per mostrare l'organizzazione del vault (cartelle, tag, note pinnate)."
```

---

#### 13.8 — Frontend

**Nuovi tipi TypeScript** (`frontend/src/renderer/src/types/notes.ts`):

```typescript
/** A single note in the vault. Mirrors backend NoteEntry. */
export interface Note {
  id: string
  title: string
  content: string       // Markdown
  folder_path: string
  tags: string[]
  wikilinks: string[]   // titoli estratti da [[...]], usati per backlinks panel
  pinned: boolean
  created_at: string    // ISO 8601
  updated_at: string
}

export interface NoteSearchResult {
  notes: Note[]
  total: number
  query: string
}

export interface NoteFolder {
  path: string
  count: number
  children: NoteFolder[]
}
```

**Pinia store** (`frontend/src/renderer/src/stores/notes.ts`):

Usa **Setup API** (`defineStore('notes', () => {...})`), identico a `stores/memory.ts`.
Nessuna Options API. Stato tramite `ref<T>()`, azioni come `async function`.

```typescript
// Pattern Setup API (come stores/memory.ts):
export const useNotesStore = defineStore('notes', () => {
  // state — tutti ref()
  const notes = ref<Note[]>([])
  const total = ref<number>(0)
  const currentNote = ref<Note | null>(null)
  const folders = ref<NoteFolder[]>([])
  const activeFolder = ref<string | null>(null)
  const activeTags = ref<string[]>([])
  const searchQuery = ref<string>('')
  const loading = ref(false)
  const error = ref<string | null>(null)

  // actions — async functions con try/catch + finally { loading.value = false }
  // Tutte chiamano api.ts (mai fetch diretta) — stesso pattern di useMemoryStore:
  // loadNotes(filters?)     — GET /api/notes      (via api.getNotes)
  // loadNote(id)            — GET /api/notes/{id} (via api.getNote)
  // createNote(req)         — POST /api/notes     (via api.createNote)
  // updateNote(id, changes) — PUT /api/notes/{id} (via api.updateNote)
  // deleteNote(id)          — DELETE /api/notes/{id} (via api.deleteNote)
  // searchNotes(q, filters) — POST /api/notes/search (via api.searchNotes)
  // loadFolders()           — GET /api/notes/folders (via api.getNoteFolders)

  return { notes, total, currentNote, folders, activeFolder, activeTags,
           searchQuery, loading, error, loadNotes, loadNote, createNote,
           updateNote, deleteNote, searchNotes, loadFolders }
})
```

> **`services/api.ts` — aggiornamento richiesto**: aggiungere i metodi notes al client
> centralizzato (`api.getNotes`, `api.getNote`, `api.createNote`, `api.updateNote`,
> `api.deleteNote`, `api.searchNotes`, `api.getNoteFolders`) seguendo esattamente
> il pattern dei metodi memory (`api.getMemories`, `api.searchMemories`, ecc.).
> Il store non chiama mai `fetch()` direttamente.

**Componenti Vue** (in `frontend/src/renderer/src/`):

1. **`views/NotesPageView.vue`** — vista principale a tre colonne
   - Stesso contenitore minimale di `CalendarPageView.vue` (lazy-load sub-componenti)
   - Layout flex-row: `NotesBrowser.vue` (280px, fisso) + `NoteEditor.vue` (flex-1) +
     `NotesBacklinks.vue` (240px, collassabile, visibile solo quando una nota è aperta)

2. **`components/notes/NotesBrowser.vue`**:
   - Folder tree navigabile (click → filtra per cartella; cartelle annidate con indent)
   - Tag cloud cliccabili (filtro per tag, multiple selection con toggle)
   - Lista note con titolo + anteprima 2 righe del contenuto + timestamp relativo
   - Note pinnate in cima con indicatore visivo (icona 📌)
   - Input ricerca con debounce 300ms → `store.searchNotes(query)` → lista reagisce live
   - Pulsante "Nuova nota" → `store.createNote({ title: 'Senza titolo', content: '', folder_path: activeFolder })` → apre la nota nel NoteEditor
   - Nessuno stato locale: tutto da `useNotesStore()` (cartella attiva, tag attivi, note filtrate)

3. **`components/notes/NoteEditor.vue`**:
   - `<textarea>` monospace per editing Markdown raw (v1 — nessun rich editor WYSIWYG)
   - Toggle preview (pulsante nel header) → mostra rendered HTML via `useMarkdown(content)`
     (composable già esistente in `composables/useMarkdown.ts`)
   - Header: input titolo inline editabile, folder selector `<select>`, tag chips con
     aggiunta/rimozione inline (Enter per aggiungere, × per rimuovere)
   - Autosave: `watch(content, debounce(() => store.updateNote(id, { content }), 800))`
   - Indicatore stato: `"Salvato ✓"` / `"Salvataggio…"` nel header (stato locale reattivo)
   - Pulsante pin/unpin + pulsante elimina (apre `useModal` confirm dialog — composable già esistente)
   - I wikilinks `[[Titolo]]` nel testo sono **non-cliccabili in v1** (testo puro nella textarea)

4. **`components/notes/NotesBacklinks.vue`** *(nuovo, collassabile)*:
   - Mostra le note che contengono `[[Titolo della nota corrente]]` nei loro `wikilinks[]`
   - Dati: `store.notes.filter(n => n.wikilinks.includes(currentNote.title))` — zero chiamate API extra
   - Lista cliccabile → click → `store.loadNote(id)` → apre la nota referenziante
   - Visibile solo quando `currentNote !== null`; collassabile con toggle (titolo: "Backlinks")
   - In assenza di backlinks: placeholder "Nessuna nota fa riferimento a questa"

4. **Router entry** (`frontend/src/renderer/src/router/index.ts`):
   ```typescript
   {
     path: '/notes',
     name: 'notes',
     component: () => import('../views/NotesPageView.vue')
   }
   ```
   Aggiungere alla lista `routes[]` dopo la voce `calendar`.

5. **Sidebar link** (`components/sidebar/AppSidebar.vue`): aggiungere nella sezione `<nav>`
   della sidebar, che contiene già i link per `/settings`, `/assistant` e `/hybrid`.
   Il calendario **non** ha un link diretto nella nav (usa `CalendarWidget` con
   `router.push()` interno) — le note invece usano un link esplicito nella nav:
   ```vue
   <router-link to="/notes" class="sidebar__link" active-class="sidebar__link--active">
     <span class="sidebar__link-icon">📝</span>
     <span class="sidebar__link-label">Note</span>
   </router-link>
   ```

---

#### 13.9 — Test Suite Fase 13

**`backend/tests/test_note_service.py`**:
- `test_create_and_get`: crea nota → get per ID → tutti i campi corretti
- `test_update_note_fields`: crea → update titolo + tags → get → valori aggiornati
- `test_wikilinks_extracted_on_create`: crea nota con `[[Link A]]` nel content → wikilinks==["Link A"]
- `test_wikilinks_updated_on_content_change`: update content con nuovo `[[Link B]]` → wikilinks aggiornati
- `test_delete_note`: crea → delete → get restituisce `None`
- `test_fts_search_finds_match`: crea nota con keyword → search query → trovata
- `test_fts_search_no_match`: search query irrilevante → lista vuota
- `test_semantic_search_mock`: mock EmbeddingClient → search → risultato sopra threshold
- `test_semantic_threshold_filtered`: score coseno < threshold → non restituito
- `test_list_folder_filter`: 3 note in cartelle diverse → `list(folder="lavoro")` → solo 1
- `test_list_tag_filter`: note con tag diversi → filtro tag → solo matching
- `test_list_pinned_only`: pin nota → `list(pinned_only=True)` → solo pinnate
- `test_embedding_disabled_no_vec`: `embedding_enabled=False` → init senza sqlite-vec load
- `test_service_disabled_no_crash`: `notes.enabled=False` → service non inizializzato, zero crash

**`backend/tests/test_note_plugin.py`**:
- `test_create_note_tool`: chiama `create_note` → `NoteService.create()` → `ToolResult(success=True)`
- `test_read_note_existing`: chiama `read_note` con ID valido → contenuto nel result
- `test_read_note_not_found`: ID inesistente → `ToolResult(success=False)` con error_message
- `test_update_note_tool`: `update_note` con nuovi campi → `NoteService.update()` chiamato
- `test_delete_note_requires_confirmation`: `delete_note` ha `requires_confirmation=True`
- `test_search_notes_delegates`: `search_notes` → `NoteService.search()` → risultati JSON
- `test_list_notes_delegates`: `list_notes` → `NoteService.list()` → lista JSON
- `test_service_unavailable_all_tools`: `ctx.note_service = None` → tutti i tool errore graceful

**`backend/tests/test_notes_api.py`**:
- CRUD completo via `AsyncClient` (pattern identico a `test_memory_api.py`)
- `test_list_with_folder_filter`: `GET /api/notes?folder=lavoro` → solo note in quella cartella
- `test_search_endpoint`: `POST /api/notes/search` con `{"query": "python"}` → risultati
- `test_get_folders`: `GET /api/notes/folders` → struttura ad albero cartelle
- `test_note_id_invalid`: UUID non valido → `422 Unprocessable Entity`
- `test_service_unavailable_503`: `ctx.note_service = None` → `503 Service Unavailable`

**`backend/tests/test_note_events.py`** (integrazione EventBus):
- `test_note_created_event`: `create_note` tool → evento `NOTE_CREATED` emesso sul bus
- `test_note_updated_event`: `update_note` tool → evento `NOTE_UPDATED` emesso
- `test_note_deleted_event`: `delete_note` tool → evento `NOTE_DELETED` emesso

**Verifica no-regression** (pre-PR): tutta la suite esistente deve passare invariata.

---

#### 13.10 — Dipendenze e Compatibilità

**Nessuna nuova dipendenza** — tutto già presente in `pyproject.toml`:
- `sqlite-vec >= 0.1.6` — già installato per `MemoryService` (Fase 9)
- `fastembed >= 0.3` — già installato come fallback embedding (Fase 9)
- `aiosqlite` — già presente (usato da `MemoryService` e da `MemoryService`)

**Compatibilità PyInstaller**: identica a `MemoryService` — `_resolve_vec_extension_path()`
gestisce dev (`importlib.resources`) e bundle PyInstaller (`sys._MEIPASS`).

**VRAM impact**:
| Configurazione | VRAM aggiuntiva |
|---|---|
| Note FTS5 search only | 0 MB — SQLite CPU puro |
| Note semantic search via LM Studio | 0 MB (condiviso con MemoryService se embedding già caricato) |
| Note semantic search via fastembed | 0 MB VRAM (CPU-only) |

---

#### 13.11 — File Structure Fase 13

```
backend/
├── services/
│   └── note_service.py              ← NoteService (aiosqlite + FTS5 + sqlite-vec)
├── plugins/
│   └── notes/
│       ├── __init__.py              ← import + PLUGIN_REGISTRY["notes"] = NotesPlugin
│       └── plugin.py               ← NotesPlugin con 6 tool
├── api/
│   └── routes/
│       └── notes.py                ← REST /api/notes/*
├── core/
│   ├── config.py                   ← + NotesConfig + OmniaConfig.notes field
│   ├── protocols.py                ← + NoteServiceProtocol
│   ├── context.py                  ← + note_service: NoteServiceProtocol | None = None
│   ├── event_bus.py                ← + NOTE_CREATED / NOTE_UPDATED / NOTE_DELETED
│   └── app.py                      ← + NoteService init nel lifespan
└── tests/
    ├── test_note_service.py
    ├── test_note_plugin.py
    ├── test_notes_api.py
    └── test_note_events.py

frontend/src/renderer/src/
├── services/
│   └── api.ts                      ← + metodi notes (getNotes, getNote, createNote, updateNote,
│                                       deleteNote, searchNotes, getNoteFolders)
├── types/
│   └── notes.ts                    ← Note, NoteSearchResult, NoteFolder types
├── stores/
│   └── notes.ts                    ← Pinia notes store (Setup API)
├── views/
│   └── NotesPageView.vue           ← Vista split (browser + editor)
├── components/
│   ├── sidebar/
│   │   └── AppSidebar.vue          ← + router-link /notes nella sezione <nav>
│   └── notes/
│       ├── NotesBrowser.vue        ← Lista note: folder tree + tag cloud + ricerca
│       ├── NoteEditor.vue          ← Editor Markdown + preview + autosave + header
│       └── NotesBacklinks.vue      ← Pannello backlinks (note che puntano alla corrente)

config/
├── default.yaml                    ← + sezione notes: + entry commentata plugins.enabled
└── system_prompt.md                ← + sezione tools.notes con guidelines
```

---

#### 13.14 — Graph View (v2 feature — non implementata in Fase 13)

> **Nota**: la Graph View è una funzionalità v2 pianificata, descritta qui per chiarire
> il perché `wikilinks` è già persistito nel DB fin dalla v1.

**Obiettivo**: visualizzare le note come nodi in un grafo interattivo, con archi che
rappresentano i wikilinks `[[Titolo]]`. Ispirato alla Graph View di Obsidian.

**Architettura v2** (quando implementata):
- **Nuovo endpoint REST**: `GET /api/notes/graph` → restituisce
  `{ nodes: [{id, title, folder_path}], edges: [{source_id, target_id}] }`
  Il backend risolve `wikilinks[]` (titoli) in ID reali con una query SQLite.
- **Nuovo componente**: `components/notes/NotesGraphView.vue`
  — usa `cytoscape.js` o `d3-force` per rendering
  — nodi colorati per cartella, dimensione proporzionale al numero di backlinks in entrata
  — click su nodo → `store.loadNote(id)` → apre la nota nel NoteEditor
- **Nuovo tab** in `NotesPageView.vue`: toggle tra lista (`NotesBrowser`) e grafo
  (`NotesGraphView`) — stesso pattern del toggle preview in `NoteEditor`

**Perché non in Fase 13**: richiede dipendenza JS aggiuntiva (cytoscape/d3) e logica
di risoluzione titoli→ID nel backend. Il DB è già pronto (`wikilinks` persistiti) —
il costo aggiuntivo è solo UI, adottabile come pull request autonomo.

---

#### 13.12 — Ordine di Implementazione Consigliato

1. **`NotesConfig`** in `config.py` + `default.yaml` — aggiunta pura, zero dipendenze
2. **`OmniaEvent` note events** in `event_bus.py` — aggiunta pura all'enum
3. **`NoteEntry` dataclass** in `note_service.py` — zero dipendenze dal resto
4. **`NoteService`** completo — dipende da `aiosqlite` + `EmbeddingClient` (già presente)
5. **`NoteServiceProtocol`** in `protocols.py` + campo `AppContext.note_service`
6. **Wiring in `app.py`** — init `NoteService` nel lifespan
7. **`NotesPlugin`** — dipende da `NoteService` tramite context
8. **Route `notes.py`** + registrazione in `routes/__init__.py`
9. **Frontend `types/notes.ts` + `stores/notes.ts`** — tipi e store Pinia
10. **Aggiornamento `services/api.ts`** — metodi notes (getNotes, getNote, createNote, updateNote, deleteNote, searchNotes, getNoteFolders)
11. **`NotesBrowser.vue` + `NoteEditor.vue` + `NotesBacklinks.vue`** — componenti standalone
12. **`NotesPageView.vue`** — assembla browser + editor + backlinks
13. **Router entry + sidebar link** — aggiunta route `/notes`
14. **`config/system_prompt.md`** — guidelines tool notes
15. **Test suite completa** — scritti in parallelo ai passi 1–14

---

#### 13.13 — Verifiche Fase 13

| Scenario | Comportamento atteso |
|---|---|
| "Crea una nota con la ricetta della carbonara" | LLM chiama `create_note(title="Ricetta Carbonara", content="...", folder_path="cucina", tags=["ricette"])` → nota creata → ID restituito |
| "Trova le mie note su Python" | LLM chiama `search_notes(query="Python")` → lista titoli + ID → riassume risultati |
| "Leggi la nota sulla carbonara" | LLM: `search_notes("carbonara")` → trova ID → `read_note(id)` → contenuto troncato a `max_content_chars_llm` |
| "Aggiorna la ricetta: aggiungi guanciale 150g" | `read_note` → `update_note(id, content="...aggiornato...")` → salvato |
| "Elimina la nota sulla carbonara" | `delete_note` → `requires_confirmation=True` → dialog frontend → approvazione → eliminata |
| UI: click nota in NotesBrowser | Nota si apre in NoteEditor; modifica → autosave dopo 800ms → indicatore "Salvato ✓" |
| UI: nuova nota da pulsante | Nota vuota creata nella cartella attiva → focus su campo titolo |
| UI: ricerca "pasta" | Debounce 300ms → `searchNotes("pasta")` → lista aggiornata in tempo reale |
| `notes.enabled=False` (default) | NoteService non avviato; tool restituiscono errore graceful; REST → 503; zero impatto test esistenti |
| `notes` non in `plugins.enabled` | Tool LLM non disponibili; NoteService puede funzionare (REST attiva); i due flag sono indipendenti |
| `embedding_enabled=False` | Solo FTS5 search; nessun sqlite-vec caricato; funziona senza LM Studio |
| LM Studio offline durante creazione | Nota creata senza embedding vector; search semantica non disponibile; log warning; FTS funziona |
| 1000+ note nel vault | Paginazione via `limit/offset`; indici SQLite → query O(log n); frontend scroll virtuale futuro v2 |

---

## Fase 14 — Generazione Grafici Interattivi (Chart Generator)

> **Obiettivo**: aggiungere all'agente la capacità di generare grafici interattivi e di
> renderizzarli direttamente nella chat. I dati possono provenire da qualsiasi fonte
> gestita dall'LLM: note del vault (Fase 13), allegati immagine/CSV via vision,
> risultati di ricerca web, o dati forniti direttamente nel prompt.
> I grafici sono persistiti su disco con un ID univoco e possono essere
> aggiornati, recuperati o eliminati nelle conversazioni successive tramite i tool dedicati.
>
> **Pattern architetturale**: `chart_generator` segue esattamente il pattern di
> `cad_generator` (Fase 12): plugin-only (no service separato), `ToolResult` con
> `content_type='application/vnd.omnia.chart+json'`, REST proxy `/api/charts/`,
> `ChartViewer.vue` lazy-loaded via `defineAsyncComponent` in `MessageBubble.vue`.
> La libreria di rendering è **Apache ECharts** (utilizzo diretto senza wrapper Vue,
> consistente con il pattern Three.js in `CADViewer.vue`).

- [x] §14.1 `ChartConfig` in `backend/core/config.py`
- [x] §14.2 Modello dati `ChartSpec`, `ChartPayload`, `ChartListItem` (Pydantic)
- [x] §14.3 `ChartStore` — persistenza JSON in `data/charts/`
- [x] §14.4 Plugin `ChartGeneratorPlugin` (5 tool LLM)
- [x] §14.5 REST API `/api/charts/` — 3 endpoint
- [x] §14.6 Frontend: `ChartPayload` in `types/chat.ts` + `ChartViewer.vue` + aggiornamenti `MessageBubble.vue` e `ToolExecutionIndicator.vue`
- [x] §14.7 System prompt aggiornato
- [x] §14.8 Dipendenze
- [x] §14.9 Struttura file
- [x] §14.10 Test suite
- [x] §14.11 Ordine di implementazione
- [x] §14.12 Verifiche

---

### §14.0 — Scelte architetturali

**Perché plugin e non service?**
Il sistema non richiede una vera service layer: non c'è embeddings, full-text search,
né logica di routing complessa. Il plugin gestisce direttamente lo storage tramite
`ChartStore` e delega all'LLM tutta la fase di estrazione e formattazione dei dati.
Questo è identico al pattern di `cad_generator`, che ha un plugin senza service associato.

**Perché Apache ECharts?**
ECharts usa una configurazione interamente JSON-dichiarativa (`option` object) che
gli LLM conoscono molto bene. Supporta 20+ tipi di grafico (bar, line, pie, scatter,
heatmap, sankey, candlestick, radar, treemap, …) contro ~8 di Chart.js.
La visualizzazione è interattiva (zoom, tooltip, legend toggle) out-of-the-box.

**Perché utilizzo diretto di ECharts (no vue-echarts)?**
`CADViewer.vue` usa Three.js direttamente (`import * as THREE from 'three'`), senza
wrapper Vue. La stessa scelta si applica a ECharts per coerenza: `import * as echarts from 'echarts'`,
mount manuale nel `div` container, `onMounted`/`onUnmounted` per lifecycle Composition API.
Evita la dipendenza `vue-echarts` e il suo overhead di reattività.

**Perché JSON file e non SQLite?**
I chart spec sono blob JSON arbitrari di dimensione variabile (5 KB – 300 KB).
SQLite è ottimale per query strutturate; JSON files sono migliori per blob opachi
non interrogabili. Il `ChartStore` è analogo a `ConversationFileManager` (Fase 1.6):
file `.json` in `data/charts/`, no migrations, no schema.

**Perché il payload `ToolResult` non include la `echarts_option` inline?**
`MAX_TOOL_RESULT_LENGTH = 15_000`. Un chart con dataset medio (100–500 punti) può
eccedere facilmente questo limite. La soluzione è salvare la spec su disco e mettere
nel `ToolResult` solo i metadati (`chart_id`, `title`, `chart_type`, `chart_url`).
`ChartViewer.vue` effettua una GET a `/api/charts/{chart_id}` per caricare la spec completa.
Identico al pattern `CADViewer.vue` → `/api/cad/models/{name}`.

**Separazione responsabilità LLM / plugin:**
Il plugin è un puro "salva e servi". L'LLM è responsabile di:
- leggere i dati sorgente (via `read_note`, `web_search`, vision su immagini/CSV)
- costruire l'oggetto `echarts_option` (conosce il formato dalla documentazione)
- scegliere il tipo di grafico appropriato
- chiamare `generate_chart` con l'option pronta

---

### §14.1 — Configurazione

**`backend/core/config.py`** — aggiungere la classe e il campo:

```python
class ChartConfig(BaseSettings):
    """Configurazione plugin chart_generator."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_CHART__")

    enabled: bool = False
    """Abilita il plugin chart_generator (opt-in, come tutti i plugin OMNIA)."""

    chart_output_dir: str = "data/charts"
    """Directory dove vengono salvati i chart spec JSON."""

    max_option_chars: int = 10_000
    """Dimensione massima della echarts_option serializzata (in caratteri).

    L'LLM deve aggregare i dati prima di chiamare generate_chart se il
    dataset supera questo limite.
    """

    max_charts: int = 1_000
    """Numero massimo di grafici persistiti. Oltre questo limite, generate_chart
    restituisce un errore con istruzioni per eliminare grafici vecchi.
    """
```

Nella classe `OmniaConfig`:

```python
chart: ChartConfig = Field(default_factory=ChartConfig)
```

**`config/default.yaml`** — aggiungere sezione:

```yaml
chart:
  enabled: true
  chart_output_dir: "data/charts"
  max_option_chars: 10000
  max_charts: 1000
```

---

### §14.2 — Modello dati

**`backend/plugins/chart_generator/models.py`**

I modelli Pydantic definiscono il contratto interno al plugin e il JSON salvato
su disco. Non è un `SQLModel` perché lo storage è file-based.

```python
"""Modelli Pydantic per il plugin chart_generator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class ChartSpec(BaseModel):
    """Specifica completa di un grafico, persistita su disco.

    Ogni istanza corrisponde a un file `data/charts/{chart_id}.json`.
    """

    chart_id: str
    """UUID v4 identificativo univoco."""

    title: str
    """Titolo leggibile del grafico, usato in UI e nei tool list."""

    chart_type: str
    """Tipo principale del grafico (bar, line, pie, scatter, …).

    Informativo — il tipo effettivo è determinato da `echarts_option.series[].type`.
    """

    description: str = ""
    """Breve descrizione della fonte dati e dello scopo del grafico."""

    echarts_option: dict[str, Any]
    """Configurazione Apache ECharts completa (option object).

    Esempio minimo:
    {
      "title": {"text": "Vendite Q1"},
      "xAxis": {"type": "category", "data": ["Gen", "Feb", "Mar"]},
      "yAxis": {"type": "value"},
      "series": [{"type": "bar", "data": [150, 230, 180]}]
    }
    """

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ChartPayload(BaseModel):
    """Payload serializzato nel `ToolResult.content`.

    Piccolo subset della ChartSpec — non include `echarts_option`.
    Questo è il JSON che viene salvato nel DB come contenuto del messaggio tool.
    Deve restare sincronizzato con l'interfaccia TypeScript `ChartPayload` nel frontend.
    """

    chart_id: str
    title: str
    chart_type: str
    chart_url: str
    """URL relativo `/api/charts/{chart_id}` per caricare la spec completa."""
    created_at: datetime


class ChartListItem(BaseModel):
    """Elemento della lista grafici — usato da `list_charts` e `GET /api/charts`."""

    chart_id: str
    title: str
    chart_type: str
    description: str
    created_at: datetime
    updated_at: datetime
```

---

### §14.3 — ChartStore

**`backend/plugins/chart_generator/chart_store.py`**

Gestisce la persistenza dei grafici come file JSON in `data/charts/`.
Pattern identico a `ConversationFileManager` (`backend/services/conversation_file_manager.py`):
tutto l'I/O file sincrono viene eseguito in un thread separato via `asyncio.to_thread`.

```python
"""ChartStore — persistenza JSON per i grafici generati dall'agente."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

from .models import ChartListItem, ChartSpec


class ChartStore:
    """Gestisce il salvataggio e il recupero dei grafici su disco.

    Ogni grafico viene salvato come `{chart_output_dir}/{chart_id}.json`.
    """

    def __init__(self, chart_output_dir: str | Path) -> None:
        self._dir = Path(chart_output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Operazioni pubbliche (async)
    # ------------------------------------------------------------------

    async def save(self, spec: ChartSpec) -> None:
        """Salva un nuovo grafico su disco."""
        await asyncio.to_thread(self._write, spec)

    async def load(self, chart_id: str) -> ChartSpec | None:
        """Carica un grafico dal disco. Restituisce None se non trovato."""
        return await asyncio.to_thread(self._read, chart_id)

    async def update(self, chart_id: str, new_spec: ChartSpec) -> bool:
        """Sovrascrive la spec di un grafico esistente.

        Args:
            chart_id: ID del grafico da aggiornare.
            new_spec: Nuova spec — ``new_spec.chart_id`` deve corrispondere a ``chart_id``.

        Returns:
            True se aggiornato, False se il file non esiste.

        Raises:
            ValueError: Se ``new_spec.chart_id`` non coincide con ``chart_id``.
        """
        if new_spec.chart_id != chart_id:
            raise ValueError(
                f"chart_id mismatch: atteso {chart_id!r}, ricevuto {new_spec.chart_id!r}"
            )
        path = self._path(chart_id)
        if not await asyncio.to_thread(path.exists):
            return False
        await asyncio.to_thread(self._write, new_spec)
        return True

    async def delete(self, chart_id: str) -> bool:
        """Elimina un grafico dal disco.

        Returns:
            True se eliminato, False se non trovato.
        """
        path = self._path(chart_id)
        deleted = await asyncio.to_thread(self._unlink, path)
        if deleted:
            logger.info(f"Chart eliminato: {chart_id}")
        return deleted

    async def list(self, limit: int = 50, offset: int = 0) -> list[ChartListItem]:
        """Restituisce la lista dei grafici persistiti, ordinata per data di modifica decrescente."""
        return await asyncio.to_thread(self._list_sync, limit, offset)

    async def count(self) -> int:
        """Restituisce il numero totale di grafici salvati."""
        return await asyncio.to_thread(self._count_sync)

    # ------------------------------------------------------------------
    # Metodi sincroni (eseguiti in thread pool via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _path(self, chart_id: str) -> Path:
        # Sanitizzazione: accetta solo caratteri alfanumerici e trattini (UUID format).
        # Previene path traversal — `../../../etc/passwd` diventa `etcpasswd`.
        safe_id = "".join(c for c in chart_id if c.isalnum() or c == "-")
        if not safe_id:
            raise ValueError(f"chart_id non valido (nessun carattere sicuro): {chart_id!r}")
        return self._dir / f"{safe_id}.json"

    def _write(self, spec: ChartSpec) -> None:
        path = self._path(spec.chart_id)
        path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    def _read(self, chart_id: str) -> ChartSpec | None:
        path = self._path(chart_id)
        if not path.exists():
            return None
        try:
            return ChartSpec.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
                logger.exception(f"Errore lettura chart {chart_id}")

    def _unlink(self, path: Path) -> bool:
        if path.exists():
            path.unlink()
            return True
        return False

    def _list_sync(self, limit: int, offset: int) -> list[ChartListItem]:
        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except FileNotFoundError:
                return 0.0

        files = sorted(
            self._dir.glob("*.json"),
            key=_mtime,
            reverse=True,
        )
        page = files[offset : offset + limit]
        items: list[ChartListItem] = []
        for f in page:
            try:
                spec = ChartSpec.model_validate_json(f.read_text(encoding="utf-8"))
                items.append(
                    ChartListItem(
                        chart_id=spec.chart_id,
                        title=spec.title,
                        chart_type=spec.chart_type,
                        description=spec.description,
                        created_at=spec.created_at,
                        updated_at=spec.updated_at,
                    )
                )
            except Exception:
                logger.warning(f"Grafico non leggibile: {f.name} (ignorato)")
        return items

    def _count_sync(self) -> int:
        return sum(1 for _ in self._dir.glob("*.json"))
```

---

### §14.4 — Plugin ChartGeneratorPlugin

**`backend/plugins/chart_generator/__init__.py`**

```python
"""O.M.N.I.A. — Chart Generator plugin package.

Importing this module registers ChartGeneratorPlugin in the static PLUGIN_REGISTRY
so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.chart_generator.plugin import ChartGeneratorPlugin  # noqa: F401

PLUGIN_REGISTRY["chart_generator"] = ChartGeneratorPlugin
```

**`backend/plugins/chart_generator/plugin.py`**

Il plugin implementa 5 tool. Non ha dipendenze dal plugin registry (`depends_on = []`).

```python
"""Plugin chart_generator — genera, aggiorna e gestisce grafici ECharts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult

from .chart_store import ChartStore
from .models import ChartPayload, ChartSpec

if TYPE_CHECKING:
    from backend.core.context import AppContext

_GENERATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Titolo del grafico (max 255 caratteri).",
            "maxLength": 255,
        },
        "chart_type": {
            "type": "string",
            "description": (
                "Tipo principale del grafico. Esempi: bar, line, pie, scatter, "
                "radar, heatmap, sankey, candlestick, treemap, funnel."
            ),
        },
        "echarts_option": {
            "type": "object",
            "description": (
                "Configurazione Apache ECharts completa (option object). "
                "Deve includere almeno: title, series. Includere xAxis/yAxis "
                "per grafici cartesiani, legend e tooltip per interattività. "
                "Il formato è identico alla documentazione ufficiale ECharts."
            ),
            "additionalProperties": True,
        },
        "description": {
            "type": "string",
            "description": "Breve descrizione della fonte dati e dello scopo del grafico.",
            "maxLength": 500,
        },
    },
    "required": ["title", "chart_type", "echarts_option"],
}

_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_id": {
            "type": "string",
            "description": "UUID del grafico da aggiornare.",
        },
        "echarts_option": {
            "type": "object",
            "description": "Nuova configurazione ECharts completa che sostituisce la precedente.",
            "additionalProperties": True,
        },
        "title": {
            "type": "string",
            "description": "Nuovo titolo (opzionale — omettere per mantenere il titolo corrente).",
            "maxLength": 255,
        },
    },
    "required": ["chart_id", "echarts_option"],
}

_GET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_id": {
            "type": "string",
            "description": "UUID del grafico da recuperare.",
        },
    },
    "required": ["chart_id"],
}

_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "description": "Numero massimo di grafici da restituire (default 20, max 100).",
            "default": 20,
            "minimum": 1,
            "maximum": 100,
        },
        "offset": {
            "type": "integer",
            "description": "Numero di grafici da saltare per paginazione (default 0).",
            "default": 0,
            "minimum": 0,
        },
    },
}

_DELETE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_id": {
            "type": "string",
            "description": "UUID del grafico da eliminare definitivamente.",
        },
    },
    "required": ["chart_id"],
}


class ChartGeneratorPlugin(BasePlugin):
    """Plugin per la generazione di grafici interattivi Apache ECharts.

    L'LLM costruisce autonomamente la `echarts_option` JSON dai dati
    disponibili (note, vision, ricerca web, prompt). Il plugin si occupa
    di persistere la spec su disco e di restituire un `ToolResult` con
    `content_type='application/vnd.omnia.chart+json'` che il frontend
    renderizza come `ChartViewer.vue`.
    """

    plugin_name: str = "chart_generator"
    plugin_version: str = "1.0.0"
    plugin_description: str = "Genera grafici interattivi ECharts da qualsiasi fonte dati."
    plugin_dependencies: list[str] = []
    plugin_priority: int = 25

    def __init__(self) -> None:
        super().__init__()
        self._store: ChartStore | None = None

    async def initialize(self, ctx: "AppContext") -> None:
        await super().initialize(ctx)
        cfg = ctx.config.chart
        if not cfg.enabled:
            self.logger.info("Plugin chart_generator disabilitato dalla configurazione.")
            return
        self._store = ChartStore(cfg.chart_output_dir)
        self.logger.info(f"ChartGeneratorPlugin inizializzato (dir={cfg.chart_output_dir})")

    async def cleanup(self) -> None:
        self._store = None
        await super().cleanup()

    def get_tools(self) -> list[ToolDefinition]:
        if not self.ctx.config.chart.enabled:
            return []
        return [
            ToolDefinition(
                name="generate_chart",
                description=(
                    "Genera un grafico interattivo Apache ECharts e lo persiste su disco. "
                    "L'output viene visualizzato direttamente nella chat come viewer interattivo. "
                    "Costruisci l'echarts_option in base ai dati raccolti (note, vision, web, prompt). "
                    "Usa questo tool SOLO dopo aver raccolto tutti i dati necessari."
                ),
                parameters=_GENERATE_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=30_000,
            ),
            ToolDefinition(
                name="update_chart",
                description=(
                    "Aggiorna la configurazione ECharts di un grafico esistente. "
                    "Usa il chart_id restituito da generate_chart o list_charts. "
                    "L'intera echarts_option viene sostituita con la nuova versione."
                ),
                parameters=_UPDATE_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=15_000,
            ),
            ToolDefinition(
                name="get_chart",
                description=(
                    "Recupera i metadati e la echarts_option di un grafico salvato. "
                    "Utile per leggere un grafico esistente prima di aggiornarlo."
                ),
                parameters=_GET_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=5_000,
            ),
            ToolDefinition(
                name="list_charts",
                description=(
                    "Elenca i grafici persistiti nel vault, ordinati dal più recente. "
                    "Restituisce chart_id, title, chart_type, description e date."
                ),
                parameters=_LIST_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=5_000,
            ),
            ToolDefinition(
                name="delete_chart",
                description=(
                    "Elimina definitivamente un grafico dal disco. L'operazione è irreversibile."
                ),
                parameters=_DELETE_SCHEMA,
                risk_level="medium",
                requires_confirmation=True,
                timeout_ms=5_000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch al metodo privato corrispondente al tool_name."""
        if not self.ctx.config.chart.enabled:
            return ToolResult(success=False, content="Plugin chart_generator non abilitato.")

        handlers = {
            "generate_chart": self._generate_chart,
            "update_chart": self._update_chart,
            "get_chart": self._get_chart,
            "list_charts": self._list_charts,
            "delete_chart": self._delete_chart,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return ToolResult(success=False, content=f"Tool sconosciuto: {tool_name}")
        return await handler(args)

    # ------------------------------------------------------------------
    # Implementazioni tool private
    # ------------------------------------------------------------------

    async def _generate_chart(self, args: dict[str, Any]) -> ToolResult:
        """Crea un nuovo grafico, lo salva su disco e restituisce il payload per il frontend."""
        cfg = self.ctx.config.chart
        count = await self._store.count()
        if count >= cfg.max_charts:
            return ToolResult(
                success=False,
                content=(
                    f"Limite massimo di grafici raggiunto ({cfg.max_charts}). "
                    "Usa `delete_chart` per eliminare grafici non più necessari."
                ),
            )

        option = args["echarts_option"]
        option_str = json.dumps(option, ensure_ascii=False)
        if len(option_str) > cfg.max_option_chars:
            return ToolResult(
                success=False,
                content=(
                    f"La echarts_option supera il limite di {cfg.max_option_chars} caratteri "
                    f"(attuale: {len(option_str)}). Aggrega o riduci i dati prima di richiamare il tool."
                ),
            )

        chart_id = str(uuid4())
        now = datetime.now(timezone.utc)
        spec = ChartSpec(
            chart_id=chart_id,
            title=args["title"],
            chart_type=args["chart_type"],
            description=args.get("description", ""),
            echarts_option=option,
            created_at=now,
            updated_at=now,
        )
        await self._store.save(spec)
        self.logger.info(f"Grafico '{spec.title}' generato (id={chart_id}, type={spec.chart_type})")

        payload = ChartPayload(
            chart_id=chart_id,
            title=spec.title,
            chart_type=spec.chart_type,
            chart_url=f"/api/charts/{chart_id}",
            created_at=now,
        )
        return ToolResult(
            success=True,
            content=payload.model_dump_json(),
            content_type="application/vnd.omnia.chart+json",
        )

    async def _update_chart(self, args: dict[str, Any]) -> ToolResult:
        """Aggiorna la echarts_option di un grafico esistente."""
        chart_id = args["chart_id"]
        existing = await self._store.load(chart_id)
        if existing is None:
            return ToolResult(success=False, content=f"Grafico non trovato: {chart_id}")

        cfg = self.ctx.config.chart
        option_str = json.dumps(args["echarts_option"], ensure_ascii=False)
        if len(option_str) > cfg.max_option_chars:
            return ToolResult(
                success=False,
                content=f"echarts_option supera il limite di {cfg.max_option_chars} caratteri.",
            )

        existing.echarts_option = args["echarts_option"]
        existing.updated_at = datetime.now(timezone.utc)
        if "title" in args:
            existing.title = args["title"]

        await self._store.update(chart_id, existing)
        self.logger.info(f"Grafico aggiornato: {chart_id}")

        payload = ChartPayload(
            chart_id=chart_id,
            title=existing.title,
            chart_type=existing.chart_type,
            chart_url=f"/api/charts/{chart_id}",
            created_at=existing.created_at,
        )
        return ToolResult(
            success=True,
            content=payload.model_dump_json(),
            content_type="application/vnd.omnia.chart+json",
        )

    async def _get_chart(self, args: dict[str, Any]) -> ToolResult:
        """Recupera metadata e echarts_option di un grafico salvato."""
        chart_id = args["chart_id"]
        spec = await self._store.load(chart_id)
        if spec is None:
            return ToolResult(success=False, content=f"Grafico non trovato: {chart_id}")
        return ToolResult(success=True, content=spec.model_dump_json())

    async def _list_charts(self, args: dict[str, Any]) -> ToolResult:
        """Elenca i grafici salvati con paginazione."""
        limit = min(int(args.get("limit", 20)), 100)
        offset = max(int(args.get("offset", 0)), 0)
        items = await self._store.list(limit=limit, offset=offset)
        total = await self._store.count()
        payload = {
            "charts": [item.model_dump(mode="json") for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False, default=str),
        )

    async def _delete_chart(self, args: dict[str, Any]) -> ToolResult:
        """Elimina un grafico dal disco."""
        chart_id = args["chart_id"]
        deleted = await self._store.delete(chart_id)
        if not deleted:
            return ToolResult(success=False, content=f"Grafico non trovato: {chart_id}")
        return ToolResult(success=True, content=f"Grafico eliminato: {chart_id}")
```

**Registrazione plugin** in `backend/plugins/__init__.py` — aggiungere dopo l'import di `cad_generator`:

```python
from .chart_generator import ChartGeneratorPlugin  # noqa: F401
```

---

### §14.5 — REST API `/api/charts/`

**`backend/api/routes/charts.py`**

Tre endpoint: GET spec singola, GET lista paginata, DELETE.
I tool del plugin gestiscono la logica core — la route è un proxy che serve
i file JSON salvati su disco al `ChartViewer.vue` nel frontend.

```python
"""REST API per il recupero e la gestione dei grafici generati dall'agente."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/charts", tags=["charts"])


def _get_store(request: Request):
    """Recupera il ChartStore dal plugin chart_generator tramite AppContext."""
    ctx = request.app.state.context
    plugin = ctx.plugin_manager.get_plugin("chart_generator")
    if plugin is None or not ctx.config.chart.enabled:
        raise HTTPException(status_code=503, detail="Plugin chart_generator non disponibile.")
    store = plugin._store
    if store is None:
        raise HTTPException(status_code=503, detail="ChartStore non inizializzato.")
    return store


@router.get("/{chart_id}", summary="Recupera la spec completa di un grafico")
async def get_chart(chart_id: str, request: Request) -> JSONResponse:
    """Restituisce il JSON completo della ChartSpec (inclusa echarts_option).

    Chiamato da `ChartViewer.vue` al mount per caricare la configurazione ECharts.
    """
    store = _get_store(request)
    spec = await store.load(chart_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Grafico non trovato: {chart_id}")
    return JSONResponse(content=spec.model_dump(mode="json"))


@router.get("", summary="Lista grafici salvati")
async def list_charts(
    request: Request, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    """Restituisce la lista paginata dei grafici, ordinata dal più recente."""
    store = _get_store(request)
    items = await store.list(limit=min(limit, 100), offset=offset)
    total = await store.count()
    return {
        "charts": [item.model_dump(mode="json") for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.delete("/{chart_id}", summary="Elimina un grafico")
async def delete_chart(chart_id: str, request: Request) -> dict[str, str]:
    """Elimina il file JSON del grafico dal disco.

    Nota: per l'eliminazione via LLM usare il tool `delete_chart`,
    che attiva il dialog di conferma utente.
    """
    store = _get_store(request)
    deleted = await store.delete(chart_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Grafico non trovato: {chart_id}")
    return {"status": "deleted", "chart_id": chart_id}
```

**Registrazione router** in `backend/api/routes/__init__.py` — aggiungere dopo il router `cad`:

```python
# Aggiungere alla riga import esistente (o come import separato):
from . import charts

# Nella sezione di registrazione router:
router.include_router(charts.router)
```

---

### §14.6 — Frontend

#### Tipo `ChartPayload` — `frontend/src/renderer/src/types/chat.ts`

Aggiungere l'interfaccia accanto a `CadModelPayload`:

```typescript
/** Payload restituito dai tool `generate_chart` e `update_chart`.
 *  Corrisponde al modello Pydantic `ChartPayload` nel backend.
 *  Non include `echarts_option` — il viewer la carica via `chart_url`.
 */
export interface ChartPayload {
  chart_id: string
  title: string
  chart_type: string
  /** URL relativo: "/api/charts/{chart_id}" */
  chart_url: string
  created_at: string
}
```

#### `ChartViewer.vue` — `frontend/src/renderer/src/components/chat/ChartViewer.vue`

Componente autonomo che monta un'istanza ECharts su un `div` di riferimento.
Pattern identico a `CADViewer.vue`: utilizzo diretto della libreria (no wrapper Vue),
`onMounted`/`onUnmounted` lifecycle, `ResizeObserver` per dimensionamento responsivo.

```vue
<script setup lang="ts">
/**
 * ChartViewer.vue — Visualizza un grafico Apache ECharts nella chat.
 *
 * Carica la ChartSpec completa dall'endpoint REST GET /api/charts/{chart_id},
 * monta un'istanza echarts.init() sul div container e gestisce il resize.
 */
import { ref, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import type { ECharts } from 'echarts'
import { resolveBackendUrl } from '../../services/api'
import type { ChartPayload } from '../../types/chat'

const props = defineProps<{ payload: ChartPayload }>()

const containerRef = ref<HTMLDivElement | null>(null)
let instance: ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const loading = ref(true)
const error = ref<string | null>(null)

async function loadAndRender(): Promise<void> {
  if (!containerRef.value) return
  try {
    const response = await fetch(resolveBackendUrl(props.payload.chart_url))
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const spec = await response.json()

    instance = echarts.init(containerRef.value, 'dark')
    instance.setOption(spec.echarts_option)
    loading.value = false

    resizeObserver = new ResizeObserver(() => instance?.resize())
    resizeObserver.observe(containerRef.value)
  } catch (err) {
    error.value = `Impossibile caricare il grafico: ${(err as Error).message}`
    loading.value = false
  }
}

onMounted(loadAndRender)

onUnmounted(() => {
  resizeObserver?.disconnect()
  instance?.dispose()
  instance = null
})
</script>

<template>
  <div class="chart-viewer">
    <div class="chart-viewer__header">
      <span class="chart-viewer__title">{{ payload.title }}</span>
      <span class="chart-viewer__type">{{ payload.chart_type }}</span>
    </div>
    <div v-if="loading" class="chart-viewer__loading">Caricamento grafico…</div>
    <div v-if="error" class="chart-viewer__error">{{ error }}</div>
    <div v-show="!loading && !error" ref="containerRef" class="chart-viewer__canvas" />
  </div>
</template>

<style scoped>
.chart-viewer {
  border-radius: 8px;
  overflow: hidden;
  background: var(--surface-2);
  margin: 8px 0;
}
.chart-viewer__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--surface-3);
  border-bottom: 1px solid var(--border);
}
.chart-viewer__title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--text-primary);
  flex: 1;
}
.chart-viewer__type {
  font-size: 0.75rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.chart-viewer__canvas {
  width: 100%;
  height: 380px;
}
.chart-viewer__loading,
.chart-viewer__error {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.875rem;
}
.chart-viewer__error {
  color: var(--danger);
}
</style>
```

#### `MessageBubble.vue` — aggiornamento

Aggiungere il supporto per `application/vnd.omnia.chart+json` nei messaggi `role='tool'`
già persistiti nella cronologia della chat. Pattern identico a `cadPayload`:

```typescript
// Aggiungere import accanto a CadModelPayload:
import type { ChartPayload } from '../../types/chat'

const ChartViewer = defineAsyncComponent(
  () => import('./ChartViewer.vue')
)

// Aggiungere computed accanto a cadPayload:
const chartPayload = computed((): ChartPayload | null => {
  if (props.message.role !== 'tool') return null
  try {
    const p = JSON.parse(props.message.content)
    if (
      typeof p.chart_id === 'string' &&
      typeof p.chart_url === 'string' &&
      typeof p.chart_type === 'string'
    ) {
      return p as ChartPayload
    }
  } catch { /* non è JSON chart payload */ }
  return null
})
```

Nel template, aggiungere **dopo** `<CADViewer v-if="cadPayload" …>`:

```vue
<ChartViewer v-if="chartPayload" :payload="chartPayload" />
```

La condizione del contenuto testuale deve diventare:
```vue
<div v-if="!cadPayload && !chartPayload" class="bubble__content" … />
```

#### `ToolExecutionIndicator.vue` — aggiornamento

Aggiungere il case per `application/vnd.omnia.chart+json` accanto al case esistente
per `application/vnd.omnia.cad-model+json` (rendering inline durante lo streaming).
Siccome `ToolExecutionIndicator.vue` itera su `executions: ToolExecution[]` (non espone
`contentType`/`result` come props atomici), si usa una funzione helper per-elemento
anziché un `computed` top-level:

```typescript
import type { ChartPayload } from '../../types/chat'

const ChartViewer = defineAsyncComponent(
  () => import('./ChartViewer.vue')
)

/** Analizza il contenuto di un tool result come ChartPayload. Restituisce null se non è un chart. */
function parseChartPayload(result: string): ChartPayload | null {
  try {
    const p = JSON.parse(result)
    if (typeof p.chart_id === 'string' && typeof p.chart_url === 'string') return p as ChartPayload
    return null
  } catch { return null }
}
```

Nel template (dopo il blocco `cad-model+json` esistente):

```vue
<template v-else-if="exec.contentType === 'application/vnd.omnia.chart+json' && exec.result">
  <ChartViewer
    v-if="parseChartPayload(exec.result)"
    :payload="parseChartPayload(exec.result)!"
  />
</template>
```

---

### §14.7 — System Prompt

**`config/system_prompt.md`** — aggiungere sezione:

```yaml
chart_generator:
  principio: genera e gestisce grafici interattivi Apache ECharts da qualsiasi fonte dati
  workflow:
    - "raccolta dati PRIMA di chiamare generate_chart: note → read_note/search_notes, immagini/CSV → analisi visiva, web → web_search, prompt → dati già disponibili"
    - "costruzione echarts_option: costruisci il JSON ECharts mentalmente prima della tool call. Deve essere un object JSON valido, NON una stringa serializzata"
    - "chiamata generate_chart: passa la spec completa — il grafico è visualizzato nella chat come viewer interattivo"
  tipi_supportati: bar line pie scatter radar heatmap sankey candlestick treemap funnel gauge boxplot parallel themeRiver — e qualsiasi combinazione in series misto
  limiti:
    - "echarts_option serializzata: max 10.000 caratteri. Aggrega o campiona i dati prima di chiamare il tool se il dataset è grande"
    - "max 1.000 grafici nel vault. Usa list_charts / delete_chart per gestirli"
  update: usa update_chart(chart_id, echarts_option) per modificare un grafico esistente. Recupera prima la spec con get_chart(chart_id) per modifiche puntuali
```

---

### §14.8 — Dipendenze

#### Frontend

**`frontend/package.json`** — aggiungere in `dependencies`:

```json
"echarts": "^5.6.0"
```

Installazione: `cd frontend && npm install --save echarts`.

Non è necessario `vue-echarts` — ECharts viene usato con API imperativa
(`echarts.init`, `instance.setOption`), coerente con il pattern Three.js di `CADViewer.vue`.

#### Backend

Nessuna dipendenza Python aggiuntiva. Il plugin usa solo librerie stdlib:
`pathlib`, `json`, `uuid`, `asyncio` — e `pydantic` già in uso nel progetto.

---

### §14.9 — Struttura file

```
backend/
  plugins/
    __init__.py                       # + import ChartGeneratorPlugin
    chart_generator/
      __init__.py                     # Esporta ChartGeneratorPlugin
      plugin.py                       # ChartGeneratorPlugin + PLUGIN_REGISTRY
      chart_store.py                  # ChartStore (JSON file persistence)
      models.py                       # ChartSpec, ChartPayload, ChartListItem
  api/
    routes/
      charts.py                       # GET /{id}, GET /, DELETE /{id}
      __init__.py                     # + charts_router
  core/
    config.py                         # + ChartConfig, OmniaConfig.chart

frontend/
  package.json                        # + echarts ^5.6.0
  src/renderer/src/
    components/chat/
      ChartViewer.vue                 # Viewer ECharts autonomo (nuovo)
      MessageBubble.vue               # + chartPayload computed + <ChartViewer>
      ToolExecutionIndicator.vue      # + parseChartPayload helper + <ChartViewer>
    types/
      chat.ts                         # + ChartPayload interface

config/
  default.yaml                        # + sezione chart:
  system_prompt.md                    # + sezione chart_generator:

data/
  charts/                             # Creata automaticamente da ChartStore
    {uuid}.json                       # Un file JSON per ogni grafico

backend/
  tests/
    test_chart_store.py
    test_chart_generator_plugin.py
    test_charts_route.py
```

---

### §14.10 — Test suite

**`backend/tests/test_chart_store.py`**

```python
"""Test ChartStore — operazioni CRUD su file JSON."""

import pytest
from pathlib import Path
from backend.plugins.chart_generator.chart_store import ChartStore
from backend.plugins.chart_generator.models import ChartSpec


@pytest.fixture
def store(tmp_path: Path) -> ChartStore:
    return ChartStore(chart_output_dir=tmp_path)


@pytest.fixture
def sample_spec() -> ChartSpec:
    return ChartSpec(
        chart_id="test-uuid-001",
        title="Vendite Q1",
        chart_type="bar",
        description="Dati di test",
        echarts_option={
            "xAxis": {"type": "category", "data": ["Gen", "Feb", "Mar"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [150, 230, 180]}],
        },
    )


@pytest.mark.asyncio
async def test_save_and_load(store: ChartStore, sample_spec: ChartSpec) -> None:
    await store.save(sample_spec)
    loaded = await store.load(sample_spec.chart_id)
    assert loaded is not None
    assert loaded.title == "Vendite Q1"
    assert loaded.echarts_option["series"][0]["type"] == "bar"


@pytest.mark.asyncio
async def test_load_nonexistent_returns_none(store: ChartStore) -> None:
    assert await store.load("nonexistent-id") is None


@pytest.mark.asyncio
async def test_delete_existing(store: ChartStore, sample_spec: ChartSpec) -> None:
    await store.save(sample_spec)
    assert await store.delete(sample_spec.chart_id) is True
    assert await store.load(sample_spec.chart_id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(store: ChartStore) -> None:
    assert await store.delete("ghost-id") is False


@pytest.mark.asyncio
async def test_list_and_count(store: ChartStore, sample_spec: ChartSpec) -> None:
    for i in range(3):
        spec = sample_spec.model_copy(update={"chart_id": f"id-{i}", "title": f"Chart {i}"})
        await store.save(spec)
    assert await store.count() == 3
    items = await store.list(limit=2, offset=0)
    assert len(items) == 2


@pytest.mark.asyncio
async def test_path_sanitization(store: ChartStore, sample_spec: ChartSpec) -> None:
    """Path traversal non possibile — i caratteri non-UUID vengono rimossi dal filename."""
    spec = sample_spec.model_copy(update={"chart_id": "../../../etc/passwd"})
    await store.save(spec)
    # _path() deve restituire un percorso DENTRO store._dir, non fuori
    sanitized_path = store._path("../../../etc/passwd")
    assert sanitized_path.parent == store._dir, (
        "Il path sanitizzato deve rimanere dentro la directory del store"
    )
    assert sanitized_path.exists(), "Il file sanitizzato deve esistere nella directory del store"
```

**`backend/tests/test_chart_generator_plugin.py`**

```python
"""Test ChartGeneratorPlugin — esecuzione tool LLM."""

import pytest
from unittest.mock import MagicMock
from backend.plugins.chart_generator.plugin import ChartGeneratorPlugin

VALID_OPTION = {"series": [{"type": "bar", "data": [1, 2, 3]}]}


@pytest.fixture
def mock_ctx(tmp_path):
    ctx = MagicMock()
    ctx.config.chart.enabled = True
    ctx.config.chart.max_option_chars = 10_000
    ctx.config.chart.max_charts = 1_000
    ctx.config.chart.chart_output_dir = str(tmp_path)
    return ctx


@pytest.fixture
async def plugin(mock_ctx):
    p = ChartGeneratorPlugin(mock_ctx)
    await p.initialize(mock_ctx)
    return p


@pytest.mark.asyncio
async def test_generate_chart_success(plugin) -> None:
    result = await plugin.execute_tool("generate_chart", {
        "title": "Test Chart",
        "chart_type": "bar",
        "echarts_option": VALID_OPTION,
    }, context=None)
    assert result.success is True
    assert result.content_type == "application/vnd.omnia.chart+json"
    import json
    payload = json.loads(result.content)
    assert "chart_id" in payload
    assert payload["chart_url"].startswith("/api/charts/")


@pytest.mark.asyncio
async def test_generate_chart_option_too_large(plugin) -> None:
    plugin.ctx.config.chart.max_option_chars = 10
    result = await plugin.execute_tool("generate_chart", {
        "title": "Big",
        "chart_type": "line",
        "echarts_option": {"data": list(range(10_000))},
    }, context=None)
    assert result.success is False
    assert "limite" in result.content.lower()


@pytest.mark.asyncio
async def test_list_charts_empty(plugin) -> None:
    result = await plugin.execute_tool("list_charts", {}, context=None)
    assert result.success is True
    import json
    data = json.loads(result.content)
    assert data["charts"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_chart_not_found(plugin) -> None:
    result = await plugin.execute_tool("get_chart", {"chart_id": "nonexistent"}, context=None)
    assert result.success is False


@pytest.mark.asyncio
async def test_delete_chart_success(plugin) -> None:
    gen = await plugin.execute_tool("generate_chart", {
        "title": "Da eliminare",
        "chart_type": "bar",
        "echarts_option": VALID_OPTION,
    }, context=None)
    assert gen.success is True
    import json
    chart_id = json.loads(gen.content)["chart_id"]

    result = await plugin.execute_tool("delete_chart", {"chart_id": chart_id}, context=None)
    assert result.success is True

    get = await plugin.execute_tool("get_chart", {"chart_id": chart_id}, context=None)
    assert get.success is False


@pytest.mark.asyncio
async def test_delete_chart_not_found(plugin) -> None:
    result = await plugin.execute_tool("delete_chart", {"chart_id": "nonexistent"}, context=None)
    assert result.success is False


@pytest.mark.asyncio
async def test_update_chart_success(plugin) -> None:
    gen = await plugin.execute_tool("generate_chart", {
        "title": "Originale",
        "chart_type": "bar",
        "echarts_option": VALID_OPTION,
    }, context=None)
    import json
    chart_id = json.loads(gen.content)["chart_id"]

    new_option = {"series": [{"type": "line", "data": [10, 20, 30]}]}
    result = await plugin.execute_tool("update_chart", {
        "chart_id": chart_id,
        "echarts_option": new_option,
    }, context=None)
    assert result.success is True


@pytest.mark.asyncio
async def test_plugin_disabled_returns_no_tools(mock_ctx) -> None:
    mock_ctx.config.chart.enabled = False
    p = ChartGeneratorPlugin(mock_ctx)
    await p.initialize(mock_ctx)
    assert p.get_tools() == []
```

**`backend/tests/test_charts_route.py`**

```python
"""Test REST route /api/charts/."""

import pytest


@pytest.mark.asyncio
async def test_get_chart_not_found(client) -> None:
    response = await client.get("/api/charts/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_charts_empty(client) -> None:
    response = await client.get("/api/charts")
    assert response.status_code == 200
    data = response.json()
    assert "charts" in data
    assert "total" in data
    assert data["charts"] == []
    assert data["total"] == 0
```

---

### §14.11 — Ordine di implementazione

1. `backend/plugins/chart_generator/models.py` — modelli Pydantic
2. `backend/plugins/chart_generator/chart_store.py` — ChartStore
3. `backend/core/config.py` — `ChartConfig` + campo `chart` in `OmniaConfig`
4. `config/default.yaml` — sezione `chart:`
5. `backend/plugins/chart_generator/plugin.py` — ChartGeneratorPlugin completo
6. `backend/plugins/chart_generator/__init__.py` — export
7. `backend/plugins/__init__.py` — import per trigger PLUGIN_REGISTRY
8. `backend/api/routes/charts.py` — 3 endpoint REST
9. `backend/api/routes/__init__.py` — registrazione `charts_router`
10. `frontend/package.json` → `npm install echarts`
11. `frontend/src/renderer/src/types/chat.ts` — `ChartPayload` interface
12. `frontend/src/renderer/src/components/chat/ChartViewer.vue` — nuovo componente
13. `frontend/src/renderer/src/components/chat/MessageBubble.vue` — `chartPayload` + `<ChartViewer>`
14. `frontend/src/renderer/src/components/chat/ToolExecutionIndicator.vue` — case chart
15. `config/system_prompt.md` — sezione `chart_generator`
16. Test `test_chart_store.py`, `test_chart_generator_plugin.py` e `test_charts_route.py`

---

### §14.12 — Verifiche

| Scenario | Risultato atteso |
|---|---|
| "Fai un grafico a barre: Gen=150, Feb=230, Mar=180" | LLM costruisce echarts_option → `generate_chart(...)` → ToolResult `application/vnd.omnia.chart+json` → `ChartViewer` in chat |
| "Fai un grafico dalla nota 'statistiche vendite'" | LLM chiama `read_note` → estrae dati → `generate_chart(...)` → viewer in chat |
| Upload immagine con tabella + "Grafico da questa tabella" | LLM legge immagine via vision → estrae valori → `generate_chart(...)` → viewer |
| `list_charts(limit=5)` | Lista con titolo, tipo, date; paginazione `offset` funzionante |
| `get_chart(chart_id)` | Metadati + `echarts_option` del grafico restituiti correttamente; chart inesistente → errore descrittivo |
| `update_chart(chart_id, echarts_option)` | Spec aggiornata su disco; `ChartViewer` ricarica e mostra grafico aggiornato |
| `delete_chart(chart_id)` | Dialog di conferma → approvazione → file eliminato; `GET /api/charts/{id}` → 404 |
| Ricaricamento conversazione con grafico precedente dal DB | `MessageBubble.vue` rileva `application/vnd.omnia.chart+json` → `ChartViewer` renderizza correttamente |
| `echarts_option` serializzata > 10.000 caratteri | Errore descrittivo con hint "aggrega i dati" |
| `chart.enabled=False` in config | Plugin non registrato; tool LLM non disponibili; REST → 503 |
| 1.000 grafici già presenti nel vault | `generate_chart` → errore limit con hint `delete_chart` |
| `chart_id` con caratteri `../` (path traversal) | `ChartStore._path()` sanitizza → file scritto dentro `data/charts/` senza uscire dalla directory |

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
| 12 | "Crea un vaso decorativo Art Nouveau" → `cad_generate(description="...")` → VRAM swap (LLM unload → TRELLIS genera GLB → LLM reload) → ToolResult con `content_type=cad-model+json` → CADViewer Three.js GLTFLoader nel frontend; ebook-mcp configurato → LLM legge docs PDF |
| 12 (edge) | TRELLIS microservizio non avviato → errore descrittivo con istruzioni; CUDA OOM → errore + LLM comunque ricaricato; `auto_vram_swap: false` su GPU ≥ 24GB → coesistenza senza swap; `model_name="../../../etc"` → sanitizzato; GLB > 100MB → ValueError; conversazione ricaricata da DB → viewer non compare (noto v1) |
| 13 | "Crea una nota sulla carbonara" → `create_note(title=..., content=..., folder_path="cucina")` → nota salvata in notes.db → conferma all'utente; "Trova note su Python" → `search_notes("Python")` → FTS5 + semantic → lista titoli; UI NoteEditor autosave dopo 800ms |
| 13 (edge) | `notes.enabled=False` → service non avviato, tool restituiscono errore graceful, REST 503, zero impatto test esistenti; `embedding_enabled=False` → solo FTS5, nessun sqlite-vec caricato; LM Studio offline → nota creata senza embedding, search solo keyword; `delete_note` → `requires_confirmation=True` → dialog conferma |
| 14 | "Fai un grafico a barre: Gen=150, Feb=230, Mar=180" → LLM costruisce echarts_option → `generate_chart(...)` → ToolResult `application/vnd.omnia.chart+json` → `ChartViewer.vue` ECharts renderizzato in chat; `get_chart` → metadati+option corretti; `list_charts` → lista paginata; `update_chart` → grafico aggiornato; ricaricamento conversazione da DB → viewer ripristinato |
| 14 (edge) | `chart.enabled=False` → tool LLM non disponibili, REST 503; `echarts_option` > 10.000 char → errore descrittivo con hint; 1.000 grafici presenti → errore limit con hint `delete_chart`; `delete_chart` → dialog conferma prima di eliminare; `chart_id` con `../` → sanitizzato, file scritto dentro `data/charts/` |
