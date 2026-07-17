# Baseline Fase 0 — Agent v2 (run 20260717-060213)

**Data:** 2026-07-17
**Modello:** `z-ai/glm-5.2` via OpenRouter (pinned in `backend/evals/runner.py`)
**Run id:** `20260717-060213` (report completo: `report.json` in questa cartella)
**Comando:** `python -m backend.evals run` dalla repo root (venv root, key OpenRouter da keyring)
**Esito:** **23/23 scenari PASS — 79/79 check** — exit code 0
**Costo agente:** $0.2843 — **Durata:** ~11.5 min (somma scenari 639s)
**Token:** input 1.007.080 / output 14.010 (vedi caveat sotto)

## Risultati per dominio

| Dominio     | Scenari | Check | Costo ($) |
|-------------|---------|-------|-----------|
| filesystem  | 5/5     | 20/20 | 0.0594    |
| knowledge   | 2/2     | 7/7   | 0.0197    |
| multistep   | 4/4     | 17/17 | 0.0502    |
| permissions | 3/3     | 7/7   | 0.0263    |
| planning    | 3/3     | 11/11 | 0.0600    |
| recovery    | 3/3     | 10/10 | 0.0318    |
| search      | 3/3     | 7/7   | 0.0369    |

Prova economica preliminare (stesso giorno, run `20260717-055938`, 5 scenari fs senza judge):
5/5, 20/20, $0.0925 — spesa totale della sessione ~$0.38.

## Judge LLM

5 criteri valutati su 5 scenari:

| Scenario                | Score | Note |
|-------------------------|-------|------|
| fs-read-summarize-01    | 0     | **verdetto non parsabile** (completion vuota → 0 fail-closed) |
| multi-checklist-01      | 0     | **verdetto non parsabile** (completion vuota → 0 fail-closed) |
| perm-plan-readonly-01   | 10    | ok |
| perm-scope-01           | 10    | ok |
| plan-doc-01             | 10    | ok |

Il judge è informativo, non gate del pass: i due score 0 sono rumore del judge (il modello
ha restituito una completion vuota), non giudizi negativi — le risposte dell'agente in
entrambi i casi erano corrette (verificato a mano nel report). Follow-up candidato per le
fasi successive: retry sul verdetto vuoto in `evals/judge.py`.

## Osservazioni (alimentano le fasi 1-4)

1. **La suite è satura alla baseline.** L'handoff prevedeva exit code 1 (fallimenti che
   fotografano i limiti dell'agente); l'agente attuale passa invece tutto. Come guardia di
   regressione la suite funziona da subito, ma per misurare i *miglioramenti* delle fasi
   1-4 servono scenari più difficili (multi-turno lunghi, ambiguità reali, recovery da
   errori di tool ripetuti, contesti più grandi, tool distractor).
2. **Ambiente della baseline: embeddings/tool-RAG disabilitati.** Con provider `openrouter`
   gli embedding restano locali ma il fallback fastembed era inattivo
   (`qdrant.embedding_dim=1024`, `embedding_fallback=False` dal layer utente): il boot
   dell'harness ha disabilitato memoria semantica e tool-RAG, quindi l'offerta tool non è
   passata dal ranking RAG. I meta-tool planning risultavano comunque offerti (plan-tasks-01
   e plan-doc-01 passano). Una baseline con RAG attivo richiederebbe `embedding_dim=384` +
   `embedding_fallback=True` nel layer di config dell'harness.
3. **Caveat token:** i token nel report sommano solo le snapshot `turn.usage` delle re-query
   del tool loop (un turno senza tool call riporta 0); il **costo** è invece sempre corretto
   (`TurnResult.cost`).
4. Nessun timeout, nessun errore di trasporto, nessun fail di phrasing sui
   `response_matches`: i pattern allargati nella review finale hanno tenuto.
