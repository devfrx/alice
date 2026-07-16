"""Tests for tool confirmation audit system (Phase 5)."""

import uuid

import pytest

from backend.db.models import ToolConfirmationAudit


class TestToolConfirmationAuditModel:
    """Test the ToolConfirmationAudit SQLModel."""

    def test_create_audit_entry(self):
        """Can create an audit entry with all fields."""
        entry = ToolConfirmationAudit(
            conversation_id=uuid.uuid4(),
            execution_id=str(uuid.uuid4()),
            tool_name="pc_automation_execute_command",
            args_json='{"command": "ipconfig"}',
            risk_level="dangerous",
            user_approved=True,
        )
        assert entry.user_approved is True
        assert entry.risk_level == "dangerous"
        assert entry.rejection_reason is None

    def test_create_rejected_entry(self):
        """Can create a rejected audit entry."""
        entry = ToolConfirmationAudit(
            conversation_id=uuid.uuid4(),
            execution_id=str(uuid.uuid4()),
            tool_name="pc_automation_take_screenshot",
            args_json="{}",
            risk_level="medium",
            user_approved=False,
            rejection_reason="user_rejected",
        )
        assert entry.user_approved is False
        assert entry.rejection_reason == "user_rejected"

    def test_create_with_thinking(self):
        """Can store thinking/reasoning content."""
        entry = ToolConfirmationAudit(
            conversation_id=uuid.uuid4(),
            execution_id=str(uuid.uuid4()),
            tool_name="pc_automation_open_application",
            args_json='{"app_name": "notepad"}',
            risk_level="medium",
            user_approved=True,
            thinking_content="The user asked to open Notepad so I will use the open_application tool.",
        )
        assert entry.thinking_content is not None

    def test_default_timestamp(self):
        """Entry gets a default created_at timestamp."""
        entry = ToolConfirmationAudit(
            conversation_id=uuid.uuid4(),
            execution_id=str(uuid.uuid4()),
            tool_name="test_tool",
            args_json="{}",
            risk_level="safe",
            user_approved=True,
        )
        assert entry.created_at is not None


@pytest.mark.asyncio
class TestAuditEndpoint:
    """Test the GET /api/audit/confirmations endpoint."""

    async def test_list_empty(self, client):
        """Returns empty list when no audit entries exist."""
        resp = await client.get("/api/audit/confirmations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert data["count"] == 0

    async def test_list_with_filters(self, client):
        """Supports filter query parameters without error."""
        resp = await client.get(
            "/api/audit/confirmations",
            params={"tool_name": "pc_automation_test", "approved": "true", "limit": 10},
        )
        assert resp.status_code == 200

    async def test_list_pagination(self, client):
        """Supports offset and limit parameters."""
        resp = await client.get(
            "/api/audit/confirmations",
            params={"offset": 0, "limit": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["offset"] == 0
        assert data["limit"] == 5

    async def test_list_filter_by_conversation(self, client):
        """Supports filtering by conversation_id."""
        conv_id = str(uuid.uuid4())
        resp = await client.get(
            "/api/audit/confirmations",
            params={"conversation_id": conv_id},
        )
        assert resp.status_code == 200

    async def test_invalid_limit(self, client):
        """Rejects limit > 500."""
        resp = await client.get(
            "/api/audit/confirmations",
            params={"limit": 1000},
        )
        assert resp.status_code == 422  # Validation error
