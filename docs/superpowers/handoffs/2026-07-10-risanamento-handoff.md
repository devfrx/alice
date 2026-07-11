# Handoff — Risanamento architetturale AL\CE (stato al 2026-07-10, post-Fase 5)

> Per la sessione che continua questo lavoro a contesto fresco/compattato. Contiene SOLO ciò che
> non è ricostruibile dal repo: stato, decisioni, gotchas pagati sul campo, recon da fare.
> Fonti di verità nel repo: spec e piani citati sotto. Questo file SOSTITUISCE la versione
> precedente (post-fase4, `2026-07-08-risanamento-handoff.md`); la storia è in git.

## Stato del programma

- **Spec normativa** (approvata): `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` — 8 fasi, principi §4, criteri §9. È LA fonte di verità.
- **Fasi 1a, 1b, 2, 3, 4, 5: COMPLETE** — branch impilati NON mergiati e NON pushati per decisione utente
  (5 su 4 su 3 su 2 su 1b su 1a): `arch/fase1a-contratti-rest` → `arch/fase1b-ws-schema` →
  `arch/fase2-persistenza` → `arch/fase3-contenuti` → `arch/fase4-conoscenza` → `arch/fase5-kernel`
  (conteggio e head: `git log --oneline arch/fase4-conoscenza..arch/fase5-kernel`).
- **Fase 5 (Kernel): COMPLETATA** — review finale di fase «Phase ready with notes», zero fix
  richiesti. Piano chiuso e veritiero con esiti review per task + verdetto finale + backlog:
  `docs/superpowers/plans/2026-07-08-fase5-kernel.md`.
- Pending esterni: chip/task `task_6c67e5a8` (fix suite lenta); CI `contracts.yml` MAI eseguita
  (parte al primo push) — ora include anche lo step import-linter.

## Cosa ha consegnato la Fase 5 (mappa rapida, dettagli nel piano)

- **`AppContext` = 5 gruppi coesi** (`core/service_groups.py`: `inference`/`knowledge`/`workspace`/
  `conversation`/`platform`) con radice sottile (`core/context.py`, classe regolare, non più
  dataclass): TUTTI i 34 nomi piatti legacy restano property tipizzate get+set deleganti;
  costruttore accetta i kwargs piatti (le ~20 fixture di test sono intatte). La migrazione dei
  consumer ai gruppi è BACKLOG, le property sono l'API di transizione.
- **Bootstrap dichiarativo**: `core/bootstrap/` con 9 stage 1:1 con l'ordine pre-esistente
  (`database → platform → inference → knowledge → senses → plugins → surfaces → conversation →
  workspace`) + `shutdown_services` difensivo (gira anche su failure a metà startup con ctx
  parziale — deviazione accettata + `tests/test_bootstrap.py`). `core/app.py`: ~800 → ~150 righe,
  zero `from backend.services`.
- **Repair a swap atomico**: `repair_vector_store` costruisce in locali e swappa `ctx.knowledge`
  intero (1 scrittura coerente + rag_readiness additiva) — chiuso il backlog fase 4 sulla finestra
  di concorrenza; ri-punta ToolRag via `set_vector_backends`; `QdrantServiceProtocol.in_memory`
  aggiunto. Test: `tests/test_knowledge_repair.py`.
- **`tool_registry` = facade su `core/tools/`** (catalog/availability/policy/execution/rag);
  firma e API pubblica IDENTICHE, suite di equivalenza passata SENZA modifiche ai test; alias
  test-compat `_tools`/`_tool_to_plugin`/`_status_probe_timeout` (backlog: migrare i test).
  Costanti vettoriali in `core/vector_collections.py` (qdrant_service le re-esporta).
- **`llm_service` = facade su `services/llm/`** (client/prompting/model_resolution); il facade
  possiede l'httpx client (`self._client` RESTA l'httpx grezzo — i test lo patchano) e la famiglia
  context-window (test usa `__new__`); `LLMClient` in `self._llm_client`; protocol allineato
  (scoped prompt, context-window, response_format/temperature su chat). NON riassegnare mai
  `svc._client` (footgun: resolver/client lo tengono per riferimento) — per un futuro hot-reload
  ricostruire l'intero LLMService come stt/tts.
- **Flag**: `docs/flag-registry.md` (21 vivi, censimento verificato); 3 morti RIMOSSI
  (`voice.voice_confirmation_enabled`, `pc_automation.enabled`, `notifications.sound_enabled`)
  con strip legacy per-layer (`_strip_removed_legacy_keys` in `migrate_legacy_config_keys`,
  copre anche env `ALICE_*` stantie e costruzione diretta via model_validator). Regen: zero diff.
- **Layering sanato + import-linter in CI**: `services/calendar_events.py` (modello+rrule condivisi),
  `services/mcp_gateway.py` (`McpClientProtocol` strutturale con isinstance runtime_checkable +
  i tre 503 canonici — chiuso backlog "mcp_memory → service MCP"), terminal `security.py` →
  `services/terminal/`. `[tool.importlinter]` in backend/pyproject.toml: **6 contratti kept, 0
  broken** (454 file); step CI in contracts.yml. NB: i wildcard grimp `*` matchano UN livello,
  `**` è ricorsivo — le ignore usano `**` dove serve; una ignore che non matcha FA FALLIRE il run.

## Decisioni registrate in Fase 5 (non rilitigare)

1. **Property piatte = API di transizione**; migrazione consumer ai gruppi è backlog, non lavoro di fase.
2. **Stage di init ≠ gruppo di appartenenza** (es. context_manager [Conversation] nasce nello stage inference).
3. **Shutdown su failure a metà startup** è una deviazione ACCETTATA (miglioramento reale, testato).
4. **Context-window resta sul facade LLM** e **`svc._client` resta httpx**: vincoli di test binding
   (`__new__`, patch su `._client`) — si armonizza solo migrando i test (backlog).
5. **Ignore-list import-linter = perimetro approvato** (composition root + 2 re-export protocol);
   non allargarla senza review; una entry che non matcha più va rimossa.
6. Docstring/commenti in inglese; piano ed esiti in italiano.

## Prossimo lavoro: Fase 6 — Frontend (spec §5, riga 215)

Da scrivere con `writing-plans` su branch `arch/fase6-frontend` (figlio di `arch/fase5-kernel`).
Requisiti spec: **rimozione orb-era** (Horizon unica superficie); **client per dominio**;
**dispatcher tipizzato**; **Command Registry** (azioni UI come comandi). Dipende da fasi 1 e 3.

Messaggio di kickoff della sessione (copiare tale e quale):
«leggi specs, piano ed handoff della skill superpowers e continuiamo l'implementazione. /using-superpowers»

### Recon fase 6 — note utili già verificate

- Backlog FE ereditato da piazzare nella fase: `AgentTier` duplicato FE; vitest in CI;
  eventi bulk delete artifacts + invalidazione FE; live-update whiteboard; CAD `export_url` →
  `/artifacts/{id}/download`; `memory.spec.ts`; mutazioni KG tipizzate `KGMutationResponse` in api.ts.
- CLAUDE.md già descrive Horizon come superficie primaria e gli orb-era come legacy.
- `npm run lint` rotto repo-wide (gotcha 2): la fase 6 è l'occasione naturale per sanarlo.

## Workflow collaudato (riusare così; raffinamenti fase 5 inclusi)

- Per fase: branch dedicato → `writing-plans` (codice VERBATIM, comandi esatti) → `subagent-driven-development`:
  implementer (sonnet) + spec reviewer (sonnet) + quality reviewer (modello top, SEMPRE) + fix loop →
  review finale di fase (modello top, range intero, angolo = coerenza cross-task) → branch resta
  impilato, handoff aggiornato.
- I nit banali delle review (1-10 righe) li applica il CONTROLLER direttamente, verificando coi
  gate scoped. **Raffinamento fase 5**: task di pura configurazione con gate auto-verificante
  (es. import-linter) può farli il controller direttamente; le due review per-task (spec+quality)
  possono girare IN PARALLELO dopo la verifica del diff dell'implementer.
- Ogni fix di review aggiorna ANCHE il piano (esito per task, sempre); finding fuori task → backlog del piano.
- Le review hanno trovato cose vere anche in fase 5 (I001 introdotto dal rename in terminal manager,
  docstring package inveritiera, test end-to-end extra=forbid mancante, runtime_checkable inerte).
  NON saltare i cicli.
- Commit convenzionali + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Mai push senza richiesta.

## Gotchas (validi anche dopo la fase 5)

1. **Suite backend completa IMPRATICABILE** (fixture `app` ~25s/test). Verifica di fase = test mirati per
   dominio + `tests/contracts/`. Subagent avvisati di NON killare run lente (timeout 600s).
2. **`npm run lint` rotto repo-wide** → gate FE = `npx eslint <file toccati>` (solo ERRORI) + `npm run typecheck`.
3. **ruff/mypy con errori pre-esistenti** → scoped; file nuovi puliti; confrontare con `git show <base>:file`.
   N815 è ATTIVA (i camelCase MCP richiedono noqa mirati sui campi NUOVI, mai sui pre-esistenti).
4. **EOL: TRE incidenti nel programma** (2 in fase 4; in fase 5 l'Edit del controller ha flippato
   `pc_automation/README.md` a CRLF). Il repo è `i/lf` in index (con eccezioni). SEMPRE verificare
   `git ls-files --eol <file toccati>` PRIMA e DOPO ogni commit; diff sospettosamente grande = flip EOL
   (`git diff --ignore-cr-at-eol --stat` per smascherarlo). MAI cmdlet PowerShell su file non-ASCII.
5. **Subagent**: prescrizioni ESATTE ai fix-agent e VERIFICARE IL DIFF al ritorno (`git show`); commit con
   due `-m`, trailer esatto, niente here-string. Un reviewer morto con output vuoto → RILANCIARE.
6. **`check-contracts.ps1` DOPO il commit** (untracked = dirty). Regen SOLO nel task previsto.
7. **PowerShell 5.1**: niente `&&`; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`;
   il boot-check (`create_app`) va lanciato dalla REPO ROOT, non da `backend/`.
8. **Il venv NON ha pip** → installare con `uv pip install` (o attivare il venv e usare uv).
9. **`ToolResult.error()` riempie `error_message`, NON `content`** — i test sugli errori asserzionano
   `res.error_message`.
10. **Campi generati opzionali**: i tipi `ApiSchema` rendono OPZIONALI i campi con default backend →
    fallback `??` nei consumer, mai tipi a mano.
11. **Contratti WS**: regole 1b invariate (modello in ws_schema + vocabolario congelato + dispatcher FE esaustivo).
12. **`test_plugins_enabled_list` è ROSSO ereditato** (21 plugin reali vs 20 attesi, fallisce identico
    sulla base fase 4): non è una regressione delle fasi — aggiornare l'atteso quando si tocca test_config.
13. **import-linter**: lanciare dalla REPO ROOT (`./.venv/Scripts/lint-imports --config backend/pyproject.toml`);
    wildcard `*` = un livello, `**` = ricorsivo; ignore non-matchante = run fallito.

## Backlog (in fondo ai piani 1a/1b/2/3/4/5; voci fase 5 principali)

1. Migrazione dei consumer ai gruppi (`ctx.llm_service` → `ctx.inference.llm_service`) + fixture test.
2. Migrare i test LLM/registry dagli alias privati dei facade ai moduli → poi armonizzare l'ownership
   dello stato dei due facade (LLM tiene context-window, registry delega tutto).
3. Guardia anti-drift per `docs/flag-registry.md`; unificare `{fs_write, process_exec}` duplicata
   (permission_mode_policy vs permission_service); `usage_guidance_for` → prompt assembly (valutare).
4. `mcp.py`: tipizzare le route MCP (`response_model`) + burn-down ratchet residuo degli altri domini.
5. Ereditati (fasi 1-4): 500→503 search a embedding giù; `MemoryService.list` offset O(n);
   export conversazioni a modello; dedup closure broadcaster (`make_ws_broadcaster`).

## Decisioni utente registrate (non rilitigare)

- Refactor incrementale, app sempre funzionante; dati azzerabili (no migrazioni); orb-era UI da eliminare
  (Horizon unica superficie); codegen completo; visione = runtime agentico locale con Command Layer
  (invariante anti-escalation non negoziabile, spec §7).
- I branch di fase restano NON mergiati e NON pushati finché l'utente non decide diversamente; si impilano
  (5 sopra 4 sopra 3 sopra 2 sopra 1b sopra 1a).
