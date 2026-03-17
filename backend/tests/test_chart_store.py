"""Test ChartStore — operazioni CRUD su file JSON."""

import pytest
from pathlib import Path
from backend.plugins.chart_generator.chart_store import ChartStore
from backend.plugins.chart_generator.models import ChartSpec


@pytest.fixture
def store(tmp_path: Path) -> ChartStore:
    return ChartStore(chart_output_dir=tmp_path)


@pytest.fixture
def sample_spec() -> ChartSpec:
    return ChartSpec(
        chart_id="test-uuid-001",
        title="Vendite Q1",
        chart_type="bar",
        description="Dati di test",
        echarts_option={
            "xAxis": {"type": "category", "data": ["Gen", "Feb", "Mar"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [150, 230, 180]}],
        },
    )


@pytest.mark.asyncio
async def test_save_and_load(store: ChartStore, sample_spec: ChartSpec) -> None:
    await store.save(sample_spec)
    loaded = await store.load(sample_spec.chart_id)
    assert loaded is not None
    assert loaded.title == "Vendite Q1"
    assert loaded.echarts_option["series"][0]["type"] == "bar"


@pytest.mark.asyncio
async def test_load_nonexistent_returns_none(store: ChartStore) -> None:
    assert await store.load("nonexistent-id") is None


@pytest.mark.asyncio
async def test_delete_existing(store: ChartStore, sample_spec: ChartSpec) -> None:
    await store.save(sample_spec)
    assert await store.delete(sample_spec.chart_id) is True
    assert await store.load(sample_spec.chart_id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(store: ChartStore) -> None:
    assert await store.delete("ghost-id") is False


@pytest.mark.asyncio
async def test_list_and_count(store: ChartStore, sample_spec: ChartSpec) -> None:
    for i in range(3):
        spec = sample_spec.model_copy(update={"chart_id": f"id-{i}", "title": f"Chart {i}"})
        await store.save(spec)
    assert await store.count() == 3
    items = await store.list(limit=2, offset=0)
    assert len(items) == 2


@pytest.mark.asyncio
async def test_path_sanitization(store: ChartStore, sample_spec: ChartSpec) -> None:
    spec = sample_spec.model_copy(update={"chart_id": "../../../etc/passwd"})
    await store.save(spec)
    sanitized_path = store._path("../../../etc/passwd")
    assert sanitized_path.parent == store._dir
    assert sanitized_path.exists()
