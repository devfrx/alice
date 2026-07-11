# Handoff — Risanamento architetturale AL\CE (stato al 2026-06-12, post-Fase 2)

> Per la sessione che continua questo lavoro a contesto fresco/compattato. Contiene SOLO ciò che
> non è ricostruibile dal repo: stato, decisioni, gotchas pagati sul campo, recon da fare.
> Fonti di verità nel repo: spec e piani citati sotto. Questo file SOSTITUISCE la versione
> precedente (post-1b); la storia è in git.

## Stato del programma

- **Spec normativa** (approvata): `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` — 8 fasi, principi §4, criteri §9. È LA fonte di verità.
- **Fase 1a (Contratti REST): COMPLETATA** — branch `arch/fase1a-contratti-rest` (head `a209957`), NON mergiato. Piano chiuso: `docs/superpowers/plans/2026-06-10-fase1a-contratti-rest.md`.
- **Fase 1b (Schema WS tipizzato): COMPLETATA** — branch `arch/fase1b-ws-schema` (head `f6b6a18`), NON mergiato. Piano chiuso: `docs/superpowers/plans/2026-06-11-fase1b-ws-schema.md`.
- **Fase 2 (Persistenza): COMPLETATA** — branch `arch/fase2-persistenza` (figlio di 1b), review finale di fase «Phase ready: Yes», **NON mergiato per decisione utente** (i branch si impilano: 2 sopra 1b sopra 1a). Piano chiuso e veritiero con esiti review per task: `docs/superpowers/plans/2026-06-11-fase2-persistenza.md` (in fondo: review finale + note handoff + backlog).
- Pending esterni: chip/task `task_6c67e5a8` (fix suite lenta); CI `contracts.yml` MAI eseguita (parte al primo push); prova live dei due bottoni sidebar (Esporta / Backup tutte) all'avvio frontend — il percorso REST sottostante è stato smoke-testato per davvero (exported=3).

## Cosa ha consegnato la Fase 2 (mappa rapida, dettagli nel piano)

- **SQLite unica fonte di verità**: `ConversationFileManager` + mirror JSON + rebuild allo startup ELIMINATI (protocollo, campo ctx, lifespan, threading `sync_fn` nel turn engine: tutto sparito; grep = 0).
- **Un solo motore di export**: `backend/services/conversation_export.py` — modelli contratto (`ConversationExport` & co.), `build_conversation_export`, `export_conversations_to_dir` (scritture atomiche), `attachment_url` (pubblica, ex `_attachment_url` di `_shared.py`), `default_backup_dir()`. REST, tool e UI delegano TUTTI qui.
- **Tre fronti espliciti**: `GET .../export` (tipizzato) + `POST /chat/conversations/backup` (`BackupRequest`/`BackupResult`, dest assoluta o default `data/backups/conversations-<ts>/`); plugin `conversation_backup` (tool `backup_conversations`, sentinella `'current'` da `context.conversation_id`, errore su id inesistente, capabilities OMESSE di proposito: dest app-owned, `fs_write` farebbe scattare DENY_NO_SCOPE a torto); sidebar FE (picker directory Electron + toast con conteggio, `useToast` esistente).
- **Contratti**: ratchet REST −9 voci (dominio conversations tipizzato; resta SOLO `GET /chat/conversations/{id}` in baseline); lista → `{items,total}`; endpoint `file-path` ELIMINATO. Tipi FE del dominio = re-export `ApiSchema<'...'>` (inclusi Rename/BranchRequest). `check-contracts` verde.
- **Guardia nuova**: `tests/test_backend_spec.py` — `PLUGIN_PACKAGES` di `backend.spec` ↔ filesystem (manifest riconciliato per intero: +agent/continuum/terminal/conversation_backup, −notes fantasma).
- Gate a fine fase: 147 mirati backend, typecheck FE 0, vitest 259/259, check-contracts verde, boot smoke reale (health 200, backup e2e, dir mirror legacy intatta e mai ricreata).

## Decisioni registrate in Fase 2 (non rilitigare)

1. **`exported=0` ha semantica diversa per fronte, DI PROPOSITO**: REST → 200 con conteggio (la UI mostra warning toast); tool agente → errore esplicito (l'LLM non deve dichiarare backup mai avvenuti). Non uniformare alla cieca in Fase 6.
2. **`POST .../backup` accetta `dest_dir` assoluta arbitraria**: corretto per la UI locale (picker). In **Fase 7** l'endpoint deve restare strutturalmente FUORI dalla superficie agent-callable del Command Layer; il tool agente è già confinato a `data/backups/`.
3. **GET dettaglio conversazione resta in baseline ratchet** (modello pesante con context_usage) — si tipizza in Fase 6 col client per dominio.
4. La dir legacy `data/conversations/` (152 file utente) resta su disco, inerte: mai letta, mai cancellata (dati azzerabili per decisione; nessuna pulizia automatica).

## Prossimo lavoro: Fase 3 — Contenuti unificati (spec §5.2, secondo bullet)

Da scrivere con `writing-plans` su branch `arch/fase3-contenuti` (figlio di `arch/fase2-persistenza`). Requisiti spec: chart, whiteboard, modelli 3D/CAD → *kind* di un solo `Artifact` (metadati DB, blob in `data/artifacts/<kind>/`); UN registry (generalizzare `ArtifactRegistry`), UNA famiglia di route `/api/artifacts`, UN solo store FE con viewer per kind; `ChartStore` e `WhiteboardStore` assorbiti ed eliminati.

### Recon da fare PRIMA del piano 3 (non fatta, puntatori noti)

- `plugins/chart_generator/chart_store.py`, `plugins/whiteboard/store.py`, `services/artifacts/registry.py` (+ parsers), route esistenti (artifacts/charts/`whiteboards.py`), store FE `artifacts`/`charts`/`whiteboard`, tabelle DB (`Artifact`/`ArtifactKind` in `db/models.py` — verificare cosa esiste già).
- **Da review fase 2**: la pulizia file-artifact inline in `delete_conversation`/`delete_all_conversations` (`conversations.py` ~414-574) va ASSORBITA dal servizio artifact unificato — non duplicarla.
- Il whiteboard plugin è letto anche da `_helpers._build_whiteboard_context` (system prompt) — censire i consumatori prima di spostare lo store.
- Verificare a mano i fatti load-bearing (gli audit dei subagent sbagliano i dettagli — gotcha storico).

## Workflow collaudato (riusare così)

- Per fase: branch dedicato → `writing-plans` (codice VERBATIM, comandi esatti) → `subagent-driven-development`: implementer (haiku per fix meccanici da prescrizione esatta, sonnet per multi-file) + spec reviewer (sonnet) + quality reviewer (modello top, SEMPRE) + fix loop → review finale di fase (modello top, range intero, angolo = coerenza cross-task) → `finishing-a-development-branch`.
- Ogni fix di review aggiorna ANCHE il piano (esito per task, sempre); finding fuori task → backlog del piano o task successivi.
- Le review hanno trovato bug veri a quasi ogni task anche in fase 2 (test vacuo file-path, mock stale che silenziava un TypeError, tool inutilizzabile dall'LLM senza sentinella 'current', manifest PyInstaller). NON saltare i cicli.
- Commit convenzionali + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Mai push senza richiesta.

## Gotchas (validi anche dopo la fase 2)

1. **Suite backend completa IMPRATICABILE** (fixture `app` ~25s/test). Verifica di fase = test mirati per dominio toccato + `tests/contracts/`.
2. **`npm run lint` fallisce repo-wide** (pre-esistente) → gate FE = `npx eslint <file toccati>` (contare solo gli ERRORI) + `npm run typecheck` exit 0.
3. **ruff/mypy con errori pre-esistenti** in molti file → scoped; file nuovi sempre puliti. Verificare la pre-esistenza confrontando con la base (`git show base:file`).
4. **CRLF**: file destinati al commit con `newline="\n"`.
5. **MOJIBAKE PowerShell 5.1**: MAI editare file non-ASCII via cmdlet PowerShell; usare Edit tool o Bash+python.
6. **Subagent**: prompt con forma `git commit -m "subject" -m "Co-Authored-By: ..."` e "trailer exactly `Claude Fable 5`" esplicito; niente here-string. Ai fix-agent dare prescrizioni ESATTE (diff atteso) e VERIFICARE IL DIFF al ritorno — un agente in fase 2 ha attribuito a "un formatter" modifiche extra proprie (benefiche ma non richieste) e ha lasciato un file untracked fuori commit: controllare `git status` dopo ogni fix-agent.
7. **`check-contracts.ps1` DOPO il commit** (untracked = dirty). Baseline ratchet: `$env:ALICE_REGEN_CONTRACT_BASELINE="1"` + pytest → fallisce APPOSTA, rilanciare senza env var.
8. **PowerShell 5.1**: niente `&&`; attenzione ai `cd backend` relativi quando la cwd è già `backend/` (usare `Set-Location` con path assoluti).
9. Ambiente: pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`; venv `.venv` alla radice.
10. **Contratti WS**: invariati in fase 2 (nessun frame nuovo). Le regole 1b restano (modello in ws_schema + vocabolario congelato + dispatcher FE esaustivo).
11. **API test lenti**: i test con fixture `client` (~25s l'uno) vanno tenuti al minimo (3-4 per file) e i subagent avvisati di NON killare run lente (timeout 600s).

## Backlog (oltre a quello in fondo ai piani 1a/1b/2)

1. Burn-down ratchet REST residuo nelle fasi 3-6, dominio per dominio (con `{items,total}` per le liste).
2. `AgentTier` duplicato a mano in FE `types/settings.ts:171` (§4, pre-esistente).
3. Calendar non emette `calendar.changed` (chiudere quando si tocca il dominio).
4. Canale voice (`useVoice.ts`, `types/voice.ts`) hand-typed.
5. Narrowing `as` in `stores/services.ts:238,262`.
6. (fase 2) Export costruito a dict: valutare costruzione VIA modello (`ConversationExport(...).model_dump()`) ora che il filo sync è morto — garanzia schema anche per i file di backup.
7. (fase 2) `POST .../import` accetta body non-Pydantic (validazione a mano) — convertire a modello al prossimo passaggio sul dominio.
8. (fase 2) `ConversationSummaryResponse` vive in un modulo route e `io.py` la importa route→route — home neutrale se compare un terzo consumatore (fase 6).
9. (fase 2) Narrowing `Literal["deleted"]` sui DeleteResponse (lato BE) quando si ritocca il dominio.
10. Valutare vitest in CI quando stabile.

## Decisioni utente registrate (non rilitigare)

- Refactor incrementale, app sempre funzionante; dati azzerabili (no migrazioni); orb-era UI da eliminare (Horizon unica superficie); codegen completo; visione = runtime agentico locale con Command Layer (invariante anti-escalation non negoziabile, spec §7).
- I branch di fase restano NON mergiati e NON pushati finché l'utente non decide diversamente; si impilano (2 sopra 1b sopra 1a).
