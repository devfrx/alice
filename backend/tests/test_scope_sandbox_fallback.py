"""The no-scope hard-sandbox fallback gives each conversation an isolated workdir."""
from __future__ import annotations

from backend.core.config import WorkspaceScopeConfig
from backend.services.scope_service import ScopeService


def _svc(tmp_path) -> ScopeService:
    cfg = WorkspaceScopeConfig(sandbox_root=str(tmp_path / "data" / "workspaces"))
    svc = ScopeService.__new__(ScopeService)
    svc._config = cfg
    svc._scopes = {}
    return svc


def test_sandbox_root_is_per_conversation_and_created(tmp_path):
    svc = _svc(tmp_path)
    conv = "11111111-1111-1111-1111-111111111111"
    root = svc.sandbox_root_for(conv)
    assert root.exists() and root.is_dir()
    assert root.name == conv
    assert root.parent.name == "workspaces"


def test_effective_roots_uses_sandbox_when_no_explicit_scope(tmp_path):
    svc = _svc(tmp_path)
    conv = "22222222-2222-2222-2222-222222222222"
    eff = svc.effective_roots(conv)
    assert eff == [svc.sandbox_root_for(conv)]


def test_effective_roots_prefers_explicit_scope(tmp_path):
    svc = _svc(tmp_path)
    conv = "33333333-3333-3333-3333-333333333333"
    explicit = tmp_path / "myproject"
    explicit.mkdir()
    svc._scopes[conv] = [explicit]
    assert svc.effective_roots(conv) == [explicit]
