# Invariants map — Fase 1 AgentEngine (Task 17)

Riferimenti: checklist §6 in
`docs/superpowers/specs/2026-07-17-agent-engine-fase1-design.md`.

Suite del motore: `backend/tests/agent/` (114 test dopo questo task; 105 prima).
9 test nuovi aggiunti in questo task per colmare buchi genuini identificati
sotto (elenco a fine documento).

---

## Tabella 1 — Checklist §6 → test del motore nuovo

### 6.1 API OpenAI

**1. Una tool response per OGNI `tool_call_id`, in OGNI ramo terminale**
(success, timeout, eccezione, rejected/forbidden/scope-denied, deduped,
client-executed, argomenti non parsabili, tool senza nome).

| Ramo | Test |
|---|---|
| success | `test_engine_tools.py::test_every_call_id_gets_a_tool_result_across_branches` |
| timeout (per-tool) | `test_adapter_execution.py::test_execute_timeout_returns_ok_false_with_timeout_message` *(nuovo — vedi §6.13)* |
| eccezione | `test_engine_tools.py::test_tool_exception_yields_error_result_not_crash` *(nuovo)* |
| rejected (confirm) | `test_engine_tools.py::test_rejection_still_persists_tool_response` |
| forbidden/scope-denied (DENY) | `test_engine_tools.py::test_every_call_id_gets_a_tool_result_across_branches` (call `c_deny`) |
| deduped | `test_engine_tools.py::test_duplicate_call_yields_synthetic_result_not_execution` |
| client-executed | `test_engine_tools.py::test_client_executed_tool_routes_through_interaction_port` *(nuovo)* |
| argomenti non parsabili | `test_engine_tools.py::test_every_call_id_gets_a_tool_result_across_branches` (call `c_bad`) + `test_models.py::test_normalize_preserves_existing_id_and_bad_json` |
| tool senza nome | `test_models.py::test_normalize_missing_name_yields_parse_error` — normalizza sempre a `parse_error` ("tool call senza nome"), quindi ricade nello stesso ramo sintetico di "argomenti non parsabili" in `engine.py::_gate_call` (nessun branch separato nel motore: verificato leggendo `models.py::normalize_tool_invocations`, riga `if not name: parse_error = "tool call senza nome"`) |

Verdetto: **COPERTO, 2 test aggiunti** (timeout, eccezione, client-executed
non avevano copertura diretta).

**2. Assistant message con `tool_calls` persistito PRIMA dei tool result;
ID normalizzati upfront e coerenti tra assistant e tool message.**

| Test |
|---|
| `test_engine_tools.py::test_assistant_step_persisted_before_results_and_checkpointed` (ordine: assistant è `persistence.order[0]`) |
| `test_adapter_db.py::test_assistant_and_tool_rows_share_call_id` (riga reale DB: stesso `call_id` su riga assistant e riga tool) |
| `test_models.py::test_normalize_assigns_missing_call_ids` + `test_normalize_preserves_existing_id_and_bad_json` (normalizzazione ID upfront, una sola volta) |

Verdetto: **COPERTO**.

**3. History ricostruita (DB ordinato per `created_at`, esclusi
`context_excluded`) preserva l'ordine e non orfana mai tool response dopo
compaction.**

| Parte | Test |
|---|---|
| Ordine `created_at` | `test_adapter_db.py::test_load_history_preserves_created_at_order` *(nuovo — inserimento fuori ordine, verifica riordino)* |
| Esclusione `context_excluded` | `test_adapter_db.py::test_archive_compacted_excludes_from_history` |
| Mai orfana un tool response dopo compaction | **COPERTO ALTROVE**: la scelta del confine di archiviazione (`split_index`) che evita di spezzare una coppia assistant/tool è logica di `backend/services/context_manager.py::ContextManager.compress` (servizio di piattaforma, consumato dal motore SOLO via `ContextPort.compact()` — `services/agent/adapters/context.py`). Il motore/adapter applica fedelmente gli ID che il servizio gli restituisce (`archive_compacted`), non decide il confine. Nessun test di piattaforma verifica oggi esplicitamente "mai un tool_call_id orfano" in `backend/tests/test_context.py`: è un debito PIATTAFORMA pre-esistente, non introdotto né colmabile da questo task (fuori da `services/agent`). Segnalato nel report come nota per il team piattaforma. |

Verdetto: **COPERTO (2/3 parti dirette, 1 COPERTO ALTROVE con nota di debito
pre-esistente)**, 1 test aggiunto.

---

### 6.2 Cancel / disconnect / recovery

**4. Persist-prima-di-cancel: il check di cancel avviene DOPO la
persistenza dei tool result (mai `tool_calls` orfani nel DB).**

| Test |
|---|
| `test_engine_tools.py::test_cancel_checked_only_after_persistence` |

Verdetto: **COPERTO**.

**5. Disconnect ≠ cancel ≠ timeout nei round-trip di interazione, con
precedenza disconnect > cancel > timeout; su disconnect il contenuto
parziale è recuperato (recovery message in `ws.py`, fuori dal motore).**

| Parte | Test |
|---|---|
| Precedenza (disconnect > cancel > timeout) | `test_adapter_ws.py::test_disconnect_during_request_raises_engine_disconnected`, `test_confirm_tool_timeout_and_cancel_outcomes`, `test_confirm_tool_disconnect_returns_disconnected_as_data` — insieme, i tre test fissano la mappatura deterministica implementata in `adapters/ws.py::WsTransport.request`/`_interrupted_output` (disconnect solleva sempre per prima; a parità di `None`, `cancel.is_set()` è controllato prima di dichiarare timeout) |
| Recupero contenuto parziale su disconnect | **COPERTO ALTROVE**: `backend/api/routes/chat/ws.py` (route WS, kernel — non `services/agent`), per design invariato tra v1/v2 (la logica di recovery non dipende dal motore). Test legacy: `backend/tests/test_direct_executor_disconnect.py` (comportamento del canale, non del motore) |

Verdetto: **COPERTO (precedenza), COPERTO ALTROVE (recovery, per design fuori
scope motore)**.

**6. Un solo lettore del socket (read-pump unico); il lato send non
solleva mai su socket chiuso; cancel via frame `cancel` con reset
per-turno.**

| Test |
|---|
| `test_adapter_ws.py::test_single_reader_and_cancel_dispatch` |
| `test_adapter_ws.py::test_send_after_close_never_raises` |
| `test_adapter_ws.py::test_cancel_does_not_leak_across_turns` |
| `test_adapter_ws.py::test_event_port_never_raises_after_disconnect` |

Verdetto: **COPERTO**.

---

### 6.3 Gate e autonomia nei guardrail

**7. OGNI tool call passa da scope + permission mode + permission rules +
audit; `plan` è read-only; `auto_edits` approva solo scritture in-scope; le
conferme hanno timeout e l'esito è auditato. Nessun percorso privilegiato:
headless, subagent, voice passano dagli stessi gate.**

| Parte | Test |
|---|---|
| Ogni call passa dal gate (mode + tool_def risolti per-call) | `test_adapter_permission.py::test_mode_and_tool_def_resolved_on_every_call` |
| Mapping verdict piattaforma → azione motore | `test_adapter_permission.py::test_gate_action_mapping` (ALLOW/DENY/NEEDS_CONFIRMATION) |
| Audit su conferma approvata | `test_engine_tools.py::test_confirmation_flow_events_and_audit` |
| Audit su DENY (nessun round-trip, `interaction=None`) | `test_engine_tools.py::test_deny_verdict_is_audited` *(nuovo)* |
| Timeout di conferma | `test_adapter_ws.py::test_confirm_tool_timeout_and_cancel_outcomes` |
| Policy `plan`/`auto_edits` (read-only / solo scritture in-scope) | **COPERTO ALTROVE**: `backend/services/permission_service.py` + `permission_mode_policy.py` (servizi di piattaforma, non ridisegnati dal motore — spec §1: "PermissionService... non sono legacy del motore, sono la piattaforma"). Il motore consuma solo il `GateVerdict` risultante via `PermissionPort.decide()`, testato in `test_adapter_permission.py`. Test di piattaforma pre-esistenti (non nel perimetro `services.turn`, quindi non nella Tabella 2) |
| Nessun percorso privilegiato per source (headless/subagent/voice) | **Verificato strutturalmente**: `engine.py::_gate_call` non legge mai `state.request.source` — l'unico uso di `request.source` in tutto `engine.py` è la riga 197 (`TurnStartedEvent.source`, solo telemetria). Non esiste alcun branch `if source == ...` nel percorso di gating: è impossibile per costruzione avere un ramo privilegiato. Evidenza indiretta: `test_runner_integration.py::test_headless_turn_runs_on_v2_engine` esegue un turno headless passando dallo STESSO `AgentEngine`/`_gate_call` di un turno chat. Il subagent v2 non esiste ancora in Fase 1 (§10 non-obiettivi: arriva in Fase 5) — non c'è nulla da testare qui per il subagent finché non esiste un adapter dedicato. |

Verdetto: **COPERTO** (gate/audit/timeout diretti nel motore; policy
tier-specifica COPERTO ALTROVE per pillar §1; no-privilegio verificato per
costruzione del codice). 1 test aggiunto.

**8. Dedup cross-step delle tool call identiche (hash normalizzato
Windows-safe); il deduped produce comunque la sua tool response.**

| Test |
|---|
| `test_dedup.py` (4 test: prima/seconda occorrenza, args distinti, path Windows `\` vs `/`, key order irrilevante) |
| `test_engine_tools.py::test_duplicate_call_yields_synthetic_result_not_execution` |

Verdetto: **COPERTO**.

**9. Il mode provider è interrogato per-call (cambio modalità mid-turn
rispettato).**

| Test |
|---|
| `test_adapter_permission.py::test_mode_and_tool_def_resolved_on_every_call` (`mode_service.get_mode.call_count == 2` per 2 `decide()`) |

Verdetto: **COPERTO**.

---

### 6.4 Semantica di piattaforma

**10. Version groups e `version_index` invariati (assegnati fuori dal
motore).**

| Test |
|---|
| `test_adapter_db.py::test_version_group_and_index_applied_to_assistant_message` *(nuovo — verifica che l'adapter applichi invariati `version_group_id`/`version_index` ricevuti dal chiamante alla riga `Message` assistant)* |

Verdetto: **COPERTO**, 1 test aggiunto (prima nessun test usava un valore
non-`None`).

**11. Artifact registry: i tool result registrano artifact/immagini come
oggi (risoluzione bare tool name inclusa); le immagini persistite su
disco.**

| Parte | Test |
|---|---|
| Ordine (checkpoint prima della registrazione artifact) | `test_engine_tools.py::test_artifact_registered_after_checkpoint_of_the_batch` |
| Adapter delega ad `ArtifactRegistry` coi parametri giusti (`tool_call_id`, `message_id` risolto, `payload`) | `test_adapter_db.py::test_register_artifacts_delegates_to_registry_with_call_id` *(nuovo)* |
| Risoluzione bare tool name / parsing payload / persistenza immagini su disco | **COPERTO ALTROVE**: `backend/services/artifacts/registry.py::ArtifactRegistry.register_from_tool_result` + `parse_tool_payload` (servizio di piattaforma, esplicitamente citato in spec §1 come non-legacy-del-motore). Non ha test dedicati in `services.turn` (non compare in Tabella 2) — è testato a livello di piattaforma indipendentemente da questa fase. |

Verdetto: **COPERTO (ordine + delega dall'adapter)**, 1 test aggiunto;
parsing/persistenza immagini COPERTO ALTROVE per pillar.

**12. Compaction: trigger su soglia, summary persistito, messaggi
archiviati `context_excluded=True`, eventi `context.*` emessi.**

| Test |
|---|
| `test_engine_compaction.py::test_compaction_triggers_between_steps_and_rewrites_history` (trigger, eventi `started`/`done`, summary iniettato nel prossimo step) |
| `test_engine_compaction.py::test_context_usage_emitted_each_extra_step` |
| `test_engine_compaction.py::test_compaction_failure_is_fail_open` + `test_compaction_raise_is_fail_open` (fail-open, evento `failed`) |
| `test_adapter_db.py::test_archive_compacted_excludes_from_history` (`context_excluded=True` reale su DB + summary inserito) |

Verdetto: **COPERTO**.

**13. Step budget (`max_tool_iterations`), timeout per-tool, budget voice
(`agent.voice.max_tools`), costo accumulato per turno stampato in
`turn.finished`.**

| Parte | Test |
|---|---|
| Step budget | `test_engine_loop.py::test_max_steps_stops_loop_with_warning` |
| Timeout per-tool | `test_adapter_execution.py::test_execute_timeout_returns_ok_false_with_timeout_message` *(nuovo)* |
| Budget voice (trim `max_tool_calls`) | `test_engine_loop.py::test_voice_trim_caps_tool_calls` |
| Wiring `agent.voice.max_tools` → `max_tool_calls` | **COPERTO ALTROVE**: `backend/api/routes/chat/ws.py` (righe ~211-217, assembly layer del WS, non `services/agent`) — il motore riceve `max_tool_calls` già risolto in `TurnRequest`, non legge la config. Non è un test `services.turn`, quindi fuori Tabella 2; nessun test dedicato individuato per questa riga di wiring specifica — nota per il team piattaforma/WS. |
| Costo accumulato in `turn.finished` | `test_engine_loop.py::test_cost_and_usage_accumulate_across_steps` |

Verdetto: **COPERTO (3/4 dirette nel motore)**, 1 test aggiunto (timeout);
wiring config→campo COPERTO ALTROVE con nota di gap di piattaforma.

**14. Turni headless: sink iniettabile con `is_connected=True` (contratto
eval harness), interaction channel che auto-declina.**

| Test |
|---|
| `test_runner_integration.py::test_headless_turn_runs_on_v2_engine` (integrazione end-to-end: `run_headless_turn` → `AgentEngine` via v2, eventi `turn.llm_step`/`turn.finished` sul sink) |
| `test_runner_integration.py::test_auto_decline_interaction_port_declines_all` *(nuovo — unit: `confirm_tool` → REJECTED, `run_client_tool`/`ask_user` → `ok=False`, mai un'eccezione)* |
| `test_runner_integration.py::test_sink_event_port_noop_when_sink_disconnected` *(nuovo — unit: `SinkEventPort.emit` rispetta `sink.is_connected`)* |

Verdetto: **COPERTO**, 2 test aggiunti (prima solo integrazione, nessun unit
diretto sulle due classi di `runner.py`).

---

### 6.5 Disciplina SQLite

**15. Il write-lock impone commit boundaries prima dell'esecuzione
parallela dei tool e dopo ogni batch di persistenza: policy dichiarata di
`adapters/db.py` (unit-of-work).**

| Test |
|---|
| `test_adapter_db.py::test_checkpoint_commits_and_survives_rollback` (commit SOLO a `checkpoint()`: righe salvate prima sopravvivono a un `rollback()` successivo, righe salvate dopo un `rollback()` pre-checkpoint spariscono) |
| `test_engine_tools.py::test_assistant_step_persisted_before_results_and_checkpointed` (checkpoint dopo assistant, PRIMA del batch parallelo — `checkpoints >= 2`) |
| `test_engine_tools.py::test_artifact_registered_after_checkpoint_of_the_batch` (checkpoint dopo il batch di tool result, PRIMA della registrazione artifact) |

Verdetto: **COPERTO**.

---

## Riepilogo Tabella 1

| Voce | Verdetto |
|---|---|
| 1 | COPERTO (2 test aggiunti: timeout, eccezione, client-executed) |
| 2 | COPERTO |
| 3 | COPERTO (2/3 dirette, 1 COPERTO ALTROVE — debito piattaforma pre-esistente); 1 test aggiunto |
| 4 | COPERTO |
| 5 | COPERTO (precedenza) + COPERTO ALTROVE (recovery, per design) |
| 6 | COPERTO |
| 7 | COPERTO + COPERTO ALTROVE (policy tier) + verifica strutturale (no privilegio); 1 test aggiunto |
| 8 | COPERTO |
| 9 | COPERTO |
| 10 | COPERTO; 1 test aggiunto |
| 11 | COPERTO (parte motore) + COPERTO ALTROVE (parsing/immagini); 1 test aggiunto |
| 12 | COPERTO |
| 13 | COPERTO (3/4) + COPERTO ALTROVE (wiring config); 1 test aggiunto |
| 14 | COPERTO; 2 test aggiunti |
| 15 | COPERTO |

**15/15 invarianti hanno almeno un test diretto nel motore nuovo.**
4 invarianti (3, 5, 7, 11, 13 — 5 in realtà) hanno anche una parte
esplicitamente COPERTO ALTROVE, per pillar (servizi di piattaforma
consumati via porte, mai reimplementati/ritestati nel motore). 9 test
nuovi aggiunti in totale.

---

## Tabella 2 — Test legacy → destino

`grep -rl "services.turn" backend/tests --include="*.py"` (eseguito da
`backend/`) restituisce 18 file. Esclusi per istruzione esplicita del
brief: `backend/tests/agent/test_parity.py` (harness di parità sanzionato,
vive per design accanto al motore nuovo finché `services/turn/` non muore).

**Nota preliminare**: `test_parity.py` stesso — pur escluso da questa
tabella — importa `DirectTurnExecutor`/`TurnInput` da `services.turn` E i
double `MockSession`/`MockToolRegistry`/`MockWebSocket` da
`backend.tests.test_tool_loop` (riga legacy, vedi sotto). Quando
`test_tool_loop.py` verrà rimosso in Task 19, questi double andranno
estratti/duplicati in un modulo indipendente per non spezzare l'harness di
parità — azione da includere nel piano di demolizione.

| File legacy | Destino |
|---|---|
| `tests/test_ask_user_multi.py` | `test_multi_question_payload_and_answer_formatting` → `test_adapter_ws.py::test_ask_user_roundtrip_timeout_and_frame_shape` (stessa forma di payload/frame, risposte multi-domanda). `test_no_questions_fails_gracefully` → DECADE: caso limite del canale legacy (ask_user senza domande) non riprodotto nella nuova suite; la robustezza generale ("mai solleva") resta comunque garantita da tutta `test_adapter_ws.py`. |
| `tests/test_confirmation_toggle.py` | Il flusso di conferma/audit/rifiuto → `test_engine_tools.py::test_confirmation_flow_events_and_audit`, `test_rejection_still_persists_tool_response`, `test_deny_verdict_is_audited`; il mapping verdict → `test_adapter_permission.py::test_gate_action_mapping`. Le policy tier-specifiche (`strict`/`autopilot`/toggle globale confirmations) sono logica `PermissionService`/`PermissionModeService` di piattaforma (spec §1) → DECADE come test del *motore*: restano (e vanno preservati) come test di piattaforma, fuori dal perimetro `services/agent`. |
| `tests/test_direct_executor_cancel.py` | `test_cancel_set_before_execute_returns_cancelled` → `test_engine_single_step.py::test_cancel_before_step_stops_clean`. `test_cancel_set_during_stream_short_circuits` → `test_engine_tools.py::test_cancel_checked_only_after_persistence` (stesso invariante: cancel osservato durante l'esecuzione non interrompe prima della persistenza). |
| `tests/test_direct_executor_disconnect.py` | Disconnect durante un round-trip di interazione → `test_adapter_ws.py::test_disconnect_during_request_raises_engine_disconnected`, `test_confirm_tool_disconnect_returns_disconnected_as_data`. `test_closed_websocket_runtime_error_is_detected` → `test_adapter_ws.py::test_send_after_close_never_raises`. `test_disconnect_during_stream_returns_disconnected` / `test_sink_disconnect_mid_stream_returns_disconnected` → DECADE per design: nel motore nuovo `LLMPort` è disaccoppiato dal trasporto WS (nessuna nozione di socket dentro `stream_step`); un disconnect si manifesta solo al prossimo punto di interazione o al prossimo controllo di `cancel`/`EventPort`, mai come eccezione a metà stream testuale — comportamento architetturalmente diverso, non una lacuna. `test_llm_error_during_stream_emits_error_event` / `test_llm_streaming_error_event_marks_finish_error` → `test_engine_single_step.py::test_non_retryable_failure_is_error`. |
| `tests/test_direct_executor_streaming.py` | Mapping chunk→evento (token/thinking/tool_call/usage/done) → `test_adapter_llm.py` (intero file) + `test_engine_single_step.py::test_happy_path_stream_to_finished`. `finish_reason length` → `test_stop.py::test_length_and_completed`. `test_stream_was_compressed_forces_user_content_none` / `test_stream_default_passes_user_content_through` → DECADE: dettaglio di costruzione dei messaggi in ingresso allo stream, gestito dall'assembly layer (`_assembly.py`) prima che il motore riceva `working_messages` già pronti — non è responsabilità di `LLMPort`. |
| `tests/test_direct_executor_tool_loop.py` | `test_tool_calls_delegate_to_run_tool_loop` / `test_tool_loop_cancel_overrides_finish_reason` → `test_engine_tools.py` (intero file) + `test_stop.py` (precedenza cancel). `test_tool_calls_with_recording_sink_short_circuit_to_error` → DECADE: dettaglio implementativo del sink legacy (`RecordingEventSink` short-circuit), non un invariante comportamentale — il motore nuovo non ha un concetto equivalente di "short-circuit del sink". |
| `tests/test_headless_turn.py` | `test_run_headless_turn_persists_a_normal_turn` → `test_runner_integration.py::test_headless_turn_runs_on_v2_engine`. `test_headless_channel_satisfies_protocol` / `test_null_sink_satisfies_protocol_and_drops` → `test_runner_integration.py::test_auto_decline_interaction_port_declines_all` + `test_sink_event_port_noop_when_sink_disconnected` (stesso invariante di conformità/comportamento, riformulato sulle classi nuove `AutoDeclineInteractionPort`/`SinkEventPort`). `test_headless_channel_request_returns_none` → coperto dalla stessa coppia di test (nessuna UI da servire → esito sintetico, mai un round-trip reale). |
| `tests/test_interaction_channel.py` | Mapping quasi 1:1 sul trasporto nuovo: request/correlation/timeout/cancel/stale/disconnect/client_tool/unknown-kind → `test_adapter_ws.py` (intero file: `test_request_roundtrip_with_correlation`, `test_stale_response_is_discarded`, `test_timeout_returns_none_cancel_returns_none`, `test_cancel_frame_resolves_pending_request_to_none`, `test_disconnect_during_request_raises_engine_disconnected`, `test_run_client_tool_roundtrip_and_disconnect_raises`, ecc.). `test_scripted_*` (double scriptato del canale legacy) → DECADE: il motore nuovo ha il proprio double (`ScriptedInteractionPort` in `doubles.py`, testato da `test_doubles.py`), non riusa quello legacy per pillar. |
| `tests/test_permission_liveness.py` | `test_mode_change_takes_effect_on_next_call` → `test_adapter_permission.py::test_mode_and_tool_def_resolved_on_every_call` (stesso invariante §6.9: mode interrogato per-call, non cachato per-turno). |
| `tests/test_pipeline.py` | File più grande, mapping per gruppo: `TestDedup` → `test_dedup.py` + `test_engine_tools.py::test_duplicate_call_yields_synthetic_result_not_execution`. `TestPermission` → `test_adapter_permission.py` + `test_engine_tools.py` (rami DENY/audit). `TestConfirmation` → `test_engine_tools.py::test_confirmation_flow_events_and_audit`/`test_rejection_still_persists_tool_response` + `test_adapter_ws.py` (timeout/cancel/disconnect di conferma). `TestInteraction`/`TestAskUser*` (client tool, ask_user round-trip) → `test_adapter_ws.py::test_run_client_tool_roundtrip_and_disconnect_raises` + `test_ask_user_roundtrip_timeout_and_frame_shape` + `test_engine_tools.py::test_client_executed_tool_routes_through_interaction_port`. `TestExecute` → `test_adapter_execution.py`. `TestPipelineOrdering` (ordine dei middleware del gate) → DECADE: l'astrazione "pipeline di middleware" (`pipeline.py`) muore col design — il motore nuovo ha un flusso lineare (`engine.py::_gate_call`/`_run_tool_step`), non componibile a middleware; l'ordine delle fasi è fissato nel codice e coperto indirettamente da tutta `test_engine_tools.py`, non da un test di "ordinamento" dedicato (non esiste più l'astrazione da ordinare). |
| `tests/test_reflective_executor.py` | DECADE INTEGRALE: la reflection è eliminata per decisione esplicita (spec §2, tabella decisioni — feature off-by-default rimossa; l'anti-degenerazione strutturale arriva in Fase 3 dentro il motore, non come wrapper esterno). Nessun equivalente nel motore nuovo, per design. |
| `tests/test_tool_loop.py` | Il cuore del loop legacy, mapping per gruppo: `TestMaxIterations` → `test_engine_loop.py::test_max_steps_stops_loop_with_warning`. `TestParallelExecution` → `test_engine_tools.py::test_parallel_execution_of_greenlit_batch`. `TestDeduplication` → `test_dedup.py` + `test_engine_tools.py`. `TestErrorRecovery` → `test_engine_tools.py::test_tool_exception_yields_error_result_not_crash` + `test_adapter_execution.py::test_execute_timeout_returns_ok_false_with_timeout_message`. `TestTransientErrorRetry` → `test_retry.py` + `test_adapter_llm.py` (4xx non-retryable, 5xx retryable). `TestCancellation` → `test_engine_tools.py::test_cancel_checked_only_after_persistence`. `TestConfirmation` → `test_engine_tools.py` (confirm/reject). `TestClientExecutedTools` → `test_engine_tools.py::test_client_executed_tool_routes_through_interaction_port` + `test_adapter_ws.py::test_run_client_tool_roundtrip_and_disconnect_raises`. `TestEmptyResponseRetry` → `test_engine_single_step.py::test_empty_response_retried_with_nudge` + `test_retry.py`. Nota: questo file è anche la fonte dei double `MockSession`/`MockToolRegistry`/`MockWebSocket` importati da `test_parity.py` per pilotare v1 — vedi nota preliminare sopra. |
| `tests/test_turn_cost.py` | Accumulo costo/usage per turno → `test_engine_loop.py::test_cost_and_usage_accumulate_across_steps` + `test_parity.py` (cost in `turn.finished` confrontato v1/v2). `test_message_model_has_usage_column` / `test_usage_round_trips_through_db_and_sums` → DECADE come test del *motore*: lo schema `Message.usage` è piattaforma (`db/models.py`), non ridisegnato da questa fase — resta verificato dai test di piattaforma esistenti (fuori demolizione). |
| `tests/test_turn_events.py` | Vocabolario/forma dei frame → `test_events.py` (vocabolario interno, union esaustiva, frozen) + `test_parity.py` (mapping wire completo, `validate_chat_server` su ogni frame, round-trip JSON implicito nella validazione Pydantic). |
| `tests/test_turn_factory.py` | DECADE INTEGRALE: la factory legacy (selezione `DirectTurnExecutor`/`ReflectiveTurnExecutor`) muore con `services/turn/factory.py`. La selezione motore v1/v2 è oggi governata dal flag `agent.engine`, esercitata da `test_runner_integration.py` (fixture `v2_app` con `ALICE_AGENT__ENGINE=v2`) — non c'è più una "reflective" da selezionare (reflection eliminata, §2). |
| `tests/test_turn_lifecycle_events.py` | `test_executor_no_tool_path_emits_full_lifecycle` → `test_engine_single_step.py::test_happy_path_stream_to_finished` + `test_parity.py::test_parity_scenario_no_tools`. `test_executor_error_path_still_finishes` → `test_engine_single_step.py::test_non_retryable_failure_is_error`. `test_tool_loop_emits_llm_step_and_usage_with_minted_turn_id` → `test_parity.py::test_llm_step_one_emits_no_requery` + `test_engine_loop.py::test_cost_and_usage_accumulate_across_steps`. `test_tool_loop_steps_increase_across_iterations` → `test_engine_loop.py::test_max_steps_stops_loop_with_warning` (step budget che cresce/si esaurisce). |
| `tests/_turn_helpers.py` | Non è un file di test (nessun `def test_`/`class Test`): helper condiviso dai file legacy sopra. DECADE insieme a essi in Task 19 (nessun consumer nella suite nuova). |
| `tests/agent/test_runner_integration.py` | **Non è un file legacy** (vive in `tests/agent/`, è parte della suite del motore v2). L'unico import da `services.turn` è `backend.services.turn.sink.RecordingEventSink`, usato come shim locale per raccogliere gli eventi del turno headless nel test stesso (non il motore legacy). **AZIONE per Task 19**: prima di demolire `services/turn/sink.py`, sostituire questo import con un double locale equivalente (stesso contratto `send`/`is_connected`, es. spostato in `doubles.py`) — il file resta, ma la dipendenza da un modulo in demolizione va recisa. |

### Riepilogo Tabella 2

- 18 file trovati dal grep; 1 escluso per istruzione (`test_parity.py`).
- Dei 17 restanti: **16 sono legacy puri** con destino assegnato (mappato o
  DECADE); **1** (`test_runner_integration.py`) è un file della suite nuova
  con un'azione di scollegamento da eseguire prima della demolizione (non
  un "destino" nel senso della domanda, ma un prerequisito).
- Distribuzione destini tra i 16 file legacy: 2 file DECADE integrale
  (`test_reflective_executor.py`, `test_turn_factory.py`); gli altri 14
  hanno mapping misto (alcuni test → equivalente nel motore nuovo, alcuni
  → DECADE puntuale con motivazione) o mapping quasi totale (es.
  `test_interaction_channel.py`, `test_ask_user_multi.py`).
- Azione aggiuntiva per Task 19 identificata: i double
  `MockSession`/`MockToolRegistry`/`MockWebSocket` usati da `test_parity.py`
  vivono oggi in `tests/test_tool_loop.py` (che decade) — vanno estratti
  prima della rimozione.

---

## Test nuovi aggiunti in questo task (9 totali)

1. `test_adapter_execution.py::test_execute_timeout_returns_ok_false_with_timeout_message` — §6.1 (ramo timeout), §6.13 (timeout per-tool).
2. `test_engine_tools.py::test_tool_exception_yields_error_result_not_crash` — §6.1 (ramo eccezione).
3. `test_engine_tools.py::test_client_executed_tool_routes_through_interaction_port` — §6.1 (ramo client-executed).
4. `test_engine_tools.py::test_deny_verdict_is_audited` — §6.7 (audit su DENY).
5. `test_adapter_db.py::test_load_history_preserves_created_at_order` — §6.3 (ordine history).
6. `test_adapter_db.py::test_version_group_and_index_applied_to_assistant_message` — §6.10.
7. `test_adapter_db.py::test_register_artifacts_delegates_to_registry_with_call_id` — §6.11.
8. `test_runner_integration.py::test_auto_decline_interaction_port_declines_all` — §6.14 (unit).
9. `test_runner_integration.py::test_sink_event_port_noop_when_sink_disconnected` — §6.14 (unit).

Modifiche di supporto (non test): `_engine_helpers.py` estesi con i
parametri `errors` (eccezione ExecutionPort) e `client_result`
(InteractionPort client-executed) per costruire gli scenari sopra
riusando l'infrastruttura esistente, senza duplicarla.
