# Agent v2 — Fase 2, Mossa 1 (backend): perimetro MCP + tool file nativi + exec unificato — Piano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chiudere il perimetro permessi dei tool MCP (annotations → gate, fallback conservativo,
path_args per-server, rimozione grant layer) e portare i tool file/exec nativi a parità Claude
Code (read con line numbers/offset/limit/immagini, edit exact-string con read-tracking, write con
guardie, glob, grep contenuti, exec unificato sul terminal, path-safety consolidata).

**Architecture:** La spec di fase è
`docs/superpowers/specs/2026-07-18-agent-v2-fase2-fondamenta-tool-design.md` — LEGGERLA PRIMA.
Il mapping annotations vive in un modulo puro nuovo (`services/mcp_tool_mapping.py`) consumato da
`McpSession`; il gate cambia solo in 2 punti chirurgici (plan-block `mcp_write`, offer policy). I
tool nuovi evolvono il plugin `file_search` in place. La path-safety converge in
`core/path_safety.py`. La Mossa 2 (contratti wire `tool_meta`, endpoint catalog, FE) ha piano
proprio e parte SOLO a Mossa 1 conclusa.

**Tech Stack:** Python 3.11+/FastAPI, SQLModel, pytest, libreria `mcp` 1.26.0 (espone già
`Tool.annotations`), plugin system AL\CE (`ToolDefinition` frozen dataclass in
`backend/core/plugin_models.py`).

**Branch:** `feat/agent-tools-fase2` (creato da `72d5a5c`, HEAD congelato di Fase 1 — NON
committare mai su `feat/agent-engine-fase1`).

**Gotcha macchina (VITALI, dal handoff di Fase 1):**
- venv SEMPRE con path assoluto in OGNI comando:
  `& "C:\Users\Jays\Desktop\alice\alice\.venv\Scripts\Activate.ps1"` — un path relativo fallisce
  in silenzio lasciando il Python di sistema.
- Tutti i pytest si lanciano da `backend/`. MAI due pytest concorrenti, MAI in background.
- Per gli hang: `-o faulthandler_timeout=120`.
- MAI la suite pytest integrale (AUD-008): solo i sottoinsiemi indicati nei task.
- Eval a pagamento SOLO con OK esplicito dell'utente (questa mossa tocca solo il subset mock).

---

## Blocco A — Perimetro permessi MCP

### Task 1: Config per-server `trust_annotations` + `path_args`

**Files:**
- Modify: `backend/core/config.py` (classe `McpServerConfig`, righe ~788-829)
- Test: `backend/tests/test_mcp_tool_mapping.py` (NUOVO — ospiterà anche i test del Task 2)

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for MCP server config extensions and annotations→gate mapping (Fase 2)."""
from backend.core.config import McpServerConfig


def test_mcp_server_config_defaults() -> None:
    cfg = McpServerConfig(name="filesystem", command=["npx", "server"])
    assert cfg.trust_annotations is True
    assert cfg.path_args == {}


def test_mcp_server_config_explicit_values() -> None:
    cfg = McpServerConfig(
        name="filesystem",
        command=["npx", "server"],
        trust_annotations=False,
        path_args={"write_file": ["path"], "move_file": ["source", "destination"]},
    )
    assert cfg.trust_annotations is False
    assert cfg.path_args["move_file"] == ["source", "destination"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run (da `backend/`): `pytest tests/test_mcp_tool_mapping.py -v`
Expected: FAIL — `ValidationError`/`AttributeError` (campi inesistenti).

- [ ] **Step 3: Implement — aggiungi i campi a `McpServerConfig`**

Dopo `enabled: bool = True` (config.py:816-817):

```python
    trust_annotations: bool = True
    """Honour the server's MCP tool annotations (readOnlyHint/destructiveHint) when
    mapping tools onto the permission gate.  ``False`` demotes every tool of this
    server to the conservative fallback (treated as destructive, always confirmed)."""

    path_args: dict[str, list[str]] = Field(default_factory=dict)
    """Optional map ``tool name -> argument names that carry filesystem paths``.
    A listed tool receives real fs capabilities + ``path_args`` in its
    ToolDefinition, so the per-conversation scope confinement of the permission
    gate applies to it by construction (spec Fase 2 §3.3)."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_tool_mapping.py -v` → PASS.
Poi regressione config: `pytest tests/ -k "config" -v` (se esiste una suite config) e
`ruff check backend/core/config.py`.

- [ ] **Step 5: Commit**

```bash
git add backend/core/config.py backend/tests/test_mcp_tool_mapping.py
git commit -m "feat(mcp): config per-server trust_annotations + path_args (fase 2)"
```

### Task 2: Mapping annotations → ToolDefinition (`mcp_tool_mapping.py`)

**Files:**
- Create: `backend/services/mcp_tool_mapping.py`
- Modify: `backend/services/mcp_session.py:494-508` (conversione in `_session_task`)
- Modify: `backend/plugins/mcp_client/plugin.py:210-215` (`get_tools` DEVE preservare i campi
  nuovi nel re-namespacing — oggi ricostruisce il `ToolDefinition` con 4 campi e li perderebbe)
- Test: `backend/tests/test_mcp_tool_mapping.py` (estendi), `backend/tests/test_mcp_client_plugin.py`

- [ ] **Step 1: Write the failing tests** (usa `mcp.types.Tool`/`ToolAnnotations` VERI — la lib è
  installata; niente mock dei tipi)

```python
from mcp.types import Tool, ToolAnnotations

from backend.services.mcp_tool_mapping import map_mcp_tool


def _tool(name: str = "t", annotations: ToolAnnotations | None = None) -> Tool:
    return Tool(name=name, inputSchema={"type": "object", "properties": {}},
                annotations=annotations)


def _server(**kw) -> McpServerConfig:
    return McpServerConfig(name="srv", command=["x"], **kw)


def test_read_only_tool_maps_to_mcp_read_safe_no_confirm() -> None:
    td = map_mcp_tool(_tool(annotations=ToolAnnotations(readOnlyHint=True)), _server())
    assert td.capabilities == ("mcp_read",)
    assert td.risk_level == "safe"
    assert td.requires_confirmation is False


def test_non_destructive_write_maps_to_mcp_write_medium_confirm() -> None:
    td = map_mcp_tool(
        _tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False)),
        _server())
    assert td.capabilities == ("mcp_write",)
    assert td.risk_level == "medium"
    assert td.requires_confirmation is True


def test_destructive_write_maps_to_dangerous() -> None:
    td = map_mcp_tool(
        _tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True)),
        _server())
    assert td.risk_level == "dangerous"
    assert td.requires_confirmation is True


def test_missing_annotations_falls_back_conservative() -> None:
    td = map_mcp_tool(_tool(annotations=None), _server())
    assert td.capabilities == ("mcp_write",)
    assert td.risk_level == "dangerous"
    assert td.requires_confirmation is True


def test_untrusted_server_ignores_annotations() -> None:
    td = map_mcp_tool(
        _tool(annotations=ToolAnnotations(readOnlyHint=True)),
        _server(trust_annotations=False))
    assert td.capabilities == ("mcp_write",)
    assert td.risk_level == "dangerous"


def test_path_args_promote_to_fs_capability() -> None:
    server = _server(path_args={"write_file": ["path"], "read_file": ["path"]})
    write_td = map_mcp_tool(
        _tool(name="write_file",
              annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True)),
        server)
    read_td = map_mcp_tool(
        _tool(name="read_file", annotations=ToolAnnotations(readOnlyHint=True)), server)
    assert write_td.capabilities == ("fs_write",)
    assert write_td.path_args == ("path",)
    assert read_td.capabilities == ("fs_read",)
    assert read_td.path_args == ("path",)
```

E in `test_mcp_client_plugin.py` un test che `get_tools()` PRESERVA capability/risk/confirm/
path_args dopo il re-namespacing (costruisci una sessione finta con un `ToolDefinition` mappato e
verifica il tool namespaced `mcp_srv_write_file`).

- [ ] **Step 2: Run** `pytest tests/test_mcp_tool_mapping.py tests/test_mcp_client_plugin.py -v`
  → FAIL (`ImportError: map_mcp_tool`).

- [ ] **Step 3: Implement `backend/services/mcp_tool_mapping.py`**

```python
"""Pure mapping from MCP tool metadata onto the permission-gate vocabulary.

Spec: docs/superpowers/specs/2026-07-18-agent-v2-fase2-fondamenta-tool-design.md §3.1.
Conservative-by-default: a tool without (trusted) annotations is treated as
destructive — confirmed in strict AND auto_edits, withheld and denied in plan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.plugin_models import ToolDefinition

if TYPE_CHECKING:
    from mcp.types import Tool

    from backend.core.config import McpServerConfig

MCP_READ_CAPABILITY = "mcp_read"
MCP_WRITE_CAPABILITY = "mcp_write"


def map_mcp_tool(tool: "Tool", server: "McpServerConfig") -> ToolDefinition:
    """Build the gate-aware ToolDefinition for one MCP tool."""
    annotations = tool.annotations if server.trust_annotations else None

    if annotations is not None and annotations.readOnlyHint is True:
        capabilities: tuple[str, ...] = (MCP_READ_CAPABILITY,)
        risk_level, requires_confirmation = "safe", False
    elif annotations is not None:
        # Annotations present, not read-only.  MCP spec: destructiveHint
        # defaults to True when omitted.
        destructive = annotations.destructiveHint is not False
        capabilities = (MCP_WRITE_CAPABILITY,)
        risk_level = "dangerous" if destructive else "medium"
        requires_confirmation = True
    else:
        # No annotations (or untrusted server): conservative fallback.
        capabilities = (MCP_WRITE_CAPABILITY,)
        risk_level, requires_confirmation = "dangerous", True

    declared_paths = tuple(server.path_args.get(tool.name, ()))
    if declared_paths:
        # Path-aware tool: promote to a real fs capability so the gate's
        # per-conversation scope confinement applies by construction.
        capabilities = (
            ("fs_read",) if capabilities == (MCP_READ_CAPABILITY,) else ("fs_write",)
        )

    return ToolDefinition(
        name=tool.name,
        description=(tool.description or "")[:1024],
        parameters=(
            tool.inputSchema
            if tool.inputSchema
            else {"type": "object", "properties": {}}
        ),
        capabilities=capabilities,
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        path_args=declared_paths,
    )
```

In `mcp_session.py:495-508` la list-comprehension diventa:

```python
                self._cached_tools = [
                    map_mcp_tool(tool, self._config)
                    for tool in tools_response.tools
                ]
```

(import in testa: `from backend.services.mcp_tool_mapping import map_mcp_tool`).

In `plugin.py:210-215` il rebuild usa `dataclasses.replace` per non perdere i campi:

```python
                renamed = replace(
                    tool,
                    name=full_name,
                    description=full_desc[:512],
                    max_result_chars=self._MCP_MAX_RESULT_CHARS,
                )
```

(`from dataclasses import replace`; ATTENZIONE: `ToolDefinition.__post_init__` rivalida — ok.)

- [ ] **Step 4: Run** gli stessi test → PASS. Poi regressione:
  `pytest tests/test_mcp_session.py tests/test_mcp_client_plugin.py tests/test_mcp_tool_mapping.py -v`
  e `mypy backend/services/mcp_tool_mapping.py`.

- [ ] **Step 5: Commit** `feat(mcp): annotations readOnly/destructive mappate su capability/risk/confirm del gate, fallback conservativo`

### Task 3: Gate — plan-block e offer-policy per `mcp_write`

**Files:**
- Modify: `backend/services/permission_service.py` (riga ~54 costanti; riga ~330 plan-block)
- Modify: `backend/services/permission_mode_policy.py:36-38`
- Test: `backend/tests/test_permission_mcp_perimeter.py` (NUOVO), `backend/tests/test_permission_mode_policy.py`

- [ ] **Step 1: Write the failing tests** — matrice tier × capability MCP. Costruisci i
  `ToolDefinition` con `map_mcp_tool` (coerenza col Task 2) e un `PermissionService` come nei
  test esistenti (`tests/test_permission_tiers.py` è il modello per fixture/provider).

```python
# I casi minimi da coprire (un test per riga; segui lo stile di test_permission_tiers.py):
# 1. mcp_write (dangerous, confirm) in STRICT      -> NEEDS_CONFIRMATION
# 2. mcp_write (dangerous, confirm) in AUTO_EDITS  -> NEEDS_CONFIRMATION (risk dangerous)
# 3. mcp_write (medium, confirm)   in AUTO_EDITS   -> NEEDS_CONFIRMATION (requires_confirmation)
# 4. mcp_write in PLAN                              -> DENY plan_mode
# 5. mcp_read in STRICT e in PLAN                   -> ALLOW (nessuna conferma)
# 6. mcp_write in AUTOPILOT                         -> ALLOW
# 7. tool MCP promosso fs_write via path_args, path FUORI scope -> DENY outside_scope
# 8. tool MCP promosso fs_write via path_args, path IN scope, STRICT -> NEEDS_CONFIRMATION
# 9. PermissionRule DENY su nome mcp_* namespaced   -> DENY user_denied (vince su tutto)
```

E in `test_permission_mode_policy.py`: `policy_for(PLAN).blocked_capabilities` contiene
`"mcp_write"` (e non `"mcp_read"`).

- [ ] **Step 2: Run** `pytest tests/test_permission_mcp_perimeter.py tests/test_permission_mode_policy.py -v`
  → FAIL sui casi 4 e sul blocked_capabilities (oggi `mcp_write` non è bloccato in plan).
  NOTA: i casi 1-3/5-9 potrebbero già passare per costruzione (requires_confirmation/path_args
  fanno il lavoro) — il rosso VERIFICATO deve esserci almeno su 4 e sulla policy; gli altri sono
  pin di regressione.

- [ ] **Step 3: Implement**

`permission_service.py` — vicino a `UI_COMMAND_CAPABILITY` (riga ~54):

```python
MCP_WRITE_CAPABILITY = "mcp_write"
```

Riga ~330:

```python
        # 5. plan tier is read-only: block writes / process-exec / MCP writes.
        if mode is PermissionMode.PLAN and (
            is_write or is_exec or MCP_WRITE_CAPABILITY in caps
        ):
            return GateDecision.deny(PermissionOutcome.DENY_PLAN_MODE, "plan_mode")
```

`permission_mode_policy.py:36-38`:

```python
_READ_ONLY_BLOCKED_CAPABILITIES: frozenset[str] = frozenset(
    {"fs_write", "process_exec", "mcp_write"}
)
```

(aggiorna il commento alle righe 31-35: cita anche gli MCP write.)

- [ ] **Step 4: Run** le due suite + regressione
  `pytest tests/test_permission_service.py tests/test_permission_tiers.py tests/test_permission_scope_confinement.py -v` → PASS.

- [ ] **Step 5: Commit** `feat(permissions): mcp_write negato e non offerto in plan; matrice tier x MCP pinnata`

### Task 4: Rimozione del layer grant in-memory

**Files:**
- Modify: `backend/services/permission_service.py` (righe 175, 284-289, 311-313, 337-339,
  442-483 `_check_scope`, 489-505 `grant/revoke/is_granted/clear_grants`, firma
  `_decide_ui_command` riga ~397)
- Test: `backend/tests/test_permission_service.py:203-233`, `backend/tests/test_permission_circuit_breakers.py:80,92`, `backend/tests/test_permission_ui_commands.py:129,143`

- [ ] **Step 1: Grep dei chiamanti** (verifica pre-condizione, non test):
  `rg "\.grant\(|is_granted|revoke\(|clear_grants" backend/ --type py`
  Attesi SOLO: `permission_service.py` stesso + i 3 file di test. Verifica anche i chiamanti di
  `evaluate(`/`_check_scope`: se `evaluate` non ha chiamanti di produzione (attesa: solo test),
  rimuovi ANCHE `evaluate`+`_check_scope` in questo task; se ne ha, lasciali e censisci
  nell'handoff. Documenta l'esito nel messaggio di commit.

- [ ] **Step 2: Migra i test rossi** — i test che chiamavano `.grant(...)` esprimono lo stesso
  intento con una `PermissionRule` ALLOW via `rule_provider` finto (stile già presente in
  `test_permission_service.py` per i casi rule). Esegui
  `pytest tests/test_permission_service.py tests/test_permission_circuit_breakers.py tests/test_permission_ui_commands.py -v`
  e verifica il ROSSO dopo la rimozione (step 3) prima del fix dei test, oppure — ordine più
  pratico qui — riscrivi prima i test sull'intento (rule al posto di grant), verificali VERDI
  con il codice attuale, POI rimuovi il layer.

- [ ] **Step 3: Implement la rimozione** — cancella `self._grants` (175), le 4 API (489-505),
  la lettura `granted` in `decide` (289) e i suoi usi: riga 311-313 diventa
  `if rule is not RuleEffect.ALLOW:`, riga 337-339 diventa `if rule is RuleEffect.ALLOW:`;
  togli il parametro `granted` da `_decide_ui_command` e dai suoi call site; stessa pulizia in
  `_check_scope` se sopravvive. Aggiorna la docstring di `decide` (240-262) che cita i grant.

- [ ] **Step 4: Run**
  `pytest tests/test_permission_service.py tests/test_permission_tiers.py tests/test_permission_ui_commands.py tests/test_permission_circuit_breakers.py tests/test_permission_scope_confinement.py tests/agent/test_adapter_permission.py -v`
  → PASS; `ruff check backend/services/permission_service.py`; `mypy` sul file.

- [ ] **Step 5: Commit** `refactor(permissions): rimosso il layer grant in-memory senza scrittori (le PermissionRule coprono il remember)`

### Task 5: `default.yaml` + flag-registry

**Files:**
- Modify: `config/default.yaml` (sezione `mcp.servers`, righe ~352-368)
- Modify: `docs/flag-registry.md`

- [ ] **Step 1:** Nel server `filesystem` aggiungi la mappa `path_args` compilata (tool del
  server-filesystem v2026.7.10 che portano path):

```yaml
    - name: filesystem
      command: [npx, "@modelcontextprotocol/server-filesystem", "~"]
      enabled: true
      # trust_annotations: true (default) — annotations onorate.
      path_args:
        read_file: [path]
        read_text_file: [path]
        read_media_file: [path]
        read_multiple_files: [paths]
        write_file: [path]
        edit_file: [path]
        create_directory: [path]
        list_directory: [path]
        directory_tree: [path]
        move_file: [source, destination]
        search_files: [path]
        get_file_info: [path]
```

NOTA: `read_multiple_files.paths` è una LISTA di path — il gate itera `args.get(arg)` come
stringa singola (`decide` riga 316-319). Verifica il comportamento: se il gate non gestisce le
liste, NON dichiarare `read_multiple_files` e censisci il limite nel commento yaml e
nell'handoff (niente falsa copertura).

- [ ] **Step 2:** `docs/flag-registry.md`: censisci `mcp.servers[].trust_annotations` (default
  `true`) e `mcp.servers[].path_args` (default `{}`) con una riga sul significato, sezione MCP.

- [ ] **Step 3:** Smoke di config: da `backend/`,
  `python -c "from backend.core.config import Settings; s=Settings(); print([ (x.name, x.trust_annotations, len(x.path_args)) for x in s.mcp.servers ])"`
  → il filesystem server mostra la mappa. Run `pytest tests/test_mcp_tool_mapping.py -v` → PASS.

- [ ] **Step 4: Commit** `feat(mcp): path_args del server filesystem builtin dichiarati in default.yaml + flag-registry`

## Blocco B — Path-safety consolidata

### Task 6: Modulo `backend/core/path_safety.py`

**Files:**
- Create: `backend/core/path_safety.py`
- Test: `backend/tests/test_path_safety.py` (NUOVO)

- [ ] **Step 1: Write the failing tests** — porta i casi limite GIÀ coperti dalle 4 suite
  esistenti (`test_terminal_security.py`, `test_file_search_plugin.py` sezione path,
  `test_permission_scope_confinement.py`) come pin del modulo unico: resolve di `..`, symlink,
  UNC `\\server\share` e `//server/share`, forbidden dir (match esatto e discendente), containment
  positivo/negativo, drive Windows diversi, path inesistente.

```python
from pathlib import Path

from backend.core.path_safety import (
    is_relative_to, is_unc_path, safe_resolve, within_any_root,
)


def test_unc_paths_rejected() -> None:
    assert is_unc_path(r"\\server\share")
    assert is_unc_path("//server/share")
    assert not is_unc_path(r"C:\Users\x")


def test_safe_resolve_normalises_dotdot(tmp_path: Path) -> None:
    child = tmp_path / "a" / ".." / "b"
    assert safe_resolve(str(child)) == (tmp_path / "b").resolve()


def test_within_any_root(tmp_path: Path) -> None:
    inside = tmp_path / "sub" / "f.txt"
    assert within_any_root(inside, [tmp_path])
    assert not within_any_root(tmp_path.parent, [tmp_path])


def test_is_relative_to_cross_drive() -> None:
    assert not is_relative_to(Path(r"D:\x"), Path(r"C:\x"))
```

- [ ] **Step 2: Run** `pytest tests/test_path_safety.py -v` → FAIL (modulo inesistente).

- [ ] **Step 3: Implement**

```python
"""Single implementation of filesystem path-safety primitives.

Consolidates the deliberate replicas that lived in file_search/searcher.py,
terminal/security.py, permission_service.py, pc_automation/security.py and
scope_service (censused debt, saldato in Fase 2).  Semantics are IDENTICAL to
the replicas: resolve-first, forbidden-before-containment, no I/O beyond
``Path.resolve``.
"""

from __future__ import annotations

from pathlib import Path


def is_unc_path(raw: str) -> bool:
    """True for Windows UNC/device paths (``\\\\server`` or ``//server``)."""
    return raw.startswith(("\\\\", "//"))


def safe_resolve(raw: str | Path) -> Path | None:
    """``Path.resolve()`` that returns None instead of raising (invalid path)."""
    try:
        return Path(raw).resolve()
    except (OSError, ValueError):
        return None


def is_relative_to(child: Path, parent: Path) -> bool:
    """Containment check on already-resolved paths (no filesystem access)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def within_any_root(target: Path, roots: list[Path] | tuple[Path, ...]) -> bool:
    """True if the resolved target sits under at least one resolved root."""
    return any(is_relative_to(target, root) for root in roots)


def is_forbidden(target: Path, forbidden: list[Path] | tuple[Path, ...]) -> bool:
    """True if the target is one of, or sits under, a forbidden directory."""
    return any(target == f or is_relative_to(target, f) for f in forbidden)
```

(Se durante il porting dei casi emergono primitive in più davvero condivise — es. il check
symlink di `searcher.py` — aggiungile QUI con test; niente funzioni speculative.)

- [ ] **Step 4: Run** `pytest tests/test_path_safety.py -v` → PASS; `mypy backend/core/path_safety.py`.

- [ ] **Step 5: Commit** `feat(core): modulo path_safety unico (resolve/containment/forbidden/UNC) con pin dai casi limite esistenti`

### Task 7: Migrazione dei consumatori a `path_safety`

**Files:**
- Modify: `backend/plugins/file_search/searcher.py:17-90,195-209`
- Modify: `backend/services/terminal/security.py` (togli il commento "replicate rather than import", righe ~11-18)
- Modify: `backend/services/permission_service.py:520-544` (`_within_scope`/`_safe_resolve`/`_is_relative_to`)
- Modify: `backend/plugins/pc_automation/security.py`
- Modify: `backend/services/scope_service.py:328-394` (`validate_folder` usa le primitive)
- Test: le suite ESISTENTI dei 5 file (nessun test nuovo: il pin è la non-regressione)

- [ ] **Step 1:** Un consumatore alla volta, in quest'ordine (dal meno al più critico):
  `pc_automation/security.py` → `file_search/searcher.py` → `terminal/security.py` →
  `scope_service.py` → `permission_service.py`. Per ognuno: sostituisci le copie locali di
  resolve/containment/forbidden/UNC con gli import da `backend.core.path_safety`, SENZA cambiare
  la semantica dei check né l'ordine (resolve-first, forbidden-before-containment).

- [ ] **Step 2:** Dopo OGNI consumatore, run della sua suite:
  - `pytest tests/test_file_search_plugin.py -v`
  - `pytest tests/test_terminal_security.py tests/test_terminal_plugin.py -v`
  - `pytest tests/test_permission_scope_confinement.py tests/test_permission_service.py -v`
  - `pytest tests/ -k "scope_service or pc_automation" -v`
  Expected: PASS identico a prima (nessun test modificato).

- [ ] **Step 3:** `lint-imports --config backend/pyproject.toml` (dal repo root, venv attivo)
  → 6 kept, 0 broken (core non importa services/plugins: `path_safety` sta in core, i
  consumatori lo importano — direzione lecita).

- [ ] **Step 4: Commit** (uno per consumatore o unico, a discrezione del task)
  `refactor: path-safety consolidata sul modulo unico core.path_safety (semantica invariata)`

## Blocco C — Tool file nativi (plugin `file_search`)

### Task 8: Read-tracker per-conversazione

**Files:**
- Create: `backend/plugins/file_search/read_tracker.py`
- Test: `backend/tests/test_file_search_read_tracker.py` (NUOVO)

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

from backend.plugins.file_search.read_tracker import ReadState, ReadTracker


def test_unread_file(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"; f.write_text("x")
    assert ReadTracker().verify("conv1", f) is ReadState.UNREAD


def test_fresh_after_record(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"; f.write_text("x")
    t = ReadTracker(); t.record("conv1", f)
    assert t.verify("conv1", f) is ReadState.FRESH


def test_stale_after_external_modification(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"; f.write_text("x")
    t = ReadTracker(); t.record("conv1", f)
    import os
    os.utime(f, ns=(1, 1))  # mtime cambiato "esternamente"
    assert t.verify("conv1", f) is ReadState.STALE


def test_conversations_are_isolated(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"; f.write_text("x")
    t = ReadTracker(); t.record("conv1", f)
    assert t.verify("conv2", f) is ReadState.UNREAD


def test_lru_cap_evicts_oldest(tmp_path: Path) -> None:
    t = ReadTracker(max_entries=2)
    files = []
    for i in range(3):
        f = tmp_path / f"{i}.txt"; f.write_text("x"); files.append(f)
        t.record("conv1", f)
    assert t.verify("conv1", files[0]) is ReadState.UNREAD  # evicted
    assert t.verify("conv1", files[2]) is ReadState.FRESH
```

- [ ] **Step 2: Run** `pytest tests/test_file_search_read_tracker.py -v` → FAIL.

- [ ] **Step 3: Implement**

```python
"""Per-conversation read-before-write tracking (Claude Code model).

In-memory, process-lifetime: after a backend restart the agent simply re-reads.
Keys are RESOLVED paths; staleness is detected via mtime_ns.
"""

from __future__ import annotations

import enum
from collections import OrderedDict
from pathlib import Path


class ReadState(enum.Enum):
    UNREAD = "unread"
    STALE = "stale"
    FRESH = "fresh"


class ReadTracker:
    """LRU map ``conversation_id -> {resolved path: mtime_ns at read}``."""

    def __init__(self, max_entries: int = 256) -> None:
        self._max_entries = max_entries
        self._by_conversation: dict[str, OrderedDict[Path, int]] = {}

    def record(self, conversation_id: str, path: Path) -> None:
        entries = self._by_conversation.setdefault(conversation_id, OrderedDict())
        resolved = path.resolve()
        entries.pop(resolved, None)
        entries[resolved] = resolved.stat().st_mtime_ns
        while len(entries) > self._max_entries:
            entries.popitem(last=False)

    def verify(self, conversation_id: str, path: Path) -> ReadState:
        entries = self._by_conversation.get(conversation_id)
        resolved = path.resolve()
        if entries is None or resolved not in entries:
            return ReadState.UNREAD
        try:
            current = resolved.stat().st_mtime_ns
        except OSError:
            return ReadState.STALE
        return ReadState.FRESH if current == entries[resolved] else ReadState.STALE
```

- [ ] **Step 4: Run** → PASS. `mypy` sul file.

- [ ] **Step 5: Commit** `feat(file_search): ReadTracker per-conversazione (mtime) per le guardie edit/write`

### Task 9: `read_text_file` — line numbers + offset/limit

**Files:**
- Modify: `backend/plugins/file_search/plugin.py:189-221` (schema) e `:446-488` (handler)
- Modify: `backend/plugins/file_search/readers.py` (formato output testo)
- Modify: `backend/core/config.py` (FileSearchConfig: `max_read_lines: int = 2000`,
  `max_line_chars: int = 2000`)
- Test: `backend/tests/test_file_search_plugin.py`

- [ ] **Step 1: Write the failing tests** (nella classe/sezione read del file esistente)

```python
async def test_read_text_file_numbers_lines(plugin, tmp_workspace):
    f = tmp_workspace / "notes.txt"
    f.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = await plugin.execute_tool("read_text_file", {"path": str(f)}, ctx())
    assert result.success
    content = result.content["content"]
    assert "     1\talpha" in content and "     3\tgamma" in content
    assert result.content["total_lines"] == 3


async def test_read_text_file_offset_and_limit(plugin, tmp_workspace):
    f = tmp_workspace / "big.txt"
    f.write_text("\n".join(f"line{i}" for i in range(1, 101)), encoding="utf-8")
    result = await plugin.execute_tool(
        "read_text_file", {"path": str(f), "offset": 50, "limit": 2}, ctx())
    content = result.content["content"]
    assert "    50\tline50" in content and "    51\tline51" in content
    assert "line52" not in content
    assert result.content["next_offset"] == 52
    assert result.content["truncated"] is True
```

(Adatta fixture/`ctx()` allo stile già presente in `test_file_search_plugin.py`.)

- [ ] **Step 2: Run** `pytest tests/test_file_search_plugin.py -k read -v` → FAIL.

- [ ] **Step 3: Implement** — in `readers.py` il formatter (dopo il decode già esistente):

```python
def format_numbered(
    text: str, *, offset: int = 1, limit: int, max_line_chars: int,
) -> tuple[str, dict[str, int | bool]]:
    """cat -n style slice: 1-based ``offset``, ``limit`` lines, long lines capped."""
    lines = text.splitlines()
    total = len(lines)
    start = max(offset, 1) - 1
    window = lines[start:start + limit]
    rendered = []
    for i, line in enumerate(window, start=start + 1):
        if len(line) > max_line_chars:
            line = line[:max_line_chars] + " …[riga troncata]"
        rendered.append(f"{i:>6}\t{line}")
    truncated = start + len(window) < total
    meta = {
        "total_lines": total,
        "lines_read": len(window),
        "truncated": truncated,
        "next_offset": (start + len(window) + 1) if truncated else 0,
    }
    return "\n".join(rendered), meta
```

Handler: aggiungi `offset` (default 1) e `limit` (default `config.max_read_lines`) allo schema
JSON del tool (`plugin.py:189-221`) e nel payload di risposta unisci `content` numerato + meta +
`path`. Il vecchio `max_chars` resta come cap complessivo a valle (leggi → numera → cap chars).
PDF/DOCX: invariati (niente line numbers; documentalo nella descrizione del tool).

- [ ] **Step 4: Run** `pytest tests/test_file_search_plugin.py -v` → PASS (inclusi i test read
  preesistenti, aggiornati SOLO se asseriscono il vecchio formato — è un cambio di output del
  tool, atteso dalla spec §4.1).

- [ ] **Step 5: Commit** `feat(file_search): read con line numbers, offset/limit a righe e next_offset (parita Read di Claude Code)`

### Task 10: `read_text_file` — immagini

**Files:**
- Modify: `backend/plugins/file_search/plugin.py` (handler read), `readers.py`
- Modify: `backend/core/config.py` (FileSearchConfig: `max_image_bytes: int = 5_242_880`)
- Test: `backend/tests/test_file_search_plugin.py`

- [ ] **Step 1: Failing test**

```python
async def test_read_image_returns_base64(plugin, tmp_workspace):
    import base64
    png_1px = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
        "h6FO1AAAAABJRU5ErkJggg==")
    f = tmp_workspace / "dot.png"
    f.write_bytes(png_1px)
    result = await plugin.execute_tool("read_text_file", {"path": str(f)}, ctx())
    assert result.success
    assert result.content_type == "image/png"
    assert base64.b64decode(result.content) == png_1px


async def test_read_image_over_cap_fails(plugin, tmp_workspace):
    import base64
    png_1px = base64.b64decode(
        "iVBORw0KGgoAAAABAAAAAQCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
        "h6FO1AAAAABJRU5ErkJggg==")
    f = tmp_workspace / "dot.png"
    f.write_bytes(png_1px)
    plugin._config.max_image_bytes = 10  # cap sotto la dimensione del file
    result = await plugin.execute_tool("read_text_file", {"path": str(f)}, ctx())
    assert not result.success
    assert "immagine" in result.error_message.lower()
```

- [ ] **Step 2: Run** → FAIL (oggi `.png` → "estensione non supportata").

- [ ] **Step 3: Implement** — in `readers.py`:

```python
_IMAGE_CONTENT_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}
```

Nel dispatch del reader: se l'estensione è in `_IMAGE_CONTENT_TYPES`, verifica il cap
`max_image_bytes` (errore chiaro se superato), leggi i byte, `base64.b64encode(...).decode()` e
ritorna `ToolResult.ok(content=b64, content_type=_IMAGE_CONTENT_TYPES[ext])` — stesso modello di
`pc_automation.take_screenshot` (`binary_base64`, esente dal troncamento centrale in
`core/tools/execution.py:385-388`). Registra comunque la lettura nel ReadTracker (Task 11-12: un
overwrite di un'immagine letta è legittimo).

- [ ] **Step 4: Run** `pytest tests/test_file_search_plugin.py -v` → PASS.

- [ ] **Step 5: Commit** `feat(file_search): lettura immagini (png/jpg/gif/webp) via binary_base64 con cap dimensione`

### Task 11: `edit_text_file` (exact-string, unique-fail, read-tracking)

**Files:**
- Modify: `backend/plugins/file_search/plugin.py` (nuova ToolDefinition + handler + wiring del
  ReadTracker come attributo del plugin; `read_text_file` handler chiama `tracker.record`)
- Test: `backend/tests/test_file_search_plugin.py`

- [ ] **Step 1: Failing tests**

```python
async def test_edit_requires_prior_read(plugin, tmp_workspace):
    f = tmp_workspace / "a.py"; f.write_text("x = 1\n")
    result = await plugin.execute_tool(
        "edit_text_file",
        {"path": str(f), "old_string": "x = 1", "new_string": "x = 2"}, ctx())
    assert not result.success
    assert "lett" in result.error_message.lower()  # "leggi il file prima"


async def test_edit_exact_string_happy_path(plugin, tmp_workspace):
    f = tmp_workspace / "a.py"; f.write_text("x = 1\ny = 2\n")
    await plugin.execute_tool("read_text_file", {"path": str(f)}, ctx())
    result = await plugin.execute_tool(
        "edit_text_file",
        {"path": str(f), "old_string": "x = 1", "new_string": "x = 99"}, ctx())
    assert result.success
    assert f.read_text() == "x = 99\ny = 2\n"


async def test_edit_fails_on_non_unique(plugin, tmp_workspace):
    f = tmp_workspace / "a.py"; f.write_text("v\nv\n")
    await plugin.execute_tool("read_text_file", {"path": str(f)}, ctx())
    result = await plugin.execute_tool(
        "edit_text_file", {"path": str(f), "old_string": "v", "new_string": "w"}, ctx())
    assert not result.success and "2" in result.error_message  # conteggio occorrenze


async def test_edit_replace_all(plugin, tmp_workspace):
    f = tmp_workspace / "a.py"; f.write_text("v\nv\n")
    await plugin.execute_tool("read_text_file", {"path": str(f)}, ctx())
    result = await plugin.execute_tool(
        "edit_text_file",
        {"path": str(f), "old_string": "v", "new_string": "w", "replace_all": True},
        ctx())
    assert result.success and f.read_text() == "w\nw\n"


async def test_edit_fails_on_stale_read(plugin, tmp_workspace):
    f = tmp_workspace / "a.py"; f.write_text("x = 1\n")
    await plugin.execute_tool("read_text_file", {"path": str(f)}, ctx())
    f.write_text("x = 1  # cambiato fuori\n")
    result = await plugin.execute_tool(
        "edit_text_file",
        {"path": str(f), "old_string": "x = 1", "new_string": "x = 2"}, ctx())
    assert not result.success and "modificato" in result.error_message.lower()
```

- [ ] **Step 2: Run** → FAIL (tool inesistente).

- [ ] **Step 3: Implement** — ToolDefinition (accanto a `write_text_file`, `plugin.py:245-277`):
  `name="edit_text_file"`, `capabilities=("fs_write",)`, `path_args=("path",)`,
  `requires_confirmation=True`, `risk_level="medium"`, `result_type="string"`, `timeout_ms=10_000`,
  parametri `path`(req)/`old_string`(req)/`new_string`(req)/`replace_all`(bool, default false).
  Handler (stessa `_validate_path` + guardie del write: estensioni eseguibili, cap 1 MiB):

```python
    async def _edit_text_file(self, args, context) -> ToolResult:
        resolved = ...  # _validate_path come write_text_file
        state = self._read_tracker.verify(context.conversation_id, resolved)
        if state is ReadState.UNREAD:
            return ToolResult.error(
                "File mai letto in questa conversazione: leggi il file con "
                "read_text_file prima di modificarlo.")
        if state is ReadState.STALE:
            return ToolResult.error(
                "Il file è stato modificato dopo l'ultima lettura: rileggilo "
                "con read_text_file e riprova.")
        text = resolved.read_text(encoding="utf-8")
        old, new = args["old_string"], args["new_string"]
        count = text.count(old)
        if count == 0:
            return ToolResult.error("old_string non trovata nel file (0 occorrenze).")
        if count > 1 and not args.get("replace_all", False):
            return ToolResult.error(
                f"old_string non è unica ({count} occorrenze): estendi il contesto "
                "della stringa o usa replace_all=true.")
        updated = text.replace(old, new) if args.get("replace_all") \
            else text.replace(old, new, 1)
        resolved.write_text(updated, encoding="utf-8")   # stesse guardie byte-cap del write
        self._read_tracker.record(context.conversation_id, resolved)
        return ToolResult.ok(f"Edit applicato ({count if args.get('replace_all') else 1} sostituzioni).")
```

`read_text_file` handler: dopo una lettura riuscita (testo O immagine),
`self._read_tracker.record(context.conversation_id, resolved)`.

- [ ] **Step 4: Run** `pytest tests/test_file_search_plugin.py -v` → PASS.

- [ ] **Step 5: Commit** `feat(file_search): edit_text_file exact-string (unique-fail, replace_all) con guardia read-tracking`

### Task 12: Guardie su `write_text_file`

**Files:**
- Modify: `backend/plugins/file_search/plugin.py:533-590`
- Test: `backend/tests/test_file_search_plugin.py`

- [ ] **Step 1: Failing tests**

```python
async def test_write_new_file_is_free(plugin, tmp_workspace):
    f = tmp_workspace / "new.txt"
    result = await plugin.execute_tool(
        "write_text_file", {"path": str(f), "content": "hello"}, ctx())
    assert result.success and f.read_text() == "hello"


async def test_overwrite_requires_prior_read(plugin, tmp_workspace):
    f = tmp_workspace / "a.txt"; f.write_text("originale")
    result = await plugin.execute_tool(
        "write_text_file", {"path": str(f), "content": "nuovo"}, ctx())
    assert not result.success and f.read_text() == "originale"


async def test_overwrite_allowed_after_read(plugin, tmp_workspace):
    f = tmp_workspace / "a.txt"; f.write_text("originale")
    await plugin.execute_tool("read_text_file", {"path": str(f)}, ctx())
    result = await plugin.execute_tool(
        "write_text_file", {"path": str(f), "content": "nuovo"}, ctx())
    assert result.success and f.read_text() == "nuovo"
```

- [ ] **Step 2: Run** → FAIL sul secondo test (oggi l'overwrite è libero).

- [ ] **Step 3: Implement** — in `_write_text_file`, prima della scrittura
  (`plugin.py:~584`): se `resolved.exists()` e `tracker.verify(...)` non è FRESH → errore con lo
  stesso vocabolario del Task 11 (UNREAD → "leggi prima", STALE → "rileggi"). Dopo la scrittura
  riuscita: `self._read_tracker.record(context.conversation_id, resolved)`.

- [ ] **Step 4: Run** `pytest tests/test_file_search_plugin.py -v` → PASS.

- [ ] **Step 5: Commit** `feat(file_search): overwrite di file esistente solo dopo lettura (read-tracking)`

### Task 13: `glob_files`

**Files:**
- Modify: `backend/plugins/file_search/plugin.py` (ToolDefinition + handler)
- Create: la logica in `backend/plugins/file_search/searcher.py` (funzione `run_glob`)
- Test: `backend/tests/test_file_search_plugin.py`

- [ ] **Step 1: Failing tests**

```python
async def test_glob_recursive_pattern(plugin, tmp_workspace):
    (tmp_workspace / "src").mkdir()
    (tmp_workspace / "src" / "a.py").write_text("x")
    (tmp_workspace / "b.py").write_text("x")
    (tmp_workspace / "c.txt").write_text("x")
    result = await plugin.execute_tool(
        "glob_files", {"pattern": "**/*.py", "path": str(tmp_workspace)}, ctx())
    assert result.success
    paths = result.content["matches"]
    assert len(paths) == 2 and all(p.endswith(".py") for p in paths)


async def test_glob_sorted_by_mtime_desc_and_bounded(plugin, tmp_workspace):
    import os, time
    older = tmp_workspace / "old.py"; older.write_text("x")
    os.utime(older, ns=(1, 1))
    newer = tmp_workspace / "new.py"; newer.write_text("x")
    result = await plugin.execute_tool(
        "glob_files",
        {"pattern": "*.py", "path": str(tmp_workspace), "max_results": 1}, ctx())
    assert result.content["matches"] == [str(newer)]
    assert result.content["truncated"] is True
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — `run_glob` in `searcher.py` (riusa `_validate_path` per la root e
  il thread+timeout pattern di `search_files`, `searcher.py:237-247`):

```python
def run_glob(
    root: Path, pattern: str, *, max_results: int,
    forbidden: tuple[Path, ...],
) -> tuple[list[Path], bool]:
    """Glob under root, newest-first, bounded.  Returns (matches, truncated)."""
    matches: list[tuple[int, Path]] = []
    for candidate in root.glob(pattern):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if is_forbidden(resolved, forbidden):
            continue
        matches.append((resolved.stat().st_mtime_ns, resolved))
        if len(matches) >= max_results * 4:   # raccogli extra, poi ordina e taglia
            break
    matches.sort(key=lambda t: t[0], reverse=True)
    truncated = len(matches) > max_results
    return [p for _, p in matches[:max_results]], truncated
```

ToolDefinition: `capabilities=("fs_read",)`, `path_args=("path",)`, `risk_level="safe"`,
parametri `pattern`(req)/`path`(req)/`max_results`(default da `config.max_results`). Payload:
`{matches: [str], truncated: bool, root: str}` + messaggio su come restringere se troncato.

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(file_search): glob_files (pattern ** veri, newest-first, bounded)`

### Task 14: `grep_content`

**Files:**
- Create: `backend/plugins/file_search/grep.py`
- Modify: `backend/plugins/file_search/plugin.py` (ToolDefinition + handler + config)
- Modify: `backend/core/config.py` (FileSearchConfig: `grep_max_files: int = 5000`,
  `grep_max_matches: int = 200`, `grep_timeout_s: int = 20`)
- Test: `backend/tests/test_file_search_grep.py` (NUOVO)

- [ ] **Step 1: Failing tests**

```python
from pathlib import Path

from backend.plugins.file_search.grep import GrepOptions, run_grep


def _tree(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    return 42\n")
    (tmp_path / "b.py").write_text("x = 'foo bar'\n")
    (tmp_path / "c.txt").write_text("nothing here\n")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01binary")


def test_grep_files_with_matches(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"foo"))
    assert sorted(p.name for p in result.files) == ["a.py", "b.py"]
    assert not result.truncated


def test_grep_content_mode_with_context(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(
        tmp_path,
        GrepOptions(pattern=r"return", output_mode="content", context_lines=1))
    [match] = result.matches
    assert match.path.name == "a.py" and match.line_number == 2
    assert "def foo()" in match.context_before[0]


def test_grep_glob_filter(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"foo", glob="*.txt"))
    assert result.files == []


def test_grep_skips_binaries(tmp_path: Path) -> None:
    _tree(tmp_path)
    result = run_grep(tmp_path, GrepOptions(pattern=r"binary"))
    assert result.files == []


def test_grep_bounded_matches(tmp_path: Path) -> None:
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text("hit\n")
    result = run_grep(tmp_path, GrepOptions(pattern=r"hit", max_matches=5))
    assert result.truncated


def test_grep_invalid_regex_is_clean_error(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(ValueError, match="regex"):
        run_grep(tmp_path, GrepOptions(pattern=r"foo["))
```

- [ ] **Step 2: Run** `pytest tests/test_file_search_grep.py -v` → FAIL.

- [ ] **Step 3: Implement `grep.py`**

```python
"""Bounded pure-Python content grep (spec Fase 2 §4.6 — no ripgrep binary)."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.core.path_safety import is_forbidden

_BINARY_SNIFF_BYTES = 8192
_MAX_FILE_BYTES = 1_048_576  # allineato a max_file_size_read_bytes


@dataclass(frozen=True, slots=True)
class GrepOptions:
    pattern: str
    glob: str | None = None
    extensions: tuple[str, ...] = ()
    output_mode: str = "files_with_matches"  # | "content" | "count"
    context_lines: int = 0
    case_insensitive: bool = False
    max_files: int = 5000
    max_matches: int = 200


@dataclass(frozen=True, slots=True)
class GrepMatch:
    path: Path
    line_number: int
    line: str
    context_before: tuple[str, ...] = ()
    context_after: tuple[str, ...] = ()


@dataclass(slots=True)
class GrepResult:
    files: list[Path] = field(default_factory=list)
    matches: list[GrepMatch] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    files_scanned: int = 0


def _is_binary(path: Path) -> bool:
    with path.open("rb") as fh:
        return b"\x00" in fh.read(_BINARY_SNIFF_BYTES)


def run_grep(
    root: Path, options: GrepOptions,
    forbidden: tuple[Path, ...] = (),
) -> GrepResult:
    try:
        regex = re.compile(
            options.pattern, re.IGNORECASE if options.case_insensitive else 0)
    except re.error as exc:
        raise ValueError(f"regex non valida: {exc}") from exc

    result = GrepResult()
    for candidate in sorted(root.rglob("*")):
        if result.truncated or result.files_scanned >= options.max_files:
            result.truncated = True
            break
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if is_forbidden(resolved, forbidden):
            continue
        if options.glob and not fnmatch.fnmatch(candidate.name, options.glob):
            continue
        if options.extensions and candidate.suffix not in options.extensions:
            continue
        try:
            if resolved.stat().st_size > _MAX_FILE_BYTES or _is_binary(resolved):
                continue
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        result.files_scanned += 1
        lines = text.splitlines()
        file_hits = 0
        for idx, line in enumerate(lines):
            if not regex.search(line):
                continue
            file_hits += 1
            if options.output_mode == "content":
                lo = max(0, idx - options.context_lines)
                result.matches.append(GrepMatch(
                    path=resolved, line_number=idx + 1, line=line,
                    context_before=tuple(lines[lo:idx]),
                    context_after=tuple(
                        lines[idx + 1:idx + 1 + options.context_lines]),
                ))
            if len(result.matches) >= options.max_matches:
                result.truncated = True
                break
        if file_hits:
            result.files.append(resolved)
            result.counts[str(resolved)] = file_hits
    return result
```

Handler nel plugin: valida `path` con `_validate_path`, esegue `run_grep` in thread con timeout
`grep_timeout_s` (stesso pattern `asyncio.to_thread` + `wait_for` di `search_files`), payload
JSON per output_mode con `truncated` + suggerimento ("restringi con glob/extensions o un pattern
più specifico"). ToolDefinition: `capabilities=("fs_read",)`, `path_args=("path",)`, safe.

- [ ] **Step 4: Run** `pytest tests/test_file_search_grep.py tests/test_file_search_plugin.py -v` → PASS.

- [ ] **Step 5: Commit** `feat(file_search): grep_content pure-Python bounded (regex, glob/ext filter, context, 3 output mode)`

### Task 15: `usage_guidance` + messaggi di troncamento coordinati

**Files:**
- Modify: `backend/plugins/file_search/plugin.py` (campo `usage_guidance` su tutti i tool del plugin)
- Modify: `backend/plugins/terminal/plugin.py:85-127` (guidance del tool exec)
- Test: `backend/tests/test_file_search_plugin.py` (assert sulle definizioni)

- [ ] **Step 1: Failing test** — le definizioni dei tool nuovi/potenziati hanno
  `usage_guidance` non-None e coerente:

```python
def test_tool_definitions_carry_usage_guidance(plugin):
    tools = {t.name: t for t in plugin.get_tools()}
    for name in ("read_text_file", "edit_text_file", "write_text_file",
                 "glob_files", "grep_content", "search_files"):
        assert tools[name].usage_guidance, f"{name} senza usage_guidance"
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** — guidance in italiano, una frase densa per
  tool (il meccanismo `[ORCHESTRAZIONE]` esiste già, `core/tool_registry.py:296-324`). Contenuti
  minimi: read → "usa offset/limit per file lunghi, il risultato è numerato per riga";
  edit → "preferiscilo a write_text_file per modifiche puntuali; serve una lettura precedente;
  old_string deve essere unica"; write → "overwrite totale, solo file letti prima; per modifiche
  puntuali usa edit_text_file"; glob → "pattern `**/*.ext` per trovare file per nome";
  grep → "cerca nei CONTENUTI (regex); per i nomi file usa glob_files/search_files";
  search → "ricerca per NOME file"; terminal → "unica via di esecuzione comandi; l'output è
  bounded". Per il troncamento: verifica che i payload di read (Task 9), glob (13), grep (14)
  dicano COME riprendere — già previsto nei task; qui aggiungi solo ciò che manca.

- [ ] **Step 4: Run** `pytest tests/test_file_search_plugin.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(tools): usage_guidance per i tool file/exec (orchestrazione)`

## Blocco D — Exec unificato

### Task 16: Ritiro di `pc_automation.execute_command`

**Files:**
- Modify: `backend/plugins/pc_automation/plugin.py:217-244` (ToolDefinition) + handler
  (`:367-372`) + `backend/plugins/pc_automation/executor.py:472` (`exec_command`)
- Modify: `backend/plugins/pc_automation/security.py` (`command_paths_within_workspace` se
  resta orfana)
- Modify: `backend/core/config.py` (`max_command_output_chars` fuori da PcAutomationConfig) +
  `config/default.yaml:122`
- Modify: strip della chiave dai layer persistiti — grep `_REMOVED_LEGACY_KEYS` (meccanismo già
  usato per `agent.engine` in Fase 1) e aggiungi `pc_automation.max_command_output_chars`
- Test: suite pc_automation esistente (rimuovi i test di execute_command, aggiungi il test "il
  tool NON esiste più")

- [ ] **Step 1: Failing test**

```python
def test_execute_command_retired(plugin):
    names = {t.name for t in plugin.get_tools()}
    assert "execute_command" not in names
    assert "open_application" in names  # il lancio app resta
```

- [ ] **Step 2: Run** → FAIL (il tool esiste ancora).

- [ ] **Step 3: Implement** — rimuovi ToolDefinition, handler, `exec_command`, i suoi test e la
  config; `command_paths_within_workspace` si rimuove SOLO se nessun altro la usa (grep). Strip
  key legacy. `open_application` e gli altri 8 tool restano invariati.

- [ ] **Step 4: Run** `pytest tests/ -k "pc_automation" -v` → PASS;
  `rg "execute_command|exec_command|max_command_output_chars" backend/ config/` → zero residui
  (fuori da CHANGELOG/docs).

- [ ] **Step 5: Commit** `refactor(exec)!: ritirato pc_automation.execute_command - run_terminal_command unica via di esecuzione (una capability, una implementazione)`

## Blocco E — Eval mock + gate di mossa

### Task 17: Scenari eval `fs-edit` / `fs-glob` / `fs-grep` (subset mock CI)

**Files:**
- Create: scenari nuovi in `backend/evals/` accanto agli `fs-*` esistenti (COPIA la struttura di
  uno scenario `fs-` esistente: stesso formato dichiarativo, stessi check deterministici)
- Modify: `backend/tests/evals/` (subset mock: script LLM che chiama i tool nuovi)
- Test: `pytest tests/evals/ -v`

- [ ] **Step 1:** Leggi 2 scenari `fs-*` esistenti per il formato (prompt, fixture workspace,
  check). Definisci: `fs-edit-exact` (fixture: file con 2 occorrenze di una stringa; successo =
  il file finale contiene la modifica GIUSTA — il modello deve estendere il contesto o usare
  replace_all consapevolmente), `fs-glob` (successo = la risposta cita i file `.py` attesi e non
  quelli esclusi), `fs-grep` (successo = la risposta individua il file che contiene il pattern).
- [ ] **Step 2:** Aggiungi i 3 scenari al subset mock CI con script LLM deterministici
  (`ScriptedLLMShim` o l'equivalente del harness eval — vedi `backend/tests/evals/` esistente).
  Run: `pytest tests/evals/ -v` → i nuovi scenari PASSANO col mock.
- [ ] **Step 3:** Scenario mock del perimetro MCP (spec §8): uno scenario `mcp-gate` nel subset
  mock in cui lo script LLM invoca un tool MCP finto NON annotato in tier `strict` — successo =
  il turno headless produce una DENIAL/auto-decline (il runner headless usa
  `AutoDeclineInteractionPort`: la conferma richiesta diventa un rifiuto pulito, quindi il check
  deterministico è "il tool NON è stato eseguito e il turno chiude senza side-effect"). Il tool
  MCP finto si registra costruendo la `ToolDefinition` con `map_mcp_tool` su un
  `mcp.types.Tool` senza annotations (coerenza col Task 2).
- [ ] **Step 4:** NON eseguire il run eval a pagamento (solo con OK utente, a fine fase).
- [ ] **Step 5: Commit** `test(evals): scenari fs-edit/fs-glob/fs-grep + mcp-gate nel subset mock (i tool nuovi e il perimetro entrano nel metro)`

### Task 18: Gate di mossa

- [ ] **Step 1:** Da `backend/` (venv assoluto attivo), in sequenza (MAI concorrenti):
  - `pytest tests/agent/ tests/evals/ tests/contracts/ -v` → tutti PASS
  - `pytest tests/test_file_search_plugin.py tests/test_file_search_grep.py tests/test_file_search_read_tracker.py tests/test_path_safety.py tests/test_mcp_tool_mapping.py tests/test_mcp_client_plugin.py tests/test_mcp_session.py tests/test_permission_mcp_perimeter.py tests/test_permission_service.py tests/test_permission_tiers.py tests/test_permission_mode_policy.py tests/test_permission_scope_confinement.py tests/test_terminal_plugin.py tests/test_terminal_security.py -v` → PASS
  - `pytest tests/ -k "pc_automation" -v` → PASS
- [ ] **Step 2:** `ruff check .` → 0; `mypy` sui file toccati (parità: zero errori NUOVI).
- [ ] **Step 3:** Dal repo root: `lint-imports --config backend/pyproject.toml` → 6 kept, 0 broken.
- [ ] **Step 4:** `.\scripts\check-contracts.ps1` → verde (questa mossa NON tocca il wire: se il
  check segnala drift, qualcosa è andato storto — indagare, non rigenerare alla cieca).
- [ ] **Step 5:** Aggiorna il ledger `.superpowers/sdd/progress.md` (cronaca task-per-task con i
  "perché") e committa eventuali residui. NON aggiornare CLAUDE.md/handoff qui: si fa a fine
  fase (Mossa 2).

---

## Cosa NON fa questa mossa (→ Mossa 2, piano separato)

- Campo wire `tool_meta` su `interaction.requested` (rituale contratti completo) + badge FE.
- `GET /api/tools/catalog` + picker in `PermissionRulesManager.vue`.
- Pannello MCP in Impostazioni + `response_model` sulle route `/api/mcp/*`.
- Diff preview degli edit nel dialogo di conferma.
- Eval a pagamento di chiusura fase, CLAUDE.md/flag-registry finali, handoff di fase.
