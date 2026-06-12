# Handoff — Risanamento architetturale AL\CE (stato al 2026-06-12, post-Fase 3)

> Per la sessione che continua questo lavoro a contesto fresco/compattato. Contiene SOLO ciò che
> non è ricostruibile dal repo: stato, decisioni, gotchas pagati sul campo, recon da fare.
> Fonti di verità nel repo: spec e piani citati sotto. Questo file SOSTITUISCE la versione
> precedente (post-fase2); la storia è in git.

## Stato del programma

- **Spec normativa** (approvata): `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` — 8 fasi, principi §4, criteri §9. È LA fonte di verità.
- **Fase 1a (Contratti REST): COMPLETATA** — branch `arch/fase1a-contratti-rest`, NON mergiato.
- **Fase 1b (Schema WS): COMPLETATA** — branch `arch/fase1b-ws-schema`, NON mergiato.
- **Fase 2 (Persistenza): COMPLETATA** — branch `arch/fase2-persistenza`, NON mergiato.
- **Fase 3 (Contenuti unificati): COMPLETATA** — branch `arch/fase3-contenuti` (figlio di fase2), review
  finale di fase «Phase ready» (2 fix doc applicati), **NON mergiato per decisione utente** (i branch si
  impilano: 3 su 2 su 1b su 1a). Piano chiuso e veritiero con esiti review per task:
  `docs/superpowers/plans/2026-06-12-fase3-contenuti-unificati.md` (in fondo: verdetto review finale + backlog).
- Pending esterni: chip/task `task_6c67e5a8` (fix suite lenta); CI `contracts.yml` MAI eseguita (parte al primo push).

## Cosa ha consegnato la Fase 3 (mappa rapida, dettagli nel piano)

- **Un solo modello di contenuto**: chart e whiteboard sono *kind* di `Artifact` (`ArtifactKind.CHART/WHITEBOARD`
  in `db/models.py`); blob JSON in `data/artifacts/<kind>/<artifact_id>.json` via `ArtifactBlobStore`
  (`services/artifacts/blob_store.py`, scritture atomiche). `chart_id`/`board_id` nei payload == UUID dell'artifact.
- **Registry generalizzato** (`services/artifacts/registry.py`): `create_json_artifact` (id pre-generabile),
  `read_json_content`, `update_json_artifact` (merge top-level + hook per-kind: `shape_count` whiteboard),
  `count_artifacts`, `delete_for_conversation` (detach pinned / delete unpinned + blob), `delete_all`.
  Eventi WS: `artifact.created` (conversation_id ora nullable) + nuovi `artifact.updated`/`artifact.deleted`
  (solo operazioni singole; bulk SENZA eventi, di proposito).
- **Plugin chart/whiteboard**: stessa capability (tool, validatore, shape_builder), persistenza SOLO via
  `ctx.artifact_registry` (`_registry()` con raise+cast, simmetrico). `ChartStore`/`WhiteboardStore` ELIMINATI.
- **Route**: `/api/charts` e `/api/whiteboards` ELIMINATE; `/api/artifacts/{id}/content` GET/PATCH tipizzate
  (PATCH = merge top-level, guardia 5MiB SUL BODY non sul blob risultante — commentato). Baseline ratchet −7.
  La pulizia artifact in `delete_conversation`/`delete_all_conversations` è DELEGATA al registry (transazione
  separata, idempotente — commentato).
- **Contesto system-prompt whiteboard** (`_build_whiteboard_context` in `chat/_helpers.py`): legge il registry
  (kind=whiteboard), non più i plugin internals; guardia tz-naive sul `updated_at` da SQLite.
- **FE**: store Pinia `charts` e `whiteboard` ELIMINATI (+ `types/whiteboard.ts` + 4 metodi api). Tutto sul
  store `artifacts` unificato (byKind 4 bucket, cache `contents` + `fetchContent(force?)`/`saveContent`).
  `types/artifacts.ts` = re-export `ApiSchema` (campi con default OPZIONALI → fallback `??` nei consumer).
  Helper puri `isChartPayload`/`extractCharts` in `types/chat.ts`. View-model lavagne in
  `composables/whiteboard/useWhiteboardBoards.ts` (conversation_title risolto dal chat store, non più dal BE).
  Viewer per kind invariati (ChartViewer via `api.getArtifactContent`, TldrawCanvas idem).
- Gate a fine fase: 143 mirati backend, typecheck 0, vitest 259/259, check-contracts verde, smoke e2e reale
  (boot, lista, content GET/PATCH con shape_count 1→2 dal hook, DELETE 204 con blob rimosso).

## Decisioni registrate in Fase 3 (non rilitigare)

1. **CAD resta dov'è**: GLB in `trellis.model_output_dir`, route `/api/cad/*` intatte (in baseline). Migrazione
   `export_url` → `/artifacts/{id}/download` = backlog fase 6.
2. **Dati legacy inerti**: `data/charts/` (49 file) e `data/whiteboards/` (3 file) restano su disco, mai letti
   né cancellati (stessa policy di `data/conversations/`). Payload vecchi nelle conversazioni → stato d'errore
   del viewer (azzerabile, nessuna migrazione).
3. **Eventi bulk**: `delete_for_conversation`/`delete_all` NON emettono `artifact.deleted` (parità pre-fase);
   invalidazione FE su delete conversazione = backlog.
4. **`refreshById` NON tocca la cache `contents`** (lo snapshot in editing non va strappato sotto l'editor);
   i viewer whiteboard fanno `fetchContent(id, force=true)` allo switch (parità freshness col legacy dopo
   edit agente). Live-update del board aperto = backlog.
5. **`list_charts` GLOBALE, `whiteboard list` scoped alla conversazione corrente** (parità pre-fase).
6. **PATCH content**: merge top-level, può toccare chiavi identity nel blob — inerte (l'identità è la riga).

## Prossimo lavoro: Fase 4 — Conoscenza (spec §5.2, terzo bullet)

Da scrivere con `writing-plans` su branch `arch/fase4-conoscenza` (figlio di `arch/fase3-contenuti`).
Requisiti spec: `KnowledgeService` unico punto d'accesso (sopra `CompositeKnowledgeBackend`); plugin memory
= guscio sottile di tools; route memory deleganti allo stesso service; client Continuum istanziato una volta
sola nel wiring. Da 6 strati a 3: *tools/route → KnowledgeService → backend componibili*.

### Recon da fare PRIMA del piano 4 (non fatta, puntatori noti)

- `services/memory_service.py`, `services/knowledge/` (QdrantBackend/ContinuumBackend/Composite),
  `plugins/memory/`, `plugins/continuum/`, route `memory.py`/`knowledge.py`/`mcp_memory.py`/`vector_store.py`,
  store FE `memory`/`mcpMemory`, dove viene istanziato il ContinuumClient (cercare doppie istanziazioni).
- Censire i consumatori di `memory_service`/`knowledge_backend` su ctx (turn assembly inietta memorie nel
  prompt — `_assembly.py`); verificare a mano i fatti load-bearing (gli audit dei subagent sbagliano i dettagli).
- Burn-down ratchet del dominio memory/knowledge (voci in `response_model_baseline.txt`).

## Workflow collaudato (riusare così)

- Per fase: branch dedicato → `writing-plans` (codice VERBATIM, comandi esatti) → `subagent-driven-development`:
  implementer (sonnet; haiku per fix meccanici da prescrizione esatta) + spec reviewer (sonnet) + quality
  reviewer (modello top, SEMPRE) + fix loop → review finale di fase (modello top, range intero, angolo =
  coerenza cross-task) → branch resta impilato, handoff aggiornato.
- Ogni fix di review aggiorna ANCHE il piano (esito per task, sempre); finding fuori task → backlog del piano.
- Le review hanno trovato bug veri anche in fase 3 (race async sugli snapshot whiteboard, copertura persa con
  un test legacy eliminato, type-ignore sbagliato, 4 consumatori FE nascosti). NON saltare i cicli.
- Commit convenzionali + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Mai push senza richiesta.

## Gotchas (validi anche dopo la fase 3)

1. **Suite backend completa IMPRATICABILE** (fixture `app` ~25s/test). Verifica di fase = test mirati per
   dominio + `tests/contracts/`. Test con fixture `client` al minimo (2-3 per task) e subagent avvisati di
   NON killare run lente (timeout 600s).
2. **`npm run lint` rotto repo-wide** → gate FE = `npx eslint <file toccati>` (solo ERRORI) + `npm run typecheck`.
3. **ruff/mypy con errori pre-esistenti** → scoped; file nuovi puliti; confrontare con `git show base:file`.
4. **CRLF**: file destinati al commit con `newline="\n"`. **MOJIBAKE PowerShell 5.1**: MAI editare file
   non-ASCII via cmdlet PowerShell; Edit tool o Bash+python.
5. **Subagent**: prescrizioni ESATTE ai fix-agent e VERIFICARE IL DIFF al ritorno (`git show`); un agente ha
   dichiarato un "push" mai avvenuto (verificare con `git branch -vv`); commit con due `-m`, trailer esatto,
   niente here-string.
6. **`check-contracts.ps1` DOPO il commit** (untracked = dirty). Regen SOLO nei task previsti: tra un task che
   elimina route e la regen, `test_openapi_export` resta rosso — non eseguirlo nei task intermedi.
7. **PowerShell 5.1**: niente `&&`; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`.
8. **`ToolResult.error()` riempie `error_message`, NON `content`** — i test sugli errori dei tool asserzionano
   `res.error_message` (typo ricorrente nei piani, già pagato due volte).
9. **Recon FE**: censire anche le chiamate api DIRETTE nei componenti (grep sui nomi dei metodi api), non solo
   gli import degli store — TldrawCanvas e HorizonStage erano consumatori nascosti delle route whiteboard.
10. **Campi generati opzionali**: i tipi `ApiSchema` rendono OPZIONALI i campi con default backend
    (artifact_metadata, pinned, conversation_id) → fallback `??` nei consumer, mai tipi a mano.
11. **Contratti WS**: regole 1b invariate (modello in ws_schema + vocabolario congelato in
    `test_ws_schema_events.py` + dispatcher FE esaustivo: nuovo frame senza handler = errore di compilazione).

## Backlog (oltre a quello in fondo ai piani 1a/1b/2/3)

1. Burn-down ratchet REST residuo nelle fasi 4-6, dominio per dominio (`{items,total}` per le liste).
2. (fase 3) Eventi bulk delete + invalidazione store FE artifacts su delete conversazione.
3. (fase 3) Live-update whiteboard aperto su `artifact.updated` (design per non strappare lo snapshot);
   ChartViewer non si ri-fetcha su `artifact.updated` (onMounted-only, pre-esistente).
4. (fase 3) CAD: `export_url` → `/artifacts/{id}/download`, eliminare `/api/cad/models*` (fase 6).
5. (fase 3) `_parse_artifact_id` duplicato nei due plugin e usato anche per conversation_id → `_parse_uuid`
   condiviso se nasce un modulo comune; `DELETE /api/artifacts/{id}` e `GET .../download` restano in baseline.
6. (fase 3) Test pinia sul filtro conversazione di `useWhiteboardBoards`; DRY `remove`→`removeLocal` nello
   store artifacts (scelta consapevole di non farlo).
7. `AgentTier` duplicato a mano in FE `types/settings.ts` (pre-esistente); canale voice hand-typed;
   narrowing `as` in `stores/services.ts`; calendar non emette `calendar.changed`.
8. (fase 2) Export via modello (`ConversationExport(...).model_dump()`); `POST .../import` a modello;
   home neutrale per `ConversationSummaryResponse`; `Literal["deleted"]` sui DeleteResponse.
9. Valutare vitest in CI quando stabile.

## Decisioni utente registrate (non rilitigare)

- Refactor incrementale, app sempre funzionante; dati azzerabili (no migrazioni); orb-era UI da eliminare
  (Horizon unica superficie); codegen completo; visione = runtime agentico locale con Command Layer
  (invariante anti-escalation non negoziabile, spec §7).
- I branch di fase restano NON mergiati e NON pushati finché l'utente non decide diversamente; si impilano
  (3 sopra 2 sopra 1b sopra 1a).
