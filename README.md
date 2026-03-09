# O.M.N.I.A.

> **O**rchestrated **M**odular **N**etwork for **I**ntelligent **A**utomation — Assistente AI personale, 100% locale.

## Prerequisites

| Tool | Version | Download |
|------|---------|----------|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) |
| NVIDIA GPU | CUDA 12 compatible (optional) | Driver aggiornati |
| LM Studio **oppure** Ollama | — | [lmstudio.ai](https://lmstudio.ai/) / [ollama.com](https://ollama.com/) |

## Quick Setup

```powershell
# Dalla root del progetto:
.\scripts\setup.ps1
```

Questo installa **tutto** automaticamente:
- Virtual environment Python + dipendenze backend (core, voice, GPU, file-reader)
- Modello Piper TTS (it_IT-paola-medium, ~65 MB)
- Dipendenze frontend (npm install)
- Verifica finale di tutti i pacchetti

### Opzioni

```powershell
# Solo CPU (no CUDA, per PC senza NVIDIA)
.\scripts\setup.ps1 -CpuOnly

# Salta download modelli TTS
.\scripts\setup.ps1 -SkipModels

# Salta frontend
.\scripts\setup.ps1 -SkipFrontend

# Salta Ollama
.\scripts\setup.ps1 -SkipOllama

# Combinabili
.\scripts\setup.ps1 -CpuOnly -SkipOllama
```

## Start Development

```powershell
.\scripts\start-dev.ps1
```

Oppure manualmente:

```powershell
# Terminal 1 — Backend
.\backend\.venv\Scripts\Activate.ps1
uvicorn backend.core.app:create_app --factory --reload --reload-dir backend --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

## Project Structure

```
backend/          # Python — FastAPI, plugin system, servizi AI
  core/           # App factory, config, context, event bus, plugin system
  services/       # LLM, STT, TTS, audio services
  api/routes/     # REST + WebSocket endpoints
  plugins/        # Plugin modulari (system_info, web_search, calendar, ...)
  db/             # SQLite + SQLModel
  tests/          # pytest + pytest-asyncio
frontend/         # Electron + Vue 3 + TypeScript (electron-vite)
  src/main/       # Electron main process
  src/preload/    # Context bridge
  src/renderer/   # Vue 3 app (stores, composables, components)
config/           # YAML config, system prompt
models/           # AI model files (gitignored)
  stt/            # faster-whisper (auto-cached da HuggingFace)
  tts/            # Piper voice files (.onnx + .json)
  llm/            # LLM model files
scripts/          # Setup e dev scripts
```

## Services

| Servizio | Porta | Descrizione |
|----------|-------|-------------|
| Backend API | `localhost:8000` | FastAPI + WebSocket |
| Frontend | `localhost:5173` | Vite dev server |
| LM Studio | `localhost:1234` | LLM provider (default) |
| Ollama | `localhost:11434` | LLM provider (alternativo) |

## Testing

```powershell
cd backend
.\..\.venv\Scripts\Activate.ps1   # oppure attiva il venv
pytest tests/ -v
```
