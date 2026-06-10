# Fase 1a — Contratti REST (codegen OpenAPI offline) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** I tipi TypeScript del confine REST frontend↔backend diventano artefatti generati dallo schema OpenAPI (prodotto offline, senza server avviato), con un test "ratchet" che impedisce nuovi endpoint senza `response_model` Pydantic.

**Architecture:** Un modulo backend (`backend/api/openapi_export.py`) costruisce l'app FastAPI senza lifespan e serializza `app.openapi()` in JSON deterministico, committato in `frontend/src/renderer/src/types/generated/openapi.json`. `openapi-typescript` lo trasforma in `api.d.ts` (committato anch'esso). Due script PowerShell orchestrano rigenerazione e verifica di staleness. Un test pytest congela le violazioni `response_model` attuali in una baseline che può solo restringersi. Una conversione esemplare (permission-mode + scope) dimostra il loop end-to-end.

**Tech Stack:** Python 3.11+/FastAPI/Pydantic v2/pytest (backend), openapi-typescript v7 (npm devDependency), PowerShell 5.1 (script), vue-tsc per il gate di typecheck.

**Riferimento spec:** `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` §6 (REST) e §9. Lo schema WS tipizzato è il piano separato "Fase 1b" (non in questo piano).

**Contesto repo (verificato il 2026-06-10):**
- Venv: `.\.venv\` alla radice del repo; backend installato editable; convenzione import `from backend....`
- `create_app(testing=True)` (`backend/core/app.py:838`) NON istanzia servizi (tutto nel lifespan) → l'export offline è fattibile; pattern già usato da `backend/tests/conftest.py`.
- Test backend: si lanciano da `backend/` (`pytest tests/ -v`); config in `pyproject.toml` (`testpaths=["tests"]`, asyncio auto, ruff line-length 100, mypy strict).
- Frontend: script npm in `frontend/package.json` (verificati); eslint flat config `frontend/eslint.config.mjs` (ignores a riga 8); `frontend/.prettierignore` esiste.
- `GET /api/health` esiste (`backend/api/routes/__init__.py:39`) — usato come asserzione nei test.
- `scope.py` e `permission_mode.py` hanno GIÀ `response_model` su tutti gli endpoint (verificato leggendo i file — NON fidarsi della tabella di audit per i singoli file: la baseline va generata meccanicamente, mai scritta a mano).

---

### Task 1: Modulo export OpenAPI offline

**Files:**
- Create: `backend/api/openapi_export.py`
- Test: `backend/tests/contracts/test_openapi_export.py`

- [ ] **Step 1: Scrivere il test che fallisce**

Creare `backend/tests/contracts/test_openapi_export.py` (creare anche la directory `backend/tests/contracts/`, senza `__init__.py`, coerente con `tests/`):

```python
"""Contract tests: offline OpenAPI export."""

from __future__ import annotations

import json
from pathlib import Path

from backend.api.openapi_export import build_schema, main


def test_build_schema_has_expected_shape() -> None:
    """The schema is OpenAPI 3.x and contains a known route."""
    schema = build_schema()
    assert str(schema["openapi"]).startswith("3.")
    assert "/api/health" in schema["paths"]


def test_main_writes_deterministic_json(tmp_path: Path) -> None:
    """Two consecutive exports produce byte-identical output."""
    out = tmp_path / "openapi.json"
    assert main([str(out)]) == 0
    first = out.read_text(encoding="utf-8")
    assert main([str(out)]) == 0
    assert out.read_text(encoding="utf-8") == first
    parsed = json.loads(first)
    assert "/api/health" in parsed["paths"]
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run (da `backend/`): `pytest tests/contracts/test_openapi_export.py -v`
Expected: FAIL/ERROR con `ModuleNotFoundError: No module named 'backend.api.openapi_export'`

- [ ] **Step 3: Implementare il modulo**

Creare `backend/api/openapi_export.py`:

```python
"""AL\\CE — Offline OpenAPI schema export (no server, no lifespan).

Phase-1 contract tooling: builds the FastAPI app object only (services are
initialized in the lifespan, which never runs here) and serializes
``app.openapi()`` deterministically (sorted keys, stable indentation) so the
schema can be committed and consumed as codegen input by the frontend
(``openapi-typescript`` via ``scripts/gen-contracts.ps1``).

Usage (from the repo root, venv active)::

    python -m backend.api.openapi_export frontend/src/renderer/src/types/generated/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def build_schema() -> dict[str, Any]:
    """Build the OpenAPI schema without starting any service.

    Returns:
        The OpenAPI document as a plain dict, exactly as FastAPI generates it.
    """
    from backend.core.app import create_app

    app = create_app(testing=True)
    return app.openapi()


def main(argv: list[str]) -> int:
    """Write the schema as stable JSON to ``argv[0]`` (default ``./openapi.json``).

    Args:
        argv: CLI arguments (without the program name).

    Returns:
        Process exit code (0 on success).
    """
    out = Path(argv[0]) if argv else Path("openapi.json")
    schema = build_schema()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Eseguire il test e verificare che passi**

Run (da `backend/`): `pytest tests/contracts/test_openapi_export.py -v`
Expected: 2 PASS

- [ ] **Step 5: Lint e typecheck dei file nuovi**

Run (da `backend/`): `ruff check api/openapi_export.py tests/contracts/; mypy api/openapi_export.py`
Expected: nessun errore (eventuali errori mypy/ruff vanno corretti prima di proseguire)

- [ ] **Step 6: Commit**

```powershell
git add backend/api/openapi_export.py backend/tests/contracts/test_openapi_export.py
git commit -m "feat(contracts): offline OpenAPI export module (no server needed)"
```

---

### Task 2: Test ratchet per i `response_model`

**Files:**
- Test: `backend/tests/contracts/test_response_models.py`
- Create (generato dal test stesso): `backend/tests/contracts/response_model_baseline.txt`

- [ ] **Step 1: Scrivere il test (fallisce finché non esiste la baseline)**

Creare `backend/tests/contracts/test_response_models.py`:

```python
"""Contract ratchet: every /api endpoint must declare a Pydantic response model.

The baseline file freezes today's violations. The test fails when:

* a NEW untyped endpoint appears (fix it: declare ``response_model``), or
* a baseline entry becomes typed (good: delete that line from the baseline).

Policy: only a named Pydantic model (or ``list[Model]``) counts as typed.
Schema-producing generics (``Model | None``, unions, ``dict[str, Model]``) are
deliberately rejected: the generated TS contract is built from named
components. Endpoints declaring ``response_class=FileResponse`` in the route
decorator are exempt (no JSON contract to declare); endpoints that merely
*return* a ``FileResponse`` from the body stay in the baseline until their
decorator is fixed. WebSocket routes are not ``APIRoute`` and are skipped.

Regenerating the baseline (ONLY when intentionally shrinking it) rewrites the
file and then FAILS on purpose so a leaked env var can never turn the
guardrail green — inspect the diff and rerun WITHOUT the env var (PowerShell)::

    $env:ALICE_REGEN_CONTRACT_BASELINE = "1"
    pytest tests/contracts/test_response_models.py
    Remove-Item Env:\\ALICE_REGEN_CONTRACT_BASELINE
"""

from __future__ import annotations

import os
import typing
from pathlib import Path

import pytest
from backend.core.app import create_app
from fastapi.datastructures import DefaultPlaceholder
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.responses import FileResponse

BASELINE = Path(__file__).parent / "response_model_baseline.txt"


def _is_typed(route: APIRoute) -> bool:
    """True when the route declares a Pydantic response contract.

    Accepts a ``BaseModel`` subclass or ``list[BaseModel]``; anything else
    (including ``dict`` annotations and unions) does NOT count.
    """
    model = route.response_model
    if model is None:
        return False
    if typing.get_origin(model) is list:
        args = typing.get_args(model)
        return bool(args) and isinstance(args[0], type) and issubclass(args[0], BaseModel)
    return isinstance(model, type) and issubclass(model, BaseModel)


def _is_exempt(route: APIRoute) -> bool:
    """File/stream endpoints (decorator-declared ``response_class``) are exempt."""
    response_class: object = route.response_class
    if isinstance(response_class, DefaultPlaceholder):
        response_class = response_class.value
    return isinstance(response_class, type) and issubclass(response_class, FileResponse)


def _violations() -> set[str]:
    """Collect ``"METHOD /api/path"`` keys for every untyped endpoint."""
    app = create_app(testing=True)
    found: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
            continue
        if _is_exempt(route) or _is_typed(route):
            continue
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            found.add(f"{method} {route.path}")
    return found


def test_all_api_routes_under_prefix() -> None:
    """Every APIRoute lives under /api — anything else would escape the ratchet."""
    app = create_app(testing=True)
    escaped = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and not route.path.startswith("/api")
    ]
    assert not escaped, f"APIRoutes outside /api escape the contract ratchet: {escaped}"


def test_response_model_ratchet() -> None:
    """No new untyped endpoints; baseline entries must be removed once fixed."""
    current = _violations()
    if os.environ.get("ALICE_REGEN_CONTRACT_BASELINE") == "1":
        BASELINE.write_text(
            "\n".join(sorted(current)) + "\n", encoding="utf-8", newline="\n",
        )
        pytest.fail("Baseline regenerated. Inspect the diff, then rerun WITHOUT the env var.")
    baseline = {
        line.strip()
        for line in BASELINE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    new = current - baseline
    fixed = baseline - current
    assert not new, f"New endpoints without a Pydantic response_model: {sorted(new)}"
    assert not fixed, (
        "Endpoints now typed — delete these lines from response_model_baseline.txt: "
        f"{sorted(fixed)}"
    )
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run (da `backend/`): `pytest tests/contracts/test_response_models.py -v`
Expected: FAIL con `FileNotFoundError` su `response_model_baseline.txt` (la baseline non esiste ancora)

- [ ] **Step 3: Generare la baseline meccanicamente**

Run (da `backend/`):

```powershell
$env:ALICE_REGEN_CONTRACT_BASELINE = "1"
pytest tests/contracts/test_response_models.py -v
Remove-Item Env:\ALICE_REGEN_CONTRACT_BASELINE
```

Expected: FAIL INTENZIONALE con "Baseline regenerated. Inspect the diff, then rerun WITHOUT the env var." — il file `backend/tests/contracts/response_model_baseline.txt` ora esiste (LF, ~70-90 righe ordinate `GET /api/...`). Il numero esatto è quello calcolato — NON va aggiustato a mano.

- [ ] **Step 4: Eseguire di nuovo il test senza la variabile e verificare che passi**

Run (da `backend/`): `pytest tests/contracts/test_response_models.py -v`
Expected: PASS

- [ ] **Step 5: Lint e typecheck**

Run (da `backend/`): `ruff check tests/contracts/; mypy tests/contracts/test_response_models.py`
Expected: nessun errore

- [ ] **Step 6: Commit**

```powershell
git add backend/tests/contracts/test_response_models.py backend/tests/contracts/response_model_baseline.txt
git commit -m "test(contracts): response_model ratchet with frozen baseline"
```

---

### Task 3: Pipeline di generazione frontend (openapi-typescript + script)

**Files:**
- Modify: `frontend/package.json` (devDependency + script)
- Modify: `frontend/eslint.config.mjs:8` (ignores)
- Modify: `frontend/.prettierignore`
- Create: `scripts/gen-contracts.ps1`
- Create: `scripts/check-contracts.ps1`
- Create (generati): `frontend/src/renderer/src/types/generated/openapi.json`, `frontend/src/renderer/src/types/generated/api.d.ts`
- Create: `frontend/src/renderer/src/types/generated/index.ts`

- [ ] **Step 1: Installare openapi-typescript**

Run (da `frontend/`): `npm install --save-dev openapi-typescript`
Expected: exit 0; `package.json` e `package-lock.json` aggiornati con `openapi-typescript` in devDependencies (v7.x)

- [ ] **Step 2: Aggiungere lo script npm**

In `frontend/package.json`, nel blocco `"scripts"`, aggiungere dopo la riga `"build:installer"`:

```json
    "gen:api:types": "openapi-typescript src/renderer/src/types/generated/openapi.json -o src/renderer/src/types/generated/api.d.ts"
```

(attenzione alla virgola sulla riga precedente)

- [ ] **Step 3: Escludere i generati da eslint e prettier**

In `frontend/eslint.config.mjs` riga 8, sostituire:

```js
  { ignores: ['**/node_modules', '**/dist', '**/out'] },
```

con:

```js
  { ignores: ['**/node_modules', '**/dist', '**/out', 'src/renderer/src/types/generated/api.d.ts'] },
```

In `frontend/.prettierignore` aggiungere in coda le righe:

```
src/renderer/src/types/generated/openapi.json
src/renderer/src/types/generated/api.d.ts
```

(Nota: `index.ts` è il file scritto a mano e deve restare sotto lint e prettier.)

- [ ] **Step 4: Creare lo script di rigenerazione**

Creare `scripts/gen-contracts.ps1`:

```powershell
# Regenerates the FE<->BE contract artifacts:
#   1. backend OpenAPI schema -> frontend/src/renderer/src/types/generated/openapi.json
#   2. openapi-typescript     -> frontend/src/renderer/src/types/generated/api.d.ts
# Run from anywhere; requires the repo venv (.venv) and frontend npm deps installed.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv python not found at $python - run scripts\setup.ps1 first" }
$schemaPath = Join-Path $repoRoot "frontend\src\renderer\src\types\generated\openapi.json"

Push-Location $repoRoot
try {
    & $python -m backend.api.openapi_export $schemaPath
    if ($LASTEXITCODE -ne 0) { throw "OpenAPI export failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Push-Location (Join-Path $repoRoot "frontend")
try {
    npm run gen:api:types
    if ($LASTEXITCODE -ne 0) { throw "openapi-typescript failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Host "Contracts regenerated." -ForegroundColor Green
```

- [ ] **Step 5: Creare lo script di verifica staleness**

Creare `scripts/check-contracts.ps1`:

```powershell
# Fails when the committed contract artifacts are stale (i.e. regenerating
# them produces a diff). Intended as a local/CI gate.
# NOTE: never hand-merge the generated files on conflicts - regenerate instead.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

& (Join-Path $PSScriptRoot "gen-contracts.ps1")

Push-Location $repoRoot
try {
    $generated = @(
        "frontend/src/renderer/src/types/generated/openapi.json",
        "frontend/src/renderer/src/types/generated/api.d.ts"
    )
    $dirty = git status --porcelain -- $generated
    if ($LASTEXITCODE -ne 0) { throw "git status failed (exit $LASTEXITCODE)" }
    if ($dirty) {
        $dirty | Write-Host
        throw "Contract artifacts are stale: run scripts/gen-contracts.ps1 and commit the result."
    }
} finally {
    Pop-Location
}

Write-Host "Contracts are up to date." -ForegroundColor Green
```

- [ ] **Step 6: Prima generazione**

Run (da qualunque cwd): `.\scripts\gen-contracts.ps1`
Expected: `Contracts regenerated.`; esistono `frontend/src/renderer/src/types/generated/openapi.json` (JSON, contiene `"/api/health"`) e `api.d.ts` (inizia con il commento di auto-generazione di openapi-typescript ed esporta `paths` e `components`)

- [ ] **Step 7: Creare il modulo alias sui tipi generati**

Creare `frontend/src/renderer/src/types/generated/index.ts`:

```typescript
/**
 * Hand-written aliases over the GENERATED OpenAPI types (./api).
 *
 * `./openapi.json` and `./api.d.ts` are build artifacts: regenerate them with
 * `scripts/gen-contracts.ps1` — NEVER edit them by hand. This index is the only
 * hand-written file in this directory.
 */
import type { components } from './api'

/** Resolve a backend Pydantic model by its OpenAPI component name. */
export type ApiSchema<K extends keyof components['schemas']> = components['schemas'][K]
```

- [ ] **Step 8: Typecheck**

Run (da `frontend/`): `npm run typecheck`
Expected: exit 0 (il file generato compila; nessun consumatore è ancora cambiato)

- [ ] **Step 9: Verifica del gate di staleness**

Run: `.\scripts\check-contracts.ps1`
Expected: `Contracts are up to date.` — ATTENZIONE: il check passa solo DOPO il commit dello Step 10 (i file appena creati risultano untracked e quindi "dirty"). Eseguire questo step DOPO il commit, oppure aspettarsi il fallimento qui e rieseguire dopo il commit.

- [ ] **Step 10: Commit (poi rieseguire lo Step 9)**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/eslint.config.mjs frontend/.prettierignore scripts/gen-contracts.ps1 scripts/check-contracts.ps1 frontend/src/renderer/src/types/generated
git commit -m "feat(contracts): OpenAPI->TS codegen pipeline with staleness gate"
.\scripts\check-contracts.ps1
```

Expected: commit creato; poi `Contracts are up to date.`

---

### Task 4: Conversione esemplare end-to-end (permission-mode + scope)

Dimostra il loop completo: miglioramento del contratto backend → rigenerazione → il frontend consuma i tipi generati. `scope.py` e `permission_mode.py` hanno già `response_model`; l'unico miglioramento backend è tipizzare `mode` come enum (oggi `str`), che nel TS generato diventa l'unione letterale `'strict' | 'auto_edits' | 'plan' | 'autopilot'`.

**Files:**
- Modify: `backend/api/routes/permission_mode.py` (campo `mode: str` → `mode: PermissionMode`)
- Modify: `frontend/src/renderer/src/types/permission.ts` (re-export dei tipi generati)
- Modify: `frontend/src/renderer/src/types/scope.ts` (re-export di `ScopeResponse`)
- Regenerate: `frontend/src/renderer/src/types/generated/*`

- [ ] **Step 1: Tipizzare l'enum nel response model backend**

In `backend/api/routes/permission_mode.py`, classe `PermissionModeResponse` (righe 41-50), sostituire:

```python
    conversation_id: str
    mode: str
```

con:

```python
    conversation_id: str
    mode: PermissionMode
```

Poi aggiornare i tre punti di costruzione della risposta:
- `get_permission_mode`, ramo `service is None` (riga ~126): `mode=PermissionMode.STRICT.value` → `mode=PermissionMode.STRICT`
- `get_permission_mode`, ritorno finale (riga ~130): `mode=mode.value` → `mode=mode`
- `put_permission_mode`, ritorno finale (riga ~175): `mode=mode.value` → `mode=mode`

(Il JSON sul filo non cambia: l'enum è una `StrEnum` e serializza al suo valore. Aggiornare la docstring del campo se cita "stringa".)

- [ ] **Step 2: Verificare che i test backend restino verdi**

Run (da `backend/`): `pytest tests/ -v`
Expected: tutti PASS (nessun cambiamento di formato sul filo). Se un test asserisce esplicitamente il tipo `str` del campo, aggiornarlo all'enum value — il JSON resta identico.

- [ ] **Step 3: Rigenerare i contratti**

Run: `.\scripts\gen-contracts.ps1`
Expected: `Contracts regenerated.`; in `api.d.ts` il componente `PermissionMode` è ora un'unione di letterali `'strict' | 'auto_edits' | 'plan' | 'autopilot'`

- [ ] **Step 4: Far consumare i tipi generati al frontend**

In `frontend/src/renderer/src/types/permission.ts`: eliminare le definizioni locali di `PermissionMode` e `PermissionModeResponse` e sostituirle con:

```typescript
import type { ApiSchema } from './generated'

/** Generated from the backend contract — do not redefine locally. */
export type PermissionMode = ApiSchema<'PermissionMode'>
export type PermissionModeResponse = ApiSchema<'PermissionModeResponse'>
```

Tutto il resto del file (`WsPermissionModeUpdatedMessage`, `PermissionRule`, `PermissionRuleCreate`, ecc.) resta invariato — i tipi WS migrano nel piano 1b.

In `frontend/src/renderer/src/types/scope.ts`: eliminare la definizione locale di `ScopeResponse` e sostituirla con:

```typescript
import type { ApiSchema } from './generated'

/** Generated from the backend contract — do not redefine locally. */
export type ScopeResponse = ApiSchema<'ScopeResponse'>
```

(`WsScopeUpdatedMessage` resta invariato.)

- [ ] **Step 5: Typecheck e lint frontend**

Run (da `frontend/`): `npm run typecheck; if ($?) { npm run lint }`
Expected: entrambi exit 0. Se il typecheck segnala consumatori incompatibili (es. confronti con letterali non previsti), sono veri drift trovati dal compilatore: allineare il consumatore al contratto generato, non viceversa.

- [ ] **Step 6: Commit**

```powershell
git add backend/api/routes/permission_mode.py frontend/src/renderer/src/types/permission.ts frontend/src/renderer/src/types/scope.ts frontend/src/renderer/src/types/generated
git commit -m "feat(contracts): permission-mode enum in contract; FE consumes generated types (exemplar)"
```

---

### Task 5: Documentazione e verifica finale

**Files:**
- Modify: `CLAUDE.md` (sezioni Commands e Conventions)

- [ ] **Step 1: Documentare i comandi in CLAUDE.md**

In `CLAUDE.md`, nella sezione `## Commands`, aggiungere dopo il blocco "One-shot setup / dev":

````markdown
### Contracts (FE<->BE codegen)
```powershell
.\scripts\gen-contracts.ps1      # regenerate OpenAPI schema + generated TS types
.\scripts\check-contracts.ps1    # fail if committed contract artifacts are stale
```
````

Nella sezione `## Conventions`, aggiungere il bullet:

```markdown
- **Contracts are generated**: new/changed REST endpoints must declare a Pydantic `response_model` (ratchet test in `backend/tests/contracts/`) and require regenerating contracts (`.\scripts\gen-contracts.ps1`). Files in `frontend/src/renderer/src/types/generated/` are build artifacts — never edit them by hand (except `index.ts`).
```

- [ ] **Step 2: Verifica finale completa**

```powershell
cd backend; pytest tests/ -v          # Expected: tutti PASS
cd backend; ruff check .; mypy api/openapi_export.py tests/contracts/
.\scripts\check-contracts.ps1         # Expected: "Contracts are up to date."
cd frontend; npm run typecheck        # Expected: exit 0
cd frontend; npm run lint             # Expected: exit 0
```

- [ ] **Step 3: Commit**

```powershell
git add CLAUDE.md
git commit -m "docs: contract codegen commands and conventions"
```

---

## Criteri di uscita della fase (dalla spec §9)

1. Tutti i test backend verdi, `npm run typecheck` verde.
2. `.\scripts\check-contracts.ps1` verde su working tree pulito.
3. App avviabile (`.\scripts\start-dev.ps1`) e feature esemplare funzionante: cambiare il permission mode da Horizon e verificare che la UI rifletta il valore (il payload sul filo è invariato, quindi è una verifica di regressione).
4. Enforcement consegnato: test ratchet + check-contracts (da agganciare a una futura CI; oggi non esistono workflow).
