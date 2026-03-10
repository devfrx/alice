project: OMNIA
full_name: "Orchestrated Modular Network for Intelligent Automation"
description: "Personal local AI assistant — full-stack/plugin-based/async-first"

architecture:
  backend: "Python 3.14/FastAPI/async-first/SQLite via SQLModel/plugin-based"
  frontend: "Electron + Vue 3 (Composition API) + TypeScript/electron-vite"
  llm: "LM Studio (v1 REST API + OpenAI-compatible)"
  stt: faster-whisper (CTranslate2)
  tts: "Piper TTS (primary) / XTTS v2 (optional) / Kokoro TTS (optional)"
  communication: "WebSocket (streaming) + REST API on localhost:8000"
  di: AppContext pattern

structure:
  backend: "Python — pyproject.toml/.venv/"
  backend_core: "app.py/config.py/context.py/event_bus.py/plugin_base.py/plugin_manager.py/plugin_models.py/protocols.py/tool_registry.py/http_security.py"
  backend_services: "llm_service.py/lmstudio_service.py/stt_service.py/tts_service.py/audio_utils.py/vram_monitor.py/preferences_service.py/conversation_file_manager.py/thinking_parser.py"
  backend_routes[7]: chat,voice,models,config,settings,plugins,audit
  backend_middleware[3]: exception_handler,origin_guard,rate_limit
  plugins[11]: calendar,clipboard,file_search,home_automation,media_control,news,notifications,pc_automation,system_info,weather,web_search
  db[2]: database.py,models.py
  frontend: "Electron — package.json/node_modules/"
  frontend_main: "src/main/index.ts — window mgmt/IPC/CSP"
  frontend_preload: "src/preload/index.ts — context bridge"
  frontend_stores[6]: ui,chat,voice,settings,plugins,calendar
  frontend_composables[7]: useChat,useVoice,useCalendar,useModal,useMarkdown,useCodeBlocks,usePluginComponents
  frontend_views[5]: HomeView,AssistantView,HybridView,CalendarPageView,SettingsView
  frontend_types[5]: chat.ts,settings.ts,voice.ts,plugin.ts,calendar.ts
  config: "default.yaml/system_prompt.md"
  models: "AI model files (gitignored) — llm//stt//tts/"
  scripts: "PowerShell — setup.ps1/start-dev.ps1"
  data: "conversations//uploads/ (gitignored)"

quality_rules[10]:
  - Coherence — read existing code before writing/never break signatures/endpoints/interfaces/DB schema
  - Readability — clean/intuitive/explicit code/immediately understandable
  - "Documentation — Google-style docstrings (Python)/TSDoc (TypeScript)/inline comments for non-obvious logic"
  - "Modularity — max ~200 lines per file/organize by responsibility"
  - "No technical debt — implement properly the first time/no TODO/FIXME/hack"
  - "No regressions — verify all callers before modifying/existing tests must pass"
  - "No cascading incompatibilities — Frontend ↔ Backend ↔ DB must stay consistent"
  - "Function verification — verify function exists before calling/verify no duplicate before creating"
  - "Contract consistency — API endpoints/WS messages/TS types/Pinia stores/DB models must all agree"
  - "Task-oriented — one complete logical unit at a time/no partial implementations"

code_style:
  python:
    type_hints: all functions (params + return)
    async: async def for all I/O operations
    logging: "loguru.logger (not stdlib logging)"
    paths: "pathlib.Path (not os.path)"
    http: "httpx (not requests)"
    max_line_length: 100
  typescript_vue:
    component_template: "<script setup lang=\"ts\"> exclusively"
    types: No any types
    composition: "ref()/computed()/watch() — no Options API"
    styles: CSS scoped in components

commands:
  backend_install: "cd backend; uv pip install -e \".[dev]\""
  backend_run: "uvicorn core.app:create_app --factory --reload --port 8000"
  backend_test: pytest tests/ -v
  frontend_install: cd frontend; npm install
  frontend_dev: cd frontend; npm run dev
  frontend_typecheck: cd frontend; npm run typecheck

constraints[4]:
  - "Everything runs locally — NO external paid APIs"
  - Windows primary target
  - All I/O must be async where possible
  - Plugin tools must be serializable to JSON for LLM function calling
