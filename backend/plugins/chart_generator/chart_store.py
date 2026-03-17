"""ChartStore — persistenza JSON per i grafici generati dall'agente."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

from .models import ChartListItem, ChartSpec


class ChartStore:
    """Gestisce il salvataggio e il recupero dei grafici su disco."""

    def __init__(self, chart_output_dir: str | Path) -> None:
        self._dir = Path(chart_output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    async def save(self, spec: ChartSpec) -> None:
        await asyncio.to_thread(self._write, spec)

    async def load(self, chart_id: str) -> ChartSpec | None:
        return await asyncio.to_thread(self._read, chart_id)

    async def update(self, chart_id: str, new_spec: ChartSpec) -> bool:
        if new_spec.chart_id != chart_id:
            raise ValueError(
                f"chart_id mismatch: atteso {chart_id!r}, ricevuto {new_spec.chart_id!r}"
            )
        path = self._path(chart_id)
        if not await asyncio.to_thread(path.exists):
            return False
        await asyncio.to_thread(self._write, new_spec)
        return True

    async def delete(self, chart_id: str) -> bool:
        path = self._path(chart_id)
        deleted = await asyncio.to_thread(self._unlink, path)
        if deleted:
            logger.info(f"Chart eliminato: {chart_id}")
        return deleted

    async def list(self, limit: int = 50, offset: int = 0) -> list[ChartListItem]:
        return await asyncio.to_thread(self._list_sync, limit, offset)

    async def count(self) -> int:
        return await asyncio.to_thread(self._count_sync)

    def _path(self, chart_id: str) -> Path:
        safe_id = "".join(c for c in chart_id if c.isalnum() or c == "-")
        if not safe_id:
            raise ValueError(f"chart_id non valido (nessun carattere sicuro): {chart_id!r}")
        return self._dir / f"{safe_id}.json"

    def _write(self, spec: ChartSpec) -> None:
        path = self._path(spec.chart_id)
        path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    def _read(self, chart_id: str) -> ChartSpec | None:
        path = self._path(chart_id)
        if not path.exists():
            return None
        try:
            return ChartSpec.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception(f"Errore lettura chart {chart_id}")
            return None

    def _unlink(self, path: Path) -> bool:
        if path.exists():
            path.unlink()
            return True
        return False

    def _list_sync(self, limit: int, offset: int) -> list[ChartListItem]:
        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except FileNotFoundError:
                return 0.0

        files = sorted(self._dir.glob("*.json"), key=_mtime, reverse=True)
        page = files[offset : offset + limit]
        items: list[ChartListItem] = []
        for f in page:
            try:
                spec = ChartSpec.model_validate_json(f.read_text(encoding="utf-8"))
                items.append(
                    ChartListItem(
                        chart_id=spec.chart_id,
                        title=spec.title,
                        chart_type=spec.chart_type,
                        description=spec.description,
                        created_at=spec.created_at,
                        updated_at=spec.updated_at,
                    )
                )
            except Exception:
                logger.warning(f"Grafico non leggibile: {f.name} (ignorato)")
        return items

    def _count_sync(self) -> int:
        return sum(1 for _ in self._dir.glob("*.json"))
