# Agent v2 — Fase 0: Eval harness + baseline — Design

**Data:** 2026-07-16
**Programma:** `docs/superpowers/specs/2026-07-16-agent-v2-program-design.md` (Fase 0 di 9)
**Stato:** in review utente

---

## 1. Obiettivo

Costruire il metro con cui ogni fase del programma Agent v2 si misura: una suite di scenari
agentici ripetibili eseguiti contro l'agente reale, con esiti verificabili, tracce complete e
un report confrontabile tra run. Chiude con la **baseline fotografata** dell'agente attuale.

Non-obiettivi: nessuna superficie Horizon (è tooling per sviluppatori, CLI-only — eccezione
sancita al principio "UI al passo"); nessun run a pagamento in CI; nessuna modifica al
comportamento dell'agente (l'unico ritocco al runtime è l'iniettabilità del sink, additiva).

## 2. Decisioni

| Decisione | Scelta |
|---|---|
| Modello pinnato per i run ufficiali | **`z-ai/glm-5.2`** via OpenRouter (scelto dall'utente tra le opzioni proposte; agentic-focused, stabile, niente rate limit `:free`) |
| Giudice LLM | Stesso modello pinnato, chiamata singola per criterio qualitativo; i check deterministici restano la misura primaria |
| Scala baseline | **~20-25 scenari** sui domini chiave |
| Dove vive | `backend/evals/` (package dedicato, fuori da `tests/`) |
| Esecuzione | CLI locale: `python -m backend.evals run [--filter ...]`; subset mock-only per la CI (testa l'harness, non l'agente) |

## 3. Architettura

### 3.1 Scenario (YAML, uno per file, `backend/evals/scenarios/`)

```yaml
id: file-organize-01
title: Riordina i file per tipo
domain: filesystem          # filesystem | search | multistep | planning | permissions | recovery | knowledge
setup:
  sandbox:                  # file creati nella cartella sandbox dello scenario
    - path: "in/nota.txt"
      content: "..."
  permission_mode: auto_edits   # tier della conversazione
  config: {}                # override ALICE_* addizionali (opzionali)
prompt: "Riordina i file in in/ per tipo, creando una cartella per estensione."
budget:
  max_seconds: 180          # wall-clock cap per scenario
checks:                     # deterministici — la misura primaria
  - kind: file_exists
    path: "in/txt/nota.txt"
  - kind: tool_called
    name: "filesystem_move_file"
  - kind: response_matches
    pattern: "(?i)riordinat"
judge:                      # opzionale — misura secondaria
  criteria:
    - "Ha spiegato cosa ha fatto in modo conciso e corretto?"
```

Tipi di check (v1): `file_exists`, `file_absent`, `file_contains`, `response_matches`,
`tool_called`, `tool_not_called`, `max_steps`, `finished_ok` (finish_reason non error/cancel).
L'insieme è estendibile per fase.

### 3.2 Runner

1. Boot dell'app con lifespan `testing=True` e **data dir temporanea isolata** (mai il data dir
   reale; niente Qdrant condiviso — il knowledge non è sotto misura in Fase 0).
2. Config forzata via layer runtime/env: `llm.provider=openrouter`,
   `llm.openrouter_model=z-ai/glm-5.2` (la chiave arriva dal SecretStore/env dell'utente).
3. Per scenario: sandbox temporanea popolata dal `setup` → conversazione nuova → scope fissato
   alla sandbox → permission mode dal `setup` → turno via `run_headless_turn` con **sink di
   registrazione iniettato** (estensione additiva: parametro `sink` opzionale, default
   `NullEventSink`) → raccolta trace → check → judge → teardown.
4. Trace per scenario in JSONL (`evals_output/<run_id>/<scenario_id>.jsonl`): ogni frame del
   sink (step, tool call, risultati, usage) + `TurnResult`. Output directory **gitignored**.
5. Report aggregato (`report.json` + rendering testuale): per scenario pass/fail dei check,
   punteggio judge, step/tool/token/costo/durata; totali e confronto con un report precedente
   (`--baseline <path>`).

I run degli scenari sono **seriali** (un turno alla volta): stessi vincoli del backend reale,
nessuna contesa sul data dir.

### 3.3 Baseline e gate

- La baseline di Fase 0 è il report committato in `docs/superpowers/evals/` (file datato al
  giorno del run, es. `2026-07-18-baseline-fase0.md`: sintesi leggibile + `report.json` allegato). I run successivi confrontano contro l'ultimo
  report committato.
- Gate di fase (dalla Fase 1 in poi): percentuale check pass ≥ baseline; regressioni per-scenario
  giustificate esplicitamente nell'handoff di fase.
- Il costo del run è tracciato per scenario (il campo `usage.cost` OpenRouter esiste già).

### 3.4 Harness testato (mock-only per CI)

L'harness ha i suoi unit test con un LLM scriptato (nessuna rete): scenario fittizio → il
runner esegue, i check valutano, il report si genera. Gira nella suite pytest normale e in CI.
I run veri (`z-ai/glm-5.2`) sono solo locali e on-demand.

## 4. Domini della suite baseline (~20-25 scenari)

| Dominio | ~N | Cosa misura |
|---|---|---|
| filesystem | 4-5 | lettura/scrittura/organizzazione file nella sandbox |
| search | 3 | trovare informazioni in file/albero directory |
| multistep | 4-5 | task lunghi con dipendenze tra passi, senza perdersi |
| planning | 3 | uso sensato di update_tasks/write_plan (quando sì, quando no) |
| permissions | 3 | rispetto di plan mode/scope; niente tentativi fuori sandbox |
| recovery | 3 | tool che falliscono, argomenti errati, ripresa pulita |
| knowledge | 2 | uso della memoria/contesto conversazione |

La lista puntuale degli scenari è lavoro del piano di implementazione, non della spec.

## 5. Rischi

| Rischio | Mitigazione |
|---|---|
| Variabilità del modello tra run | Modello pinnato; check deterministici primari; il confronto tra fasi guarda il trend, non il singolo scenario |
| Costo dei run | Modello economico; run seriali on-demand; costo per scenario nel report |
| `run_headless_turn` scarta gli eventi | Estensione additiva del parametro sink (default invariato) |
| Isolamento imperfetto (DB/Qdrant reali) | Data dir temporanea obbligatoria; knowledge fuori misura in Fase 0 |
