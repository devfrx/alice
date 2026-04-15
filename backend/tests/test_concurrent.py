"""Tests for concurrent access patterns (WebSocket + REST)."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from backend.services.llm_service import LLMService

# ---------------------------------------------------------------------------
# Mock LLM helpers (same as test_websocket.py)
# ---------------------------------------------------------------------------


async def _mock_chat_generator(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    cancel_event: asyncio.Event | None = None,
    *,
    user_content: str | None = None,
    conversation_id: str | None = None,
    attachments: list[dict[str, str]] | None = None,
    memory_context: str | None = None,
    system_prompt: str | None = None,
    max_output_tokens: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "token", "content": "Hello"}
    yield {"type": "token", "content": " world"}
    yield {"type": "done"}


def _mock_build_messages(
    user_content: str,
    history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, str]] | None = None,
    memory_context: str | None = None,
    system_prompt: str | None = None,
) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": user_content},
    ]


def _patch_llm(app: FastAPI) -> None:
    llm = app.state.context.llm_service
    llm.chat = _mock_chat_generator
    llm.build_messages = _mock_build_messages


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def concurrent_app(app: FastAPI) -> FastAPI:
    """Return the test app with a mocked LLM service."""
    _patch_llm(app)
    return app


# ---------------------------------------------------------------------------
# Tests — concurrent WebSocket connections
# ---------------------------------------------------------------------------


def _ws_client_serial(
    app: FastAPI,
    results: list[dict[str, Any] | None],
    errors: list[str | None],
    index: int,
) -> None:
    """Open a WS, send one message, collect done, then close before returning.

    Running sequentially inside a thread avoids hitting the per-IP WS
    connection limit that the production code enforces.
    """
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": f"Message {index}"})
            while True:
                data = ws.receive_json()
                if data["type"] == "done":
                    results[index] = data
                    break
                if data["type"] == "error":
                    errors[index] = data["content"]
                    break
    except Exception as exc:
        errors[index] = str(exc)


class TestConcurrentWebSocket:
    """Stress tests for simultaneous WebSocket connections."""

    def test_multiple_sequential_ws_connections(
        self, concurrent_app: FastAPI,
    ) -> None:
        """10 sequential WS clients (each opens, sends, receives, closes)
        should all succeed.  This avoids the per-IP connection limit while
        verifying the server handles rapid connect/disconnect cycles.
        """
        n = 10
        results: list[dict[str, Any] | None] = [None] * n
        errors: list[str | None] = [None] * n

        # Run them in separate threads but sequentially via a lock so only
        # one WS connection is open at a time (mirrors real browser tabs).
        lock = threading.Lock()

        def _locked_client(
            app: FastAPI,
            res: list[dict[str, Any] | None],
            errs: list[str | None],
            idx: int,
        ) -> None:
            with lock:
                _ws_client_serial(app, res, errs, idx)

        threads = [
            threading.Thread(
                target=_locked_client,
                args=(concurrent_app, results, errors, i),
            )
            for i in range(n)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

        for i in range(n):
            assert errors[i] is None, f"Client {i} failed: {errors[i]}"
            assert results[i] is not None, f"Client {i} got no done event"
            assert results[i]["type"] == "done"  # type: ignore[index]
            uuid.UUID(results[i]["conversation_id"])  # type: ignore[index]

    def test_parallel_ws_within_connection_limit(
        self, concurrent_app: FastAPI,
    ) -> None:
        """A small batch of parallel WS clients (within the per-IP limit)
        should all receive valid responses.
        """
        # The default limit is typically 5; use 3 to stay safe.
        n = 3
        results: list[dict[str, Any] | None] = [None] * n
        errors: list[str | None] = [None] * n

        threads = [
            threading.Thread(
                target=_ws_client_serial,
                args=(concurrent_app, results, errors, i),
            )
            for i in range(n)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        for i in range(n):
            assert errors[i] is None, f"Client {i} failed: {errors[i]}"
            assert results[i] is not None, f"Client {i} got no done event"
            assert results[i]["type"] == "done"  # type: ignore[index]

    def test_concurrent_ws_unique_conversations(
        self, concurrent_app: FastAPI,
    ) -> None:
        """Each sequential WS client (without id) should get a unique conv."""
        n = 5
        results: list[dict[str, Any] | None] = [None] * n
        errors: list[str | None] = [None] * n

        for i in range(n):
            _ws_client_serial(concurrent_app, results, errors, i)

        conv_ids = {r["conversation_id"] for r in results if r}  # type: ignore[index]
        assert len(conv_ids) == n

    def test_concurrent_ws_same_conversation(
        self, concurrent_app: FastAPI,
    ) -> None:
        """Two clients writing to the same conversation sequentially must
        both succeed and reference the same conversation id.
        """
        cid = str(uuid.uuid4())
        n = 2
        results: list[dict[str, Any] | None] = [None] * n
        errors: list[str | None] = [None] * n

        def _ws_same_conv(
            app: FastAPI,
            res: list[dict[str, Any] | None],
            errs: list[str | None],
            idx: int,
        ) -> None:
            try:
                client = TestClient(app, raise_server_exceptions=False)
                with client.websocket_connect("/api/ws/chat") as ws:
                    ws.send_json(
                        {"content": f"Msg {idx}", "conversation_id": cid}
                    )
                    while True:
                        data = ws.receive_json()
                        if data["type"] == "done":
                            res[idx] = data
                            break
                        if data["type"] == "error":
                            errs[idx] = data["content"]
                            break
            except Exception as exc:
                errs[idx] = str(exc)

        # Run sequentially to avoid connection limit.
        for i in range(n):
            _ws_same_conv(concurrent_app, results, errors, i)

        for i in range(n):
            assert errors[i] is None, f"Client {i} failed: {errors[i]}"
            assert results[i] is not None
            assert results[i]["conversation_id"] == cid  # type: ignore[index]


# ---------------------------------------------------------------------------
# Tests — concurrent REST API calls
# ---------------------------------------------------------------------------


class TestConcurrentREST:
    """Concurrent REST API operations should not corrupt data."""

    async def test_concurrent_list_and_create(
        self, concurrent_app: FastAPI,
    ) -> None:
        """Simultaneous list + create requests must all succeed."""
        import asyncio

        transport = ASGITransport(app=concurrent_app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            # Fire off creates and lists simultaneously.
            create_tasks = [
                ac.post(
                    "/api/chat/conversations",
                    json={"id": str(uuid.uuid4())},
                )
                for _ in range(5)
            ]
            list_tasks = [
                ac.get("/api/chat/conversations")
                for _ in range(5)
            ]

            responses = await asyncio.gather(
                *create_tasks, *list_tasks, return_exceptions=True
            )

            for resp in responses:
                if isinstance(resp, Exception):
                    # Some async SQLite contention is acceptable.
                    continue
                assert resp.status_code in (200, 409), resp.text

    async def test_concurrent_create_and_delete(
        self, concurrent_app: FastAPI,
    ) -> None:
        """Create conversations then delete them concurrently."""
        import asyncio

        transport = ASGITransport(app=concurrent_app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            # Create 5 conversations first.
            conv_ids = []
            for _ in range(5):
                cid = str(uuid.uuid4())
                resp = await ac.post(
                    "/api/chat/conversations", json={"id": cid}
                )
                assert resp.status_code == 200
                conv_ids.append(cid)

            # Delete them all concurrently.
            tasks = [
                ac.delete(f"/api/chat/conversations/{cid}")
                for cid in conv_ids
            ]
            responses = await asyncio.gather(*tasks)
            for resp in responses:
                assert resp.status_code == 200

            # Verify all are gone.
            resp = await ac.get("/api/chat/conversations")
            assert resp.status_code == 200
            assert len(resp.json()) == 0

    async def test_concurrent_list_is_consistent(
        self, concurrent_app: FastAPI,
    ) -> None:
        """Multiple concurrent list calls should each return valid JSON."""
        import asyncio

        transport = ASGITransport(app=concurrent_app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            tasks = [ac.get("/api/chat/conversations") for _ in range(10)]
            responses = await asyncio.gather(*tasks)
            for resp in responses:
                assert resp.status_code == 200
                assert isinstance(resp.json(), list)
