# Fase 16 — Canvas AI Visiva (Lavagna Intelligente)

> **Obiettivo**: Integrare una lavagna interattiva basata su **Fabric.js** come vista full-screen
> con pop-out Electron, connessa al modello vision (Qwen 3.5 9B) tramite tre modalità:
> canvas-as-context persistente nei messaggi chat, region-select → allegato, e analisi istantanea
> in panel dedicato. Persistenza standalone su SQLite.

- [ ] §16.1  Canvas DB model in `backend/db/models.py`
- [ ] §16.2  `CanvasService` (`backend/services/canvas_service.py`) + `CanvasServiceProtocol`
- [ ] §16.3  `AppContext.canvas_service` + `OmniaEvent.CANVAS_*` + `protocols.py`
- [ ] §16.4  REST API `/api/canvas` (5 endpoint + 1 analyze)
- [ ] §16.5  App lifespan wiring (`backend/core/app.py`) + `routes/__init__.py`
- [ ] §16.6  `npm install fabric` + tipi TypeScript + note CSP
- [ ] §16.7  `types/canvas.ts`
- [ ] §16.8  `stores/canvas.ts` + `stores/chat.ts` (pendingCanvasContext)
- [ ] §16.9  `composables/useCanvas.ts`
- [ ] §16.10 `CanvasBoard.vue` + `CanvasToolbar.vue`
- [ ] §16.11 `CanvasBrowser.vue`
- [ ] §16.12 `CanvasAnalysisPanel.vue`
- [ ] §16.13 `CanvasView.vue` (vista full-screen)
- [ ] §16.14 Router `/canvas` + Sidebar link
- [ ] §16.15 `useChat.ts` — canvas-as-context injection + `services/api.ts` canvas methods
- [ ] §16.16 Electron pop-out IPC (`main/index.ts` + `preload/index.ts` + `preload/index.d.ts`)
- [ ] §16.17 Test suite (2 file, 25+ test case)
- [ ] §16.18 System prompt aggiornato (`canvas_ai:` YAML section)
- [ ] §16.19 Struttura file
- [ ] §16.20 Ordine di implementazione
- [ ] §16.21 Verifiche

---

## §16.0 — Analisi Vincoli e Scelte Architetturali

**Perché Fabric.js e non tldraw/Excalidraw:**
- tldraw ed Excalidraw sono librerie **React-only**: integrarli come iframe richiederebbe un mini-app
  React separata, CSP complicata per Electron, canale postMessage per sincronizzare lo stato con
  Vue → troppa indirection
- **Fabric.js v6** (`npm install fabric`) è framework-agnostic TypeScript-ready: si istanzia su un
  `<canvas>` nativo e si gestisce tramite `ref<fabric.Canvas>` in Vue 3. Zero dipendenze framework
  aggiuntive
- `canvas.toDataURL({format:'png', multiplier:0.5})` produce un base64 PNG da passare direttamente
  all'LLM vision — identico al flusso upload esistente
- `canvas.toJSON()` / `fabric.Canvas.loadFromJSON()` per serializzazione completa dello stato

**Perché `CanvasService` in AppContext e non route-level puro:**
- Segue il pattern SQLModel/SQLAlchemy del main DB: `initialize(engine)` crea la tabella via
  `SQLModel.metadata.create_all(engine)` se assente. Il service riceve il `session_factory`
  nell'`__init__` (pattern `PreferencesService`) e gestisce le session internamente
- **Diversamente da `NoteService`/`MemoryService`** (che usano aiosqlite dedicato), `CanvasService`
  usa l'engine condiviso dell'app — la tabella `Canvas` vive in `omnia.db`
- I test usano `create_async_engine("sqlite+aiosqlite:///:memory:")` + `SQLModel.metadata.create_all()`
- Testabile in isolamento tramite un fixture locale (vedi §16.17), route = HTTP layer sottile

**Perché persistenza standalone (no FK a `Conversation`):**
- Le canvas sono artefatti di lavoro separati dalle conversazioni chat
- Una canvas può essere inviata come contesto a N conversazioni diverse — un FK 1:1 sarebbe
  restrittivo
- Il link canvas ↔ conversazione avviene implicitamente tramite il file allegato, non nel DB

**I tre modi AI — razionale:**

1. **Canvas-as-context toggle** (innovativo): quando attivo, `useChat.ts` esporta automaticamente la
   canvas corrente come PNG prima di inviare ogni messaggio chat. L'export è a risoluzione ridotta
   (≤ 1024px) per contenere la dimensione. Il `file_id` viene memorizzato dopo il primo upload e
   riutilizzato se la canvas non è cambiata (`isDirty` tracking). Il messaggio viene prefissato con
   `[Contesto canvas: "{nome}"]` così il modello sa cosa sta guardando

2. **Region-select → allegato**: Fabric.js in Select Mode permette di selezionare un gruppo di
   oggetti. Il bounding-box della selezione viene usato come `crop` in `canvas.toDataURL()`. Il PNG
   ritagliato viene allegato al messaggio corrente nella chat — precisione chirurgica sul dettaglio
   di interesse

3. **Analisi istantanea** (`POST /api/canvas/analyze`): chiamata REST non-streaming (il modello
   vision produce risposte brevi). Il backend costruisce un messaggio multimodale tramite
   `build_messages()` e **drena l'async generator** `ctx.llm_service.chat()` raccogliendo tutti i
   chunk in un'unica stringa — `LLMService` non ha un metodo `chat_complete()` non-streaming.
   Ritorna `{"analysis": "..."}`. Il panel destro mostra il risultato. Senza history DB — ogni
   analisi è indipendente. Espandibile a SSE in una fase futura

**Pop-out Electron:**
- IPC handler `canvas-popout` in `main/index.ts` crea una secondaria `BrowserWindow` frameless che
  carica l'hash `#/canvas?detached=true`
- Il renderer Vue in `CanvasView.vue` rileva `route.query.detached === 'true'` e nasconde la sidebar
  di navigazione globale e il `CanvasBrowser` per un'esperienza canvas-only
- La finestra pop-out opera indipendentemente: carica la canvas corrente dal DB alla mount, salva le
  modifiche normalmente. Non c'è real-time sync tra main e pop-out window — la sincronizzazione
  avviene tramite il DB al focus/blur delle finestre
- Al ritorno nella main window, `CanvasView` ricarica la canvas dal server sull'evento
  `window.addEventListener('focus', ...)`. `visibilitychange` gestisce il caso in cui la finestra
  viene minimizzata/ripristinata; `focus` gestisce il caso (più comune con pop-out) in cui entrambe
  le finestre sono visibili simultaneamente e l'utente clicca dalla pop-out alla main

**Perché analisi non-streaming e non via WebSocket:**
- Il WebSocket `/ws/chat` è gestito da `chat.ts` store a livello globale: iniettare i messaggi di
  analisi canvas nello stesso stream interferirebbe con la conversazione attiva
- Una REST call POST separata è più semplice, non condivide stato, non richiede un secondo WS. La
  latenza di un'analisi visiva è già nell'ordine dei 2-5s — lo spinner è sufficiente

---

## §16.1 — Canvas DB model (`backend/db/models.py`)

Aggiungere dopo i modelli esistenti:

```python
class Canvas(SQLModel, table=True):
    """Persistent whiteboard canvas stored as Fabric.js JSON + PNG thumbnail."""

    __tablename__ = "canvas"
    __table_args__ = (
        sa.Index("ix_canvas_created_at", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=_new_uuid, primary_key=True)
    name: str = Field(default="Nuova lavagna", max_length=120)
    fabric_json: str = Field(default='{"version":"6.0.0","objects":[]}')
    """Serialized Fabric.js canvas state (JSON string)."""
    thumbnail_b64: str | None = Field(default=None)
    """Base64-encoded PNG thumbnail (piccolo, max ~75 000 char base64 = ~512px PNG).
    Stored inline in SQLite per semplicità. CanvasService deve rifiutare thumbnails
    con len(thumbnail_b64) > 75_000. CanvasItem (listing) NON include questo campo."""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
```

> **Nota sulle factory**: `_new_uuid` e `_utcnow` sono helper di modulo già definiti in `models.py`
> — usarli invece di lambda inline per coerenza con tutti gli altri modelli del file.

---

## §16.2 — `CanvasService` (`backend/services/canvas_service.py`)

`CanvasService` riceve il `session_factory: async_sessionmaker` nel costruttore (pattern
`PreferencesService`) e gestisce le session **internamente** — le route non passano una session:

```
def __init__(self, session_factory: async_sessionmaker) -> None
async def initialize() -> None          # crea tabella se assente (SQLModel.metadata.create_all)
async def list_canvases() -> list[CanvasItem]      # senza fabric_json e senza thumbnail_b64
async def create_canvas(name) -> Canvas
async def get_canvas(canvas_id) -> Canvas | None
async def update_canvas(canvas_id, name?, fabric_json?, thumbnail_b64?) -> Canvas | None
async def delete_canvas(canvas_id) -> bool
```

`CanvasItem` è un Pydantic model (no `table=True`) — campi per i listing:

```python
class CanvasItem(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime
    # thumbnail_b64 ESCLUSO: può essere decine di KB — solo GET /{id} lo restituisce
```

> **Nota**: `update_canvas` deve assegnare esplicitamente `updated_at = _utcnow()` ad ogni
> aggiornamento — SQLModel non ha `onupdate` automatico.

---

## §16.3 — AppContext + Events (`context.py`, `event_bus.py`, `protocols.py`)

**`backend/core/protocols.py`** — aggiungere `CanvasServiceProtocol`:
```python
@runtime_checkable
class CanvasServiceProtocol(Protocol):
    async def initialize(self) -> None: ...
    async def list_canvases(self) -> list["CanvasItem"]: ...
    async def create_canvas(self, name: str) -> "Canvas": ...
    async def get_canvas(self, canvas_id: uuid.UUID) -> "Canvas | None": ...
    async def update_canvas(self, canvas_id: uuid.UUID, **kwargs: Any) -> "Canvas | None": ...
    async def delete_canvas(self, canvas_id: uuid.UUID) -> bool: ...
```

In `context.py` — aggiungere campo (tipato tramite Protocol, non classe concreta, per evitare
circular imports e rispettare il pattern DI già usato per tutti gli altri service):
```python
canvas_service: CanvasServiceProtocol | None = None
```

In `event_bus.py` — aggiungere a `OmniaEvent`:
```python
CANVAS_CREATED = "canvas.created"
CANVAS_UPDATED = "canvas.updated"
CANVAS_DELETED = "canvas.deleted"
```

---

## §16.4 — REST API (`backend/api/routes/canvas.py`)

Router prefix: `/canvas` (il prefix `/api` viene dal parent router in `routes/__init__.py`).
I path finali risultanti sono `/api/canvas/...`.

> **⚠️ Ordine registrazione obbligatorio** (FastAPI matcha in ordine): `POST /analyze` deve essere
> registrata **prima** di `GET /{id}`, altrimenti `analyze` viene consumata come `id`.

| Ordine | Method   | Path          | Descrizione                                                     |
|--------|----------|---------------|-----------------------------------------------------------------|
| 1      | `GET`    | `/`           | Lista canvas (`CanvasItem`, senza `fabric_json`)                |
| 2      | `POST`   | `/`           | Crea canvas (body: `{name?: str}`)                              |
| 3      | `POST`   | `/analyze`    | Analisi vision (body: `CanvasAnalyzeRequest`) — **prima di /{id}** |
| 4      | `GET`    | `/{id}`       | Dettaglio con `fabric_json`                                     |
| 5      | `PUT`    | `/{id}`       | Aggiorna (body: `CanvasUpdateRequest`)                          |
| 6      | `DELETE` | `/{id}`       | Elimina                                                         |

`CanvasUpdateRequest`:
```python
class CanvasUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    fabric_json: str | None = None
    thumbnail_b64: str | None = None
```

`CanvasAnalyzeRequest`:
```python
class CanvasAnalyzeRequest(BaseModel):
    thumbnail_b64: str    # base64 PNG (raw base64, senza prefisso data URI)
    prompt: str = "Analizza questa lavagna e descrivi in dettaglio cosa vedi."
    canvas_name: str | None = None
```

> **Nota base64**: il renderer deve rimuovere il prefisso `data:image/png;base64,` prima di inviare
> il payload — `llm_service.build_messages()` accetta byte grezzi, non data URI.

Il handler `analyze_canvas` **drena l'async generator** `ctx.llm_service.chat()`:
```python
messages = ctx.llm_service.build_messages(
    user_content=f"[Canvas: {req.canvas_name or 'senza nome'}]\n{req.prompt}",
    attachments=[{"content_type": "image/png", "_bytes": base64.b64decode(req.thumbnail_b64)}],
    system_prompt="Sei un assistente visivo. Rispondi in modo chiaro e strutturato.",
)
text_parts: list[str] = []
async for event in ctx.llm_service.chat(messages=messages, user_content=req.prompt):
    if event.get("type") == "text":
        text_parts.append(event.get("content", ""))
analysis = "".join(text_parts)
```

> **`chat_complete()` non esiste**: `LLMService.chat()` è l'unico entry-point, sempre streaming
> (async generator). Non aggiungere un nuovo metodo — drenare il generator è la soluzione
> corretta e minimale.

---

## §16.5 — `app.py` — Router registration + lifespan

**Registrazione router** — seguire il pattern esistente: aggiungere in
`backend/api/routes/__init__.py` (non direttamente in `app.py`):

```python
# In backend/api/routes/__init__.py, insieme agli altri include:
from backend.api.routes import canvas   # ..., calendar, notes, canvas
...
router.include_router(canvas.router)
```

Il file `canvas.py` deve definire il router con il suo prefix relativo:
```python
router = APIRouter(prefix="/canvas", tags=["canvas"])
```

Il parent `APIRouter(prefix="/api")` in `routes/__init__.py` produce il path finale
`/api/canvas/...`. **Non usare** `app.include_router(canvas_router, prefix="/api/canvas")` in
`app.py` — duplicherebbe il prefix.

**Lifespan startup** — dopo gli altri service:
```python
from backend.services.canvas_service import CanvasService
ctx.canvas_service = CanvasService(session_factory)
await ctx.canvas_service.initialize()
```

> `session_factory` è già disponibile nel lifespan di `app.py` (stessa variabile usata da
> `PreferencesService`).

---

## §16.6 — Dipendenze

**Frontend:**
```
npm install fabric   # runtime dependency — NON usare --save-dev (segue il pattern di three, echarts, cytoscape)
```

`fabric@^6` include i tipi TypeScript nativi — zero `@types/*` aggiuntivi.

**Backend:** nessuna nuova dipendenza Python — `base64` è stdlib. **Attenzione**: `llm_service.py`
accetta immagini tramite `file_path` su disco, NON inline base64 da data URL. Il PNG esportato da
Fabric.js (`canvas.toDataURL()`) deve essere POST-ato via multipart alla route di upload esistente
(`POST /api/chat/upload`) per ottenere un `file_path`; in alternativa il `analyze` handler in
§16.4 riceve raw base64 e usa `base64.b64decode()` per costruire i byte da passare a
`build_messages()` via `_bytes` (see §16.4).

**CSP** (`frontend/src/main/index.ts`): se vengono usati filtri Fabric.js
(`fabric.Image.filters.*`), aggiungere `"worker-src 'self' blob:"` a `devCsp` e `prodCsp` — i
Web Worker di Fabric vengono serviti come `blob:` URL. Non necessario se il canvas è solo
drawing/annotation senza filtri immagine.

---

## §16.7 — `types/canvas.ts`

```typescript
export interface CanvasItem {
  id: string
  name: string
  thumbnail_b64: string | null
  created_at: string
  updated_at: string
}

export interface CanvasDetail extends CanvasItem {
  fabric_json: string
}

export interface CanvasAnalysisResponse {
  analysis: string
  canvas_name: string | null
}

export type CanvasTool =
  | 'select'
  | 'pen'
  | 'eraser'
  | 'text'
  | 'rect'
  | 'circle'
  | 'line'
  // 'arrow' omesso: Fabric.js v6 non ha tool arrow nativo (richiederebbe overlay custom)

export interface CanvasToolbarState {
  activeTool: CanvasTool
  strokeColor: string
  fillColor: string
  strokeWidth: number
  opacity: number
}
```

---

## §16.8 — `stores/canvas.ts`

Pinia store. Stato:

```typescript
canvases: ref<CanvasItem[]>([])
currentCanvas: ref<CanvasDetail | null>(null)
contextEnabled: ref(false)        // canvas-as-context toggle
isDirty: ref(false)               // canvas ha modifiche non salvate
cachedContextFile: ref<FileAttachment | null>(null)  // attachment cacheato per context
// FileAttachment importata da '../types/chat'
isAnalyzing: ref(false)
lastAnalysis: ref<string | null>(null)
exportFn: ref<(() => Promise<string>) | null>(null)  // registrata da CanvasBoard
loading: ref(false)               // per list/load operations
saving: ref(false)                // per save operations
error: ref<string | null>(null)   // ultimo errore (reset ad ogni action)
```

> **Pattern loading/error**: ogni action async fa `loading.value = true; try { ... }
> catch (err) { error.value = String(err) } finally { loading.value = false }` —
> stesso pattern di `stores/notes.ts`.

Actions:
- `loadCanvases()` — GET `/api/canvas/`
- `createCanvas(name?)` — POST `/api/canvas/`
- `loadCanvas(id)` — GET `/api/canvas/{id}`, sets `currentCanvas`
- `saveCanvas(fabricJson, thumbnailB64)` — PUT `/api/canvas/{id}`, resets `isDirty`
- `deleteCanvas(id)` — DELETE `/api/canvas/{id}`
- `renameCanvas(id, name)` — PUT `/api/canvas/{id}` con solo `name`
- `analyzeCanvas(thumbnailB64, prompt?)` — POST `/api/canvas/analyze`
- `markDirty()` — sets `isDirty = true`, invalida `cachedContextFile = null`
- `setContextEnabled(val)` — toggle + reset `cachedContextFile = null`
- `registerExportFn(fn)` / `unregisterExportFn()` — per l'accesso da `useChat.ts`
- `getCachedContextFile()` — ritorna `cachedContextFile.value` (tipo `FileAttachment | null`)
- `setCachedContextFile(file: FileAttachment)` — salva l'attachment cacheato

---

## §16.9 — `composables/useCanvas.ts`

Composable che gestisce l'istanza Fabric.js e le operazioni canvas.

```typescript
const fabricRef = ref<fabric.Canvas | null>(null)

// Init/destroy
function initCanvas(el: HTMLCanvasElement, initialJson?: string): void
function destroyCanvas(): void

// Strumenti
function setTool(tool: CanvasTool): void
function setColor(stroke: string, fill: string): void
function setStrokeWidth(w: number): void

// Export
async function exportDataUrl(scale?: number): Promise<string>
// scale=1.0 full res, scale=0.5 per context, crop per region-select

async function exportSelection(): Promise<string | null>
// Esporta il bounding-box dell'oggetto/selezione attiva come PNG ritagliato

// Serializzazione
function getJson(): string
async function loadJson(json: string): Promise<void>
// GUARD: if (!fabricRef.value) return  — fabric può essere null prima di onMounted
// o dopo onUnmounted. Caller (watcher in CanvasBoard) deve usare { immediate: false }.

// History (stack JSON, max 50)
function undo(): void
function redo(): void

// Canvas ops
function clearCanvas(): void
function addTextAt(x: number, y: number): void
```

**Undo/Redo**: Fabric.js v6 non ha history built-in. Implementare uno stack di snapshot JSON:
- `historyStack: string[]` (max 50 entries), `historyIndex: number`
- Ogni modifica useriale triggera `_pushHistory()` dopo `object:modified`, `object:added`,
  `object:removed`
- `undo()`: carica `historyStack[--historyIndex]`
- `redo()`: carica `historyStack[++historyIndex]`

---

## §16.10 — `CanvasBoard.vue` + `CanvasToolbar.vue`

**`CanvasBoard.vue`**:
- Template: `<canvas ref="canvasEl" />` dentro un contenitore `position: relative; overflow: hidden`
- **Importante**: `useCanvas()` va chiamato al **top-level di `<script setup>`** (non dentro
  `onMounted`) — i composable Vue 3 devono avere un'istanza componente attiva:
  ```typescript
  const canvas = useCanvas()  // top-level
  onMounted(() => {
    canvas.initCanvas(canvasEl.value!, props.initialJson)
    canvasStore.registerExportFn(() => canvas.exportDataUrl(0.5))
  })
  ```
- `onUnmounted`: `canvas.destroyCanvas()` + `canvasStore.unregisterExportFn()`
- Watch su `props.initialJson` con `{ immediate: false }`: se cambia (caricamento canvas diversa),
  `canvas.loadJson()`. Il flag `immediate: false` è essenziale perché `loadJson` ha un guard
  `if (!fabricRef.value) return` e il watcher viene registrato prima di `onMounted`
- Emette `@change(json: string, thumbnailB64: string)` con debounce 800ms su ogni modifica
- `@change` gestito da `CanvasView.vue`: `canvasStore.markDirty()` + auto-save debounce 2000ms

**`CanvasToolbar.vue`** (toolbar verticale sinistra):
- Strumenti: Select, Pen (freehand), Eraser, Text, Rect, Circle, Line
- Color picker nativo `<input type="color">` per stroke e fill
- Slider stroke width `<input type="range" min="1" max="40">`
- Undo/Redo (Ctrl+Z / Ctrl+Shift+Z) — listener su `document` in `onMounted`/`onUnmounted`,
  con check su `event.target` per non sparare quando il focus è su un `<input>` o `<textarea>`;
  `event.preventDefault()` per sopprimere il menu nativo Electron
- Clear canvas (con confirm dialog)
- Pulsante **"Invia selezione"** — attivo solo se `hasFabricSelection` → emette `@sendSelection`
- Toggle **"Contesto AI"** con indicatore visivo verde quando attivo
- Pulsante **"🔍 Analizza"** → emette `@analyze`

---

## §16.11 — `CanvasBrowser.vue`

Pannello sinistro (280px). Pattern identico a `NotesBrowser.vue`:

- Header con bottone "+ Nuova lavagna" → `canvasStore.createCanvas()` poi `loadCanvas(id)`
- Lista scrollabile di `CanvasItem`:
  - Thumbnail preview 32×32 (o placeholder se `thumbnail_b64` è null)
  - Nome canvas (click-to-rename inline con `<input>` su doppio click)
  - Data modifica relativa ("5 min fa")
  - Icona cestino con conferma tramite `useModal().confirm()` (tipo `'danger'`) — stesso pattern
    di `NotesBrowser.vue`, **non** un toast (i toast sono informativi, non di conferma)
- Item attivo evidenziato (bordo accent color)
- Stato vuoto: "Crea la tua prima lavagna"

---

## §16.12 — `CanvasAnalysisPanel.vue`

Pannello destro (320px, collassabile):

```html
<div class="analysis-panel">
  <div class="analysis-panel__header">
    <span>Analisi AI</span>
    <button @click="$emit('close')">✕</button>
  </div>

  <div class="analysis-panel__prompt">
    <textarea v-model="promptText" placeholder="Cosa vuoi sapere? (opzionale)" />
    <button @click="runAnalysis" :disabled="canvasStore.isAnalyzing">
      {{ canvasStore.isAnalyzing ? 'Analisi in corso...' : 'Analizza' }}
    </button>
  </div>

  <div class="analysis-panel__result">
    <div v-if="canvasStore.isAnalyzing" class="spinner" />
    <div
      v-else-if="canvasStore.lastAnalysis"
      class="analysis-panel__markdown"
      v-html="renderMarkdown(canvasStore.lastAnalysis)"
    />
    <!-- renderMarkdown da composables/useMarkdown.ts, stesso pattern di MessageBubble.vue -->
    <p v-else class="placeholder">Clicca "Analizza" per inviare la lavagna all'AI</p>
  </div>

  <div class="analysis-panel__footer">
    <button @click="sendToChat">💬 Continua in chat</button>
  </div>
</div>
```

`runAnalysis()`:
1. `const dataUrl = await canvasStore.exportFn?.()` (full res via store-registered fn)
2. `await canvasStore.analyzeCanvas(dataUrl, promptText.value || undefined)`

`sendToChat()`:
1. `const dataUrl = await canvasStore.exportFn?.()`
2. Rimuovi prefisso `data:image/png;base64,` dal dataUrl per ottenere raw base64
3. Naviga a `/hybrid`
4. `chatStore.setPendingCanvasContext({ dataUrl, canvasName: canvasStore.currentCanvas?.name ?? '' })`
   (`pendingCanvasContext` è un campo aggiunto a `chat.ts` store — vedi nota §16.15)
5. `HybridView.vue` legge `chatStore.pendingCanvasContext` con un `watch` reattivo e lo converte
   in un attachment al prossimo invio

---

## §16.13 — `CanvasView.vue`

Layout three-panel:

```html
<template>
  <div class="canvas-view" :class="{ 'canvas-view--detached': isDetached }">
    <!-- LEFT: browser panel (nascosto in modalità detached) -->
    <CanvasBrowser v-if="!isDetached" class="canvas-view__browser" />

    <!-- CENTER: canvas area -->
    <div class="canvas-view__main">
      <div class="canvas-view__topbar">
        <span class="canvas-name">{{ currentName }}</span>
        <button @click="saveNow" :class="{ dirty: canvasStore.isDirty }">Salva</button>
        <button v-if="!isDetached" @click="popOut">↗ Pop-out</button>
      </div>
      <CanvasToolbar
        v-bind="toolbarState"
        @tool-change="setTool"
        @color-change="setColor"
        @stroke-width-change="setStrokeWidth"
        @send-selection="handleSendSelection"
        @toggle-context="canvasStore.setContextEnabled"
        @analyze="showAnalysisPanel = true"
      />
      <CanvasBoard
        :initial-json="canvasStore.currentCanvas?.fabric_json"
        @change="handleCanvasChange"
      />
    </div>

    <!-- RIGHT: analysis panel (collassabile) -->
    <CanvasAnalysisPanel
      v-if="showAnalysisPanel"
      class="canvas-view__analysis"
      @close="showAnalysisPanel = false"
    />
  </div>
</template>
```

`isDetached` = `route.query.detached === 'true'`

`popOut()`:
```typescript
await window.electron.canvas.popout(canvasStore.currentCanvas?.id)
```

Auto-save con debounce 2000ms: quando `isDirty` diventa true, avvia un timer; al timeout chiama
`saveCanvas()`.

Ricarica al ritorno dal pop-out: `window.addEventListener('focus', reloadIfStale)` dove stale =
`updatedAt` nel DB è più recente dell'istanza corrente. Usare `focus` (non `visibilitychange` che
non scatta quando entrambe le finestre Electron sono visibili simultaneamente).

---

## §16.14 — Router + Sidebar

**`router/index.ts`** — aggiungere **prima del catch-all** `/:pathMatch(.*)*`:
```typescript
{
  path: '/canvas',
  name: 'canvas',
  component: () => import('../views/CanvasView.vue'),
},
```

> **`MODE_ROUTES`** in `router/index.ts`: `'canvas'` non va aggiunto a `MODE_ROUTES` — Canvas è
> una vista standalone, non una transizione di modalità UI.

**`AppSidebar.vue`** — aggiungere link canvas con SVG icon (pennello), posizione dopo "Note" e
prima di "Email":
```html
<router-link to="/canvas" class="sidebar__link" active-class="sidebar__link--active">
  <!-- SVG icon: pennello/canvas -->
  <span class="sidebar__link-label">Canvas</span>
</router-link>
```

---

## §16.15 — `useChat.ts` — Canvas-as-context injection

**Prerequisito — `stores/chat.ts`**: aggiungere campo e action:
```typescript
const pendingCanvasContext = ref<{ dataUrl: string; canvasName: string } | null>(null)
function setPendingCanvasContext(ctx: { dataUrl: string; canvasName: string } | null): void {
  pendingCanvasContext.value = ctx
}
```
Esporre nel return del defineStore. `HybridView.vue` legge questo valore tramite un `watch` e
lo consuma (setta a null) al prossimo invio messaggio.

**In `sendMessage()`**: `trimmed` è `const` nella versione attuale — deve diventare `let` per
permettere il prefisso canvas. Questa è la **prima modifica** da applicare a `sendMessage()`:
```typescript
let trimmed = content.trim()  // era: const trimmed = content.trim()
```

Dopo l'upload dei file manuali e prima della costruzione del payload:

```typescript
// Canvas-as-context: inietta snapshot canvas come attachment se toggle attivo
if (canvasStore.contextEnabled && canvasStore.currentCanvas && convId) {
  const contextAttachment = await uploadCanvasContext(convId)
  if (contextAttachment) {
    uploaded = [...(uploaded ?? []), contextAttachment]
    trimmed = `[Contesto canvas: "${canvasStore.currentCanvas.name}"]\n${trimmed}`
  }
}
```

Helper `uploadCanvasContext(convId: string): Promise<FileAttachment | null>`:
```typescript
async function uploadCanvasContext(convId: string): Promise<FileAttachment | null> {
  // Usa il cache se canvas non è cambiata
  if (!canvasStore.isDirty && canvasStore.cachedContextFile) {
    return canvasStore.getCachedContextFile()
  }
  // Esporta a risoluzione ridotta tramite la fn registrata nello store
  const dataUrl = await canvasStore.exportFn?.()
  if (!dataUrl) return null
  // Converti dataUrl → File (usa Blob per evitare problemi CSP con fetch(data:...))
  const base64 = dataUrl.replace(/^data:image\/png;base64,/, '')
  const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0))
  const blob = new Blob([bytes], { type: 'image/png' })
  const file = new File([blob], `canvas-ctx-${Date.now()}.png`, { type: 'image/png' })
  const attachment = await api.uploadFile(file, convId)
  canvasStore.setCachedContextFile(attachment)
  return attachment
}
```

> **CSP**: `fetch(dataUrl)` dove `dataUrl` è `data:image/png;base64,...` verrebbe bloccato da
> `connect-src 'self'` in Electron. Il helper sopra usa `atob()` + `Uint8Array` che non richiede
> fetch — nessuna modifica CSP necessaria per questa operazione.

**Region-select** (`handleSendSelection()` in `CanvasView.vue`):
1. `const dataUrl = await canvas.exportSelection()` — se null, mostra toast warning
2. Naviga a `/hybrid`
3. `chatStore.setPendingCanvasContext({ dataUrl, canvasName: canvasStore.currentCanvas?.name ?? '' })`
4. `ChatInput.vue` USA `watch(() => chatStore.pendingCanvasContext, (val) => { ... },
   { immediate: true })` per consumare l'attachment reattivamente, **non** `onMounted` —
   se l'utente è già su `/hybrid`, il componente è montato e `onMounted` non riscatta

---

## §16.16 — Electron Pop-out IPC

**`main/index.ts`** — aggiungere handler:
```typescript
ipcMain.handle('canvas-popout', async (_event, canvasId?: string) => {
  const detachedWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 800,
    minHeight: 600,
    frame: false,
    show: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true,           // deve essere true come nella main window
      nodeIntegration: false,  // esplicito per sicurezza
      contextIsolation: true,
    },
  })

  const hash = canvasId
    ? `/canvas?detached=true&canvasId=${canvasId}`
    : '/canvas?detached=true'

  if (is.dev && process.env.ELECTRON_RENDERER_URL) {
    await detachedWindow.loadURL(`${process.env.ELECTRON_RENDERER_URL}#${hash}`)
  } else {
    await detachedWindow.loadFile(join(__dirname, '../renderer/index.html'), { hash })
  }

  detachedWindow.once('ready-to-show', () => detachedWindow.show())
})
```

**`preload/index.ts`** — estendere `contextBridge.exposeInMainWorld` con il namespace `canvas`:
```typescript
const canvas = {
  popout: (canvasId?: string): Promise<void> => ipcRenderer.invoke('canvas-popout', canvasId),
}
// La call a exposeInMainWorld diventa:
contextBridge.exposeInMainWorld('electron', { ...electronAPI, windowControls, fileOps, canvas })
```

Aggiornare il tipo TypeScript in **`frontend/src/preload/index.d.ts`** (non `env.d.ts`):
```typescript
interface Canvas {
  popout: (canvasId?: string) => Promise<void>
}
// Nel blocco Window interface, estendere electron:
electron: ElectronAPI & { windowControls: WindowControls; fileOps: FileOps; canvas: Canvas }
```

> **Fallback preload**: il branch `window.electron = { ...electronAPI, windowControls, fileOps }`
> (non-isolated context fallback) va aggiornato con `canvas` per coerenza.

---

## §16.17 — Test Suite

**`tests/test_canvas_service.py`** (15+ test):

Definire un fixture file-locale `canvas_svc` (analogo a `note_svc` in `test_note_service.py`):
```python
@pytest_asyncio.fixture
async def canvas_svc():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    svc = CanvasService(session_factory)
    await svc.initialize()
    yield svc
    await engine.dispose()
```

Test cases:
- `test_create_canvas` — crea, verifica campi default
- `test_list_canvases` — lista vuota + lista con 2 canvas
- `test_get_canvas` — get by id, get non-esistente → None
- `test_update_fabric_json` — `await asyncio.sleep(0.001)` **prima** dell'update per garantire
  `updated_at_after > updated_at_before` (SQLModel non ha `onupdate` automatico; il service deve
  assegnare esplicitamente `updated_at = _utcnow()` ad ogni update)
- `test_update_thumbnail` — aggiorna `thumbnail_b64`
- `test_rename_canvas` — aggiorna solo `name`
- `test_delete_canvas` — delete + verifica assenza
- `test_delete_nonexistent` — ritorna False senza errore

**`tests/test_canvas_routes.py`** (10+ test):
- `test_list_empty` — GET `/api/canvas/` ritorna lista vuota
- `test_create_and_get` — POST poi GET by id
- `test_update_canvas` — PUT body parziale
- `test_delete_canvas` — DELETE + 404 successivo
- `test_analyze_canvas` — POST `/api/canvas/analyze` con mock LLM service

**Mock LLM** — **non** in `conftest.py` (non c'è un pattern LLM mock centralizzato). Usare il
pattern file-locale di `test_concurrent.py`:
```python
async def _mock_canvas_analyze(*args, **kwargs):
    """Async generator che simula una risposta vision."""
    yield {"type": "text", "content": "Vedo un diagramma con due rettangoli collegati."}
    yield {"type": "done", "content": ""}

@pytest_asyncio.fixture
async def canvas_app(app):  # wrappa il fixture app da conftest
    app.state.context.llm_service.chat = _mock_canvas_analyze
    yield app
```

Il `client` di test va costruito usando `canvas_app` invece di `app` quando si testa
`test_analyze_canvas`.

---

## §16.18 — System prompt (`config/system_prompt.md`)

**Formato**: il file usa struttura YAML key-value, **non** heading Markdown. Aggiungere in
append dopo la sezione `email_assistant:` (ultima sezione attualmente), prima del blocco
`## Ambiente utente` che viene aggiunto dinamicamente da `_load_system_prompt()`:

```yaml
canvas_ai:
  context_toggle: "quando l'utente include una canvas come contesto (prefisso [Contesto canvas: '...']): analizza attentamente l'immagine allegata prima di rispondere"
  spatial: descrivi forme, testo, diagrammi e layout con precisione spaziale
  direct_response: se il messaggio contiene una domanda sulla canvas, rispondi in modo diretto e specifico
  suggestions: puoi suggerire miglioramenti o interpretazioni del disegno se pertinente
```

---

## §16.19 — Struttura file

```
backend/
  db/
    models.py                      ← aggiunto Canvas model
  services/
    canvas_service.py              ← NUOVO
  api/
    routes/
      canvas.py                    ← NUOVO
      __init__.py                  ← aggiunto canvas.router
  core/
    protocols.py                   ← aggiunto CanvasServiceProtocol
    context.py                     ← aggiunto canvas_service: CanvasServiceProtocol | None
    config.py                      ← aggiunto CanvasConfig (contesto export max px, thumbnail max px)
    app.py                         ← lifespan: CanvasService(session_factory)
  tests/
    test_canvas_service.py         ← NUOVO
    test_canvas_routes.py          ← NUOVO

frontend/src/
  renderer/src/
    types/
      canvas.ts                    ← NUOVO
    stores/
      canvas.ts                    ← NUOVO
      chat.ts                      ← aggiunto pendingCanvasContext + setPendingCanvasContext
    composables/
      useCanvas.ts                 ← NUOVO
      useChat.ts                   ← modificato (canvas context injection, let trimmed)
    services/
      api.ts                       ← aggiunto metodi canvas (getCanvases, createCanvas,
                                      getCanvas, saveCanvas, deleteCanvas, renameCanvas,
                                      analyzeCanvas)
    views/
      CanvasView.vue               ← NUOVO
    components/
      canvas/
        CanvasBoard.vue            ← NUOVO
        CanvasToolbar.vue          ← NUOVO
        CanvasBrowser.vue          ← NUOVO
        CanvasAnalysisPanel.vue    ← NUOVO
    router/
      index.ts                     ← aggiunto /canvas route (prima del catch-all)
    components/sidebar/
      AppSidebar.vue               ← aggiunto canvas link
  main/
    index.ts                       ← aggiunto canvas-popout IPC handler
  preload/
    index.ts                       ← esposto window.electron.canvas.popout()
    index.d.ts                     ← aggiunto tipo Canvas al Window interface
config/
  default.yaml                     ← aggiunta sezione canvas:
  system_prompt.md                 ← aggiunta sezione canvas_ai: (YAML)
```

---

## §16.20 — Ordine di implementazione

**Step 1** (backend, sequenziali per dipendenze di import):
- §16.1 DB model (`Canvas` in `models.py`)
- §16.2 `CanvasService` + `CanvasServiceProtocol` in `protocols.py` *(dipende da §16.1)*
- §16.3 `AppContext.canvas_service` + `OmniaEvent.CANVAS_*` *(dipende da §16.2)*

**Step 2** (dipende da Step 1):
- §16.4 REST routes `canvas.py`
- §16.5 `app.py` wiring

**Step 3** (frontend types + store, parallelizzabili):
- §16.6 `npm install fabric`
- §16.7 `types/canvas.ts`
- §16.8 `stores/canvas.ts`

**Step 4** (composable, dipende da Step 3):
- §16.9 `useCanvas.ts`

**Step 5** (componenti, parallelizzabili dopo Step 3-4):
- §16.10 `CanvasBoard.vue` + `CanvasToolbar.vue`
- §16.11 `CanvasBrowser.vue`
- §16.12 `CanvasAnalysisPanel.vue`

**Step 6** (view + routing, dipende da Step 5):
- §16.13 `CanvasView.vue`
- §16.14 Router + Sidebar

**Step 7** (integrazione chat + IPC, dipende da Step 6):
- §16.15 `useChat.ts` injection
- §16.16 Electron IPC

**Step 8** (finale):
- §16.17 Test suite
- §16.18 System prompt
- §16.19 Verifiche

---

## §16.21 — Verifiche

1. `pytest tests/test_canvas_service.py tests/test_canvas_routes.py -v` → tutti pass
2. `cd frontend && npm run typecheck` → 0 errori
3. Click su "Canvas" nella sidebar → `CanvasView.vue` carica correttamente
4. Click "+ Nuova lavagna" → appare in `CanvasBrowser` con nome default
5. Pen tool → disegna una linea → canvas mostra il segno
6. `Ctrl+Z` → undo funziona; `Ctrl+Y` → redo funziona
7. Modifica → `isDirty = true` → click "Salva" → `PUT /api/canvas/{id}` 200
8. Riavvia app → naviga a Canvas → canvas mostra lo stato salvato (Fabric.js JSON ripristinato)
9. Attiva toggle "Contesto AI" → invia messaggio in `/hybrid` → backend log contiene
   `"Built multimodal message with 1 image(s)"` (emesso da `llm_service.build_messages()`)
10. Select tool → seleziona oggetti → click "Invia selezione" → naviga a chat → PNG allegato
    visibile nel `ChatInput`
11. Click "Analizza" → `CanvasAnalysisPanel` apre → click "Analizza" → risposta LLM nel panel
12. Click "↗ Pop-out" → finestra secondaria si apre con canvas corrente; modifica in pop-out →
    salva → torna alla main window → main ricarica dal DB sull'evento `window 'focus'`
    (`visibilitychange` non è affidabile quando entrambe le finestre sono visibili simultaneamente)
13. In modalità detached: sidebar di navigazione globale è nascosta
14. `pytest tests/ -v` → tutti i test esistenti passano (nessuna regressione)
