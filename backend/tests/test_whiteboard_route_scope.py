"""GET /api/whiteboards count must respect the conversation_id filter."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_list_passes_conversation_id_to_count(monkeypatch):
    from backend.api.routes import whiteboards as wb

    store = MagicMock()
    store.list = AsyncMock(return_value=[])
    store.count = AsyncMock(return_value=0)

    request = MagicMock()
    request.app.state.context.db = None  # skip title resolution

    monkeypatch.setattr(wb, "_get_store", lambda _req: store)

    await wb.list_whiteboards(request, conversation_id="conv-1", limit=50, offset=0)
    store.count.assert_awaited_once_with(conversation_id="conv-1")
