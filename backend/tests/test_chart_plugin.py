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
    assert "non trovato" in (res.error_message or "")


async def test_disabled_plugin_exposes_no_tools_and_errors(registry) -> None:
    p = ChartGeneratorPlugin()
    stub = _StubCtx(registry)
    stub.config.chart = ChartConfig(enabled=False)
    p._ctx = stub
    assert p.get_tools() == []
    res = await p.execute_tool("generate_chart", {}, _exec_ctx())
    assert not res.success


async def test_unknown_tool_returns_error(plugin) -> None:
    res = await plugin.execute_tool("nope", {}, _exec_ctx())
    assert not res.success


async def test_generate_chart_rejects_oversized_option(plugin) -> None:
    big_option = {"series": [{"type": "bar", "data": ["x" * 20_000]}]}
    res = await plugin.execute_tool(
        "generate_chart",
        {"title": "T", "chart_type": "bar", "echarts_option": big_option},
        _exec_ctx(),
    )
    assert not res.success
    assert "limite" in (res.error_message or "")


async def test_generate_chart_respects_max_charts(plugin) -> None:
    plugin.ctx.config.chart.max_charts = 1
    gen1 = await plugin.execute_tool(
        "generate_chart",
        {"title": "T1", "chart_type": "bar", "echarts_option": _OPTION},
        _exec_ctx(),
    )
    assert gen1.success
    gen2 = await plugin.execute_tool(
        "generate_chart",
        {"title": "T2", "chart_type": "bar", "echarts_option": _OPTION},
        _exec_ctx(),
    )
    assert not gen2.success
    assert "Limite massimo" in (gen2.error_message or "")


async def test_update_chart_unknown_uuid_is_clean_error(plugin) -> None:
    res = await plugin.execute_tool(
        "update_chart",
        {"chart_id": str(uuid.uuid4()), "echarts_option": _OPTION},
        _exec_ctx(),
    )
    assert not res.success
    assert "non trovato" in (res.error_message or "")


async def test_list_charts_empty(plugin) -> None:
    res = await plugin.execute_tool("list_charts", {}, _exec_ctx())
    assert res.success
    payload = json.loads(res.content)
    assert payload["total"] == 0
    assert payload["charts"] == []


async def test_get_chart_returns_spec(plugin) -> None:
    gen = await plugin.execute_tool(
        "generate_chart",
        {"title": "T", "chart_type": "bar", "echarts_option": _OPTION},
        _exec_ctx(),
    )
    aid = json.loads(gen.content)["chart_id"]
    res = await plugin.execute_tool("get_chart", {"chart_id": aid}, _exec_ctx())
    assert res.success
    spec = json.loads(res.content)
    assert spec["chart_id"] == aid
    assert spec["echarts_option"]["series"][0]["type"] == "bar"


async def test_generate_chart_surfaces_validator_error(plugin) -> None:
    bad_option = {"series": [{"type": "nonsense", "data": [1, 2]}]}
    res = await plugin.execute_tool(
        "generate_chart",
        {"title": "T", "chart_type": "bar", "echarts_option": bad_option},
        _exec_ctx(),
    )
    assert not res.success
    assert res.error_message
