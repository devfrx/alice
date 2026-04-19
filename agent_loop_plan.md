# Agent Loop v2 â€” Integrazione alla radice via `TurnExecutor`

> **Versione 2** del piano. Sostituisce v1 (closure-based, "agent come wrapper").
>
> **Tesi**: l'agent loop non Ã¨ un wrapper sopra il flusso esistente, Ã¨ una
> **strategia di esecuzione** intercambiabile. Per ottenere questo serve
> riconoscere che `ws_chat` oggi accumula 3 responsabilitÃ  mescolate (protocollo
> WS, persistenza, esecuzione del turno LLM) ed estrarre la terza in un servizio
> con interfaccia chiara: `TurnExecutor`.
>
> **Vincolo cardine**: zero regressioni. Tutto il comportamento attuale
> (streaming, tool loop, confirmation, compression per-iterazione, image
> persistence, artifact registry, file sync, cancel, recovery on disconnect,
> dedup tool calls, rejected tool audit, version_group, image messages,
> tool_call_id contract con OpenAI API) deve essere bit-equivalente quando
> l'agent Ã¨ disabilitato, e funzionalmente preservato quando Ã¨ abilitato.

---

## 1. Inventario di ciÃ² che `run_tool_loop` fa oggi (e che NON va rotto)

Letto da [_tool_loop.py](backend/api/routes/_tool_loop.py). Lista esaustiva:

| # | Comportamento | Punto di rischio |
|---|--------------|------------------|
| 1 | Normalizza `tc.id` a `call_<uuid>` se mancante | Contratto OpenAI |
| 2 | Persiste `Message(role="assistant", tool_calls=[...])` per ogni iter | Schema DB |
| 3 | Mantiene `mem_history` in-memory (skip DB re-fetch) | Performance |
| 4 | Dedup tool calls via `_dedup_hash` (sopravvive tra iter) | Protezione loop infiniti |
| 5 | Parsing JSON args con fallback a "tool error" come `role=tool` msg | OpenAI API richiede tool response per ogni tc_id |
| 6 | Risk level `forbidden` â†’ blocco + audit | Sicurezza |
| 7 | `requires_confirmation` â†’ WS request â†’ wait â†’ audit | UX critica |
| 8 | Esecuzione tool **in parallelo** con timeout `tool_execution_timeout` | Performance |
| 9 | Su timeout: cancel + persiste tool msg "timeout" + WS event | Resilienza |
| 10 | Su exception: persiste tool msg "failed" + WS event | Resilienza |
| 11 | Image content (`content_type=image/*`) â†’ `_persist_tool_image` su disco + placeholder DB | Multimodale |
| 12 | Artifact registry: estrae `raw_content` per non perdere paths sanitizzati | Integrazione CAD/3D |
| 13 | Per-iter compression: `should_compress(usage)` â†’ `compress` â†’ archive `Message.context_excluded=True` + summary `is_context_summary=True` | Context window |
| 14 | Per-iter sync conversazione su file via `sync_fn` | Persistence layer |
| 15 | Re-query con retry su empty response (`_EMPTY_REQUERY_RETRIES`) + nudge user msg non persistente | Local LLM quirks |
| 16 | Cancel event check tra iter, dopo persistence (DB consistente) | UX cancel |
| 17 | WS events: `tool_execution_start`, `tool_execution_done`, `llm_requery`, `context_compression_*`, `context_info`, `warning` | Frontend contract |
| 18 | Ritorna `(content, thinking, in_tokens, out_tokens, finish_reason)` | Caller dipende da quello |
| 19 | `version_group_id` / `version_index` su tutti i messaggi | Branching/regen |
| 20 | Commit espliciti per rilasciare lock SQLite prima di `artifact_registry` | DB concurrency |

**Conseguenza**: qualsiasi astrazione che pretenda di "rimpiazzare" o "wrappare"
questo loop senza preservare 1:1 questi 20 punti rompe qualcosa. La strategia
v2 Ã¨ **NON sostituire** `run_tool_loop`, ma promuoverlo a *implementazione di
default* di un'interfaccia `TurnExecutor`.

---

## 2. Architettura v2: tre livelli netti

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ LAYER 1 â€” WS Protocol (ws_chat in chat.py)                  â”‚
â”‚   - handshake, rate limit, auth, message routing            â”‚
â”‚   - cancel event creation, disconnect recovery              â”‚
â”‚   - DELEGA al TurnExecutor; NON sa cosa c'Ã¨ dentro          â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                         â”‚
                         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ LAYER 2 â€” TurnExecutor (interfaccia)                        â”‚
â”‚   async def execute(turn_input) -> TurnResult:              â”‚
â”‚                                                             â”‚
â”‚   Implementazioni:                                          â”‚
â”‚   â”œâ”€ DirectTurnExecutor   (= comportamento attuale)         â”‚
â”‚   â””â”€ AgentTurnExecutor    (plan/critic, USA Direct dentro)  â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                         â”‚
                         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ LAYER 3 â€” Persistence & Side Effects (delegati o iniettati) â”‚
â”‚   - Message persistence (assistant + tool + summary)        â”‚
â”‚   - File sync                                               â”‚
â”‚   - Artifact registry                                       â”‚
â”‚   - Tool execution (registry + confirmations + audit)       â”‚
â”‚   - Context compression                                     â”‚
â”‚                                                             â”‚
â”‚   Esposti al TurnExecutor via:                              â”‚
â”‚   - AppContext (servizi singoli, giÃ  esistente)             â”‚
â”‚   - WSEventSink (emette WS events, iniettato)               â”‚
â”‚   - PersistenceGateway (scrive Message, gestisce versioning)â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

Punti chiave:
- `ws_chat` smette di sapere come si esegue un turno. Crea un `TurnExecutor`
  (basato su config), gli passa l'input, riceve `TurnResult`, e fa la
  persistence finale + sync + WS done.
- Le persistence intermedie (assistant msg con tool_calls, tool msgs, summary)
  restano dentro l'executor che le produce. **Non spostiamo tutto** alla call
  site: rovinerebbe la semantica transazionale dei tool e la coerenza WS.
- `WSEventSink` astrae `websocket.send_json`. In test si sostituisce con un
  `RecordingSink`. In voice mode/HTTP futuro si puÃ² swappare senza toccare gli
  executor.

---

## 3. Componenti nuovi (interfacce)

### 3.1 `TurnInput` â€” DTO immutabile di ingresso

```python
@dataclass(frozen=True, slots=True)
class TurnInput:
    """Tutto ciÃ² che serve per eseguire un turno LLM. Immutabile."""
    conv_id: uuid.UUID
    user_msg_id: uuid.UUID
    user_content: str
    history: list[dict[str, Any]]           # giÃ  normalizzata, no system
    messages: list[dict[str, Any]]          # full prompt: system+memory+history
    tools: list[dict[str, Any]] | None
    memory_context: str | None
    cached_sys_prompt: str | None
    attachment_info: list[dict[str, str]] | None
    context_window: int
    version_group_id: uuid.UUID | None
    version_index: int
    client_ip: str
    resolved_max_tokens: int | None
    # --- FIX #2: stato compressione pre-gen ---
    was_compressed: bool = False            # se True, la pre-gen compression Ã¨ avvenuta
    compressed_history: list[dict[str, Any]] | None = None
    # Quando was_compressed=True:
    #   - _stream_initial usa user_content=None (forza path OAI-compat)
    #   - run_tool_loop riceve compressed_history come initial_history
    #     (invece di history crudo, evitando ri-compressione)
    tool_tokens: int = 0                    # token delle tool definitions (per breakdown)
```

### 3.2 `TurnResult` â€” DTO immutabile di uscita

```python
@dataclass(frozen=True, slots=True)
class TurnResult:
    """Esito del turno. Persistenza intermedia giÃ  fatta dall'executor."""
    content: str                            # final assistant content
    thinking: str
    input_tokens: int
    output_tokens: int
    finish_reason: str                      # stop|cancelled|error|length
    # Side-effect metadata (per WS done event):
    final_assistant_message_id: uuid.UUID | None
    # --- FIX #4: contenuto parziale per disconnect recovery ---
    # Quando l'executor propaga WebSocketDisconnect, il contenuto
    # parziale va recuperato. Soluzione: l'executor NON propaga
    # direttamente; cattura WebSocketDisconnect internamente e
    # ritorna un TurnResult con finish_reason="disconnected".
    # ws_chat controlla finish_reason=="disconnected" e fa recovery.
    had_tool_calls: bool = False            # per decidere se salvare msg finale
    # Agent-only metadata (None per Direct):
    agent_run_id: uuid.UUID | None = None
```

### 3.3 `WSEventSink` â€” sink di eventi WS

```python
class WSEventSink(Protocol):
    async def send(self, event: dict[str, Any]) -> None: ...
    @property
    def is_connected(self) -> bool: ...

class WebSocketEventSink(WSEventSink):
    """Default impl che inoltra a fastapi.WebSocket."""
    def __init__(self, ws: WebSocket): ...
```

In test: `RecordingEventSink` che accumula in lista. Nessun mock di WebSocket.

### 3.4 `TurnExecutor` â€” interfaccia

```python
class TurnExecutor(Protocol):
    async def execute(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        session: AsyncSession,
    ) -> TurnResult: ...
```

### 3.5 `DirectTurnExecutor` â€” implementazione di default

Wrappa il comportamento attuale **senza modifiche di logica**:

```python
class DirectTurnExecutor:
    """Esegue un turno con il comportamento legacy: stream + run_tool_loop.

    Preserva 1:1 i 20 punti del comportamento attuale.
    """
    def __init__(self, ctx: AppContext, llm: LLMService): ...

    async def execute(self, turn, sink, cancel_event, session) -> TurnResult:
        # 1. Stream iniziale (era _stream_and_collect)
        # FIX #2: se turn.was_compressed â†’ user_content=None (forza OAI-compat)
        effective_user_content = None if turn.was_compressed else turn.user_content
        full_content, thinking, tool_calls, finish_reason, in_tok, out_tok = \
            await self._stream_initial(
                turn, sink, cancel_event,
                effective_user_content=effective_user_content,
            )

        if cancel_event.is_set():
            return TurnResult(content=full_content, thinking=thinking,
                              input_tokens=in_tok, output_tokens=out_tok,
                              finish_reason="cancelled",
                              final_assistant_message_id=None)

        # 2. Tool loop (delegato all'esistente run_tool_loop)
        had_tools = False
        if tool_calls and finish_reason not in ("cancelled", "error"):
            had_tools = True
            try:
                # FIX #2: usa compressed_history se disponibile
                effective_history = (
                    turn.compressed_history
                    if turn.was_compressed and turn.compressed_history
                    else turn.history
                )
                full_content, thinking, in_tok2, out_tok2, loop_finish = \
                    await run_tool_loop(
                        websocket=sink._ws,                # escape hatch fase 1
                        ctx=self.ctx, session=session, conv_id=turn.conv_id,
                        llm=self.llm,
                        tool_calls_from_llm=tool_calls,
                        full_content=full_content,
                        thinking_content=thinking,
                        max_iterations=self.ctx.config.llm.max_tool_iterations,
                        confirmation_timeout_s=self.ctx.config.pc_automation.confirmation_timeout_s,
                        client_ip=turn.client_ip,
                        sync_fn=_sync_conversation_to_file,
                        cancel_event=cancel_event,
                        memory_context=turn.memory_context,
                        tools=turn.tools,
                        initial_history=effective_history,
                        system_prompt=turn.cached_sys_prompt,
                        version_group_id=turn.version_group_id,
                        version_index=turn.version_index,
                        context_window=turn.context_window,
                    )
                if in_tok2 > 0:
                    in_tok, out_tok = in_tok2, out_tok2
                finish_reason = loop_finish
            except WebSocketDisconnect:
                # FIX #4: NON propagare. Ritornare result con "disconnected"
                # cosÃ¬ ws_chat puÃ² fare recovery con il contenuto parziale.
                return TurnResult(
                    content=full_content, thinking=thinking,
                    input_tokens=in_tok, output_tokens=out_tok,
                    finish_reason="disconnected",
                    final_assistant_message_id=None,
                    had_tool_calls=True,
                )

        return TurnResult(
            content=full_content, thinking=thinking,
            input_tokens=in_tok, output_tokens=out_tok,
            finish_reason=finish_reason,
            final_assistant_message_id=None,  # persistence finale fa ws_chat
            had_tool_calls=had_tools,
        )
```

> **Nota**: `WSEventSink` ha un escape hatch interno per ottenere il
> `WebSocket` raw. Necessario perchÃ© `run_tool_loop` lo richiede oggi.
> Quando refattorizzeremo `run_tool_loop` per usare il sink direttamente,
> l'hatch sparirÃ . Per la fase 1 Ã¨ la concessione minima per **non
> toccare** `run_tool_loop`.
>
> **FIX #3 â€” Cancel task mechanism**: `_listen_for_cancel` resta in `ws_chat`
> e **non** riceve `stream_task`. Invece, `DirectTurnExecutor._stream_initial`
> Ã¨ implementato come task interno all'executor che **controlla `cancel_event`
> ogni chunk**. Quando `cancel_event` viene settato da `_listen_for_cancel`,
> `_stream_initial` esce dal loop `async for event in llm.chat(...)` nel giro
> di un chunk (~1ms). Se il modello Ã¨ lento (reasoning, nessun chunk ancora),
> il task del caller (`ws_chat`) puÃ² fare `asyncio.wait` con timeout e poi
> `executor_task.cancel()`. Ecco il pattern in `ws_chat`:
>
> ```python
> executor_task = asyncio.create_task(
>     executor.execute(turn, sink, cancel_event, session)
> )
> cancel_task = asyncio.create_task(
>     _listen_for_cancel(cancel_event, executor_task, message_buffer)
> )
> try:
>     result = await executor_task
> except asyncio.CancelledError:
>     cancel_event.set()
>     result = TurnResult(
>         content="", thinking="", input_tokens=0, output_tokens=0,
>         finish_reason="cancelled", final_assistant_message_id=None,
>     )
> finally:
>     cancel_task.cancel()
> ```
>
> `_listen_for_cancel` ora riceve `executor_task` (il task dell'executor, non
> lo stream task interno) e fa `executor_task.cancel()` su cancel/disconnect.
> Questo interrompe anche `httpx.stream()` bloccato. **Stessa semantica di oggi.**

### 3.6 `AgentTurnExecutor` â€” strategia agent

```python
class AgentTurnExecutor:
    """Plan â†’ Act â†’ Critic loop. Internamente usa DirectTurnExecutor.

    Esegue ogni step come un mini-turno LLM con prompt arricchito.
    NON persiste un Message per step (sarebbe rumoroso). Persiste:
      - 1 sola assistant Message finale (concatenazione step outputs)
      - tool messages emergono naturalmente dal DirectTurnExecutor degli step
      - 1 AgentRun row con plan + stato
    """
    def __init__(
        self,
        direct: DirectTurnExecutor,
        classifier: ClassifierService,
        planner: PlannerService,
        critic: CriticService,
        cfg: AgentConfig,
    ): ...

    async def execute(self, turn, sink, cancel_event, session) -> TurnResult:
        # 1. Classifier (con cache LRU per session)
        complexity = await self.classifier.classify(
            turn.user_content, has_tools=bool(turn.tools), cancel_event=cancel_event,
        )

        # 2. Bypass paths: trivial / open_ended / no tools / classifier disabled
        if complexity in (TRIVIAL, OPEN_ENDED) or not turn.tools:
            return await self.direct.execute(turn, sink, cancel_event, session)

        # 3. Persiste AgentRun
        run = AgentRun(conversation_id=turn.conv_id, ...)
        session.add(run); await session.flush()
        await sink.send({"type": "agent.run_started", ...})

        # 4. SINGLE_TOOL: skip planner/critic, ma traccia in AgentRun
        if complexity == SINGLE_TOOL:
            result = await self.direct.execute(turn, sink, cancel_event, session)
            run.state = "done"; run.finished_at = _utcnow(); await session.flush()
            return result.with_run_id(run.id)

        # 5. PLAN
        plan = await self.planner.plan(...)
        run.plan_json = plan.model_dump_json(); ...; await session.flush()
        await sink.send({"type": "agent.plan_created", ...})

        # 6. EXECUTE LOOP
        accumulated_content = ""
        accumulated_thinking = ""
        agg_in = agg_out = 0
        retries: dict[int, int] = {}
        i = 0
        while i < len(plan.steps):
            if cancel_event.is_set():
                run.state = "cancelled"; break

            step = plan.steps[i]
            await sink.send({"type": "agent.step_started", "step": step.model_dump(),
                             "step_index": i, "total_steps": len(plan.steps)})

            # Sub-turn: stesso turn, ma messages arricchito da step prompt + storia accumulata
            sub_turn = self._build_sub_turn(turn, step, accumulated_content, i)

            # Direct esegue il singolo step (incluso eventuale tool loop)
            sub_result = await self.direct.execute(sub_turn, sink, cancel_event, session)

            accumulated_content += ("\n\n" if accumulated_content else "") + sub_result.content
            accumulated_thinking += sub_result.thinking
            agg_in += sub_result.input_tokens
            agg_out += sub_result.output_tokens

            # Critic
            verdict = await self.critic.evaluate(step, sub_result.content, ...)
            await sink.send({"type": "agent.step_completed", "step_index": i,
                             "verdict": verdict.model_dump()})

            match verdict.action:
                case OK:        i += 1
                case RETRY if retries.get(i, 0) < self.cfg.max_retries_per_step:
                    retries[i] = retries.get(i, 0) + 1
                    # non avanzare i
                case RETRY:     i += 1   # esauriti i retry, prosegui
                case REPLAN if run.replans < self.cfg.max_replans:
                    new_plan = await self.planner.plan(remaining_goal=...)
                    plan.steps = plan.steps[:i+1] + new_plan.steps
                    run.replans += 1
                    await sink.send({"type": "agent.replanned", ...})
                    i += 1
                case ASK_USER:
                    run.state = "asked_user"; break
                case ABORT:
                    run.state = "failed"; run.error = verdict.reason; break

        run.state = "done" if run.state == "running" else run.state
        run.finished_at = _utcnow(); ...; await session.flush()
        await sink.send({"type": "agent.run_finished", "run_id": str(run.id), "state": run.state})

        return TurnResult(
            content=accumulated_content, thinking=accumulated_thinking,
            input_tokens=agg_in, output_tokens=agg_out,
            finish_reason="stop" if run.state == "done" else run.state,
            final_assistant_message_id=None, agent_run_id=run.id,
        )
```

### 3.7 `TurnExecutorFactory`

```python
def create_turn_executor(ctx: AppContext, llm: LLMService) -> TurnExecutor:
    direct = DirectTurnExecutor(ctx, llm)
    if not ctx.config.agent.enabled or ctx.agent_orchestrator_components is None:
        return direct
    return AgentTurnExecutor(direct=direct, **ctx.agent_orchestrator_components)
```

### 3.8 Affrontare le 5 incoerenze della v1 + 7 incoerenze della v2 bozza

**Incoerenze v1 (confermate risolte):**

| Incoerenza v1 | Risoluzione v2 |
|---------------|----------------|
| **a) closure con side-effect impliciti** | Eliminata: `TurnExecutor` ha contratto esplicito (input â†’ result), persistenza intermedia gestita dentro l'executor (Ã¨ la sua responsabilitÃ ) |
| **b) timeout vs attesa utente** | `cancel_event.wait()` per confirmation Ã¨ OUTSIDE il timeout dell'agent. `AgentConfig.total_timeout_seconds` esclude tempo speso in `tool_execution_start` â†’ `tool_execution_done` con `requires_confirmation=true`. Implementazione: clock pause/resume tracker dentro `AgentTurnExecutor`. |
| **c) streaming token-by-token con N step** | Ogni step emette eventi token regolari (frontend li vede streaming). Aggiungiamo metadata `step_index` agli eventi token quando dentro AgentTurnExecutor. Il bubble assistente Ã¨ UNO solo, lo step boundary Ã¨ marcato da `agent.step_completed`. Il frontend puÃ² scegliere di renderizzare separatori soft. |
| **d) compression dentro al loop** | GiÃ  gestita da `run_tool_loop` per-iterazione (punto #13). `AgentTurnExecutor` chiama `direct.execute` per ogni step, e `direct.execute` invoca `run_tool_loop` che giÃ  comprime. **Funziona by composition**. |
| **e) AgentRun vs Message audit trail** | `AgentRun.plan_json` Ã¨ l'audit trail completo del piano. I tool messages dei singoli step sono persistiti normalmente da `run_tool_loop` (utente vede cosa Ã¨ stato fatto). L'unica omissione: NON persistiamo un `Message` separato per step intermedio (verrebbero N bubble assistente). UX nel frontend: il bubble assistente principale ha un dettaglio collapsable "vedi piano" (rendering di `AgentRun.plan_json`). |

**Incoerenze v2 bozza (scoperte nella review, ora risolte):**

| # | Incoerenza | Risoluzione | Dove nel piano |
|---|-----------|-------------|----------------|
| **1** | **Post-stream compression assente** â€” dopo il commit del msg finale, `ws_chat` oggi controlla `finish_reason=="length"` O `real_pct >= threshold`, ri-legge tutti i msg, comprime, archivia, salva summary, manda WS events, aggiorna `context_snapshot`. ~100 righe di codice che non erano mappate nel piano. | Questo blocco resta in `ws_chat`, dentro `_persist_final_turn`. NON Ã¨ responsabilitÃ  dell'executor (avviene DOPO che il turno Ã¨ completato e il Message Ã¨ committato). La funzione `_persist_final_turn` include: persist msg â†’ commit â†’ post-stream compression check â†’ WS done. Vedi sezione 4.1 aggiornata. | §4.1 |
| **2** | **`was_compressed` non in `TurnInput`** â€” se la pre-gen compression Ã¨ avvenuta, `_stream_and_collect` forza `user_content=None` (path OAI-compat, no native API). Inoltre `initial_history` passato a `run_tool_loop` deve essere la versione compressa. `TurnInput` non portava questa info. | Aggiunto `was_compressed: bool`, `compressed_history: list | None`, `tool_tokens: int` a `TurnInput`. `DirectTurnExecutor` controlla `turn.was_compressed` per scegliere il path e la history. | §3.1, §3.5 |
| **3** | **`stream_task.cancel()` non gestito** â€” `_listen_for_cancel` oggi cancella il `stream_task` per interrompere `httpx.stream()` bloccato. Il piano v2 bozza non dava accesso al task interno dell'executor. | `ws_chat` wrappa `executor.execute()` in un `asyncio.create_task()`. `_listen_for_cancel` riceve questo task e lo cancella su cancel/disconnect. `executor.execute` riceve `CancelledError` e esce. Stessa semantica di oggi. | §3.5 nota |
| **4** | **`WebSocketDisconnect` mid-tool-loop** â€” oggi `ws_chat` cattura `WebSocketDisconnect` e salva il `full_content` parziale come recovery. Con il pattern executor, il contenuto Ã¨ dentro l'executor e un'eccezione non lo ritorna. | `DirectTurnExecutor` cattura `WebSocketDisconnect` internamente e ritorna `TurnResult(finish_reason="disconnected")` col contenuto parziale. `ws_chat` controlla `finish_reason=="disconnected"` â†’ salva recovery msg â†’ raise per uscire dal WS loop. | §3.5 |
| **5** | **`context_snapshot` su Conversation** â€” dopo il save, `ws_chat` scrive `conv.context_snapshot = {prompt_tokens, completion_tokens, context_window}` per l'estimazione anchor+delta al turno successivo. Non era mappato. | Gestito in `_persist_final_turn`: se `result.input_tokens > 0`, persiste snapshot sulla `Conversation`. | §4.1 |
| **6** | **`context_info` reale post-persist** â€” se ci sono token reali, `ws_chat` invia un secondo `context_info` event con dati reali + breakdown. Non era mappato. | Gestito in `_persist_final_turn`: calcola `get_usage_real()` e invia `context_info` via sink prima del `done` event. | §4.1 |
| **7** | **`token_count` sul Message finale** â€” `asst_msg.token_count = last_input_tokens`. Non era catturato. | Gestito in `_persist_final_turn`: setta `asst_msg.token_count = result.input_tokens` prima del commit. | §4.1 |

---

## 4. Modifiche al codice esistente

### 4.1 `chat.py::ws_chat` â€” refactor strutturale

Lo scope del refactor: **estrarre l'esecuzione del turno** da `ws_chat`. Il
risultato Ã¨ una funzione `ws_chat` molto piÃ¹ corta e leggibile.

**Diff logico** (non riga per riga):

```python
# PRIMA (semplificato):
async def ws_chat(websocket):
    # ... boilerplate WS, rate limit, ack ...
    while True:
        # ... receive message, build user_msg, fetch history ...
        # ... memory retrieval, system prompt, compression pre-gen ...

        full_content = ""; thinking_content = ""
        tool_calls_collected = []; finish_reason = "stop"
        cancel_event = asyncio.Event()

        async def _stream_and_collect(): ...    # ~80 righe
        async def _listen_for_cancel(...): ...  # ~30 righe

        stream_task = asyncio.create_task(_stream_and_collect())
        cancel_task = asyncio.create_task(_listen_for_cancel(stream_task, ...))
        try: await stream_task
        except: ...

        if tool_calls_collected:
            (full_content, thinking, ...) = await run_tool_loop(...)

        # ... persist final assistant Message, sync file, send done ...
        # ... post-stream compression check, context_info reale, token_count ...

# DOPO:
async def ws_chat(websocket):
    # ... boilerplate WS, rate limit, ack ... (INVARIATO)
    sink = WebSocketEventSink(websocket)
    executor = create_turn_executor(ctx, llm)

    while True:
        # ... receive message, build user_msg, fetch history ... (INVARIATO)
        # ... memory retrieval, system prompt, compression pre-gen ... (INVARIATO)

        cancel_event = asyncio.Event()

        # FIX #2: TurnInput porta was_compressed + compressed_history
        turn = TurnInput(
            conv_id=conv_id, user_msg_id=user_msg.id,
            ...,
            was_compressed=comp is not None,
            compressed_history=(
                [m for m in comp.messages if m.get("role") != "system"]
                if comp is not None else None
            ),
            tool_tokens=_tool_tokens,
        )

        # FIX #3: executor.execute wrappato in task per cancel
        executor_task = asyncio.create_task(
            executor.execute(turn, sink, cancel_event, session)
        )
        cancel_task = asyncio.create_task(
            _listen_for_cancel(cancel_event, executor_task, message_buffer)
        )

        try:
            result = await executor_task
        except asyncio.CancelledError:
            # FIX #3: cancel ha interrotto l'executor
            cancel_event.set()
            # Salva contenuto parziale se c'Ã¨ (non accessibile â†’ msg vuoto)
            result = TurnResult(
                content="", thinking="", input_tokens=0, output_tokens=0,
                finish_reason="cancelled", final_assistant_message_id=None,
            )
        except Exception:
            logger.exception(...); await sink.send({"type": "error", ...})
            await session.rollback(); continue
        finally:
            cancel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_task

        # FIX #4: disconnect recovery
        if result.finish_reason == "disconnected":
            if result.content:
                recovery_msg = Message(
                    conversation_id=conv_id, role="assistant",
                    content=result.content,
                    thinking_content=result.thinking or None,
                    version_group_id=user_msg.version_group_id,
                    version_index=user_msg.version_index,
                )
                session.add(recovery_msg)
                conv.updated_at = _utcnow()
                await session.commit()
                if ctx.conversation_file_manager:
                    await _sync_conversation_to_file(...)
            raise WebSocketDisconnect()  # propaga per uscire dal WS loop

        # Persist + post-processing (FIX #1, #5, #6, #7 tutti qui)
        await _persist_final_turn(
            session, conv, conv_id, user_msg, result, sink,
            ctx=ctx, llm=llm,
            was_compressed=turn.was_compressed,
            context_window=turn.context_window,
            tool_tokens=turn.tool_tokens,
            messages=turn.messages,        # per breakdown
            av_map=av_map,                 # per post-compression archival
        )
```

### 4.1.1 `_persist_final_turn` â€” helper estratto (NUOVO)

Questa funzione contiene TUTTA la logica post-turno che oggi Ã¨ inline in
`ws_chat` (righe ~1527-1845). **Non Ã¨ semplificata, Ã¨ solo spostata**:

```python
async def _persist_final_turn(
    session, conv, conv_id, user_msg, result: TurnResult, sink: WSEventSink,
    *, ctx, llm, was_compressed, context_window, tool_tokens, messages, av_map,
) -> None:
    """Persiste il messaggio finale e gestisce post-stream compression.

    Contiene 1:1 la logica che oggi Ã¨ inline in ws_chat dopo il tool loop:
    - Salva assistant Message (se ha contenuto)
    - FIX #7: setta asst_msg.token_count = result.input_tokens
    - FIX #6: invia context_info reale (get_usage_real) se token disponibili
    - Aggiorna conv.updated_at, conv.title
    - FIX #5: persiste conv.context_snapshot
    - Commit
    - Sync file
    - FIX #1: post-stream compression (se finish_reason=="length" O
      real_pct >= threshold)
    - Invia WS "done" event
    """
    asst_msg_id = ""
    asst_msg = None

    # Salva msg solo se c'Ã¨ contenuto (quando had_tool_calls, gli intermedi
    # sono giÃ  persistiti da run_tool_loop)
    if result.content.strip() or not result.had_tool_calls:
        asst_msg = Message(
            conversation_id=conv_id, role="assistant",
            content=result.content,
            thinking_content=result.thinking or None,
            version_group_id=user_msg.version_group_id,
            version_index=user_msg.version_index,
        )
        session.add(asst_msg)
        asst_msg_id = str(asst_msg.id)

    # FIX #6: context_info reale
    if (
        result.input_tokens > 0
        and ctx.context_manager
        and context_window > 0
    ):
        real_usage = ctx.context_manager.get_usage_real(
            result.input_tokens, context_window,
        )
        await sink.send({
            "type": "context_info",
            "used": real_usage.used_tokens,
            "available": real_usage.available_tokens,
            "context_window": context_window,
            "percentage": real_usage.percentage,
            "was_compressed": was_compressed,
            "messages_summarized": 0,  # solo pre-gen, qui non rilevante
            "is_estimated": False,
            "breakdown": _compute_context_breakdown(
                messages, tool_tokens, ctx.context_manager,
            ),
        })
        # FIX #7: token_count sul Message
        if asst_msg is not None:
            asst_msg.token_count = result.input_tokens
            session.add(asst_msg)
            await session.flush()

    # Update conversation metadata
    conv.updated_at = _utcnow()
    if conv.title is None and user_msg.content:
        conv.title = user_msg.content[:100]

    # FIX #5: context_snapshot per anchor+delta
    if result.input_tokens > 0 and context_window > 0:
        conv.context_snapshot = {
            "prompt_tokens": result.input_tokens,
            "completion_tokens": result.output_tokens,
            "context_window": context_window,
        }

    await session.commit()

    # Sync to file
    if ctx.conversation_file_manager:
        await _sync_conversation_to_file(
            session, conv_id, ctx.conversation_file_manager,
        )

    # FIX #1: POST-STREAM COMPRESSION
    # Due trigger: finish_reason=="length" OPPURE real_pct >= threshold
    post_compress = result.finish_reason == "length"
    if (
        not post_compress
        and result.input_tokens > 0
        and result.output_tokens > 0
        and context_window > 0
    ):
        total_tokens = result.input_tokens + result.output_tokens
        real_pct = total_tokens / context_window
        if real_pct >= ctx.config.llm.context_compression_threshold:
            post_compress = True

    if (
        post_compress
        and ctx.config.llm.context_compression_enabled
        and ctx.context_manager is not None
        and context_window > 0
    ):
        try:
            await sink.send({"type": "context_compression_start"})
            # Ri-legge messaggi dal DB (include il msg appena salvato)
            post_stmt = (
                select(Message)
                .where(Message.conversation_id == conv_id)
                .order_by(Message.created_at, Message.id)
            )
            post_results = await session.exec(post_stmt)
            post_all_msgs = post_results.all()
            post_raw = [_msg_to_raw_dict(m, i) for i, m in enumerate(post_all_msgs)]
            post_hist = _filter_history_for_llm(post_raw, av_map)
            post_msgs = llm.build_continuation_messages(
                post_hist, system_prompt=cached_sys_prompt,
            )
            post_comp = await ctx.context_manager.compress(
                post_msgs, llm, context_window,
                ctx.config.llm.context_compression_reserve,
                tool_tokens=tool_tokens if tool_tokens else 0,
            )
            await _archive_messages_in_db(
                session, post_all_msgs, post_raw,
                post_comp.split_index, active_versions=av_map,
            )
            post_summary = (
                f"[Context summary of {post_comp.split_index} earlier "
                f"messages]:\n{post_comp.summary_text}"
            )
            post_sum_msg = Message(
                conversation_id=conv_id, role="assistant",
                content=post_summary, is_context_summary=True,
            )
            session.add(post_sum_msg)
            await session.commit()

            if ctx.conversation_file_manager:
                await _sync_conversation_to_file(
                    session, conv_id, ctx.conversation_file_manager,
                )

            await sink.send({
                "type": "context_compression_done",
                "messages_summarized": post_comp.usage.messages_summarized,
                "summary_message_id": str(post_sum_msg.id),
            })
            await sink.send({
                "type": "context_info",
                "used": post_comp.usage.used_tokens,
                "available": post_comp.usage.available_tokens,
                "context_window": context_window,
                "percentage": post_comp.usage.percentage,
                "was_compressed": True,
                "messages_summarized": post_comp.usage.messages_summarized,
                "is_estimated": True,
                "breakdown": _compute_context_breakdown(
                    post_comp.messages, tool_tokens, ctx.context_manager,
                ),
            })
            # Aggiorna snapshot con dati compressi
            conv.context_snapshot = {
                "prompt_tokens": post_comp.usage.used_tokens,
                "completion_tokens": 0,
                "context_window": context_window,
            }
            await session.commit()
        except Exception as exc:
            logger.warning("Post-stream compression failed: {}", exc)
            await sink.send({"type": "context_compression_failed"})

    # WS done (sempre, come ultimo evento)
    await sink.send({
        "type": "done",
        "conversation_id": str(conv_id),
        "message_id": asst_msg_id,
        "user_message_id": str(user_msg.id),
        "finish_reason": result.finish_reason,
        "version_group_id": str(user_msg.version_group_id)
        if user_msg.version_group_id else None,
        "version_index": user_msg.version_index,
    })
```

**Linee toccate stimate**: ~350 (di cui ~250 sono spostamenti, ~100 nuove).

**Garanzie di non-regressione**:
1. `_stream_and_collect` viene spostato in `DirectTurnExecutor._stream_initial`
   con firma diversa ma logica byte-identica.
2. `_listen_for_cancel` resta in `chat.py` (gestione protocollo WS, non turno).
   FIX #3: ora riceve `executor_task` e lo cancella (stessa semantica di oggi
   con `stream_task`).
3. `run_tool_loop` non viene MODIFICATO. Riceve gli stessi argomenti di prima.
4. `_persist_final_turn` contiene **tutta** la logica post-turno: save msg,
   context_info reale (FIX #6), token_count (FIX #7), context_snapshot (FIX #5),
   post-stream compression (FIX #1), WS done. **Niente Ã¨ dimenticato.**
5. FIX #4: disconnect recovery gestito PRIMA di `_persist_final_turn` tramite
   `result.finish_reason == "disconnected"` â†’ save + raise.

### 4.2 `_tool_loop.py` â€” zero modifiche in fase 1

Il file resta intoccato. `DirectTurnExecutor` lo chiama come oggi.

In una fase 5 *opzionale* si potrÃ  evolvere `run_tool_loop` per accettare un
`WSEventSink` invece di `WebSocket` raw, eliminando l'escape hatch in
`WSEventSink._ws`. Ãˆ un cleanup, non un blocker.

### 4.3 Nuovi file backend

```
backend/services/turn/
â”œâ”€â”€ __init__.py
â”œâ”€â”€ models.py                    # TurnInput, TurnResult
â”œâ”€â”€ sink.py                      # WSEventSink protocol + WebSocketEventSink + RecordingEventSink
â”œâ”€â”€ direct_executor.py           # DirectTurnExecutor (wrappa logica attuale)
â”œâ”€â”€ agent_executor.py            # AgentTurnExecutor (orchestrazione)
â””â”€â”€ factory.py                   # create_turn_executor(ctx, llm)

backend/services/agent/
â”œâ”€â”€ __init__.py
â”œâ”€â”€ models.py                    # TaskComplexity, Plan, Step, Verdict (Pydantic)
â”œâ”€â”€ prompts.py                   # System prompts IT (planner, critic, classifier)
â”œâ”€â”€ classifier.py                # ClassifierService
â”œâ”€â”€ planner.py                   # PlannerService
â””â”€â”€ critic.py                    # CriticService
```

> Nota: ho separato `services/turn/` (infrastruttura turno) da `services/agent/`
> (intelligenza agentica). `DirectTurnExecutor` non dipende da `agent/`.
> `AgentTurnExecutor` dipende da entrambi. ModularitÃ  rispettata.

### 4.4 Modifiche additive a file esistenti

| File | Modifica | Righe stimate |
|------|----------|---------------|
| `core/config.py` | + `AgentConfig` sub-model in `AliceConfig` | +60 |
| `core/protocols.py` | + `TurnExecutorProtocol`, `WSEventSinkProtocol` | +30 |
| `core/context.py` | + `agent_components: AgentComponents \| None` (planner/critic/classifier istanziati) | +5 |
| `core/app.py` | startup: se `cfg.agent.enabled` istanzia `AgentComponents` | +20 |
| `db/models.py` | + `class AgentRun(SQLModel, table=True)` | +35 |
| `api/routes/chat.py` | refactor `ws_chat` (vedi 4.1), estrazione `_persist_final_turn` | -80 / +120 |
| `config/default.yaml` | + sezione `agent:` con `enabled: false` | +25 |

**Totale codice nuovo**: ~1500-1800 righe (di cui ~600 test).
**Totale codice modificato esistente**: ~250 righe (per lo piÃ¹ spostamenti).

---

## 5. Schema DB additivo

```python
class AgentRun(SQLModel, table=True):
    """Persistence di una singola esecuzione agent loop.

    Opzionale: conversazioni senza agent NON hanno righe qui.
    Nessuna FK obbligatoria da Message â†’ AgentRun.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    conversation_id: uuid.UUID = Field(foreign_key="conversation.id", index=True)
    user_message_id: uuid.UUID = Field(foreign_key="message.id")
    final_assistant_message_id: uuid.UUID | None = Field(default=None)

    goal: str
    complexity: str                # TaskComplexity value
    plan_json: str                 # JSON serialized list[Step]
    state: str                     # planning|running|done|failed|cancelled|asked_user
    current_step: int = 0
    total_steps: int = 0
    replans: int = 0
    retries_total: int = 0

    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_tool_calls: int = 0

    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None
    error: str | None = None
```

**Migration**: nessuna alembic (la dir Ã¨ vuota oggi). Si aggiunge la classe e
`SQLModel.metadata.create_all` la crea allo startup, esattamente come per le
altre tabelle attuali.

---

## 6. Eventi WebSocket â€” additivi e namespaced

Tutti i nuovi eventi sono prefissati `agent.*`. Il frontend attuale che ha un
`switch(event.type)` con default no-op li ignora silenziosamente.

```typescript
type AgentEvent =
  | { type: "agent.run_started"; run_id: string; complexity: TaskComplexity }
  | { type: "agent.plan_created"; run_id: string; plan: Plan }
  | { type: "agent.step_started"; step_index: number; total_steps: number; step: Step }
  | { type: "agent.step_completed"; step_index: number; verdict: Verdict }
  | { type: "agent.replanned"; new_plan: Plan }
  | { type: "agent.ask_user"; question: string; run_id: string }
  | { type: "agent.run_finished"; run_id: string; state: string }
```

**Eventi token/thinking dentro un step**: durante `direct.execute` invocata
da `AgentTurnExecutor`, il `WSEventSink` puÃ² essere wrappato in un
`AnnotatingSink` che aggiunge `agent_step_index` agli eventi token/thinking/
tool_call/tool_execution_*. Frontend puÃ² ignorare il campo extra. Nessuna
breaking change.

---

## 7. Frontend â€” impatto

### Fase 1 (questa proposta): **zero impatto frontend**
- Eventi `agent.*` ignorati dal default `switch` case esistente.
- Eventi token/thinking continuano a renderizzare nel bubble assistente come oggi.
- `AgentTurnExecutor` accumula i token degli step in un'unica `result.content`,
  che diventa il `Message.content` finale â†’ identico a oggi visivamente.

### Fase 2 (opzionale, dopo validazione backend):
- `AgentPlanCard.vue` â€” checklist piano live sotto il messaggio assistente
- `useAgentRun.ts` composable â€” sub-store per `agent_run_id â†’ state`
- `chatStore.agentRuns: Map` â€” additivo
- `SettingsView` â†’ toggle `agent.enabled`
- API REST `GET /agent/runs/:conv_id` per riaprire conversazioni con run history

---

## 8. Rollout in 5 fasi

### Fase 1 â€” Estrazione `TurnExecutor` (no behavior change)
- [ ] Crea `backend/services/turn/` con `models.py`, `sink.py`,
      `direct_executor.py`, `factory.py`.
- [ ] Refactor `chat.py::ws_chat`: usa `DirectTurnExecutor` come unico path.
      Estrae `_persist_final_turn`.
- [ ] **Test**: tutti i test esistenti devono passare INVARIATI.
      Smoke test manuale: chat testo, voice, tool call, confirmation,
      cancel, compression. Comportamento bit-identico atteso.

### Fase 2 â€” Componenti agent isolati (no integration)
- [ ] `backend/services/agent/models.py` (Pydantic + Enum).
- [ ] `prompts.py` con few-shot italiano.
- [ ] `ClassifierService`, `PlannerService`, `CriticService`.
- [ ] Test unitari con mock LLM (`RecordingLLM`).
- [ ] **Test**: zero impatto su backend in esecuzione.

### Fase 3 â€” `AgentTurnExecutor` + factory + DB
- [ ] `agent_executor.py` con orchestrazione completa.
- [ ] `AgentRun` in `db/models.py`.
- [ ] `AgentConfig` in `core/config.py` con `enabled: false` default.
- [ ] `AgentComponents` istanziati in startup se `agent.enabled`.
- [ ] `factory.py` istanzia `AgentTurnExecutor` se config on, altrimenti `Direct`.
- [ ] **Test**: con `agent.enabled=false` â†’ comportamento bit-identico a fase 1.
      Con `agent.enabled=true` â†’ smoke test su query trivial/single/multi.

### Fase 4 â€” UX frontend (opzionale, non bloccante)
- [ ] WS event handler per `agent.*` in `chatStore`.
- [ ] `AgentPlanCard.vue` componente di rendering piano.
- [ ] Settings toggle in `SettingsView`.
- [ ] Endpoint REST per history runs.

### Fase 5 â€” Cleanup `run_tool_loop` (opzionale, post-stabilizzazione)
- [ ] Refactor `run_tool_loop` per accettare `WSEventSink` invece di `WebSocket`.
- [ ] Rimuove escape hatch `WSEventSink._ws`.
- [ ] **Test**: regressione completa.

> Le fasi 1-3 sono il MVP. Le 4-5 sono polish.

---

## 9. Test plan (regressione assoluta)

### Test esistenti che devono passare invariati

Tutti i test sotto `backend/tests/` senza modifiche al codice di test.

### Nuovi test fase 1 (`TurnExecutor` extraction)

- `test_direct_executor_streaming.py` â€” verifica che eventi WS prodotti da
  `DirectTurnExecutor` siano bit-identici a quelli prodotti dal vecchio
  `_stream_and_collect` (snapshot test su `RecordingEventSink`).
- `test_direct_executor_tool_loop.py` â€” invoca executor con tool_call mockato,
  verifica che chiami `run_tool_loop` con argomenti corretti e propaghi result.
- `test_direct_executor_cancel.py` â€” cancel event durante stream e durante tool
  loop â†’ ritorno con `finish_reason="cancelled"`.
- `test_direct_executor_disconnect.py` â€” `WebSocketDisconnect` durante
  esecuzione si propaga senza perdere dati.

### Nuovi test fase 2 (componenti agent)

- `test_classifier.py` â€” output deterministico su input fissi, fallback su LLM error.
- `test_planner.py` â€” JSON parsing, validazione Pydantic, fallback single-step.
- `test_critic.py` â€” verdict parsing, fallback OK su parse error.

### Nuovi test fase 3 (integration)

- `test_agent_executor_bypass.py` â€” complexity TRIVIAL/OPEN_ENDED â†’ delega a
  `DirectTurnExecutor` 1:1.
- `test_agent_executor_single_tool.py` â€” SINGLE_TOOL â†’ AgentRun creato +
  Direct chiamato + plan_json vuoto.
- `test_agent_executor_multi_step.py` â€” MULTI_STEP â†’ planner + NÃ—Direct + critic.
- `test_agent_executor_replan.py` â€” verdict REPLAN â†’ planner ri-chiamato.
- `test_agent_executor_ask_user.py` â€” verdict ASK_USER â†’ break + state="asked_user".
- `test_agent_executor_cancel_during_step.py` â€” cancel mid-step â†’ cleanup pulito.
- `test_chat_route_agent_disabled.py` â€” E2E WS con `agent.enabled=false` â†’
  comportamento identico al baseline.
- `test_chat_route_agent_enabled.py` â€” E2E WS con `agent.enabled=true` â†’
  eventi `agent.*` presenti nel sink.

### Smoke test manuale obbligatorio prima di merge

1. Chat testo semplice â†’ risposta normale
2. Chat con tool (web_search) â†’ stesso comportamento
3. Tool con confirmation (pc_automation) â†’ dialog funziona
4. Voice mode end-to-end â†’ STT â†’ LLM â†’ TTS catena intatta
5. CAD generation â†’ artifact registry funziona, side panel si apre
6. Whiteboard creation â†’ tldraw integration intatta
7. Long context (2k+ messaggi) â†’ compression scatta
8. Cancel mid-stream â†’ stop pulito
9. Cancel mid-tool â†’ stop pulito
10. Network drop mid-stream â†’ recovery message salvato
11. Branch / regenerate / version switch â†’ version_group_id intatto

Tutti questi devono passare con `agent.enabled=false` (regressione zero) e
con `agent.enabled=true` (zero impatto se classifier dice trivial).

---

## 10. Configurazione

```yaml
# config/default.yaml â€” sezione additiva
agent:
  enabled: false                  # OFF di default
  voice_mode_bypass: true         # in voice mode usa sempre DirectTurnExecutor
  max_steps: 8
  max_retries_per_step: 2
  max_replans: 2
  step_timeout_seconds: 60        # tempo MASSIMO per UN step (escluso wait utente)
  total_timeout_seconds: 240      # tempo MASSIMO per intero run (escluso wait utente)
  pause_timeout_during_confirmation: true   # clock fermo durante tool confirmation

  classifier:
    enabled: true                 # se false â†’ sempre full loop
    cache_ttl_seconds: 300
    max_output_tokens: 20
    temperature: 0.0

  planner:
    max_output_tokens: 600
    temperature: 0.2
    require_json_object: true     # response_format={"type":"json_object"}

  critic:
    max_output_tokens: 80
    temperature: 0.0
    fail_open: true               # parse error â†’ verdict OK (non blocca utente)

  persistence:
    save_runs: true
```

Override env: `ALICE_AGENT__ENABLED=true`, `ALICE_AGENT__MAX_STEPS=12`, ecc.
(Pattern giÃ  usato dal resto della config.)

---

## 11. CompatibilitÃ : matrice esplicita

| Feature attuale | Stato post-v2 | Note |
|----------------|---------------|------|
| WS `/ws/chat` protocol | Invariato | Eventi nuovi solo additivi |
| `run_tool_loop` | Invariato (fase 1-4) | Refactorato in fase 5 opzionale |
| `_persist_tool_image` | Invariato | Chiamato dentro `run_tool_loop` |
| Artifact registry | Invariato | Chiamato dentro `run_tool_loop` |
| Tool confirmation dialog | Invariato | Chiamato dentro `run_tool_loop` |
| Forbidden tool blocking | Invariato | Chiamato dentro `run_tool_loop` |
| Tool dedup | Invariato | Chiamato dentro `run_tool_loop` |
| Tool execution timeout | Invariato | Chiamato dentro `run_tool_loop` |
| Per-iter compression | Invariato | Chiamato dentro `run_tool_loop` |
| Empty re-query retry | Invariato | Chiamato dentro `run_tool_loop` |
| File sync conversazione | Invariato | `sync_fn` continua a funzionare |
| Voice mode (STTâ†’LLMâ†’TTS) | Invariato | Bypass agent forzato |
| LM Studio native API path | Invariato | Usata da `DirectTurnExecutor._stream_initial` |
| Ollama OAI-compat path | Invariato | Idem |
| Branch/regenerate | Invariato | `version_group_id` propagato |
| Memory retrieval (RAG) | Invariato | Eseguita prima di `executor.execute` |
| Pre-gen compression | Invariato | Eseguita prima di `executor.execute` |
| Cancel mid-stream | Invariato | FIX #3: `executor_task.cancel()` + `cancel_event` |
| Disconnect recovery | Invariato | FIX #4: `finish_reason="disconnected"` + recovery in ws_chat |
| Post-stream compression | Invariato | FIX #1: spostata in `_persist_final_turn` |
| `context_snapshot` persist | Invariato | FIX #5: in `_persist_final_turn` |
| `context_info` reale post-persist | Invariato | FIX #6: in `_persist_final_turn` |
| `asst_msg.token_count` | Invariato | FIX #7: in `_persist_final_turn` |
| Nativeâ†’OAI switch su compression | Invariato | FIX #2: `TurnInput.was_compressed` |
| Tool image persistence | Invariato | Dentro `run_tool_loop` |
| ToolConfirmationAudit | Invariato | Dentro `run_tool_loop` |
| `Message.context_excluded` | Invariato | Compression scrive come oggi |
| `Message.is_context_summary` | Invariato | Compression scrive come oggi |
| Plugin system | Invariato | Tool registry tocca solo `run_tool_loop` |
| MCP integration | Invariato | Stesso plugin path |
| Frontend Vue stores | Invariato | Eventi nuovi ignorati |
| Frontend `chatStore` | Invariato in fase 1, additivo in fase 4 | |

---

## 12. Cose esplicitamente fuori scope v2

- Strategia B/C (multi-modello, drafter dedicato).
- Memory consolidation / knowledge graph.
- Sub-agent specializzati con LLM diversi per ruolo.
- Resume di un AgentRun interrotto da crash backend.
- UI di "browse historical agent runs" (Ã¨ solo `GET /agent/runs/:conv_id` REST).
- Function-calling parallelo a livello di step.
- Modifica di `run_tool_loop` (rimandata a fase 5 opzionale).

---

## 13. Riepilogo: integrazione alla radice (v2 vs v1)

| Aspetto | v1 (toppa) | v2 (radice) |
|---------|-----------|-------------|
| Astrazione del turno | Closure con side-effect impliciti | Interfaccia `TurnExecutor` con DTO |
| Branching condizionale | `if ctx.agent_orchestrator` in `chat.py` | Strategia scelta in factory, una volta |
| Modifiche a `run_tool_loop` | Implicite (messages_override) | Zero modifiche |
| Refactor di `chat.py` | Estrazione 80 righe in closure | Estrazione 250 righe in helper + executor |
| TestabilitÃ  unit di componenti agent | Difficile (closure deps) | Banale (`RecordingEventSink` + mock LLM) |
| Path voice mode | Flag in orchestrator | Factory ritorna `Direct` per voice |
| EstendibilitÃ  futura (strategia B/C) | Altri if-branching | Nuovo executor + factory ramo |
| Path persistenza turno | Sparso tra closure e orchestrator | Singolo helper `_persist_final_turn` |
| Compression in loop multi-step | Non gestita esplicitamente | Composta naturalmente via `run_tool_loop` |
| Audit trail step | `Message` per step (rumoroso) o niente | `AgentRun.plan_json` + tool messages naturali |

**Costo**: +60% scope rispetto a v1 (+10% per i 7 fix).
**Beneficio**: il sistema diventa estendibile senza altri if-branching.
Coerente con le regole del workspace (modularitÃ , zero debito tecnico).

---

## 14. Audit finale pre-implementazione

### 14.1 Incoerenze v1 + v2 risolte (12/12)

| # | Origine | Incoerenza | Risolto in | Sezione |
|---|---------|-----------|-----------|----------|
| v1-a | v1 review | closure con side-effect | TurnExecutor Protocol | §3.8 |
| v1-b | v1 review | timeout vs attesa utente | clock pause/resume | §3.8 |
| v1-c | v1 review | streaming N step | step_index su token events | §3.8 |
| v1-d | v1 review | compression mid-loop | composizione naturale | §3.8 |
| v1-e | v1 review | audit trail asimmetrico | AgentRun.plan_json | §3.8 |
| v2-1 | v2 audit | post-stream compression | `_persist_final_turn` | §4.1.1 |
| v2-2 | v2 audit | was_compressed in TurnInput | campi aggiunti | §3.1, §3.5 |
| v2-3 | v2 audit | cancel task mechanism | executor_task.cancel() | §3.5 nota |
| v2-4 | v2 audit | disconnect recovery | finish_reason=disconnected | §3.2, §3.5, §4.1 |
| v2-5 | v2 audit | context_snapshot | in _persist_final_turn | §4.1.1 |
| v2-6 | v2 audit | context_info reale | in _persist_final_turn | §4.1.1 |
| v2-7 | v2 audit | token_count su Message | in _persist_final_turn | §4.1.1 |

### 14.2 Nuove incoerenze trovate nell'audit finale (5)

#### **v3-1 (CRITICO): Reader WebSocket concorrenti**

**Problema**: Il piano avvolge l'intero `executor.execute()` in un task e
lancia `_listen_for_cancel` per tutta la sua durata. Ma `run_tool_loop`
al suo interno lancia il proprio reader (`_ws_cancel_reader`) durante
ogni re-query LLM, e `_request_tool_confirmation` legge dal WebSocket
durante l'attesa di conferma utente. Due reader concorrenti sullo stesso
WebSocket = **race condition**:
- Un messaggio `tool_confirmation_response` verrebbe intercettato da
  `_listen_for_cancel` e messo in `msg_buffer`, mai raggiungendo
  `_request_tool_confirmation` -> **tool confirmation rotta**
- Un messaggio `cancel` potrebbe essere gestito da entrambi i reader

**Flusso attuale (corretto)**:
1. `_listen_for_cancel` corre SOLO durante `_stream_and_collect`
2. `finally: cancel_task.cancel()` -> listener fermato
3. `run_tool_loop` parte con i PROPRI reader interni -> nessun overlap

**Soluzione**: l'executor gestisce cancel reader internamente.
`_listen_for_cancel` viene **rimossa** da `ws_chat`:

```python
class DirectTurnExecutor:
    async def execute(self, turn, sink, cancel_event, session) -> TurnResult:
        # Fase 1: stream con reader interno (come _ws_cancel_reader)
        reader = asyncio.create_task(
            _ws_cancel_reader(sink._ws, cancel_event)
        )
        try:
            content, thinking, tool_calls, ... = await self._stream(...)
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader

        if cancel_event.is_set():
            return TurnResult(finish_reason="cancelled", ...)

        # Fase 2: tool loop — ha i propri reader interni, nessun overlap
        if tool_calls:
            content, ... = await run_tool_loop(websocket=sink._ws, ...)

        return TurnResult(...)
```

In `ws_chat`:

```python
# ws_chat (versione pulita — no _listen_for_cancel):
executor_task = asyncio.create_task(
    executor.execute(turn, sink, cancel_event, session)
)
try:
    result = await executor_task
except asyncio.CancelledError:
    result = TurnResult(finish_reason="cancelled", ...)
```

Per intercettare disconnect durante l'intera esecuzione, FastAPI cancella
automaticamente il task quando la connessione WS cade -> l'executor
riceve `CancelledError` e esce. Il `msg_buffer` per messaggi non-cancel
durante stream si sposta dentro l'executor (o si elimina — in pratica
non arrivano messaggi non-cancel durante lo stream).

---

#### **v3-2 (ALTO): Cancel dopo tool loop non gestito dall'executor**

**Problema**: `run_tool_loop` quando `cancel_event` e' settato esce dal
loop e ritorna `_loop_finish_reason` che e' il finish_reason dell'ULTIMO
call LLM (tipicamente `"stop"`), **non `"cancelled"`**. Nel codice
attuale, `ws_chat` ha un check esplicito (riga 1491):

```python
if cancel_event.is_set():
    # salva parziale, manda done(cancelled), continue
```

Il `DirectTurnExecutor` nel piano NON ha questo check dopo
`run_tool_loop`. Risultato: un turno cancellato durante il tool loop
verrebbe trattato come turno normale.

**Soluzione**: aggiungere check in `DirectTurnExecutor` dopo
`run_tool_loop`:

```python
# In DirectTurnExecutor.execute(), dopo run_tool_loop:
if cancel_event.is_set():
    return TurnResult(
        content=full_content, thinking=thinking,
        input_tokens=in_tok, output_tokens=out_tok,
        finish_reason="cancelled",
        final_assistant_message_id=None,
        had_tool_calls=True,
    )
```

---

#### **v3-3 (ALTO): `cached_sys_prompt` mancante in `_persist_final_turn`**

**Problema**: Il blocco post-stream compression in `_persist_final_turn`
chiama:

```python
post_msgs = llm.build_continuation_messages(
    post_hist, system_prompt=cached_sys_prompt,
)
```

Ma `cached_sys_prompt` **non e' tra i parametri** di `_persist_final_turn`.
La funzione produrrebbe un `NameError` a runtime.

**Soluzione**: aggiungere `cached_sys_prompt: str | None` alla firma:

```python
async def _persist_final_turn(
    session, conv, conv_id, user_msg, result: TurnResult, sink: WSEventSink,
    *, ctx, llm, was_compressed, context_window, tool_tokens,
    messages, av_map,
    cached_sys_prompt: str | None,  # <-- AGGIUNTO
) -> None:
```

---

#### **v3-4 (ALTO): `_persist_final_turn` manca fast-path per cancelled/error**

**Problema**: Nel codice attuale, i turni `cancelled` hanno un path
dedicato (righe 1490-1515) che:
- Salva contenuto parziale
- Aggiorna `conv.updated_at` e `conv.title`
- Commit + sync file
- Manda `done(cancelled)`
- **NON fa**: post-stream compression, context_info reale, context_snapshot

Il piano fa passare TUTTI i result (inclusi cancelled) attraverso
`_persist_final_turn`, che farebbe post-compression se i token superano
la soglia. Un turno cancellato con molti token (cancel dopo 3 iterazioni
tool loop) attiverebbe la compression inutilmente.

Stesso problema per `finish_reason="error"` (attualmente: rollback +
error event, nessun save).

**Soluzione**: `_persist_final_turn` deve avere early-return:

```python
async def _persist_final_turn(...) -> None:
    # --- Fast path: cancelled ---
    if result.finish_reason == "cancelled":
        if result.content.strip() or result.thinking:
            cancel_msg = Message(
                conversation_id=conv_id, role="assistant",
                content=result.content,
                thinking_content=result.thinking or None,
                version_group_id=user_msg.version_group_id,
                version_index=user_msg.version_index,
            )
            session.add(cancel_msg)
            asst_msg_id = str(cancel_msg.id)
        else:
            asst_msg_id = ""
        conv.updated_at = _utcnow()
        if conv.title is None and user_msg.content:
            conv.title = user_msg.content[:100]
        await session.commit()
        if ctx.conversation_file_manager:
            await _sync_conversation_to_file(
                session, conv_id, ctx.conversation_file_manager,
            )
        await sink.send({
            "type": "done", "conversation_id": str(conv_id),
            "message_id": asst_msg_id,
            "user_message_id": str(user_msg.id),
            "finish_reason": "cancelled",
            "version_group_id": str(user_msg.version_group_id)
            if user_msg.version_group_id else None,
            "version_index": user_msg.version_index,
        })
        return

    # --- Fast path: error ---
    if result.finish_reason == "error":
        await sink.send({
            "type": "done", "conversation_id": str(conv_id),
            "message_id": "", "user_message_id": str(user_msg.id),
            "finish_reason": "error",
            "version_group_id": str(user_msg.version_group_id)
            if user_msg.version_group_id else None,
            "version_index": user_msg.version_index,
        })
        return

    # ... path normale (save, context_info, compression, done) ...
```

---

#### **v3-5 (MEDIO): Errore LLM durante stream — dettaglio perso**

**Problema**: Nel codice attuale, un errore LLM durante lo streaming
(es. httpx 503) viene catturato e produce un messaggio specifico:

```python
except Exception as exc:
    err_detail = "LLM error"
    if hasattr(exc, "response"):
        err_detail = f"LLM returned {exc.response.status_code}"
    await websocket.send_json({"type": "error", "content": err_detail})
```

Se l'executor propaga l'eccezione, il `except Exception` generico in
`ws_chat` invierebbe un messaggio diverso.

**Soluzione**: `DirectTurnExecutor._stream_initial` cattura errori LLM
internamente, emette l'error event via `sink.send()` con il dettaglio,
e ritorna `TurnResult(finish_reason="error", content="")`. Non propaga
eccezioni LLM al caller.

```python
# In DirectTurnExecutor._stream_initial:
try:
    async for event in llm.chat(...):
        ...
except Exception as exc:
    err_detail = "LLM error"
    if hasattr(exc, "response"):
        err_detail = f"LLM returned {exc.response.status_code}"
    await sink.send({"type": "error", "content": err_detail})
    return StreamResult(finish_reason="error", ...)
```

---

### 14.3 Riepilogo stato incoerenze — audit finale

| # | Severita' | Incoerenza | Stato |
|---|---------|-----------|-------|
| v1-a..v1-e | — | 5 incoerenze v1 | Risolte |
| v2-1..v2-7 | — | 7 incoerenze v2 | Risolte |
| **v3-1** | **CRITICO** | **Reader WS concorrenti** | Risolto: executor gestisce cancel reader internamente, `_listen_for_cancel` rimossa |
| **v3-2** | **ALTO** | **Cancel post-tool-loop** | Risolto: check `cancel_event.is_set()` dopo `run_tool_loop` in executor |
| **v3-3** | **ALTO** | **`cached_sys_prompt` mancante** | Risolto: aggiunto a firma `_persist_final_turn` |
| **v3-4** | **ALTO** | **Fast-path cancelled/error** | Risolto: early-return in `_persist_final_turn` |
| **v3-5** | **MEDIO** | **Dettaglio errore LLM** | Risolto: executor cattura e emette error event internamente |

**Totale incoerenze trovate e risolte: 17/17**

### 14.4 Impatto delle 5 nuove fix sulle sezioni precedenti

| Fix | Sezione da aggiornare | Cosa cambia |
|-----|-----------------------|-------------|
| v3-1 | §3.5 (DirectTurnExecutor) | Reader cancel interno, non esterno. `_listen_for_cancel` rimossa da ws_chat. |
| v3-1 | §4.1 (ws_chat refactor) | Niente `cancel_task`. Solo `executor_task` + `try/except CancelledError`. |
| v3-2 | §3.5 (DirectTurnExecutor) | Aggiungere `if cancel_event.is_set()` dopo `run_tool_loop`. |
| v3-3 | §4.1.1 (_persist_final_turn) | Aggiungere `cached_sys_prompt` alla firma. |
| v3-4 | §4.1.1 (_persist_final_turn) | Aggiungere early-return per cancelled e error. |
| v3-5 | §3.5 (DirectTurnExecutor) | `_stream_initial` cattura eccezioni LLM e ritorna error TurnResult. |

### 14.5 Valutazione finale

**Coerenza: ~99%.** Il restante ~1% sono dettagli di firma e nomi
variabili che emergeranno al primo `mypy`/runtime e si risolvono in
secondi. Nessun problema architetturale residuo.

**Il piano e' pronto per l'implementazione.**
