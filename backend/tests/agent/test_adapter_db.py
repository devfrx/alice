"""Test ``SqlModelPersistence`` — ``PersistencePort`` sopra SQLModel/SQLite.

Copre le tre invarianti chiave del binding (spec Fase 1):

- §6.1: assistant/tool rows condividono lo stesso ``call_id`` normalizzato.
- §6.15: ``checkpoint()`` è l'UNICO punto di ``commit()`` — ``save_*`` fanno
  solo ``flush()``, quindi un ``rollback()`` prima del checkpoint deve poter
  annullare le righe, mentre uno dopo il checkpoint non le tocca più.
- §6.4.11: ``archive_compacted`` esclude gli ID archiviati da
  ``load_history`` e vi inserisce il messaggio di riassunto.
"""

from __future__ import annotations

import json
import uuid

from sqlmodel import select

from backend.db.models import Conversation, Message
from backend.services.agent.adapters.db import SqlModelPersistence
from backend.services.agent.models import ToolInvocation


async def test_assistant_and_tool_rows_share_call_id(db_session, conv: Conversation) -> None:
    """save_assistant_step + save_tool_result condividono call_z (§6.1)."""
    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=None, version_group_id=None, version_index=None,
    )
    call = ToolInvocation(call_id="call_z", name="t", args={}, raw_args="{}")
    await p.save_assistant_step(content="", thinking="", tool_calls=(call,))
    await p.save_tool_result(call=call, content="ok", status="ok")
    await p.checkpoint()

    rows = (
        await db_session.exec(select(Message).order_by(Message.created_at))
    ).all()
    assert rows[-2].role == "assistant"
    assert "call_z" in json.dumps(rows[-2].tool_calls)
    assert rows[-1].role == "tool" and rows[-1].tool_call_id == "call_z"


async def test_archive_compacted_excludes_from_history(db_session, conv: Conversation) -> None:
    """archive_compacted esclude gli ID archiviati e inserisce il summary (§6.4.11)."""
    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=None, version_group_id=None, version_index=None,
    )
    for i in range(3):
        db_session.add(
            Message(conversation_id=conv.id, role="user", content=f"m{i}")
        )
    await db_session.flush()
    rows = (
        await db_session.exec(select(Message).order_by(Message.created_at))
    ).all()
    ids = [str(r.id) for r in rows[:2]]

    await p.archive_compacted(summary_text="SUMMARY", upto_message_ids=ids)
    await p.checkpoint()

    history = await p.load_history()
    contents = [m.get("content") for m in history]
    assert "m0" not in contents and "m1" not in contents
    assert "m2" in contents
    assert any("SUMMARY" in str(c) for c in contents)


async def test_checkpoint_commits_and_survives_rollback(
    db_session, conv: Conversation,
) -> None:
    """checkpoint() è l'unico commit: dopo, un rollback() non perde righe (§6.15)."""
    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=None, version_group_id=None, version_index=None,
    )
    msg_id = await p.save_assistant_step(content="hi", thinking="", tool_calls=())

    # Before checkpoint(): only flush() happened, a rollback discards the row.
    await db_session.rollback()
    rows = (
        await db_session.exec(
            select(Message).where(Message.id == uuid.UUID(msg_id))
        )
    ).all()
    assert rows == []

    # Re-save and this time checkpoint() -> commit(); a later rollback is a
    # no-op on already-committed data.
    msg_id2 = await p.save_assistant_step(content="hi again", thinking="", tool_calls=())
    await p.checkpoint()
    await db_session.rollback()
    rows2 = (
        await db_session.exec(
            select(Message).where(Message.id == uuid.UUID(msg_id2))
        )
    ).all()
    assert len(rows2) == 1
    assert rows2[0].content == "hi again"
