"""Events-route ingestion of command.manifest / command.result (Fase 7)."""

from __future__ import annotations

from typing import Any

import pytest

from backend.api.routes.events import _handle_command_frame


class _FakeBridge:
    def __init__(self) -> None:
        self.manifests: list[list[dict[str, Any]]] = []
        self.resolved: list[tuple[str, dict[str, Any]]] = []

    async def set_manifest(self, entries: list[dict[str, Any]]) -> None:
        self.manifests.append(entries)

    def resolve(self, correlation_id: str, payload: dict[str, Any]) -> None:
        self.resolved.append((correlation_id, payload))


class _FakeCtx:
    def __init__(self) -> None:
        self.command_bridge_service = _FakeBridge()


@pytest.mark.asyncio
async def test_manifest_frame_is_validated_and_ingested() -> None:
    ctx = _FakeCtx()
    await _handle_command_frame(ctx, {
        "type": "command.manifest",
        "commands": [{
            "name": "view.switch",
            "description": "Switch view",
            "capability": "navigation",
            "args_schema": {"type": "object"},
        }],
    })
    assert len(ctx.command_bridge_service.manifests) == 1
    assert ctx.command_bridge_service.manifests[0][0]["name"] == "view.switch"


@pytest.mark.asyncio
async def test_result_frame_resolves_by_correlation_id() -> None:
    ctx = _FakeCtx()
    await _handle_command_frame(ctx, {
        "type": "command.result",
        "correlation_id": "c-9",
        "ok": True,
        "result": {"done": True},
    })
    assert ctx.command_bridge_service.resolved == [
        ("c-9", {"ok": True, "result": {"done": True}, "error": None}),
    ]


@pytest.mark.asyncio
async def test_invalid_frame_is_dropped_silently() -> None:
    ctx = _FakeCtx()
    await _handle_command_frame(ctx, {"type": "command.result", "ok": "not-a-bool"})
    await _handle_command_frame(ctx, {"type": "command.manifest", "commands": "nope"})
    assert ctx.command_bridge_service.resolved == []
    assert ctx.command_bridge_service.manifests == []


@pytest.mark.asyncio
async def test_result_without_correlation_id_is_dropped() -> None:
    ctx = _FakeCtx()
    await _handle_command_frame(ctx, {"type": "command.result", "ok": True})
    assert ctx.command_bridge_service.resolved == []


@pytest.mark.asyncio
async def test_missing_bridge_is_noop() -> None:
    class _EmptyCtx:
        pass

    await _handle_command_frame(_EmptyCtx(), {"type": "command.result", "ok": True})
