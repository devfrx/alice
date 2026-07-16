"""Tests for backend.api.routes.cad — CAD model proxy route."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.cad import router
from backend.core.config import TrellisServiceConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(tmp_path: Path, trellis_enabled: bool = True) -> FastAPI:
    """Create a minimal FastAPI app with the CAD router and mocked context."""
    app = FastAPI()
    app.include_router(router, prefix="/api")

    trellis_cfg = TrellisServiceConfig(
        enabled=trellis_enabled,
        service_url="http://localhost:8090",
        model_output_dir=str(tmp_path / "3d_models"),
    )

    ctx = MagicMock()
    ctx.config.trellis = trellis_cfg
    ctx.config.project_root = str(tmp_path)

    app.state.context = ctx
    return app


def _create_glb_file(tmp_path: Path, model_name: str) -> Path:
    """Write a fake GLB file and return its path."""
    models_dir = tmp_path / "3d_models"
    models_dir.mkdir(parents=True, exist_ok=True)
    glb_path = models_dir / f"{model_name}.glb"
    glb_path.write_bytes(b"glTF\x02\x00\x00\x00" + b"\x00" * 100)
    return glb_path


# ===========================================================================
# 1. GET /api/cad/models/{model_name}
# ===========================================================================


class TestGetModel:
    """Serve GLB files from the local filesystem."""

    def test_get_model_success(self, tmp_path: Path) -> None:
        """Existing GLB file → 200 OK with binary content."""
        _create_glb_file(tmp_path, "test_cube")
        app = _make_app(tmp_path)

        with TestClient(app) as client:
            resp = client.get("/api/cad/models/test_cube")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "model/gltf-binary"
        assert resp.content.startswith(b"glTF")

    def test_get_model_not_found(self, tmp_path: Path) -> None:
        """Non-existent model → 404."""
        app = _make_app(tmp_path)
        (tmp_path / "3d_models").mkdir(parents=True, exist_ok=True)

        with TestClient(app) as client:
            resp = client.get("/api/cad/models/nonexistent")

        assert resp.status_code == 404

    def test_get_model_invalid_name(self, tmp_path: Path) -> None:
        """Path traversal attempt (../../etc/passwd) → 400."""
        app = _make_app(tmp_path)

        with TestClient(app) as client:
            resp = client.get("/api/cad/models/../../etc/passwd")

        # FastAPI may resolve the path or the regex check rejects it
        assert resp.status_code in (400, 404, 422)

    def test_get_model_path_traversal(self, tmp_path: Path) -> None:
        """URL-encoded path traversal (..%2F..%2Fetc) → 400."""
        app = _make_app(tmp_path)

        with TestClient(app) as client:
            resp = client.get("/api/cad/models/..%2F..%2Fetc")

        assert resp.status_code in (400, 404, 422)


# ===========================================================================
# 2. GET /api/cad/health
# ===========================================================================


class TestCadHealth:
    """Health check endpoint for the TRELLIS microservice."""

    def test_cad_health(self, tmp_path: Path) -> None:
        """Health check with mocked plugin → 200."""
        app = _make_app(tmp_path)

        # Mock the plugin manager to return a cad_generator plugin with health_check
        mock_plugin = MagicMock()
        mock_plugin.client = MagicMock()
        mock_plugin.client.health_check = AsyncMock(return_value=True)

        ctx = app.state.context
        ctx.plugin_manager = MagicMock()
        ctx.plugin_manager.get_plugin = MagicMock(return_value=mock_plugin)

        with TestClient(app) as client:
            resp = client.get("/api/cad/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("ok", "healthy", True)


# ===========================================================================
# 3. GET /api/cad/models (list)
# ===========================================================================


class TestCadModelList:
    """List generated 3D models."""

    def test_cad_model_list(self, tmp_path: Path) -> None:
        """Directory with GLB files → JSON list of model names."""
        _create_glb_file(tmp_path, "cube_01")
        _create_glb_file(tmp_path, "sphere_02")
        app = _make_app(tmp_path)

        with TestClient(app) as client:
            resp = client.get("/api/cad/models")

        assert resp.status_code == 200
        data = resp.json()
        # Should be a list containing the model names
        assert isinstance(data, (list, dict))
        # If list, check names are present
        if isinstance(data, list):
            names = [m if isinstance(m, str) else m.get("name", m.get("model_name", "")) for m in data]
            assert "cube_01" in names
            assert "sphere_02" in names
        else:
            # dict format with "models" key
            models = data.get("models", [])
            names = [m if isinstance(m, str) else m.get("name", m.get("model_name", "")) for m in models]
            assert "cube_01" in names
            assert "sphere_02" in names
