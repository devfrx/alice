# O.M.N.I.A. Backend

FastAPI backend for the OMNIA AI assistant.

## Architecture

- **FastAPI** app with WebSocket support for real-time chat
- **SQLModel** for database models and persistence
- **Plugin system** for extensible tool capabilities
- **Event bus** for decoupled inter-component communication

## Plugin / Tool System

OMNIA uses a modular plugin architecture for tool calling. The LLM can invoke tools at runtime to perform actions on behalf of the user.

### Key components

| Module | Role |
|---|---|
| `core/plugin_base.py` | `BasePlugin` ABC — every plugin subclasses this |
| `core/plugin_manager.py` | Discovery, dependency resolution (topological sort), lifecycle |
| `core/tool_registry.py` | Aggregates tools from plugins, validates schemas, dispatches execution |
| `core/plugin_models.py` | Shared models: `ToolDefinition`, `ToolResult`, `ExecutionContext` |

### Built-in plugins

| Plugin | Description |
|---|---|
| `system_info` | CPU, RAM, disk, battery monitoring |
| `web_search` | Internet search and page reading |
| `home_automation` | Home Assistant / MQTT device control |
| `pc_automation` | Application control, screenshots, input |
| `calendar` | Events, appointments, task management |

### Writing a plugin

1. Create a folder under `plugins/` with an `__init__.py`
2. Subclass `BasePlugin`, implement `get_tools()` and `execute_tool()`
3. Register the class in `PLUGIN_REGISTRY` at import time
4. Tool definitions use JSON Schema for parameter validation

## Running

```bash
uvicorn backend.core.app:create_app --factory --reload --host 0.0.0.0 --port 8000
```
