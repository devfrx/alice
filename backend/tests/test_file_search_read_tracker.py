"""Tests for the per-conversation read-before-write tracker (Fase 2)."""

from pathlib import Path

from backend.plugins.file_search.read_tracker import ReadState, ReadTracker


def test_unread_file(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert ReadTracker().verify("conv1", f) is ReadState.UNREAD


def test_fresh_after_record(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x")
    t = ReadTracker()
    t.record("conv1", f)
    assert t.verify("conv1", f) is ReadState.FRESH


def test_stale_after_external_modification(tmp_path: Path) -> None:
    import os

    f = tmp_path / "a.txt"
    f.write_text("x")
    t = ReadTracker()
    t.record("conv1", f)
    os.utime(f, ns=(1, 1))  # mtime cambiato "esternamente"
    assert t.verify("conv1", f) is ReadState.STALE


def test_conversations_are_isolated(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x")
    t = ReadTracker()
    t.record("conv1", f)
    assert t.verify("conv2", f) is ReadState.UNREAD


def test_deleted_file_is_stale(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x")
    t = ReadTracker()
    t.record("conv1", f)
    f.unlink()
    assert t.verify("conv1", f) is ReadState.STALE


def test_lru_cap_evicts_oldest(tmp_path: Path) -> None:
    t = ReadTracker(max_entries=2)
    files = []
    for i in range(3):
        f = tmp_path / f"{i}.txt"
        f.write_text("x")
        files.append(f)
        t.record("conv1", f)
    assert t.verify("conv1", files[0]) is ReadState.UNREAD  # evicted
    assert t.verify("conv1", files[2]) is ReadState.FRESH


def test_rerecord_after_modification_is_fresh(tmp_path: Path) -> None:
    import os

    f = tmp_path / "a.txt"
    f.write_text("x")
    t = ReadTracker()
    t.record("conv1", f)
    os.utime(f, ns=(1, 1))  # modifica esterna
    assert t.verify("conv1", f) is ReadState.STALE
    t.record("conv1", f)  # l'agente ri-legge (ciclo Task 11-12)
    assert t.verify("conv1", f) is ReadState.FRESH


def test_conversation_cap_evicts_least_recently_used(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x")
    t = ReadTracker(max_conversations=2)
    t.record("conv1", f)
    t.record("conv2", f)
    t.record("conv3", f)  # evict conv1 (la meno recentemente usata)
    assert t.verify("conv1", f) is ReadState.UNREAD
    assert t.verify("conv2", f) is ReadState.FRESH
    assert t.verify("conv3", f) is ReadState.FRESH


def test_verify_refreshes_conversation_lru_position(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x")
    t = ReadTracker(max_conversations=2)
    t.record("conv1", f)
    t.record("conv2", f)
    assert t.verify("conv1", f) is ReadState.FRESH  # conv1 torna in testa
    t.record("conv3", f)  # evict conv2, non conv1
    assert t.verify("conv1", f) is ReadState.FRESH
    assert t.verify("conv2", f) is ReadState.UNREAD


def test_rerecord_refreshes_lru_position(tmp_path: Path) -> None:
    t = ReadTracker(max_entries=2)
    a = tmp_path / "a.txt"
    a.write_text("x")
    b = tmp_path / "b.txt"
    b.write_text("x")
    c = tmp_path / "c.txt"
    c.write_text("x")
    t.record("conv1", a)
    t.record("conv1", b)
    t.record("conv1", a)  # a torna in testa
    t.record("conv1", c)  # evict b, non a
    assert t.verify("conv1", a) is ReadState.FRESH
    assert t.verify("conv1", b) is ReadState.UNREAD
