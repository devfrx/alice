# Agent v2 — Fase 1: Motore greenfield (AgentEngine) — Design

**Data:** 2026-07-17
**Stato:** approvato dall'utente (brainstorming 2026-07-17, sezioni approvate una a una)
**Programma:** `docs/superpowers/specs/2026-07-16-agent-v2-program-design.md` (Fase 1 di 9)
**Baseline eval di riferimento:** `docs/superpowers/evals/2026-07-17-baseline-fase0/` (23/23, 79/79)

---

## 1. Obiettivo e principio pilastro

Sostituire il motore agentico attuale (`DirectTurnExecutor` → `run_tool_loop`, 1336 righe,
firma a ~22 parametri, ritorno a tupla-5, persistenza/frame/compaction/retry intrecciati) con
un **`AgentEngine` greenfield** progettato da principi primi — riferimento architetturale:
Claude Code — come servizio kernel con porte esplicite. Swap e demolizione del percorso
legacy nella stessa fase.

**Principio pilastro (elevato dall'utente in brainstorming):** il legacy NON influenza in
nessun modo il nuovo sviluppo, né in logica né in professionalità. In pratica:

- `backend/services/agent/` non importa nulla da `backend/services/turn/` — contratto
  import-linter `agent ↛ turn` per la durata del fork.
- Il legacy entra nel design SOLO come **checklist di invarianti comportamentali** (§6).
- Nessun riuso di codice del vecchio percorso: `pipeline.py`, `channel.py`, `sink.py`,
  `tool_loop.py`, `direct_executor.py`, `reflective_executor.py`, `_reflection.py` muoiono
  tutti a fine fase. Anche i componenti "buoni" si riprogettano: se il design nuovo converge
  su soluzioni simili è convergenza sugli invarianti, non influenza.
- I **servizi di dominio della piattaforma** (PermissionService, ScopeService,
  ContextManager, artifact registry, modelli DB, LLMService) non sono "legacy del motore":
  sono la piattaforma, e si consumano esclusivamente attraverso le porte.

## 2. Decisioni prese (brainstorming 2026-07-17)

| Decisione | Scelta |
|---|---|
| Consolidamento frame WS | **Totale, in questa fase**: vocabolario canonico v2 completo, FE migrato in lockstep, frame legacy eliminati dal contratto |
| Sequenza | **Due mosse provabili**: Mossa 1 motore (wire invariato via adapter di parità throwaway), Mossa 2 wire (contratti v2 + FE, adapter eliminato) |
| Riuso dal vecchio percorso | **Zero** (principio pilastro); muore tutto `services/turn/` |
| Reflection (`agent.reflection.*`) | **Eliminata** (feature off-by-default; le guardie anti-degenerazione arrivano in Fase 3 dentro il motore). Rimozione deliberata censita |
| Flag | `agent.engine: "v1" \| "v2"`, default `v1` in sviluppo; swap a parità provata; **flag rimosso a fine fase** |
| Eval gate | 23/23 = baseline Fase 0 (suite satura: la baseline È il tetto) |

## 3. Architettura

### Package `backend/services/agent/`

- **`engine.py` — `AgentEngine`.** UN loop unificato: nessun caso speciale per il primo
  step (oggi `_stream_initial` è un percorso a sé). Ogni step: stream LLM → tool call? →
  gate → esecuzione parallela del batch greenlit → step successivo. Consuma `TurnInput`
  nuovo, restituisce `TurnResult` nuovo (modelli disegnati nel package agent; l'assembly
  layer mappa verso di essi).
- **`ports.py` — Protocol delle porte**, tutte iniettate nel costruttore:
  - `LLMPort` — uno step = uno stream tipizzato di eventi LLM (delta testo/thinking, tool
    call, usage, errore). Il motore non conosce httpx né il formato OpenAI.
  - `PermissionPort` — `decide(tool_call) → Disposition`: l'autorità resta
    PermissionService/scope/rules/mode. Il **flusso** di gate (dedup, decisione, conferma,
    esecuzione) è logica del motore, ridisegnata.
  - `InteractionPort` — round-trip verso l'umano (conferma tool, ask_user, client tool)
    con semantica timeout/cancel/disconnect distinta.
  - `EventPort` — unica uscita: eventi canonici tipizzati (modelli, non dict).
  - `PersistencePort` — messaggi assistant/tool, audit conferme, artifact/immagini, con
    **unit-of-work esplicite** (la disciplina commit del write-lock SQLite diventa policy
    dichiarata dell'adapter, non commit sparsi nel loop).
  - `ContextPort` — stima token, `should_compact`, `compact`: policy chiamata tra gli
    step.
  - `ExecutionPort` — esecuzione tool via tool registry (timeout per-tool, risultato
    tipizzato).
- **`stop.py`** — stop conditions strutturate: `StopReason` (completed, max_steps,
  budget_tokens, budget_time, cancelled, disconnected, error) + hook di degenerazione
  (vuoto in Fase 1, riempito in Fase 3).
- **`retry.py`** — policy object per retry/steering: empty-response nudge, errori
  transienti retryable vs fail-fast (HTTP status), budget di retry.
- **`events.py`** — modello interno `TurnEvent` tipizzato (superset del vocabolario wire).
- **`dedup.py`** — dedup tool call cross-step (hash normalizzato, proprietà del motore).
- **`adapters/`** — dove il mondo nuovo incontra la piattaforma:
  - `ws.py` — implementazioni WS di EventPort e InteractionPort, scritte da zero;
    l'invariante "un solo lettore del socket" viene dalla checklist (§6.2).
  - `parity.py` (SOLO Mossa 1, throwaway) — traduce gli eventi interni nel wire attuale
    (legacy + canonico) identico byte-per-byte al motore vecchio.
  - `db.py` — PersistencePort su sessione SQLModel con commit boundaries dichiarate.
  - `llm.py` — LLMPort su LLMService.
  - `permission.py`, `context.py`, `execution.py` — wrapping dei servizi di dominio.
- Wiring: stage dedicato in `core/bootstrap/`; il motore è esposto su `AppContext` dietro
  `Protocol` (`core/protocols.py`); `factory` seleziona v1/v2 dal flag fino allo swap.

### Cosa muore a fine fase

Tutto `backend/services/turn/` (tool_loop, direct_executor, pipeline, channel, sink,
events legacy-builder, reflection, factory legacy), la doppia emissione frame, il flag
`agent.engine`, la config `agent.reflection.*` (esce dal flag registry). I test di
`services/turn/` muoiono col codice: le behavior che fissano rinascono come test del
motore nuovo (mappatura esplicita nel piano — nessun buco di copertura).

## 4. Vocabolario canonico v2 (canale chat)

Envelope piatto invariato (`type` + `origin` + `correlation_id?`), modelli Pydantic in
`api/ws_schema/`. Un evento = un fatto del turno; payload completi (la UI non incrocia
stato da frame diversi). A fine Mossa 2 il canale chat parla SOLO questo:

| Evento | Sostituisce (legacy) | Payload chiave |
|---|---|---|
| `turn.started` | — | turn_id, conversation_id, source |
| `turn.delta` | `token`, `thinking` | turn_id, step, kind (`text`\|`thinking`), testo |
| `turn.llm_step` | `llm_requery` | turn_id, step (il FE resetta i buffer di streaming) |
| `tool.call` | `tool_call` raw | call_id, name, args, step |
| `tool.started` | `tool_execution_start` | call_id (solo greenlit) |
| `tool.progress` | `tool_progress` | call_id, progress |
| `tool.result` | `tool_execution_done` | call_id, disposition/status, risultato, artifact |
| `interaction.requested` | `tool_confirmation_required`, `ask_user_required`, `client_tool_call` | interaction_id, kind, payload completo (args, risk_level, description, reasoning, questions) |
| `interaction.resolved` | — (arricchito) | interaction_id, outcome |
| `context.usage` | `context_info` | token, finestra, percentuale |
| `context.compaction` | `context_compression_start/done/failed` | phase, dettagli |
| `turn.warning` | `warning` | code, message |
| `turn.error` | `error` | code, message |
| `turn.usage` | — | token in/out, cost (per step) |
| `turn.finished` | `done` | finish_reason, message_id, version info, cost totale — tutto ciò che `done` trasporta oggi |

- `turn.llm_step`, `tool.call`, `turn.usage` mantengono nome e semantica attuali:
  **l'eval harness (`backend/evals/trace.py`) funziona senza modifiche**.
- Frame client→server rinominati coerentemente nella stessa passata: le risposte alle
  interazioni convergono su `interaction.response` (kind discriminato); messaggio utente e
  `cancel` invariati.
- I frame diagnostici del reflective executor (`agent.critic_invoked`, `agent.warning`)
  escono dal contratto (la feature è eliminata).
- Canale events (`/api/events/ws`): NON coinvolto, nessun cambio.

## 5. Migrazione frontend (Mossa 2)

- **Una sola fonte di verità per il turno**: lo store `agentRun` fa il fold dell'intero
  stream canonico (timeline, tool, interazioni); `chat.ts` mantiene solo lo stato dei
  messaggi (testo streaming via `turn.delta`, finalizzazione via `turn.finished`, context
  bar via `context.*`). Chip tool, dialog di conferma e ask_user leggono dal fold
  canonico; spariscono gli handler legacy paralleli.
- `ChatHandlerMap` (esaustiva su `ChatServerMessage['type']`) migra al vocabolario v2:
  togliere/aggiungere frame senza handler = errore di compilazione.
- Tipi TS rigenerati via `gen-contracts.ps1` — mai a mano.
- Contratti congelati aggiornati nella stessa passata: `EXPECTED_CHAT_SERVER_TYPES`,
  representative frames, guard strict (`ALICE_WS_STRICT_CONTRACTS`), baseline OpenAPI.
  È il cambio di contratto deliberato previsto dal programma (§7 rischi).

## 6. Checklist di invarianti comportamentali (l'unico input dal legacy)

Estratta prima di scrivere codice; ogni voce diventa test del motore nuovo.

### 6.1 API OpenAI
1. Una tool response (`role="tool"`) per OGNI `tool_call_id`, in OGNI ramo terminale:
   success, timeout, eccezione, rejected/forbidden/scope-denied, deduped, client-executed,
   argomenti non parsabili, tool senza nome.
2. Il messaggio assistant con `tool_calls` è persistito PRIMA dei tool result; gli ID sono
   normalizzati upfront e coerenti tra assistant e tool message.
3. La history ricostruita (memoria o DB ordinato per `created_at`, esclusi i
   `context_excluded`) preserva l'ordine e non orfana mai tool response dopo compaction.

### 6.2 Cancel / disconnect / recovery
4. Persist-prima-di-cancel: il check di cancel avviene DOPO la persistenza dei tool result
   (mai `tool_calls` orfani nel DB).
5. Disconnect ≠ cancel ≠ timeout nei round-trip di interazione, con precedenza
   disconnect > cancel > timeout; su disconnect il contenuto parziale è recuperato
   (recovery message in `ws.py`, che resta fuori dal motore).
6. Un solo lettore del socket (read-pump unico); il lato send non solleva mai su socket
   chiuso; cancel via frame `cancel` con reset per-turno.

### 6.3 Gate e autonomia nei guardrail
7. OGNI tool call passa da scope + permission mode + permission rules + audit; il tier
   `plan` è read-only; `auto_edits` approva solo scritture in-scope; le conferme hanno
   timeout e l'esito è auditato. Nessun percorso privilegiato: headless (eval/trigger),
   subagent e voice passano dagli stessi gate.
8. Dedup cross-step delle tool call identiche (hash normalizzato Windows-safe); il
   deduped produce comunque la sua tool response (§6.1.1).
9. Il mode provider è interrogato per-call (cambio modalità mid-turn rispettato).

### 6.4 Semantica di piattaforma
10. Version groups e `version_index` invariati (assegnati fuori dal motore).
11. Artifact registry: i tool result registrano artifact/immagini come oggi (risoluzione
    bare tool name inclusa); le immagini persistite su disco.
12. Compaction: trigger su soglia, summary persistito, messaggi archiviati
    `context_excluded=True`, eventi `context.*` emessi.
13. Step budget (`max_tool_iterations`), timeout per-tool, budget voice
    (`agent.voice.max_tools`), costo accumulato per turno e stampato in `turn.finished`.
14. Turni headless: sink iniettabile con `is_connected=True` (contratto dell'eval harness),
    interaction channel che auto-declina.

### 6.5 Disciplina SQLite
15. Il write-lock impone commit boundaries prima dell'esecuzione parallela dei tool e dopo
    ogni batch di persistenza: nel motore nuovo è policy dichiarata di `adapters/db.py`
    (unit-of-work), ma l'obbligo resta finché il DB è SQLite a connessione condivisa.

## 7. Sequenza operativa

**Mossa 1 — motore (wire invariato).**
1. Checklist §6 trascritta in test-plan (ogni voce → test).
2. `services/agent/` costruito TDD: unit per porta/stop/retry/dedup + integrazione con
   double propri del motore (niente riuso di `ScriptedLLM` da `tests/evals/`: il principio
   pilastro vale anche per i test double).
3. `adapters/parity.py`: eventi interni → wire attuale identico.
4. Test di parità: stessi scenari scriptati → stream frame equivalente v1/v2 + invarianti.
5. Flag `agent.engine` (default `v1`); eval run con `v2`: **23/23**.
6. Swap default a `v2`; demolizione `services/turn/` + ramo v1 + reflection; eval di
   conferma.

**Mossa 2 — wire (contratti v2).**
7. Vocabolario §4 in `api/ws_schema/`, emesso dall'adapter WS definitivo;
   `adapters/parity.py` eliminato.
8. FE migrato (§5); `gen-contracts.ps1`; contratti congelati aggiornati.
9. Eval run finale (23/23), gate completi, baseline di fase committata in
   `docs/superpowers/evals/`.

Un branch unico `feat/agent-engine-fase1`; il flag non sopravvive alla fase.

## 8. Test e parità

- Suite propria del motore in `backend/tests/agent/` (unit + integrazione), scritta TDD.
- Test di parità Mossa 1: harness che esegue lo stesso scenario scriptato su v1 e v2 e
  confronta gli stream di frame (ordine, type, payload salienti) e lo stato DB finale.
- Mappatura esplicita nel piano: ogni test di `services/turn/` → test equivalente del
  motore nuovo o motivazione di decadenza (es. test della doppia emissione).
- Eval agentica come gate a ogni milestone (fine Mossa 1, fine Mossa 2): 23/23.

## 9. Gate di chiusura fase

ruff = 0; mypy a parità sui file toccati; `lint-imports` (incluso `agent ↛ turn` finché
turn esiste, poi il contratto si ritira con la demolizione); `check-contracts.ps1` +
ratchet response_model; FE `typecheck`/`lint`/vitest; eval 23/23 committata come baseline
di fase; `docs/flag-registry.md` e CLAUDE.md aggiornati; handoff di fase con debito
eventuale censito.

## 10. Non-obiettivi

- Nuove primitive: subagent v2 (Fase 5), skills (Fase 6), hooks (Fase 7).
- Prompting nuovo o profili per modello (Fase 3) — il system prompt resta invariato.
- Context engineering oltre la parità di compaction (Fase 4).
- UI Horizon nuova oltre la migrazione frame — la timeline arricchita arriva dopo.
- Migrazione DB o cambio di storage (SQLite resta).
- AUD-008 e zona voice STT/TTS.

## 11. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Parità comportamentale incompleta | Checklist §6 estratta prima del design; parity harness frame-per-frame in Mossa 1; eval gate a ogni milestone |
| Regressione UI nella migrazione FE | Mossa 2 separata e provabile; `ChatHandlerMap` esaustiva; vitest; smoke manuale su Horizon |
| Scope creep (motore + wire + FE è tanto) | Non-obiettivi §10; due mosse con gate intermedi; il piano spezza in task review-ati |
| Rimozione reflection percepita come regressione | Feature off-by-default; decisione esplicita utente; anti-degenerazione strutturale in Fase 3 |
| Riscrittura channel/pump introduce bug sottili | Invarianti §6.2 con test dedicati (stale response, cancel race, disconnect mid-round-trip) |

## 12. Docs da aggiornare in fase

- `docs/superpowers/specs/2026-07-16-agent-v2-program-design.md` — principio 1 rafforzato
  col pilastro "il legacy non influenza il nuovo" (fatto contestualmente a questa spec).
- CLAUDE.md — sezione motore (turn executor → AgentEngine).
- `docs/flag-registry.md` — `agent.engine` (temporaneo), rimozione `agent.reflection.*`.
- Handoff di fase in `docs/superpowers/handoffs/`.
