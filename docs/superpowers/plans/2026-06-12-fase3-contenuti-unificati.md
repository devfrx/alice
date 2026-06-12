# Fase 3 — Contenuti unificati (Artifact generalizzato) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** chart, whiteboard e modelli 3D diventano *kind* di un solo `Artifact` (metadati in SQLite, blob JSON su disco in `data/artifacts/<kind>/`): UN registry (`ArtifactRegistry` generalizzato con blob store), UNA famiglia di route `/api/artifacts`, UN solo store FE con viewer per kind. `ChartStore`, `WhiteboardStore`, le route `/api/charts` e `/api/whiteboards` e gli store Pinia `charts`/`whiteboard` vengono assorbiti ed eliminati (spec §5.2, secondo bullet).

**Architecture:** il registry esistente (già generico: riga DB + `file_path` + parsers per i tool CAD) guadagna un `ArtifactBlobStore` per i contenuti JSON e metodi `create_json_artifact` / `read_json_content` / `update_json_artifact` / `count_artifacts` / `delete_for_conversation` / `delete_all`. I plugin chart e whiteboard restano i proprietari della *capability* (tool, validazione, shape building) ma delegano TUTTA la persistenza al registry via `ctx.artifact_registry` (§1 della spec: una sola implementazione). Le route artifacts guadagnano `GET/PATCH /{id}/content` tipizzate; la pulizia file-artifact inline in `conversations.py` viene assorbita dal registry (finding review fase 2). Lato FE lo store `artifacts` diventa l'unico store contenuti (cache contenuti JSON inclusa), i viewer per kind esistenti (ChartViewer, TldrawCanvas, CADViewer) restano e si riagganciano.

**Tech Stack:** FastAPI + Pydantic (response models), SQLModel/aiosqlite, plugin system AL\CE, ws_schema 1b (envelope piatto + vocabolario congelato), openapi-typescript, Vue 3 + Pinia + vitest.

**Branch:** `arch/fase3-contenuti` (figlio di `arch/fase2-persistenza`).

---

## Contesto verificato (recon 2026-06-12, a mano)

**Già unificato (non rifare):**
- `Artifact`/`ArtifactKind` in `backend/db/models.py:291-388` — modello già generico (id, conversation_id FK SET NULL, message_id, tool_call_id, kind, title 256, file_path relativo a PROJECT_ROOT, mime, size_bytes, artifact_metadata JSON, pinned, created_at/updated_at, indici per conv e kind). Kind attuali: solo `CAD_3D_TEXT`/`CAD_3D_IMAGE`.
- `backend/services/artifacts/` — `registry.py` (CRUD righe + evento `artifact.created` via callback broadcast, wired in `core/app.py:628-638`), `parsers.py` (parser per tool-name, solo CAD), `schemas.py` (`ArtifactRead` con `download_url` computed, `ArtifactListResponse {items,total}`, `ArtifactPinUpdate`), hook nel tool loop (`services/turn/tool_loop.py:608-650`, usa `raw_content` e risolve il bare tool name).
- Route `/api/artifacts` (`api/routes/artifacts.py`) — list/get/pin tipizzate; in baseline ratchet restano `DELETE /api/artifacts/{artifact_id}` (204 senza body) e `GET .../download` (FileResponse binaria): LEGITTIME, non bruciarle.
- WS: `WsArtifactCreated` in `api/ws_schema/events.py:157-164`, union a riga 363; FE `useEventsWebSocket.ts:97` (`artifact.created` → `artifactsStore.fetchById`); store FE `stores/artifacts.ts` (items/byKind/pinned/togglePin/remove, `byToolCallId` usato da `MessageBubble.vue:163`).
- Test esistenti: `tests/test_artifact_registry.py` (fixture session_factory in-memory + registry con captured_events), `tests/test_artifacts_route.py` (fixture `app`/`client`, LENTE ~25s l'una — aggiungere al massimo 2 test), `tests/contracts/test_ws_schema_events.py` (vocabolario congelato `EXPECTED_EVENTS_SERVER_TYPES` riga 23 + frame rappresentativi riga 56).

**Da assorbire (i tre sistemi paralleli):**
- Chart: `plugins/chart_generator/` — `chart_store.py` (JSON per-file in `data/charts/`, id stringa sanitizzata), `plugin.py` (5 tool: generate/update/get/list/delete; handler con firma `(args)` SENZA context; payload `ChartPayload` con `chart_url=f"/api/charts/{id}"`, content_type `application/vnd.alice.chart+json`; limiti `cfg.max_option_chars`, `cfg.max_charts`; `option_validator.py` resta), `models.py` (ChartSpec/ChartPayload/ChartListItem). Route `api/routes/charts.py` (3 endpoint NON tipizzati, in baseline; legge `plugin.store` via plugin_manager — violazione §4). Config: `ChartConfig` (`core/config.py:716-731`, `chart_output_dir` da rimuovere), `config/default.yaml:280-285`.
- Whiteboard: `plugins/whiteboard/` — `store.py` (JSON per-file in `data/whiteboards/`, `update_snapshot`, conteggio shape da snapshot tldraw), `plugin.py` (6 tool: create/get/add_shapes/update/list/delete; handler firma `(args, context)`; `context.conversation_id` come default per create/list; `shape_builder.py` resta; `_extract_shapes_summary` resta), `models.py` (SimpleShape/WhiteboardSpec/WhiteboardPayload/WhiteboardListItem). Route `api/routes/whiteboards.py` (4 endpoint NON tipizzati, in baseline; PATCH snapshot con guardia 5 MiB; lista con join titolo conversazione dal DB). Config: `WhiteboardConfig` (`core/config.py:734-746`, `whiteboard_output_dir` da rimuovere), `config/default.yaml:288-295`. Test `tests/test_whiteboard_route_scope.py` (testa la route che muore → eliminare).
- Consumatori del whiteboard store FUORI dal plugin: `_build_whiteboard_context` in `api/routes/chat/_helpers.py:305-357` (system prompt; chiamata da `_assembly.py:469` e `conversations.py:249`; usa `item.board_id/title/updated_at/shape_count`).
- Pulizia inline da assorbire (finding review fase 2): `api/routes/chat/conversations.py:414-463` (`delete_all_conversations`: snapshot path + `sa.delete(Artifact)` + unlink) e `:466-574` (`delete_conversation`: detach pinned / delete unpinned + unlink).

**Frontend:**
- `stores/charts.ts` — store DERIVATO dai tool message (`extractCharts`/`isChartPayload`, riusati da `MessageBubble.vue:16`, `ChartModule.vue:26`, `useArtifactAutoOpen.ts:26`); `stores/charts.spec.ts`.
- `stores/whiteboard.ts` — REST verso `/api/whiteboards` (boards/currentBoard/saveSnapshot/deleteBoard); consumato da `WhiteboardPageView.vue`, `WhiteboardListSidebar.vue` (legge store direttamente), `WhiteboardModule.vue`; `stores/whiteboard.spec.ts`; tipi in `types/whiteboard.ts`.
- `services/api.ts` — metodi whiteboard a righe 795-830 (getWhiteboards/getWhiteboard/deleteWhiteboard/saveWhiteboardSnapshot), metodi artifacts a righe 849-890.
- Payload nei tool message (NON cambiano di shape, cambiano i valori): `ChartPayload {chart_id,title,chart_type,chart_url,created_at}` e `WhiteboardPayload {board_id,title,board_url,conversation_id,created_at}` in `types/chat.ts:179-211` (lì vive già `isWhiteboardPayload`); `horizonArtifacts.ts` e `useArtifactAutoOpen.ts` estraggono i payload dai messaggi (continueranno a funzionare invariati nella logica).
- `types/artifacts.ts` — `Artifact`/`ArtifactKind` duplicati A MANO (da convertire a re-export `ApiSchema<...>`; verificato: `ArtifactRead` è in `types/generated/api.d.ts:2426` con `artifact_metadata?: {[key: string]: unknown}`, `conversation_id?: string | null`, `pinned?: boolean` — campi con default diventano OPZIONALI, i consumatori devono usare `??`).
- `ChartViewer.vue:402-407` — fetch grezza di `payload.chart_url`, legge `spec.echarts_option`.

**Vincoli operativi (gotchas handoff, validi qui):** suite backend completa impraticabile → test mirati; `npm run lint` rotto repo-wide → `npx eslint <file toccati>` (solo ERRORI) + `npm run typecheck`; ruff/mypy scoped (file nuovi puliti, pre-esistenze confrontate con `git show base:file`); file scritti con `newline="\n"`; MAI editare file non-ASCII via cmdlet PowerShell; `check-contracts.ps1` DOPO il commit; pytest da `backend/` con `..\.venv\Scripts\python.exe -m pytest`; niente `&&` in PowerShell 5.1.

---

## Decisioni di design della fase (registrate, non rilitigare durante l'esecuzione)

1. **Blob JSON in `data/artifacts/<kind>/<artifact_id>.json`** (spec §5.2). I GLB CAD restano dove Trellis li produce (`trellis.model_output_dir`): il registry registra il path, spostare l'output toccherebbe l'orchestrator Trellis (fuori scope §11 — "si sposta/consolida, non si riscrive"). Idem le route legacy `/api/cad/*` (servono `export_url` dei payload CAD e l'health proxy): INVARIATE, restano in baseline; eventuale migrazione a `/artifacts/{id}/download` → backlog fase 6.
2. **Id = artifact UUID**: `chart_id`/`board_id` nei payload e nei blob coincidono con `Artifact.id` (il plugin pre-genera l'UUID e lo passa a `create_json_artifact(artifact_id=...)`). `chart_url`/`board_url` → `/api/artifacts/{id}/content`. Le shape dei payload NON cambiano (FE: type guard e estrattori invariati).
3. **Dati legacy azzerabili**: `data/charts/` e `data/whiteboards/` restano su disco, inerti (mai letti, mai cancellati — stessa policy di `data/conversations/` in fase 2). I payload chart/whiteboard nelle conversazioni esistenti puntano a route morte: il viewer mostra lo stato d'errore già esistente. Nessuna migrazione.
4. **`PATCH /api/artifacts/{id}/content`** = merge delle chiavi top-level nel blob (body `{content: {...}}`, guardia 5 MiB come oggi). Il registry applica hook di normalizzazione per kind (`_JSON_METADATA_HOOKS`: per `whiteboard` ricalcola `shape_count` nei metadati e tocca `updated_at` nel blob). Tool del plugin e route FE usano LO STESSO metodo (`update_json_artifact`) — una sola implementazione.
5. **Eventi WS**: nuovi frame `artifact.updated` e `artifact.deleted` (minimi: solo `artifact_id`), emessi dal registry su update/pin/delete SINGOLI. Le delete bulk (`delete_for_conversation`, `delete_all`) NON emettono eventi (parità con oggi; invalidazione FE su delete conversazione → backlog). `WsArtifactCreated.conversation_id` diventa `str | None` (i JSON artifact possono nascere senza conversazione).
6. **Parità di comportamento dei tool**: `list_charts` resta GLOBALE, `whiteboard list` resta scoped alla conversazione corrente (default `context.conversation_id`); `delete` tool con `delete_file=True`; messaggi d'errore in italiano invariati dove possibile. `conversation_id` non-UUID (es. vuoto) → trattato come `None`, mai un crash.
7. **Lista whiteboard FE**: `conversation_title` non viene più risolto dal backend (join eliminato con la route); lo risolve il FE dal chat store (`conversations` già caricate in sidebar).
8. **Ordine task** = ogni task lascia verdi i test backend mirati e il typecheck FE. Finestra transitoria accettata e documentata: tra Task 3/4 e Task 7 il dominio whiteboard/chart FE punta a route eliminate (runtime 404) — lo stato finale di fase è l'oggetto della review finale. I test `tests/contracts/test_openapi_export.py`/`check-contracts` si eseguono SOLO nei task con rigenerazione (1, 5) e al gate finale.

---

### Task 1: Frame WS `artifact.updated`/`artifact.deleted` + dispatcher FE

> **Esito (2026-06-12):** DONE. Spec review: conforme. Quality review (opus): Ready to merge, 0 critical/important; minor annotati: (a) `remove` puo' riusare `removeLocal` (DRY, da fare nel Task 6), (b) alias `ArtifactCreatedEvent` senza usi (pre-esistente), (c) commento su semantica eventually-consistent di `refreshById`. Gate: contracts 84 pass, typecheck 0, vitest 259, check-contracts verde. Commit 1c3c06c.

**Files:**
- Modify: `backend/api/ws_schema/events.py` (frame + union; `WsArtifactCreated.conversation_id` nullable)
- Modify: `backend/tests/contracts/test_ws_schema_events.py` (vocabolario + frame rappresentativi)
- Modify: `frontend/src/renderer/src/stores/artifacts.ts` (azioni `refreshById`/`removeLocal`)
- Modify: `frontend/src/renderer/src/composables/useEventsWebSocket.ts` (2 handler)
- Regen: `.\scripts\gen-contracts.ps1`

- [x] **Step 1: Aggiorna il vocabolario congelato (test first)**

In `backend/tests/contracts/test_ws_schema_events.py`, dentro `EXPECTED_EVENTS_SERVER_TYPES` aggiungi dopo `"artifact.created",`:

```python
    "artifact.updated",
    "artifact.deleted",
```

e in `REPRESENTATIVE_SERVER_FRAMES`, subito dopo il frame `artifact.created` esistente:

```python
    {"type": "artifact.updated", "artifact_id": "a1"},
    {"type": "artifact.deleted", "artifact_id": "a1"},
```

- [x] **Step 2: Esegui i test contracts per vederli fallire**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/contracts/test_ws_schema_events.py -v
```

Atteso: FAIL (vocabolario non corrisponde / frame non validano).

- [x] **Step 3: Aggiungi i modelli in `events.py`**

In `backend/api/ws_schema/events.py`, modifica `WsArtifactCreated` (riga 157-164): il campo `conversation_id: str` diventa

```python
    conversation_id: str | None = None
```

e subito dopo la classe aggiungi:

```python
class WsArtifactUpdated(EventsServerFrame):
    """An existing artifact changed (row metadata or JSON content)."""

    type: Literal["artifact.updated"]
    artifact_id: str


class WsArtifactDeleted(EventsServerFrame):
    """An artifact row was deleted."""

    type: Literal["artifact.deleted"]
    artifact_id: str
```

Nell'union dei server frame (riga ~363, voce `| WsArtifactCreated`) aggiungi sotto di essa:

```python
    | WsArtifactUpdated
    | WsArtifactDeleted
```

Controlla anche `backend/api/ws_schema/__init__.py`: se i frame sono ri-esportati per nome, aggiungi i due nuovi simboli allo stesso modo di `WsArtifactCreated`.

- [x] **Step 4: Test verdi**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/contracts/ -v
```

Atteso: PASS (tutti, incluso `test_ws_guard`).

- [x] **Step 5: Rigenera i contratti**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
.\scripts\gen-contracts.ps1
```

Atteso: exit 0; `frontend/src/renderer/src/types/generated/` aggiornato (union eventi con i 2 nuovi type).

- [x] **Step 6: Azioni FE nello store artifacts**

In `frontend/src/renderer/src/stores/artifacts.ts`, dopo la funzione `fetchById` aggiungi:

```ts
  /** Force-refresh a single artifact row from the backend (upsert). */
  async function refreshById(id: string): Promise<void> {
    try {
      const artifact = await api.getArtifact(id)
      addArtifact(artifact)
    } catch (err) {
      console.warn('[artifacts] refreshById failed:', err)
    }
  }

  /** Remove an artifact from local state (the server already deleted it). */
  function removeLocal(id: string): void {
    const idx = items.value.findIndex((a) => a.id === id)
    if (idx !== -1) items.value.splice(idx, 1)
  }
```

e aggiungi `refreshById,` e `removeLocal,` al return dello store (sezione actions).

- [x] **Step 7: Handler nel dispatcher esaustivo**

In `frontend/src/renderer/src/composables/useEventsWebSocket.ts`, nella mappa `type → handler`, dopo la riga `'artifact.created': ...` aggiungi:

```ts
    'artifact.updated': (msg) => void artifactsStore.refreshById(msg.artifact_id),
    'artifact.deleted': (msg) => artifactsStore.removeLocal(msg.artifact_id),
```

- [x] **Step 8: Gate FE**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\frontend
npm run typecheck
npx vitest run
```

Atteso: typecheck exit 0; vitest tutti verdi.

- [x] **Step 9: Commit + check-contracts**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add -A
git commit -m "feat(ws): artifact.updated/deleted frames; nullable conversation_id on artifact.created" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
.\scripts\check-contracts.ps1
```

Atteso: commit ok; check-contracts verde.

---

### Task 2: Kind `chart`/`whiteboard` + `ArtifactBlobStore` + metodi JSON del registry

> **Esito (2026-06-12):** DONE. Spec review: conforme (verifica riga-per-riga + run 22/22). Quality review (opus): With fixes -> applicati e verificati a diff: type-ignore corretto ([attr-defined]), note docstring su torn-state/corruzione, +2 test (patch+title insieme, blob illeggibile). 12/12 test json, mypy pulito sulla riga corretta. Decisi NO: normalizzazione difensiva conversation_id nel registry (il contratto resta nei plugin per piano, decisione 6), tmp-name unico per writer concorrenti (non-issue per app single-user). Commit ad17403 + 58b0c86.

**Files:**
- Modify: `backend/db/models.py` (2 kind nuovi)
- Create: `backend/services/artifacts/blob_store.py`
- Modify: `backend/services/artifacts/registry.py` (metodi JSON, count, bulk delete, eventi updated/deleted)
- Modify: `backend/services/artifacts/__init__.py` (export)
- Create: `backend/tests/test_artifact_json.py`

- [x] **Step 1: Scrivi i test che falliscono**

Crea `backend/tests/test_artifact_json.py` (newline `\n`):

```python
"""AL\\CE — Tests for JSON-kind artifacts (blob store + registry methods)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import Artifact, ArtifactKind, Conversation
from backend.services.artifacts import ArtifactRegistry
from backend.services.artifacts.blob_store import ArtifactBlobStore


@pytest.fixture
async def session_factory():
    """In-memory SQLite + session factory with all tables created."""
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=SQLModelAsyncSession, expire_on_commit=False,
    )
    yield factory
    await engine.dispose()


@pytest.fixture
async def conversation_id(session_factory) -> uuid.UUID:
    async with session_factory() as session:
        conv = Conversation(title="t")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv.id


@pytest.fixture
def captured_events() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def registry(session_factory, captured_events, tmp_path) -> ArtifactRegistry:
    async def _cb(event: dict[str, Any]) -> None:
        captured_events.append(event)

    reg = ArtifactRegistry(
        session_factory=session_factory,
        blob_store=ArtifactBlobStore(tmp_path),
    )
    reg.set_event_callback(_cb)
    return reg


_SNAPSHOT = {
    "store": {
        "shape:s1": {"typeName": "shape", "id": "shape:s1"},
        "shape:s2": {"typeName": "shape", "id": "shape:s2"},
        "page:p1": {"typeName": "page", "id": "page:p1"},
    },
}


async def test_create_json_artifact_writes_blob_row_event(
    registry, captured_events, conversation_id, tmp_path,
) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART,
        title="My chart",
        content={"chart_id": "x", "echarts_option": {"series": []}, "updated_at": "2026-06-12T00:00:00+00:00"},
        conversation_id=conversation_id,
        metadata={"chart_type": "bar"},
    )
    assert artifact.kind is ArtifactKind.CHART
    assert artifact.mime == "application/json"
    assert artifact.size_bytes > 0
    blob = tmp_path / "chart" / f"{artifact.id}.json"
    assert blob.exists()
    assert captured_events[-1]["type"] == "artifact.created"
    assert captured_events[-1]["kind"] == "chart"


async def test_whiteboard_metadata_hook_counts_shapes(registry) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD,
        title="Board",
        content={"board_id": "b", "snapshot": _SNAPSHOT, "updated_at": "2026-06-12T00:00:00+00:00"},
    )
    assert artifact.artifact_metadata["shape_count"] == 2


async def test_read_json_content_roundtrip_and_missing(registry) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART,
        title="c",
        content={"chart_id": "c", "echarts_option": {"series": [1]}},
    )
    result = await registry.read_json_content(artifact.id)
    assert result is not None
    row, content = result
    assert row.id == artifact.id
    assert content["echarts_option"] == {"series": [1]}
    assert await registry.read_json_content(uuid.uuid4()) is None


async def test_update_json_artifact_merges_and_bumps(
    registry, captured_events,
) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD,
        title="Board",
        content={"board_id": "b", "snapshot": {"store": {}}, "updated_at": "2026-06-12T00:00:00+00:00"},
    )
    assert artifact.artifact_metadata["shape_count"] == 0
    updated = await registry.update_json_artifact(
        artifact.id, content_patch={"snapshot": _SNAPSHOT},
    )
    assert updated is not None
    assert updated.artifact_metadata["shape_count"] == 2
    assert updated.updated_at >= artifact.updated_at
    _row, content = await registry.read_json_content(artifact.id)
    assert content["snapshot"] == _SNAPSHOT
    assert content["updated_at"] != "2026-06-12T00:00:00+00:00"
    assert captured_events[-1] == {
        "type": "artifact.updated", "artifact_id": str(artifact.id),
    }


async def test_update_json_artifact_title_only(registry) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="old",
        content={"chart_id": "c", "echarts_option": {}},
    )
    updated = await registry.update_json_artifact(artifact.id, title="new")
    assert updated is not None and updated.title == "new"


async def test_count_artifacts_by_kind(registry, conversation_id) -> None:
    for i in range(3):
        await registry.create_json_artifact(
            kind=ArtifactKind.CHART, title=f"c{i}",
            content={"chart_id": str(i), "echarts_option": {}},
            conversation_id=conversation_id,
        )
    await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD, title="b",
        content={"board_id": "b", "snapshot": {"store": {}}},
    )
    assert await registry.count_artifacts(kind=ArtifactKind.CHART) == 3
    assert await registry.count_artifacts(kind=ArtifactKind.WHITEBOARD) == 1
    assert await registry.count_artifacts() == 4
    assert await registry.count_artifacts(
        kind=ArtifactKind.CHART, conversation_id=conversation_id,
    ) == 3


async def test_delete_artifact_emits_deleted_event(
    registry, captured_events, tmp_path,
) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="c",
        content={"chart_id": "c", "echarts_option": {}},
    )
    blob = tmp_path / "chart" / f"{artifact.id}.json"
    assert blob.exists()
    assert await registry.delete_artifact(artifact.id, delete_file=True)
    assert not blob.exists()
    assert captured_events[-1] == {
        "type": "artifact.deleted", "artifact_id": str(artifact.id),
    }


async def test_set_pinned_emits_updated_event(registry, captured_events) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="c",
        content={"chart_id": "c", "echarts_option": {}},
    )
    await registry.set_pinned(artifact.id, True)
    assert captured_events[-1] == {
        "type": "artifact.updated", "artifact_id": str(artifact.id),
    }


async def test_delete_for_conversation_detaches_pinned(
    registry, conversation_id, tmp_path,
) -> None:
    pinned = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD, title="keep",
        content={"board_id": "k", "snapshot": {"store": {}}},
        conversation_id=conversation_id,
    )
    await registry.set_pinned(pinned.id, True)
    gone = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="gone",
        content={"chart_id": "g", "echarts_option": {}},
        conversation_id=conversation_id,
    )
    gone_blob = tmp_path / "chart" / f"{gone.id}.json"
    deleted = await registry.delete_for_conversation(conversation_id)
    assert deleted == 1
    assert not gone_blob.exists()
    survivor = await registry.get_artifact(pinned.id)
    assert survivor is not None and survivor.conversation_id is None
    assert await registry.get_artifact(gone.id) is None


async def test_delete_all_wipes_rows_and_files(registry, tmp_path) -> None:
    a1 = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="a",
        content={"chart_id": "a", "echarts_option": {}},
    )
    a2 = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD, title="b",
        content={"board_id": "b", "snapshot": {"store": {}}},
    )
    count = await registry.delete_all()
    assert count == 2
    assert await registry.count_artifacts() == 0
    assert not (tmp_path / "chart" / f"{a1.id}.json").exists()
    assert not (tmp_path / "whiteboard" / f"{a2.id}.json").exists()
```

- [x] **Step 2: Esegui i test per vederli fallire**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_artifact_json.py -v
```

Atteso: FAIL con `ModuleNotFoundError: backend.services.artifacts.blob_store` (o ImportError).

- [x] **Step 3: Aggiungi i kind in `db/models.py`**

In `ArtifactKind` (riga ~299, dopo `CAD_3D_IMAGE`):

```python
    CHART = "chart"
    """Interactive ECharts chart (chart_generator plugin) — JSON blob."""

    WHITEBOARD = "whiteboard"
    """tldraw whiteboard (whiteboard plugin) — JSON blob with snapshot."""
```

- [x] **Step 4: Crea `backend/services/artifacts/blob_store.py`**

```python
"""AL\\CE — JSON blob store for artifact content.

Owns the on-disk *content* of JSON-kind artifacts (charts, whiteboards,
…) under ``data/artifacts/<kind>/<artifact_id>.json``.  The DB row
(:class:`backend.db.models.Artifact`) remains the source of truth for
metadata; this store only owns blob bytes (atomic writes).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.config import PROJECT_ROOT
from backend.db.models import ArtifactKind

DEFAULT_BLOB_BASE_DIR = PROJECT_ROOT / "data" / "artifacts"


class ArtifactBlobStore:
    """On-disk JSON blobs for artifacts, one file per artifact id."""

    def __init__(self, base_dir: Path | None = None) -> None:
        """Build a blob store rooted at *base_dir* (default ``data/artifacts``)."""
        self._base_dir = base_dir or DEFAULT_BLOB_BASE_DIR

    def path_for(self, kind: ArtifactKind, artifact_id: uuid.UUID) -> Path:
        """Return the canonical blob path for *kind* / *artifact_id*."""
        return self._base_dir / kind.value / f"{artifact_id}.json"

    async def write(
        self,
        kind: ArtifactKind,
        artifact_id: uuid.UUID,
        content: dict[str, Any],
    ) -> tuple[Path, int]:
        """Atomically serialise *content*; return ``(path, size_bytes)``."""
        path = self.path_for(kind, artifact_id)
        data = json.dumps(content, ensure_ascii=False, indent=2, default=str)
        size = await asyncio.to_thread(self._write_sync, path, data)
        return path, size

    async def read(self, file_path: str | Path) -> dict[str, Any] | None:
        """Load a blob by its (possibly relative) *file_path*.

        Returns ``None`` when the file is missing or not a JSON object.
        """
        p = Path(file_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return await asyncio.to_thread(self._read_sync, p)

    @staticmethod
    def _write_sync(path: Path, data: str) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(data, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        return path.stat().st_size

    @staticmethod
    def _read_sync(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Artifact blob unreadable {}: {}", path, exc)
            return None
        return loaded if isinstance(loaded, dict) else None
```

- [x] **Step 5: Estendi `registry.py`**

In `backend/services/artifacts/registry.py`:

5a. Aggiungi all'import block:

```python
from backend.services.artifacts.blob_store import ArtifactBlobStore
```

e (per le delete bulk) sposta/aggiungi `import sqlalchemy as sa` a livello modulo.

5b. Dopo `EventCallback` aggiungi gli hook per kind:

```python
def _whiteboard_metadata(content: dict[str, Any]) -> dict[str, Any]:
    """Derive list-display metadata from a whiteboard blob (tldraw spec)."""
    snapshot = content.get("snapshot")
    store = snapshot.get("store", {}) if isinstance(snapshot, dict) else {}
    count = sum(
        1
        for v in store.values()
        if isinstance(v, dict) and v.get("typeName") == "shape"
    )
    return {"shape_count": count}


_JSON_METADATA_HOOKS: dict[
    ArtifactKind, Callable[[dict[str, Any]], dict[str, Any]]
] = {
    ArtifactKind.WHITEBOARD: _whiteboard_metadata,
}
```

(`Callable` è già importato da `collections.abc` in testa al file.)

5c. Il costruttore guadagna il blob store:

```python
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        event_callback: EventCallback | None = None,
        blob_store: ArtifactBlobStore | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._event_callback: EventCallback | None = event_callback
        self._blob_store = blob_store or ArtifactBlobStore()
```

(aggiorna la docstring del costruttore di conseguenza).

5d. Nuova sezione dopo `_persist_descriptor` (Create JSON):

```python
    # ------------------------------------------------------------------
    # JSON-kind artifacts (chart, whiteboard, …)
    # ------------------------------------------------------------------

    async def create_json_artifact(
        self,
        *,
        kind: ArtifactKind,
        title: str,
        content: dict[str, Any],
        conversation_id: uuid.UUID | str | None = None,
        message_id: uuid.UUID | str | None = None,
        tool_call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        artifact_id: uuid.UUID | None = None,
    ) -> Artifact:
        """Persist a JSON-content artifact: blob on disk + row + event.

        Args:
            kind: Target :class:`ArtifactKind` (blob lives in
                ``data/artifacts/<kind>/``).
            title: Human-readable label (clipped to 256 chars).
            content: JSON-serialisable blob content.
            conversation_id: Optional source conversation.
            message_id: Optional producing tool message.
            tool_call_id: Optional producing tool-call id.
            metadata: Free-form metadata; merged with the per-kind hook
                output (hook wins on key collisions).
            artifact_id: Pre-generated id, so callers can embed it in
                *content* before persisting.  Generated when omitted.
        """
        aid = artifact_id or uuid.uuid4()
        path, size = await self._blob_store.write(kind, aid, content)
        meta = dict(metadata or {})
        hook = _JSON_METADATA_HOOKS.get(kind)
        if hook is not None:
            meta.update(hook(content))
        artifact = Artifact(
            id=aid,
            conversation_id=_to_uuid_or_none(conversation_id),
            message_id=_to_uuid_or_none(message_id),
            tool_call_id=tool_call_id,
            kind=kind,
            title=title[:256],
            file_path=_normalize_path(str(path)),
            mime="application/json",
            size_bytes=size,
            artifact_metadata=meta,
        )
        async with self._session_factory() as session:
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)

        logger.info(
            "JSON artifact created: id={} kind={} title={!r}",
            artifact.id, artifact.kind.value, artifact.title,
        )
        await self._emit_event({
            "type": "artifact.created",
            "artifact_id": str(artifact.id),
            "kind": artifact.kind.value,
            "conversation_id": (
                str(artifact.conversation_id)
                if artifact.conversation_id else None
            ),
            "title": artifact.title,
        })
        return artifact

    async def read_json_content(
        self, artifact_id: uuid.UUID | str,
    ) -> tuple[Artifact, dict[str, Any]] | None:
        """Return ``(row, blob content)`` for a JSON-kind artifact.

        ``None`` when the artifact is missing, is not JSON-mime, or the
        blob is unreadable.
        """
        artifact = await self.get_artifact(artifact_id)
        if artifact is None or artifact.mime != "application/json":
            return None
        content = await self._blob_store.read(artifact.file_path)
        if content is None:
            return None
        return artifact, content

    async def update_json_artifact(
        self,
        artifact_id: uuid.UUID | str,
        *,
        content_patch: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> Artifact | None:
        """Merge *content_patch* into the blob and/or retitle the row.

        Top-level merge semantics: ``blob.update(content_patch)``.  When
        the blob carries an ``updated_at`` key it is refreshed; per-kind
        metadata hooks re-run on the merged content.  Emits
        ``artifact.updated``.  Returns ``None`` when the artifact is
        missing or has no JSON content.
        """
        artifact = await self.get_artifact(artifact_id)
        if artifact is None or artifact.mime != "application/json":
            return None
        size: int | None = None
        meta = dict(artifact.artifact_metadata)
        if content_patch:
            content = await self._blob_store.read(artifact.file_path)
            if content is None:
                return None
            content.update(content_patch)
            if "updated_at" in content:
                content["updated_at"] = _utcnow().isoformat()
            _path, size = await self._blob_store.write(
                artifact.kind, artifact.id, content,
            )
            hook = _JSON_METADATA_HOOKS.get(artifact.kind)
            if hook is not None:
                meta.update(hook(content))
        async with self._session_factory() as session:
            row = await session.get(Artifact, artifact.id)
            if row is None:
                return None
            if title is not None:
                row.title = title[:256]
            if size is not None:
                row.size_bytes = size
            row.artifact_metadata = meta
            row.updated_at = _utcnow()
            session.add(row)
            await session.commit()
            await session.refresh(row)

        await self._emit_event({
            "type": "artifact.updated", "artifact_id": str(row.id),
        })
        return row

    async def count_artifacts(
        self,
        *,
        kind: ArtifactKind | None = None,
        conversation_id: uuid.UUID | str | None = None,
    ) -> int:
        """Count artifacts, optionally filtered by kind/conversation."""
        from sqlalchemy import func

        async with self._session_factory() as session:
            stmt = select(func.count()).select_from(Artifact)
            if kind is not None:
                stmt = stmt.where(Artifact.kind == kind)
            if conversation_id is not None:
                stmt = stmt.where(
                    Artifact.conversation_id == _to_uuid(conversation_id),
                )
            total = (await session.exec(stmt)).one()
        return int(total)
```

5e. `set_pinned`: prima del `return artifact` finale aggiungi

```python
        await self._emit_event({
            "type": "artifact.updated", "artifact_id": str(artifact.id),
        })
```

5f. `delete_artifact`: dopo il blocco `if delete_file:` e prima di `return True` aggiungi

```python
        await self._emit_event({
            "type": "artifact.deleted", "artifact_id": str(artifact_uuid),
        })
```

5g. Nuova sezione dopo `delete_artifact` (assorbe la pulizia inline di `conversations.py`, finding review fase 2):

```python
    async def delete_for_conversation(
        self, conversation_id: uuid.UUID | str,
    ) -> int:
        """Conversation-deletion cleanup (single implementation).

        Pinned artifacts survive detached (``conversation_id=NULL``,
        preserved on the board); unpinned rows are deleted together with
        their on-disk files.  No per-row WS events (bulk operation).
        Returns the number of deleted rows.
        """
        conv_uuid = _to_uuid(conversation_id)
        async with self._session_factory() as session:
            unpinned_q = await session.exec(
                select(Artifact.id, Artifact.file_path).where(
                    Artifact.conversation_id == conv_uuid,
                    Artifact.pinned == False,  # noqa: E712 (SQL boolean)
                )
            )
            unpinned: list[tuple[uuid.UUID, str]] = list(unpinned_q.all())
            conn = await session.connection()
            if unpinned:
                await conn.execute(
                    sa.delete(Artifact).where(
                        Artifact.id.in_(  # type: ignore[union-attr]
                            [aid for aid, _ in unpinned],
                        )
                    )
                )
            await conn.execute(
                sa.update(Artifact)
                .where(
                    Artifact.conversation_id == conv_uuid,
                    Artifact.pinned == True,  # noqa: E712
                )
                .values(conversation_id=None)
            )
            await session.commit()

        # Best-effort file cleanup AFTER commit (a transient FS failure
        # must not roll back the row deletion).
        for _aid, file_path in unpinned:
            await asyncio.to_thread(_unlink_quietly, _resolve_path(file_path))
        return len(unpinned)

    async def delete_all(self) -> int:
        """Delete EVERY artifact row and on-disk file (full wipe).

        Used by "delete all conversations"; pinned status is irrelevant
        because the user asked to delete everything.  No WS events.
        """
        async with self._session_factory() as session:
            paths_q = await session.exec(
                select(Artifact.id, Artifact.file_path),
            )
            rows: list[tuple[uuid.UUID, str]] = list(paths_q.all())
            conn = await session.connection()
            await conn.execute(sa.delete(Artifact))
            await session.commit()

        for _aid, file_path in rows:
            await asyncio.to_thread(_unlink_quietly, _resolve_path(file_path))
        return len(rows)
```

5h. In `backend/services/artifacts/__init__.py` aggiungi l'import e l'`__all__`:

```python
from backend.services.artifacts.blob_store import ArtifactBlobStore
```

con `"ArtifactBlobStore",` in `__all__`.

- [x] **Step 6: Test verdi + regressione registry**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_artifact_json.py tests/test_artifact_registry.py -v
```

Atteso: PASS. Nota: se test esistenti di `test_artifact_registry.py` contano gli eventi emessi (pin/delete ora emettono `artifact.updated`/`artifact.deleted`), aggiornali ad asserire i nuovi eventi — il comportamento nuovo è quello voluto.

- [x] **Step 7: Lint scoped + commit**

```powershell
..\.venv\Scripts\python.exe -m ruff check services/artifacts/ tests/test_artifact_json.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git add -A
git commit -m "feat(artifacts): chart/whiteboard kinds, JSON blob store, registry json methods + bulk delete" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Plugin chart_generator sul registry; via `ChartStore` e route `/api/charts`

> **Esito (2026-06-12):** DONE. Deviazioni accettate: (1) i test asserzionano `error_message` (typo del piano: `ToolResult.error()` non riempie `content`); (2) eliminato anche il pre-esistente `test_chart_generator_plugin.py` (usava `chart_output_dir`), copertura ripristinata con +7 test (limiti, disabled, edge) in 711b276. Spec review: conforme. Quality review (opus): Ready to merge; minor rinviati al Task 4: narrowing `_registry()` (raise invece di `| None`) da applicare a entrambi i plugin + 1 test integrazione plugin-validator. 12/12 test plugin, ratchet -3 verde. Commit bb1c115 + 711b276.

**Files:**
- Modify: `backend/plugins/chart_generator/plugin.py`
- Delete: `backend/plugins/chart_generator/chart_store.py`
- Delete: `backend/api/routes/charts.py`
- Modify: `backend/api/routes/__init__.py` (import riga 7, include riga 26)
- Modify: `backend/core/config.py` (rimuovi `chart_output_dir`, righe 724-725)
- Modify: `config/default.yaml` (rimuovi `chart_output_dir`, riga 282)
- Modify: `backend/tests/contracts/response_model_baseline.txt` (−3 voci charts)
- Delete: `backend/tests/test_chart_store.py`
- Create: `backend/tests/test_chart_plugin.py`

- [x] **Step 1: Scrivi i test che falliscono**

Crea `backend/tests/test_chart_plugin.py`:

```python
"""AL\\CE — Tests for the chart_generator plugin on the unified registry."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.config import ChartConfig
from backend.core.plugin_models import ExecutionContext
from backend.db.models import ArtifactKind, Conversation
from backend.plugins.chart_generator.plugin import ChartGeneratorPlugin
from backend.services.artifacts import ArtifactRegistry
from backend.services.artifacts.blob_store import ArtifactBlobStore


@pytest.fixture
async def session_factory():
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=SQLModelAsyncSession, expire_on_commit=False,
    )
    yield factory
    await engine.dispose()


@pytest.fixture
async def conversation_id(session_factory) -> uuid.UUID:
    async with session_factory() as session:
        conv = Conversation(title="t")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv.id


@pytest.fixture
def registry(session_factory, tmp_path) -> ArtifactRegistry:
    return ArtifactRegistry(
        session_factory=session_factory,
        blob_store=ArtifactBlobStore(tmp_path),
    )


class _StubConfig:
    def __init__(self) -> None:
        self.chart = ChartConfig(enabled=True)


class _StubCtx:
    def __init__(self, registry: ArtifactRegistry) -> None:
        self.artifact_registry = registry
        self.config = _StubConfig()


@pytest.fixture
def plugin(registry) -> ChartGeneratorPlugin:
    p = ChartGeneratorPlugin()
    p._ctx = _StubCtx(registry)  # bypass full AppContext wiring
    return p


def _exec_ctx(conversation_id: uuid.UUID | None = None) -> ExecutionContext:
    return ExecutionContext(
        session_id="s",
        conversation_id=str(conversation_id) if conversation_id else "",
        execution_id="e",
    )


_OPTION = {
    "xAxis": {"data": ["a", "b"]},
    "yAxis": {"type": "value"},
    "series": [{"type": "bar", "data": [1, 2]}],
}


async def test_generate_chart_creates_artifact(
    plugin, registry, conversation_id,
) -> None:
    result = await plugin.execute_tool(
        "generate_chart",
        {"title": "T", "chart_type": "bar", "echarts_option": _OPTION},
        _exec_ctx(conversation_id),
    )
    assert result.success, result.content
    payload = json.loads(result.content)
    aid = payload["chart_id"]
    assert payload["chart_url"] == f"/api/artifacts/{aid}/content"
    read = await registry.read_json_content(aid)
    assert read is not None
    artifact, content = read
    assert artifact.kind is ArtifactKind.CHART
    assert artifact.conversation_id == conversation_id
    assert artifact.artifact_metadata["chart_type"] == "bar"
    assert content["chart_id"] == aid
    assert content["echarts_option"]["series"][0]["type"] == "bar"


async def test_update_chart_replaces_option(plugin, registry, conversation_id) -> None:
    gen = await plugin.execute_tool(
        "generate_chart",
        {"title": "T", "chart_type": "bar", "echarts_option": _OPTION},
        _exec_ctx(conversation_id),
    )
    aid = json.loads(gen.content)["chart_id"]
    new_option = {
        "xAxis": {"data": ["a", "b"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [3, 4]}],
    }
    upd = await plugin.execute_tool(
        "update_chart",
        {"chart_id": aid, "echarts_option": new_option, "title": "T2"},
        _exec_ctx(),
    )
    assert upd.success, upd.content
    read = await registry.read_json_content(aid)
    assert read is not None
    artifact, content = read
    assert artifact.title == "T2"
    assert content["echarts_option"]["series"][0]["data"] == [3, 4]


async def test_list_charts_returns_metadata(plugin, conversation_id) -> None:
    await plugin.execute_tool(
        "generate_chart",
        {"title": "T", "chart_type": "bar", "echarts_option": _OPTION},
        _exec_ctx(conversation_id),
    )
    res = await plugin.execute_tool("list_charts", {}, _exec_ctx())
    assert res.success
    payload = json.loads(res.content)
    assert payload["total"] == 1
    assert payload["charts"][0]["chart_type"] == "bar"
    assert payload["charts"][0]["title"] == "T"


async def test_delete_chart_removes_row_and_blob(
    plugin, registry, tmp_path,
) -> None:
    gen = await plugin.execute_tool(
        "generate_chart",
        {"title": "T", "chart_type": "bar", "echarts_option": _OPTION},
        _exec_ctx(),
    )
    aid = json.loads(gen.content)["chart_id"]
    res = await plugin.execute_tool("delete_chart", {"chart_id": aid}, _exec_ctx())
    assert res.success
    assert await registry.get_artifact(aid) is None
    assert not (tmp_path / "chart" / f"{aid}.json").exists()


async def test_invalid_chart_id_is_clean_error(plugin) -> None:
    res = await plugin.execute_tool(
        "get_chart", {"chart_id": "not-a-uuid"}, _exec_ctx(),
    )
    assert not res.success
    assert "non trovato" in res.content
```

- [x] **Step 2: Esegui i test per vederli fallire**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_chart_plugin.py -v
```

Atteso: FAIL (il plugin usa ancora ChartStore; `chart_url` punta a `/api/charts/`).

- [x] **Step 3: Riscrivi `plugins/chart_generator/plugin.py`**

Modifiche (gli SCHEMA `_GENERATE_SCHEMA`… e `get_tools()` restano INVARIATI):

3a. Import: rimuovi `from backend.core.config import PROJECT_ROOT` e `from .chart_store import ChartStore`; la riga `from uuid import uuid4` diventa `from uuid import UUID, uuid4`; aggiungi:

```python
from backend.db.models import ArtifactKind

if TYPE_CHECKING:
    from backend.core.context import AppContext
    from backend.services.artifacts import ArtifactRegistry
```

(estendendo il blocco `TYPE_CHECKING` esistente). Aggiungi gli import dei modelli: `from .models import ChartListItem, ChartPayload, ChartSpec`.

3b. Aggiungi a livello modulo (dopo gli schema):

```python
def _parse_artifact_id(value: str) -> UUID | None:
    """Parse *value* as an artifact UUID; ``None`` when malformed."""
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None
```

3c. `__init__`, `store` property, `initialize`, `cleanup`: rimuovi `self._store` e la property `store`; `initialize` si riduce a

```python
    async def initialize(self, ctx: "AppContext") -> None:
        await super().initialize(ctx)
        if not ctx.config.chart.enabled:
            self.logger.info("Plugin chart_generator disabilitato dalla configurazione.")
            return
        self.logger.info("ChartGeneratorPlugin inizializzato (registry-backed)")
```

e `cleanup` chiama solo `await super().cleanup()`. Aggiungi l'accessor:

```python
    def _registry(self) -> "ArtifactRegistry | None":
        return getattr(self.ctx, "artifact_registry", None)
```

3d. `execute_tool`: sostituisci il check dello store con

```python
        if self._registry() is None:
            return ToolResult.error("Artifact registry non inizializzato.")
```

e cambia la dispatch in `return await handler(args, context)`.

3e. Handler (tutti con firma `(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult`; in `_get_chart`/`_list_charts`/`_delete_chart` il parametro context è inutilizzato — chiamalo `_context`):

```python
    async def _generate_chart(
        self, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        title = (args.get("title") or "").strip()
        if not title:
            return ToolResult.error("Missing required parameter: title")
        chart_type = (args.get("chart_type") or "").strip()
        if not chart_type:
            return ToolResult.error("Missing required parameter: chart_type")
        option = args.get("echarts_option")
        if not isinstance(option, dict):
            return ToolResult.error("Missing required parameter: echarts_option")

        cfg = self.ctx.config.chart
        option_str = json.dumps(option, ensure_ascii=False)
        if len(option_str) > cfg.max_option_chars:
            return ToolResult.error(
                f"La echarts_option supera il limite di {cfg.max_option_chars} caratteri "
                f"(attuale: {len(option_str)}). Aggrega o riduci i dati prima di richiamare il tool."
            )

        try:
            option = validate_and_normalize_option(option, chart_type)
        except ChartOptionError as exc:
            self.logger.warning(f"echarts_option non valida per '{title}': {exc}")
            return ToolResult.error(str(exc))

        registry = self._registry()
        count = await registry.count_artifacts(kind=ArtifactKind.CHART)
        if count >= cfg.max_charts:
            return ToolResult.error(
                f"Limite massimo di grafici raggiunto ({cfg.max_charts}). "
                "Usa `delete_chart` per eliminare grafici non più necessari."
            )

        aid = uuid4()
        now = datetime.now(timezone.utc)
        spec = ChartSpec(
            chart_id=str(aid),
            title=title,
            chart_type=chart_type,
            description=args.get("description", ""),
            echarts_option=option,
            created_at=now,
            updated_at=now,
        )
        await registry.create_json_artifact(
            kind=ArtifactKind.CHART,
            title=title,
            content=spec.model_dump(mode="json"),
            conversation_id=_parse_artifact_id(context.conversation_id or ""),
            metadata={"chart_type": chart_type, "description": spec.description},
            artifact_id=aid,
        )
        self.logger.info(f"Grafico '{title}' generato (id={aid}, type={chart_type})")

        payload = ChartPayload(
            chart_id=str(aid),
            title=title,
            chart_type=chart_type,
            chart_url=f"/api/artifacts/{aid}/content",
            created_at=now,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.chart+json",
        )

    async def _update_chart(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        chart_id = (args.get("chart_id") or "").strip()
        aid = _parse_artifact_id(chart_id)
        if aid is None:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        option = args.get("echarts_option")
        if not isinstance(option, dict):
            return ToolResult.error("Missing required parameter: echarts_option")

        registry = self._registry()
        existing = await registry.read_json_content(aid)
        if existing is None:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        artifact, content = existing

        chart_type = str(content.get("chart_type") or "")
        try:
            option = validate_and_normalize_option(option, chart_type)
        except ChartOptionError as exc:
            self.logger.warning(f"echarts_option non valida per update {chart_id}: {exc}")
            return ToolResult.error(str(exc))

        cfg = self.ctx.config.chart
        option_str = json.dumps(option, ensure_ascii=False)
        if len(option_str) > cfg.max_option_chars:
            return ToolResult.error(
                f"echarts_option supera il limite di {cfg.max_option_chars} caratteri."
            )

        patch: dict[str, Any] = {"echarts_option": option}
        new_title = args.get("title") if "title" in args else None
        if new_title is not None:
            patch["title"] = new_title
        updated = await registry.update_json_artifact(
            aid, content_patch=patch, title=new_title,
        )
        if updated is None:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        self.logger.info(f"Grafico aggiornato: {chart_id}")

        payload = ChartPayload(
            chart_id=chart_id,
            title=updated.title,
            chart_type=chart_type,
            chart_url=f"/api/artifacts/{chart_id}/content",
            created_at=artifact.created_at,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.chart+json",
        )

    async def _get_chart(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        chart_id = (args.get("chart_id") or "").strip()
        aid = _parse_artifact_id(chart_id)
        if aid is None:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        result = await self._registry().read_json_content(aid)
        if result is None:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        _artifact, content = result
        return ToolResult.ok(json.dumps(content, ensure_ascii=False, default=str))

    async def _list_charts(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        limit = min(int(args.get("limit", 20)), 100)
        offset = max(int(args.get("offset", 0)), 0)
        registry = self._registry()
        items, total = await registry.list_artifacts(
            kind=ArtifactKind.CHART, limit=limit, offset=offset,
        )
        charts = [
            ChartListItem(
                chart_id=str(a.id),
                title=a.title,
                chart_type=str(a.artifact_metadata.get("chart_type") or ""),
                description=str(a.artifact_metadata.get("description") or ""),
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in items
        ]
        payload = {
            "charts": [c.model_dump(mode="json") for c in charts],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        return ToolResult.ok(json.dumps(payload, ensure_ascii=False, default=str))

    async def _delete_chart(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        chart_id = (args.get("chart_id") or "").strip()
        aid = _parse_artifact_id(chart_id)
        if aid is None:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        registry = self._registry()
        artifact = await registry.get_artifact(aid)
        if artifact is None or artifact.kind is not ArtifactKind.CHART:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        deleted = await registry.delete_artifact(aid, delete_file=True)
        if not deleted:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        return ToolResult.ok(f"Grafico eliminato: {chart_id}")
```

3f. Elimina `backend/plugins/chart_generator/chart_store.py`.

- [x] **Step 4: Elimina la route e la config**

- Elimina `backend/api/routes/charts.py`.
- In `backend/api/routes/__init__.py`: togli `charts` dall'import (riga 7) e la riga `router.include_router(charts.router)` (riga 26).
- In `backend/core/config.py` rimuovi da `ChartConfig` le righe:

```python
    chart_output_dir: str = "data/charts"
    """Directory dove vengono salvati i chart spec JSON."""
```

- In `config/default.yaml` rimuovi la riga `  chart_output_dir: "data/charts"` (ATTENZIONE: file con commenti non-ASCII possibili — usa Edit tool, MAI cmdlet PowerShell).
- In `backend/tests/contracts/response_model_baseline.txt` rimuovi le 3 voci:

```
DELETE /api/charts/{chart_id}
GET /api/charts
GET /api/charts/{chart_id}
```

- Elimina `backend/tests/test_chart_store.py`.

- [x] **Step 5: Test verdi**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_chart_plugin.py tests/contracts/test_response_models.py -v
```

Atteso: PASS (la ratchet vede 3 route in meno e 3 voci baseline in meno).

- [x] **Step 6: Lint scoped + commit**

```powershell
..\.venv\Scripts\python.exe -m ruff check plugins/chart_generator/ tests/test_chart_plugin.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git add -A
git commit -m "refactor(chart): chart_generator on unified artifact registry; drop ChartStore + /api/charts" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Plugin whiteboard sul registry; via `WhiteboardStore`, route `/api/whiteboards` e contesto system-prompt dal registry

> **Esito (2026-06-12):** DONE. Spec review: conforme (handler, contesto registry-based con guardia tz-naive, -4 baseline, parity decisioni 6/7 verificate). Quality review (opus): Ready to merge; follow-up applicati in d034b0f: +5 test whiteboard (update, missing-board, disabled, unknown tool, max_boards), `_registry()` con cast in entrambi i plugin (via union-attr/no-any-return), commento edge schema-less merge. Amendment B variante: series type 'nonsense' con chart_type='bar' (il '' inciampa nella guardia missing-param). 23/23 test plugin. Commit c1883e4 + d034b0f.

**Files:**
- Modify: `backend/plugins/whiteboard/plugin.py`
- Delete: `backend/plugins/whiteboard/store.py`
- Delete: `backend/api/routes/whiteboards.py`
- Modify: `backend/api/routes/__init__.py` (import riga 7, include riga 27)
- Modify: `backend/api/routes/chat/_helpers.py` (`_build_whiteboard_context` → registry)
- Modify: `backend/core/config.py` (rimuovi `whiteboard_output_dir`, righe 742-743)
- Modify: `config/default.yaml` (rimuovi `whiteboard_output_dir`, riga 293)
- Modify: `backend/tests/contracts/response_model_baseline.txt` (−3 voci whiteboards)
- Delete: `backend/tests/test_whiteboard_route_scope.py`
- Create: `backend/tests/test_whiteboard_plugin.py`

- [x] **Step 1: Scrivi i test che falliscono**

Crea `backend/tests/test_whiteboard_plugin.py` (stesse fixture `session_factory`/`conversation_id`/`registry` di `test_chart_plugin.py` — copiale verbatim, NON importarle cross-file):

```python
"""AL\\CE — Tests for the whiteboard plugin on the unified registry."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.config import WhiteboardConfig
from backend.core.plugin_models import ExecutionContext
from backend.db.models import ArtifactKind, Conversation
from backend.plugins.whiteboard.plugin import WhiteboardPlugin
from backend.services.artifacts import ArtifactRegistry
from backend.services.artifacts.blob_store import ArtifactBlobStore


@pytest.fixture
async def session_factory():
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=SQLModelAsyncSession, expire_on_commit=False,
    )
    yield factory
    await engine.dispose()


@pytest.fixture
async def conversation_id(session_factory) -> uuid.UUID:
    async with session_factory() as session:
        conv = Conversation(title="Conv title")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv.id


@pytest.fixture
def registry(session_factory, tmp_path) -> ArtifactRegistry:
    return ArtifactRegistry(
        session_factory=session_factory,
        blob_store=ArtifactBlobStore(tmp_path),
    )


class _StubConfig:
    def __init__(self) -> None:
        self.whiteboard = WhiteboardConfig(enabled=True)


class _StubCtx:
    def __init__(self, registry: ArtifactRegistry) -> None:
        self.artifact_registry = registry
        self.config = _StubConfig()


@pytest.fixture
def plugin(registry) -> WhiteboardPlugin:
    p = WhiteboardPlugin()
    p._ctx = _StubCtx(registry)  # bypass full AppContext wiring
    return p


def _exec_ctx(conversation_id: uuid.UUID | None = None) -> ExecutionContext:
    return ExecutionContext(
        session_id="s",
        conversation_id=str(conversation_id) if conversation_id else "",
        execution_id="e",
    )


_SHAPES = [
    {"type": "geo", "id": "n1", "text": "Start"},
    {"type": "geo", "id": "n2", "text": "End", "x": 250},
]


async def test_create_whiteboard_counts_shapes(
    plugin, registry, conversation_id,
) -> None:
    result = await plugin.execute_tool(
        "create", {"title": "B", "shapes": _SHAPES}, _exec_ctx(conversation_id),
    )
    assert result.success, result.content
    payload = json.loads(result.content)
    aid = payload["board_id"]
    assert payload["board_url"] == f"/api/artifacts/{aid}/content"
    artifact = await registry.get_artifact(aid)
    assert artifact is not None
    assert artifact.kind is ArtifactKind.WHITEBOARD
    assert artifact.conversation_id == conversation_id
    assert artifact.artifact_metadata["shape_count"] == 2


async def test_get_whiteboard_summarises_shapes(plugin, conversation_id) -> None:
    created = await plugin.execute_tool(
        "create", {"title": "B", "shapes": _SHAPES}, _exec_ctx(conversation_id),
    )
    aid = json.loads(created.content)["board_id"]
    res = await plugin.execute_tool("get", {"board_id": aid}, _exec_ctx())
    assert res.success
    data = json.loads(res.content)
    assert data["board_id"] == aid
    assert data["shape_count"] == 2


async def test_add_shapes_merges_snapshot(plugin, registry, conversation_id) -> None:
    created = await plugin.execute_tool(
        "create", {"title": "B", "shapes": _SHAPES}, _exec_ctx(conversation_id),
    )
    aid = json.loads(created.content)["board_id"]
    res = await plugin.execute_tool(
        "add_shapes",
        {"board_id": aid, "shapes": [{"type": "note", "id": "n3", "text": "Nota"}]},
        _exec_ctx(),
    )
    assert res.success, res.content
    artifact = await registry.get_artifact(aid)
    assert artifact.artifact_metadata["shape_count"] == 3


async def test_list_scoped_to_current_conversation(
    plugin, conversation_id,
) -> None:
    await plugin.execute_tool(
        "create", {"title": "Mine"}, _exec_ctx(conversation_id),
    )
    await plugin.execute_tool("create", {"title": "Orphan"}, _exec_ctx())
    res = await plugin.execute_tool("list", {}, _exec_ctx(conversation_id))
    assert res.success
    payload = json.loads(res.content)
    assert payload["total"] == 1
    assert payload["boards"][0]["title"] == "Mine"


async def test_delete_whiteboard_removes_row_and_blob(
    plugin, registry, tmp_path,
) -> None:
    created = await plugin.execute_tool("create", {"title": "B"}, _exec_ctx())
    aid = json.loads(created.content)["board_id"]
    res = await plugin.execute_tool("delete", {"board_id": aid}, _exec_ctx())
    assert res.success
    assert await registry.get_artifact(aid) is None
    assert not (tmp_path / "whiteboard" / f"{aid}.json").exists()
```

- [x] **Step 2: Esegui i test per vederli fallire**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_whiteboard_plugin.py -v
```

Atteso: FAIL.

- [x] **Step 3: Riscrivi `plugins/whiteboard/plugin.py`**

Schema e `get_tools()` INVARIATI; `_extract_shapes_summary` e `shape_builder.py` restano.

3a. Import: rimuovi `from backend.core.config import PROJECT_ROOT` e `from .store import WhiteboardStore`; `from uuid import uuid4` → `from uuid import UUID, uuid4`; aggiungi `from backend.db.models import ArtifactKind`; estendi `TYPE_CHECKING` con `from backend.services.artifacts import ArtifactRegistry`. Import modelli: `from .models import SimpleShape, WhiteboardPayload, WhiteboardSpec` (invariato).

3b. Helper a livello modulo (dopo `_extract_shapes_summary`):

```python
def _parse_artifact_id(value: str) -> UUID | None:
    """Parse *value* as an artifact UUID; ``None`` when malformed."""
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None
```

3c. `__init__`/property/`initialize`/`cleanup` come per il chart plugin: via `self._store`, `initialize` logga `"WhiteboardPlugin inizializzato (registry-backed)"`, accessor `_registry()` identico. In `execute_tool` sostituisci il check store con il check registry (stesso testo del Task 3).

3d. Handler:

```python
    async def _create(
        self, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        """Crea una nuova lavagna, opzionalmente pre-popolata."""
        title = (args.get("title") or "").strip()
        if not title:
            return ToolResult.error("Missing required parameter: title")

        cfg = self.ctx.config.whiteboard
        registry = self._registry()
        count = await registry.count_artifacts(kind=ArtifactKind.WHITEBOARD)
        if count >= cfg.max_boards:
            return ToolResult.error(
                f"Limite massimo di lavagne raggiunto ({cfg.max_boards}). "
                "Usa `whiteboard_delete` per eliminare lavagne non più necessarie."
            )

        aid = uuid4()
        now = datetime.now(timezone.utc)

        raw_shapes = args.get("shapes", [])
        shapes = [SimpleShape(**s) for s in raw_shapes] if raw_shapes else []
        snapshot = build_snapshot(shapes)

        conversation_id = _parse_artifact_id(
            args.get("conversation_id") or context.conversation_id or "",
        )

        spec = WhiteboardSpec(
            board_id=str(aid),
            title=title,
            description=args.get("description", ""),
            conversation_id=str(conversation_id) if conversation_id else None,
            snapshot=snapshot,
            created_at=now,
            updated_at=now,
        )
        await registry.create_json_artifact(
            kind=ArtifactKind.WHITEBOARD,
            title=title,
            content=spec.model_dump(mode="json"),
            conversation_id=conversation_id,
            metadata={"description": spec.description},
            artifact_id=aid,
        )
        self.logger.info(
            f"Whiteboard '{title}' creata (id={aid}, shapes={len(shapes)})"
        )

        payload = WhiteboardPayload(
            board_id=str(aid),
            title=title,
            board_url=f"/api/artifacts/{aid}/content",
            conversation_id=str(conversation_id) if conversation_id else None,
            created_at=now,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.whiteboard+json",
        )

    async def _get(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        """Recupera il contenuto completo di una lavagna in formato leggibile."""
        board_id = (args.get("board_id") or "").strip()
        aid = _parse_artifact_id(board_id)
        if aid is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        result = await self._registry().read_json_content(aid)
        if result is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        artifact, content = result

        snapshot = content.get("snapshot") or {}
        shapes_info = _extract_shapes_summary(
            snapshot if isinstance(snapshot, dict) else {},
        )
        out = {
            "board_id": str(artifact.id),
            "title": artifact.title,
            "description": content.get("description", ""),
            "conversation_id": (
                str(artifact.conversation_id)
                if artifact.conversation_id else None
            ),
            "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
            "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
            "shapes": shapes_info,
            "shape_count": len(shapes_info),
        }
        return ToolResult.ok(
            json.dumps(out, ensure_ascii=False, default=str),
            content_type="application/json",
        )

    async def _add_shapes(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        """Aggiunge shapes a una lavagna esistente senza rimpiazzare."""
        board_id = (args.get("board_id") or "").strip()
        aid = _parse_artifact_id(board_id)
        if aid is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        registry = self._registry()
        result = await registry.read_json_content(aid)
        if result is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        artifact, content = result

        raw_shapes = args.get("shapes")
        if not raw_shapes or not isinstance(raw_shapes, list):
            return ToolResult.error("Missing required parameter: shapes")
        new_shapes = [SimpleShape(**s) for s in raw_shapes]

        snapshot = content.get("snapshot")
        merged = merge_shapes_into_snapshot(
            snapshot if isinstance(snapshot, dict) else {}, new_shapes,
        )
        await registry.update_json_artifact(aid, content_patch={"snapshot": merged})
        self.logger.info(
            f"Whiteboard '{artifact.title}' aggiornata: +{len(new_shapes)} shapes"
        )

        payload = WhiteboardPayload(
            board_id=str(artifact.id),
            title=artifact.title,
            board_url=f"/api/artifacts/{artifact.id}/content",
            conversation_id=(
                str(artifact.conversation_id)
                if artifact.conversation_id else None
            ),
            created_at=artifact.created_at,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.whiteboard+json",
        )

    async def _update(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        """Sovrascrive completamente il contenuto di una lavagna."""
        board_id = (args.get("board_id") or "").strip()
        aid = _parse_artifact_id(board_id)
        if aid is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        registry = self._registry()
        result = await registry.read_json_content(aid)
        if result is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        artifact, _content = result

        raw_shapes = args.get("shapes")
        if not raw_shapes or not isinstance(raw_shapes, list):
            return ToolResult.error("Missing required parameter: shapes")
        shapes = [SimpleShape(**s) for s in raw_shapes]

        patch: dict[str, Any] = {"snapshot": build_snapshot(shapes)}
        new_title = args.get("title") if "title" in args else None
        if new_title is not None:
            patch["title"] = new_title
        updated = await registry.update_json_artifact(
            aid, content_patch=patch, title=new_title,
        )
        if updated is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        self.logger.info(f"Whiteboard '{updated.title}' sovrascritta (id={aid})")

        payload = WhiteboardPayload(
            board_id=str(updated.id),
            title=updated.title,
            board_url=f"/api/artifacts/{updated.id}/content",
            conversation_id=(
                str(updated.conversation_id)
                if updated.conversation_id else None
            ),
            created_at=artifact.created_at,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.whiteboard+json",
        )

    async def _list(
        self, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        """Elenca le lavagne con paginazione, scope default = conversazione corrente."""
        limit = min(int(args.get("limit", 20)), 100)
        offset = max(int(args.get("offset", 0)), 0)
        # Default to current conversation to prevent cross-conversation leakage.
        conversation_id = _parse_artifact_id(
            args.get("conversation_id", context.conversation_id) or "",
        )

        registry = self._registry()
        items, total = await registry.list_artifacts(
            kind=ArtifactKind.WHITEBOARD,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )
        boards = [
            {
                "board_id": str(a.id),
                "title": a.title,
                "description": str(a.artifact_metadata.get("description") or ""),
                "conversation_id": (
                    str(a.conversation_id) if a.conversation_id else None
                ),
                "created_at": a.created_at,
                "updated_at": a.updated_at,
                "shape_count": int(a.artifact_metadata.get("shape_count") or 0),
            }
            for a in items
        ]
        payload = {
            "boards": boards,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        return ToolResult.ok(json.dumps(payload, ensure_ascii=False, default=str))

    async def _delete(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        """Elimina una lavagna (riga + blob)."""
        board_id = (args.get("board_id") or "").strip()
        aid = _parse_artifact_id(board_id)
        if aid is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        registry = self._registry()
        artifact = await registry.get_artifact(aid)
        if artifact is None or artifact.kind is not ArtifactKind.WHITEBOARD:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        deleted = await registry.delete_artifact(aid, delete_file=True)
        if not deleted:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        return ToolResult.ok(f"Lavagna eliminata: {board_id}")
```

NOTA su `_list`: `registry.list_artifacts` con `conversation_id=None` lista TUTTE le lavagne — parità col comportamento attuale quando il context non ha conversazione. Elimina `backend/plugins/whiteboard/store.py`.

3e. ATTENZIONE al test `test_list_scoped_to_current_conversation`: la lavagna "Orphan" ha `conversation_id=None`, e `list` con conversazione corrente filtra per quella conversazione → total 1. Verifica che `list_artifacts` filtri correttamente (`where Artifact.conversation_id == conv` esclude i NULL: sì).

- [x] **Step 4: `_build_whiteboard_context` dal registry**

In `backend/api/routes/chat/_helpers.py` sostituisci il corpo di `_build_whiteboard_context` (righe 305-357) con:

```python
async def _build_whiteboard_context(
    ctx: AppContext, conversation_id: str
) -> str | None:
    """Build a brief context block listing whiteboards for the current conversation.

    Injected into the system prompt so the LLM knows which boards already
    exist and can reference or update them instead of creating duplicates.
    Reads the unified artifact registry (kind=whiteboard) — no plugin
    internals involved.

    Args:
        ctx: Application context with the artifact registry.
        conversation_id: The current conversation's UUID as a string.

    Returns:
        A markdown context block, or None if no whiteboards or registry unavailable.
    """
    registry = getattr(ctx, "artifact_registry", None)
    if registry is None:
        return None
    try:
        items, _total = await registry.list_artifacts(
            kind=ArtifactKind.WHITEBOARD, conversation_id=conversation_id,
        )
    except Exception as exc:
        logger.warning("Whiteboard context fetch failed for conv={}: {}", conversation_id, exc)
        return None
    if not items:
        return None

    now = datetime.now(UTC)
    lines = ["[LAVAGNE ASSOCIATE A QUESTA CONVERSAZIONE]"]
    for item in items:
        updated = item.updated_at
        if updated is not None and updated.tzinfo is None:
            # SQLite round-trip may strip tzinfo; registry writes UTC.
            updated = updated.replace(tzinfo=UTC)
        if updated:
            delta = now - updated
            hours = int(delta.total_seconds() // 3600)
            if hours < 1:
                age = "aggiornata poco fa"
            elif hours < 24:
                age = f"aggiornata {hours}h fa"
            else:
                days = hours // 24
                age = f"aggiornata {days}g fa"
        else:
            age = ""
        shape_count = int(item.artifact_metadata.get("shape_count") or 0)
        shape_info = f"{shape_count} shape" if shape_count else "vuota"
        extra = f", {age}" if age else ""
        lines.append(
            f'- "{item.title}" (id: {item.id}) — {shape_info}{extra}'
        )
    lines.append("[/LAVAGNE ASSOCIATE]")
    return "\n".join(lines)
```

Aggiungi `from backend.db.models import ArtifactKind` agli import del file (verifica prima che non importi già da `backend.db.models`: in tal caso estendi quella riga).

- [x] **Step 5: Route, config, baseline**

- Elimina `backend/api/routes/whiteboards.py`; in `routes/__init__.py` togli `whiteboards` dall'import e `router.include_router(whiteboards.router)` (riga 27).
- In `backend/core/config.py` rimuovi da `WhiteboardConfig`:

```python
    whiteboard_output_dir: str = "data/whiteboards"
    """Directory dove vengono salvati i board spec JSON."""
```

- In `config/default.yaml` rimuovi la riga `  whiteboard_output_dir: "data/whiteboards"`.
- In `response_model_baseline.txt` rimuovi le 3 voci:

```
DELETE /api/whiteboards/{board_id}
GET /api/whiteboards
GET /api/whiteboards/{board_id}
PATCH /api/whiteboards/{board_id}/snapshot
```

(NOTA: sono 4 righe — il titolo del task dice "−3" per simmetria col chart ma le voci whiteboard in baseline sono QUATTRO, righe 13, 55, 56, 59: rimuovile tutte.)
- Elimina `backend/tests/test_whiteboard_route_scope.py`.

- [x] **Step 6: Test verdi**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_whiteboard_plugin.py tests/contracts/test_response_models.py -v
```

Atteso: PASS. Esegui anche una verifica grep che nessun consumatore residuo legga lo store:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "WhiteboardStore"; git grep -n "ChartStore"; git grep -n "whiteboard_output_dir"; git grep -n "chart_output_dir"
```

Atteso: 0 risultati nel codice (ammessi solo in `docs/`).

- [x] **Step 7: Lint scoped + commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m ruff check plugins/whiteboard/ api/routes/chat/_helpers.py tests/test_whiteboard_plugin.py
Set-Location C:\Users\Jays\Desktop\alice\alice
git add -A
git commit -m "refactor(whiteboard): whiteboard plugin on unified artifact registry; drop WhiteboardStore + /api/whiteboards" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Endpoint `GET/PATCH /api/artifacts/{id}/content` + pulizia conversazioni delegata al registry + regen contratti

**Files:**
- Modify: `backend/services/artifacts/schemas.py` (3 modelli content)
- Modify: `backend/services/artifacts/__init__.py` (export)
- Modify: `backend/api/routes/artifacts.py` (2 endpoint)
- Modify: `backend/api/routes/chat/conversations.py` (delete singola + delete all delegate al registry)
- Modify: `backend/tests/test_artifacts_route.py` (+2 test, fixture client lenta: NON di più)
- Regen: `.\scripts\gen-contracts.ps1`

- [ ] **Step 1: Scrivi i test che falliscono**

In `backend/tests/test_artifacts_route.py` aggiungi in coda (rispetta gli import esistenti del file; aggiungi `from backend.db.models import ArtifactKind` e `from backend.services.artifacts.blob_store import ArtifactBlobStore` se mancanti):

```python
async def test_content_roundtrip(app, client, tmp_path):
    """GET/PATCH /content: blob JSON servito e aggiornato via merge."""
    registry = app.state.context.artifact_registry
    registry._blob_store = ArtifactBlobStore(tmp_path)
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD,
        title="b",
        content={
            "board_id": "b1",
            "snapshot": {"store": {}},
            "updated_at": "2026-06-12T00:00:00+00:00",
        },
    )

    r = await client.get(f"/api/artifacts/{artifact.id}/content")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "whiteboard"
    assert body["content"]["board_id"] == "b1"

    r2 = await client.patch(
        f"/api/artifacts/{artifact.id}/content",
        json={"content": {"snapshot": {"store": {"shape:s1": {"typeName": "shape"}}}}},
    )
    assert r2.status_code == 200
    assert r2.json()["artifact_id"] == str(artifact.id)

    r3 = await client.get(f"/api/artifacts/{artifact.id}")
    assert r3.json()["artifact_metadata"]["shape_count"] == 1


async def test_content_404_for_binary_artifact(app, client, tmp_path):
    """GET /content su un artifact binario (CAD) → 404."""
    registry = app.state.context.artifact_registry
    glb = tmp_path / "m.glb"
    glb.write_bytes(b"glTF")
    artifact = await registry.register_from_tool_result(
        conversation_id=uuid.uuid4(),
        message_id=None,
        tool_call_id="tc1",
        tool_name="cad_generate",
        payload={"file_path": str(glb), "model_name": "m", "description": "d"},
        content_type=None,
    )
    assert artifact is not None
    r = await client.get(f"/api/artifacts/{artifact.id}/content")
    assert r.status_code == 404
```

NOTA: `register_from_tool_result` richiede una `Conversation` esistente? No — `conversation_id` non ha vincolo FK enforced su SQLite di default nei test esistenti; verifica come fanno i test esistenti del file (`test_full_pin_and_filter_flow`) a registrare artifact e replica ESATTAMENTE quel pattern (inclusa l'eventuale creazione della Conversation) se il vincolo è enforced.

- [ ] **Step 2: Esegui per vederli fallire**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_artifacts_route.py -v
```

Atteso: i 2 test nuovi FAIL con 404/405 (endpoint inesistenti); i preesistenti PASS.

- [ ] **Step 3: Modelli in `schemas.py`**

In `backend/services/artifacts/schemas.py` aggiungi in coda:

```python
class ArtifactContentResponse(BaseModel):
    """JSON content of a JSON-kind artifact (chart spec, whiteboard spec)."""

    artifact_id: uuid.UUID
    kind: ArtifactKind
    content: dict[str, Any]


class ArtifactContentUpdate(BaseModel):
    """Body of ``PATCH /api/artifacts/{id}/content`` (top-level merge)."""

    content: dict[str, Any]


class ArtifactContentUpdateResponse(BaseModel):
    """Outcome of a content merge."""

    artifact_id: uuid.UUID
    updated_at: datetime
```

e in `services/artifacts/__init__.py` esporta `ArtifactContentResponse`, `ArtifactContentUpdate`, `ArtifactContentUpdateResponse` (import + `__all__`).

- [ ] **Step 4: Endpoint in `routes/artifacts.py`**

Aggiorna l'import da `backend.services.artifacts` aggiungendo i 3 modelli; aggiungi `import json` agli import. Dopo `pin_artifact` aggiungi:

```python
_MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MiB (same guard as the old whiteboard PATCH)


@router.get(
    "/{artifact_id}/content",
    response_model=ArtifactContentResponse,
    summary="Get the JSON content of an artifact",
)
async def get_artifact_content(
    artifact_id: str, request: Request,
) -> ArtifactContentResponse:
    """Return the JSON blob for chart/whiteboard artifacts (404 otherwise)."""
    registry = _get_registry(request)
    result = await registry.read_json_content(_to_uuid(artifact_id))
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact has no JSON content: {artifact_id}",
        )
    artifact, content = result
    return ArtifactContentResponse(
        artifact_id=artifact.id, kind=artifact.kind, content=content,
    )


@router.patch(
    "/{artifact_id}/content",
    response_model=ArtifactContentUpdateResponse,
    summary="Merge top-level keys into the JSON content of an artifact",
)
async def update_artifact_content(
    artifact_id: str, body: ArtifactContentUpdate, request: Request,
) -> ArtifactContentUpdateResponse:
    """Top-level merge into the blob (used by the whiteboard editor)."""
    registry = _get_registry(request)
    try:
        size = len(json.dumps(body.content, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Content non serializzabile: {exc}",
        ) from exc
    if size > _MAX_CONTENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Content troppo grande ({size} bytes). "
                f"Massimo consentito: {_MAX_CONTENT_BYTES} bytes."
            ),
        )
    artifact = await registry.update_json_artifact(
        _to_uuid(artifact_id), content_patch=body.content,
    )
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact has no JSON content: {artifact_id}",
        )
    return ArtifactContentUpdateResponse(
        artifact_id=artifact.id, updated_at=artifact.updated_at,
    )
```

- [ ] **Step 5: `conversations.py` delega al registry**

5a. `delete_all_conversations` (righe 414-463): sostituisci l'INTERO corpo con

```python
@router.delete("/chat/conversations", response_model=DeleteAllConversationsResponse)
async def delete_all_conversations(request: Request) -> dict[str, Any]:
    """Delete ALL conversations, messages, attachments, and associated files."""
    ctx = _ctx(request)

    # Artifacts first: rows + on-disk blobs die in one place (the
    # unified registry — fase 3); pinned status is irrelevant because
    # the user explicitly asked to delete EVERYTHING.
    registry = getattr(ctx, "artifact_registry", None)
    if registry is not None:
        await registry.delete_all()

    async with ctx.db() as session:
        # Use the underlying SA connection for DML (avoids SQLModel exec() warning).
        conn = await session.connection()
        await conn.execute(sa.delete(Attachment))
        await conn.execute(sa.delete(Message))
        await conn.execute(sa.delete(Conversation))
        await session.commit()

    # Remove all upload directories.
    uploads_base = PROJECT_ROOT / "data" / "uploads"
    if uploads_base.exists():
        removed_dirs = 0
        for child in uploads_base.iterdir():
            if child.is_dir():
                await asyncio.to_thread(shutil.rmtree, child, True)
                removed_dirs += 1
        logger.debug("Removed {} upload directories", removed_dirs)

    logger.info("Deleted all conversations")
    return {"status": "deleted"}
```

5b. `delete_conversation` (righe 466-574): sostituisci l'INTERO corpo con

```python
@router.delete("/chat/conversations/{conversation_id}", response_model=DeleteConversationResponse)
async def delete_conversation(
    conversation_id: uuid.UUID, request: Request
) -> dict[str, str]:
    """Delete a conversation and all its messages.

    Uses bulk SQL DELETE statements to avoid async lazy-loading issues
    with SQLAlchemy ORM relationships.  Artifact cleanup (detach pinned,
    delete unpinned rows + blobs) is delegated to the unified registry.
    """
    ctx = _ctx(request)
    async with ctx.db() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # ── Artifacts (single implementation in the registry) ──────────────
    registry = getattr(ctx, "artifact_registry", None)
    if registry is not None:
        await registry.delete_for_conversation(conversation_id)

    async with ctx.db() as session:
        # Collect message IDs for attachment cleanup.
        msg_stmt = select(Message.id).where(
            Message.conversation_id == conversation_id
        )
        results = await session.exec(msg_stmt)
        msg_ids: list[uuid.UUID] = list(results.all())

        # Use the underlying SA connection for DML (avoids SQLModel exec() warning).
        conn = await session.connection()

        # Bulk-delete attachments for those messages.
        if msg_ids:
            await conn.execute(
                sa.delete(Attachment).where(
                    Attachment.message_id.in_(msg_ids)  # type: ignore[union-attr]
                )
            )

        # Bulk-delete messages.
        await conn.execute(
            sa.delete(Message).where(
                Message.conversation_id == conversation_id
            )
        )

        # Bulk-delete conversation (avoids ORM relationship lazy-load).
        await conn.execute(
            sa.delete(Conversation).where(
                Conversation.id == conversation_id
            )
        )

        await session.commit()

    # Clean up uploaded files for this conversation.
    upload_dir = PROJECT_ROOT / "data" / "uploads" / str(conversation_id)
    if upload_dir.exists():
        await asyncio.to_thread(shutil.rmtree, upload_dir, True)
        logger.debug("Removed upload dir {}", upload_dir)

    # Kill any live interactive terminal sessions (PTYs + process trees)
    # for this conversation — they have no DB row to cascade-delete.
    terminal_manager = getattr(ctx, "terminal_session_manager", None)
    if terminal_manager is not None:
        try:
            await terminal_manager.cleanup_conversation(str(conversation_id))
        except Exception as exc:
            logger.warning(
                "Terminal cleanup failed for {}: {}", conversation_id, exc,
            )

    return {"status": "deleted"}
```

5c. Pulisci gli import del file: `Artifact` e `Path` potrebbero diventare inutilizzati — verifica con

```powershell
..\.venv\Scripts\python.exe -m ruff check api/routes/chat/conversations.py
```

e rimuovi SOLO gli import segnalati come unused (F401), niente altro.

- [ ] **Step 6: Test verdi + regen + commit + check**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_artifacts_route.py tests/contracts/ -v
```

Atteso: FAIL su `test_openapi_export` finché non rigeneri. Quindi:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
.\scripts\gen-contracts.ps1
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_artifacts_route.py tests/contracts/ -v
```

Atteso: PASS. FE typecheck (i tipi generati sono cambiati: route charts/whiteboards rimosse — il FE le chiama solo da `api.ts` con stringhe, quindi il typecheck resta verde):

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\frontend
npm run typecheck
```

Atteso: exit 0. Commit + verifica:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add -A
git commit -m "feat(artifacts): typed GET/PATCH content endpoints; conversation deletion delegates artifact cleanup to registry" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
.\scripts\check-contracts.ps1
```

Atteso: check-contracts verde.

---

### Task 6: FE — dominio chart sullo store artifacts unificato

**Files:**
- Modify: `frontend/src/renderer/src/types/artifacts.ts` (re-export `ApiSchema`)
- Modify: `frontend/src/renderer/src/types/chat.ts` (sposta `isChartPayload`/`extractCharts`)
- Modify: `frontend/src/renderer/src/services/api.ts` (content endpoints)
- Modify: `frontend/src/renderer/src/stores/artifacts.ts` (byKind + cache contenuti)
- Delete: `frontend/src/renderer/src/stores/charts.ts`, `frontend/src/renderer/src/stores/charts.spec.ts`
- Create: `frontend/src/renderer/src/types/chat.spec.ts`
- Modify: `frontend/src/renderer/src/components/chat/ChartViewer.vue`, `components/canvas/modules/ChartModule.vue`, `components/chat/MessageBubble.vue`, `composables/workspace/useArtifactAutoOpen.ts`

- [ ] **Step 1: Tipi generati al posto dei duplicati a mano**

Sostituisci l'INTERO contenuto di `types/artifacts.ts` con:

```ts
/**
 * artifacts.ts — Frontend types for the AL\CE artifacts registry.
 *
 * Re-exports of the GENERATED OpenAPI schemas (single source of truth:
 * backend/services/artifacts/schemas.py). Fields with backend defaults
 * (artifact_metadata, pinned, conversation_id, …) are OPTIONAL here —
 * consumers must use `??` fallbacks.
 */

import type { ApiSchema } from './generated'

/** Kinds of persisted artifacts (generated enum). */
export type ArtifactKind = ApiSchema<'ArtifactKind'>

/** Single persisted artifact row, as returned by the REST API. */
export type Artifact = ApiSchema<'ArtifactRead'>

/** Paginated artifact list response. */
export type ArtifactListResponse = ApiSchema<'ArtifactListResponse'>

/** JSON content envelope for chart/whiteboard artifacts. */
export type ArtifactContentResponse = ApiSchema<'ArtifactContentResponse'>

/** Outcome of a PATCH content merge. */
export type ArtifactContentUpdateResponse = ApiSchema<'ArtifactContentUpdateResponse'>

/** Query parameters accepted by ``GET /api/artifacts``. */
export interface ArtifactListQuery {
  conversation_id?: string
  kind?: ArtifactKind
  pinned?: boolean
  limit?: number
  offset?: number
}

/** Generated from the backend WS contract — do not redefine locally. */
export type ArtifactCreatedEvent = ApiSchema<'WsArtifactCreated'>
```

Poi `npm run typecheck`: gli errori elencano i consumatori che assumevano campi NON opzionali (`artifact_metadata`, `pinned`, `conversation_id`). Correggili con fallback espliciti (`a.pinned ?? false`, `a.artifact_metadata ?? {}`, `a.conversation_id ?? null`) — NON reintrodurre tipi a mano. Punti noti: `stores/artifacts.ts` (`pinnedItems`, `byConversation`), `MessageBubble.vue`, `CADViewer.vue`, `Cad3dModule.vue`, `ArtifactBoardView.vue`, `useArtifactAutoOpen.ts`.

- [ ] **Step 2: Helper chart puri in `types/chat.ts`**

In `types/chat.ts`, dopo `isWhiteboardPayload` (riga ~211), aggiungi:

```ts
/** Type guard: checks if a parsed tool result is a ChartPayload. */
export function isChartPayload(p: unknown): p is ChartPayload {
  if (typeof p !== 'object' || p === null || Array.isArray(p)) return false
  const o = p as Record<string, unknown>
  return (
    typeof o.chart_id === 'string' &&
    typeof o.chart_url === 'string' &&
    typeof o.chart_type === 'string'
  )
}

/**
 * Extract every chart payload from a message list, in chronological order
 * (oldest → newest). Non-tool / non-JSON / non-chart messages are skipped.
 */
export function extractCharts(messages: ChatMessage[]): ChartPayload[] {
  const out: ChartPayload[] = []
  for (const msg of messages) {
    if (msg.role !== 'tool') continue
    try {
      const p = JSON.parse(msg.content) as unknown
      if (isChartPayload(p)) out.push(p)
    } catch {
      // not JSON — skip
    }
  }
  return out
}
```

(Se `ChatMessage` è definito più in basso nel file, sposta il blocco DOPO la sua definizione.)

- [ ] **Step 3: Sposta i test puri**

Crea `frontend/src/renderer/src/types/chat.spec.ts` trasferendo da `stores/charts.spec.ts` i test di `isChartPayload`/`extractCharts` (aggiorna gli import a `./chat`; elimina i `describe` legati a `useChartsStore`/Pinia). Poi elimina `stores/charts.ts` e `stores/charts.spec.ts`.

- [ ] **Step 4: API client + store**

4a. In `services/api.ts`, sezione `-- Artifacts`, aggiungi dopo `getArtifact`:

```ts
  /** Fetch the JSON content of a chart/whiteboard artifact. */
  getArtifactContent: (id: string): Promise<ArtifactContentResponse> =>
    request<ArtifactContentResponse>(`/artifacts/${encodeURIComponent(id)}/content`),

  /** Merge top-level keys into the JSON content of an artifact. */
  updateArtifactContent: (
    id: string,
    content: Record<string, unknown>,
  ): Promise<ArtifactContentUpdateResponse> =>
    request<ArtifactContentUpdateResponse>(
      `/artifacts/${encodeURIComponent(id)}/content`,
      { method: 'PATCH', body: JSON.stringify({ content }) },
    ),
```

aggiornando l'import dei tipi artifacts in testa al file (`ArtifactContentResponse`, `ArtifactContentUpdateResponse`).

4b. In `stores/artifacts.ts`:

- estendi la mappa `byKind` con i nuovi kind:

```ts
    const map: Record<ArtifactKind, Artifact[]> = {
      cad_3d_text: [],
      cad_3d_image: [],
      chart: [],
      whiteboard: [],
    }
```

- aggiungi la cache contenuti dopo `fetchedConversations`:

```ts
  /** Cache of fetched JSON contents (chart/whiteboard), keyed by artifact id. */
  const contents = ref<Record<string, Record<string, unknown>>>({})
```

- aggiungi le azioni dopo `refreshById`:

```ts
  /** Fetch (and cache) the JSON content of a chart/whiteboard artifact. */
  async function fetchContent(
    id: string,
    force = false,
  ): Promise<Record<string, unknown> | null> {
    if (!force && contents.value[id]) return contents.value[id]
    try {
      const res = await api.getArtifactContent(id)
      contents.value[id] = res.content
      return res.content
    } catch (err) {
      console.warn('[artifacts] fetchContent failed:', err)
      return null
    }
  }

  /** Merge top-level keys into an artifact's JSON content (PATCH + local cache). */
  async function saveContent(
    id: string,
    patch: Record<string, unknown>,
  ): Promise<boolean> {
    try {
      await api.updateArtifactContent(id, patch)
      const cached = contents.value[id]
      if (cached) contents.value[id] = { ...cached, ...patch }
      return true
    } catch (err) {
      console.warn('[artifacts] saveContent failed:', err)
      return false
    }
  }
```

- in `removeLocal` aggiungi la riga `delete contents.value[id]` prima dello splice; in `remove` aggiungi `delete contents.value[id]` dopo lo splice. NOTA: `refreshById` NON tocca la cache contenuti (lo snapshot in editing non deve essere invalidato sotto le mani dell'utente — stessa staleness di oggi).
- esporta `contents`, `fetchContent`, `saveContent` nel return.

- [ ] **Step 5: ChartViewer + ChartModule + import fix**

5a. `components/chat/ChartViewer.vue`, in `loadAndRender` sostituisci

```ts
        const response = await fetch(resolveBackendUrl(props.payload.chart_url))
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const spec = await response.json()
        fetchedOption = sanitizeOption(spec.echarts_option)
```

con

```ts
        const res = await api.getArtifactContent(props.payload.chart_id)
        const spec = res.content as { echarts_option?: Record<string, unknown> }
        fetchedOption = sanitizeOption(spec.echarts_option ?? {})
```

aggiungendo `import { api } from '../../services/api'` e rimuovendo l'import di `resolveBackendUrl` SE non più usato altrove nel file (verifica con grep nel file).

5b. `components/canvas/modules/ChartModule.vue`: sostituisci la sezione script con la versione senza store charts:

```ts
import { computed, defineAsyncComponent } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import ModuleSelectorBar from '../ModuleSelectorBar.vue'
import { useChatStore } from '../../../stores/chat'
import { extractCharts, isChartPayload } from '../../../types/chat'
import { useModuleItemSelection } from '../../../composables/workspace/useModuleItemSelection'
import type { UiSegmentedOption } from '../../ui/UiSegmented.vue'
import type { ChartPayload } from '../../../types/chat'

const ChartViewer = defineAsyncComponent(() => import('../../chat/ChartViewer.vue'))

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const chatStore = useChatStore()

/** Charts in the active conversation, oldest → newest (derived from messages). */
const charts = computed<ChartPayload[]>(() => extractCharts(chatStore.messages))

const { current, currentId, select } = useModuleItemSelection<ChartPayload>({
  items: () => charts.value,
  getId: (c) => c.chart_id,
  preferredId: () => {
    const p = props.params?.chartPayload
    return isChartPayload(p) ? p.chart_id : null
  },
})

/**
 * Chart to display: the resolved selection, falling back to the raw param
 * payload if the message list hasn't populated yet (initial-load race).
 */
const chartPayload = computed<ChartPayload | null>(() => {
  if (current.value) return current.value
  const p = props.params?.chartPayload
  return isChartPayload(p) ? p : null
})

/** One selector option per chart in the conversation. */
const options = computed<UiSegmentedOption[]>(() =>
  charts.value.map((c, i) => ({ value: c.chart_id, label: c.title || `Grafico ${i + 1}` })),
)
```

(template e style INVARIATI; aggiorna il commento di testa del file: la lista deriva dai messaggi, non più da `useChartsStore`).

5c. `MessageBubble.vue`: `import { isChartPayload } from '../../stores/charts'` → spostalo nell'import esistente da `'../../types/chat'`.

5d. `useArtifactAutoOpen.ts`: `import { extractCharts } from '../../stores/charts'` → `from '../../types/chat'` (mergiando con l'import esistente di `isWhiteboardPayload`).

- [ ] **Step 6: Gate FE + commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\frontend
npm run typecheck
npx vitest run
npx eslint src/renderer/src/types/artifacts.ts src/renderer/src/types/chat.ts src/renderer/src/types/chat.spec.ts src/renderer/src/stores/artifacts.ts src/renderer/src/services/api.ts src/renderer/src/components/chat/ChartViewer.vue src/renderer/src/components/canvas/modules/ChartModule.vue src/renderer/src/components/chat/MessageBubble.vue src/renderer/src/composables/workspace/useArtifactAutoOpen.ts
```

Atteso: typecheck 0; vitest verdi (inclusi i test spostati); eslint senza ERRORI nuovi. Commit:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add -A
git commit -m "refactor(fe): charts on unified artifacts store; generated artifact types; content api" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: FE — dominio whiteboard sullo store artifacts unificato

**Files:**
- Create: `frontend/src/renderer/src/composables/whiteboard/useWhiteboardBoards.ts`
- Create: `frontend/src/renderer/src/composables/whiteboard/useWhiteboardBoards.spec.ts`
- Delete: `frontend/src/renderer/src/stores/whiteboard.ts`, `stores/whiteboard.spec.ts`, `types/whiteboard.ts`
- Modify: `frontend/src/renderer/src/services/api.ts` (rimuovi i 4 metodi whiteboard + import tipi)
- Modify: `components/canvas/modules/WhiteboardModule.vue`, `views/WhiteboardPageView.vue`, `components/whiteboard/WhiteboardListSidebar.vue`

- [ ] **Step 1: Composable view-model + test**

Crea `composables/whiteboard/useWhiteboardBoards.ts`:

```ts
/**
 * useWhiteboardBoards — shared view-model for whiteboards-as-artifacts.
 *
 * Derives the board list from the unified artifacts store
 * (kind='whiteboard'), mapping registry metadata (shape_count) and
 * resolving the conversation title from the chat store. Replaces the
 * retired 'whiteboard' Pinia store.
 */
import { computed, type ComputedRef } from 'vue'
import { useArtifactsStore } from '../../stores/artifacts'
import { useChatStore } from '../../stores/chat'
import type { Artifact } from '../../types/artifacts'

export interface WhiteboardBoardItem {
  /** Artifact id (the old board_id). */
  boardId: string
  title: string
  conversationId: string | null
  conversationTitle: string | null
  shapeCount: number
  /** ISO 8601 datetime. */
  updatedAt: string
}

/** Pure mapping Artifact → board view-model (exported for tests). */
export function toBoardItem(
  a: Artifact,
  titleOf: (id: string | null) => string | null,
): WhiteboardBoardItem {
  const meta = a.artifact_metadata ?? {}
  const convId = a.conversation_id ?? null
  return {
    boardId: a.id,
    title: a.title,
    conversationId: convId,
    conversationTitle: titleOf(convId),
    shapeCount: typeof meta.shape_count === 'number' ? meta.shape_count : 0,
    updatedAt: a.updated_at,
  }
}

export function useWhiteboardBoards(
  conversationId?: () => string | null | undefined,
): {
  boards: ComputedRef<WhiteboardBoardItem[]>
  loading: ComputedRef<boolean>
  refresh: () => Promise<void>
} {
  const artifactsStore = useArtifactsStore()
  const chatStore = useChatStore()

  function titleOf(id: string | null): string | null {
    if (!id) return null
    return chatStore.conversations.find((c) => c.id === id)?.title ?? null
  }

  const boards = computed<WhiteboardBoardItem[]>(() => {
    const convId = conversationId?.()
    return artifactsStore.items
      .filter((a) => a.kind === 'whiteboard')
      .filter((a) => (convId ? a.conversation_id === convId : true))
      .map((a) => toBoardItem(a, titleOf))
  })

  async function refresh(): Promise<void> {
    const convId = conversationId?.()
    await artifactsStore.fetch({
      kind: 'whiteboard',
      ...(convId ? { conversation_id: convId } : {}),
    })
  }

  return {
    boards,
    loading: computed(() => artifactsStore.loading),
    refresh,
  }
}
```

VERIFICA (prima di committare): il chat store espone la lista conversazioni come `conversations` con campi `id`/`title` — controlla `stores/chat.ts` e adatta `titleOf` al nome reale di stato e campi.

Crea `composables/whiteboard/useWhiteboardBoards.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { toBoardItem } from './useWhiteboardBoards'
import type { Artifact } from '../../types/artifacts'

const art = {
  id: 'a1',
  kind: 'whiteboard',
  title: 'Board',
  conversation_id: 'c1',
  artifact_metadata: { shape_count: 3, description: '' },
  created_at: '2026-06-12T00:00:00Z',
  updated_at: '2026-06-12T01:00:00Z',
  file_path: 'data/artifacts/whiteboard/a1.json',
  mime: 'application/json',
  size_bytes: 10,
  download_url: '/api/artifacts/a1/download',
} as unknown as Artifact

describe('toBoardItem', () => {
  it('maps registry metadata to the board view-model', () => {
    const item = toBoardItem(art, (id) => (id === 'c1' ? 'Conv' : null))
    expect(item.boardId).toBe('a1')
    expect(item.shapeCount).toBe(3)
    expect(item.conversationTitle).toBe('Conv')
    expect(item.updatedAt).toBe('2026-06-12T01:00:00Z')
  })

  it('defaults shapeCount to 0 and titles to null when metadata is missing', () => {
    const bare = { ...art, artifact_metadata: undefined, conversation_id: null } as unknown as Artifact
    const item = toBoardItem(bare, () => null)
    expect(item.shapeCount).toBe(0)
    expect(item.conversationTitle).toBeNull()
  })
})
```

- [ ] **Step 2: Esegui il test nuovo**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\frontend
npx vitest run src/renderer/src/composables/whiteboard/useWhiteboardBoards.spec.ts
```

Atteso: PASS.

- [ ] **Step 3: Riscrivi i tre componenti**

3a. `components/canvas/modules/WhiteboardModule.vue` — script sostituito (template: cambia solo i binding del selettore e di TldrawCanvas; lo stato vuoto resta):

```ts
import { computed, ref, watch, defineAsyncComponent } from 'vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import ModuleSelectorBar from '../ModuleSelectorBar.vue'
import { useArtifactsStore } from '../../../stores/artifacts'
import { useChatStore } from '../../../stores/chat'
import {
  useWhiteboardBoards,
  type WhiteboardBoardItem,
} from '../../../composables/whiteboard/useWhiteboardBoards'
import { useModuleItemSelection } from '../../../composables/workspace/useModuleItemSelection'
import type { UiSegmentedOption } from '../../ui/UiSegmented.vue'

const TldrawCanvas = defineAsyncComponent(() => import('../../whiteboard/TldrawCanvas.vue'))

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const artifactsStore = useArtifactsStore()
const chatStore = useChatStore()
const { boards, refresh } = useWhiteboardBoards(
  () => chatStore.currentConversation?.id ?? null,
)

const { currentId, select } = useModuleItemSelection<WhiteboardBoardItem>({
  items: () => boards.value,
  getId: (b) => b.boardId,
  preferredId: () => {
    const id = props.params?.boardId
    return typeof id === 'string' && id.length > 0 ? id : null
  },
})

/** Effective board id: resolved selection > param. */
const boardId = computed((): string | null => {
  if (currentId.value) return currentId.value
  const fromParams = props.params?.boardId
  if (typeof fromParams === 'string' && fromParams.length > 0) return fromParams
  return null
})

/** tldraw snapshot of the active board (from the artifact JSON content). */
const snapshot = ref<Record<string, unknown> | null>(null)

watch(
  boardId,
  async (id) => {
    snapshot.value = null
    if (!id) return
    const content = await artifactsStore.fetchContent(id)
    const snap = content?.snapshot
    snapshot.value = snap && typeof snap === 'object' ? (snap as Record<string, unknown>) : null
  },
  { immediate: true },
)

/** Persist snapshot changes via the unified store (top-level merge). */
function onSnapshotChange(snap: Record<string, unknown>): void {
  const id = boardId.value
  if (!id) return
  void artifactsStore.saveContent(id, { snapshot: snap })
}

/** One selector option per board in the conversation. */
const options = computed<UiSegmentedOption[]>(() =>
  boards.value.map((b, i) => ({ value: b.boardId, label: b.title || `Lavagna ${i + 1}` })),
)

/** Reload the board list when the active conversation changes. */
watch(
  () => chatStore.currentConversation?.id,
  (id) => {
    if (id) void refresh()
  },
  { immediate: true },
)
```

Nel template: `@update:model-value="(v) => select(String(v))"` invariato; `<TldrawCanvas v-if="boardId" :key="boardId" :board-id="boardId" :snapshot="snapshot" @change="onSnapshotChange" />` invariato nei binding.

3b. `views/WhiteboardPageView.vue` — script sostituito:

```ts
import { onMounted, ref, computed, defineAsyncComponent } from 'vue'
import { useArtifactsStore } from '../stores/artifacts'
import { useWhiteboardBoards } from '../composables/whiteboard/useWhiteboardBoards'
import WhiteboardListSidebar from '../components/whiteboard/WhiteboardListSidebar.vue'
import AppIcon from '../components/ui/AppIcon.vue'

const TldrawCanvas = defineAsyncComponent(
  () => import('../components/whiteboard/TldrawCanvas.vue')
)

const artifactsStore = useArtifactsStore()
const { boards, loading, refresh } = useWhiteboardBoards()

const currentBoardId = ref<string | null>(null)
const currentSnapshot = ref<Record<string, unknown> | null>(null)
const hasBoard = computed(() => currentBoardId.value !== null)

onMounted(() => {
  void refresh()
})

async function onSelectBoard(id: string): Promise<void> {
  currentBoardId.value = id
  currentSnapshot.value = null
  const content = await artifactsStore.fetchContent(id)
  const snap = content?.snapshot
  currentSnapshot.value = snap && typeof snap === 'object' ? (snap as Record<string, unknown>) : null
}

async function onDeleteBoard(id: string): Promise<void> {
  await artifactsStore.remove(id, true)
  if (currentBoardId.value === id) {
    currentBoardId.value = null
    currentSnapshot.value = null
  }
}

function onSnapshotChange(snapshot: Record<string, unknown>): void {
  if (!currentBoardId.value) return
  void artifactsStore.saveContent(currentBoardId.value, { snapshot })
}
```

Template: il sidebar diventa props-based —

```html
    <WhiteboardListSidebar
      :boards="boards"
      :active-board-id="currentBoardId"
      :loading="loading"
      @select="onSelectBoard"
      @delete="onDeleteBoard"
    />
```

e il canvas `<TldrawCanvas :board-id="currentBoardId ?? ''" :snapshot="currentSnapshot" @change="onSnapshotChange" />` (resto invariato).

3c. `components/whiteboard/WhiteboardListSidebar.vue` — script sostituito (style INVARIATO):

```ts
/**
 * WhiteboardListSidebar — Left sidebar listing whiteboards (artifact-backed).
 *
 * Pure presentational: receives the board view-models via props, emits
 * 'select' / 'delete'. State lives in the artifacts store upstream.
 */
import AppIcon from '../ui/AppIcon.vue'
import type { WhiteboardBoardItem } from '../../composables/whiteboard/useWhiteboardBoards'

defineProps<{
  boards: WhiteboardBoardItem[]
  activeBoardId: string | null
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'select', boardId: string): void
  (e: 'delete', boardId: string): void
}>()

/** Format a date string to a short readable format. */
function formatDate(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 86_400_000) {
    return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short' })
}
```

Template: sostituisci i riferimenti allo store (`store.total` → `boards.length`; `store.loading` → `loading`; `store.hasBoards` → `boards.length > 0`; `board.board_id` → `board.boardId`; `board.conversation_title` → `board.conversationTitle`; `board.shape_count` → `board.shapeCount`; `board.updated_at` → `board.updatedAt`; `activeBoardId` dalla prop).

- [ ] **Step 4: Eliminazioni + API client**

- Elimina `stores/whiteboard.ts`, `stores/whiteboard.spec.ts`, `types/whiteboard.ts`.
- In `services/api.ts`: rimuovi l'intera sezione `-- Whiteboards (Phase 16)` (i 4 metodi `getWhiteboards`/`getWhiteboard`/`deleteWhiteboard`/`saveWhiteboardSnapshot`) e l'import dei tipi da `'../types/whiteboard'`.
- Verifica residui:

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git grep -n "stores/whiteboard"; git grep -n "types/whiteboard"; git grep -n "useWhiteboardStore"; git grep -n "api/whiteboards"
```

Atteso: 0 risultati nel codice FE (ammessi in docs/ e nei tipi generati storici no — `types/generated` è rigenerato e non deve più contenere `/api/whiteboards`).

- [ ] **Step 5: Gate FE + commit**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\frontend
npm run typecheck
npx vitest run
npx eslint src/renderer/src/composables/whiteboard/useWhiteboardBoards.ts src/renderer/src/composables/whiteboard/useWhiteboardBoards.spec.ts src/renderer/src/components/canvas/modules/WhiteboardModule.vue src/renderer/src/views/WhiteboardPageView.vue src/renderer/src/components/whiteboard/WhiteboardListSidebar.vue src/renderer/src/services/api.ts
```

Atteso: typecheck 0, vitest verdi, eslint senza ERRORI nuovi.

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
git add -A
git commit -m "refactor(fe): whiteboards on unified artifacts store; drop whiteboard store/types + api methods" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Gate di fine fase + smoke reale

**Files:**
- Create (temporaneo, NON committare): `_smoke_fase3.py` alla radice
- Modify: questo piano (tick + esiti)

- [ ] **Step 1: Suite backend mirata completa**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\backend
..\.venv\Scripts\python.exe -m pytest tests/test_artifact_json.py tests/test_artifact_registry.py tests/test_artifacts_route.py tests/test_chart_plugin.py tests/test_whiteboard_plugin.py tests/contracts/ tests/test_backend_spec.py -v
```

Atteso: tutti PASS (le run con fixture `client` sono lente ~25s/test: NON killare, timeout 600s).

- [ ] **Step 2: Gate FE completo**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice\frontend
npm run typecheck
npx vitest run
```

Atteso: typecheck exit 0; vitest tutti verdi.

- [ ] **Step 3: check-contracts (workspace pulito post-commit)**

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
.\scripts\check-contracts.ps1
```

Atteso: verde.

- [ ] **Step 4: Smoke reale end-to-end**

4a. Crea `_smoke_fase3.py` alla radice (seed di una lavagna via registry, STESSO bootstrap di `backend/scripts/backfill_artifacts.py`):

```python
"""Smoke fase 3: seed whiteboard artifact via registry (run once, then delete)."""
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.config import load_config
from backend.db.database import create_engine_and_session, init_db
from backend.db.models import ArtifactKind
from backend.services.artifacts import ArtifactRegistry


async def main() -> None:
    config = load_config()
    engine, session_factory = create_engine_and_session(config.database.url)
    await init_db(engine)
    registry = ArtifactRegistry(session_factory=session_factory)
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD,
        title="smoke board fase3",
        content={
            "board_id": "",
            "title": "smoke board fase3",
            "description": "",
            "conversation_id": None,
            "snapshot": {"store": {"shape:s1": {"typeName": "shape", "id": "shape:s1"}}},
            "created_at": "2026-06-12T00:00:00+00:00",
            "updated_at": "2026-06-12T00:00:00+00:00",
        },
    )
    print(str(artifact.id))
    await engine.dispose()


asyncio.run(main())
```

```powershell
Set-Location C:\Users\Jays\Desktop\alice\alice
.\.venv\Scripts\python.exe _smoke_fase3.py
```

Atteso: stampa un UUID; verifica che esista `data/artifacts/whiteboard/<uuid>.json`.

4b. Avvia il server e verifica via REST (in due shell, o backgrounding):

```powershell
.\.venv\Scripts\python.exe -m backend
```

poi (seconda shell o dopo aver atteso il boot):

```powershell
$aid = "<uuid stampato sopra>"
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod "http://127.0.0.1:8000/api/artifacts?kind=whiteboard" | ConvertTo-Json -Depth 4
Invoke-RestMethod "http://127.0.0.1:8000/api/artifacts/$aid/content" | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Patch -ContentType "application/json" -Body '{"content":{"snapshot":{"store":{"shape:s1":{"typeName":"shape"},"shape:s2":{"typeName":"shape"}}}}}' "http://127.0.0.1:8000/api/artifacts/$aid/content"
Invoke-RestMethod "http://127.0.0.1:8000/api/artifacts/$aid" | ConvertTo-Json -Depth 4
```

Atteso: health 200; lista con l'artifact (kind whiteboard, shape_count 1 nei metadati); content col board; PATCH ok; rilettura con `artifact_metadata.shape_count == 2`. Spegni il server, elimina la riga smoke (facoltativo: `DELETE /api/artifacts/$aid?delete_file=true` prima di spegnere) ed ELIMINA `_smoke_fase3.py`.

- [ ] **Step 5: Verifica anti-regressione dirs legacy**

```powershell
Get-ChildItem data\charts, data\whiteboards -ErrorAction SilentlyContinue | Measure-Object
```

Atteso: le directory legacy (se esistono) sono INTATTE e nessun file nuovo vi è comparso durante lo smoke.

- [ ] **Step 6: Tick del piano + commit finale**

Spunta tutte le checkbox, annota gli esiti review per task (come da workflow fase 2), poi:

```powershell
git add docs/superpowers/plans/2026-06-12-fase3-contenuti-unificati.md
git commit -m "docs(plans): fase3 - tick task e criteri di uscita" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Criteri di uscita della fase (spec §9)

- [ ] Test mirati backend verdi (artifact json/registry/route, chart plugin, whiteboard plugin, contracts, backend_spec).
- [ ] `npm run typecheck` exit 0; vitest tutti verdi; eslint senza errori nuovi sui file toccati.
- [ ] `check-contracts.ps1` verde su workspace pulito.
- [ ] App avviabile (health 200) e feature di riferimento del dominio funzionante e2e (lista artifacts, content GET/PATCH con ricalcolo `shape_count`).
- [ ] `grep` = 0 per: `ChartStore`, `WhiteboardStore`, `chart_output_dir`, `whiteboard_output_dir`, `api/whiteboards`, `stores/whiteboard`, `useChartsStore`, `useWhiteboardStore` (fuori da docs/).
- [ ] Ratchet baseline: −7 voci (3 charts + 4 whiteboards); nessuna voce nuova.
- [ ] Review finale di fase (modello top, range intero `arch/fase2-persistenza..HEAD`, angolo = coerenza cross-task) con verdetto registrato in fondo a questo piano.

## Backlog (fuori scope fase 3, da riportare nell'handoff)

1. Eventi `artifact.deleted` per le delete bulk (`delete_for_conversation`/`delete_all`) + invalidazione FE dello store artifacts alla cancellazione conversazione (oggi: parità col comportamento pre-fase, item stale finché non si rifetcha).
2. Migrare i payload CAD (`export_url` → `/api/artifacts/{id}/download`) ed eliminare `/api/cad/models*` (fase 6, col client per dominio).
3. `GET /api/artifacts/{id}/download` e `DELETE /api/artifacts/{id}` restano in baseline ratchet (FileResponse binaria / 204 senza body): valutare in fase 6 se modellarli.
4. Live-update del whiteboard aperto quando l'agente fa `add_shapes` (ora il FE riceve `artifact.updated` ma non invalida la cache contenuti di proposito — serve un design per non strappare lo snapshot sotto l'editor).
5. Auto-open chart/whiteboard potrebbe passare dagli eventi `artifact.created` (oggi resta message-payload-based per parità).
6. `extractCharts`/`isChartPayload` e `isWhiteboardPayload` potrebbero unificarsi in un modulo `services/artifactPayloads.ts` se compare un terzo consumatore (fase 6).
