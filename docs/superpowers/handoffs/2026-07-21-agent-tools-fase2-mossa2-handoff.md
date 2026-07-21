# Handoff — Fase 2 (Fondamenta tool), Mossa 2 COMPLETA (feat/agent-tools-fase2)

**Data:** 2026-07-21
**Branch:** `feat/agent-tools-fase2`, HEAD di chiusura `4712463` (~30 commit di mossa sopra
`a852750`, chiusura Mossa 1). Il branch resta **discendente** di `feat/agent-engine-fase1`
(congelato @ `72d5a5c`): il merge di Fase 1 resta pulito.
**Stato programma:** Fase 2 di 9 — Mossa 2 (wire/FE/vision) COMPLETA, gate automatici TUTTI
VERDI. La fase NON è ancora chiusa: restano i **due gate-utente** (sotto).
**Piano:** `docs/superpowers/plans/2026-07-20-agent-v2-fase2-mossa2.md` (20 task; T1-T18 e T20
eseguiti; T19 in attesa di OK utente).
**Spec di fase:** `docs/superpowers/specs/2026-07-18-agent-v2-fase2-fondamenta-tool-design.md`
**Ledger locale:** `.superpowers/sdd/progress.md`, sezione "FASE 2 - FONDAMENTA TOOL, MOSSA 2"
(con i "perché" di ogni scelta e le scoperte delle review, blocco per blocco).

## GATE-UTENTE PENDENTI (la fase chiude solo con questi)

1. **Smoke manuale su Horizon** (gate di fase spec §9.6): un edit con diff preview + conferma;
   un tool MCP annotato e uno non annotato in strict (badge origine + avviso fallback); un
   grep/glob; uno screenshot con immagine nel fold e — se il modello attivo è vision — la
   descrizione corretta del contenuto.
2. **Eval a pagamento di chiusura fase** (T19): SOLO con OK esplicito dell'utente.
   `python -m backend.evals run --baseline docs/superpowers/evals/20260718-121940-baseline-fase1/report.json`
   (venv assoluto, API key OpenRouter, modello pinnato z-ai/glm-5.2). Criterio: nessuna
   REGRESSIONE; `fs-edit-exact-01`/`fs-glob-01`/`fs-grep-01` compariranno come NUOVO e devono
   passare. Salvare e committare il report sotto `docs/superpowers/evals/`.
3. Il **merge di Fase 1** resta pendente (smoke 2 provider-saturo + OK utente;
   `finishing-a-development-branch` su `feat/agent-engine-fase1`, poi la Fase 2 segue).

## Cosa è stato costruito (per blocco, con le scoperte di review)

### A — tool_meta sul wire (T1-T5)
- `McpToolMeta` su `ToolDefinition` (`core/plugin_models.py`): PROVENIENZA delle annotations
  (server/annotated/trusted/read_only/destructive), None per i nativi. SEMANTICA PINNATA:
  meta = provenienza, gate = autorità — divergono nel fail-closed `path_args` (test dedicato).
  Costruzione DRY post-branch in `map_mcp_tool` (annotated/trusted veri per costruzione).
- `GateVerdict.tool_meta` (`ToolMetaInfo` in ports.py, origin `Literal`) popolato da
  `_tool_meta_from` nell'adapter permessi; payload evento con chiave SEMPRE presente;
  `WsToolMeta` sul frame `interaction.requested` (rituale contratti completo, pin di simmetria
  `model_fields == as_payload()`). **Gotcha pinnato**: `exclude_none` è RICORSIVO — le
  sotto-chiavi None sono omesse dal frame (FE: assente == null == unknown).
- FE: badge `MCP · <server>` + avviso fallback nel dialogo. **Review fix**: due messaggi
  distinti — "Tool non annotato: trattato come distruttivo" (annotated=false) e "Annotazioni
  non attendibili: trattato come distruttivo" (trusted=false) — la dicitura unica di spec
  era FALSA per il caso annotated=true+trusted=false (deviazione motivata, nel commit).

### B — diff preview (T6-T7)
- `editDiff.ts`: LCS DP a suffissi (righe già in ordine, niente reverse), cap 400 righe con
  fallback removed-poi-added; tie-break `>=` documentato (load-bearing); boundary test 400/401.
- `toolConfirmationView.ts`: view-model a 3 rami (diff / write-preview troncata onesta /
  args JSON invariato), suffix-match sui tool name, guardie typeof strette. I computed del
  dialogo di T5 sono MIGRATI qui e testati (10 boundary test). A11y: blocchi scrollabili
  focusabili (tabindex).

### C — catalogo tool (T8-T9)
- Entry di `get_tool_catalog()` estese (additive): `risk_level`/`requires_confirmation`/
  `mcp_server`. Route nuova `GET /api/tools/catalog` tipizzata (`RiskLevel` condiviso da
  ws_schema); `get_tool_catalog` aggiunto a `ToolRegistryProtocol` (fix mypy pre-esistente).
- FE: `toolsApi` + picker/autocomplete in `PermissionRulesManager.vue` (`filterCatalog`
  prefix-first + `moveHighlight` con wrap, a11y base, fallback free-text se catalogo giù).
  **Follow-up tracciato** (spawn_task): pattern ARIA combobox completo (richiede passthrough
  attributi in UiInput).

### D — pannello MCP (T10-T11)
- Route `/api/mcp/*` tipizzate con VOCABOLARI CHIUSI (`McpTransport`, `McpServerStatus` a 6
  valori, reconnect `Literal["connected"]`); livello per-tool derivato dalla PROVENIENZA
  (`_tool_level`: read_only/write/fallback — il path_args-promoted resta read_only); 3 righe
  rimosse dalla baseline ratchet. **Scoperta**: la union hand-written FE era INCOMPLETA
  (mancavano unknown/degraded) e il buco era RUNTIME (default che ingoiava) — ora
  `types/mcp.ts` deriva da ApiSchema e `statusLabel` è switch esaustivo compile-enforced.
- `McpManager.vue`: badge trust per-server (read-only), livello per-tool con label corta +
  tooltip completo (risk localizzato), `mcpToolLevel.ts` testato. **Review fix**: opacity
  tolta dalla label di sicurezza (contrasto light ~1.5:1); **follow-up tracciato**
  (spawn_task): varianti light dei tre state color in theme.css.

### E — consegna vision (T12-T17)
- `ToolImage` su `ToolExecutionOutput.images` (popolato SOLO su success dalla guardia
  anti-context-bomb; placeholder invariato in content; invariante dichiarata e
  self-enforcing anche nel motore con filtro `output.ok`).
- `LLMPort.supports_vision()` (porta sync; doubles/shim/scripted censiti e pronti).
- Engine: passo "4-ter" in `_run_tool_step` — UN messaggio user multimodale (data URL) dopo
  tutti i tool message del batch, SOLO in working history (mai persistito), cap per-TURNO
  (`agent.vision.max_images_per_turn`, contatore su `_TurnState`); config `agent.vision.*`
  censita, wiring nel runner (ctor unico WS+headless).
- **BUG REALE trovato da T15**: `ContextManager.compress` faceva `.startswith` sul content →
  `AttributeError` su content-list → con vision in history la compaction falliva SEMPRE
  (fail-open silenzioso). Fix: strip degli image part nell'adapter PRIMA del summarizer
  (marker testuale; contratto: le immagini non sopravvivono alla compaction) + guardia
  difensiva content-str upstream. La stima token multimodale era GIA' gestita (flat 765/img,
  pinnata).
- Artifact `IMAGE`: `create_image_artifact` (blob atomico via `ArtifactBlobStore.write_bytes`,
  filename == row id, fail-safe su base64 invalido), ramo images prima del payload in
  `register_artifacts`; `GET /api/artifacts/{id}/download` serve il kind nuovo senza
  modifiche (test end-to-end). FE: `toolImageUrl` + img nei due rami del nodo tool di
  `ReasoningThread.vue` (@error nasconde, Set per executionId con clear a run nuovo).

### Gate finale (T18) — tutti verdi su HEAD `4712463`
pytest: 333 (agent/evals/contracts) + 137 (MCP/registry) + 169 (artifacts/context/config/
settings) = **639 passed**; ruff 0; lint-imports 6/6; mypy 4445 = baseline (nel percorso
della mossa il conteggio è pure SCESO di 3 per fix di pre-esistenti); check-contracts
"up to date"; FE typecheck/lint verdi; vitest FE **462/462**.
**Due BLOCKED intermedi, stessa causa**: `ArtifactKind.IMAGE` (T16) affiora nell'enum
OpenAPI ma la rigenerazione contratti non era stata fatta → drift artifacts (fix `604bdba`)
e poi due `Record<ArtifactKind,…>` FE non esaustivi, di cui uno era un BUG RUNTIME (il
bucket `byKind` scartava silenziosamente gli artifact image — fix `4712463`).
LEZIONE: un membro nuovo in un enum DB-side che affiora nell'OpenAPI richiede il rituale
contratti completo come un campo wire.

## DEBITO CENSITO (nuovo di mossa — si somma ai handoff precedenti)

1. **Reidratazione vision cross-turn**: il modello vede l'immagine solo nel turno del tool;
   dopo, resta il placeholder. L'artifact IMAGE è la fonte per una futura reidratazione
   on-demand (leggere il blob e re-iniettare) — non in scope.
2. **Immagini e compaction**: strip deliberato (contratto); costo stimato flat 765/img.
3. **Una sola immagine per tool result** registrata come artifact (`images[0]`, warning se
   più); coerente con `ToolActivity.artifactId` scalare.
4. **`_atomic_publish` comune ai due writer del blob store**: la logica tmp+replace è
   duplicata (JSON e bytes) e il cleanup del tmp su eccezione manca in ENTRAMBI — da fare
   insieme, non solo sul writer nuovo.
5. **ARIA combobox completo del picker** e **varianti light degli state color**: tracciati
   come task separati (spawn_task in sessione).
6. I debiti di Mossa 1 e Fase 1 restano invariati (arg-lista nel gate, executor cancellabile
   per search/glob/grep, chiavi pc_automation non cablate, infra test WS/REST Windows).

## Gotcha di sessione (i vecchi restano validi; nuovi:)

1. **Enum DB-side che affiora nell'OpenAPI = contratto**: `ArtifactKind` è nei componenti
   generati; aggiungere un membro senza gen-contracts + typecheck FE lascia drift latente
   che esplode solo al gate (e un `Record` esaustivo FE può nascondere un bug runtime).
2. **`exclude_none` ricorsivo sul wire**: le sotto-chiavi None dei sub-object sono omesse
   dal frame — lato TS assente == null; pinnato nei test wire.
3. **Vitest FE gira in node SENZA plugin SFC**: mai montare/importare .vue nei test — logica
   estratta in moduli .ts accanto al componente (pattern consolidato in questa mossa).
4. **Gate 4 lento**: `test_config.py` + `test_settings.py` da soli ~12 min (montano l'app);
   spezzare i batch pytest per stare nei timeout, sempre foreground sequenziale.
5. **Review = trova-difetti, confermato**: in questa mossa hanno trovato un messaggio UI
   fattualmente falso (trusted=false), una union FE incompleta con buco runtime, un bug
   compaction reale, un filtro ok mancante nel motore, blob filename disallineato dall'id
   row, contrasto illeggibile in light. Budget-are le review come lavoro vero anche in Fase 3.
6. Macchina (VITALI, invariati): venv path assoluto; pytest da backend/, foreground, mai
   concorrenti, mai suite integrale; EOL per-FILE (verificare prima di editare);
   check-contracts con `powershell -File` per evitare l'exit-1 fantasma PS 5.1.

## Prossima sessione (delega)

1. Chiedere all'utente: smoke Horizon (punto 1 sopra) e OK per l'eval a pagamento (punto 2).
   Con l'esito: eventuale fix da smoke → re-gate mirato; report eval committato; POI la fase
   si dichiara chiusa (aggiornare la sezione Fase 2 del programma se serve).
2. Se l'utente dà l'OK al merge di Fase 1: `finishing-a-development-branch` su
   `feat/agent-engine-fase1`, poi decidere con l'utente la via per la Fase 2 (lo stesso
   flusso, essendo discendente).
3. Fase 3 (dal programma): prompting/guidance comportamentale e guardie anti-degenerazione
   DENTRO l'engine — leggere prima questo handoff, il ledger e la spec di programma.
4. Principi NON negoziabili invariati: pilastro, contratti generati, TDD col rosso
   verificato, review indipendente doppia per task, eval solo con OK, un solo implementer
   alla volta.
