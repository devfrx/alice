"""Tests for backend.core.plugin_models — data models, enums, validation.

Covers ConnectionStatus, ToolDefinition, ToolResult, ExecutionContext,
and module-level constants.
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.core.plugin_models import (
    MAX_TOOL_DESCRIPTION_LENGTH,
    MAX_TOOL_RESULT_LENGTH,
    PLUGIN_API_VERSION,
    TOOL_NAME_PATTERN,
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)


# ===================================================================
# ConnectionStatus
# ===================================================================


class TestConnectionStatus:
    """Enum values, string behaviour, and membership."""

    def test_enum_values(self) -> None:
        assert ConnectionStatus.UNKNOWN == "unknown"
        assert ConnectionStatus.CONNECTED == "connected"
        assert ConnectionStatus.DISCONNECTED == "disconnected"
        assert ConnectionStatus.DEGRADED == "degraded"
        assert ConnectionStatus.ERROR == "error"

    def test_member_count(self) -> None:
        assert len(ConnectionStatus) == 5

    def test_str_behaviour(self) -> None:
        """StrEnum members are usable as plain strings."""
        assert f"status={ConnectionStatus.CONNECTED}" == "status=connected"

    def test_membership(self) -> None:
        assert "connected" in ConnectionStatus.__members__.values()
        assert "nonexistent" not in ConnectionStatus.__members__.values()


# ===================================================================
# ToolDefinition
# ===================================================================


class TestToolDefinition:
    """Creation, defaults, validation, serialisation, immutability."""

    def test_creation_minimal(self) -> None:
        td = ToolDefinition(name="ping", description="Ping check")
        assert td.name == "ping"
        assert td.description == "Ping check"

    def test_default_parameters(self) -> None:
        td = ToolDefinition(name="t", description="d")
        assert td.parameters == {"type": "object", "properties": {}}

    def test_custom_parameters(self) -> None:
        params = {"type": "object", "properties": {"q": {"type": "string"}}}
        td = ToolDefinition(name="search", description="Search", parameters=params)
        assert td.parameters is params

    def test_default_result_type(self) -> None:
        td = ToolDefinition(name="t", description="d")
        assert td.result_type == "string"

    def test_default_supports_cancellation(self) -> None:
        td = ToolDefinition(name="t", description="d")
        assert td.supports_cancellation is False

    def test_default_timeout_ms(self) -> None:
        td = ToolDefinition(name="t", description="d")
        assert td.timeout_ms == 30_000

    def test_default_requires_confirmation(self) -> None:
        td = ToolDefinition(name="t", description="d")
        assert td.requires_confirmation is False

    def test_default_risk_level(self) -> None:
        td = ToolDefinition(name="t", description="d")
        assert td.risk_level == "safe"

    def test_custom_fields(self) -> None:
        td = ToolDefinition(
            name="nuke",
            description="Remove everything",
            result_type="json",
            supports_cancellation=True,
            timeout_ms=60_000,
            requires_confirmation=True,
            risk_level="dangerous",
        )
        assert td.result_type == "json"
        assert td.supports_cancellation is True
        assert td.timeout_ms == 60_000
        assert td.requires_confirmation is True
        assert td.risk_level == "dangerous"

    # -- validate() -----------------------------------------------------

    def test_validate_valid_name(self) -> None:
        td = ToolDefinition(name="get_weather", description="Get weather")
        td.validate()  # should not raise

    def test_validate_name_with_hyphen(self) -> None:
        td = ToolDefinition(name="get-weather", description="OK")
        td.validate()

    def test_validate_name_with_digits(self) -> None:
        td = ToolDefinition(name="tool123", description="OK")
        td.validate()

    def test_validate_name_single_char(self) -> None:
        td = ToolDefinition(name="x", description="OK")
        td.validate()

    def test_validate_name_max_length_64(self) -> None:
        td = ToolDefinition(name="a" * 64, description="OK")
        td.validate()

    def test_validate_name_too_long(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            ToolDefinition(name="a" * 65, description="OK")

    def test_validate_name_empty(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            ToolDefinition(name="", description="OK")

    def test_validate_name_with_space(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            ToolDefinition(name="bad name", description="OK")

    def test_validate_name_with_special_char(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            ToolDefinition(name="bad.name", description="OK")

    def test_validate_description_within_limit(self) -> None:
        td = ToolDefinition(name="t", description="x" * MAX_TOOL_DESCRIPTION_LENGTH)
        td.validate()

    def test_validate_description_exceeds_limit(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            ToolDefinition(
                name="t", description="x" * (MAX_TOOL_DESCRIPTION_LENGTH + 1)
            )

    # -- to_openai_format() ---------------------------------------------

    def test_to_openai_format_structure(self) -> None:
        params = {"type": "object", "properties": {"q": {"type": "string"}}}
        td = ToolDefinition(name="search", description="Search", parameters=params)
        fmt = td.to_openai_format()
        assert fmt["type"] == "function"
        assert fmt["function"]["name"] == "search"
        assert fmt["function"]["description"] == "Search"
        assert fmt["function"]["parameters"] is params

    def test_to_openai_format_default_params(self) -> None:
        td = ToolDefinition(name="t", description="d")
        fmt = td.to_openai_format()
        assert fmt["function"]["parameters"] == {
            "type": "object",
            "properties": {},
        }

    # -- frozen immutability -------------------------------------------

    def test_frozen_cannot_set_name(self) -> None:
        td = ToolDefinition(name="t", description="d")
        with pytest.raises(dataclasses.FrozenInstanceError):
            td.name = "other"  # type: ignore[misc]

    def test_frozen_cannot_set_description(self) -> None:
        td = ToolDefinition(name="t", description="d")
        with pytest.raises(dataclasses.FrozenInstanceError):
            td.description = "other"  # type: ignore[misc]


# ===================================================================
# ToolResult
# ===================================================================


class TestToolResult:
    """Factory methods, field access, mutability."""

    def test_ok_factory(self) -> None:
        r = ToolResult.ok("hello")
        assert r.success is True
        assert r.content == "hello"
        assert r.content_type == "text/plain"
        assert r.execution_time_ms == 0.0
        assert r.error_message is None

    def test_ok_factory_custom_content_type(self) -> None:
        r = ToolResult.ok({"key": "val"}, content_type="application/json")
        assert r.content == {"key": "val"}
        assert r.content_type == "application/json"

    def test_ok_factory_with_time(self) -> None:
        r = ToolResult.ok("data", execution_time_ms=123.4)
        assert r.execution_time_ms == 123.4

    def test_ok_factory_none_content(self) -> None:
        r = ToolResult.ok(None)
        assert r.success is True
        assert r.content is None

    def test_error_factory(self) -> None:
        r = ToolResult.error("boom")
        assert r.success is False
        assert r.error_message == "boom"
        assert r.content is None
        assert r.execution_time_ms == 0.0

    def test_error_factory_with_time(self) -> None:
        r = ToolResult.error("oops", execution_time_ms=99.9)
        assert r.execution_time_ms == 99.9

    def test_direct_creation(self) -> None:
        r = ToolResult(success=True, content="x", truncated=True)
        assert r.truncated is True

    def test_mutable(self) -> None:
        r = ToolResult.ok("old")
        r.content = "new"
        assert r.content == "new"

    def test_default_truncated(self) -> None:
        r = ToolResult.ok("x")
        assert r.truncated is False


# ===================================================================
# ExecutionContext
# ===================================================================


class TestExecutionContext:
    """Creation, optional user_id, frozen immutability."""

    def test_creation(self) -> None:
        ec = ExecutionContext(
            session_id="s1",
            conversation_id="c1",
            execution_id="e1",
        )
        assert ec.session_id == "s1"
        assert ec.conversation_id == "c1"
        assert ec.execution_id == "e1"
        assert ec.user_id is None

    def test_with_user_id(self) -> None:
        ec = ExecutionContext(
            session_id="s", conversation_id="c", execution_id="e", user_id="u42"
        )
        assert ec.user_id == "u42"

    def test_frozen_cannot_set_session(self) -> None:
        ec = ExecutionContext(session_id="s", conversation_id="c", execution_id="e")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ec.session_id = "other"  # type: ignore[misc]

    def test_frozen_cannot_set_user_id(self) -> None:
        ec = ExecutionContext(session_id="s", conversation_id="c", execution_id="e")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ec.user_id = "u"  # type: ignore[misc]


# ===================================================================
# Module-level constants
# ===================================================================


class TestConstants:
    """Verify module constants are sensible."""

    def test_tool_name_pattern_type(self) -> None:
        assert hasattr(TOOL_NAME_PATTERN, "match")

    def test_tool_name_pattern_valid(self) -> None:
        assert TOOL_NAME_PATTERN.match("hello_world-123")

    def test_tool_name_pattern_rejects_empty(self) -> None:
        assert TOOL_NAME_PATTERN.match("") is None

    def test_max_tool_description_length(self) -> None:
        assert MAX_TOOL_DESCRIPTION_LENGTH == 1024

    def test_max_tool_result_length(self) -> None:
        assert MAX_TOOL_RESULT_LENGTH == 4096

    def test_plugin_api_version(self) -> None:
        assert PLUGIN_API_VERSION == "1.0.0"
