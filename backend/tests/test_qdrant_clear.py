"""QdrantService.clear_embedded_data — destructive reset of the embedded store.

Backs the user-triggered "Ripara/Reset vector store" CTA: when the on-disk
embedded data was written by an incompatible ``qdrant-client`` version (so the
client can no longer open it), clearing the directory lets a fresh store be
created on the next ``initialize()``.
"""

from __future__ import annotations

from pathlib import Path

from backend.core.config import QdrantConfig
from backend.services.qdrant_service import QdrantService


def test_clear_embedded_data_removes_directory(tmp_path: Path) -> None:
    """Embedded mode: the data directory (and its contents) is removed."""
    data_dir = tmp_path / "qdrant"
    (data_dir / "collection").mkdir(parents=True)
    (data_dir / "meta.json").write_text("{}", encoding="utf-8")
    (data_dir / ".lock").write_text("", encoding="utf-8")

    svc = QdrantService(QdrantConfig(mode="embedded", path=str(data_dir)))
    removed = svc.clear_embedded_data()

    assert removed is True
    assert not data_dir.exists()


def test_clear_embedded_data_noop_when_absent(tmp_path: Path) -> None:
    """Nothing to remove → still reports success (idempotent)."""
    svc = QdrantService(
        QdrantConfig(mode="embedded", path=str(tmp_path / "missing")),
    )
    assert svc.clear_embedded_data() is True


def test_clear_embedded_data_refuses_in_server_mode(tmp_path: Path) -> None:
    """Server mode has no local data dir → returns False, touches nothing."""
    svc = QdrantService(QdrantConfig(mode="server", path=str(tmp_path)))
    assert svc.clear_embedded_data() is False
    assert tmp_path.exists()
