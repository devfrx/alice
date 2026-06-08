"""AL\\CE — Tests for the interactive terminal REST API (Fase 7 E1).

Drives ``/api/terminal`` through a FastAPI ``TestClient`` over a minimal app
whose ``app.state.context`` carries a real
:class:`~backend.services.terminal.manager.TerminalSessionManager` backed by the
:class:`FakePtyProcess` (no real process / Win32 job).  Pins the contract: the
``enabled`` gate, scope confinement surfacing as ``400``, the not-found paths,
and rename/assign.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.terminal import router
from backend.core.config import WorkspaceScopeConfig
from backend.services.terminal.manager import TerminalSessionManager
from backend.services.terminal.pty_backend import FakePtyProcess

CONV = "11111111-1111-1111-1111-111111111111"


class _Factory:
    def __init__(self) -> None:
        self.created: list[FakePtyProcess] = []

    def __call__(
        self, argv: list[str], *, cwd: str, rows: int = 24, cols: int = 80,
        env: dict[str, str] | None = None,
    ) -> FakePtyProcess:
        fake = FakePtyProcess(pid=4242 + len(self.created))
        self.created.append(fake)
        return fake


def _make_client(
    *, enabled: bool, scope_roots: list[Path] | None,
) -> tuple[TestClient, _Factory]:
    factory = _Factory()

    def scope_provider(_cid: str) -> list[Path] | None:
        return scope_roots

    mgr = TerminalSessionManager(
        scope_provider=scope_provider,
        scope_config=WorkspaceScopeConfig(),
        pty_factory=factory,
        job_factory=lambda _pid: None,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.context = SimpleNamespace(
        config=SimpleNamespace(terminal=SimpleNamespace(enabled=enabled)),
        terminal_session_manager=mgr,
    )
    client = TestClient(app)
    return client, factory


@pytest.fixture
def in_scope_client(tmp_path: Path) -> tuple[TestClient, _Factory]:
    return _make_client(enabled=True, scope_roots=[tmp_path])


def _terminate_all(factory: _Factory) -> None:
    """Unblock leaked reader threads at test end."""
    for fake in factory.created:
        fake.terminate()


# ---------------------------------------------------------------------------
# List + enabled gate
# ---------------------------------------------------------------------------


def test_list_empty_reports_enabled(in_scope_client: tuple[TestClient, _Factory]) -> None:
    client, _factory = in_scope_client
    resp = client.get(f"/api/terminal/{CONV}")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"enabled": True, "sessions": []}


def test_list_bad_uuid_400(in_scope_client: tuple[TestClient, _Factory]) -> None:
    client, _factory = in_scope_client
    assert client.get("/api/terminal/not-a-uuid").status_code == 400


def test_create_disabled_403(tmp_path: Path) -> None:
    client, _factory = _make_client(enabled=False, scope_roots=[tmp_path])
    resp = client.post(f"/api/terminal/{CONV}", json={})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "terminal_disabled"


# ---------------------------------------------------------------------------
# Create / scope confinement
# ---------------------------------------------------------------------------


def test_create_then_list_then_delete(
    in_scope_client: tuple[TestClient, _Factory],
) -> None:
    client, factory = in_scope_client
    try:
        created = client.post(f"/api/terminal/{CONV}", json={"title": "Build"})
        assert created.status_code == 200
        snap = created.json()
        assert snap["title"] == "Build"
        assert snap["conversation_id"] == CONV
        sid = snap["id"]

        listed = client.get(f"/api/terminal/{CONV}").json()
        assert [s["id"] for s in listed["sessions"]] == [sid]

        assert client.delete(f"/api/terminal/{CONV}/{sid}").status_code == 204
        assert client.delete(f"/api/terminal/{CONV}/{sid}").status_code == 404
    finally:
        _terminate_all(factory)


def test_create_out_of_scope_cwd_400(tmp_path: Path) -> None:
    scope = tmp_path / "scope"
    scope.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    client, factory = _make_client(enabled=True, scope_roots=[scope])
    try:
        resp = client.post(f"/api/terminal/{CONV}", json={"cwd": str(outside)})
        assert resp.status_code == 400
        assert "outside the workspace scope" in resp.json()["detail"]
    finally:
        _terminate_all(factory)


def test_create_no_scope_400(tmp_path: Path) -> None:
    client, factory = _make_client(enabled=True, scope_roots=None)
    try:
        resp = client.post(f"/api/terminal/{CONV}", json={})
        assert resp.status_code == 400
        assert "No workspace folder scope" in resp.json()["detail"]
    finally:
        _terminate_all(factory)


# ---------------------------------------------------------------------------
# Patch (rename + assign)
# ---------------------------------------------------------------------------


def test_patch_rename_and_assign(
    in_scope_client: tuple[TestClient, _Factory],
) -> None:
    client, factory = in_scope_client
    try:
        sid = client.post(f"/api/terminal/{CONV}", json={}).json()["id"]
        resp = client.patch(
            f"/api/terminal/{CONV}/{sid}",
            json={"title": "Server", "assign_to_agent": True},
        )
        assert resp.status_code == 200
        snap = resp.json()
        assert snap["title"] == "Server"
        assert snap["agent_assigned"] is True
    finally:
        _terminate_all(factory)


def test_patch_unknown_session_404(
    in_scope_client: tuple[TestClient, _Factory],
) -> None:
    client, _factory = in_scope_client
    resp = client.patch(f"/api/terminal/{CONV}/missing", json={"title": "x"})
    assert resp.status_code == 404
