"""Tests for backend.plugins.continuum — ContinuumPlugin.

The plugin's :class:`ContinuumClient` is replaced by an ``AsyncMock`` so
tests exercise tool dispatch and request shaping without a live server.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.plugin_models import ExecutionContext
from backend.services.knowledge.continuum_client import ContinuumError


def _exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="s", conversation_id="c", execution_id="e",
    )


@pytest.fixture
def plugin():
    """Return a ContinuumPlugin with a mocked client injected."""
    from backend.plugins.continuum.plugin import ContinuumPlugin

    p = ContinuumPlugin()
    p._ctx = MagicMock()
    p._initialized = True
    p._client = AsyncMock()
    # invalidate_folder_cache is synchronous on the real client; keep it a
    # plain (non-awaitable) mock so call assertions are clean.
    p._client.invalidate_folder_cache = MagicMock()
    return p


@pytest.mark.asyncio
async def test_get_tools_namespacing_ready(plugin):
    names = {t.name for t in plugin.get_tools()}
    assert {"list_folders", "create_folder", "get_database", "query_database"} <= names


@pytest.mark.asyncio
async def test_list_folders_returns_forest(plugin):
    plugin._client.request.return_value = [{"id": "1", "slug": "a"}]
    res = await plugin.execute_tool("list_folders", {}, _exec_ctx())
    assert res.success
    assert res.content["count"] == 1
    plugin._client.request.assert_awaited_with("GET", "/folders")


@pytest.mark.asyncio
async def test_create_folder_maps_parent_id(plugin):
    plugin._client.request.return_value = {"id": "f1"}
    await plugin.execute_tool(
        "create_folder", {"name": "Work", "parent_id": "p1"}, _exec_ctx(),
    )
    plugin._client.request.assert_awaited_with(
        "POST", "/folders", json={"name": "Work", "parentId": "p1"},
    )


@pytest.mark.asyncio
async def test_create_folder_invalidates_folder_cache(plugin):
    """A new folder must drop the cached path↔id map so the next note
    placement resolves it instead of falling back to root within the TTL."""
    plugin._client.request.return_value = {"id": "f1"}
    await plugin.execute_tool("create_folder", {"name": "Work"}, _exec_ctx())
    plugin._client.invalidate_folder_cache.assert_called_once()


@pytest.mark.asyncio
async def test_create_folder_requires_name(plugin):
    res = await plugin.execute_tool("create_folder", {"name": "  "}, _exec_ctx())
    assert not res.success


@pytest.mark.asyncio
async def test_query_database_requires_id(plugin):
    res = await plugin.execute_tool("query_database", {}, _exec_ctx())
    assert not res.success


@pytest.mark.asyncio
async def test_query_database_calls_endpoint(plugin):
    plugin._client.request.return_value = {"rows": []}
    await plugin.execute_tool(
        "query_database",
        {
            "database_id": "db1",
            "config": {"sort": []},
            "pagination": {"offset": 0, "limit": 10},
        },
        _exec_ctx(),
    )
    plugin._client.request.assert_awaited_with(
        "POST",
        "/databases/db1/query",
        json={"config": {"sort": []}, "pagination": {"offset": 0, "limit": 10}},
    )


@pytest.mark.asyncio
async def test_get_database_calls_bundle_endpoint(plugin):
    plugin._client.request.return_value = {"database": {"id": "db1"}, "schema": []}
    await plugin.execute_tool("get_database", {"database_id": "db1"}, _exec_ctx())
    plugin._client.request.assert_awaited_with("GET", "/databases/db1")


@pytest.mark.asyncio
async def test_graph_query_passes_options(plugin):
    plugin._client.request.return_value = {"nodes": [], "edges": []}
    await plugin.execute_tool(
        "graph_query",
        {
            "limit": 50,
            "include_metrics": True,
            "filter": {"type": "group", "id": "root", "combinator": "and", "children": []},
            "edge_sources": {
                "includeLinks": True,
                "allRelationProperties": False,
                "relationPropertyKeys": ["related"],
            },
            "include_properties": ["status"],
        },
        _exec_ctx(),
    )
    plugin._client.request.assert_awaited_with(
        "POST",
        "/graph/query",
        json={
            "filter": {"type": "group", "id": "root", "combinator": "and", "children": []},
            "edgeSources": {
                "includeLinks": True,
                "allRelationProperties": False,
                "relationPropertyKeys": ["related"],
            },
            "includeProperties": ["status"],
            "includeMetrics": True,
        },
    )


@pytest.mark.asyncio
async def test_unknown_tool_errors(plugin):
    res = await plugin.execute_tool("nope", {}, _exec_ctx())
    assert not res.success


@pytest.mark.asyncio
async def test_continuum_error_surfaced_as_tool_error(plugin):
    plugin._client.request.side_effect = ContinuumError("boom")
    res = await plugin.execute_tool("list_kinds", {}, _exec_ctx())
    assert not res.success
    assert "Continuum error" in res.error_message


@pytest.mark.asyncio
async def test_disabled_client_returns_error(plugin):
    plugin._client = None
    res = await plugin.execute_tool("list_folders", {}, _exec_ctx())
    assert not res.success


@pytest.mark.asyncio
async def test_block_tools_advertised_as_client_executed(plugin):
    """The live block tools are exposed and flagged client_execution."""
    block_names = {
        "list_blocks", "list_block_types", "list_block_commands",
        "insert_block", "run_block_command", "update_block",
        "delete_block", "move_block", "turn_block_into", "duplicate_block",
    }
    database_names = {
        "list_database_blocks",
        "run_database_action",
        "run_database_destructive_action",
    }
    graph_names = {"graph_get_state", "run_graph_action"}
    tools = {t.name: t for t in plugin.get_tools()}
    assert block_names <= set(tools)
    assert database_names <= set(tools)
    assert graph_names <= set(tools)
    assert "collapse_heading_section" not in tools
    assert "collapse_all_heading_sections" not in tools
    for name in block_names | database_names | graph_names:
        assert tools[name].client_execution is True
    for name in block_names | {"list_database_blocks", "run_database_action"} | graph_names:
        assert tools[name].requires_confirmation is False
    assert tools["run_database_destructive_action"].requires_confirmation is True
    assert "scope" in tools["turn_block_into"].parameters["properties"]


@pytest.mark.asyncio
async def test_block_tool_not_executed_server_side(plugin):
    """Client-executed block tools defensively error if run server-side."""
    res = await plugin.execute_tool("run_graph_action", {}, _exec_ctx())
    assert not res.success
    # The mocked HTTP client must NOT have been called.
    plugin._client.request.assert_not_awaited()
