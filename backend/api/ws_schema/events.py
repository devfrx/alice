"""AL\\CE — Typed schema of the events WebSocket channel (``/api/events/ws``).

One Pydantic model per frame. Field shapes were audited from the actual
emit sites on 2026-06-11:

* route keep-alives — ``api/routes/events.py``;
* lifespan bus bridges — ``core/app.py`` (mcp/email/note/service/knowledge);
* model downloads — ``services/model_downloader.py`` (dynamic payload);
* service callbacks — artifacts registry, plan/plan-document/scope/
  permission-mode services, terminal manager;
* REST side-effects — ``api/routes/calendar.py``, ``api/routes/config.py``.

Bridges forward ``kwargs.get(...)`` values, so most payload fields are
typed Optional with ``None`` defaults: absent-on-the-wire must validate.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.api.ws_schema._base import ClientFrame, EventsServerFrame

# ---------------------------------------------------------------------------
# Keep-alives
# ---------------------------------------------------------------------------


class WsPong(EventsServerFrame):
    """Reply to a client ``ping``."""

    type: Literal["pong"]


class WsHeartbeat(EventsServerFrame):
    """Periodic liveness frame pushed when the client is idle."""

    type: Literal["heartbeat"]


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


class WsMcpServerConnected(EventsServerFrame):
    """An MCP server successfully connected."""

    type: Literal["mcp.server.connected"]
    server: str | None = None


class WsMcpServerDisconnected(EventsServerFrame):
    """An MCP server disconnected."""

    type: Literal["mcp.server.disconnected"]
    server: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


class WsEmailReceived(EventsServerFrame):
    """A new email arrived in a monitored folder."""

    type: Literal["email.received"]
    folder: str = "INBOX"


class WsEmailSent(EventsServerFrame):
    """An outbound email was sent."""

    type: Literal["email.sent"]
    message_id: str | None = None


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


class WsNoteCreated(EventsServerFrame):
    """A new note was created."""

    type: Literal["note.created"]
    note_id: str | None = None
    title: str | None = None


class WsNoteUpdated(EventsServerFrame):
    """An existing note was updated."""

    type: Literal["note.updated"]
    note_id: str | None = None


class WsNoteDeleted(EventsServerFrame):
    """A note was deleted."""

    type: Literal["note.deleted"]
    note_id: str | None = None


# ---------------------------------------------------------------------------
# Service / model health
# ---------------------------------------------------------------------------


class WsServiceStatus(EventsServerFrame):
    """A backend service changed its readiness status."""

    type: Literal["service.status"]
    service: str
    status: str
    detail: str | None = None
    timestamp: float | str | None = None


class WsKnowledgeStatus(EventsServerFrame):
    """The composite knowledge backend reported its readiness."""

    type: Literal["knowledge.status"]
    ready: bool | None = None
    reason: str | None = None
    memory_enabled: bool | None = None
    tool_rag_enabled: bool | None = None


class WsModelDownloadProgress(EventsServerFrame):
    """Progress update for an in-flight model download.

    Payload forwarded verbatim from the bus; ``extra='allow'`` because the
    downloader may add fields without a synchronized schema bump.
    """

    model_config = ConfigDict(extra="allow")

    type: Literal["service.model_download_progress"]
    service: str | None = None
    model_id: str | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    phase: str | None = None
    file: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


class WsArtifactCreated(EventsServerFrame):
    """A new artifact was registered in the artifacts registry."""

    type: Literal["artifact.created"]
    artifact_id: str
    kind: str
    conversation_id: str | None = None
    title: str | None = None


class WsArtifactUpdated(EventsServerFrame):
    """An existing artifact changed (row metadata or JSON content)."""

    type: Literal["artifact.updated"]
    artifact_id: str


class WsArtifactDeleted(EventsServerFrame):
    """An artifact row was deleted."""

    type: Literal["artifact.deleted"]
    artifact_id: str


class WsArtifactsBulkDeleted(EventsServerFrame):
    """Bulk artifact deletion (conversation cleanup or full wipe).

    ``conversation_id`` is ``None`` for the delete-all wipe.  Pinned
    artifacts of a deleted conversation survive detached
    (``conversation_id=NULL``) and are NOT listed in ``artifact_ids``.
    """

    type: Literal["artifact.bulk_deleted"]
    conversation_id: str | None = None
    artifact_ids: list[str]


# ---------------------------------------------------------------------------
# Agent tasks / plan document
# ---------------------------------------------------------------------------


class WsTaskStep(BaseModel):
    """One ordered step of a conversation task list (``update_plan``).

    extra='allow' because the step dicts come from the agent's
    ``update_plan`` tool and may grow.
    """

    model_config = ConfigDict(extra="allow")

    step: str
    status: str


class WsTasksUpdated(EventsServerFrame):
    """The agent updated the mutable task list for a conversation."""

    type: Literal["tasks.updated"]
    conversation_id: str
    steps: list[WsTaskStep]


class WsPlanDocumentUpdated(EventsServerFrame):
    """The agent wrote or edited the plan document for a conversation."""

    type: Literal["plan_document.updated"]
    conversation_id: str
    title: str
    body: str
    updated_at: str | None = None


# ---------------------------------------------------------------------------
# Scope / permission mode
# ---------------------------------------------------------------------------


class WsScopeUpdated(EventsServerFrame):
    """The workspace scope (allowed folders) changed for a conversation."""

    type: Literal["scope.updated"]
    conversation_id: str
    folders: list[str]


class WsPermissionModeUpdated(EventsServerFrame):
    """The permission tier changed for a conversation.

    ``mode`` is a Literal (not the ``PermissionMode`` enum) to avoid a
    ``$defs`` name collision with the REST component of the same name;
    ``test_mode_literal_matches_enum`` pins the two in sync.
    """

    type: Literal["permission_mode.updated"]
    conversation_id: str
    mode: Literal["strict", "auto_edits", "plan", "autopilot"]


# ---------------------------------------------------------------------------
# Calendar / config
# ---------------------------------------------------------------------------


class WsCalendarChanged(EventsServerFrame):
    """A calendar event was created, updated, or deleted."""

    type: Literal["calendar.changed"]
    action: Literal["created", "updated", "deleted"]
    event_id: str


class WsConfigChanged(EventsServerFrame):
    """A layered-config key was mutated."""

    type: Literal["config.changed"]
    path: str
    value: Any = None
    layer: str


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------


class WsTerminalSession(BaseModel):
    """JSON snapshot of a live terminal session (``session.snapshot()``)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    conversation_id: str
    title: str
    cwd: str
    rows: int
    cols: int
    agent_assigned: bool
    created_at: str
    pid: int | None = None
    alive: bool


class WsTerminalSessionOpened(EventsServerFrame):
    """A new terminal session was opened."""

    type: Literal["terminal.session_opened"]
    conversation_id: str
    session: WsTerminalSession


class WsTerminalOutput(EventsServerFrame):
    """PTY output data from a terminal session."""

    type: Literal["terminal.output"]
    conversation_id: str
    session_id: str
    data: str


class WsTerminalClosed(EventsServerFrame):
    """A terminal session was closed."""

    type: Literal["terminal.closed"]
    conversation_id: str
    session_id: str
    exit_code: int | None = None


class WsTerminalRenamed(EventsServerFrame):
    """A terminal session was given a new title."""

    type: Literal["terminal.renamed"]
    conversation_id: str
    session_id: str
    title: str


class WsTerminalAssigned(EventsServerFrame):
    """A terminal session was assigned to a conversation."""

    type: Literal["terminal.assigned"]
    conversation_id: str
    session_id: str


# ---------------------------------------------------------------------------
# Client→server frames
# ---------------------------------------------------------------------------


class WsPing(ClientFrame):
    """Keep-alive ping from the client; server replies with ``pong``."""

    type: Literal["ping"]


class WsTerminalInput(ClientFrame):
    """Keyboard input from the client destined for a PTY session."""

    type: Literal["terminal.input"]
    conversation_id: str
    session_id: str
    data: str


class WsTerminalResize(ClientFrame):
    """Terminal resize notification from the client."""

    type: Literal["terminal.resize"]
    conversation_id: str
    session_id: str
    rows: int
    cols: int


# ---------------------------------------------------------------------------
# Channel unions
# ---------------------------------------------------------------------------

EventsServerMessage = Annotated[
    WsPong
    | WsHeartbeat
    | WsMcpServerConnected
    | WsMcpServerDisconnected
    | WsEmailReceived
    | WsEmailSent
    | WsNoteCreated
    | WsNoteUpdated
    | WsNoteDeleted
    | WsServiceStatus
    | WsKnowledgeStatus
    | WsModelDownloadProgress
    | WsArtifactCreated
    | WsArtifactUpdated
    | WsArtifactDeleted
    | WsArtifactsBulkDeleted
    | WsTasksUpdated
    | WsPlanDocumentUpdated
    | WsScopeUpdated
    | WsPermissionModeUpdated
    | WsCalendarChanged
    | WsConfigChanged
    | WsTerminalSessionOpened
    | WsTerminalOutput
    | WsTerminalClosed
    | WsTerminalRenamed
    | WsTerminalAssigned,
    Field(discriminator="type"),
]

EventsClientMessage = Annotated[
    WsPing | WsTerminalInput | WsTerminalResize,
    Field(discriminator="type"),
]
