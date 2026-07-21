"""Test ``SqlModelPersistence`` — ``PersistencePort`` sopra SQLModel/SQLite.

Copre le invarianti chiave del binding (spec Fase 1):

- §6.1: assistant/tool rows condividono lo stesso ``call_id`` normalizzato.
- §6.3: ``load_history`` preserva l'ordine ``created_at`` indipendentemente
  dall'ordine di inserimento.
- §6.10: ``version_group_id``/``version_index`` (assegnati fuori dal motore)
  sono applicati invariati alla riga ``Message`` assistant.
- §6.11: ``register_artifacts`` delega ad ``ArtifactRegistry`` coi parametri
  corretti (``tool_call_id``, ``message_id`` risolto, ``payload``).
- §6.15: ``checkpoint()`` è l'UNICO punto di ``commit()`` — ``save_*`` fanno
  solo ``flush()``, quindi un ``rollback()`` prima del checkpoint deve poter
  annullare le righe, mentre uno dopo il checkpoint non le tocca più.
- §6.4.11: ``archive_compacted`` esclude gli ID archiviati da
  ``load_history`` e vi inserisce il messaggio di riassunto.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any, cast

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.models import Conversation, Message
from backend.services.agent import ports
from backend.services.agent.adapters.db import SqlModelPersistence
from backend.services.agent.models import ToolInvocation
from backend.services.artifacts.registry import ArtifactRegistry


class _StubArtifactRegistry:
    """Double locale: registra le chiamate, non tocca il DB reale."""

    def __init__(self, artifact_id: str | None = "art-1") -> None:
        self.calls: list[dict[str, Any]] = []
        self.image_calls: list[dict[str, Any]] = []
        self._artifact_id = artifact_id

    async def register_from_tool_result(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._artifact_id is None:
            return None
        from types import SimpleNamespace
        return SimpleNamespace(id=self._artifact_id)

    async def create_image_artifact(self, **kwargs: Any) -> Any:
        self.image_calls.append(kwargs)
        if self._artifact_id is None:
            return None
        from types import SimpleNamespace
        return SimpleNamespace(id=self._artifact_id)


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


async def test_save_final_message_writes_row_and_returns_id(
    db_session, conv: Conversation,
) -> None:
    """save_final_message scrive la riga assistant finale (role/content/version)
    e ritorna l'id; ``usage`` solo con cost>0, ``token_count`` solo con
    input_tokens>0 (carry #2)."""
    vg = str(uuid.uuid4())
    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=None, version_group_id=vg, version_index=2,
    )
    msg_id = await p.save_final_message(
        content="risposta finale", thinking="ragiono",
        input_tokens=120, output_tokens=15, cost=0.004,
    )
    await p.checkpoint()

    row = (
        await db_session.exec(
            select(Message).where(Message.id == uuid.UUID(msg_id))
        )
    ).one()
    assert row.role == "assistant"
    assert row.content == "risposta finale"
    assert row.thinking_content == "ragiono"
    assert str(row.version_group_id) == vg
    assert row.version_index == 2
    assert row.token_count == 120
    assert row.usage == {
        "prompt_tokens": 120, "completion_tokens": 15, "cost": round(0.004, 8),
    }


async def test_save_final_message_omits_usage_and_token_count_when_zero(
    db_session, conv: Conversation,
) -> None:
    """Nessun ``usage`` senza costo e nessun ``token_count`` senza input_tokens."""
    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=None, version_group_id=None, version_index=None,
    )
    msg_id = await p.save_final_message(
        content="senza token", thinking="",
        input_tokens=0, output_tokens=0, cost=0.0,
    )
    await p.checkpoint()

    row = (
        await db_session.exec(
            select(Message).where(Message.id == uuid.UUID(msg_id))
        )
    ).one()
    assert row.token_count is None
    assert row.usage is None
    assert row.thinking_content is None
    assert row.version_index == 0


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


async def test_load_history_preserves_created_at_order(
    db_session, conv: Conversation,
) -> None:
    """``load_history`` ordina per ``created_at``, non per ordine di INSERT
    (§6.3: la history ricostruita preserva l'ordine)."""
    base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    later = Message(
        conversation_id=conv.id, role="user", content="later",
        created_at=base + dt.timedelta(seconds=10),
    )
    earlier = Message(
        conversation_id=conv.id, role="user", content="earlier", created_at=base,
    )
    # Inserite fuori ordine: "later" per prima.
    db_session.add(later)
    db_session.add(earlier)
    await db_session.flush()

    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=None, version_group_id=None, version_index=None,
    )
    history = await p.load_history()
    contents = [m["content"] for m in history]
    assert contents.index("earlier") < contents.index("later")


async def test_version_group_and_index_applied_to_assistant_message(
    db_session, conv: Conversation,
) -> None:
    """``version_group_id``/``version_index`` (assegnati fuori dal motore,
    §6.10) sono applicati invariati alla riga ``Message`` assistant."""
    vg = str(uuid.uuid4())
    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=None, version_group_id=vg, version_index=3,
    )
    await p.save_assistant_step(content="hi", thinking="", tool_calls=())
    await p.checkpoint()

    rows = (
        await db_session.exec(select(Message).order_by(Message.created_at))
    ).all()
    assert str(rows[-1].version_group_id) == vg
    assert rows[-1].version_index == 3


async def test_register_artifacts_delegates_to_registry_with_call_id(
    db_session, conv: Conversation,
) -> None:
    """``register_artifacts`` (§6.11) delega ad ``ArtifactRegistry`` passando
    ``tool_call_id``/``tool_name``/``payload`` e il ``message_id`` risolto
    dal tool result appena salvato; no-op se il tool ha fallito o non porta
    payload strutturato."""
    registry = _StubArtifactRegistry(artifact_id="art-1")
    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=registry, version_group_id=None, version_index=None,
    )
    call = ToolInvocation(call_id="call_art", name="cad_generate", args={}, raw_args="{}")
    await p.save_tool_result(call=call, content="ok", status="ok")
    await p.checkpoint()

    artifact_id = await p.register_artifacts(
        call=call,
        output=ports.ToolExecutionOutput(ok=True, content="ok", payload={"a": 1}),
    )

    assert artifact_id == "art-1"
    assert len(registry.calls) == 1
    assert registry.calls[0]["tool_call_id"] == "call_art"
    assert registry.calls[0]["tool_name"] == "cad_generate"
    assert registry.calls[0]["payload"] == {"a": 1}
    assert registry.calls[0]["message_id"] is not None

    # Nessun payload strutturato -> no-op, nessuna chiamata al registry.
    no_payload = await p.register_artifacts(
        call=call, output=ports.ToolExecutionOutput(ok=True, content="ok"),
    )
    assert no_payload is None
    assert len(registry.calls) == 1


async def test_register_artifacts_images_create_image_artifact(
    db_session: AsyncSession, conv: Conversation,
) -> None:
    """T16: ``output.images`` popolato -> ``create_image_artifact`` col base64
    della PRIMA immagine e ritorno dell'id; il ramo payload NON viene toccato
    anche se il payload è presente (precedenza al ramo immagini)."""
    registry = _StubArtifactRegistry(artifact_id="img-1")
    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=cast(ArtifactRegistry, registry),
        version_group_id=None, version_index=None,
    )
    call = ToolInvocation(call_id="call_img", name="browser_shot", args={}, raw_args="{}")
    await p.save_tool_result(call=call, content="[image]", status="ok")
    await p.checkpoint()

    artifact_id = await p.register_artifacts(
        call=call,
        output=ports.ToolExecutionOutput(
            ok=True, content="[image]",
            images=(
                ports.ToolImage(mime="image/png", base64_data="QUJD"),
                ports.ToolImage(mime="image/jpeg", base64_data="REVG"),
            ),
            payload={"ignored": True},
            content_type="image/png",
        ),
    )

    assert artifact_id == "img-1"
    assert registry.calls == []  # payload branch untouched
    assert len(registry.image_calls) == 1
    kwargs = registry.image_calls[0]
    assert kwargs["tool_call_id"] == "call_img"
    assert kwargs["tool_name"] == "browser_shot"
    assert kwargs["mime"] == "image/png"
    assert kwargs["base64_data"] == "QUJD"  # solo la prima immagine
    assert kwargs["message_id"] is not None


async def test_register_artifacts_images_none_paths(
    db_session: AsyncSession, conv: Conversation,
) -> None:
    """Guardie: ok=False (anche con immagini) -> None; images+payload vuoti ->
    None; registry che scarta il base64 -> None senza eccezioni."""
    registry = _StubArtifactRegistry(artifact_id=None)
    p = SqlModelPersistence(
        session=db_session, conversation_id=str(conv.id),
        artifact_registry=cast(ArtifactRegistry, registry),
        version_group_id=None, version_index=None,
    )
    call = ToolInvocation(call_id="c1", name="t", args={}, raw_args="{}")

    failed = await p.register_artifacts(
        call=call,
        output=ports.ToolExecutionOutput(
            ok=False, content="err", error="boom",
            images=(ports.ToolImage(mime="image/png", base64_data="QUJD"),),
        ),
    )
    assert failed is None
    assert registry.image_calls == []  # guardia ok=False a monte

    empty = await p.register_artifacts(
        call=call, output=ports.ToolExecutionOutput(ok=True, content="ok"),
    )
    assert empty is None

    # Registry ritorna None (base64 scartato) -> None propagato, no raise.
    rejected = await p.register_artifacts(
        call=call,
        output=ports.ToolExecutionOutput(
            ok=True, content="[image]",
            images=(ports.ToolImage(mime="image/png", base64_data="x"),),
        ),
    )
    assert rejected is None
    assert len(registry.image_calls) == 1
