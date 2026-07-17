# Handoff — Agent v2 Fase 0: Eval harness + baseline (feat/agent-evals-fase0)

**Data:** 2026-07-17
**Branch:** `feat/agent-evals-fase0` — **NON ancora mergiato**, pushato su origin (19 commit, HEAD `7bedd10`)
**Programma:** `docs/superpowers/specs/2026-07-16-agent-v2-program-design.md` (Agent v2 — parità Claude Code, 9 fasi)
**Spec di fase:** `docs/superpowers/specs/2026-07-16-agent-evals-fase0-design.md`
**Piano:** `docs/superpowers/plans/2026-07-16-agent-evals-fase0.md` (13 task)
**Metodo:** subagent-driven — ogni task: implementer + spec review + quality review; 8 fix di
review applicati in-branch; review olistica finale: **Ready to merge**.

## Stato: IMPLEMENTAZIONE COMPLETA (task 1-12); manca SOLO il Task 13

Il Task 13 è il **run baseline reale** (OpenRouter, `z-ai/glm-5.2`, ~23 scenari + judge,
pochi dollari, 15-40 min) — richiede l'OK esplicito dell'utente sulla spesa, ancora NON dato.
Dopo il run: baseline committata in `docs/superpowers/evals/`, merge in main, aggiornamento di
questo handoff.

## Come riprendere su un'altra macchina

1. `git fetch && git checkout feat/agent-evals-fase0`
2. Setup standard (CLAUDE.md): venv root, `cd backend; uv pip install -e ".[dev,memory]"`,
   `uv pip install sqlite-vec`.
3. Sanity: da `backend/`: `pytest tests/evals/ -v` → **39 passed** attesi (l'e2e mock
   `test_runner_mock.py` boota l'app completa, ~30s).
4. Smoke CLI da repo root: `python -m backend.evals list` → 23 scenari.
5. **Task 13** (con OK dell'utente sulla spesa):
   - la API key OpenRouter deve essere nel Credential Manager (`alice /
     llm.openrouter_api_key`, c'è già se la macchina ha fatto l'e2e del programma OpenRouter)
     o in env `ALICE_LLM__OPENROUTER_API_KEY`;
   - prova economica: `python -m backend.evals run --filter fs- --no-judge` (5 scenari);
   - run completo: `python -m backend.evals run` (23 scenari; **exit code 1 è ATTESO** — la
     baseline fotografa i limiti dell'agente attuale, alcuni scenari falliranno);
   - copia `evals_output/<run_id>/report.json` in
     `docs/superpowers/evals/<data>-baseline-fase0/` + README con: data, modello, run_id,
     tabella per-dominio, costo totale, osservazioni sui fallimenti (alimentano le fasi 1-4);
   - commit baseline, merge del branch in main, push, aggiorna questo handoff.

## Cosa contiene il branch (architettura)

- **`backend/evals/`** (package nuovo, fuori dai contratti import-linter):
  - `models.py` — pydantic v2; modelli input YAML con `extra="forbid"`; 8 check kinds; 7 domini.
  - `loader.py` — YAML → `Scenario`; `ScenarioLoadError` (I/O, sintassi, schema, id≠filename).
  - `trace.py` — sintesi dai frame canonici (`turn.llm_step`→steps, `tool.call`→nomi,
    `turn.usage` **sommati** su tutti gli step); JSONL sempre LF (`newline="\n"`).
  - `checks.py` — valutatori fail-closed: regex invalida → check fallito; path fuori sandbox →
    check fallito (`is_relative_to`); `tool_called` con match a suffisso (`read_text_file`
    matcha `file_search_read_text_file`).
  - `judge.py` — `complete_nonstreaming` per criterio; parsing JSON→regex→0; Protocol locale
    `_JudgeLLM` (interface segregation).
  - `runner.py` — `PINNED_MODEL="z-ai/glm-5.2"`; `eval_app()` su `create_app(testing=True)`
    (DB in-memory, secret store in-memory, ctx da `app.state.context`); per scenario: sandbox
    temp + `Conversation` + `set_scope` + `set_mode` + `RecordingEventSink` +
    `run_headless_turn` con `wait_for` sul budget; trace best-effort anche su timeout/errore;
    `run_suite` seriale in una singola app.
  - `report.py` — save/load JSON (LF), `compare_reports` (REGRESSIONE/MIGLIORATO/NUOVO/
    RIMOSSO), `render_text` con totali e costo.
  - `cli.py` + `__main__.py` — `run`/`list`, `--filter/--output/--no-judge/--baseline`; key
    env→keyring; forza `ALICE_LLM__PROVIDER/OPENROUTER_MODEL/OPENROUTER_API_KEY` PRIMA del
    boot; **isolamento Qdrant**: `setdefault("ALICE_QDRANT__PATH", <output>/qdrant)` (il
    lifespan testing altrimenti aprirebbe il `data/qdrant` REALE — stage_knowledge non ha
    flag testing); stdout/stderr riconfigurati UTF-8 (crash cp1252 altrimenti).
  - `scenarios/*.yaml` — 23 scenari: fs 5, search 3, multistep 4, planning 3, permissions 3,
    recovery 3, knowledge 2. Prompt italiani, `{sandbox}` sostituito dal runner.
- **Unica modifica al runtime** (additiva): `run_headless_turn(..., sink: WSEventSink | None
  = None)` — default `NullEventSink` invariato; il sink iniettato DEVE tenere
  `is_connected=True` (l'executor tronca lo stream altrimenti; `RecordingEventSink` ok).
- **Test**: `backend/tests/evals/` (39): unit per modulo + `scripted_llm.py`
  (`ScriptedLLM` = LLMServiceProtocol minimo a eventi scriptati) + e2e mock che attraversa
  il percorso di produzione VERO (assembly → executor → persist). Girano in CI dentro pytest.
- **Docs**: CLAUDE.md sezione "Agent evals"; `.gitignore` += `evals_output/`.

## Gate verificati (2026-07-17)

ruff repo-wide = 0; mypy a parità sui 21 file toccati (uniche eccezioni pre-esistenti: 3 errori
`LLMServiceProtocol` vs `LLMService` in `headless.py`, `import-untyped` su yaml — manca
`types-PyYAML`, debito censito); import-linter 6/6 kept; evals suite 39/39; regressione
`-k "headless or trigger or turn"`: 235 passed + 1 rosso PRE-ESISTENTE
(`test_voice_tool_calling.py::TestVoiceTranscription::test_no_stt_service_returns_empty`,
identico su main — zona voice nota, AUD-008).

## Gotchas scoperti in sessione (NON ripeterli)

1. **Subagent + pytest in background = stallo** (riconferma del gotcha settings-core): il gate
   agent si è appeso su un run in background; SEMPRE foreground nei dispatch, dirlo esplicito.
2. **Console cp1252**: `print()` di titoli con Unicode (→, è) crasha la CLI su console legacy —
   risolto con `stream.reconfigure(encoding="utf-8")` in `main()`.
3. **`Path.open("w")` senza `newline=`** su Windows scrive CRLF anche se scrivi `"\n"` — tutti
   i writer dell'harness usano `newline="\n"`.
4. **`monkeypatch.delenv` su chiave assente non registra teardown**: per mettere sotto
   controllo chiavi che il codice sotto test SETTA internamente serve `setenv(sentinel)` prima
   (vedi `test_cli.py`).
5. **ruff format ha un drift di versione** (0.15.16 locale vs pin implicito): un caso di
   formattazione in `test_cli.py` segnalato da `--check` ma pre-esistente allo HEAD — non
   sistemato (fuori scope), non è nel gate CI (solo `ruff check` lo è).
6. **Processi pytest orfani**: sulla macchina originale girano 4 pytest stale di sessioni
   precedenti su `test_voice_tool_calling.py` (PID 27776/21368/28212/38980) — da killare a
   mano; non inquinano gli esiti ma tengono lock.
7. Regola utente (in memoria locale, ripetuta qui perché la memoria NON segue la macchina):
   suite pytest integrale RARAMENTE e sempre cappata a 20-25 min (oltre = hang AUD-008);
   mai due pytest concorrenti.

## Residui censiti (deliberati, per le fasi successive)

- `setup.config` (override ALICE_* per-scenario) è nella spec §3.1 ma NON implementato
  (YAGNI: nessuno scenario lo usa; `extra="forbid"` rifiuta pulito chi lo usasse).
- L'isolamento Qdrant vive SOLO nella CLI: chi chiamasse `run_suite` programmaticamente
  scriverebbe nel `data/qdrant` reale — candidato spostamento in `run_suite` se nasce un
  secondo entry point.
- `backend.evals` non è in alcun contratto import-linter — candidato contratto "app ↛ evals".
- Token nel report = somma delle snapshot `turn.usage` (solo re-query del tool loop:
  un turno senza tool call riporta 0 token; il costo invece è sempre corretto da
  `TurnResult.cost`).
- Tool RAG (top_k 20) può NON offrire i meta-tool agli scenari planning: un fail su
  `tool_called: update_tasks` va verificato nella trace JSONL (tool non offerto ≠ agente
  che sbaglia).
- Timeout default 180s: possibili 1-3 timeout spuri col modello cloud nei giorni lenti;
  multistep già a 240-300.

## Rischi noti per il run baseline (Task 13)

Exit code 1 atteso; primo scenario più lento (Qdrant embedded crea le collection, eventuale
download fastembed); qualche FAIL sarà rumore di phrasing sui `response_matches` nonostante i
pattern allargati — leggere le trace prima di trarre conclusioni; mai due run concorrenti.
