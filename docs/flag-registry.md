# Registro dei flag `enabled` (Fase 5 — censimento spec §5.1)

Fonte di verità sui flag booleani di abilitazione della config backend.
Regola: un flag entra qui quando nasce; un flag mai letto si elimina.
I default indicati sono quelli EFFETTIVI a runtime (YAML `config/default.yaml`,
che vince sul default pydantic).

## Il doppio gate dei plugin

`plugins.enabled` è una LISTA di nomi (seed da YAML, override persistente
per-utente nel DB via `plugin_states`): decide quali plugin vengono CARICATI.
I flag `<sezione>.enabled` qui sotto sono un SECONDO gate indipendente letto
dal plugin stesso (tool nascosti/erroranti finché false). Per accendere una
feature servono ENTRAMBI.

## Flag vivi

| Flag | Default runtime | Letto da | Note |
|---|---|---|---|
| `llm.system_prompt_enabled` | true | `services/llm/prompting.py` | salta il system prompt |
| `llm.tools_enabled` | true | `chat/_assembly.py`, `chat/conversations.py` | gate globale invio tool |
| `llm.tool_rag_enabled` | true | `chat/_assembly.py`, `rag_readiness.py` | Tool RAG vs toolset pieno |
| `llm.context_compression_enabled` | true | `chat/_assembly.py`, `turn/tool_loop.py`, `chat/_persist.py` | compaction |
| `stt.enabled` | true | bootstrap (`stage_senses`) | avvia STTService |
| `tts.enabled` | true | bootstrap (`stage_senses`) | avvia TTSService |
| `permissions.confirmations_enabled` | true | `turn/tool_loop.py`, `turn/pipeline.py` | conferme tool pericolosi |
| `commands.enabled` | true | `bootstrap/workspace.py`, `services/command_bridge.py` | spegne app_command + ingestione manifest (early-return nel bridge) |
| `terminal.enabled` | true | plugin terminal, route terminal/events | doppio gate col plugin |
| `vram.monitoring_enabled` | true | bootstrap (`stage_senses`) | |
| `memory.enabled` | true | bootstrap (`stage_knowledge`), `knowledge_init.py` | doppio gate col plugin `memory` |
| `continuum.enabled` | true | bootstrap (`stage_knowledge`), `knowledge_init.py` | doppio gate col plugin `continuum` |
| `chart.enabled` | true | plugin `chart_generator` | doppio gate |
| `whiteboard.enabled` | true | plugin `whiteboard` | doppio gate |
| `email.enabled` | false | bootstrap (`stage_senses`), plugin, route email | doppio gate |
| `email.imap_idle_enabled` | true | `services/email_service.py` | task IMAP IDLE |
| `trellis.enabled` | true | bootstrap (`stage_senses`), route services | microservizio 3D |
| `trellis2.enabled` | true | bootstrap (`stage_senses`), plugin `cad_generator` | |
| `trellis2multiview.enabled` | true | bootstrap (`stage_senses`), plugin `cad_generator` | |
| `agent.reflection.enabled` | false | `turn/factory.py` | ReflectiveTurnExecutor |
| `agent.reflection.degeneration_detector_enabled` | true | `turn/_reflection.py` | |
| `mcp.servers[].enabled` | true (per server) | plugin `mcp_client`, `chat/_helpers.py`, route mcp | per-server |
| `attention.enabled` | true | `bootstrap/jarvis.py`, `services/attention_service.py` | spegne OGNI iniziativa dell'agente verso l'utente (decision point unico §8) |
| `triggers.enabled` | true | `bootstrap/jarvis.py`, `services/trigger_service.py` | spegne i turni autonomi (nessun trigger registrato di default) |

Affini fuori convenzione: `agent.planning` / `agent.delegation` /
`agent.clarification` (gate dei meta-tool; rinominati dai legacy `*_enabled`).

## Flag rimossi in Fase 5 (morti: mai letti da alcun consumatore)

| Flag | Perché era morto |
|---|---|
| `voice.voice_confirmation_enabled` | esposto in GET/PUT config, nessun consumatore BE/FE |
| `pc_automation.enabled` | il gate reale è `plugins.enabled` (toggle DB); il flag non gate-ava nulla |
| `notifications.sound_enabled` | il plugin legge solo `default_timeout_s`/`app_id`/`max_active_timers` |

Le chiavi stantie nei layer `system.yaml`/`user.yaml` vengono eliminate dal
migratore legacy (`migrate_legacy_config_keys`, i modelli sono extra=forbid).
