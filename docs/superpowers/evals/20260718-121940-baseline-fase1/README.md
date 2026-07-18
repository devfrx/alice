# Baseline Fase 1 — Agent v2 (run 20260718-121940)

**Data:** 2026-07-18
**Modello:** `z-ai/glm-5.2` via OpenRouter (pinned in `backend/evals/runner.py`)
**Run id:** `20260718-121940` (report completo: `report.json` in questa cartella)
**Comando:** `python -m backend.evals run --baseline docs/superpowers/evals/2026-07-17-baseline-fase0/report.json` dalla repo root (venv root, key OpenRouter da keyring)
**Esito:** **23/23 scenari PASS — 79/79 check** — exit code 0
**Confronto baseline Fase 0 (`20260717-060213`):** **nessuna variazione per-scenario**
**Costo agente:** $0.0972 — HEAD del run: `fe6b716` (fine Mossa 2)

## Contesto

Gate di chiusura della **Fase 1 completa** (Mossa 1 motore + Mossa 2 wire v2):
il canale chat parla SOLO il vocabolario canonico v2 (`api/ws_schema/` +
`api/ws_schema/wire.py`), il frontend fa il fold su `agentRun`, l'adapter di
parità e il flag `agent.engine` sono eliminati. La suite eval è satura alla
baseline Fase 0 (la baseline È il tetto): questo run conferma parità
comportamentale end-to-end del percorso v2 headless, non misura un
miglioramento.

Questa è la baseline di riferimento per le fasi successive del programma
Agent v2 (Fase 2+).
