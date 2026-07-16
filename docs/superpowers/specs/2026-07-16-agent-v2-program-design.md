# Agent v2 — parità Claude Code — Design di programma

**Data:** 2026-07-16
**Stato:** approvato dall'utente (conversazione di brainstorming); ogni fase avrà spec e piano propri
**Scope:** programma multi-fase su backend + frontend (Horizon); `continuum/` e i server Trellis restano fuori
**Predecessori:** agent-rework (Fasi 0-6, merged), risanamento architetturale (8 fasi, merged), Fondamenta Jarvis (fase 8 risanamento)

---

## 1. Contesto e problema

L'agente attuale è "agentico di prima generazione": un percorso unico (`DirectTurnExecutor` →
`run_tool_loop`) con budget di step, dedup, pipeline middleware per i permessi, compattazione
per-iterazione; meta-tool `update_tasks` / `write_plan` / `spawn_subagent` / `ask_user`; scope +
quattro tier di permessi; reflection opzionale; Command Bridge; fondamenta Jarvis.

Il riferimento dichiarato dall'utente è **Claude Code**: il divario è su tutti gli assi, non su
uno solo —

1. **Affidabilità sui task lunghi** — l'agente si perde, chiude troppo presto, non verifica il
   proprio lavoro.
2. **Primitive mancanti** — niente subagent specializzati/paralleli/in background, niente skills,
   niente hooks, niente checkpoint/rewind, niente resume di sessione.
3. **Qualità del comportamento** — prompting debole: quando pianificare, quando esplorare, come
   usare i tool, come comunicare.
4. **Tool di base deboli** — file/ricerca/exec sotto il livello di Read/Edit/Grep/Glob/Bash.
5. **Debito strutturale nel motore** — `tool_loop.py` (~1.050 righe) mescola loop, persistenza
   DB (commit piazzati per il lock SQLite), doppia emissione frame legacy+canonici, compressione
   inline e retry: ogni evoluzione paga quel file.

## 2. Decisioni prese (brainstorming 2026-07-16)

| Decisione | Scelta |
|---|---|
| Ambizione | Olistica: tutto il gap verso Claude Code |
| Dominio | **Assistente generale potenziato** (il coding è un dominio tra tanti, non il focus) |
| Modello target | **OpenRouter top-tier come riferimento**, degradazione dignitosa sui locali |
| UI | **Al passo del backend**: ogni primitiva consegna la sua superficie Horizon |
| Primitive extra | Tutte in scope: skills, hooks, checkpoint/rewind, sessioni/resume |
| Misura del successo | **Eval suite agentica dedicata**, gate di ogni fase |
| Struttura | Incrementale a fasi (metodo risanamento) + **riscrittura greenfield del motore in fase early** con swap e demolizione nella stessa fase |
| Qualità | Sistema professionale, senza debiti, non pigro (impegno esplicito dell'utente su ogni sezione) |

## 3. Principi normativi del programma

1. **Greenfield sul motore.** Il motore nuovo si progetta da principi primi — il riferimento è
   l'architettura di Claude Code, NON il codice attuale. Il legacy entra nel design solo come
   **checklist di invarianti comportamentali** (contratto WS congelato, invarianti API OpenAI
   — una tool response per ogni `tool_call_id` —, semantica cancel/disconnect/recovery, gate
   permessi/scope/audit, version groups, artifact registry) estratta UNA volta nella spec della
   Fase 1. Chi progetta e implementa il motore non usa `tool_loop.py` come modello di design.
2. **Un solo percorso vivo.** Il fork motore-nuovo/motore-vecchio dura una fase, dietro flag;
   swap e cancellazione del vecchio avvengono nella stessa fase. Mai due sistemi mantenuti in
   parallelo oltre quella finestra (lezione del risanamento).
3. **Primitive come servizi kernel.** Ogni primitiva nuova (subagent runtime, skills, hooks,
   checkpoint, context engine) nasce come servizio kernel con interfaccia `Protocol` su
   `AppContext`, wired nel bootstrap dichiarativo; il loop le adotta via porta, non le ingloba.
4. **Eval come gate.** Nessuna fase chiude senza il run della suite agentica: risultato ≥
   baseline della fase precedente, più i target propri della fase. La qualità si misura, non si
   stima.
5. **UI al passo.** Ogni fase consegna anche la sua superficie Horizon (il Workspace è
   superficie di prodotto).
6. **Autonomia dentro i guardrail** (invariato dal risanamento): qualunque esecuzione agentica
   — loop, subagent, hooks — passa dagli stessi gate (scope + permission mode + audit) di un
   turno normale. Nessun percorso privilegiato.
7. **Contratti generati** (invariato): frame WS nel vocabolario congelato con estensioni
   additive via `gen-contracts.ps1`; endpoint nuovi con `response_model`; mai tipi TS a mano.

## 4. Le nove fasi

Ogni fase = spec propria → piano → branch dedicato → gate verdi → eval run → merge in main.
L'ordine è motivato: il metro prima di tutto (0), il motore prima delle primitive che ci vivono
sopra (1), i tool prima del prompting che li descrive (2→3), il contesto prima dei subagent che
lo consumano (4→5), estensibilità e safety net in coda (6-8).

### Fase 0 — Eval harness + baseline
Runner di scenari agentici costruito sui turni headless (`api/routes/chat/headless.py::run_headless_turn`):
scenario = ambiente preparato (workspace sandbox, fixture) + prompt + criteri di successo
verificabili (check deterministici sul filesystem/DB/risposta + LLM-judge per i criteri
qualitativi). Tracce di turno persistite (JSONL per turno: step, tool call, token, esiti) per il
debug comportamentale. CLI per il run locale; progettato per girare anche in CI su scenari
mock-only. Chiude con la **baseline fotografata** dell'agente attuale.

### Fase 1 — Motore nuovo (greenfield)
`AgentEngine` come servizio kernel, progettato da principi primi: loop unico con scheduler dei
tool (parallelismo vero sui tool indipendenti), stop conditions strutturate (budget step/token/
tempo, degenerazione), retry/steering, porte esplicite — PersistencePort, EventPort (adapter che
emette il vocabolario WS congelato), PermissionPort, ContextPort. Dietro flag per la durata
della fase; test di parità sui frame WS e sugli invarianti della checklist; swap, demolizione di
`tool_loop.py` e del percorso legacy nella stessa fase. Eval ≥ baseline.

### Fase 2 — Fondamenta tool
I tool di base al livello di Claude Code: lettura file con line numbers/offset/limit, edit
exact-string (fallisce se non-unico), write con guardie, glob, ricerca contenuti degna di
ripgrep, exec unificato con scope e permessi (convergenza col terminal PTY esistente), shaping
dei risultati (politiche di troncamento, immagini, guidance per-tool). Tool nuovi e tool
esistenti riconciliati: una capability = una implementazione.

### Fase 3 — Prompting e comportamento
Riscrittura del prompt agentico: esplora-poi-agisci, verify-before-done, stile di comunicazione
(aggiornamenti brevi durante il lavoro, esito in testa alla risposta finale), preamboli e
guidance dei tool, quando pianificare vs quando agire. Profili per classe di modello (strong vs
local: prompt più rigido e budget più corti sui locali). Guardie anti-degenerazione nel motore.

### Fase 4 — Context engineering
Budget token esplicito per turno; compaction stile Claude Code (summary strutturato che preserva
stato del task, decisioni prese, file toccati, prossimi passi — non un riassunto generico);
pruning dei tool-result vecchi prima della compaction; working notes dell'agente (scratchpad
persistente per-conversazione).

### Fase 5 — Subagent v2
Tipi di subagent dichiarativi (explore, general-purpose, custom definibili), esecuzione
parallela (su OpenRouter) e in background (integrazione `BackgroundTaskService` + notifica al
turno successivo), output strutturati (schema JSON), budget per-tipo, timeline UI dedicata in
Horizon. Il subagent serial-bloccante attuale viene sostituito.

### Fase 6 — Skills
Pacchetti di procedura (markdown + frontmatter: nome, descrizione, trigger) caricati on-demand
nel contesto; discovery per-utente su directory dati; authoring e gestione da UI; skills che
Alice stessa può scriversi (con conferma utente). Le skill entrano nell'offerta del modello come
riferimenti leggeri, il corpo si carica solo all'invocazione.

### Fase 7 — Hooks
Motore di regole deterministiche sugli eventi del loop (pre/post tool call, fine turno, inizio
turno): condizione dichiarativa → azione (blocca, avvisa, esegue comando whitelisted). Config
persistita + UI di gestione. Gli hook girano nel codice, non nel modello: garanzie, non
preghiere.

### Fase 8 — Checkpoint/rewind + Sessioni/resume
Snapshot dei file toccati dall'agente (per turno) con rewind dalla UI; resume di un lavoro
interrotto: handoff automatico a fine turno lungo (stato task, decisioni, prossimi passi)
e ricostruzione del contesto alla ripresa.

## 5. Architettura target (a fine programma)

- Kernel agente in `backend/services/agent/` (nome definitivo in Fase 1): `AgentEngine`,
  `SubagentRuntime`, `SkillService`, `HookService`, `CheckpointService`, `ContextEngine` —
  servizi su `AppContext` dietro `Protocol` (`core/protocols.py`), wired in `core/bootstrap/`.
- Il plugin `agent` resta il punto in cui i meta-tool sono esposti al modello, ma diventa un
  adapter sottile sui servizi kernel.
- Il contratto WS resta il vocabolario congelato; le estensioni sono additive e passano da
  `gen-contracts.ps1`; il dispatcher FE (`useEventsWebSocket.ts`) resta esaustivo.
- Permission mode + scope restano l'autorità centrale (`PermissionService`,
  `PermissionModeService`, `ScopeService`); il motore li consuma via PermissionPort.
- Config sotto `agent.*` riorganizzata per fase e censita in `docs/flag-registry.md`.

## 6. Regole di ingaggio per ogni fase

1. Spec propria (brainstorming breve dove la fase ha decisioni aperte), piano subagent-driven,
   branch dedicato.
2. Gate verdi: ruff = 0 (gate CI), mypy a parità sui file toccati, `lint-imports`,
   `check-contracts.ps1` + ratchet, FE `typecheck`/`lint`/vitest.
3. Eval suite: risultato ≥ baseline corrente + target di fase; la baseline si aggiorna al merge.
4. Sottoinsiemi pytest mirati (mai la suite integrale come gate — AUD-008; mai due pytest
   concorrenti).
5. Qualità dichiarata: niente scorciatoie non dichiarate, niente debito nascosto; il debito
   deliberato si censisce nell'handoff di fase.

## 7. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Parità comportamentale del motore (Fase 1) | Checklist invarianti estratta prima del design; test di parità sui frame WS; flag breve; eval ≥ baseline |
| Costo/latenza subagent paralleli su OpenRouter | Budget e cap configurabili dal giorno uno; costo tracciato per-subagent (estende il tracking `usage.cost`) |
| Modelli locali degradano col prompt ricco | Profili per classe di modello (Fase 3); eval eseguita su entrambe le classi |
| Scope creep di fase | Ogni fase ha spec propria con non-obiettivi espliciti |
| Doppia emissione frame legacy+canonici | Decisione in spec di Fase 1: consolidare sul vocabolario canonico; se i frame legacy cadono, è un cambio di contratto deliberato con FE aggiornato in lockstep nella stessa fase |

## 8. Fuori scope del programma

- AUD-008 (hang suite pytest in zona voice) — resta un ticket indipendente.
- Continuum, Trellis, STT/TTS — invariati.
- Rework UI/UX generale (programma separato già completato su branch dedicato).

## 9. Primo passo

La Fase 0 (eval harness + baseline) parte per prima con la sua spec breve: formato scenari,
criteri, giudice, tracce. Senza il metro, nessuna fase successiva può dichiararsi riuscita.
