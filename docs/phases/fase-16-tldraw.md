# Fase 16 — Integrazione tldraw (Whiteboard)

## Obiettivo

Integrazione di tldraw come lavagna interattiva in AL\CE, sia come vista
standalone sia come strumento utilizzabile dall'LLM tramite function calling.

## Architettura

### Backend (Plugin System)

- **Plugin**: `backend/plugins/whiteboard/`
  - `models.py` — Modelli Pydantic: `SimpleShape`, `WhiteboardSpec`, `WhiteboardPayload`, `WhiteboardListItem`
  - `store.py` — `WhiteboardStore` con persistenza JSON async in `data/whiteboards/`
  - `shape_builder.py` — Conversione `SimpleShape[]` → TLStoreSnapshot tldraw
  - `plugin.py` — `WhiteboardPlugin` con 5 tool LLM: `whiteboard_create`, `whiteboard_add_shapes`, `whiteboard_update`, `whiteboard_list`, `whiteboard_delete`
  - `__init__.py` — Registrazione in `PLUGIN_REGISTRY`

- **REST API**: `backend/api/routes/whiteboards.py`
  - `GET /api/whiteboards` — Lista paginata con filtro `conversation_id`
  - `GET /api/whiteboards/{id}` — Spec completa con snapshot
  - `DELETE /api/whiteboards/{id}` — Eliminazione
  - `PATCH /api/whiteboards/{id}/snapshot` — Aggiornamento snapshot dal frontend

- **Config**: `WhiteboardConfig` in `config.py`, sezione `whiteboard` in `default.yaml`

### Frontend (React Island in Vue)

- **Pattern**: React island — componente React montato dentro Vue via `createRoot()`
- **Dipendenze aggiunte**: `react`, `react-dom`, `tldraw`, `@vitejs/plugin-react`
- **Tooling**: `react()` plugin prima di `vue()` in electron.vite.config.ts, `jsx: react-jsx` in tsconfig.web.json

#### Componenti

| File | Tipo | Descrizione |
|------|------|-------------|
| `tldraw-app.tsx` | React | Wrapper tldraw con debounced save |
| `TldrawCanvas.vue` | Vue | Host per il React island |
| `WhiteboardListSidebar.vue` | Vue | Sidebar lista lavagne |
| `WhiteboardPageView.vue` | Vue | Vista pagina completa |

#### Integrazioni

- **Router**: Rotta `/whiteboard` → `WhiteboardPageView.vue`
- **Sidebar**: Link "Lavagna" tra Note e Email
- **AssistantView**: Side panel tab "Lavagna" per preview inline durante le conversazioni
- **Store**: `stores/whiteboard.ts` — Pinia store con CRUD e debounced snapshot save
- **API**: Metodi `getWhiteboards`, `getWhiteboard`, `deleteWhiteboard`, `saveWhiteboardSnapshot`
- **Types**: `types/whiteboard.ts` + `WhiteboardPayload` e `isWhiteboardPayload()` in `chat.ts`

## File Modificati

| File | Modifica |
|------|----------|
| `backend/core/config.py` | Aggiunta `WhiteboardConfig` |
| `config/default.yaml` | Sezione `whiteboard` |
| `backend/api/routes/__init__.py` | Router registration |
| `frontend/package.json` | Dipendenze React + tldraw |
| `frontend/electron.vite.config.ts` | Plugin React |
| `frontend/tsconfig.web.json` | JSX config |
| `frontend/src/.../services/api.ts` | Metodi whiteboard |
| `frontend/src/.../types/chat.ts` | `WhiteboardPayload` + type guard |
| `frontend/src/.../router/index.ts` | Rotta `/whiteboard` |
| `frontend/src/.../components/sidebar/AppSidebar.vue` | Link "Lavagna" |
| `frontend/src/.../views/AssistantView.vue` | Side panel tab whiteboard |

## File Nuovi

| File | Descrizione |
|------|-------------|
| `backend/plugins/whiteboard/models.py` | Modelli Pydantic |
| `backend/plugins/whiteboard/store.py` | Store JSON async |
| `backend/plugins/whiteboard/shape_builder.py` | Conversione → tldraw snapshot |
| `backend/plugins/whiteboard/plugin.py` | Plugin LLM (5 tool) |
| `backend/plugins/whiteboard/__init__.py` | Registry |
| `backend/api/routes/whiteboards.py` | REST endpoints |
| `frontend/src/.../types/whiteboard.ts` | TypeScript types |
| `frontend/src/.../stores/whiteboard.ts` | Pinia store |
| `frontend/src/.../components/whiteboard/tldraw-app.tsx` | React tldraw wrapper |
| `frontend/src/.../components/whiteboard/TldrawCanvas.vue` | Vue host component |
| `frontend/src/.../components/whiteboard/WhiteboardListSidebar.vue` | Lista lavagne |
| `frontend/src/.../views/WhiteboardPageView.vue` | Vista pagina |
| `docs/phases/fase-16-tldraw.md` | Questa documentazione |

## Tool LLM Disponibili

| Tool | Risk | Descrizione |
|------|------|-------------|
| `whiteboard_create` | safe | Crea una nuova lavagna con forme |
| `whiteboard_add_shapes` | safe | Aggiunge forme a una lavagna esistente |
| `whiteboard_update` | medium | Aggiorna titolo/descrizione |
| `whiteboard_list` | safe | Lista le lavagne |
| `whiteboard_delete` | dangerous | Elimina una lavagna (richiede conferma) |
