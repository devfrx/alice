# Fase 2 — Persistenza (SQLite unica fonte di verità) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SQLite diventa l'unica fonte di verità per le conversazioni: il mirror JSON automatico (`ConversationFileManager`) viene rimosso e sostituito da un comando di export/backup esplicito (endpoint REST + tool agente + voci UI), come da spec §5.2.

**Architecture:** Un nuovo servizio `backend/services/conversation_export.py` assorbe la serializzazione conversazione→dict (oggi `_build_conversation_data` in `_helpers.py`) e aggiunge l'export su directory. Route REST e tool del nuovo plugin `conversation_backup` delegano allo STESSO servizio (principio §1 della spec). Tutta la catena `sync_fn` / `ctx.conversation_file_manager` viene rimossa (turn engine, route chat, lifespan). Gli endpoint del dominio conversations toccati dalla fase guadagnano `response_model` (burn-down ratchet) e la lista passa alla convenzione `{items,total}`.

**Tech Stack:** FastAPI + Pydantic (response models), SQLModel/aiosqlite, plugin system AL\CE, openapi-typescript (contratti generati), Vue 3 + Pinia.

**Branch:** `arch/fase2-persistenza` (figlio di `arch/fase1b-ws-schema`).

---

## Contesto verificato (recon 2026-06-11, a mano)

Scrittori del mirror (`_sync_conversation_to_file`):
- `backend/services/turn/tool_loop.py` — righe ~447, ~675 (dentro `except WebSocketDisconnect`), ~700, ~1295; parametro `sync_fn` in `run_tool_loop`, `_persist_gate_outcome` (~1066), `_persist_client_tool_result` (~1262); alias `SyncFn` riga 43.
- `backend/services/turn/direct_executor.py` — param `sync_fn` (riga 67), `self._sync_fn` (71), pass-through a `run_tool_loop` (251), alias `SyncFn` (49).
- `backend/services/turn/factory.py` — param `sync_fn` (34), pass a `DirectTurnExecutor` (49), alias `SyncFn` (28).
- `backend/api/routes/chat/ws.py` — import (31), `create_turn_executor(ctx, llm, sync_fn=...)` (162-164), blocco recovery (215-220).
- `backend/api/routes/chat/_persist.py` — import (29), blocchi a ~162, ~241, ~384.
- `backend/api/routes/chat/_assembly.py` — import (57), blocco a ~312.
- `backend/api/routes/chat/conversations.py` — import (27, 34), blocchi sync a ~601 (title), ~683 (switch-version), ~857 (branch), ~961 (create); `file_manager.delete_all()` a ~426-429 (delete all), `file_manager.delete()` a ~537-541 (delete singola).
- `backend/api/routes/chat/io.py` — import (20, 22), endpoint `file-path` (111-136), sync nell'import (288-291).

Lettori del mirror: SOLO `rebuild_from_files` nel lifespan (`core/app.py:214-226`) e l'endpoint `file-path` (consumato da `AppSidebar.vue:212-219` «Apri nel file manager» via `api.getConversationFilePath`).

Definizioni da rimuovere: `services/conversation_file_manager.py` (intero file), `ConversationFileManagerProtocol` (`core/protocols.py:408-448`), campo `conversation_file_manager` (`core/context.py:59` + import a riga 19), import+costruzione+rebuild in `core/app.py` (riga 30 e 214-226).

Test esistenti coinvolti: `tests/test_conversation_file_manager.py` e `tests/test_conversation_migration.py` (da ELIMINARE); `tests/test_confirmation_toggle.py` (riga 85 `ctx.conversation_file_manager = None`, kwarg `sync_fn=None` alle righe 167, 189, 209, 239, 289, 331, 372); `tests/test_tool_loop.py` (riga 243 attr fake-ctx, riga 290 kwarg); `tests/test_turn_lifecycle_events.py` (riga 160 kwarg); `tests/test_app.py:33` e `tests/test_concurrent.py` (~255-319) usano `GET /api/chat/conversations` (cambia shape in Task 3).

Già esistenti e indipendenti dal mirror: `GET /chat/conversations/{id}/export` e `POST /chat/conversations/import` (entrambi costruiti dal DB). FE: `api.exportConversation` / `api.importConversation` + action nello store, MA nessuna UI le invoca.

Ratchet baseline (`backend/tests/contracts/response_model_baseline.txt`) — voci del dominio che questa fase brucia: `DELETE /api/chat/conversations`, `DELETE /api/chat/conversations/{conversation_id}`, `GET /api/chat/conversations`, `GET .../export`, `GET .../file-path` (endpoint eliminato), `POST /api/chat/conversations`, `POST .../import`, `POST .../switch-version`, `POST .../title`. Resta in baseline `GET /api/chat/conversations/{conversation_id}` (modello pesante, vedi Backlog).

---

### Task 1: Servizio `conversation_export` + test (TDD)

**Files:**
- Create: `backend/services/conversation_export.py`
- Create: `backend/tests/test_conversation_export.py`
- Modify: `backend/api/routes/chat/_shared.py` (sposta `_attachment_url` nel servizio, re-import)
- Modify: `backend/api/routes/chat/_helpers.py` (rimuovi `_build_conversation_data`, delega al servizio)
- Modify: `backend/api/routes/chat/io.py` (solo la riga di import di `_build_conversation_data`)

- [x] **Step 1: Scrivi il test che fallisce**

Crea `backend/tests/test_conversation_export.py`:

```python
"""AL\\CE — Tests for backend.services.conversation_export."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import Conversation, Message
from backend.services.conversation_export import (
    ConversationExport,
    build_conversation_export,
    export_conversations_to_dir,
)


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


async def _seed_conversation(session_factory, *, title: str = "Test") -> uuid.UUID:
    """Insert a conversation with one user + one assistant message."""
    async with session_factory() as session:
        conv = Conversation(title=title)
        session.add(conv)
        await session.flush()
        session.add(Message(conversation_id=conv.id, role="user", content="hi"))
        session.add(
            Message(
                conversation_id=conv.id,
                role="assistant",
                content="hello",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "f", "arguments": "{}"},
                    },
                ],
            ),
        )
        await session.commit()
        return conv.id


class TestBuildConversationExport:
    async def test_returns_full_dict(self, session_factory) -> None:
        conv_id = await _seed_conversation(session_factory)
        async with session_factory() as session:
            data = await build_conversation_export(session, conv_id)
        assert data["id"] == str(conv_id)
        assert data["title"] == "Test"
        assert len(data["messages"]) == 2
        assert data["messages"][1]["tool_calls"][0]["id"] == "call_1"
        # Il dict prodotto DEVE validare contro il modello del contratto.
        ConversationExport.model_validate(data)

    async def test_missing_conversation_returns_empty(self, session_factory) -> None:
        async with session_factory() as session:
            data = await build_conversation_export(session, uuid.uuid4())
        assert data == {}


class TestExportConversationsToDir:
    async def test_exports_all_to_directory(
        self, session_factory, tmp_path: Path,
    ) -> None:
        id_a = await _seed_conversation(session_factory, title="A")
        id_b = await _seed_conversation(session_factory, title="B")
        dest = tmp_path / "backup"

        exported = await export_conversations_to_dir(session_factory, dest)

        assert exported == 2
        for cid in (id_a, id_b):
            payload = json.loads(
                (dest / f"{cid}.json").read_text(encoding="utf-8"),
            )
            assert payload["id"] == str(cid)
        # Nessun file temporaneo residuo.
        assert list(dest.glob("*.tmp.*")) == []

    async def test_exports_subset_by_id(
        self, session_factory, tmp_path: Path,
    ) -> None:
        id_a = await _seed_conversation(session_factory, title="A")
        await _seed_conversation(session_factory, title="B")
        dest = tmp_path / "backup"

        exported = await export_conversations_to_dir(
            session_factory, dest, conversation_ids=[id_a],
        )

        assert exported == 1
        assert (dest / f"{id_a}.json").exists()
        assert len(list(dest.glob("*.json"))) == 1

    async def test_unknown_id_is_skipped(
        self, session_factory, tmp_path: Path,
    ) -> None:
        dest = tmp_path / "backup"
        exported = await export_conversations_to_dir(
            session_factory, dest, conversation_ids=[uuid.uuid4()],
        )
        assert exported == 0
```

- [x] **Step 2: Esegui il test e verifica che fallisca**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_conversation_export.py -v
```
Atteso: FAIL/ERROR con `ModuleNotFoundError: No module named 'backend.services.conversation_export'`.

- [x] **Step 3: Crea `backend/services/conversation_export.py`**

Il corpo di `build_conversation_export` è `_build_conversation_data` spostato VERBATIM da `_helpers.py` (righe 29-100); `_attachment_url` e `_UPLOADS_BASE` sono spostati VERBATIM da `_shared.py` (righe 32, 110-124):

```python
"""AL\\CE — Conversation export service (Fase 2, spec §5.2).

SQLite is the single source of truth for conversations. This module is the
ONE implementation of conversation serialization and explicit export/backup:
the REST routes (``api/routes/chat/io.py``) and the ``conversation_backup``
plugin tool both delegate here. There is no automatic mirror.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

from loguru import logger
from pydantic import BaseModel, Field
from sqlmodel import select

from backend.core.config import PROJECT_ROOT
from backend.db.models import Attachment, Conversation, Message

# Base path for uploaded files (used to build safe /uploads/… URLs).
_UPLOADS_BASE: Path = (PROJECT_ROOT / "data" / "uploads").resolve()


# ---------------------------------------------------------------------------
# Contract models (response_model of the export endpoint AND file schema)
# ---------------------------------------------------------------------------


class ExportedAttachment(BaseModel):
    """One attachment inside an exported message."""

    file_id: str
    url: str
    filename: str
    content_type: str
    file_path: str


class ExportedMessage(BaseModel):
    """One message inside a conversation export."""

    id: str
    role: str
    content: str
    thinking_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    created_at: str
    attachments: list[ExportedAttachment] | None = None
    version_group_id: str | None = None
    version_index: int = 0
    is_context_summary: bool = False
    context_excluded: bool = False


class ConversationExport(BaseModel):
    """Full conversation export (REST response body and backup file schema)."""

    id: str
    title: str | None
    created_at: str
    updated_at: str
    active_versions: dict[str, int] = Field(default_factory=dict)
    messages: list[ExportedMessage]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _attachment_url(file_path: str) -> str:
    """Build a safe ``/uploads/…`` URL from an attachment's file_path.

    Uses :meth:`pathlib.Path.relative_to` instead of string splitting
    to avoid path-traversal issues.  Components are percent-encoded.
    """
    try:
        relative = Path(file_path).resolve().relative_to(_UPLOADS_BASE)
        # Use POSIX-style separators so the URL works on Windows where
        # ``Path.__str__`` would otherwise yield backslashes (which the
        # static-file mount at ``/uploads`` does not match).
        return f"/uploads/{quote(relative.as_posix(), safe='/')}"
    except ValueError:
        logger.warning("Attachment path outside uploads base: {}", file_path)
        return ""


async def build_conversation_export(
    session: Any, conv_id: uuid.UUID,
) -> dict[str, Any]:
    """Build the full conversation dict (messages + attachments) from DB.

    The returned attachment dicts include **both** ``url`` (for API / frontend
    consumption) and ``file_path`` (for file-level backup / recovery).

    Args:
        session: An active async DB session.
        conv_id: The conversation UUID.

    Returns:
        A dict matching :class:`ConversationExport`, or ``{}`` if the
        conversation does not exist.
    """
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        return {}

    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at, Message.id)
    )
    results = await session.exec(msg_stmt)
    messages = results.all()

    msg_ids = [m.id for m in messages]
    att_map: dict[uuid.UUID, list[dict[str, str]]] = {}
    if msg_ids:
        att_stmt = select(Attachment).where(
            Attachment.message_id.in_(msg_ids)  # type: ignore[union-attr]
        )
        att_results = await session.exec(att_stmt)
        for att in att_results.all():
            url = _attachment_url(att.file_path)
            att_map.setdefault(att.message_id, []).append(
                {
                    "file_id": str(att.id),
                    "url": url,
                    "filename": att.filename,
                    "content_type": att.content_type,
                    "file_path": att.file_path,
                }
            )

    return {
        "id": str(conv.id),
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "active_versions": conv.active_versions or {},
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "thinking_content": m.thinking_content,
                "tool_calls": m.tool_calls,
                "tool_call_id": m.tool_call_id,
                "created_at": m.created_at.isoformat(),
                "attachments": att_map.get(m.id) or None,
                "version_group_id": str(m.version_group_id)
                if m.version_group_id
                else None,
                "version_index": m.version_index,
                "is_context_summary": getattr(m, "is_context_summary", False),
                "context_excluded": getattr(m, "context_excluded", False),
            }
            for m in messages
        ],
    }


# ---------------------------------------------------------------------------
# Explicit export / backup
# ---------------------------------------------------------------------------


def _atomic_write(target: Path, payload: str) -> None:
    """Write *payload* to *target* atomically (unique temp file + rename)."""
    tmp = target.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
    try:
        tmp.write_text(payload, encoding="utf-8", newline="\n")
        tmp.replace(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def export_conversations_to_dir(
    session_factory: Any,
    dest_dir: Path,
    conversation_ids: Sequence[uuid.UUID] | None = None,
) -> int:
    """Export conversations as ``{id}.json`` files into *dest_dir*.

    Args:
        session_factory: An ``async_sessionmaker`` for creating DB sessions.
        dest_dir: Destination directory (created if missing).
        conversation_ids: Optional subset to export; ``None`` exports all.

    Returns:
        Number of conversations exported (unknown ids are skipped).
    """
    await asyncio.to_thread(dest_dir.mkdir, parents=True, exist_ok=True)

    exported = 0
    async with session_factory() as session:
        if conversation_ids is None:
            results = await session.exec(select(Conversation.id))
            ids: list[uuid.UUID] = list(results.all())
        else:
            ids = list(conversation_ids)

        for conv_id in ids:
            data = await build_conversation_export(session, conv_id)
            if not data:
                logger.warning("Export: conversation {} not found", conv_id)
                continue
            target = dest_dir / f"{data['id']}.json"
            payload = json.dumps(data, ensure_ascii=False, indent=2)
            await asyncio.to_thread(_atomic_write, target, payload)
            exported += 1

    logger.info("Exported {} conversations to {}", exported, dest_dir)
    return exported
```

- [x] **Step 4: Esegui il test e verifica che passi**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_conversation_export.py -v
```
Atteso: tutti PASS.

- [x] **Step 5: Sposta i consumatori sulla nuova implementazione (no doppioni, §4.1)**

In `backend/api/routes/chat/_shared.py`: elimina la funzione `_attachment_url` (righe 110-124), la costante `_UPLOADS_BASE` (riga 32) e gli import diventati orfani (`quote` da `urllib.parse`; verifica `Path` e `logger` con ruff — `Path` resta usato? se no, rimuovi). In testa al file aggiungi il re-export (gli altri moduli chat continuano a importare da `_shared`):

```python
from backend.services.conversation_export import _attachment_url  # noqa: F401
```

In `backend/api/routes/chat/_helpers.py`: elimina l'intera funzione `_build_conversation_data` (righe 29-100) e fai delegare `_sync_conversation_to_file` al servizio (la funzione sparirà del tutto nel Task 4, per ora il filo resta integro):

```python
from backend.services.conversation_export import build_conversation_export
```

```python
async def _sync_conversation_to_file(
    session: Any, conv_id: uuid.UUID, file_manager: ConversationFileManager,
) -> None:
    """Build the conversation data from DB and persist it to a JSON file."""
    data = await build_conversation_export(session, conv_id)
    if data:
        await file_manager.save(data)
```

Rimuovi da `_helpers.py` gli import diventati orfani (`select` da sqlmodel, `Attachment`/`Conversation` da db.models, `_attachment_url` da `._shared` — verifica con ruff: `Message` resta usato da `_msg_to_raw_dict`).

In `backend/api/routes/chat/io.py` riga 22, sostituisci:

```python
from ._helpers import _build_conversation_data, _sync_conversation_to_file
```

con:

```python
from backend.services.conversation_export import build_conversation_export

from ._helpers import _sync_conversation_to_file
```

e nel corpo di `export_conversation` (riga 103) sostituisci `_build_conversation_data(session, conversation_id)` con `build_conversation_export(session, conversation_id)`.

- [x] **Step 6: Verifica regressione + lint**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_conversation_export.py tests/contracts/ -v
..\.venv\Scripts\python.exe -m ruff check services/conversation_export.py api/routes/chat/_shared.py api/routes/chat/_helpers.py api/routes/chat/io.py
..\.venv\Scripts\python.exe -m mypy services/conversation_export.py
```
Atteso: pytest PASS; ruff/mypy puliti sul file nuovo (sui file modificati: nessun errore NUOVO rispetto a `git stash`-baseline; errori pre-esistenti tollerati).

- [x] **Step 7: Commit**

```powershell
git add backend/services/conversation_export.py backend/tests/test_conversation_export.py backend/api/routes/chat/_shared.py backend/api/routes/chat/_helpers.py backend/api/routes/chat/io.py
git commit -m "feat(persistence): conversation_export service - single serialization + explicit dir export" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

> **Esito (2026-06-12):** COMPLETATO — commit `7b35ffc`. Spec review ✅; quality review «Ready to merge: Yes» con 1 Important (coverage attachment assente, gap pre-esistente) + minors. Fix post-review in `b022570`: 2 test attachment (round-trip url/file_id/file_path + fallback url vuota fuori base), dedup `conversation_ids` (`dict.fromkeys`), docstring con semantica partial-export. Gate: 7/7 test, ruff+mypy puliti. Recommendation registrata in Backlog (#5) e nel Task 3 (rename `_attachment_url`).

---

### Task 2: Route io.py — export tipizzato, endpoint backup, rimozione file-path

**Files:**
- Modify: `backend/api/routes/chat/io.py`
- Modify: `backend/tests/contracts/response_model_baseline.txt`
- Test: `backend/tests/test_conversation_backup_api.py` (create)

- [x] **Step 1: Scrivi i test che falliscono**

Crea `backend/tests/test_conversation_backup_api.py`. Usa le fixture `client`/`app` di `conftest.py` (httpx `AsyncClient` con lifespan eseguito; funzioni `async def` SENZA marker — asyncio mode auto, stesso stile di `test_app.py`). ATTENZIONE: la fixture `app` costa ~25s/test (gotcha noto) — tieni i test a 3:

```python
"""AL\\CE — API tests for explicit conversation backup (Fase 2)."""

from __future__ import annotations

import uuid
from pathlib import Path

from httpx import AsyncClient


async def test_backup_endpoint_exports_to_custom_dir(
    client: AsyncClient, tmp_path: Path,
) -> None:
    """POST /backup writes {id}.json files into dest_dir and reports count."""
    # Crea una conversazione via API così esiste nel DB dell'app di test.
    created = await client.post(
        "/api/chat/conversations", json={"id": str(uuid.uuid4())},
    )
    assert created.status_code == 200
    conv_id = created.json()["id"]

    dest = tmp_path / "out"
    resp = await client.post(
        "/api/chat/conversations/backup", json={"dest_dir": str(dest)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["exported"] >= 1
    assert body["path"] == str(dest)
    assert (dest / f"{conv_id}.json").exists()


async def test_backup_endpoint_rejects_relative_dir(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/chat/conversations/backup", json={"dest_dir": "relative/path"},
    )
    assert resp.status_code == 400


async def test_file_path_endpoint_removed(client: AsyncClient) -> None:
    resp = await client.get(
        f"/api/chat/conversations/{uuid.uuid4()}/file-path",
    )
    assert resp.status_code == 404
```

- [x] **Step 2: Esegui i test e verifica che falliscano**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_conversation_backup_api.py -v
```
Atteso: FAIL — `/backup` risponde 404 (endpoint inesistente); `file-path` risponde 200/503 (endpoint ancora vivo).

- [x] **Step 3: Modifica `io.py`**

(a) Aggiorna gli import: rimuovi `from backend.services.conversation_file_manager import ConversationFileManager`; aggiungi `from pydantic import BaseModel` e completa l'import dal servizio:

```python
from backend.services.conversation_export import (
    ConversationExport,
    build_conversation_export,
    export_conversations_to_dir,
)
```

(b) ELIMINA per intero l'endpoint `get_conversation_file_path` (righe 111-136, incluso il decoratore).

(c) Tipizza l'export — il decoratore diventa:

```python
@router.get(
    "/chat/conversations/{conversation_id}/export",
    response_model=ConversationExport,
)
```

(la firma resta `-> dict[str, Any]`: il `response_model` del decoratore vince e valida).

(d) Nell'`import_conversation` rimuovi il blocco sync (righe 288-291):

```python
        if ctx.conversation_file_manager:
            await _sync_conversation_to_file(
                session, conv_id, ctx.conversation_file_manager,
            )
```

e rimuovi `_sync_conversation_to_file` dall'import da `._helpers` (dopo questo task io.py non lo usa più). Aggiungi al decoratore `response_model=ConversationSummaryResponse` SOLO nel Task 3 (il modello nasce lì) — in questo task l'endpoint import resta non tipizzato.

(e) Aggiungi i modelli e l'endpoint backup (subito dopo l'endpoint import):

```python
class BackupRequest(BaseModel):
    """Request body for the explicit conversation backup command."""

    dest_dir: str | None = None
    conversation_ids: list[uuid.UUID] | None = None


class BackupResult(BaseModel):
    """Outcome of an explicit conversation backup."""

    exported: int
    path: str


@router.post("/chat/conversations/backup", response_model=BackupResult)
async def backup_conversations(
    body: BackupRequest, request: Request,
) -> BackupResult:
    """Export conversations as JSON files to an explicit destination.

    This is the user-facing replacement of the removed automatic JSON
    mirror (spec §5.2): SQLite is the single source of truth and backups
    happen only on explicit command (UI entry or agent tool).
    """
    ctx = _ctx(request)

    if body.dest_dir:
        dest = Path(body.dest_dir)
        if not dest.is_absolute():
            raise HTTPException(
                status_code=400, detail="dest_dir must be an absolute path",
            )
    else:
        stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
        dest = PROJECT_ROOT / "data" / "backups" / f"conversations-{stamp}"

    try:
        exported = await export_conversations_to_dir(
            ctx.db, dest, body.conversation_ids,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"Cannot write to destination: {exc}",
        ) from None

    return BackupResult(exported=exported, path=str(dest))
```

Aggiungi `from pathlib import Path` agli import di `io.py` se assente.

- [x] **Step 4: Aggiorna la baseline ratchet**

Da `backend/tests/contracts/response_model_baseline.txt` elimina le DUE righe:

```
GET /api/chat/conversations/{conversation_id}/export
GET /api/chat/conversations/{conversation_id}/file-path
```

- [x] **Step 5: Esegui i test e verifica che passino**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_conversation_backup_api.py tests/contracts/ -v
..\.venv\Scripts\python.exe -m ruff check api/routes/chat/io.py
```
Atteso: PASS (il ratchet conferma che `/backup` è tipizzato e che le 2 voci rimosse non sono più violazioni).

- [x] **Step 6: Commit**

```powershell
git add backend/api/routes/chat/io.py backend/tests/test_conversation_backup_api.py backend/tests/contracts/response_model_baseline.txt
git commit -m "feat(persistence): explicit POST /chat/conversations/backup; typed export; drop file-path endpoint" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

> **Esito (2026-06-12):** COMPLETATO — commit `aaad49b`. Spec review ✅ (route ordering verificato, baseline −2 esatta). Quality review «With fixes»: il test di rimozione file-path era vacuo (404 anche sul vecchio endpoint per conversazione inesistente — la predizione «200/503» dello Step 2 era errata, il test app costruisce ancora il file manager fino al Task 5). Fix in `36bc877`: assert sul body `{"detail": "Not Found"}` (404 di route, discriminante), `dest_dir is not None` (rifiuta stringa vuota), `logger.warning` prima del raise OSError, blank line residua. Gate: 3/3 API test + 85 contracts, ruff pulito. Nota per Task 7: mostrare `exported` nella UI (un subset con id inesistenti risponde 200 con exported=0).

---

### Task 3: conversations.py — rimozione mirror + response_model + lista {items,total}

**Files:**
- Modify: `backend/api/routes/chat/conversations.py`
- Modify: `backend/api/routes/chat/io.py` (import endpoint → `response_model`)
- Modify: `backend/tests/contracts/response_model_baseline.txt`
- Modify: `backend/tests/test_app.py`, `backend/tests/test_concurrent.py` (shape lista)

- [x] **Step 1: Modelli (sostituiscono `BranchConversationResponse`)**

In `conversations.py`, sostituisci il blocco modelli (righe 43-72) con (mantieni `BranchConversationRequest` IDENTICO):

```python
class ConversationSummaryResponse(BaseModel):
    """Summary of a conversation (list items, create/import/branch responses)."""

    id: str
    title: str | None
    created_at: str
    updated_at: str
    message_count: int


class ConversationListResponse(BaseModel):
    """List-endpoint envelope (convention: ``{items, total}``, spec §6)."""

    items: list[ConversationSummaryResponse]
    total: int


class TitleUpdateResponse(BaseModel):
    """Response of the title-update endpoint."""

    id: str
    title: str
    updated_at: str


class SwitchVersionResponse(BaseModel):
    """Response of the switch-version endpoint."""

    id: str
    active_versions: dict[str, int]
    updated_at: str


class DeleteConversationResponse(BaseModel):
    """Response of the single-conversation delete endpoint."""

    status: str


class DeleteAllConversationsResponse(BaseModel):
    """Response of the delete-all endpoint."""

    status: str
```

`BranchConversationResponse` viene ELIMINATO; nel corpo di `branch_conversation` (riga 862) sostituisci `return BranchConversationResponse(` con `return ConversationSummaryResponse(` e aggiorna il `response_model`/annotazione di ritorno dell'endpoint branch di conseguenza.

- [x] **Step 2: Applica i `response_model` e la shape lista**

- `GET /chat/conversations` (riga 80): decoratore → `@router.get("/chat/conversations", response_model=ConversationListResponse)`; il `return [ ... ]` (righe 101-110) diventa:

```python
        items = [
            {
                "id": str(conv.id),
                "title": conv.title,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "message_count": msg_count,
            }
            for conv, msg_count in rows
        ]
        return {"items": items, "total": len(items)}
```

e l'annotazione della firma diventa `-> dict[str, Any]`.

- `POST .../title` → `response_model=TitleUpdateResponse`.
- `POST .../switch-version` → `response_model=SwitchVersionResponse`.
- `POST /chat/conversations` (create) → `response_model=ConversationSummaryResponse`.
- `DELETE /chat/conversations/{conversation_id}` → `response_model=DeleteConversationResponse`.
- `DELETE /chat/conversations` (all) → `response_model=DeleteAllConversationsResponse`; il return (riga 442) diventa `return {"status": "deleted"}` e il log a riga 441 diventa `logger.info("Deleted all conversations")`.
- In `io.py`: `POST /chat/conversations/import` → `response_model=ConversationSummaryResponse` con `from .conversations import ConversationSummaryResponse`.

- [x] **Step 3: Rimuovi ogni traccia del mirror da `conversations.py`**

- Import: elimina riga 27 (`from backend.services.conversation_file_manager import ConversationFileManager`) e `_sync_conversation_to_file` dall'import `._helpers` (riga 34).
- Elimina i 4 blocchi sync (con il commento `# Sync to JSON file.` dove presente):
  - righe ~600-604 (title), ~683-686 (switch-version), ~857-860 (branch), ~961-964 (create).
- Elimina il blocco delete-all (righe ~425-429) e la variabile `deleted_files`:

```python
    # Remove all JSON conversation files.
    file_manager: ConversationFileManager | None = ctx.conversation_file_manager
    deleted_files = 0
    if file_manager:
        deleted_files = await file_manager.delete_all()
```

- Elimina il blocco delete singola (righe ~536-541):

```python
        # Remove JSON conversation file.
        file_manager: ConversationFileManager | None = (
            ctx.conversation_file_manager
        )
        if file_manager:
            await file_manager.delete(str(conversation_id))
```

- **Rename da review Task 1:** in `backend/services/conversation_export.py` rinomina `_attachment_url` → `attachment_url` (funzione ora consumata cross-package: il prefisso privato non è più onesto); in `conversations.py` sostituisci l'import da `._shared` con `from backend.services.conversation_export import attachment_url` e aggiorna i call-site; in `_shared.py` elimina la riga di re-export `from backend.services.conversation_export import _attachment_url  # noqa: F401`. Verifica con `git grep -n "_attachment_url"` che non restino riferimenti.

- [x] **Step 4: Baseline ratchet — elimina le righe ora tipizzate**

Da `response_model_baseline.txt` elimina:

```
DELETE /api/chat/conversations
DELETE /api/chat/conversations/{conversation_id}
GET /api/chat/conversations
POST /api/chat/conversations
POST /api/chat/conversations/import
POST /api/chat/conversations/{conversation_id}/switch-version
POST /api/chat/conversations/{conversation_id}/title
```

- [x] **Step 5: Aggiorna i test che leggono la lista**

In `tests/test_app.py`, `test_conversations_list_empty` (righe 32-37) diventa:

```python
async def test_conversations_list_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/chat/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
```

In `tests/test_concurrent.py` (righe ~255-319): ogni `resp.json()` di `GET /api/chat/conversations` ora è `{"items": [...], "total": n}` — apri il file e correggi TUTTI gli usi (`data["items"]` al posto di `data`); non lasciare asserzioni sulla vecchia shape. Se asserisce su `deleted_files` del delete-all, aggiorna a `{"status": "deleted"}`.

- [x] **Step 6: Esegui i test**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/contracts/ tests/test_app.py tests/test_concurrent.py tests/test_conversation_backup_api.py -v
..\.venv\Scripts\python.exe -m ruff check api/routes/chat/conversations.py api/routes/chat/io.py
```
Atteso: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/api/routes/chat/conversations.py backend/api/routes/chat/io.py backend/tests/contracts/response_model_baseline.txt backend/tests/test_app.py backend/tests/test_concurrent.py
git commit -m "refactor(persistence): conversations routes - drop JSON mirror, typed responses, {items,total} list" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

> **Esito (2026-06-12):** COMPLETATO — commit `895eb6e` (incluso rename `attachment_url`). Spec review ✅ (tutti i return path verificati contro i modelli; baseline esatta, il GET dettaglio resta in baseline). Quality review «Ready to merge: Yes», zero Critical/Important; verificato che `deleted_files` non aveva consumatori runtime. Fix minor in `f17fc5f`: validazione tipo `title` nell'import (prima: 500 post-commit su title non-stringa), rimosso F401 pre-esistente in test_concurrent. Minor lasciati a verbale: stile di ritorno misto (branch ritorna istanza, gli altri dict) e posizionamento di ConversationSummaryResponse in un modulo route (valutare un home neutrale se compare un terzo consumatore). Promemoria: contratti generati STALE fino al Task 7 (check-contracts rosso mid-branch, atteso).

---

### Task 4: Turn engine e route WS — rimozione completa di `sync_fn`

**Files:**
- Modify: `backend/services/turn/tool_loop.py`, `backend/services/turn/direct_executor.py`, `backend/services/turn/factory.py`
- Modify: `backend/api/routes/chat/ws.py`, `backend/api/routes/chat/_persist.py`, `backend/api/routes/chat/_assembly.py`, `backend/api/routes/chat/_helpers.py`
- Modify: `backend/tests/test_confirmation_toggle.py`, `backend/tests/test_tool_loop.py`, `backend/tests/test_turn_lifecycle_events.py`

- [x] **Step 1: `tool_loop.py`**

- Elimina l'alias e il commento (righe 42-43): `SyncFn = Callable[..., Coroutine[Any, Any, None]]` (poi verifica con ruff se `Callable`/`Coroutine` restano usati nel file; se no, rimuovili dall'import).
- `run_tool_loop`: rimuovi il parametro `sync_fn: SyncFn | None,` (riga 94) e la riga di docstring «sync_fn: Async callback…» (126).
- Rimuovi i 4 blocchi:

```python
        if ctx.conversation_file_manager and sync_fn:
            await sync_fn(session, conv_id, ctx.conversation_file_manager)
```

(righe ~447-448 e ~700-701, col commento `# 5. Sync conversation to JSON file.` a 699 — rinumera il commento successivo `# 6.` in `# 5.` solo se banale, altrimenti lascia la numerazione);

il blocco dentro `except WebSocketDisconnect` (righe ~672-677) diventa una send semplice — da:

```python
            try:
                await sink.send(ws_payload)
            except WebSocketDisconnect:
                if ctx.conversation_file_manager and sync_fn:
                    await sync_fn(session, conv_id, ctx.conversation_file_manager)
                raise
```

a:

```python
            await sink.send(ws_payload)
```

e il blocco in `_persist_client_tool_result` (righe ~1295-1296).
- `_persist_gate_outcome` (riga 1058): rimuovi il parametro `sync_fn: SyncFn | None,` e l'argomento `sync_fn=sync_fn,` nella chiamata (riga ~439) e nel forward a `_persist_client_tool_result` (riga ~1095).
- `_persist_client_tool_result` (riga 1251): rimuovi il parametro `sync_fn: SyncFn | None,`.
- Verifica che `WebSocketDisconnect` resti usato altrove nel file (sì, nel pump); se ruff lo segnala orfano, rimuovi l'import.

- [x] **Step 2: `direct_executor.py` e `factory.py`**

`direct_executor.py`: elimina alias+commento (righe 46-49), il param `sync_fn` dal costruttore (67) e `self._sync_fn = sync_fn` (71), la riga `sync_fn=self._sync_fn,` nella chiamata a `run_tool_loop` (251), le righe di docstring che lo citano (58-60). Verifica import `Callable`/`Coroutine`.

`factory.py`: elimina alias (28), param `sync_fn` (34) e relativa docstring (41-42), e la chiamata diventa `direct = DirectTurnExecutor(ctx, llm)` (49). Elimina `from collections.abc import Callable, Coroutine` se orfano.

- [x] **Step 3: Route chat**

`ws.py`: elimina `from ._helpers import _sync_conversation_to_file` (riga 31); la creazione executor (162-164) diventa `executor = create_turn_executor(ctx, llm)`; elimina il blocco recovery (215-220):

```python
                        if ctx.conversation_file_manager:
                            with contextlib.suppress(Exception):
                                await _sync_conversation_to_file(
                                    session, conv_id,
                                    ctx.conversation_file_manager,
                                )
```

(il `await session.commit()` sopra RESTA).

`_persist.py`: rimuovi `_sync_conversation_to_file` dall'import (riga 29) e i 3 blocchi `if ctx.conversation_file_manager: await _sync_conversation_to_file(...)` alle righe ~162-165, ~241-244, ~384-387.

`_assembly.py`: rimuovi `_sync_conversation_to_file` dall'import (riga 57) e il blocco alle righe ~312-315.

`_helpers.py`: elimina DEL TUTTO la funzione `_sync_conversation_to_file` e gli import ora orfani (`ConversationFileManager` da services, e `build_conversation_export` se non usato da altro nel modulo). Aggiorna la docstring di modulo (riga 3-6) togliendo «DB archival»→il riferimento alla serializzazione JSON.

- [x] **Step 4: Aggiorna i test del turn engine**

- `tests/test_confirmation_toggle.py`: elimina la riga 85 (`ctx.conversation_file_manager = None`) e TUTTI i kwarg `sync_fn=None` (righe ~167, 189, 209, 239, 289, 331, 372).
- `tests/test_tool_loop.py`: elimina la riga 243 (`self.conversation_file_manager = None` nel fake ctx) e il kwarg `sync_fn=None` (riga ~290).
- `tests/test_turn_lifecycle_events.py`: elimina il kwarg `sync_fn=None` (riga ~160).

- [x] **Step 5: Esegui i test**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_tool_loop.py tests/test_confirmation_toggle.py tests/test_turn_lifecycle_events.py tests/test_interaction_channel.py tests/contracts/ -v
..\.venv\Scripts\python.exe -m ruff check services/turn/tool_loop.py services/turn/direct_executor.py services/turn/factory.py api/routes/chat/ws.py api/routes/chat/_persist.py api/routes/chat/_assembly.py api/routes/chat/_helpers.py
```
Atteso: PASS; ruff senza errori NUOVI.

- [x] **Step 6: Commit**

```powershell
git add backend/services/turn/ backend/api/routes/chat/ backend/tests/test_confirmation_toggle.py backend/tests/test_tool_loop.py backend/tests/test_turn_lifecycle_events.py
git commit -m "refactor(persistence): remove sync_fn JSON-mirror threading from the turn engine and chat routes" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

> **Esito (2026-06-12):** COMPLETATO — commit `3cbd583` (net −91 righe). Spec review ✅ (catena disconnect verificata: run_tool_loop raise → direct_executor cattura → finish_reason=disconnected → ws.py recovery, semantica identica; tutti i commit adiacenti intatti). Quality review «With fixes»: invariante verificato (le sync erano SEMPRE side-effect post-commit; lo stato transitorio pre-Task5 è benigno perché rebuild_from_files salta le conversazioni già nel DB). Fix in `3da4fa6`: 4 righe vuote residue nei test (1 W293 nuova) + docstring stale «sync to file» in _persist.py. Migliorie drive-by accettate: factory return type tipizzato, UP035 Callable. Gate: 120/120 + contracts, ruff senza errori nuovi, grep sync_fn=0.

---

### Task 5: Rimozione di `ConversationFileManager` (servizio, protocollo, ctx, lifespan)

**Files:**
- Delete: `backend/services/conversation_file_manager.py`
- Delete: `backend/tests/test_conversation_file_manager.py`, `backend/tests/test_conversation_migration.py`
- Modify: `backend/core/app.py`, `backend/core/context.py`, `backend/core/protocols.py`

- [x] **Step 1: `core/app.py`**

Elimina la riga 30 (`from backend.services.conversation_file_manager import ConversationFileManager`) e il blocco righe 214-226:

```python
    conversations_dir = PROJECT_ROOT / "data" / "conversations"
    ctx.conversation_file_manager = ConversationFileManager(conversations_dir)

    # Restore conversations from JSON files that are missing from the DB.
    if not testing:
        try:
            restored = await ctx.conversation_file_manager.rebuild_from_files(
                session_factory,
            )
            if restored:
                logger.info("Restored {} conversations from JSON files", restored)
        except Exception as exc:
            logger.error("Failed to rebuild conversations from files: {}", exc)
```

- [x] **Step 2: `core/context.py` e `core/protocols.py`**

`context.py`: elimina il campo `conversation_file_manager: ConversationFileManagerProtocol | None = None` (riga 59) e `ConversationFileManagerProtocol` dall'import (riga 19).

`protocols.py`: elimina il blocco `ConversationFileManagerProtocol` con la sua intestazione di sezione (righe 408-448). Verifica con ruff che `Path` resti usato da altri protocolli (se orfano, rimuovi l'import).

- [x] **Step 3: Elimina servizio e test del mirror**

```powershell
git rm backend/services/conversation_file_manager.py backend/tests/test_conversation_file_manager.py backend/tests/test_conversation_migration.py
```

- [x] **Step 4: Verifica che non resti alcun riferimento**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m ruff check core/app.py core/context.py core/protocols.py
git grep -n -i "conversation_file_manager\|ConversationFileManager\|_sync_conversation_to_file\|sync_fn" -- backend/
```
Atteso: ruff pulito (niente errori nuovi); il grep restituisce ZERO righe (eventuali hit residui vanno corretti ORA).

- [x] **Step 5: Esegui i test**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/contracts/ tests/test_app.py tests/test_conversation_export.py tests/test_conversation_backup_api.py -v
```
Atteso: PASS.

- [x] **Step 6: Commit**

```powershell
git add -A backend/
git commit -m "refactor(persistence)!: delete ConversationFileManager - SQLite is the single source of truth (spec 5.2)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

> **Esito (2026-06-12):** COMPLETATO — commit `dbe05d3` (−1222 righe, 3 file eliminati, 3 modificati). Spec review ✅ (lifespan integro, Path orfano rimosso correttamente, 9 errori ruff identici a base = zero nuovi). Quality review «Ready to merge: Yes», zero issue bloccanti. Segnalazioni assorbite nel Task 8: i file istruzione `.github/copilot-instructions.md` e `.github/agents/{backend,backend-coherence,test}.agent.md` citano ancora il modulo eliminato (4 edit da fare nel sweep docs); grep finale di fase repo-wide (`conversation_file\|data/conversations`), non solo backend/; nota utente sulla dir `data/conversations/` ormai inerte.

---

### Task 6: Plugin `conversation_backup` (tool agente) + test (TDD)

**Files:**
- Create: `backend/plugins/conversation_backup/__init__.py`, `backend/plugins/conversation_backup/plugin.py`
- Create: `backend/tests/test_conversation_backup_plugin.py`
- Modify: `config/default.yaml` (plugins.enabled)

- [ ] **Step 1: Scrivi il test che fallisce**

```python
"""AL\\CE — Tests for the conversation_backup plugin tool."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.plugin_models import ExecutionContext
from backend.db.models import Conversation, Message
from backend.plugins.conversation_backup.plugin import ConversationBackupPlugin


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
async def plugin(session_factory):
    p = ConversationBackupPlugin()
    # Duck-typed ctx: il plugin usa solo ctx.db (session factory).
    await p.initialize(SimpleNamespace(db=session_factory))  # type: ignore[arg-type]
    return p


def _exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="s", conversation_id="c", execution_id="e",
    )


async def test_tool_definition_registered(plugin) -> None:
    tools = plugin.get_tools()
    assert [t.name for t in tools] == ["backup_conversations"]
    assert tools[0].risk_level == "safe"


async def test_backup_all_writes_files(
    plugin, session_factory, tmp_path, monkeypatch,
) -> None:
    import backend.plugins.conversation_backup.plugin as plugin_mod

    monkeypatch.setattr(plugin_mod, "PROJECT_ROOT", tmp_path)

    async with session_factory() as session:
        conv = Conversation(title="T")
        session.add(conv)
        await session.flush()
        session.add(Message(conversation_id=conv.id, role="user", content="hi"))
        await session.commit()
        conv_id = conv.id

    result = await plugin.execute_tool("backup_conversations", {}, _exec_ctx())

    assert result.success
    assert isinstance(result.content, dict)
    assert result.content["exported"] == 1
    out_dir = tmp_path / "data" / "backups"
    matches = list(out_dir.rglob(f"{conv_id}.json"))
    assert len(matches) == 1


async def test_backup_invalid_conversation_id(plugin) -> None:
    result = await plugin.execute_tool(
        "backup_conversations", {"conversation_id": "not-a-uuid"}, _exec_ctx(),
    )
    assert not result.success
```

- [ ] **Step 2: Esegui il test e verifica che fallisca**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_conversation_backup_plugin.py -v
```
Atteso: ERROR `ModuleNotFoundError: No module named 'backend.plugins.conversation_backup'`.

- [ ] **Step 3: Crea il plugin**

`backend/plugins/conversation_backup/__init__.py`:

```python
"""AL\\CE — Conversation backup plugin package.

Importing this module registers :class:`ConversationBackupPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.conversation_backup.plugin import ConversationBackupPlugin  # noqa: F401

PLUGIN_REGISTRY["conversation_backup"] = ConversationBackupPlugin
```

`backend/plugins/conversation_backup/plugin.py`:

```python
"""AL\\CE — Conversation backup plugin.

Exposes the ``backup_conversations`` tool: the agent-facing entry point of
the explicit conversation export command (spec §5.2). Delegates to the same
``conversation_export`` service used by the REST backup endpoint — one
capability, one implementation.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.core.config import PROJECT_ROOT
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.services.conversation_export import export_conversations_to_dir


class ConversationBackupPlugin(BasePlugin):
    """Explicit JSON backup of conversations (app-owned backups directory)."""

    plugin_name: str = "conversation_backup"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Export conversations as JSON backup files on explicit request."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 20

    def get_tools(self) -> list[ToolDefinition]:
        """Return the backup tool definition."""
        return [
            ToolDefinition(
                name="backup_conversations",
                description=(
                    "Export conversations as JSON backup files into the "
                    "app-managed backups folder (data/backups). Pass "
                    "conversation_id to export a single conversation; omit "
                    "it to export all conversations. Returns the number of "
                    "exported conversations and the destination path."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": (
                                "UUID of a single conversation to export. "
                                "Omit to export all conversations."
                            ),
                        },
                    },
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=60000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Run the backup into ``data/backups/conversations-<timestamp>/``."""
        if tool_name != "backup_conversations":
            return ToolResult.error(f"Unknown tool: {tool_name}")

        conversation_ids: list[uuid.UUID] | None = None
        raw_id = args.get("conversation_id")
        if raw_id:
            try:
                conversation_ids = [uuid.UUID(str(raw_id))]
            except ValueError:
                return ToolResult.error(f"Invalid conversation_id: {raw_id!r}")

        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        dest = PROJECT_ROOT / "data" / "backups" / f"conversations-{stamp}"

        start = time.perf_counter()
        try:
            exported = await export_conversations_to_dir(
                self.ctx.db, dest, conversation_ids,
            )
        except OSError as exc:
            return ToolResult.error(f"Backup failed: {exc}")

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content={"exported": exported, "path": str(dest)},
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )
```

- [ ] **Step 4: Abilita il plugin in config**

In `config/default.yaml`, nella lista `plugins.enabled` (riga ~74), aggiungi dopo `- clipboard`:

```yaml
    - conversation_backup   # explicit JSON backup of conversations (spec §5.2)
```

- [ ] **Step 5: Esegui i test e verifica che passino**

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_conversation_backup_plugin.py -v
..\.venv\Scripts\python.exe -m ruff check plugins/conversation_backup/
..\.venv\Scripts\python.exe -m mypy plugins/conversation_backup/
```
Atteso: PASS, ruff/mypy puliti (file nuovi).

- [ ] **Step 6: Commit**

```powershell
git add backend/plugins/conversation_backup/ backend/tests/test_conversation_backup_plugin.py config/default.yaml
git commit -m "feat(persistence): conversation_backup plugin - agent tool for explicit JSON backup" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Contratti rigenerati + frontend (tipi, API client, UI export/backup)

**Files:**
- Regenerate: `backend/api/openapi.json` (o percorso gestito da `scripts/gen-contracts.ps1`), `frontend/src/renderer/src/types/generated/*`
- Modify: `frontend/src/renderer/src/types/chat.ts`, `frontend/src/renderer/src/services/api.ts`, `frontend/src/renderer/src/stores/chat.ts`
- Modify: `frontend/src/renderer/src/components/sidebar/AppSidebar.vue`, `frontend/src/renderer/src/components/sidebar/ConversationList.vue`
- Modify (se serve): `frontend/src/renderer/src/stores/chat.spec.ts` (mock lista)

- [ ] **Step 1: Rigenera i contratti**

```powershell
.\scripts\gen-contracts.ps1
```
Atteso: exit 0; in `types/generated/api.d.ts` compaiono `ConversationExport`, `ConversationSummaryResponse`, `ConversationListResponse`, `BackupRequest`, `BackupResult` e sparisce l'operation `file-path`.

- [ ] **Step 2: `types/chat.ts` — i tipi REST del dominio diventano re-export generati**

Sostituisci le interface hand-written con re-export (`ApiSchema` da `./generated`); aggiungi in testa al file (o estendi l'import esistente):

```ts
import type { ApiSchema } from './generated'
```

- `ConversationSummary` (righe ~67-73) → `export type ConversationSummary = ApiSchema<'ConversationSummaryResponse'>`
- Aggiungi `export type ConversationListResponse = ApiSchema<'ConversationListResponse'>`
- `ConversationExport` (righe ~288-296) → `export type ConversationExport = ApiSchema<'ConversationExport'>`
- `SwitchVersionResponse` (righe ~298-303) → `export type SwitchVersionResponse = ApiSchema<'SwitchVersionResponse'>`
- `BranchConversationResponse` (righe ~311-318) → `export type BranchConversationResponse = ApiSchema<'ConversationSummaryResponse'>`
- `DeleteConversationResponse` (righe ~105-107) → `export type DeleteConversationResponse = ApiSchema<'DeleteConversationResponse'>`
- `DeleteAllConversationsResponse` (righe ~110-112, addio `deleted_files`) → `export type DeleteAllConversationsResponse = ApiSchema<'DeleteAllConversationsResponse'>`
- Aggiungi `export type BackupResult = ApiSchema<'BackupResult'>`

NON toccare `ChatMessage`/`ConversationDetail` (il GET dettaglio resta hand-typed, vedi Backlog). `BranchConversationRequest` resta com'è.

- [ ] **Step 3: `services/api.ts`**

- `getConversations` diventa:

```ts
  /** List all conversations (most recent first). */
  getConversations: (): Promise<ConversationListResponse> =>
    request<ConversationListResponse>('/chat/conversations'),
```

(aggiungi `ConversationListResponse` e `BackupResult` all'import dei tipi, riga ~14).
- ELIMINA `getConversationFilePath` (righe ~274-276).
- Aggiungi accanto a `exportConversation`:

```ts
  /** Export conversations as JSON files to a directory (explicit backup). */
  backupConversations: (destDir?: string, conversationIds?: string[]): Promise<BackupResult> =>
    request<BackupResult>('/chat/conversations/backup', {
      method: 'POST',
      body: JSON.stringify({
        dest_dir: destDir ?? null,
        conversation_ids: conversationIds ?? null
      })
    }),
```

- [ ] **Step 4: `stores/chat.ts`**

In `loadConversations` (riga ~218-219):

```ts
  async function loadConversations(): Promise<void> {
    const remote = (await api.getConversations()).items
```

(il resto della funzione resta identico — verifica che `remote` sia usato come array). Le action `exportConversation`/`importConversation` restano invariate.

- [ ] **Step 5: UI — sostituisci «Apri nel file manager» con «Esporta» + backup totale**

`ConversationList.vue`:
- nelle emit (righe 26-33): `'open-file': [id: string]` → `export: [id: string]`; aggiungi `'backup-all': []`.
- bottone per-conversazione (righe 246-249): `aria-label="Esporta conversazione"`, `title="Esporta backup JSON"`, `@click="emit('export', conv.id)"` (icona `folder` invariata).
- nell'header actions (dopo il bottone «Nuova chat», righe 203-205) aggiungi:

```html
        <button v-if="conversations.length > 0" class="conv-list__header-btn" aria-label="Esporta tutte le conversazioni"
          title="Backup di tutte le conversazioni" @click="emit('backup-all')">
          <AppIcon name="folder" :size="11" />
        </button>
```

`AppSidebar.vue`:
- sostituisci `onOpenFile` (righe 211-219) con:

```ts
/** Export a single conversation as JSON into a user-chosen directory. */
async function onExportConversation(id: string): Promise<void> {
  try {
    const dir = await window.electron.fileOps.selectDirectory()
    if (!dir) return
    const res = await api.backupConversations(dir, [id])
    window.electron.fileOps.showInFolder(`${res.path}/${id}.json`)
  } catch (err) {
    console.error(`[AppSidebar] Failed to export conversation ${id}:`, err)
  }
}

/** Backup ALL conversations as JSON files into a user-chosen directory. */
async function onBackupAll(): Promise<void> {
  try {
    const dir = await window.electron.fileOps.selectDirectory()
    if (!dir) return
    const res = await api.backupConversations(dir)
    window.electron.fileOps.showInFolder(res.path)
  } catch (err) {
    console.error('[AppSidebar] Failed to backup conversations:', err)
  }
}
```

- nel template (riga ~298): `@open-file="onOpenFile"` → `@export="onExportConversation" @backup-all="onBackupAll"`.

- [ ] **Step 6: Typecheck, lint scoped, vitest**

```powershell
cd frontend
npm run typecheck
npx eslint src/renderer/src/types/chat.ts src/renderer/src/services/api.ts src/renderer/src/stores/chat.ts src/renderer/src/components/sidebar/AppSidebar.vue src/renderer/src/components/sidebar/ConversationList.vue
npm run test
```
Atteso: typecheck exit 0; eslint senza ERRORI nuovi (warnings prettier pre-esistenti tollerati); vitest verde — se `stores/chat.spec.ts` mocka `api.getConversations`, aggiorna il mock a `{ items: [...], total: n }`.

- [ ] **Step 7: check-contracts (DOPO il commit) e commit**

```powershell
git add backend/api/ frontend/src/renderer/src/types/ frontend/src/renderer/src/services/api.ts frontend/src/renderer/src/stores/chat.ts frontend/src/renderer/src/components/sidebar/ scripts/
git commit -m "feat(persistence): FE export/backup UI on generated contracts; drop file-path; {items,total} list" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
.\scripts\check-contracts.ps1
```
Atteso: check-contracts exit 0 (artefatti freschi). Se fallisce: rigenera, `git add` + `git commit --amend` NO — fai un commit di fixup separato.

---

### Task 8: Gate finali di fase + documentazione

**Files:**
- Modify: `CLAUDE.md` (riga sul mirror JSON), `docs/superpowers/plans/2026-06-11-fase2-persistenza.md` (tick + esiti)

- [ ] **Step 1: Gate backend completi (mirati, suite intera impraticabile)**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/contracts/ tests/test_conversation_export.py tests/test_conversation_backup_api.py tests/test_conversation_backup_plugin.py tests/test_app.py tests/test_concurrent.py tests/test_tool_loop.py tests/test_confirmation_toggle.py tests/test_turn_lifecycle_events.py tests/test_interaction_channel.py -v
```
Atteso: tutto PASS.

- [ ] **Step 2: Gate frontend**

```powershell
cd frontend; npm run typecheck; npm run test
```
Atteso: exit 0 entrambi.

- [ ] **Step 3: Grep finale anti-residui**

```powershell
git grep -n -i "conversation_file_manager\|ConversationFileManager\|rebuild_from_files\|getConversationFilePath\|file-path" -- backend/ frontend/src/
```
Atteso: ZERO hit (esclusi i file generati che citano… nulla: anche i generati devono essere puliti dopo la rigenerazione).

- [ ] **Step 4: Aggiorna CLAUDE.md**

Nella sezione «Data & external services», sostituisci la frase «Conversations are also mirrored to JSON in `data/conversations/` and rebuilt into the DB on startup.» con: «SQLite is the single source of truth for conversations; JSON export/backup is explicit only (`POST /api/chat/conversations/backup`, tool `backup_conversations`, sidebar UI).»

Inoltre (da review Task 5): aggiorna i file istruzione che inventariano il modulo eliminato — `.github/copilot-instructions.md` (riga ~17), `.github/agents/backend.agent.md` (~22), `.github/agents/backend-coherence.agent.md` (~22), `.github/agents/test.agent.md` (~43, elenca i 2 file di test eliminati). Il grep dello Step 3 va esteso a TUTTO il repo (non solo backend/ e frontend/src/), esclusi docs/superpowers e i piani scratch di root (non autoritativi).

- [ ] **Step 5: Verifica end-to-end ad app avviata (criterio di uscita 3)**

Avvia il dev stack (`.\scripts\start-dev.ps1` o backend+frontend separati), poi: crea/usa una conversazione → sidebar → «Esporta backup JSON» su una conversazione → scegli cartella → verifica che il file `{id}.json` venga creato e rivelato in Explorer; poi «Backup di tutte le conversazioni». Verifica che `data/conversations/` NON venga ricreata. Se l'avvio non è possibile nella sessione, lascia il criterio NON spuntato e annotalo nel piano (come da prassi 1b).

- [ ] **Step 6: Commit finale + tick del piano**

```powershell
git add CLAUDE.md docs/superpowers/plans/2026-06-11-fase2-persistenza.md
git commit -m "docs: fase2 persistenza - CLAUDE.md single-source-of-truth note; plan ticks" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Criteri di uscita della fase (spec §9)

- [ ] Test mirati verdi (contracts + persistenza + turn engine)
- [ ] `npm run typecheck` exit 0; vitest verde; `check-contracts.ps1` verde
- [ ] App avviabile; export/backup end-to-end funzionante; nessuna ricreazione di `data/conversations/`
- [ ] Ratchet REST: −9 voci baseline (dominio conversations, resta solo `GET /{id}`)

## Backlog (fuori scope, da riportare nell'handoff)

1. `GET /api/chat/conversations/{conversation_id}` (dettaglio) resta in baseline: il modello (messages + context_usage) è pesante — tipizzarlo in Fase 6 (frontend) quando si rifà il client per dominio.
2. La cartella legacy `data/conversations/` con i vecchi mirror resta su disco (dati azzerabili per decisione): nessuna pulizia automatica; eventualmente nota utente.
3. `POST /chat/conversations/import` accetta ancora body non-Pydantic (validazione a mano): convertire la request a modello quando si tocca di nuovo il dominio.
4. Ereditati da 1a/1b: `AgentTier` duplicato FE, calendar senza `calendar.changed`, canale voice hand-typed, narrowing `as` in `stores/services.ts`.
5. (review Task 1) `build_conversation_export` costruisce un dict a mano che deve rispecchiare `ConversationExport`: quando il filo `_sync_conversation_to_file` sparisce (post-Task 4), valutare la costruzione VIA modello (`ConversationExport(...).model_dump()`) così anche i file di backup (che non passano da `response_model`) sono garantiti dallo schema.
