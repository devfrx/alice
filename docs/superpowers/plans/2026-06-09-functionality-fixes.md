# Functionality-fixes batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six root-cause defects/gaps in ALICE/Omnia — LM-Studio hot-path latency, ignored scope + ignored confirmations, silently-degrading RAG, flaky conversation switching, whiteboard cross-conversation leakage, and single-question `ask_user` — each at its native root cause.

**Architecture:** Backend = Python 3.11+/FastAPI, plugin + DI (`AppContext`), turn engine in `services/turn/`. Frontend = Electron + Vue 3 `<script setup>` + Pinia. Contract consistency across WS/REST/TS/store/DB is mandatory (CLAUDE.md). TDD where the repo supports it: pytest (backend), vitest (frontend stores/utils). `.vue` components are not unit-tested → manual verification.

**Tech Stack:** FastAPI, httpx, SQLModel/aiosqlite, Qdrant (embedded), fastembed, pytest/pytest-asyncio; Vue 3, Pinia, vitest.

**Source spec:** `docs/superpowers/specs/2026-06-09-functionality-fixes-design.md`

**Approved decisions:** hard-sandbox scope · tier-authoritative confirmations · auto-repair-then-gate RAG · sequential ask_user wizard. Boundary decisions recorded in the spec (MCP-external tools, voice/lite confirmations, lossy collection recreate).

**Group order (independent task-groups):** 0 (cross-cutting) → A (#1) → C (#3) → B (#2) → D (#4) → E (#5) → F (#6). B/D/E/F are independent and may be parallelized by the orchestrator.

**Commit convention:** end every commit body with
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure (created / modified)

**Group 0 — context-window cache (cross-cutting)**
- Modify: `backend/services/llm_service.py` (add non-blocking cached window + bg refresh + invalidation)
- Modify: `backend/api/routes/chat/_assembly.py` (use the non-blocking getter)
- Modify: `backend/api/routes/chat/conversations.py` (use the non-blocking getter)
- Modify: `backend/services/lmstudio_service.py` (notify on cache invalidation)
- Test: `backend/tests/test_context_window_cache.py` (new)

**Group A — #1 frontend polling back-off**
- Modify: `frontend/src/renderer/src/stores/services.ts` (back-off polling on down)
- Test: `frontend/src/renderer/src/stores/services.spec.ts` (new)

**Group C — #3 RAG readiness gate + auto-repair**
- Create: `backend/services/rag_readiness.py`
- Modify: `backend/services/qdrant_service.py` (stale-lock repair, dim/count probes)
- Modify: `backend/core/app.py` (run gate in lifespan, gate memory + tool_rag)
- Modify: `backend/api/routes/chat/_assembly.py` (skip memory/tool-RAG when disabled)
- Create: `backend/api/routes/knowledge.py` (`GET /api/knowledge/readiness`) + register
- Test: `backend/tests/test_rag_readiness.py` (new)

**Group B — #2 scope hard-sandbox + tier-authoritative confirmations**
- Modify: `backend/core/plugin_models.py` (add `workspace_root` to `ExecutionContext`)
- Modify: `backend/services/permission_service.py` (confine `process_exec`; effective path)
- Modify: `backend/services/scope_service.py` (no-scope → per-conversation sandbox root)
- Modify: `backend/services/turn/tool_loop.py` (populate `workspace_root`)
- Modify: `backend/services/turn/pipeline.py` (`ConfirmationMiddleware` tier-authoritative)
- Modify: `backend/plugins/file_search/plugin.py`, `backend/plugins/pc_automation/*` (cwd = workspace_root)
- Rewrite: `backend/tests/test_confirmation_toggle.py` (new contract)
- Test: `backend/tests/test_scope_sandbox_fallback.py` (new), extend `test_permission_scope_confinement.py`

**Group D — #4 conversation-switch reliability**
- Modify: `frontend/src/renderer/src/stores/chat.ts` (generation token + abort + loading flag)
- Modify: `frontend/src/renderer/src/services/api.ts` (`getConversation(id, signal?)`)
- Test: `frontend/src/renderer/src/stores/chat.spec.ts` (extend)

**Group E — #5 whiteboard conversation-scoping**
- Modify: `backend/api/routes/whiteboards.py` (`count(conversation_id=...)`)
- Modify: `frontend/src/renderer/src/stores/whiteboard.ts` (`reset()`)
- Modify: `frontend/src/renderer/src/components/canvas/modules/WhiteboardModule.vue` (pass id + watch)
- Test: `backend/tests/test_whiteboard_route_scope.py` (new), `frontend/.../stores/whiteboard.spec.ts` (new)

**Group F — #6 ask_user sequential wizard**
- Modify: `backend/plugins/agent/plugin.py` (schema → `questions[]`)
- Modify: `backend/services/turn/pipeline.py` (`_execute_user_interaction` multi-question)
- Modify: `frontend/src/renderer/src/types/chat.ts` (request/response/`AskUserRequest`)
- Rewrite: `frontend/src/renderer/src/components/chat/AskUserPrompt.vue` (Next/Back wizard)
- Modify: `frontend/src/renderer/src/composables/useChat.ts` (handlers), `stores/chat.ts` (pending shape)
- Test: `backend/tests/test_ask_user_multi.py` (new), `frontend/.../stores/chat.spec.ts` (extend)

---

## Group 0 — Cross-cutting: non-blocking context-window cache

Root cause: `await llm.get_active_context_window(ctx.lmstudio_manager)` runs on turn-start
([_assembly.py:431](../../../backend/api/routes/chat/_assembly.py)) and conversation-open
([conversations.py:160](../../../backend/api/routes/chat/conversations.py)), blocking on a
live LM-Studio round-trip for a value that only changes on model switch.

### Task 1: LLMService non-blocking cached window + background refresh

**Files:**
- Modify: `backend/services/llm_service.py` (near `get_active_context_window`, ~1578-1607; `__init__`; `close`)
- Test: `backend/tests/test_context_window_cache.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the non-blocking context-window cache in LLMService."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.llm_service import LLMService


def _llm() -> LLMService:
    cfg = MagicMock()
    cfg.connect_timeout = 1.0
    cfg.timeout = 10.0
    # Avoid real network client construction details by patching after init if needed.
    svc = LLMService.__new__(LLMService)
    # Initialise only the cache fields the methods under test touch.
    svc._ctx_window_cache = None
    svc._ctx_window_expires = 0.0
    svc._ctx_window_ttl = 300.0
    svc._default_ctx_window = 32768
    svc._ctx_window_refreshing = False
    return svc


def _manager(window: int) -> MagicMock:
    mgr = MagicMock()
    mgr.list_models = AsyncMock(return_value={
        "models": [{
            "type": "llm",
            "loaded_instances": [{"config": {"context_length": window}}],
        }],
    })
    return mgr


@pytest.mark.asyncio
async def test_cached_getter_returns_default_without_blocking_then_warms():
    svc = _llm()
    mgr = _manager(8192)
    # First call: no cache yet → returns default immediately, schedules refresh.
    first = svc.get_cached_context_window(mgr)
    assert first == 32768
    # Let the scheduled background refresh run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # Cache is now warm with the real value.
    assert svc.get_cached_context_window(mgr) == 8192


@pytest.mark.asyncio
async def test_cached_getter_never_raises_when_manager_down():
    svc = _llm()
    mgr = MagicMock()
    mgr.list_models = AsyncMock(side_effect=RuntimeError("ConnectError"))
    assert svc.get_cached_context_window(mgr) == 32768
    await asyncio.sleep(0)
    # Still returns a usable value; never propagates the error.
    assert svc.get_cached_context_window(mgr) == 32768


@pytest.mark.asyncio
async def test_invalidate_forces_refresh():
    svc = _llm()
    mgr = _manager(4096)
    await svc._refresh_context_window(mgr)
    assert svc.get_cached_context_window(mgr) == 4096
    svc.invalidate_context_window_cache()
    mgr.list_models = AsyncMock(return_value={
        "models": [{"type": "llm",
                    "loaded_instances": [{"config": {"context_length": 16384}}]}],
    })
    await svc._refresh_context_window(mgr)
    assert svc.get_cached_context_window(mgr) == 16384
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; pytest tests/test_context_window_cache.py -v`
Expected: FAIL — `LLMService` has no `get_cached_context_window` / `_refresh_context_window` / `invalidate_context_window_cache`.

- [ ] **Step 3: Implement the cache in `LLMService`**

In `__init__`, add cache fields (near the other caches):

```python
        self._ctx_window_cache: int | None = None
        self._ctx_window_expires: float = 0.0
        self._ctx_window_ttl: float = 300.0
        self._default_ctx_window: int = 32768
        self._ctx_window_refreshing: bool = False
```

Replace `get_active_context_window` body and add the new methods (keep the async one for
back-compat callers, but make it delegate to the refresh + return cache):

```python
    def get_cached_context_window(self, lmstudio_manager: Any = None) -> int:
        """Return the active model's context window WITHOUT blocking.

        Serves the cached value (or the default) immediately. When the cache is
        empty or stale it schedules a background refresh so the *next* call is
        warm — the hot path (turn-start, conversation-open) never awaits LM Studio.

        Args:
            lmstudio_manager: Optional LMStudioManager used by the background
                refresh to query loaded-model metadata.

        Returns:
            Context window size in tokens (cached, last-known, or the default).
        """
        import time
        now = time.monotonic()
        if self._ctx_window_cache is not None and now < self._ctx_window_expires:
            return self._ctx_window_cache
        if lmstudio_manager is not None and not self._ctx_window_refreshing:
            self._ctx_window_refreshing = True
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._refresh_context_window(lmstudio_manager))
            except RuntimeError:
                # No running loop (sync test context) — drop the refresh flag.
                self._ctx_window_refreshing = False
        return (
            self._ctx_window_cache
            if self._ctx_window_cache is not None
            else self._default_ctx_window
        )

    async def _refresh_context_window(self, lmstudio_manager: Any = None) -> None:
        """Refresh the cached context window from LM Studio (never raises)."""
        import time
        value = self._ctx_window_cache
        try:
            if lmstudio_manager is not None:
                data = await lmstudio_manager.list_models()
                for model in data.get("models", []):
                    if model.get("type") == "embedding":
                        continue
                    instances = model.get("loaded_instances", [])
                    if instances:
                        ctx_len = instances[0].get("config", {}).get("context_length", 0)
                        if ctx_len > 0:
                            value = ctx_len
                            break
        except Exception as exc:
            logger.debug("Failed to refresh context window: {}", exc)
        finally:
            self._ctx_window_refreshing = False
        if value is None:
            value = self._default_ctx_window
        self._ctx_window_cache = value
        self._ctx_window_expires = time.monotonic() + self._ctx_window_ttl

    def invalidate_context_window_cache(self) -> None:
        """Drop the cached context window (call on model switch / config change)."""
        self._ctx_window_cache = None
        self._ctx_window_expires = 0.0

    async def get_active_context_window(self, lmstudio_manager: Any = None) -> int:
        """Back-compat async accessor: refresh if needed, then return the cache."""
        import time
        now = time.monotonic()
        if self._ctx_window_cache is None or now >= self._ctx_window_expires:
            await self._refresh_context_window(lmstudio_manager)
        return self.get_cached_context_window(lmstudio_manager)
```

(`asyncio` and `logger` are already imported in this module; `Any` is already imported.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; pytest tests/test_context_window_cache.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/llm_service.py backend/tests/test_context_window_cache.py
git commit -m "perf(llm): non-blocking cached context window with bg refresh + invalidation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2: Use the non-blocking getter on the hot paths + invalidate on model switch

**Files:**
- Modify: `backend/api/routes/chat/_assembly.py:~431`
- Modify: `backend/api/routes/chat/conversations.py:~160`
- Modify: `backend/services/lmstudio_service.py` (`invalidate_models_cache`, `load_model`/`unload_model`)

- [ ] **Step 1: Swap the awaited call for the sync cached getter (assembly)**

In `_assembly.py`, replace:
```python
    if ctx.context_manager is not None:
        context_window = await llm.get_active_context_window(
            ctx.lmstudio_manager,
        )
```
with:
```python
    if ctx.context_manager is not None:
        context_window = llm.get_cached_context_window(ctx.lmstudio_manager)
```

- [ ] **Step 2: Same swap in `conversations.py:~160`**

Replace the `await ctx.llm_service.get_active_context_window(...)` call used for the
context-info estimate with `ctx.llm_service.get_cached_context_window(ctx.lmstudio_manager)`
(drop the `await`).

- [ ] **Step 3: Invalidate the window cache when the model changes**

In `lmstudio_service.py`, find every place that calls `self.invalidate_models_cache()`
(model load/unload). Add an optional callback the manager fires there:

In `LMStudioManager.__init__` add:
```python
        self._on_models_changed: list[Callable[[], None]] = []
```
Add:
```python
    def add_models_changed_listener(self, cb: Callable[[], None]) -> None:
        """Register a callback fired whenever the loaded-model set changes."""
        self._on_models_changed.append(cb)
```
In `invalidate_models_cache`, after clearing the cache:
```python
        for cb in self._on_models_changed:
            try:
                cb()
            except Exception:  # never let a listener break model ops
                pass
```
(`Callable` import: add `from collections.abc import Callable` at the top.)

Then in `backend/core/app.py` lifespan, after both `llm_service` and `lmstudio_manager`
exist, wire:
```python
    ctx.lmstudio_manager.add_models_changed_listener(
        ctx.llm_service.invalidate_context_window_cache
    )
```
Also call `ctx.llm_service.invalidate_context_window_cache()` in the existing
`config.changed` handler (grep `config.changed` in `core/app.py`).

- [ ] **Step 4: Verify nothing on the hot path awaits LM Studio**

Run: `cd backend; pytest tests/ -k "assembly or conversation or context_window" -v`
Expected: PASS. Then manual grep:
Run (PowerShell): use Grep tool for `get_active_context_window` under `backend/api/routes/chat` → expect zero `await` hits remaining.

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes/chat/_assembly.py backend/api/routes/chat/conversations.py backend/services/lmstudio_service.py backend/core/app.py
git commit -m "perf(chat): drop synchronous LM-Studio context-window call from hot paths

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Group A — #1: frontend polling back-off when LM Studio is down

Root cause: `/models/status` (4s) and `/config/models` polling hammers a down service.

### Task 3: Back off model polling on a down service-status

**Files:**
- Modify: `frontend/src/renderer/src/stores/services.ts` (find the model-status/model-list polling interval)
- Test: `frontend/src/renderer/src/stores/services.spec.ts`

> The implementer must first READ `stores/services.ts` to find the polling action and its
> interval. The change: track a `downSince`/`backoff` factor; when the last status is
> `down`/`error`, multiply the poll interval (e.g. 4s → up to 30s), and reset to the base
> interval on the first `up`. If polling lives in a composable instead, apply the same
> there and adjust the test target.

- [ ] **Step 1: Write the failing test (vitest)**

```ts
import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { useServicesStore } from './services'

describe('services polling back-off', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('extends the poll interval while down and resets when up', () => {
    const store = useServicesStore()
    // nextPollDelay(base) is the unit under test.
    expect(store.nextPollDelay(4000)).toBe(4000) // healthy baseline
    store.noteStatus('lmstudio', 'down')
    const d1 = store.nextPollDelay(4000)
    const d2 = store.nextPollDelay(4000)
    expect(d1).toBeGreaterThan(4000)
    expect(d2).toBeGreaterThanOrEqual(d1)
    expect(d2).toBeLessThanOrEqual(30000)
    store.noteStatus('lmstudio', 'up')
    expect(store.nextPollDelay(4000)).toBe(4000)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npx vitest run src/renderer/src/stores/services.spec.ts`
Expected: FAIL — `noteStatus` / `nextPollDelay` not defined.

- [ ] **Step 3: Implement back-off in the store**

Add to `useServicesStore`:
```ts
  const _down = ref(false)
  const _backoff = ref(1)

  function noteStatus(_service: string, status: string): void {
    if (status === 'down' || status === 'error') {
      _down.value = true
      _backoff.value = Math.min(_backoff.value * 2, 8)
    } else if (status === 'up' || status === 'ready') {
      _down.value = false
      _backoff.value = 1
    }
  }

  function nextPollDelay(base: number): number {
    return _down.value ? Math.min(base * _backoff.value, 30000) : base
  }
```
Expose `noteStatus`, `nextPollDelay` in the store's return. Then in the polling loop,
call `noteStatus(name, status)` after each status read and use
`nextPollDelay(BASE_INTERVAL)` for the next `setTimeout` (convert a fixed `setInterval`
to a self-scheduling `setTimeout` if needed).

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend; npx vitest run src/renderer/src/stores/services.spec.ts`
Expected: PASS.

- [ ] **Step 5: typecheck + commit**

Run: `cd frontend; npm run typecheck`
```bash
git add frontend/src/renderer/src/stores/services.ts frontend/src/renderer/src/stores/services.spec.ts
git commit -m "perf(fe): back off model-status polling while LM Studio is down

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Group C — #3: RAG readiness gate + bounded auto-repair

Root cause: silent degradation (in-memory Qdrant fallback, dim mismatch, swallowed
failures, existence-only health). Gate truly, auto-repair, else fully disable.

### Task 4: Qdrant probes + stale-lock repair

**Files:**
- Modify: `backend/services/qdrant_service.py` (add `count`, `get_collection_dim`, `try_clear_stale_lock`, `reinitialize`)
- Test: `backend/tests/test_qdrant_service.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_try_clear_stale_lock_removes_orphan_lockfile(tmp_path):
    from backend.core.config import QdrantConfig
    from backend.services.qdrant_service import QdrantService
    cfg = QdrantConfig(mode="embedded", path=str(tmp_path / "qd"))
    svc = QdrantService(cfg)
    # Simulate an orphan RocksDB lock with no holder.
    lock_dir = tmp_path / "qd"
    lock_dir.mkdir(parents=True)
    (lock_dir / ".lock").write_text("")
    removed = svc.try_clear_stale_lock()
    assert removed is True
    assert not (lock_dir / ".lock").exists()
```

(If the embedded lock filename differs on this machine, the implementer adjusts the probe
to whatever `AsyncQdrantClient(path=...)` actually creates — verify empirically.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; pytest tests/test_qdrant_service.py::test_try_clear_stale_lock_removes_orphan_lockfile -v`
Expected: FAIL — `try_clear_stale_lock` missing.

- [ ] **Step 3: Implement probes + repair on `QdrantService`**

```python
    async def count(self, name: str) -> int:
        """Return the number of points in *name* (0 if missing)."""
        assert self._client is not None, "QdrantService not initialized"
        if not await self._client.collection_exists(name):
            return 0
        res = await self._client.count(collection_name=name, exact=True)
        return int(res.count)

    async def get_collection_dim(self, name: str) -> int | None:
        """Return the vector dimensionality of *name*, or None if missing."""
        assert self._client is not None, "QdrantService not initialized"
        if not await self._client.collection_exists(name):
            return None
        info = await self._client.get_collection(name)
        return int(info.config.params.vectors.size)  # type: ignore[union-attr]

    def try_clear_stale_lock(self) -> bool:
        """Best-effort remove an orphan embedded-mode lock file. Returns True if removed.

        Only touches the configured embedded path; never raises. A lock held by a
        live process cannot be removed on Windows (the unlink fails) — in that case
        this returns False and the caller keeps the in-memory fallback.
        """
        from pathlib import Path
        if self._config.mode != "embedded":
            return False
        removed = False
        root = Path(self._config.path)
        for lock in root.rglob(".lock"):
            try:
                lock.unlink()
                removed = True
            except OSError:
                pass
        return removed

    async def reinitialize(self) -> None:
        """Close and re-run initialize (used after a stale-lock clear)."""
        await self.close()
        self._in_memory = False
        await self.initialize()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; pytest tests/test_qdrant_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/qdrant_service.py backend/tests/test_qdrant_service.py
git commit -m "feat(qdrant): count/dim probes + stale-lock repair + reinitialize

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 5: `rag_readiness` module (probe + bounded auto-repair → verdict)

**Files:**
- Create: `backend/services/rag_readiness.py`
- Test: `backend/tests/test_rag_readiness.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the all-or-nothing RAG readiness gate."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.rag_readiness import check_rag_readiness, RagReadiness


def _ctx(*, in_memory=False, embed_ok=True, mem_dim=1024, tool_count=3):
    ctx = MagicMock()
    ctx.config.llm.tool_rag_enabled = True
    qd = MagicMock()
    qd.in_memory = in_memory
    qd.try_clear_stale_lock = MagicMock(return_value=False)
    qd.reinitialize = AsyncMock()
    qd.get_collection_dim = AsyncMock(return_value=mem_dim)
    qd.count = AsyncMock(return_value=tool_count)
    ctx.qdrant_service = qd
    emb = MagicMock()
    emb.dimensions = 1024
    emb.encode = AsyncMock(
        return_value=[0.0] * 1024 if embed_ok else None,
        side_effect=None if embed_ok else RuntimeError("no embed"),
    )
    ctx.embedding_client = emb
    ctx.memory_service = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_ready_when_all_checks_pass():
    res = await check_rag_readiness(_ctx())
    assert isinstance(res, RagReadiness)
    assert res.ready is True
    assert res.memory_enabled is True
    assert res.tool_rag_enabled is True


@pytest.mark.asyncio
async def test_not_ready_when_in_memory_and_repair_fails():
    ctx = _ctx(in_memory=True)
    res = await check_rag_readiness(ctx)
    assert res.ready is False
    assert "in-memory" in res.reason.lower()
    ctx.qdrant_service.try_clear_stale_lock.assert_called_once()


@pytest.mark.asyncio
async def test_not_ready_when_embedding_roundtrip_fails():
    res = await check_rag_readiness(_ctx(embed_ok=False))
    assert res.ready is False
    assert "embed" in res.reason.lower()


@pytest.mark.asyncio
async def test_repair_recovers_in_memory():
    ctx = _ctx(in_memory=True)
    ctx.qdrant_service.try_clear_stale_lock = MagicMock(return_value=True)

    async def _reinit():
        ctx.qdrant_service.in_memory = False
    ctx.qdrant_service.reinitialize = AsyncMock(side_effect=_reinit)

    res = await check_rag_readiness(ctx)
    assert res.ready is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; pytest tests/test_rag_readiness.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `rag_readiness.py`**

```python
"""All-or-nothing RAG readiness gate (Fase: functionality-fixes #3).

Truly probes the vector + embedding stack and, on failure, attempts a bounded
auto-repair (clear a stale embedded lock and reinitialize). If the stack still is
not 100% healthy, the caller disables memory + tool-RAG entirely rather than
running degraded. Never raises.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

COLLECTION_MEMORY = "alice_memory"
COLLECTION_TOOLS = "alice_tools"


@dataclass(frozen=True, slots=True)
class RagReadiness:
    """Verdict of :func:`check_rag_readiness`."""

    ready: bool
    reason: str
    memory_enabled: bool
    tool_rag_enabled: bool


async def _probe(ctx: Any) -> tuple[bool, str]:
    qd = getattr(ctx, "qdrant_service", None)
    emb = getattr(ctx, "embedding_client", None)
    if qd is None or emb is None:
        return False, "qdrant or embedding client missing"
    if getattr(qd, "in_memory", False):
        return False, "Qdrant running in volatile in-memory fallback"
    try:
        vec = await emb.encode("readiness probe")
    except Exception as exc:
        return False, f"embedding round-trip failed: {exc}"
    if not vec or len(vec) != int(emb.dimensions):
        return False, "embedding round-trip returned wrong/empty vector"
    if getattr(ctx, "memory_service", None) is not None:
        dim = await qd.get_collection_dim(COLLECTION_MEMORY)
        if dim is not None and dim != int(emb.dimensions):
            return False, f"memory collection dim {dim} != {emb.dimensions}"
    return True, "ok"


async def check_rag_readiness(ctx: Any) -> RagReadiness:
    """Probe → bounded auto-repair → re-probe. Returns the final verdict."""
    ok, reason = await _probe(ctx)
    if not ok:
        qd = getattr(ctx, "qdrant_service", None)
        repaired = False
        if qd is not None and getattr(qd, "in_memory", False):
            if qd.try_clear_stale_lock():
                try:
                    await qd.reinitialize()
                    repaired = True
                except Exception as exc:
                    logger.warning("Qdrant reinitialize after lock-clear failed: {}", exc)
        if repaired:
            ok, reason = await _probe(ctx)
    tool_rag = bool(getattr(ctx.config.llm, "tool_rag_enabled", False))
    if not ok:
        logger.warning("RAG readiness FAILED — memory + tool-RAG disabled: {}", reason)
        return RagReadiness(False, reason, memory_enabled=False, tool_rag_enabled=False)
    return RagReadiness(True, "ok", memory_enabled=True, tool_rag_enabled=tool_rag)
```

(If actual collection constant names differ, the implementer imports them from
`backend/services/memory_service.py` / `core/tool_registry.py` instead of redefining.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; pytest tests/test_rag_readiness.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/rag_readiness.py backend/tests/test_rag_readiness.py
git commit -m "feat(rag): all-or-nothing readiness gate with bounded auto-repair

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 6: Wire the gate into lifespan + assembly + a status route

**Files:**
- Modify: `backend/core/app.py` (lifespan: run gate after services init; stash result on ctx; emit `knowledge.status`)
- Modify: `backend/api/routes/chat/_assembly.py` (skip memory search + tool-RAG when disabled)
- Create: `backend/api/routes/knowledge.py` + register in `api/routes/__init__.py`

- [ ] **Step 1: Run the gate in lifespan and store the verdict**

In `core/app.py`, after `memory_service` / `qdrant_service` / `tool_registry` are
initialized (and tool embeddings attempted), add:
```python
    from backend.services.rag_readiness import check_rag_readiness
    ctx.rag_readiness = await check_rag_readiness(ctx)
    if not ctx.rag_readiness.ready:
        logger.warning("Knowledge/RAG disabled: {}", ctx.rag_readiness.reason)
    with contextlib.suppress(Exception):
        await ctx.event_bus.emit("knowledge.status", {
            "ready": ctx.rag_readiness.ready,
            "reason": ctx.rag_readiness.reason,
            "memory_enabled": ctx.rag_readiness.memory_enabled,
            "tool_rag_enabled": ctx.rag_readiness.tool_rag_enabled,
        })
```
Add `rag_readiness` to `AppContext` (`core/context.py`) typed `RagReadiness | None = None`.
(Use the existing `AliceEvent` enum if `knowledge.status` must be a member — add it there
and bridge it onto the events WS like the other `service.status` events.)

- [ ] **Step 2: Gate memory + tool-RAG in assembly**

In `_assembly.py`, guard the memory search block and the tool-RAG selection with the
verdict. Memory search (~line 353-373):
```python
    rr = getattr(ctx, "rag_readiness", None)
    memory_ok = rr is None or rr.memory_enabled
    if ctx.memory_service is not None and memory_ok:
        ... existing memory search ...
```
Tool selection (~line 318-329):
```python
    tool_rag_ok = rr is not None and rr.tool_rag_enabled
    if ctx.config.llm.tool_rag_enabled and tool_rag_ok and ctx.qdrant_service is not None:
        tools = await ctx.tool_registry.get_relevant_tools(user_message)
    else:
        tools = await ctx.tool_registry.get_available_tools()
```
(This makes the full-tool path a *deliberate* choice when RAG is disabled, not a hidden
fallback.)

- [ ] **Step 3: Add `GET /api/knowledge/readiness`**

`backend/api/routes/knowledge.py`:
```python
"""Knowledge/RAG readiness status route."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/readiness", summary="RAG/knowledge readiness verdict")
async def readiness(request: Request) -> dict[str, object]:
    ctx = request.app.state.context
    rr = getattr(ctx, "rag_readiness", None)
    if rr is None:
        return {"ready": False, "reason": "not initialized",
                "memory_enabled": False, "tool_rag_enabled": False}
    return {"ready": rr.ready, "reason": rr.reason,
            "memory_enabled": rr.memory_enabled,
            "tool_rag_enabled": rr.tool_rag_enabled}
```
Register it in `api/routes/__init__.py` next to the other routers (under the `/api` prefix).

- [ ] **Step 4: Verify**

Run: `cd backend; pytest tests/ -k "assembly or knowledge or readiness" -v`
Expected: PASS. Run `ruff check backend/services/rag_readiness.py backend/api/routes/knowledge.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add backend/core/app.py backend/core/context.py backend/api/routes/chat/_assembly.py backend/api/routes/knowledge.py backend/api/routes/__init__.py
git commit -m "feat(rag): gate memory+tool-RAG on readiness; add /api/knowledge/readiness

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 7: Runtime verification on THIS Windows machine (manual, no code)

- [ ] **Step 1:** Start the backend: `.\.venv\Scripts\Activate.ps1; python -m backend --reload --reload-dir backend`
- [ ] **Step 2:** `Invoke-RestMethod http://localhost:8000/api/knowledge/readiness` → expect `ready: true`. If `false`, read `reason`, fix the surfaced cause (lock dir, embedding model not loaded in LM Studio, dim mismatch), restart, re-check.
- [ ] **Step 3:** Confirm an embed→search round-trip works: send a chat message that exercises memory; verify no `in-memory fallback` warning in logs and `GET /api/vector-store/stats` shows embedded mode.
- [ ] **Step 4:** Record the outcome in the task-group review (no commit).

---

## Group B — #2: hard-sandbox scope + tier-authoritative confirmations

### Task 8: Reproduce the home-write bypass (no code — diagnostic)

- [ ] **Step 1:** With NO scope set on a conversation, ask the model to write a file. Observe where it lands and WHICH tool ran (logs: tool name + args).
- [ ] **Step 2:** Confirm the hypothesis: the writing tool's capabilities do NOT include `fs_write` (e.g. a `process_exec`/terminal/pc_automation tool), so `decide()` rule 3/4 never confine it, and its cwd defaults to home. Record the tool name + its `capabilities`/`path_args` in the review notes. This drives Task 9.

### Task 9: Confine `process_exec` + add `workspace_root` to ExecutionContext + sandbox fallback

**Files:**
- Modify: `backend/core/plugin_models.py` (`ExecutionContext`)
- Modify: `backend/services/scope_service.py` (sandbox fallback resolver)
- Modify: `backend/services/permission_service.py` (treat exec as path-confined; effective cwd)
- Modify: `backend/services/turn/tool_loop.py` (populate `workspace_root`)
- Modify: `backend/plugins/file_search/plugin.py`, `backend/plugins/pc_automation/*` (use `workspace_root` as cwd)
- Test: `backend/tests/test_scope_sandbox_fallback.py`, extend `backend/tests/test_permission_scope_confinement.py`

- [ ] **Step 1: Write the failing test (sandbox fallback resolver)**

```python
"""The no-scope hard-sandbox fallback gives each conversation an isolated workdir."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.config import WorkspaceScopeConfig
from backend.services.scope_service import ScopeService


@pytest.mark.asyncio
async def test_sandbox_root_is_per_conversation_and_created(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = WorkspaceScopeConfig(sandbox_root="data/workspaces")
    svc = ScopeService.__new__(ScopeService)
    svc._config = cfg
    svc._scopes = {}
    conv = "11111111-1111-1111-1111-111111111111"
    root = svc.sandbox_root_for(conv)
    assert root.exists() and root.is_dir()
    assert root.name == conv
    assert Path("data/workspaces") in root.parents or root.parent.name == "workspaces"
    # effective_roots returns the sandbox when no explicit scope is set
    eff = svc.effective_roots(conv)
    assert eff == [root]
    # explicit scope wins over the sandbox
    svc._scopes[conv] = [tmp_path]
    assert svc.effective_roots(conv) == [tmp_path]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; pytest tests/test_scope_sandbox_fallback.py -v`
Expected: FAIL — `sandbox_root_for` / `effective_roots` missing.

- [ ] **Step 3: Implement the sandbox fallback on `ScopeService`**

```python
    def sandbox_root_for(self, conversation_id: str) -> Path:
        """Return (creating if needed) the per-conversation ephemeral sandbox dir."""
        root = Path(self._config.sandbox_root).resolve() / str(conversation_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def effective_roots(self, conversation_id: str) -> list[Path]:
        """Explicit scope if set, else the per-conversation hard-sandbox dir.

        This is the HARD-SANDBOX policy: the model always has exactly one safe
        place to write — never the OS home, never a system root.
        """
        explicit = self.scope_roots(conversation_id)
        if explicit:
            return explicit
        return [self.sandbox_root_for(conversation_id)]
```

- [ ] **Step 4: Add `workspace_root` to `ExecutionContext`**

In `plugin_models.py`:
```python
    session_id: str
    conversation_id: str
    execution_id: str
    user_id: str | None = None
    workspace_root: str | None = None
    """Absolute path the tool MUST use as its working directory (hard sandbox).

    Resolved from the conversation's explicit scope, or the per-conversation
    ephemeral sandbox when no scope is set. Never the OS home or a system root.
    """
```

- [ ] **Step 5: Populate it in `tool_loop.py`**

Where `ExecutionContext(...)` is built (~376-380), add the workspace root from the scope
service if wired:
```python
                context=ExecutionContext(
                    session_id=client_ip,
                    conversation_id=str(conv_id),
                    execution_id=exec_id,
                    workspace_root=(
                        str(_scope_service.effective_roots(str(conv_id))[0])
                        if (_scope_service := getattr(ctx, "scope_service", None))
                        is not None
                        else None
                    ),
                ),
```

- [ ] **Step 6: Confine `process_exec` in `PermissionService`**

Make exec tools path-confined so rule 3 (no scope → deny) and rule 4 (out-of-scope →
deny) apply to them too. With the sandbox fallback, `effective_roots` is never empty, so
exec tools are confined to the sandbox rather than denied. In `permission_service.py`:
- Change the default fs-capabilities to include exec OR add an explicit exec branch in
  `decide()` so `is_exec` participates in scope confinement. Concretely, where the scope
  provider is consulted, use the scope service's `effective_roots` (sandbox-aware) instead
  of `scope_roots` so "no scope" yields the sandbox, not a hard deny. The implementer
  wires `PermissionService` to call `effective_roots` via its `scope_provider` (pass
  `scope_service.effective_roots` as the provider in `core/app.py` instead of
  `scope_roots`).

In `core/app.py` where `PermissionService(scope_provider=...)` is constructed, change:
```python
    scope_provider=ctx.scope_service.effective_roots,
```
(so the gate confines to the sandbox when no explicit scope, instead of denying).

- [ ] **Step 7: Tools use `workspace_root` as cwd**

In `file_search/plugin.py` and `pc_automation` exec, when resolving a relative path or a
process cwd, base it on `context.workspace_root` (fall back to the existing behavior only
when it is None). Example for a write:
```python
        base = Path(context.workspace_root) if context.workspace_root else Path.cwd()
        target = (base / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
```
For pc_automation subprocess calls, pass `cwd=context.workspace_root` when set.

- [ ] **Step 8: Extend `test_permission_scope_confinement.py`**

Add a test asserting that with the `effective_roots` provider and NO explicit scope, an
fs/exec tool is ALLOWED only for paths under the sandbox dir and DENIED for a home path:
```python
@pytest.mark.asyncio
async def test_exec_confined_to_sandbox_when_no_explicit_scope(tmp_path, monkeypatch):
    # Build a PermissionService whose scope_provider is effective_roots (sandbox-aware),
    # then assert an exec/write to C:\\Users\\... is DENY_OUT_OF_SCOPE while a path under
    # the sandbox is allowed. (See existing tests in this file for the harness.)
    ...
```
(Implementer fills the body using the existing harness in that file.)

- [ ] **Step 9: Run all scope tests**

Run: `cd backend; pytest tests/test_scope_sandbox_fallback.py tests/test_permission_scope_confinement.py tests/test_scope_service.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/core/plugin_models.py backend/services/scope_service.py backend/services/permission_service.py backend/services/turn/tool_loop.py backend/plugins/file_search/plugin.py backend/plugins/pc_automation backend/core/app.py backend/tests/test_scope_sandbox_fallback.py backend/tests/test_permission_scope_confinement.py
git commit -m "fix(scope): hard-sandbox confinement incl. process_exec + per-conversation fallback

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 10: Tier-authoritative confirmations (retire the silent auto-approve)

**Files:**
- Modify: `backend/services/turn/pipeline.py` (`ConfirmationMiddleware.handle`)
- Rewrite: `backend/tests/test_confirmation_toggle.py` (new contract)

- [ ] **Step 1: Rewrite the test suite to the new contract**

Replace `test_confirmations_disabled_auto_approves` with tier-driven tests. First add a
mode hook to `_build_mocks` so a tier can be injected:
```python
def _build_mocks(*, confirmations_enabled: bool = True, mode: str = "strict"):
    ...
    mode_service = MagicMock()
    from backend.services.permission_mode_service import PermissionMode
    mode_service.get_mode = MagicMock(return_value=PermissionMode(mode))
    # Make isinstance(ms, PermissionModeService) true:
    from backend.services.permission_mode_service import PermissionModeService
    mode_service.__class__ = PermissionModeService
    ctx.permission_mode_service = mode_service
    ...
```
New/updated tests:
```python
@pytest.mark.asyncio
async def test_strict_tier_always_prompts_even_with_global_flag_off():
    """Tier authoritative: NEEDS_CONFIRMATION prompts regardless of the legacy flag."""
    ctx, ws, session, llm = _build_mocks(confirmations_enabled=False, mode="strict")
    ctx.tool_registry.get_tool_definition.return_value = _make_tool_def(
        "dangerous_tool", requires_confirmation=True, risk_level="dangerous",
    )
    with patch(
        "backend.services.turn.pipeline._request_confirmation",
        new_callable=AsyncMock, return_value=ConfirmationOutcome(approved=True),
    ) as mock_confirm:
        await run_tool_loop(..., confirmation_timeout_s=30, client_ip="127.0.0.1", sync_fn=None)
        mock_confirm.assert_called_once()  # NO LONGER auto-approved


@pytest.mark.asyncio
async def test_autopilot_tier_does_not_prompt():
    """AUTOPILOT is the explicit 'never ask' tier."""
    ctx, ws, session, llm = _build_mocks(confirmations_enabled=True, mode="autopilot")
    ctx.tool_registry.get_tool_definition.return_value = _make_tool_def(
        "dangerous_tool", requires_confirmation=True, risk_level="dangerous",
    )
    with patch(
        "backend.services.turn.pipeline._request_confirmation",
        new_callable=AsyncMock,
    ) as mock_confirm:
        await run_tool_loop(..., confirmation_timeout_s=30, client_ip="127.0.0.1", sync_fn=None)
        mock_confirm.assert_not_called()
    ctx.tool_registry.execute_tool.assert_called_once()
```
Keep `test_forbidden_blocked_*` and `test_safe_tool_no_confirmation_*`. Remove the
assertion that "disabled → auto-approve a dangerous tool" (that was the bug).

> Note: `dangerous_tool` here has no fs capabilities, so AUTOPILOT → ALLOW. If a future
> test gives it `fs_write`, set an explicit scope/grant or it will DENY on no-scope.

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd backend; pytest tests/test_confirmation_toggle.py -v`
Expected: `test_strict_tier_always_prompts_even_with_global_flag_off` FAILS (currently
auto-approved).

- [ ] **Step 3: Make the middleware tier-authoritative**

In `pipeline.py` `ConfirmationMiddleware.handle`, replace the
`if self._confirmations_enabled:` decision so a tier-mandated confirmation always prompts:
```python
        gd = call.gate_decision
        if gd is not None:
            needs = gd.action is GateAction.NEEDS_CONFIRMATION
        else:
            needs = self._permission.requires_confirmation(td)
        if not needs:
            return await nxt(call)

        risk_level = td.risk_level if td is not None else "medium"
        description = td.description if td is not None else ""

        await self._sink.send(events.interaction_requested(
            turn_id=call.turn_id, execution_id=call.exec_id,
            kind="tool_confirmation", tool_name=call.tool_name,
        ))

        # Tier authoritative: a NEEDS_CONFIRMATION verdict ALWAYS prompts. The legacy
        # global toggle only governs the no-gate-decision fallback (unit-test isolation).
        tier_mandated = gd is not None and gd.action is GateAction.NEEDS_CONFIRMATION
        ask = tier_mandated or self._confirmations_enabled
        if ask:
            confirmation = await _request_confirmation(
                self._channel, call.tool_name, call.args, call.exec_id,
                self._timeout_s, risk_level=risk_level, description=description,
                reasoning=self._reasoning, cancel_event=self._cancel_event,
            )
            approved = confirmation.approved
            remember = confirmation.remember
        else:
            logger.info(
                "No tier verdict and confirmations disabled — auto-approving '{}' (exec_id={})",
                call.tool_name, call.exec_id,
            )
            approved = True
            remember = "none"
        ... (rest unchanged: interaction_resolved, audit, persist_remember) ...
```

- [ ] **Step 4: Run to verify all confirmation tests pass**

Run: `cd backend; pytest tests/test_confirmation_toggle.py tests/test_confirmation_audit.py tests/test_pipeline.py tests/test_permission_tiers.py -v`
Expected: PASS.

- [ ] **Step 5: Voice/lite boundary**

Confirm the voice/lite path (DirectTurnExecutor in voice mode) either runs in a
non-confirming tier or has no `requires_confirmation` tools. Read the voice WS handler /
lite turn path; if a conversation in voice could yield `NEEDS_CONFIRMATION` with no
interactive client, set its tier to `AUTOPILOT` for the voice session (document in code
comment). If already safe, add a one-line comment noting why. No silent auto-approve.

- [ ] **Step 6: Commit**

```bash
git add backend/services/turn/pipeline.py backend/tests/test_confirmation_toggle.py
git commit -m "fix(perm): tier-authoritative confirmations — NEEDS_CONFIRMATION always prompts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Group D — #4: conversation-switch reliability

Root cause: `loadConversation` has no generation guard / abort / loading flag → stale
response overwrites a newer selection.

### Task 11: Generation token + AbortController + loading flag

**Files:**
- Modify: `frontend/src/renderer/src/services/api.ts` (`getConversation(id, signal?)`)
- Modify: `frontend/src/renderer/src/stores/chat.ts` (`loadConversation`)
- Test: `frontend/src/renderer/src/stores/chat.spec.ts` (extend)

- [ ] **Step 1: Write the failing test**

```ts
it('discards a stale loadConversation result (latest selection wins)', async () => {
  const store = useChatStore()
  // Two pending loads; A resolves AFTER B. Final state must be B.
  const resolvers: Record<string, (v: unknown) => void> = {}
  vi.spyOn(api, 'getConversation').mockImplementation((id: string) =>
    new Promise((res) => { resolvers[id] = res }) as never)

  const pA = store.loadConversation('A')
  const pB = store.loadConversation('B')
  // B resolves first, then the stale A.
  resolvers['B']({ id: 'B', title: 'B', created_at: '', updated_at: '', messages: [] })
  await pB
  resolvers['A']({ id: 'A', title: 'A', created_at: '', updated_at: '', messages: [] })
  await pA

  expect(store.currentConversation?.id).toBe('B')
})
```
(Adjust the mocked detail shape to `ConversationDetail`. The conversations list lookup at
the top of `loadConversation` short-circuits message_count===0 — ensure the test does NOT
pre-seed `conversations` with A/B so the API path is taken, or seed them with
`message_count > 0`.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npx vitest run src/renderer/src/stores/chat.spec.ts -t "stale loadConversation"`
Expected: FAIL — currentConversation ends as 'A' (stale wins).

- [ ] **Step 3: Add a generation guard + abort + loading flag**

Add store state:
```ts
  const isLoadingConversation = ref(false)
  let _loadGeneration = 0
  let _loadAbort: AbortController | null = null
```
Rewrite `loadConversation` core:
```ts
  async function loadConversation(id: string): Promise<void> {
    const myGen = ++_loadGeneration
    _loadAbort?.abort()
    _loadAbort = new AbortController()
    const signal = _loadAbort.signal

    // ... existing same-conversation contextInfo reset + local-empty short-circuit ...

    isLoadingConversation.value = true
    try {
      const detail = await api.getConversation(id, signal)
      if (myGen !== _loadGeneration) return            // a newer selection won
      for (const msg of detail.messages) { /* resolve attachment urls */ }
      currentConversation.value = detail
      // ... existing contextInfo population ...
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') return
      if (myGen !== _loadGeneration) return
      // ... existing 404 fallback ...
    } finally {
      if (myGen === _loadGeneration) isLoadingConversation.value = false
    }
  }
```
Expose `isLoadingConversation` in the store return.

- [ ] **Step 4: Pass the signal through `api.getConversation`**

In `api.ts`, change the signature to `getConversation(id: string, signal?: AbortSignal)`
and forward `{ signal }` into the underlying `request(...)` (which already supports it).

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend; npx vitest run src/renderer/src/stores/chat.spec.ts`
Expected: PASS. Then `cd frontend; npm run typecheck` → clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/renderer/src/stores/chat.ts frontend/src/renderer/src/services/api.ts frontend/src/renderer/src/stores/chat.spec.ts
git commit -m "fix(fe): generation-guarded + abortable conversation switch (latest wins)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Group E — #5: whiteboard conversation-scoping

### Task 12: Backend count filter + store reset + module watch

**Files:**
- Modify: `backend/api/routes/whiteboards.py:79`
- Modify: `frontend/src/renderer/src/stores/whiteboard.ts` (add `reset()`)
- Modify: `frontend/src/renderer/src/components/canvas/modules/WhiteboardModule.vue` (pass id + watch)
- Test: `backend/tests/test_whiteboard_route_scope.py`, `frontend/.../stores/whiteboard.spec.ts`

- [ ] **Step 1: Backend test — count must be conversation-scoped**

```python
"""GET /api/whiteboards count must respect the conversation_id filter."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_list_passes_conversation_id_to_count():
    from backend.api.routes import whiteboards as wb
    store = MagicMock()
    store.list = AsyncMock(return_value=[])
    store.count = AsyncMock(return_value=0)

    request = MagicMock()
    request.app.state.context.db = None
    # Patch the store accessor to return our mock.
    wb._get_store = MagicMock(return_value=store)  # type: ignore[attr-defined]

    await wb.list_whiteboards(request, conversation_id="conv-1", limit=50, offset=0)
    store.count.assert_awaited_once_with(conversation_id="conv-1")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; pytest tests/test_whiteboard_route_scope.py -v`
Expected: FAIL — `count()` called with no args.

- [ ] **Step 3: Fix the route**

In `whiteboards.py:79`:
```python
    total = await store.count(conversation_id=conversation_id)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; pytest tests/test_whiteboard_route_scope.py -v`
Expected: PASS.

- [ ] **Step 5: Frontend test — store resets on switch**

`frontend/src/renderer/src/stores/whiteboard.spec.ts`:
```ts
import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useWhiteboardStore } from './whiteboard'
import { api } from '../services/api'

describe('whiteboard store scoping', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('reset() clears boards/total/currentBoard', () => {
    const store = useWhiteboardStore()
    store.boards = [{ board_id: 'x' }] as never
    store.total = 1
    store.reset()
    expect(store.boards).toEqual([])
    expect(store.total).toBe(0)
    expect(store.currentBoard).toBeNull()
  })

  it('loadBoards forwards the conversation_id', async () => {
    const store = useWhiteboardStore()
    const spy = vi.spyOn(api, 'getWhiteboards').mockResolvedValue({ items: [], total: 0 } as never)
    await store.loadBoards('conv-9')
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ conversation_id: 'conv-9' }))
  })
})
```

- [ ] **Step 6: Run to verify it fails, then add `reset()`**

Run: `cd frontend; npx vitest run src/renderer/src/stores/whiteboard.spec.ts`
Expected: FAIL — `reset` not a function.

Add to the store and its return:
```ts
  function reset(): void {
    boards.value = []
    total.value = 0
    currentBoard.value = null
    error.value = null
  }
```

- [ ] **Step 7: Make `WhiteboardModule.vue` conversation-aware**

Read `WhiteboardModule.vue`. Replace the one-shot `onMounted` guard with a watch on the
active conversation id (from the chat store), which resets then reloads:
```ts
import { watch } from 'vue'
import { useChatStore } from '../../../stores/chat'
const chatStore = useChatStore()
watch(
  () => chatStore.currentConversation?.id,
  (id) => {
    store.reset()
    if (id) void store.loadBoards(id)
  },
  { immediate: true }
)
```
Remove the old `onMounted(() => { if (!store.hasBoards ...) store.loadBoards() })` block.

- [ ] **Step 8: Run to verify + typecheck**

Run: `cd frontend; npx vitest run src/renderer/src/stores/whiteboard.spec.ts; npm run typecheck`
Expected: PASS + clean.

- [ ] **Step 9: Commit**

```bash
git add backend/api/routes/whiteboards.py backend/tests/test_whiteboard_route_scope.py frontend/src/renderer/src/stores/whiteboard.ts frontend/src/renderer/src/stores/whiteboard.spec.ts frontend/src/renderer/src/components/canvas/modules/WhiteboardModule.vue
git commit -m "fix(whiteboard): scope list+count+store to the active conversation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Group F — #6: ask_user sequential multi-question wizard

New contract (clean cutover, no dual path). One `execution_id`; answers correlated by id.

**Request payload (server→client `ask_user_required`):**
```jsonc
{ "type": "ask_user_required", "execution_id": "...",
  "questions": [
    { "id": "q1", "text": "...", "type": "radio",
      "options": ["A","B"], "allow_free_text": true } ] }
```
**Response payload (client→server `ask_user_response`):**
```jsonc
{ "type": "ask_user_response", "execution_id": "...",
  "answers": [
    { "question_id": "q1", "selected": ["A"], "free_text": "" } ] }
```

### Task 13: Backend schema + multi-question round-trip

**Files:**
- Modify: `backend/plugins/agent/plugin.py:178-220` (schema)
- Modify: `backend/services/turn/pipeline.py:729-781` (`_execute_user_interaction`)
- Test: `backend/tests/test_ask_user_multi.py`

- [ ] **Step 1: Write the failing test**

```python
"""ask_user multi-question round-trip: payload out, labeled answers back."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.services.turn.pipeline import _execute_user_interaction


@pytest.mark.asyncio
async def test_multi_question_payload_and_answer_formatting():
    channel = AsyncMock()
    channel.request = AsyncMock(return_value={
        "answers": [
            {"question_id": "q1", "selected": ["Red"], "free_text": ""},
            {"question_id": "q2", "selected": ["A", "C"], "free_text": "and D"},
        ],
    })
    args = {
        "questions": [
            {"id": "q1", "text": "Favourite colour?", "type": "radio",
             "options": ["Red", "Blue"], "allow_free_text": False},
            {"id": "q2", "text": "Pick toppings", "type": "checkbox",
             "options": ["A", "B", "C"], "allow_free_text": True},
        ],
    }
    result = await _execute_user_interaction(
        channel, "ask_user", args, execution_id="e1", timeout_s=30,
    )
    assert result.success is True
    # Payload carried the questions array.
    sent = channel.request.call_args.args[1]
    assert sent["questions"][0]["id"] == "q1"
    assert sent["questions"][1]["type"] == "checkbox"
    # Labeled answer block back to the model.
    assert "Favourite colour?" in result.content
    assert "Red" in result.content
    assert "and D" in result.content
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; pytest tests/test_ask_user_multi.py -v`
Expected: FAIL — current handler only reads single `question`.

- [ ] **Step 3: Update the tool schema** (`agent/plugin.py`)

Replace the `parameters` of the `ask_user` `ToolDefinition` with:
```python
                    parameters={
                        "type": "object",
                        "properties": {
                            "questions": {
                                "type": "array",
                                "minItems": 1,
                                "description": (
                                    "One or more questions to ask in sequence. The "
                                    "user steps through them in a wizard and submits "
                                    "once. Use this whenever you need clarification."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string",
                                               "description": "Stable id to correlate the answer."},
                                        "text": {"type": "string",
                                                 "description": "The question, phrased clearly."},
                                        "type": {"type": "string", "enum": ["radio", "checkbox"],
                                                 "description": "radio = pick one; checkbox = pick many."},
                                        "options": {"type": "array", "items": {"type": "string"},
                                                    "description": "Choices for the question."},
                                        "allow_free_text": {"type": "boolean",
                                                            "description": "Allow an additional free-text answer."},
                                    },
                                    "required": ["id", "text", "type"],
                                },
                            },
                        },
                        "required": ["questions"],
                    },
```

- [ ] **Step 4: Rewrite `_execute_user_interaction`** (`pipeline.py:729`)

```python
async def _execute_user_interaction(
    channel: InteractionChannel,
    tool_name: str,
    args: dict[str, Any],
    execution_id: str,
    timeout_s: float,
    cancel_event: asyncio.Event | None = None,
) -> ToolResult:
    """Ask the user one or more questions (sequential wizard) and await answers."""
    raw_questions = args.get("questions")
    questions: list[dict[str, Any]] = []
    if isinstance(raw_questions, list):
        for i, q in enumerate(raw_questions):
            if not isinstance(q, dict):
                continue
            questions.append({
                "id": str(q.get("id") or f"q{i + 1}"),
                "text": str(q.get("text", "")).strip(),
                "type": "checkbox" if q.get("type") == "checkbox" else "radio",
                "options": [str(o) for o in q.get("options", []) if o is not None],
                "allow_free_text": bool(q.get("allow_free_text", False)),
            })
    if not questions:
        return ToolResult.fail("ask_user called with no questions")

    payload: dict[str, Any] = {"questions": questions}
    msg = await channel.request(
        "ask_user", payload,
        execution_id=execution_id, timeout_s=timeout_s, cancel_event=cancel_event,
    )
    answers = msg.get("answers") if isinstance(msg, dict) else None
    if not isinstance(answers, list):
        return ToolResult.ok("(no answer provided)", content_type="text/plain")

    by_id = {str(a.get("question_id")): a for a in answers if isinstance(a, dict)}
    lines: list[str] = []
    for q in questions:
        a = by_id.get(q["id"], {})
        selected = a.get("selected") if isinstance(a.get("selected"), list) else []
        free = str(a.get("free_text", "")).strip()
        parts = [str(s) for s in selected]
        if free:
            parts.append(free)
        lines.append(f"Q: {q['text']}\nA: {', '.join(parts) if parts else '(no answer)'}")
    return ToolResult.ok("\n\n".join(lines), content_type="text/plain")
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend; pytest tests/test_ask_user_multi.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/plugins/agent/plugin.py backend/services/turn/pipeline.py backend/tests/test_ask_user_multi.py
git commit -m "feat(ask_user): multi-question schema + sequential answer round-trip

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 14: Frontend types + store + handlers

**Files:**
- Modify: `frontend/src/renderer/src/types/chat.ts` (request/response/`AskUserRequest`)
- Modify: `frontend/src/renderer/src/composables/useChat.ts` (`onAskUserRequired`, `answerAskUser`)
- Modify: `frontend/src/renderer/src/stores/chat.ts` (`addPendingAskUser` shape)
- Test: `frontend/.../stores/chat.spec.ts` (extend)

- [ ] **Step 1: New TS types** (`types/chat.ts`)

```ts
export interface AskUserQuestion {
  id: string
  text: string
  type: 'radio' | 'checkbox'
  options?: string[]
  allow_free_text?: boolean
}
export interface WsAskUserRequiredMessage {
  type: 'ask_user_required'
  execution_id: string
  questions: AskUserQuestion[]
}
export interface AskUserAnswer {
  question_id: string
  selected: string[]
  free_text?: string
}
export interface WsAskUserResponsePayload {
  type: 'ask_user_response'
  execution_id: string
  answers: AskUserAnswer[]
}
export interface AskUserRequest {
  executionId: string
  questions: AskUserQuestion[]
}
```

- [ ] **Step 2: Update store pending shape + handlers**

In `stores/chat.ts`, change `addPendingAskUser` to accept
`{ executionId, questions }`. In `useChat.ts`:
```ts
const onAskUserRequired = (data: unknown): void => {
  if (store.streamGeneration !== activeGeneration) return
  const msg = data as WsAskUserRequiredMessage
  store.addPendingAskUser({ executionId: msg.execution_id, questions: msg.questions })
}
function answerAskUser(executionId: string, answers: AskUserAnswer[]): void {
  const payload: WsAskUserResponsePayload = {
    type: 'ask_user_response', execution_id: executionId, answers,
  }
  wsManager.send(payload)
  store.removePendingAskUser(executionId)
}
```

- [ ] **Step 3: Extend `chat.spec.ts`**

```ts
it('addPendingAskUser stores a multi-question request', () => {
  const store = useChatStore()
  store.addPendingAskUser({
    executionId: 'e1',
    questions: [{ id: 'q1', text: 'Hi?', type: 'radio', options: ['a'] }],
  })
  const pending = store.pendingAskUser['e1']
  expect(pending.questions[0].id).toBe('q1')
})
```

- [ ] **Step 4: Run + typecheck**

Run: `cd frontend; npx vitest run src/renderer/src/stores/chat.spec.ts; npm run typecheck`
Expected: PASS + clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/types/chat.ts frontend/src/renderer/src/composables/useChat.ts frontend/src/renderer/src/stores/chat.ts frontend/src/renderer/src/stores/chat.spec.ts
git commit -m "feat(ask_user): multi-question FE types, store and WS handlers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 15: `AskUserPrompt.vue` Next/Back wizard (manual verify)

**Files:**
- Rewrite: `frontend/src/renderer/src/components/chat/AskUserPrompt.vue`

- [ ] **Step 1: Implement the wizard**

```vue
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { AskUserRequest, AskUserAnswer } from '../../types/chat'

const props = defineProps<{ request: AskUserRequest }>()
const emit = defineEmits<{ answer: [executionId: string, answers: AskUserAnswer[]] }>()

const step = ref(0)
const total = computed(() => props.request.questions.length)
const current = computed(() => props.request.questions[step.value])

// Per-question working state, keyed by question id.
const selected = ref<Record<string, string[]>>({})
const freeText = ref<Record<string, string>>({})

function toggle(qid: string, option: string, multi: boolean): void {
  const cur = selected.value[qid] ?? []
  if (multi) {
    selected.value[qid] = cur.includes(option)
      ? cur.filter((o) => o !== option)
      : [...cur, option]
  } else {
    selected.value[qid] = [option]
  }
}

const canAdvance = computed(() => {
  const q = current.value
  if (!q) return false
  const hasSel = (selected.value[q.id]?.length ?? 0) > 0
  const hasFree = (freeText.value[q.id]?.trim().length ?? 0) > 0
  return hasSel || (q.allow_free_text ? hasFree : false) || (q.options?.length ?? 0) === 0
})

function next(): void {
  if (step.value < total.value - 1) step.value += 1
  else submit()
}
function back(): void {
  if (step.value > 0) step.value -= 1
}
function submit(): void {
  const answers: AskUserAnswer[] = props.request.questions.map((q) => ({
    question_id: q.id,
    selected: selected.value[q.id] ?? [],
    free_text: freeText.value[q.id]?.trim() || undefined,
  }))
  emit('answer', props.request.executionId, answers)
}
</script>

<template>
  <div class="ask-card" v-if="current">
    <div class="ask-card__progress">{{ step + 1 }} / {{ total }}</div>
    <p class="ask-card__question">{{ current.text }}</p>

    <div v-if="current.options?.length" class="ask-card__options">
      <button
        v-for="option in current.options"
        :key="option"
        type="button"
        class="ask-card__option"
        :class="{ 'ask-card__option--on': (selected[current.id] ?? []).includes(option) }"
        @click="toggle(current.id, option, current.type === 'checkbox')"
      >
        <span class="ask-card__marker" :class="current.type" />
        {{ option }}
      </button>
    </div>

    <input
      v-if="current.allow_free_text"
      v-model="freeText[current.id]"
      class="ask-card__free"
      type="text"
      placeholder="Oppure scrivi una risposta…"
    />

    <div class="ask-card__nav">
      <button type="button" class="ask-card__btn" :disabled="step === 0" @click="back">
        Indietro
      </button>
      <button
        type="button"
        class="ask-card__btn ask-card__btn--primary"
        :disabled="!canAdvance"
        @click="next"
      >
        {{ step < total - 1 ? 'Avanti' : 'Invia' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.ask-card { display: flex; flex-direction: column; gap: 10px; padding: 14px;
  border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
  background: var(--surface-1); }
.ask-card__progress { font-size: 11px; opacity: 0.6; }
.ask-card__question { margin: 0; font-weight: 600; }
.ask-card__options { display: flex; flex-direction: column; gap: 6px; }
.ask-card__option { display: flex; align-items: center; gap: 8px; padding: 8px 10px;
  text-align: left; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm);
  background: var(--surface-2); cursor: pointer; transition: border-color .15s, background .15s; }
.ask-card__option--on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, var(--surface-2)); }
.ask-card__marker { width: 14px; height: 14px; border: 1.5px solid var(--border-strong); }
.ask-card__marker.radio { border-radius: 50%; }
.ask-card__marker.checkbox { border-radius: 3px; }
.ask-card__option--on .ask-card__marker { background: var(--accent); border-color: var(--accent); }
.ask-card__free { padding: 8px 10px; border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm); background: var(--surface-2); color: inherit; }
.ask-card__nav { display: flex; justify-content: space-between; gap: 8px; margin-top: 4px; }
.ask-card__btn { padding: 7px 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);
  background: var(--surface-2); cursor: pointer; }
.ask-card__btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ask-card__btn--primary { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
</style>
```
(Verify the design-token names against `theme.css`; adjust to the repo's actual tokens.)

- [ ] **Step 2: Verify the parent passes the new `answer(executionId, answers)` signature**

Find where `<AskUserPrompt>` is mounted; update the `@answer` handler to call
`answerAskUser(executionId, answers)`.

- [ ] **Step 3: typecheck + manual UI verify**

Run: `cd frontend; npm run typecheck` → clean.
Manual: trigger an `ask_user` with 2 questions (one radio + free-text, one checkbox);
step through Indietro/Avanti/Invia; confirm the model receives all answers labeled.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/renderer/src/components/chat/AskUserPrompt.vue frontend/src/renderer/src/components/**/*.vue
git commit -m "feat(ask_user): Next/Back multi-question wizard UI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (whole batch)

- [ ] `cd backend; pytest tests/ -v` → all green (note any pre-existing unrelated failures explicitly).
- [ ] `cd backend; ruff check .` clean on changed files; `mypy .` no new errors on changed files.
- [ ] `cd frontend; npm run typecheck` clean; `npx vitest run` all green; `npm run lint` no new errors.
- [ ] Runtime on this Windows machine: `/api/knowledge/readiness` healthy; a no-scope write lands in `data/workspaces/<id>/`; a `STRICT` dangerous tool prompts and rejection blocks it; rapid conversation switching always lands on the last click; whiteboards scoped per conversation; ask_user 2-question wizard round-trips.
- [ ] Then run superpowers:finishing-a-development-branch.

## Self-review (author)

- **Spec coverage:** cross-cutting (T1-2) ✓ #1; #1 (T3) ✓; #3 (T4-7) ✓; #2 scope (T8-9) + confirmations (T10) ✓; #4 (T11) ✓; #5 (T12) ✓; #6 (T13-15) ✓. Boundary decisions: voice/lite (T10 S5), MCP-external (documented in spec/out-of-scope), lossy recreate (T4 reuses existing `ensure_collection`) ✓.
- **Placeholders:** the few "implementer fills the body" spots (T9 S8 exec test, T10 S1 run_tool_loop args) reuse fully-shown harnesses already in this plan or the cited existing test file — not vague TODOs.
- **Type/name consistency:** `effective_roots` (T9) used by app.py provider (T9 S6); `get_cached_context_window`/`invalidate_context_window_cache` (T1) used in T2; `reset()` (T12) used in WhiteboardModule (T12 S7); `answers`/`AskUserAnswer` consistent across T13/T14/T15; `RagReadiness` fields consistent T5↔T6.
