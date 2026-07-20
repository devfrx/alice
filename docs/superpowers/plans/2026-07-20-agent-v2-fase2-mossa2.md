# Agent v2 — Fase 2, Mossa 2: wire/FE/vision/chiusura fase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** chiudere la Fase 2 consegnando la superficie wire/frontend dei tool (tool_meta sul
dialogo di conferma, diff preview degli edit, picker del catalogo tool, pannello MCP tipizzato)
e la consegna vision delle immagini al modello + rendering FE, poi i gate di chiusura fase
(eval a pagamento SOLO con OK utente, docs, handoff).

**Architecture:** il dato di provenienza MCP (server, annotations, trust) oggi muore dentro
`map_mcp_tool`; lo si conserva strutturato su `ToolDefinition` (`McpToolMeta`) e da lì fluisce a
TRE consumatori: il gate → `GateVerdict.tool_meta` → payload evento → frame WS (Blocco A), il
nuovo `GET /api/tools/catalog` (Blocco C), le route `/api/mcp/*` tipizzate (Blocco D). La vision
usa il campo `ToolExecutionOutput.images` (esiste, mai popolato): l'adapter execution lo popola
mentre il placeholder resta in `content`; l'engine inietta un messaggio user multimodale
(data-URL) gated da `LLMPort.supports_vision` + config `agent.vision.*`; la persistenza FE passa
dagli **artifact** (kind `IMAGE`, servito da `GET /api/artifacts/{id}/download` già esistente),
MAI base64 nei frame WS. Ogni tocco al wire segue il rituale contratti: ws_schema → frozen test
→ gen-contracts → tipi generati (MAI tipi TS a mano).

**Tech Stack:** Python 3.13 (FastAPI, Pydantic, SQLModel, dataclasses frozen), TypeScript/Vue 3
Composition API, Pinia, vitest (node env, NO mount SFC), openapi-typescript.

---

## Vincoli di esecuzione (NON negoziabili, dal handoff Mossa 1)

- **venv SEMPRE con path assoluto**: `& "C:\Users\Jays\Desktop\alice\alice\.venv\Scripts\Activate.ps1"`.
- **pytest SEMPRE da `backend/`, foreground, MAI concorrenti, MAI suite integrale** (AUD-008).
  Per gli hang: `-o faulthandler_timeout=120`.
- **TDD col rosso verificato**: ogni test nuovo va eseguito e visto FALLIRE prima
  dell'implementazione.
- **EOL per-FILE**: prima di editare un file verificarne gli EOL e preservarli
  (`file_search/plugin.py` e `searcher.py` sono CRLF; `readers.py`/`read_tracker.py`/`grep.py`
  LF). Per scrivere file lunghi usare i tool file (Write/Edit), MAI here-string/Add-Content.
- **check-contracts**: un exit 1 con output DEBUG su stderr può essere il NativeCommandError
  di PS 5.1, non un drift — rilanciare con `powershell -File scripts\check-contracts.ps1` e
  leggere l'output vero.
- **mypy a parità per task** (stash round-trip: contare gli errori prima e dopo).
- **Un solo implementer alla volta sul working tree**; review doppia (spec + quality)
  indipendente PER task, trattata come trova-difetti.
- **Frontend**: `npm run typecheck` e `npm run lint` (da `frontend/`) prima di chiudere ogni
  task FE. I file in `types/generated/` si rigenerano con `.\scripts\gen-contracts.ps1`, mai a
  mano (eccetto `generated/index.ts`).
- **Eval a pagamento SOLO con OK esplicito dell'utente** (Task 19).

## Decisioni architetturali (con il perché)

1. **`McpToolMeta` su `ToolDefinition`** (non derivazione a valle): il caso "non annotato →
   fallback" è indistinguibile da "write destructive annotato" guardando solo
   capabilities/risk (`mcp_tool_mapping.py` consuma le annotations e le scarta). Conservarle
   strutturate al punto di mapping è l'unica via non-lossy; `dataclasses.replace` in
   `mcp_client/plugin.py:214-221` le preserva gratis nel re-namespacing. Serve i Blocchi A, C, D
   con UNA modifica.
2. **Vision via messaggio user multimodale iniettato** (non content-parts nel messaggio tool):
   il formato OpenAI-compatible non garantisce image parts nei messaggi `role:tool`; il pattern
   robusto cross-provider (LM Studio/Ollama/OpenRouter) è placeholder testuale nel tool message
   + messaggio `role:user` con `image_url` data-URL subito dopo il batch. Gated da
   `LLMPort.supports_vision` (nuovo metodo di porta, implementato da `LLMService.supports_vision`
   già esistente) e da `agent.vision.enabled`.
3. **Consegna FE via artifact, non base64 sul WS**: `artifact_id` + `content_type` sono GIÀ
   threaded end-to-end (`ToolResultEvent` → `WsTurnToolResult` → `ToolActivity`); il binario lo
   serve `GET /api/artifacts/{id}/download` (FileResponse col MIME). Si aggiunge
   `ArtifactKind.IMAGE` + un metodo registry che scrive il blob. Zero frame WS nuovi.
4. **Scope vision = in-turn**: l'immagine è visibile al modello nel turno in cui il tool gira
   (caso d'uso: screenshot → descrivi). Il messaggio iniettato NON è persistito (la working
   history del turno vive in memoria; `load_history` ricostruisce dal DB il placeholder).
   La **reidratazione cross-turn dall'artifact è debito censito** di questa mossa, non scope.
5. **`GET /api/tools/catalog` come route nuova** (`api/routes/tools.py`), che riusa
   `ToolCatalog.get_tool_catalog()` esteso con `risk_level`/`requires_confirmation`/`mcp_server`
   (chiavi additive: `settings._build_tool_catalog` legge chiavi esplicite, non si rompe).
   L'endpoint `/api/settings/tool-catalog` resta la superficie enable/disable; il nuovo è la
   superficie flat per picker/regole.
6. **Compaction e immagini**: le immagini inline NON sopravvivono alla compaction (contratto
   esplicito): l'adapter context le sostituisce con un marker testuale PRIMA di passare i
   messaggi al compressore (che usa un LLM potenzialmente non-vision), e la stima token tratta
   ogni image part come costante (1000 token) per non far esplodere il conteggio sul base64.

## Ordine e dipendenze

Blocco A (T1→T5) prima di C (T8 usa `mcp_server`) e D (T10 usa `McpToolMeta`). B (T6-T7) dipende
solo da T4-T5. E (T12→T17) indipendente da A/C/D ma T16 tocca `adapters/db.py` — eseguirlo dopo
T12. Chiusura T18→T20 per ultima. Ogni task = 1+ commit; gate del task nel task.

---

### Task 1: `McpToolMeta` su `ToolDefinition` + popolamento in `map_mcp_tool`

**Files:**
- Modify: `backend/core/plugin_models.py` (dopo la definizione di `ToolDefinition` o prima, come dataclass sorella)
- Modify: `backend/services/mcp_tool_mapping.py`
- Test: `backend/tests/test_mcp_tool_mapping.py`, `backend/tests/test_mcp_client_plugin.py`

- [ ] **Step 1.1: test rossi sul mapping** — in `backend/tests/test_mcp_tool_mapping.py`
  (riusare gli helper esistenti del file per costruire `Tool`/`McpServerConfig`):

```python
from backend.core.plugin_models import McpToolMeta

def test_read_only_tool_carries_mcp_meta() -> None:
    td = map_mcp_tool(_tool_with_annotations(readOnlyHint=True), _server(name="files"))
    assert td.mcp == McpToolMeta(
        server="files", annotated=True, trusted=True, read_only=True, destructive=False,
    )

def test_write_tool_meta_destructive_flag() -> None:
    td = map_mcp_tool(_tool_with_annotations(readOnlyHint=False, destructiveHint=False), _server())
    assert td.mcp is not None and td.mcp.destructive is False and td.mcp.read_only is False

def test_unannotated_tool_meta_marks_fallback() -> None:
    td = map_mcp_tool(_tool_without_annotations(), _server(name="files"))
    assert td.mcp == McpToolMeta(
        server="files", annotated=False, trusted=True, read_only=False, destructive=None,
    )

def test_untrusted_server_meta_marks_untrusted() -> None:
    server = _server(trust_annotations=False)
    td = map_mcp_tool(_tool_with_annotations(readOnlyHint=True), server)
    assert td.mcp is not None
    assert td.mcp.annotated is True and td.mcp.trusted is False
    # e il gate resta al fallback conservativo (invariante Mossa 1, non cambia):
    assert td.risk_level == "dangerous" and td.requires_confirmation is True

def test_path_args_promotion_keeps_mcp_meta() -> None:
    # il tool promosso a fs_read/fs_write NON perde la provenienza MCP
    td = map_mcp_tool(<tool read-only con path_args validi>, <server con path_args>)
    assert td.capabilities == ("fs_read",) and td.mcp is not None and td.mcp.read_only is True
```

  E in `backend/tests/test_mcp_client_plugin.py` (pin del re-namespacing):

```python
def test_get_tools_preserves_mcp_meta() -> None:
    # riusare il setup esistente del file che esercita get_tools()
    assert all(t.mcp is not None and t.mcp.server for t in mcp_tools)
```

- [ ] **Step 1.2: verificare il rosso**
  `cd backend; pytest tests/test_mcp_tool_mapping.py tests/test_mcp_client_plugin.py -v`
  Atteso: FAIL con `ImportError: cannot import name 'McpToolMeta'`.

- [ ] **Step 1.3: implementazione** — in `backend/core/plugin_models.py`:

```python
@dataclass(frozen=True, slots=True)
class McpToolMeta:
    """Provenienza MCP di un tool (``None`` su ``ToolDefinition`` per i tool nativi).

    Conserva ciò che ``map_mcp_tool`` altrimenti consuma e scarta: serve al
    dialogo di conferma (trasparenza sul fallback), al catalogo tool e al
    pannello MCP. ``destructive`` è ``None`` quando le annotations mancano o
    il server non è fidato (fallback conservativo).
    """

    server: str
    annotated: bool
    trusted: bool
    read_only: bool
    destructive: bool | None
```

  Su `ToolDefinition` aggiungere il campo (in coda, con default):
  `mcp: McpToolMeta | None = None`.

  In `backend/services/mcp_tool_mapping.py`, nei tre rami esistenti (righe 54-70), costruire il
  meta e passarlo al `ToolDefinition(...)` finale (riga 102-112):

```python
if annotations is not None and annotations.readOnlyHint is True:
    ...
    meta = McpToolMeta(server=server.name, annotated=True, trusted=True,
                       read_only=True, destructive=False)
elif annotations is not None:
    ...
    meta = McpToolMeta(server=server.name, annotated=True, trusted=True,
                       read_only=False, destructive=destructive)
else:
    ...
    meta = McpToolMeta(server=server.name, annotated=tool.annotations is not None,
                       trusted=server.trust_annotations, read_only=False, destructive=None)
```

  NB: nel ramo fallback `annotations` è già azzerato da `trust_annotations=False` — per
  distinguere "senza annotations" da "untrusted" usare `tool.annotations` originale come sopra.
  La promozione `path_args` NON tocca `meta`.

- [ ] **Step 1.4: verde + gate**
  `pytest tests/test_mcp_tool_mapping.py tests/test_mcp_client_plugin.py tests/test_mcp_session.py tests/test_permission_mcp_perimeter.py -v` → tutti PASS.
  `ruff check .` = 0; mypy a parità (stash round-trip).

- [ ] **Step 1.5: commit**
  `git commit -m "feat(mcp): McpToolMeta su ToolDefinition - provenienza server/annotations conservata dal mapping"`

### Task 2: `GateVerdict.tool_meta` + popolamento nell'adapter permessi

**Files:**
- Modify: `backend/services/agent/ports.py` (accanto a `GateVerdict`, righe 81-89)
- Modify: `backend/services/agent/adapters/permission.py` (righe 99-127)
- Test: `backend/tests/agent/test_adapter_permission.py`

- [ ] **Step 2.1: test rossi** — nel file test adapter permessi (riusare le fixture esistenti
  che costruiscono l'adapter con un registry finto):

```python
def test_verdict_tool_meta_native() -> None:
    # tool nativo noto: origin native, campi MCP a None
    verdict = <decide su tool nativo con ToolDefinition senza .mcp>
    assert verdict.tool_meta is not None
    assert verdict.tool_meta.origin == "native" and verdict.tool_meta.server is None

def test_verdict_tool_meta_mcp() -> None:
    # ToolDefinition con mcp=McpToolMeta(server="files", annotated=False, trusted=True, ...)
    verdict = <decide su tool MCP fallback>
    tm = verdict.tool_meta
    assert tm is not None and tm.origin == "mcp" and tm.server == "files"
    assert tm.annotated is False and tm.destructive is None

def test_verdict_tool_meta_unknown_tool_is_none() -> None:
    verdict = <decide su tool sconosciuto al registry>
    assert verdict.tool_meta is None
```

- [ ] **Step 2.2: rosso verificato** — `pytest tests/agent/test_adapter_permission.py -v` → FAIL.

- [ ] **Step 2.3: implementazione** — in `ports.py`:

```python
@dataclass(frozen=True, slots=True)
class ToolMetaInfo:
    """Provenienza del tool per il dialogo di conferma (wire ``tool_meta``)."""

    origin: str  # "native" | "mcp"
    server: str | None = None
    annotated: bool | None = None
    read_only: bool | None = None
    destructive: bool | None = None
    trusted: bool | None = None

    def as_payload(self) -> dict[str, Any]:
        """Forma dict per il payload evento (chiavi = contratto wire)."""
        return {
            "origin": self.origin, "server": self.server,
            "annotated": self.annotated, "read_only": self.read_only,
            "destructive": self.destructive, "trusted": self.trusted,
        }
```

  `GateVerdict` guadagna `tool_meta: ToolMetaInfo | None = None`.
  In `adapters/permission.py`, dove oggi si copiano `risk_level`/`description` dalla
  `ToolDefinition` (righe 125-126):

```python
tool_meta: ToolMetaInfo | None = None
if tool_def is not None:
    m = tool_def.mcp
    if m is not None:
        tool_meta = ToolMetaInfo(origin="mcp", server=m.server, annotated=m.annotated,
                                 read_only=m.read_only, destructive=m.destructive,
                                 trusted=m.trusted)
    else:
        tool_meta = ToolMetaInfo(origin="native")
```

- [ ] **Step 2.4: verde + gate** — suite adapter + `ruff` + mypy parità.
- [ ] **Step 2.5: commit** — `feat(agent): GateVerdict.tool_meta - provenienza tool dal gate al motore`

### Task 3: payload `tool_meta` nell'evento `interaction.requested`

**Files:**
- Modify: `backend/services/agent/engine.py` (`_confirm_call`, payload righe 724-734)
- Modify: `backend/services/agent/events.py` (docstring chiavi payload, righe 98-104)
- Test: `backend/tests/agent/test_engine_tools.py` (flusso confirm già testato lì); `backend/tests/agent/doubles.py` se il double del gate va esteso

- [ ] **Step 3.1: test rosso** — il double `PermissionPort` in `doubles.py` deve poter
  ritornare un `GateVerdict` con `tool_meta`; test:

```python
async def test_confirm_event_payload_carries_tool_meta() -> None:
    # gate double: CONFIRM con tool_meta=ToolMetaInfo(origin="mcp", server="files",
    #              annotated=False, trusted=True, read_only=False, destructive=None)
    <esegui un turno con una tool call confermata, raccogli gli eventi emessi>
    req = <primo InteractionRequestedEvent>
    assert req.payload["tool_meta"] == {
        "origin": "mcp", "server": "files", "annotated": False,
        "read_only": False, "destructive": None, "trusted": True,
    }

async def test_confirm_event_payload_tool_meta_none_when_absent() -> None:
    # verdict senza tool_meta -> chiave presente con valore None (il translator la scarta)
    assert req.payload["tool_meta"] is None
```

- [ ] **Step 3.2: rosso verificato**, poi implementazione in `_confirm_call`:

```python
payload={
    "args": call.args,
    "risk_level": verdict.risk_level,
    "description": verdict.description,
    "reasoning": verdict.reason,
    "allow_remember": True,
    "tool_meta": verdict.tool_meta.as_payload() if verdict.tool_meta else None,
},
```

  Aggiornare la docstring di `InteractionRequestedEvent` (chiave `tool_meta` per kind confirm).

- [ ] **Step 3.3: verde** — `pytest tests/agent/ -v` (intera dir agent, è la suite di mossa).
- [ ] **Step 3.4: commit** — `feat(agent): tool_meta nel payload di interaction.requested (kind confirm)`

### Task 4: contratto wire — `WsToolMeta` su `WsInteractionRequested` (rituale completo)

**Files:**
- Modify: `backend/api/ws_schema/chat.py` (sub-object accanto a `WsAskUserQuestion`, righe 63-72; campo su `WsInteractionRequested`, riga 179)
- Modify: `backend/api/ws_schema/wire.py` (ramo righe 114-135)
- Test: `backend/tests/contracts/test_ws_schema_chat.py` (frame rappresentativo), `backend/tests/contracts/test_wire.py` (value-pinned)
- Generated: `frontend/src/renderer/src/types/generated/openapi.json`, `api.d.ts` (via script, MAI a mano)

- [ ] **Step 4.1: test rossi.** In `test_ws_schema_chat.py` aggiungere a
  `REPRESENTATIVE_SERVER_FRAMES` un frame `interaction.requested` con `tool_meta` completo:

```python
{
    "type": "interaction.requested", "origin": "agent",
    "turn_id": "t1", "interaction_id": "i1", "execution_id": "c1",
    "kind": "tool_confirmation", "tool_name": "mcp_client_mcp_files_write_file",
    "args": {"path": "x.txt"}, "risk_level": "dangerous",
    "description": "[files] Write file", "allow_remember": True,
    "tool_meta": {"origin": "mcp", "server": "files", "annotated": False,
                  "read_only": False, "destructive": None, "trusted": True},
},
```

  In `test_wire.py` un nuovo value-pinned (accanto a
  `test_interaction_requested_confirm_value_pinned`, riga 135) che costruisce
  `InteractionRequestedEvent` con `payload["tool_meta"]` e pinna il dict wire completo,
  incluso che `tool_meta` con valore `None` NON compare (exclude_none). Il vocabolario
  frozen (`EXPECTED_CHAT_SERVER_TYPES`) NON cambia: nessun type nuovo.

- [ ] **Step 4.2: rosso verificato** — `pytest tests/contracts/ -v` → FAIL (extra field
  `tool_meta` rifiutato da `extra="forbid"`).

- [ ] **Step 4.3: implementazione.** In `chat.py`, sezione shared sub-objects:

```python
class WsToolMeta(BaseModel):
    """Provenienza del tool nel dialogo di conferma (spec Fase 2 §6.1)."""

    model_config = ConfigDict(extra="forbid")

    origin: Literal["native", "mcp"]
    server: str | None = None
    annotated: bool | None = None
    read_only: bool | None = None
    destructive: bool | None = None
    trusted: bool | None = None
```

  Su `WsInteractionRequested`: `tool_meta: WsToolMeta | None = None`.
  In `wire.py`, nel ramo `InteractionRequestedEvent`: `tool_meta=payload.get("tool_meta"),`
  (Pydantic valida il dict per-costruzione; un dict malformato DEVE far fallire la
  costruzione del frame, non passare — è il contratto by-construction).

- [ ] **Step 4.4: verde contratti** — `pytest tests/contracts/ tests/agent/ -v` → PASS.
- [ ] **Step 4.5: rigenerare gli artifacts** —
  `powershell -File scripts\gen-contracts.ps1` poi `powershell -File scripts\check-contracts.ps1`
  (attenzione al falso exit 1 PS 5.1). Verificare col diff che `api.d.ts` contenga `WsToolMeta`.
- [ ] **Step 4.6: commit** (sorgenti + artifacts generati insieme) —
  `feat(contracts): tool_meta su interaction.requested (WsToolMeta, wire + artifacts rigenerati)`

### Task 5: FE — tool_meta nello store e badge nel dialogo di conferma

**Files:**
- Modify: `frontend/src/renderer/src/types/turn.ts` (`InteractionActivity`, righe 86-109), `frontend/src/renderer/src/types/chat.ts` (`ConfirmationRequest`, righe 260-277)
- Modify: `frontend/src/renderer/src/stores/agentRun.ts` (`applyInteractionRequested` righe 276-295, `pendingConfirmations` righe 95-110)
- Modify: `frontend/src/renderer/src/components/chat/ToolConfirmationDialog.vue`
- Test: `frontend/src/renderer/src/stores/agentRun.spec.ts`

- [ ] **Step 5.1: tipi.** In `turn.ts`: `export type ToolMeta = NonNullable<WsInteractionRequestedMessage['tool_meta']>`
  (derivato dal generato — MAI ridefinito a mano); su `InteractionActivity`: `toolMeta?: ToolMeta`.
  In `chat.ts` su `ConfirmationRequest`: `toolMeta?: ToolMeta` (import dal turn.ts).
- [ ] **Step 5.2: test rosso store** — in `agentRun.spec.ts` (helper `interactionRequested`
  esistente, righe 393-400):

```ts
it('propaga tool_meta fino a pendingConfirmations', () => {
  store.applyInteractionRequested(interactionRequested('t1', 'x1', {
    args: { path: 'x' }, risk_level: 'dangerous',
    tool_meta: { origin: 'mcp', server: 'files', annotated: false,
                 read_only: false, destructive: null, trusted: true },
  }) as never)
  expect(store.pendingConfirmations[0].toolMeta?.server).toBe('files')
  expect(store.pendingConfirmations[0].toolMeta?.annotated).toBe(false)
})
```

  `npx vitest run src/renderer/src/stores/agentRun.spec.ts` → FAIL.
- [ ] **Step 5.3: store** — copiare `toolMeta: msg.tool_meta ?? undefined` in
  `applyInteractionRequested` e proiettarlo in `pendingConfirmations` → verde.
- [ ] **Step 5.4: dialogo.** In `ToolConfirmationDialog.vue` (dopo il badge toolName,
  righe 133-141): badge origine quando `confirmation.toolMeta?.origin === 'mcp'`
  (`MCP · {{ toolMeta.server }}`, stile `UiBadge` esistente) e, quando
  `toolMeta.annotated === false || toolMeta.trusted === false`, riga di trasparenza:
  `Tool non annotato: trattato come distruttivo` (variante warning; testo esatto dalla spec
  §6.1). Nessuna logica nel template oltre a `computed` locali.
- [ ] **Step 5.5: gate FE** — `npm run typecheck; npm run lint; npx vitest run` → verdi.
- [ ] **Step 5.6: commit** — `feat(fe): badge origine MCP e avviso fallback nel dialogo di conferma`

### Task 6: `editDiff.ts` — diff a righe pure-TS (modulo testabile)

**Files:**
- Create: `frontend/src/renderer/src/components/chat/editDiff.ts`
- Test: `frontend/src/renderer/src/components/chat/editDiff.spec.ts`

- [ ] **Step 6.1: test rossi** (vitest node, nessun mount):

```ts
import { computeLineDiff } from './editDiff'

it('righe identiche -> context', () => {
  expect(computeLineDiff('a\nb', 'a\nb')).toEqual([
    { kind: 'context', text: 'a' }, { kind: 'context', text: 'b' },
  ])
})
it('modifica una riga -> removed+added contigue', () => {
  expect(computeLineDiff('a\nold\nc', 'a\nnew\nc')).toEqual([
    { kind: 'context', text: 'a' },
    { kind: 'removed', text: 'old' }, { kind: 'added', text: 'new' },
    { kind: 'context', text: 'c' },
  ])
})
it('CRLF normalizzati prima del confronto', () => {
  expect(computeLineDiff('a\r\nb', 'a\nb')).toEqual([
    { kind: 'context', text: 'a' }, { kind: 'context', text: 'b' },
  ])
})
it('oltre il cap righe degrada a blocchi pieni removed/added', () => {
  const big = Array.from({ length: 500 }, (_, i) => `r${i}`).join('\n')
  const rows = computeLineDiff(big, big + '\nx')
  expect(rows.some((r) => r.kind === 'removed')).toBe(true) // fallback, non LCS
})
```

- [ ] **Step 6.2: rosso**, poi implementazione: LCS DP sulle righe (normalizzazione `\r\n`→`\n`
  prima dello split), cap `MAX_LCS_LINES = 400` per lato — oltre, fallback onesto: tutte le
  righe old come `removed` seguite dalle new come `added` (niente O(n²) su input enormi).

```ts
export interface DiffRow { kind: 'context' | 'removed' | 'added'; text: string }
export function computeLineDiff(oldStr: string, newStr: string): DiffRow[] { ... }
```

- [ ] **Step 6.3: verde + commit** — `feat(fe): computeLineDiff - diff a righe per la preview degli edit`

### Task 7: diff preview nel dialogo di conferma (edit + write)

**Files:**
- Modify: `frontend/src/renderer/src/components/chat/ToolConfirmationDialog.vue` (rendering args, righe 158-161)
- Test: `frontend/src/renderer/src/components/chat/toolConfirmationView.spec.ts` (nuovo, logica estratta)

- [ ] **Step 7.1: estrarre la logica di presentazione** in
  `frontend/src/renderer/src/components/chat/toolConfirmationView.ts`:

```ts
export type ConfirmationBody =
  | { mode: 'diff'; path: string; rows: DiffRow[]; replaceAll: boolean }
  | { mode: 'write-preview'; path: string; preview: string; truncated: boolean }
  | { mode: 'args'; json: string }

export function buildConfirmationBody(toolName: string, args: Record<string, unknown> | null): ConfirmationBody
```

  Regole: `toolName` che termina con `edit_text_file` e args con `old_string`/`new_string`
  stringhe → `diff` (path da `args.path`, `replaceAll` da `args.replace_all === true`);
  `write_text_file` con `content` stringa → `write-preview` con `preview` = prime 40 righe /
  2000 char (flag `truncated` onesto); altrimenti `args` con `JSON.stringify(args, null, 2)`
  (comportamento attuale). Test rossi per i tre rami + edge (args null, old_string mancante →
  fallback `args`).
- [ ] **Step 7.2: rosso → implementazione → verde** (`npx vitest run src/renderer/src/components/chat/`).
- [ ] **Step 7.3: template.** In `ToolConfirmationDialog.vue`: `computed(() => buildConfirmationBody(props.confirmation.toolName, props.confirmation.args))`;
  ramo `diff` → righe monospace con classi `diff-row--removed` (rosso) / `diff-row--added`
  (verde) / context, path in testata; ramo `write-preview` → `<pre>` troncata con nota; ramo
  `args` → rendering JSON attuale invariato. Scoped CSS coi token del tema (nessun colore
  hardcoded: usare le variabili già in uso nel componente).
- [ ] **Step 7.4: gate FE + commit** — `feat(fe): diff preview per edit_text_file e anteprima write nel dialogo di conferma`

### Task 8: catalogo arricchito + `GET /api/tools/catalog` (response_model)

**Files:**
- Modify: `backend/core/tools/catalog.py` (`get_tool_catalog`, righe 293-323)
- Create: `backend/api/routes/tools.py`
- Modify: `backend/api/routes/__init__.py` (import + include_router)
- Test: `backend/tests/test_tool_registry.py`, `backend/tests/contracts/test_response_models.py` (resta verde senza toccare la baseline), nuovo `backend/tests/test_tools_catalog_route.py`

- [ ] **Step 8.1: test rossi catalogo** — in `test_tool_registry.py`:

```python
def test_catalog_entries_carry_risk_and_confirmation() -> None:
    entry = <entry di un tool registrato con risk_level="dangerous", requires_confirmation=True>
    assert entry["risk_level"] == "dangerous"
    assert entry["requires_confirmation"] is True
    assert entry["mcp_server"] is None

def test_catalog_entry_mcp_server_from_meta() -> None:
    # tool con ToolDefinition.mcp=McpToolMeta(server="files", ...)
    assert entry["mcp_server"] == "files"
```

- [ ] **Step 8.2: rosso → implementazione**: in `catalog.py` estendere il dict entry (chiavi
  additive):

```python
catalog.append({
    "plugin": self._tool_to_plugin.get(ns_name, ""),
    "name": ns_name,
    "label": tool_def.name,
    "description": tool_def.description,
    "capabilities": list(tool_def.capabilities),
    "risk_level": tool_def.risk_level,
    "requires_confirmation": tool_def.requires_confirmation,
    "mcp_server": tool_def.mcp.server if tool_def.mcp is not None else None,
})
```

  → verde (anche `tests/test_app.py` e la suite settings: `_build_tool_catalog` legge chiavi
  esplicite, nessuna rottura attesa — verificarlo).
- [ ] **Step 8.3: test rosso route** — `backend/tests/test_tools_catalog_route.py` sul pattern
  dei test route esistenti (client di test su `create_app(testing=True)`; guardare
  `tests/test_artifacts_route.py` per il pattern):

```python
async def test_tools_catalog_shape() -> None:
    resp = await client.get("/api/tools/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["tools"], list)
    if body["tools"]:
        t = body["tools"][0]
        assert set(t) == {"name", "plugin", "label", "description", "capabilities",
                          "risk_level", "requires_confirmation", "mcp_server"}
```

- [ ] **Step 8.4: implementazione route** — `backend/api/routes/tools.py`:

```python
"""AL\\CE — Tool catalog REST surface (picker regole permessi, spec Fase 2 §6.3)."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.core.context import AppContext

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolCatalogEntry(BaseModel):
    """Descrittore flat di un tool del registry."""

    name: str
    plugin: str
    label: str
    description: str
    capabilities: list[str]
    risk_level: Literal["safe", "medium", "dangerous", "forbidden"]
    requires_confirmation: bool
    mcp_server: str | None = None


class ToolsCatalogResponse(BaseModel):
    """Catalogo completo dei tool registrati."""

    tools: list[ToolCatalogEntry]


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


@router.get("/catalog", response_model=ToolsCatalogResponse)
async def get_tools_catalog(request: Request) -> ToolsCatalogResponse:
    """Elenco flat dei tool registrati con livello di rischio e provenienza."""
    ctx = _ctx(request)
    entries: list[ToolCatalogEntry] = []
    if ctx.tool_registry is not None:
        entries = [ToolCatalogEntry(**e) for e in ctx.tool_registry.get_tool_catalog()]
    return ToolsCatalogResponse(tools=sorted(entries, key=lambda e: e.name))
```

  Registrare in `api/routes/__init__.py` (import + `router.include_router(tools_router)`).
- [ ] **Step 8.5: verde + ratchet** — `pytest tests/test_tools_catalog_route.py tests/test_tool_registry.py tests/contracts/ -v`
  (il ratchet resta verde da solo: la route nasce tipizzata, la baseline NON si tocca).
- [ ] **Step 8.6: commit** — `feat(api): GET /api/tools/catalog con response_model - catalogo flat per il picker`

### Task 9: FE — picker/autocomplete dei tool in `PermissionRulesManager`

**Files:**
- Generated: rigenerare contratti (nuovi schema `ToolCatalogEntry`/`ToolsCatalogResponse`)
- Create: `frontend/src/renderer/src/services/api/tools.ts`; modifica `services/api/index.ts`
- Create: `frontend/src/renderer/src/components/settings/toolPicker.ts` + `toolPicker.spec.ts`
- Modify: `frontend/src/renderer/src/components/settings/PermissionRulesManager.vue`
- Modify: `frontend/src/renderer/src/types/permission.ts` (tipo derivato dal generato)

- [ ] **Step 9.1: contratti** — `powershell -File scripts\gen-contracts.ps1`; commit artifacts
  col task. In `types/permission.ts`: `export type ToolCatalogEntry = ApiSchema<'ToolCatalogEntry'>`.
- [ ] **Step 9.2: API client** — `services/api/tools.ts`:

```ts
import { request } from './http'
import type { ApiSchema } from '../../types/generated'

export type ToolsCatalogResponse = ApiSchema<'ToolsCatalogResponse'>

export const toolsApi = {
  getCatalog: (): Promise<ToolsCatalogResponse> => request<ToolsCatalogResponse>('/tools/catalog'),
}
```

  + `export { toolsApi } from './tools'` in `index.ts`.
- [ ] **Step 9.3: logica picker testabile** — `toolPicker.ts`:

```ts
export function filterCatalog(entries: ToolCatalogEntry[], query: string, limit = 12): ToolCatalogEntry[]
```

  Regole (test rossi prima in `toolPicker.spec.ts`): match case-insensitive su `name`, `label`
  e `plugin`; prefix-match su `name` ordinato prima del substring-match; query vuota → primi
  `limit` in ordine alfabetico; mai più di `limit` risultati.
- [ ] **Step 9.4: integrazione** in `PermissionRulesManager.vue`: on-mount
  `toolsApi.getCatalog()` (fallback silenzioso a lista vuota: il campo resta usabile come
  testo libero — le regole devono poter riferire tool momentaneamente non registrati);
  dropdown sotto `UiInput` con i risultati di `filterCatalog` (nome mono + badge risk +
  plugin/server), click → `newTool = entry.name`. Tastiera: frecce + invio (gestione
  `keydown`), Escape chiude.
- [ ] **Step 9.5: gate FE + commit** — `feat(fe): picker del catalogo tool nelle regole permessi`

### Task 10: response_model sulle route `/api/mcp/*` + livello per-tool

**Files:**
- Modify: `backend/api/routes/mcp.py`
- Modify: `backend/tests/contracts/response_model_baseline.txt` (RIMUOVERE le 3 righe mcp)
- Test: nuovo `backend/tests/test_mcp_routes.py` (pattern client di test come Task 8)

- [ ] **Step 10.1: test rossi** — shape tipizzata + livello derivato:

```python
async def test_mcp_servers_typed_shape() -> None:
    resp = await client.get("/api/mcp/servers")
    body = resp.json()
    srv = body["servers"][0]
    assert set(srv) >= {"name", "transport", "enabled", "command", "url", "status",
                        "trust_annotations", "tools"}
    tool = srv["tools"][0]
    assert set(tool) == {"name", "description", "level", "risk_level",
                         "requires_confirmation"}
    assert tool["level"] in {"read_only", "write", "fallback"}
```

  + test unit della derivazione (`_tool_level`): read_only / write / fallback (annotated=False
  O trusted=False) / `mcp is None` → fallback.
- [ ] **Step 10.2: rosso → implementazione.** Modelli in `mcp.py` (pattern inline dei
  file route esistenti):

```python
class McpToolOut(BaseModel):
    """Tool MCP col livello derivato dal gate (spec Fase 2 §6.4)."""

    name: str
    description: str
    level: Literal["read_only", "write", "fallback"]
    risk_level: str
    requires_confirmation: bool


class McpServerOut(BaseModel):
    name: str
    transport: str
    enabled: bool
    command: list[str] | None = None
    url: str | None = None
    status: str
    trust_annotations: bool
    tools: list[McpToolOut]


class McpServersResponse(BaseModel):
    servers: list[McpServerOut]


class McpReconnectResponse(BaseModel):
    status: str
    tools_count: int
```

  Derivazione (funzione modulo, testata):

```python
def _tool_level(tool_def: ToolDefinition) -> Literal["read_only", "write", "fallback"]:
    m = tool_def.mcp
    if m is None or not m.annotated or not m.trusted:
        return "fallback"
    return "read_only" if m.read_only else "write"
```

  Le tre route guadagnano `response_model=` e costruiscono i modelli dai `ToolDefinition` di
  `get_server_tools` (che ora portano `.mcp`) + `cfg.trust_annotations`. Semantica delle route
  INVARIATA (stessi status code 404/503, stessi dati + i campi nuovi).
- [ ] **Step 10.3: baseline ratchet** — rimuovere da `response_model_baseline.txt` le righe
  `GET /api/mcp/servers`, `GET /api/mcp/servers/{server_name}`,
  `POST /api/mcp/servers/{server_name}/reconnect`. `pytest tests/contracts/ -v` → verde.
- [ ] **Step 10.4: verde completo** — `pytest tests/test_mcp_routes.py tests/test_mcp_session.py tests/test_mcp_client_plugin.py tests/contracts/ -v`.
- [ ] **Step 10.5: commit** — `feat(api): route /api/mcp/* tipizzate con livello per-tool derivato dal gate`

### Task 11: FE — pannello MCP arricchito in Impostazioni

**Files:**
- Generated: rigenerare contratti (schema `McpServerOut`/`McpToolOut`/...)
- Modify: `frontend/src/renderer/src/types/mcp.ts` (tipi derivati da `ApiSchema`, non più interface a mano)
- Modify: `frontend/src/renderer/src/components/settings/McpManager.vue`
- Create: `frontend/src/renderer/src/components/settings/mcpToolLevel.ts` + `mcpToolLevel.spec.ts`
- Test: verifica che `stores/mcp.ts` e `useEventsWebSocket.ts` restino type-safe (typecheck)

- [ ] **Step 11.1: contratti** — `powershell -File scripts\gen-contracts.ps1`. In `types/mcp.ts`
  sostituire le interface a mano:

```ts
import type { ApiSchema } from './generated'

export type McpServerTool = ApiSchema<'McpToolOut'>
export type McpServerInfo = ApiSchema<'McpServerOut'>
export type McpServersResponse = ApiSchema<'McpServersResponse'>
export type McpReconnectResponse = ApiSchema<'McpReconnectResponse'>
```

  `npm run typecheck` per stanare ogni consumer che assumeva la vecchia shape.
- [ ] **Step 11.2: label logic testabile** — `mcpToolLevel.ts`:

```ts
export function toolLevelBadge(tool: McpServerTool): { label: string; variant: 'success' | 'warning' | 'danger' } 
```

  `read_only` → `{label: 'sola lettura', variant: 'success'}`; `write` →
  `{label: 'scrittura', variant: 'warning'}`; `fallback` →
  `{label: 'non annotato → trattato come distruttivo', variant: 'danger'}`. Test rossi prima.
- [ ] **Step 11.3: pannello.** In `McpManager.vue`: per-server, accanto ai badge status/transport,
  badge `annotations fidate` / `annotations non fidate` da `server.trust_annotations`
  (read-only, riflette la config); per-tool, il tag esistente (righe 83-90) guadagna il badge
  livello da `toolLevelBadge` + `title` con risk_level. Riusare le classi `.mcp-badge--*`.
- [ ] **Step 11.4: gate FE + commit** — `feat(fe): pannello MCP con trust per-server e livello derivato per-tool`

### Task 12: `ToolExecutionOutput.images` popolato dall'adapter execution

**Files:**
- Modify: `backend/services/agent/ports.py` (`ToolExecutionOutput`, righe 128-141)
- Modify: `backend/services/agent/adapters/execution.py` (guardia immagini, righe 188-220)
- Test: `backend/tests/agent/test_adapter_execution.py`

- [ ] **Step 12.1: test rossi** (accanto ai test guardia placeholder esistenti):

```python
async def test_image_result_populates_images_and_placeholder() -> None:
    # ToolResult.ok(content=<b64>, content_type="image/png") dal registry finto
    output = await adapter.execute(call)
    assert output.content.startswith("[immagine image/png")     # placeholder invariato
    assert output.images == (ToolImage(mime="image/png", base64_data=b64),)

async def test_text_result_has_no_images() -> None:
    assert output.images == ()

async def test_failed_image_result_has_no_images() -> None:
    # success=False -> niente images, content = error path attuale
    assert output.images == ()
```

- [ ] **Step 12.2: rosso → implementazione.** In `ports.py` tipizzare il carrier (il campo
  esiste già come `tuple[dict[str, str], ...]`, zero consumatori → si irrobustisce):

```python
@dataclass(frozen=True, slots=True)
class ToolImage:
    """Immagine prodotta da un tool (base64), trasportata fuori banda dal content."""

    mime: str
    base64_data: str
```

  `images: tuple[ToolImage, ...] = ()`. In `execution.py`, nel ramo guardia immagini:

```python
if is_image and result.success and result.content:
    content = _image_placeholder(result.content_type, result.content)
    images = (ToolImage(mime=result.content_type, base64_data=result.content),)
```

  e passare `images=images` al `ToolExecutionOutput`.
- [ ] **Step 12.3: verde + gate + commit** — `feat(agent): ToolImage su ToolExecutionOutput - il base64 attraversa la porta fuori banda`

### Task 13: `LLMPort.supports_vision` + adapter e doubles

**Files:**
- Modify: `backend/services/agent/ports.py` (`LLMPort`, righe 165-176)
- Modify: `backend/services/agent/adapters/llm.py`
- Modify: `backend/tests/agent/doubles.py` (+ ogni implementor: grep `LLMPort` — inclusi `backend/tests/evals/scripted_llm.py` e `_llm_shim.py` se implementano la porta)
- Test: `backend/tests/agent/test_adapter_llm.py`

- [ ] **Step 13.1: test rosso**:

```python
def test_supports_vision_delegates_to_llm_service() -> None:
    service = <fake LLMService con supports_vision=True>
    adapter = LLMServiceAdapter(service, ...)
    assert adapter.supports_vision() is True
```

- [ ] **Step 13.2: implementazione.** Sul Protocol:

```python
def supports_vision(self) -> bool:
    """True se il modello attivo accetta input immagine (vision)."""
    ...
```

  Adapter: `return bool(self._llm.supports_vision)` (property esistente di `LLMService`,
  `llm_service.py:107-109`). Doubles/shim/scripted: default `False` (attributo o metodo),
  override per-test dove serve.
- [ ] **Step 13.3: verde + commit** — `feat(agent): LLMPort.supports_vision - capability vision alla porta del motore`

### Task 14: engine — iniezione del messaggio vision + config `agent.vision.*`

**Files:**
- Modify: `backend/services/agent/engine.py` (ctor righe 182-203; `_run_tool_step` intorno a riga 577)
- Modify: `backend/core/config.py` (`AgentConfig`: sotto-modello `vision`), `config/default.yaml`
- Modify: `backend/services/agent/runner.py` (wiring dei due parametri dal config)
- Modify: `docs/flag-registry.md` (censimento)
- Test: `backend/tests/agent/test_engine_tools.py` (o file nuovo `test_engine_vision.py`), `backend/tests/test_config*.py` per la chiave nuova

- [ ] **Step 14.1: test rossi** (fake LLM port con `supports_vision=True/False`, fake execution
  che ritorna `ToolImage`):

```python
async def test_vision_injects_user_message_after_batch() -> None:
    # 1 tool call -> output con 1 immagine; supports_vision=True
    <esegui il turno>
    msg = <messaggio working successivo al tool message>
    assert msg["role"] == "user"
    parts = msg["content"]
    assert parts[0]["type"] == "text" and "screenshot_tool" in parts[0]["text"]
    assert parts[1] == {"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{B64}"}}

async def test_vision_skipped_when_model_not_capable() -> None:
    # supports_vision=False -> NESSUN messaggio user iniettato (solo placeholder nel tool msg)

async def test_vision_skipped_when_disabled() -> None:
    # vision_enabled=False -> idem

async def test_vision_caps_images_per_turn() -> None:
    # 6 immagini nel turno, max=4 -> le prime 4 in ordine di arrivo, le altre restano
    # solo placeholder; il testo del messaggio dichiara il taglio
```

- [ ] **Step 14.2: rosso → implementazione.** Ctor engine: `vision_enabled: bool = True`,
  `vision_max_images: int = 4`. In `_run_tool_step`, dopo il loop delle resolution del batch:

```python
if injected_images_remaining and resolution.output and resolution.output.images:
    batch_images.append((call.name, resolution.output.images))
...
if batch_images and self._vision_enabled and self._llm.supports_vision():
    state.working_messages.append(_vision_message(batch_images, budget))
```

  `_vision_message` (helper modulo accanto a `_tool_message`, riga 174): parts `[{"type":
  "text", "text": "[Risultato visivo del tool <nomi> — immagini allegate...]"}, {"type":
  "image_url", "image_url": {"url": "data:<mime>;base64,<b64>"}}, ...]`, cap sul totale
  immagini del TURNO (contatore su `_TurnState`), nota nel testo quando il cap taglia.
  Il messaggio iniettato NON passa da `persistence.save_*` (in-turn only, decisione #4).
  Config: `AgentVisionConfig(enabled: bool = True, max_images_per_turn: int = 4)` su
  `AgentConfig.vision`; chiavi in `default.yaml` sotto `agent.vision.*`; `runner.py` li passa
  al ctor in ENTRAMBE le configurazioni (WS e headless). Censire in `docs/flag-registry.md`
  (tabella Flag vivi: `agent.vision.enabled`, default `true`, letto da `runner.py`).
- [ ] **Step 14.3: verde** — `pytest tests/agent/ -v` + suite config toccata.
- [ ] **Step 14.4: commit** — `feat(agent): consegna vision in-turn - messaggio user multimodale iniettato dopo il batch tool`

### Task 15: compaction e token counting vision-safe

**Files:**
- Modify: `backend/services/agent/adapters/context.py`
- Test: `backend/tests/agent/test_engine_compaction.py` (o il file test dell'adapter context se esiste)

- [ ] **Step 15.1: test rossi**:

```python
def test_estimate_tokens_handles_multimodal_content() -> None:
    # messaggio con content a lista (1 text part + 1 image part con b64 da 1 MiB)
    tokens = adapter.estimate_tokens(messages)
    assert tokens < 50_000  # l'image part conta come costante, non come len(b64)

async def test_compact_strips_image_parts() -> None:
    # nessun data-URL raggiunge ContextManager.compress; al suo posto il marker testuale
```

- [ ] **Step 15.2: rosso → implementazione.** In `context.py` un normalizzatore modulo:

```python
_IMAGE_PART_TOKENS = 1000

def _flatten_for_counting(messages): ...   # image part -> segnaposto da _IMAGE_PART_TOKENS
def _strip_image_parts(messages): ...      # image part -> "[immagine rimossa dal contesto compattato]"
```

  `estimate_tokens`/`should_compact` contano sulla forma flattened; `compact` passa a
  `ContextManager.compress` SEMPRE la forma stripped (contratto: le immagini non sopravvivono
  alla compaction — decisione #6). I `kept_messages` ritornati sono quelli stripped: il
  motore rimpiazza la working history con l'esito della compaction, coerente e onesto.
- [ ] **Step 15.3: verde + commit** — `feat(agent): compaction vision-safe - stima a costante e strip degli image part`

### Task 16: artifact `IMAGE` + registrazione dal turno

**Files:**
- Modify: `backend/db/models.py` (`ArtifactKind`, riga 300: aggiungere `IMAGE = "image"`)
- Modify: `backend/services/artifacts/registry.py` (nuovo metodo)
- Modify: `backend/services/agent/adapters/db.py` (`register_artifacts`, righe 296-317)
- Test: `backend/tests/test_artifact_registry.py`, `backend/tests/agent/test_adapter_db.py`

- [ ] **Step 16.1: test rossi registry**:

```python
async def test_create_image_artifact_writes_blob_and_row(tmp_path) -> None:
    art = await registry.create_image_artifact(
        conversation_id=conv_id, message_id=None, tool_call_id="c1",
        tool_name="pc_automation_take_screenshot", mime="image/png",
        base64_data=PNG_B64,
    )
    assert art.kind is ArtifactKind.IMAGE and art.mime == "image/png"
    assert Path(<resolve art.file_path>).read_bytes() == base64.b64decode(PNG_B64)

async def test_create_image_artifact_rejects_bad_base64() -> None:
    # base64 corrotto -> None + warning, MAI eccezione fuori
```

  Test rossi adapter (`test_adapter_db.py`): `register_artifacts` con `output.images` popolato
  → chiama il registry e ritorna l'id; con `payload` dict → path esistente invariato; con
  entrambi vuoti → `None`.
- [ ] **Step 16.2: rosso → implementazione.** Registry:

```python
_IMAGE_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
              "image/webp": ".webp"}

async def create_image_artifact(self, *, conversation_id, message_id, tool_call_id,
                                tool_name: str, mime: str, base64_data: str) -> Artifact | None:
    try:
        data = base64.b64decode(base64_data, validate=True)
    except (ValueError, binascii.Error):
        logger.warning("Immagine artifact scartata: base64 non valido ({})", tool_name)
        return None
    artifact_id = uuid.uuid4()
    rel = Path("data") / "artifacts" / "image" / f"{artifact_id}{_IMAGE_EXT.get(mime, '.bin')}"
    path = PROJECT_ROOT / rel
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, data)
    return await self._persist_descriptor(
        descriptor=ArtifactDescriptor(kind=ArtifactKind.IMAGE, title=f"{tool_name}",
                                      file_path=str(rel), mime=mime,
                                      size_bytes=len(data), metadata={}),
        conversation_id=_to_uuid(conversation_id),
        message_id=_to_uuid_or_none(message_id), tool_call_id=tool_call_id,
    )
```

  (allineare i nomi campo di `ArtifactDescriptor` a `services/artifacts/parsers.py` — leggerlo
  prima; se `artifact_id` non è iniettabile in `_persist_descriptor`, usare l'id della row e
  rinominare il file di conseguenza, o generare il nome file da `uuid.uuid4()` indipendente
  dall'id row: scelta libera purché il blob non resti orfano su fallimento commit, stessa
  tolleranza del blob JSON documentata a registry.py:228-230).
  Adapter `register_artifacts`: prima del ramo `payload`, se `output.images` → registra la
  PRIMA immagine (`output.images[0]`; se più d'una, log del taglio) e ritorna l'id.
- [ ] **Step 16.3: verde** — `pytest tests/test_artifact_registry.py tests/test_artifacts_route.py tests/agent/test_adapter_db.py -v`
  (la route `/download` serve il PNG per il kind nuovo senza modifiche: verificarlo con un test
  route se non coperto).
- [ ] **Step 16.4: commit** — `feat(artifacts): ArtifactKind.IMAGE - i risultati immagine dei tool diventano artifact scaricabili`

### Task 17: FE — rendering immagine nel fold del tool

**Files:**
- Modify: `frontend/src/renderer/src/components/chat/ReasoningThread.vue` (nodi tool, righe 98-138)
- Create: `frontend/src/renderer/src/components/chat/toolResultMedia.ts` + `toolResultMedia.spec.ts`
- Test: typecheck/lint/vitest

- [ ] **Step 17.1: logica testabile** — `toolResultMedia.ts`:

```ts
import { BASE_URL } from '../../services/api/http'   // verificare l'export reale in http.ts

export function toolImageUrl(activity: Pick<ToolActivity, 'contentType' | 'artifactId'>): string | null {
  if (!activity.artifactId) return null
  if (!activity.contentType?.startsWith('image/')) return null
  return `${BASE_URL}/artifacts/${activity.artifactId}/download`
}
```

  Test rossi: image/png+id → URL; contentType text → null; id assente → null. Se `BASE_URL`
  non è esportato da `http.ts`, esportarlo (senza duplicarne il valore).
- [ ] **Step 17.2: template.** Nel nodo tool di `ReasoningThread.vue`: quando
  `toolImageUrl(node)` non è null, `<img class="tool-result-image" :src="url" loading="lazy"
  alt="Risultato di {{ node.toolName }}">` con `max-width: 100%`, bordo/radius coi token del
  tema. Verificare che il view-model dei nodi esponga `contentType`/`artifactId` (arrivano da
  `ToolActivity`; se il nodo non li proietta, aggiungerli alla proiezione).
- [ ] **Step 17.3: gate FE + commit** — `feat(fe): rendering immagini dei tool result nel fold via artifact download`

### Task 18: gate di chiusura (backend + FE) e smoke

- [ ] **Step 18.1: pytest mirato** (da `backend/`, foreground, in sequenza — MAI integrale):
  `pytest tests/agent/ tests/evals/ tests/contracts/ -v` poi
  `pytest tests/test_mcp_tool_mapping.py tests/test_mcp_client_plugin.py tests/test_mcp_session.py tests/test_permission_mcp_perimeter.py tests/test_tool_registry.py tests/test_tools_catalog_route.py tests/test_mcp_routes.py tests/test_artifact_registry.py tests/test_artifacts_route.py -v`.
  Tutti PASS (skip solo quelli censiti).
- [ ] **Step 18.2: lint/type/imports** — `ruff check .` = 0; mypy a parità (conteggio vs
  baseline di inizio mossa); `lint-imports --config backend/pyproject.toml` (dal repo root)
  = 6 kept, 0 broken.
- [ ] **Step 18.3: contratti** — `powershell -File scripts\check-contracts.ps1` verde con
  artifacts committati freschi.
- [ ] **Step 18.4: FE** — `npm run typecheck; npm run lint; npx vitest run` verdi.
- [ ] **Step 18.5: smoke manuale utente** (gate di fase §9.6, da chiedere all'utente):
  un edit con diff preview + conferma; un tool MCP annotato e uno non annotato in strict
  (badge + avviso fallback); un grep/glob; uno screenshot con immagine nel fold e (se modello
  vision) descrizione corretta.
- [ ] **Step 18.6: commit di eventuali fix** emersi dai gate.

### Task 19: eval a pagamento di chiusura fase — SOLO CON OK ESPLICITO DELL'UTENTE

**BLOCCANTE: non eseguire senza l'OK dell'utente in sessione.** (Regola di programma.)

- [ ] **Step 19.1**: chiedere l'OK all'utente. Senza OK → la fase resta aperta su questo punto,
  documentarlo nel handoff e fermarsi qui.
- [ ] **Step 19.2** (con OK): `python -m backend.evals run --baseline docs/superpowers/evals/20260718-121940-baseline-fase1/report.json`
  (venv assoluto; API key OpenRouter da keyring/env; modello pinnato `z-ai/glm-5.2`).
- [ ] **Step 19.3**: risultato ≥ baseline (gli scenari `fs-edit-exact-01`/`fs-glob-01`/
  `fs-grep-01` compariranno come NUOVO — devono passare; nessuna REGRESSIONE ammessa).
  Salvare il report sotto `docs/superpowers/evals/` e committarlo.
- [ ] **Step 19.4**: in caso di regressione: systematic-debugging sullo scenario, fix, re-run
  (sempre con OK utente, costa denaro).

### Task 20: docs finali + handoff di fase

- [ ] **Step 20.1**: `CLAUDE.md` — aggiornare "Tools & the AgentEngine" (tool_meta sul wire,
  vision in-turn via `ToolImage`/artifact IMAGE, `GET /api/tools/catalog`) e la riga contratti
  se serve; sezione MCP già allineata da Mossa 1 (ritoccare solo se il perimetro consegnato
  devia).
- [ ] **Step 20.2**: `docs/flag-registry.md` — verificare censimento `agent.vision.*` (Task 14).
- [ ] **Step 20.3**: handoff di fase in
  `docs/superpowers/handoffs/2026-07-20-agent-tools-fase2-mossa2-handoff.md`: consegne per
  blocco con le scoperte di review, stato gate, DEBITO CENSITO aggiornato (vedi sotto),
  gotcha nuovi, delega per la fase successiva (Fase 3).
- [ ] **Step 20.4**: aggiornare il ledger locale `.superpowers/sdd/progress.md` (sezione
  FASE 2 MOSSA 2 con i perché).
- [ ] **Step 20.5**: commit docs — `docs(handoff): Fase 2 chiusa - handoff Mossa 2 + CLAUDE.md/flag-registry finali`

## Debito censito di questa mossa (da riportare nel handoff)

1. **Reidratazione vision cross-turn**: il modello vede l'immagine solo nel turno in cui il
   tool gira; nei turni successivi resta il placeholder. L'artifact IMAGE è la fonte per una
   futura reidratazione (leggere il blob e re-iniettare on-demand) — non in scope.
2. **Immagini e compaction**: le immagini inline non sopravvivono alla compaction (strip
   deliberato, decisione #6). Costo token per image part stimato a costante (1000).
3. **Una sola immagine registrata come artifact per tool result** (`output.images[0]`);
   i tool attuali ne producono al più una.
4. **`toolConfirmationView`/`editDiff`**: il fallback oltre `MAX_LCS_LINES` degrada a blocchi
   removed/added pieni (niente diff fine su file enormi) — onesto e dichiarato nel modulo.
5. I debiti di Mossa 1 e Fase 1 restano invariati (arg-lista nel gate, executor cancellabile,
   chiavi pc_automation, infra test WS/REST Windows).

## Self-review (fatta in scrittura)

- Copertura spec §6: 6.1 → T1-T5; 6.2 → T6-T7; 6.3 → T8-T9; 6.4 → T10-T11; 6.5 → invariata
  (nessun task, T17 tocca il fold solo additivamente). Debito vision handoff #1 → T12-T17.
  Chiusura fase spec §9 → T18-T20.
- Coerenza tipi: `McpToolMeta` (T1) usato in T2/T8/T10; `ToolMetaInfo.as_payload()` (T2) usato
  in T3; `WsToolMeta` (T4) derivato nei tipi FE T5; `ToolImage` (T12) usato in T14/T16;
  `toolImageUrl` (T17) consuma `ToolActivity.contentType/artifactId` esistenti.
- I punti in cui il piano delega una verifica al task (forma esatta di `ArtifactDescriptor`,
  export `BASE_URL`, proiezione nodi in `ReasoningThread`) sono esplicitamente marcati con
  l'istruzione di leggere il file prima — non sono placeholder di design ma binding locali.
