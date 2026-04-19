"""AL\\CE — SQLModel database models."""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    """Generate a new UUID4."""
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class Conversation(SQLModel, table=True):
    """A single conversation thread."""

    __tablename__ = "conversations"
    __table_args__ = (
        sa.Index("ix_conversation_updated_at", "updated_at"),
    )

    id: uuid.UUID = Field(
        default_factory=_new_uuid,
        primary_key=True,
    )
    title: Optional[str] = Field(default=None, max_length=256)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    active_versions: Optional[Any] = Field(
        default=None,
        sa_column=sa.Column(sa.JSON, nullable=True),
        description="Map of version_group_id → active version_index.",
    )
    context_snapshot: Optional[Any] = Field(
        default=None,
        sa_column=sa.Column(sa.JSON, nullable=True),
        description=(
            "Last real token counts from LLM API: "
            "{prompt_tokens, completion_tokens, context_window}."
        ),
    )

    # -- relationships ------------------------------------------------------
    messages: list["Message"] = Relationship(
        back_populates="conversation",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    artifacts: list["Artifact"] = Relationship(
        back_populates="conversation",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class Message(SQLModel, table=True):
    """A single message inside a conversation."""

    __tablename__ = "messages"
    __table_args__ = (
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'tool')",
            name="ck_message_role",
        ),
        sa.Index(
            "ix_message_conv_created",
            "conversation_id",
            "created_at",
        ),
        sa.Index("ix_message_version_group", "version_group_id"),
    )

    id: uuid.UUID = Field(
        default_factory=_new_uuid,
        primary_key=True,
    )
    conversation_id: uuid.UUID = Field(
        sa_column=sa.Column(
            sa.Uuid,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    role: str = Field(
        max_length=16,
        description='One of "user", "assistant", "system", or "tool".',
    )
    content: str = Field(default="")
    tool_calls: Optional[Any] = Field(
        default=None,
        sa_column=sa.Column(sa.JSON, nullable=True),
    )
    tool_call_id: Optional[str] = Field(default=None, max_length=64)
    thinking_content: Optional[str] = Field(
        default=None,
        description="Reasoning/thinking tokens from models that support it.",
    )
    version_group_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Groups message versions at the same edit point.",
    )
    version_index: int = Field(
        default=0,
        description="Version index within a version group (0 = original).",
    )
    token_count: Optional[int] = Field(
        default=None,
        description="Real token count from LLM API (stored after response).",
    )
    is_context_summary: bool = Field(
        default=False,
        description="True if this is an LLM-generated context summary.",
    )
    context_excluded: bool = Field(
        default=False,
        description="True if archived from LLM context (still visible in UI).",
    )
    created_at: datetime = Field(default_factory=_utcnow)

    # -- relationships ------------------------------------------------------
    conversation: Optional[Conversation] = Relationship(
        back_populates="messages"
    )
    attachments: list["Attachment"] = Relationship(
        back_populates="message",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------


class Attachment(SQLModel, table=True):
    """A file attached to a message (e.g. images for vision models)."""

    __tablename__ = "attachments"
    __table_args__ = (
        sa.Index("ix_attachment_message_id", "message_id"),
    )

    id: uuid.UUID = Field(
        default_factory=_new_uuid,
        primary_key=True,
    )
    message_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=sa.Column(
            sa.Uuid,
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        description="Linked after the user message is persisted.",
    )
    filename: str = Field(max_length=256)
    content_type: str = Field(max_length=128)
    file_path: str = Field(
        description="Relative path from the project root.",
    )
    created_at: datetime = Field(default_factory=_utcnow)

    # -- relationships ------------------------------------------------------
    message: Optional[Message] = Relationship(back_populates="attachments")


# ---------------------------------------------------------------------------
# Tool Confirmation Audit (Phase 5)
# ---------------------------------------------------------------------------


class ToolConfirmationAudit(SQLModel, table=True):
    """Audit log for tool confirmation decisions.

    Records every user approval/rejection for tools requiring confirmation,
    enabling post-hoc security review and compliance tracking.
    """

    __tablename__ = "tool_confirmation_audit"
    __table_args__ = (
        sa.Index("ix_audit_conversation_id", "conversation_id"),
        sa.Index("ix_audit_tool_name", "tool_name"),
        sa.Index("ix_audit_created_at", "created_at"),
        sa.CheckConstraint(
            "risk_level IN ('safe', 'medium', 'dangerous', 'forbidden')",
            name="ck_audit_risk_level",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=_new_uuid,
        primary_key=True,
    )
    conversation_id: uuid.UUID = Field(
        description="Conversation in which the tool was invoked.",
    )
    execution_id: str = Field(
        max_length=64,
        description="Unique execution ID for correlation with tool loop.",
    )
    tool_name: str = Field(
        max_length=128,
        description="Namespaced tool name (e.g. pc_automation_take_screenshot).",
    )
    args_json: str = Field(
        default="{}",
        description="JSON-serialized tool arguments.",
    )
    risk_level: str = Field(
        max_length=16,
        description="Risk level at time of invocation (safe/medium/dangerous/forbidden).",
    )
    user_approved: bool = Field(
        description="Whether the user approved the execution.",
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Reason for rejection: 'user_rejected', 'timeout', 'cancelled'.",
    )
    thinking_content: Optional[str] = Field(
        default=None,
        description="LLM reasoning/thinking content at time of tool invocation.",
    )
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# User Preferences
# ---------------------------------------------------------------------------


class UserPreference(SQLModel, table=True):
    """Persisted user preference (survives across restarts).

    Stores independent settings as key-value pairs, where the key
    uses dot notation (e.g. 'tts.engine', 'ui.theme').
    """

    __tablename__ = "user_preferences"

    key: str = Field(primary_key=True, max_length=128)
    value: str = Field(default="")  # JSON-encoded value
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Plugin State
# ---------------------------------------------------------------------------


class PluginState(SQLModel, table=True):
    """Persists the enabled/disabled toggle for each plugin across restarts.

    At startup the plugin manager reads this table and overrides the default
    list from ``config/default.yaml``.  On every toggle via the REST API the
    new state is written here so it survives the next restart.
    """

    __tablename__ = "plugin_states"

    plugin_name: str = Field(primary_key=True, max_length=64)
    """Unique plugin identifier (e.g. 'web_search', 'calendar')."""

    enabled: bool = Field(default=True)
    """Whether this plugin should be loaded at startup."""

    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Artifact (generated tool output: 3D models, images, audio, charts, …)
# ---------------------------------------------------------------------------


class ArtifactKind(str, enum.Enum):
    """Type of artifact produced by a tool.

    Extend with new members when adding new artifact-producing tools
    (e.g. ``IMAGE``, ``AUDIO``, ``CHART``, ``WHITEBOARD``).  The string
    value is what gets persisted in SQLite, so values must remain stable.
    """

    CAD_3D_TEXT = "cad_3d_text"
    """3D model generated from text via TRELLIS (cad_generate)."""

    CAD_3D_IMAGE = "cad_3d_image"
    """3D model generated from an image via TRELLIS.2 (cad_generate_from_image)."""


class Artifact(SQLModel, table=True):
    """Persistent record of a file produced by a tool.

    An artifact is the unified abstraction for any binary output that
    the user may want to browse, pin or download from the UI: GLB
    models today, images / audio / charts tomorrow.  It always points
    to a file on disk via ``file_path`` (relative to ``PROJECT_ROOT``)
    and carries enough metadata to render a thumbnail/preview without
    needing to load the file itself.
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        sa.Index("ix_artifact_conv_created", "conversation_id", "created_at"),
        sa.Index("ix_artifact_kind_created", "kind", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=_new_uuid, primary_key=True)
    conversation_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=sa.Column(
            sa.Uuid,
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        description=(
            "Source conversation.  Set to NULL when the conversation "
            "is deleted but the artifact was pinned (preserved on "
            "the board)."
        ),
    )
    message_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=sa.Column(
            sa.Uuid,
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        description="The tool-result message that produced this artifact.",
    )
    tool_call_id: Optional[str] = Field(
        default=None, max_length=64, index=True,
        description="OpenAI tool_call_id that produced this artifact.",
    )
    kind: ArtifactKind = Field(
        sa_column=sa.Column(
            sa.Enum(
                ArtifactKind,
                values_callable=lambda e: [m.value for m in e],
                native_enum=False,
                length=32,
            ),
            nullable=False,
            index=True,
        ),
    )
    title: str = Field(max_length=256)
    """Human-readable label (e.g. truncated description, source filename)."""

    file_path: str = Field(
        description="Path on disk relative to PROJECT_ROOT.",
    )
    mime: str = Field(max_length=128)
    size_bytes: int = Field(default=0, ge=0)

    artifact_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(sa.JSON, nullable=False, default=dict),
        description=(
            "Free-form JSON metadata; the ``metadata`` name is reserved "
            "by SQLAlchemy Declarative so we use ``artifact_metadata``."
        ),
    )
    pinned: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # -- relationships ------------------------------------------------------
    conversation: Optional[Conversation] = Relationship(
        back_populates="artifacts"
    )


# ---------------------------------------------------------------------------
# Agent Run (Agent Loop v2)
# ---------------------------------------------------------------------------


class AgentRun(SQLModel, table=True):
    """Persistence of a single agent-loop execution.

    Optional: conversations that do not use the agent loop have NO rows in
    this table.  There is no mandatory FK from :class:`Message` back to
    :class:`AgentRun` — runs are looked up by ``conversation_id`` /
    ``user_message_id``.

    Lifecycle:
        ``planning`` → ``running`` → (``done`` | ``failed`` | ``cancelled``
        | ``asked_user``)

    Fields:
        goal:         Free-form text goal extracted by the planner.
        complexity:   ``TaskComplexity`` enum value (string).
        plan_json:    JSON-serialized list of ``Step`` objects.
        state:        Current state of the run.
        current_step: Index of the step being executed (0-based).
        total_steps:  Total number of steps in the active plan.
        replans:      Number of times the planner re-planned mid-run.
        retries_total: Cumulative per-step retries across the run.
        total_tokens_in / total_tokens_out: Token accounting for the run.
        total_tool_calls: Number of tool invocations across all steps.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        sa.Index("ix_agent_run_conversation_id", "conversation_id"),
        sa.Index("ix_agent_run_started_at", "started_at"),
    )

    id: uuid.UUID = Field(default_factory=_new_uuid, primary_key=True)
    conversation_id: uuid.UUID = Field(
        sa_column=sa.Column(
            sa.Uuid,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        description="Conversation this run belongs to.",
    )
    user_message_id: uuid.UUID = Field(
        sa_column=sa.Column(
            sa.Uuid,
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        description="The user message that triggered this run.",
    )
    final_assistant_message_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=sa.Column(
            sa.Uuid,
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        description="The persisted final assistant message (set on success).",
    )

    goal: str = Field(default="")
    complexity: str = Field(default="", max_length=32)
    plan_json: str = Field(default="[]")
    state: str = Field(default="planning", max_length=32)
    current_step: int = Field(default=0)
    total_steps: int = Field(default=0)
    replans: int = Field(default=0)
    retries_total: int = Field(default=0)

    total_tokens_in: int = Field(default=0)
    total_tokens_out: int = Field(default=0)
    total_tool_calls: int = Field(default=0)

    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = Field(default=None)
    error: Optional[str] = Field(default=None)

