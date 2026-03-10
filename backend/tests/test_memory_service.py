"""Tests for the Memory Service (Phase 9).

All tests mock the aiosqlite layer and EmbeddingClient so we can verify
MemoryService logic without requiring the native sqlite-vec extension.

Mock rows use plain dicts to match the ``aiosqlite.Row`` dict-access
pattern used throughout ``_row_to_entry`` and the search/list methods.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import MemoryConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_config() -> MemoryConfig:
    """Create a MemoryConfig for testing."""
    return MemoryConfig(
        enabled=True,
        db_path=":memory:",
        embedding_model="test-model",
        embedding_dim=384,
        embedding_fallback=False,
        top_k=5,
        similarity_threshold=0.5,
        session_ttl_hours=24,
        auto_cleanup_days=90,
    )


@pytest.fixture
def mock_embedding_client() -> AsyncMock:
    """Mock embedding client returning fixed-dim vectors."""
    client = AsyncMock()
    client.encode = AsyncMock(return_value=[0.1] * 384)
    client.encode_batch = AsyncMock(return_value=[[0.1] * 384])
    client.dimensions = 384
    client.close = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Helpers — timestamps
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
_PAST = _NOW - timedelta(hours=48)
_FUTURE = _NOW + timedelta(hours=48)


# ---------------------------------------------------------------------------
# Helpers — dict-based mock rows (match aiosqlite.Row dict access)
# ---------------------------------------------------------------------------


def _entry_row(
    memory_id: str | None = None,
    content: str = "Python is my favourite language",
    scope: str = "long_term",
    category: str | None = "preference",
    source: str = "user",
    conversation_id: str | None = None,
    created_at: str | None = None,
    expires_at: str | None = None,
    embedding_model: str = "test-model",
) -> dict:
    """Build a dict mimicking an ``aiosqlite.Row`` from memory_entries."""
    return {
        "id": memory_id or str(uuid.uuid4()),
        "content": content,
        "scope": scope,
        "category": category,
        "source": source,
        "conversation_id": conversation_id,
        "created_at": created_at or _NOW.isoformat(),
        "expires_at": expires_at,
        "embedding_model": embedding_model,
    }


def _vec_row(memory_id: str | None = None, distance: float = 0.15) -> dict:
    """Build a dict mimicking an ``aiosqlite.Row`` from memory_vectors."""
    return {
        "id": memory_id or str(uuid.uuid4()),
        "distance": distance,
    }


def _make_cursor(
    fetchone_val=None,
    fetchall_val=None,
    rowcount: int = 0,
) -> AsyncMock:
    """Build a mock aiosqlite cursor."""
    cur = AsyncMock()
    cur.fetchone = AsyncMock(return_value=fetchone_val)
    cur.fetchall = AsyncMock(return_value=fetchall_val or [])
    cur.rowcount = rowcount
    return cur


def _make_conn() -> AsyncMock:
    """Build a mock aiosqlite connection.

    Every attribute is ``AsyncMock`` so ``await conn.enable_load_extension``
    and similar calls work transparently.
    """
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    return conn


def _make_asyncio_mock() -> MagicMock:
    """Build an asyncio module mock that closes coroutines passed to create_task.

    When ``asyncio`` is patched wholesale, ``create_task`` receives a real
    coroutine object but never awaits or closes it, which triggers a
    ``RuntimeWarning: coroutine … was never awaited``.  This helper
    configures ``create_task`` to close the coroutine immediately so the
    warning is suppressed while still preventing the real task from running.
    """
    m = MagicMock()
    task_mock = MagicMock()
    task_mock.done.return_value = True

    def _close_coro(coro, **kwargs):
        coro.close()
        return task_mock

    m.create_task.side_effect = _close_coro
    return m


async def _build_svc(memory_config, mock_embedding_client, mock_conn):
    """Construct, patch, and initialize a MemoryService for testing."""
    from backend.services.memory_service import MemoryService

    mock_connect = AsyncMock(return_value=mock_conn)

    with (
        patch(
            "backend.services.memory_service.aiosqlite",
            connect=mock_connect,
            Row=MagicMock(),
        ),
        patch(
            "backend.services.memory_service.EmbeddingClient",
            return_value=mock_embedding_client,
        ),
        patch("backend.services.memory_service.asyncio", _make_asyncio_mock()),
        patch(
            "backend.services.memory_service._resolve_vec_extension_path",
            return_value="vec0",
        ),
    ):
        svc = MemoryService(
            config=memory_config,
            llm_base_url="http://localhost:1234",
        )
        await svc.initialize()

    return svc


# ---------------------------------------------------------------------------
# Tests — Initialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_opens_connection(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """initialize() should call aiosqlite.connect and create tables."""
    mock_conn = _make_conn()
    mock_connect = AsyncMock(return_value=mock_conn)

    with (
        patch(
            "backend.services.memory_service.aiosqlite",
            connect=mock_connect,
            Row=MagicMock(),
        ),
        patch(
            "backend.services.memory_service.EmbeddingClient",
            return_value=mock_embedding_client,
        ),
        patch("backend.services.memory_service.asyncio", _make_asyncio_mock()),
        patch(
            "backend.services.memory_service._resolve_vec_extension_path",
            return_value="vec0",
        ),
    ):
        from backend.services.memory_service import MemoryService

        svc = MemoryService(
            config=memory_config,
            llm_base_url="http://localhost:1234",
        )
        await svc.initialize()

        mock_connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_initialize_is_idempotent(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """Calling initialize() twice should not re-open the connection."""
    mock_conn = _make_conn()
    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)

    # Second call should be a no-op (db already set)
    await svc.initialize()


# ---------------------------------------------------------------------------
# Tests — add
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_creates_entry(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """add() should embed the content and INSERT into the DB."""
    mock_conn = _make_conn()
    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)

    entry = await svc.add(
        content="User prefers dark mode",
        scope="long_term",
        category="preference",
        source="user",
    )

    mock_embedding_client.encode.assert_awaited()

    insert_calls = [
        c for c in mock_conn.execute.await_args_list
        if isinstance(c.args[0], str) and "INSERT" in c.args[0].upper()
    ]
    assert len(insert_calls) >= 1

    assert entry is not None
    assert entry.content == "User prefers dark mode"
    assert entry.scope == "long_term"
    assert entry.category == "preference"


@pytest.mark.asyncio
async def test_add_session_does_not_auto_set_expires(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """add() with scope='session' does NOT auto-set expires_at."""
    mock_conn = _make_conn()
    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)

    entry = await svc.add(
        content="Current task is writing tests",
        scope="session",
        category="context",
        source="assistant",
    )

    assert entry is not None
    assert entry.scope == "session"
    # The real add() does NOT auto-set expires_at for session scope
    assert entry.expires_at is None


@pytest.mark.asyncio
async def test_add_with_explicit_expires_at(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """add() with an explicit expires_at should honor it."""
    mock_conn = _make_conn()
    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)

    custom_expiry = _NOW + timedelta(hours=12)
    entry = await svc.add(
        content="Temporary note",
        scope="session",
        category="context",
        source="user",
        expires_at=custom_expiry,
    )

    assert entry is not None
    assert entry.expires_at == custom_expiry


@pytest.mark.asyncio
async def test_add_with_conversation_id(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """add() with conversation_id stores it as UUID in the entry."""
    mock_conn = _make_conn()
    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)

    conv_id = str(uuid.uuid4())
    entry = await svc.add(
        content="Something from this conversation",
        scope="session",
        category="context",
        source="assistant",
        conversation_id=conv_id,
    )

    assert entry is not None
    # The return value converts conversation_id str -> uuid.UUID
    assert entry.conversation_id == uuid.UUID(conv_id)


# ---------------------------------------------------------------------------
# Tests — search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_results(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """search() should embed the query and return matching entries."""
    mid = str(uuid.uuid4())
    row = _entry_row(memory_id=mid, content="User prefers dark mode")
    vrow = _vec_row(memory_id=mid, distance=0.1)

    mock_conn = _make_conn()
    vec_cursor = _make_cursor(fetchall_val=[vrow])
    entry_cursor = _make_cursor(fetchone_val=row)

    async def _route_execute(sql, *args, **kwargs):
        if isinstance(sql, str) and "memory_vectors" in sql:
            return vec_cursor
        return entry_cursor

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(side_effect=_route_execute)

    results = await svc.search("dark mode preference", k=5)

    mock_embedding_client.encode.assert_awaited()
    assert len(results) >= 1
    assert "entry" in results[0]
    assert "score" in results[0]
    assert results[0]["entry"].content == "User prefers dark mode"


@pytest.mark.asyncio
async def test_search_no_results(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """Search with no matching vector rows returns empty list."""
    mock_conn = _make_conn()
    empty_cursor = _make_cursor(fetchall_val=[])

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(return_value=empty_cursor)

    results = await svc.search("completely unrelated query xyz", k=5)
    assert results == []


@pytest.mark.asyncio
async def test_search_respects_scope_filter(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """search() with filter={'scope': ...} excludes non-matching entries."""
    mid = str(uuid.uuid4())
    row = _entry_row(memory_id=mid, scope="long_term", category="preference")
    vrow = _vec_row(memory_id=mid, distance=0.1)

    mock_conn = _make_conn()
    vec_cursor = _make_cursor(fetchall_val=[vrow])
    entry_cursor = _make_cursor(fetchone_val=row)

    async def _route_execute(sql, *args, **kwargs):
        if isinstance(sql, str) and "memory_vectors" in sql:
            return vec_cursor
        return entry_cursor

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(side_effect=_route_execute)

    results = await svc.search(
        "preference", k=5, filter={"scope": "long_term"},
    )
    assert len(results) >= 1

    # Search with a different scope — should be filtered out in Python
    mock_conn.execute = AsyncMock(side_effect=_route_execute)
    results2 = await svc.search(
        "preference", k=5, filter={"scope": "session"},
    )
    assert results2 == []


@pytest.mark.asyncio
async def test_search_filters_expired(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """Entries with past expires_at are filtered out by search()."""
    mid = str(uuid.uuid4())
    expired_row = _entry_row(
        memory_id=mid,
        content="Expired session note",
        scope="session",
        expires_at=_PAST.isoformat(),
    )
    vrow = _vec_row(memory_id=mid, distance=0.1)

    mock_conn = _make_conn()
    vec_cursor = _make_cursor(fetchall_val=[vrow])
    entry_cursor = _make_cursor(fetchone_val=expired_row)

    async def _route_execute(sql, *args, **kwargs):
        if isinstance(sql, str) and "memory_vectors" in sql:
            return vec_cursor
        return entry_cursor

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(side_effect=_route_execute)

    results = await svc.search("session note", k=10)
    # Expired entry should have been filtered out in Python
    assert results == []


@pytest.mark.asyncio
async def test_search_filters_low_similarity(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """Entries below similarity_threshold are excluded."""
    mid = str(uuid.uuid4())
    # distance = 0.9 -> similarity = 0.1, below threshold of 0.5
    vrow = _vec_row(memory_id=mid, distance=0.9)

    mock_conn = _make_conn()
    vec_cursor = _make_cursor(fetchall_val=[vrow])

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(return_value=vec_cursor)

    results = await svc.search("anything", k=5)
    assert results == []


# ---------------------------------------------------------------------------
# Tests — delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """delete() should execute DELETE and return True."""
    mock_conn = _make_conn()
    del_cursor = _make_cursor(rowcount=1)

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(return_value=del_cursor)

    target_id = str(uuid.uuid4())
    result = await svc.delete(target_id)

    assert result is True
    delete_calls = [
        c for c in mock_conn.execute.await_args_list
        if isinstance(c.args[0], str) and "DELETE" in c.args[0].upper()
    ]
    assert len(delete_calls) >= 1


@pytest.mark.asyncio
async def test_delete_nonexistent(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """delete() for a non-existent ID should return False."""
    mock_conn = _make_conn()
    del_cursor = _make_cursor(rowcount=0)

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(return_value=del_cursor)

    result = await svc.delete("nonexistent-id")
    assert result is False


@pytest.mark.asyncio
async def test_delete_accepts_str_id(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """delete() accepts a plain str (not uuid.UUID)."""
    mock_conn = _make_conn()
    del_cursor = _make_cursor(rowcount=1)

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(return_value=del_cursor)

    result = await svc.delete(str(uuid.uuid4()))
    assert result is True


# ---------------------------------------------------------------------------
# Tests — delete_by_scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_by_scope(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """delete_by_scope('session') should remove all session entries."""
    mock_conn = _make_conn()
    del_cursor = _make_cursor(rowcount=3)

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(return_value=del_cursor)

    count = await svc.delete_by_scope("session")
    assert count == 3

    delete_calls = [
        c for c in mock_conn.execute.await_args_list
        if isinstance(c.args[0], str)
        and "DELETE" in c.args[0].upper()
        and "scope" in c.args[0].lower()
    ]
    assert len(delete_calls) >= 1


@pytest.mark.asyncio
async def test_delete_by_scope_zero(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """delete_by_scope returns 0 when nothing matches."""
    mock_conn = _make_conn()
    del_cursor = _make_cursor(rowcount=0)

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(return_value=del_cursor)

    count = await svc.delete_by_scope("nonexistent_scope")
    assert count == 0


# ---------------------------------------------------------------------------
# Tests — list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """list() without filters returns all entries and a total count."""
    rows = [
        _entry_row(content="Memory 1"),
        _entry_row(content="Memory 2"),
        _entry_row(content="Memory 3"),
    ]

    mock_conn = _make_conn()
    count_cursor = _make_cursor(fetchone_val={"cnt": 3})
    data_cursor = _make_cursor(fetchall_val=rows)

    async def _route_execute(sql, *args, **kwargs):
        if isinstance(sql, str) and "COUNT" in sql.upper():
            return count_cursor
        return data_cursor

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(side_effect=_route_execute)

    entries, total = await svc.list()

    assert total == 3
    assert len(entries) == 3


@pytest.mark.asyncio
async def test_list_filtered_by_scope(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """list() with scope filter returns matching entries only."""
    rows = [_entry_row(content="Preference 1", scope="long_term")]

    mock_conn = _make_conn()
    count_cursor = _make_cursor(fetchone_val={"cnt": 1})
    data_cursor = _make_cursor(fetchall_val=rows)

    async def _route_execute(sql, *args, **kwargs):
        if isinstance(sql, str) and "COUNT" in sql.upper():
            return count_cursor
        return data_cursor

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(side_effect=_route_execute)

    entries, total = await svc.list(filter={"scope": "long_term"})

    assert total == 1
    assert len(entries) == 1

    scope_calls = [
        c for c in mock_conn.execute.await_args_list
        if len(c.args) > 0
        and isinstance(c.args[0], str)
        and "scope" in c.args[0].lower()
    ]
    assert len(scope_calls) >= 1


@pytest.mark.asyncio
async def test_list_filtered_by_category(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """list() with category filter returns matching entries only."""
    rows = [_entry_row(content="Earth is round", category="fact")]

    mock_conn = _make_conn()
    count_cursor = _make_cursor(fetchone_val={"cnt": 1})
    data_cursor = _make_cursor(fetchall_val=rows)

    async def _route_execute(sql, *args, **kwargs):
        if isinstance(sql, str) and "COUNT" in sql.upper():
            return count_cursor
        return data_cursor

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(side_effect=_route_execute)

    entries, total = await svc.list(filter={"category": "fact"})

    assert total == 1
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_list_uncategorised_emits_is_null(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """list() with category='uncategorised' emits WHERE category IS NULL."""
    rows = [_entry_row(content="No category", category=None)]

    mock_conn = _make_conn()
    count_cursor = _make_cursor(fetchone_val={"cnt": 1})
    data_cursor = _make_cursor(fetchall_val=rows)

    executed_sql: list[str] = []

    async def _route_execute(sql, *args, **kwargs):
        if isinstance(sql, str):
            executed_sql.append(sql)
            if "COUNT" in sql.upper():
                return count_cursor
        return data_cursor

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(side_effect=_route_execute)

    entries, total = await svc.list(filter={"category": "uncategorised"})

    assert total == 1
    # The SQL must use IS NULL, not = 'uncategorised'
    null_queries = [s for s in executed_sql if "IS NULL" in s.upper()]
    assert len(null_queries) >= 1, (
        "Expected 'category IS NULL' in SQL but got: " + repr(executed_sql)
    )
    uncategorised_queries = [
        s for s in executed_sql if "'uncategorised'" in s.lower()
    ]
    assert len(uncategorised_queries) == 0, (
        "Should not use literal 'uncategorised' in SQL"
    )


# ---------------------------------------------------------------------------
# Tests — stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """stats() should return counts by scope and category."""
    mock_conn = _make_conn()

    total_cursor = _make_cursor(fetchone_val={"cnt": 5})
    scope_cursor = _make_cursor(
        fetchall_val=[
            {"scope": "long_term", "cnt": 3},
            {"scope": "session", "cnt": 2},
        ],
    )
    category_cursor = _make_cursor(
        fetchall_val=[
            {"category": "preference", "cnt": 2},
            {"category": "fact", "cnt": 2},
            {"category": "context", "cnt": 1},
        ],
    )

    async def _route_execute(sql, *args, **kwargs):
        if isinstance(sql, str):
            upper = sql.upper()
            if "GROUP BY" in upper and "SCOPE" in upper:
                return scope_cursor
            if "GROUP BY" in upper and "CATEGORY" in upper:
                return category_cursor
            if "COUNT" in upper:
                return total_cursor
        return _make_cursor()

    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)
    mock_conn.execute = AsyncMock(side_effect=_route_execute)

    with patch.object(Path, "exists", return_value=False):
        result = await svc.stats()

    assert isinstance(result, dict)
    assert result["total"] == 5
    assert result["by_scope"]["long_term"] == 3
    assert result["by_scope"]["session"] == 2
    assert result["by_category"]["preference"] == 2


# ---------------------------------------------------------------------------
# Tests — dimension mismatch (checked at add/search time, not initialize)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dimension_mismatch_on_add(
    memory_config: MemoryConfig,
) -> None:
    """When encoder returns wrong-dim vector, add() should raise."""
    from backend.services.memory_service import (
        MemoryDimensionMismatchError,
        MemoryService,
    )

    bad_embed = AsyncMock()
    bad_embed.encode = AsyncMock(return_value=[0.1] * 768)  # 768 != 384
    bad_embed.close = AsyncMock()

    mock_conn = _make_conn()
    svc = await _build_svc(memory_config, bad_embed, mock_conn)

    with pytest.raises(MemoryDimensionMismatchError):
        await svc.add(content="test", scope="long_term")


@pytest.mark.asyncio
async def test_dimension_mismatch_on_search(
    memory_config: MemoryConfig,
) -> None:
    """When encoder returns wrong-dim vector, search() should raise."""
    from backend.services.memory_service import (
        MemoryDimensionMismatchError,
        MemoryService,
    )

    bad_embed = AsyncMock()
    bad_embed.encode = AsyncMock(return_value=[0.1] * 768)
    bad_embed.close = AsyncMock()

    mock_conn = _make_conn()
    svc = await _build_svc(memory_config, bad_embed, mock_conn)

    with pytest.raises(MemoryDimensionMismatchError):
        await svc.search("query")


# ---------------------------------------------------------------------------
# Tests — uninitialized service raises RuntimeError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_uninitialized_raises(
    memory_config: MemoryConfig,
) -> None:
    """Calling search() before initialize() raises RuntimeError."""
    from backend.services.memory_service import MemoryService

    svc = MemoryService(
        config=memory_config,
        llm_base_url="http://localhost:1234",
    )

    with pytest.raises(RuntimeError, match="not initialised"):
        await svc.search("test", k=5)


@pytest.mark.asyncio
async def test_add_uninitialized_raises(
    memory_config: MemoryConfig,
) -> None:
    """Calling add() before initialize() raises RuntimeError."""
    from backend.services.memory_service import MemoryService

    svc = MemoryService(
        config=memory_config,
        llm_base_url="http://localhost:1234",
    )

    with pytest.raises(RuntimeError, match="not initialised"):
        await svc.add(content="test", scope="long_term")


@pytest.mark.asyncio
async def test_delete_uninitialized_raises(
    memory_config: MemoryConfig,
) -> None:
    """Calling delete() before initialize() raises RuntimeError."""
    from backend.services.memory_service import MemoryService

    svc = MemoryService(
        config=memory_config,
        llm_base_url="http://localhost:1234",
    )

    with pytest.raises(RuntimeError, match="not initialised"):
        await svc.delete("some-id")


@pytest.mark.asyncio
async def test_list_uninitialized_raises(
    memory_config: MemoryConfig,
) -> None:
    """Calling list() before initialize() raises RuntimeError."""
    from backend.services.memory_service import MemoryService

    svc = MemoryService(
        config=memory_config,
        llm_base_url="http://localhost:1234",
    )

    with pytest.raises(RuntimeError, match="not initialised"):
        await svc.list()


# ---------------------------------------------------------------------------
# Tests — close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """close() should close the DB connection and embedding client."""
    mock_conn = _make_conn()
    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)

    await svc.close()

    mock_conn.close.assert_awaited()
    mock_embedding_client.close.assert_awaited()


@pytest.mark.asyncio
async def test_close_idempotent(
    memory_config: MemoryConfig,
    mock_embedding_client: AsyncMock,
) -> None:
    """Calling close() twice should not raise."""
    mock_conn = _make_conn()
    svc = await _build_svc(memory_config, mock_embedding_client, mock_conn)

    await svc.close()
    await svc.close()  # second call is a no-op
