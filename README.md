# AL\CE

> **O**rchestrated **M**odular **N**etwork for **I**ntelligent **A**utomation — Assistente AI personale, local-first. LLM locale via LM Studio/Ollama, oppure cloud opzionale via OpenRouter (API key, a consumo); memoria ed embedding restano sempre locali.

## Prerequisites

| Tool | Version | Download |
|------|---------|----------|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) |
| NVIDIA GPU | CUDA 12 compatible (optional) | Driver aggiornati |
| LM Studio **oppure** Ollama (locale) **oppure** una API key [OpenRouter](https://openrouter.ai/) (cloud) | — | [lmstudio.ai](https://lmstudio.ai/) / [ollama.com](https://ollama.com/) |

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
trellis_server/   # TRELLIS 3D microservice wrapper (server.py)
scripts/          # Setup e dev scripts
docs/             # Guide e documentazione tecnica
```

## Services

| Servizio | Porta | Descrizione |
|----------|-------|-------------|
| Backend API | `localhost:8000` | FastAPI + WebSocket |
| Frontend | `localhost:5173` | Vite dev server |
| LM Studio | `localhost:1234` | LLM provider (default) |
| Ollama | `localhost:11434` | LLM provider (alternativo) |
| TRELLIS 3D | `localhost:8090` | Generazione 3D neurale (opzionale) |

## TRELLIS — Generazione 3D Neurale (Opzionale)

AL\CE integra [TRELLIS](https://github.com/microsoft/TRELLIS) (Microsoft Research)
per generare modelli 3D `.glb` da descrizioni in linguaggio naturale, visualizzabili
inline nella chat con un viewer Three.js interattivo.

### Setup rapido

```powershell
# 1. Clone il fork Windows (una sola volta)
#    --recurse-submodules è OBBLIGATORIO (submodule flexicubes)
cd C:\Users\Jays\Desktop\omnia
git clone --recurse-submodules https://github.com/devfrx/TRELLIS-for-windows.git

# 2. Installa + avvia
cd omnia
.\scripts\start-trellis.ps1 -Install
```

### Avvio successivo

```powershell
.\scripts\start-trellis.ps1
```

### Requisiti aggiuntivi

- NVIDIA GPU ≥16GB VRAM
- CUDA Toolkit 12.8+
- VS Build Tools 2022 (o 2025 con [patch host_config.h](docs/trellis-setup.md#6-patch-host_configh-per-vs-2025-msvc-1950))
- Python 3.10 (gestito automaticamente nel venv TRELLIS)

### Passi manuali obbligatori su GPU Blackwell (RTX 50xx)

Questi due passi **non sono automatizzabili** e vanno eseguiti una sola volta sulla macchina target:

**1. Patch `host_config.h`** — CUDA 12.8 non riconosce MSVC 19.50+ (VS 2025).
Il file è di sistema e non è distribuibile nel fork.

```c
// C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\include\crt\host_config.h
// Cambia riga ~164 da:
#if _MSC_VER < 1910 || _MSC_VER >= 1950
// a:
#if _MSC_VER < 1910 || _MSC_VER >= 2000
```

**2. Rebuild estensioni CUDA da sorgente** — le wheel pre-built nel fork sono compilate
per torch 2.5.1+cu124 (ABI incompatibile con torch 2.7.0+cu128). Devono essere
ricompilate localmente con la versione torch/CUDA installata sulla macchina.

```powershell
$env:CUDA_HOME = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8"
$env:TORCH_CUDA_ARCH_LIST = "12.0"
$env:DISTUTILS_USE_SDK = "1"
& "C:\Users\Jays\Desktop\omnia\TRELLIS-for-windows\.venv\Scripts\Activate.ps1"

# 1. diff-gaussian-rasterization
cd C:\Users\Jays\Desktop\omnia
git clone https://github.com/sdbds/diff-gaussian-rasterization.git
cd diff-gaussian-rasterization; git submodule update --init --recursive
pip install . --no-build-isolation

# 2. diffoctreerast
cd C:\Users\Jays\Desktop\omnia
git clone https://github.com/JeffreyXiang/diffoctreerast.git
cd diffoctreerast; pip install . --no-build-isolation

# 3. vox2seq
cd C:\Users\Jays\Desktop\omnia\TRELLIS-for-windows\extensions\vox2seq
pip install . --no-build-isolation
```

> Guida completa con troubleshooting: [docs/trellis-setup.md](docs/trellis-setup.md)

## Testing

```powershell
cd backend
.\..\.venv\Scripts\Activate.ps1   # oppure attiva il venv
pytest tests/ -v
```
