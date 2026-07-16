"""Tests for the file upload endpoint ``POST /api/chat/upload``."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

from backend.core.config import PROJECT_ROOT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)
"""A minimal valid 1×1 red PNG (≈ 70 bytes)."""


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


class TestUploadHappyPath:
    """Valid upload scenarios for ``POST /api/chat/upload``."""

    async def test_upload_valid_png(
        self, client: AsyncClient, tmp_path: Any,
    ) -> None:
        """A valid PNG upload must return 200 with attachment metadata."""
        conv_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
            files={"file": ("test.png", _TINY_PNG, "image/png")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "file_id" in body
        uuid.UUID(body["file_id"])  # must be a valid UUID
        assert body["filename"] == "test.png"
        assert body["content_type"] == "image/png"
        assert body["url"].startswith("/uploads/")

    async def test_upload_valid_jpeg(self, client: AsyncClient) -> None:
        """JPEG uploads should be accepted."""
        conv_id = str(uuid.uuid4())
        # A few bytes suffice — we only validate the MIME type header.
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
            files={"file": ("photo.jpg", b"\xff\xd8\xff", "image/jpeg")},
        )
        assert resp.status_code == 200
        assert resp.json()["content_type"] == "image/jpeg"

    async def test_upload_valid_webp(self, client: AsyncClient) -> None:
        """WebP uploads should be accepted."""
        conv_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
            files={"file": ("img.webp", b"RIFF\x00\x00\x00\x00WEBP", "image/webp")},
        )
        assert resp.status_code == 200

    async def test_upload_valid_gif(self, client: AsyncClient) -> None:
        """GIF uploads should be accepted."""
        conv_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
            files={"file": ("anim.gif", b"GIF89a", "image/gif")},
        )
        assert resp.status_code == 200

    async def test_upload_creates_file_on_disk(
        self, client: AsyncClient,
    ) -> None:
        """After a successful upload the file must exist on disk."""
        conv_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
            files={"file": ("disk.png", _TINY_PNG, "image/png")},
        )
        assert resp.status_code == 200
        file_id = resp.json()["file_id"]

        expected = PROJECT_ROOT / "data" / "uploads" / conv_id / f"{file_id}.png"
        assert expected.exists()
        assert expected.read_bytes() == _TINY_PNG

        # Cleanup.
        expected.unlink(missing_ok=True)
        expected.parent.rmdir()

    async def test_upload_to_non_existent_conversation(
        self, client: AsyncClient,
    ) -> None:
        """Uploading before a conversation exists should still succeed."""
        conv_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
            files={"file": ("pre.png", _TINY_PNG, "image/png")},
        )
        assert resp.status_code == 200

        # Cleanup.
        file_id = resp.json()["file_id"]
        path = PROJECT_ROOT / "data" / "uploads" / conv_id / f"{file_id}.png"
        path.unlink(missing_ok=True)
        path.parent.rmdir()


# ---------------------------------------------------------------------------
# Tests — rejection / error cases
# ---------------------------------------------------------------------------


class TestUploadErrors:
    """Error-condition tests for the upload endpoint."""

    async def test_upload_unsupported_mime_type(
        self, client: AsyncClient,
    ) -> None:
        """Non-image MIME types must be rejected with 400."""
        conv_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
            files={"file": ("evil.exe", b"MZ\x90", "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]

    async def test_upload_pdf_rejected(self, client: AsyncClient) -> None:
        """PDF uploads must be rejected."""
        conv_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
            files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert resp.status_code == 400

    async def test_upload_text_plain_rejected(
        self, client: AsyncClient,
    ) -> None:
        """Plain text uploads must be rejected."""
        conv_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400

    async def test_upload_missing_file_field(
        self, client: AsyncClient,
    ) -> None:
        """Omitting the file entirely should fail with 422."""
        conv_id = str(uuid.uuid4())
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": conv_id},
        )
        assert resp.status_code == 422

    async def test_upload_missing_conversation_id(
        self, client: AsyncClient,
    ) -> None:
        """Omitting ``conversation_id`` should fail with 422."""
        resp = await client.post(
            "/api/chat/upload",
            files={"file": ("img.png", _TINY_PNG, "image/png")},
        )
        assert resp.status_code == 422

    async def test_upload_path_traversal_conversation_id(
        self, client: AsyncClient,
    ) -> None:
        """A ``conversation_id`` with ``../`` must not escape the uploads dir.

        FastAPI validates UUID fields via Pydantic, but the upload endpoint
        accepts ``conversation_id`` as a plain string via ``Form``.  Even if
        the value isn't a valid UUID the file should be safely sandboxed.
        """
        resp = await client.post(
            "/api/chat/upload",
            data={"conversation_id": "../../etc/passwd"},
            files={"file": ("img.png", _TINY_PNG, "image/png")},
        )
        # Path traversal attempts must be rejected by validation.
        assert resp.status_code in (400, 422)
