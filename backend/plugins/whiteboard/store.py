"""WhiteboardStore — persistenza JSON per le lavagne tldraw."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from .models import WhiteboardListItem, WhiteboardSpec


class WhiteboardStore:
    """Gestisce il salvataggio e il recupero delle lavagne su disco."""

    def __init__(self, whiteboard_output_dir: str | Path) -> None:
        self._dir = Path(whiteboard_output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    async def save(self, spec: WhiteboardSpec) -> None:
        """Salva una lavagna su disco."""
        await asyncio.to_thread(self._write, spec)

    async def load(self, board_id: str) -> WhiteboardSpec | None:
        """Carica una lavagna da disco."""
        return await asyncio.to_thread(self._read, board_id)

    async def update_snapshot(
        self, board_id: str, snapshot: dict[str, Any]
    ) -> bool:
        """Aggiorna solo lo snapshot di una lavagna esistente."""
        spec = await self.load(board_id)
        if spec is None:
            return False
        spec.snapshot = snapshot
        spec.updated_at = datetime.now(timezone.utc)
        await self.save(spec)
        return True

    async def update(self, board_id: str, new_spec: WhiteboardSpec) -> bool:
        """Aggiorna completamente una lavagna esistente."""
        if new_spec.board_id != board_id:
            raise ValueError(
                f"board_id mismatch: atteso {board_id!r}, ricevuto {new_spec.board_id!r}"
            )
        path = self._path(board_id)
        if not await asyncio.to_thread(path.exists):
            return False
        await asyncio.to_thread(self._write, new_spec)
        return True

    async def delete(self, board_id: str) -> bool:
        """Elimina una lavagna da disco."""
        path = self._path(board_id)
        deleted = await asyncio.to_thread(self._unlink, path)
        if deleted:
            logger.info(f"Whiteboard eliminata: {board_id}")
        return deleted

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        conversation_id: str | None = None,
    ) -> list[WhiteboardListItem]:
        """Lista lavagne ordinate dal più recente, con filtro opzionale."""
        items = await asyncio.to_thread(self._list_sync, limit, offset)
        if conversation_id is not None:
            items = [i for i in items if i.conversation_id == conversation_id]
        return items

    async def count(self) -> int:
        """Conta il numero totale di lavagne persistite."""
        return await asyncio.to_thread(self._count_sync)

    # -- I/O sincrono (eseguito in thread) ----------------------------------

    def _path(self, board_id: str) -> Path:
        safe_id = "".join(c for c in board_id if c.isalnum() or c == "-")
        if not safe_id:
            raise ValueError(
                f"board_id non valido (nessun carattere sicuro): {board_id!r}"
            )
        return self._dir / f"{safe_id}.json"

    def _write(self, spec: WhiteboardSpec) -> None:
        path = self._path(spec.board_id)
        path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    def _read(self, board_id: str) -> WhiteboardSpec | None:
        path = self._path(board_id)
        if not path.exists():
            return None
        try:
            return WhiteboardSpec.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception:
            logger.exception(f"Errore lettura whiteboard {board_id}")
            return None

    def _unlink(self, path: Path) -> bool:
        if path.exists():
            path.unlink()
            return True
        return False

    def _count_shape_records(self, snapshot: dict[str, Any]) -> int:
        """Conta le shape nel tldraw store snapshot."""
        store = snapshot.get("store", {})
        return sum(
            1
            for v in store.values()
            if isinstance(v, dict) and v.get("typeName") == "shape"
        )

    def _list_sync(self, limit: int, offset: int) -> list[WhiteboardListItem]:
        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except FileNotFoundError:
                return 0.0

        files = sorted(self._dir.glob("*.json"), key=_mtime, reverse=True)
        page = files[offset : offset + limit]
        items: list[WhiteboardListItem] = []
        for f in page:
            try:
                spec = WhiteboardSpec.model_validate_json(
                    f.read_text(encoding="utf-8")
                )
                items.append(
                    WhiteboardListItem(
                        board_id=spec.board_id,
                        title=spec.title,
                        description=spec.description,
                        conversation_id=spec.conversation_id,
                        created_at=spec.created_at,
                        updated_at=spec.updated_at,
                        shape_count=self._count_shape_records(spec.snapshot),
                    )
                )
            except Exception:
                logger.warning(f"Whiteboard non leggibile: {f.name} (ignorata)")
        return items

    def _count_sync(self) -> int:
        return sum(1 for _ in self._dir.glob("*.json"))
