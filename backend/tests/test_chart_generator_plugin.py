"""Test ChartGeneratorPlugin — esecuzione tool LLM."""

import pytest
from unittest.mock import MagicMock
from backend.plugins.chart_generator.plugin import ChartGeneratorPlugin

VALID_OPTION = {"series": [{"type": "bar", "data": [1, 2, 3]}]}


@pytest.fixture
def mock_ctx(tmp_path):
    ctx = MagicMock()
    ctx.config.chart.enabled = True
    ctx.config.chart.max_option_chars = 10_000
    ctx.config.chart.max_charts = 1_000
    ctx.config.chart.chart_output_dir = str(tmp_path)
    return ctx


@pytest.fixture
async def plugin(mock_ctx):
    p = ChartGeneratorPlugin()
    await p.initialize(mock_ctx)
    return p


@pytest.mark.asyncio
async def test_generate_chart_success(plugin) -> None:
    result = await plugin.execute_tool("generate_chart", {
        "title": "Test Chart",
        "chart_type": "bar",
        "echarts_option": VALID_OPTION,
    }, context=None)
    assert result.success is True
    assert result.content_type == "application/vnd.alice.chart+json"
    import json
    payload = json.loads(result.content)
    assert "chart_id" in payload
    assert payload["chart_url"].startswith("/api/charts/")


@pytest.mark.asyncio
async def test_generate_chart_option_too_large(plugin) -> None:
    plugin.ctx.config.chart.max_option_chars = 10
    result = await plugin.execute_tool("generate_chart", {
        "title": "Big",
        "chart_type": "line",
        "echarts_option": {"data": list(range(10_000))},
    }, context=None)
    assert result.success is False
    assert "limite" in result.error_message.lower()


@pytest.mark.asyncio
async def test_list_charts_empty(plugin) -> None:
    result = await plugin.execute_tool("list_charts", {}, context=None)
    assert result.success is True
    import json
    data = json.loads(result.content)
    assert data["charts"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_chart_not_found(plugin) -> None:
    result = await plugin.execute_tool("get_chart", {"chart_id": "nonexistent"}, context=None)
    assert result.success is False


@pytest.mark.asyncio
async def test_delete_chart_success(plugin) -> None:
    gen = await plugin.execute_tool("generate_chart", {
        "title": "Da eliminare",
        "chart_type": "bar",
        "echarts_option": VALID_OPTION,
    }, context=None)
    assert gen.success is True
    import json
    chart_id = json.loads(gen.content)["chart_id"]
    result = await plugin.execute_tool("delete_chart", {"chart_id": chart_id}, context=None)
    assert result.success is True
    get = await plugin.execute_tool("get_chart", {"chart_id": chart_id}, context=None)
    assert get.success is False


@pytest.mark.asyncio
async def test_update_chart_success(plugin) -> None:
    gen = await plugin.execute_tool("generate_chart", {
        "title": "Originale",
        "chart_type": "bar",
        "echarts_option": VALID_OPTION,
    }, context=None)
    import json
    chart_id = json.loads(gen.content)["chart_id"]
    new_option = {"series": [{"type": "line", "data": [10, 20, 30]}]}
    result = await plugin.execute_tool("update_chart", {
        "chart_id": chart_id,
        "echarts_option": new_option,
    }, context=None)
    assert result.success is True


@pytest.mark.asyncio
async def test_plugin_disabled_returns_no_tools(mock_ctx) -> None:
    mock_ctx.config.chart.enabled = False
    p = ChartGeneratorPlugin()
    await p.initialize(mock_ctx)
    assert p.get_tools() == []


@pytest.mark.asyncio
async def test_disabled_plugin_execute_returns_error(mock_ctx) -> None:
    """execute_tool() returns ToolResult.error when plugin is disabled."""
    mock_ctx.config.chart.enabled = False
    p = ChartGeneratorPlugin()
    await p.initialize(mock_ctx)
    result = await p.execute_tool("generate_chart", {
        "title": "X", "chart_type": "bar", "echarts_option": VALID_OPTION,
    }, context=None)
    assert result.success is False
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(plugin) -> None:
    """execute_tool() returns ToolResult.error for unrecognised tool names."""
    result = await plugin.execute_tool("nonexistent_tool", {}, context=None)
    assert result.success is False
    assert "sconosciuto" in result.error_message.lower()


@pytest.mark.asyncio
async def test_max_charts_limit_reached(plugin) -> None:
    """generate_chart fails when max_charts limit is reached."""
    plugin.ctx.config.chart.max_charts = 1
    await plugin.execute_tool("generate_chart", {
        "title": "First", "chart_type": "bar", "echarts_option": VALID_OPTION,
    }, context=None)
    result = await plugin.execute_tool("generate_chart", {
        "title": "Second", "chart_type": "bar", "echarts_option": VALID_OPTION,
    }, context=None)
    assert result.success is False
    assert "limite" in result.error_message.lower()


@pytest.mark.asyncio
async def test_generate_chart_rejects_corrupted_llm_option(plugin) -> None:
    """Regression: l'LLM emette ``"name":"X`,type:"`` → series senza type.

    Prima del validator il plugin salvava la spec e ECharts renderizzava
    vuoto.  Ora deve rispondere con error parlante che permetta al
    modello di ritentare correttamente.
    """
    corrupted_option = {
        "xAxis": {"data": ["A", "B"]},
        "yAxis": {"type": "value"},
        "series": [
            {
                "data": [3.6, 40],
                "name": "Valore in Miliardi/Milioni`,type:",
            },
        ],
    }
    result = await plugin.execute_tool("generate_chart", {
        "title": "Vendite",
        "chart_type": "bar",
        "echarts_option": corrupted_option,
    }, context=None)
    assert result.success is False
    assert "sospetto" in result.error_message.lower()


@pytest.mark.asyncio
async def test_generate_chart_autofills_missing_series_type(plugin) -> None:
    """``series[].type`` mancante viene riempito dal ``chart_type`` top-level."""
    result = await plugin.execute_tool("generate_chart", {
        "title": "Auto",
        "chart_type": "bar",
        "echarts_option": {
            "xAxis": {"data": ["X"]},
            "yAxis": {"type": "value"},
            "series": [{"data": [42]}],
        },
    }, context=None)
    assert result.success is True


@pytest.mark.asyncio
async def test_update_chart_not_found(plugin) -> None:
    """update_chart returns error for a nonexistent chart_id."""
    result = await plugin.execute_tool("update_chart", {
        "chart_id": "nonexistent",
        "echarts_option": VALID_OPTION,
    }, context=None)
    assert result.success is False
    assert result.error_message is not None
