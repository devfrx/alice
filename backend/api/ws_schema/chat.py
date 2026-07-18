"""AL\\CE — Typed schema of the chat WebSocket channel (``/api/ws/chat``).

One Pydantic model per frame. The chat channel speaks ONLY the canonical v2
vocabulary (spec §4): every turn fact is streamed by the AgentEngine through
its definitive WS translator (``api/ws_schema/wire.py``, injected into the
composition root by the api call sites, which builds
each frame through the model below, so a frame that does not validate cannot be
constructed), and the post-turn persistence path
(``api/routes/chat/_persist.py`` / ``_assembly.py``) emits the typed
conversation-maintenance frames (``context.usage`` / ``context.compaction``) on
the SAME transport. There is no legacy frame vocabulary and no parity
translator any more — both were purged in Mossa 2 Task 10.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.api.ws_schema._base import ChatServerFrame, ClientFrame

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

RiskLevel = Literal["safe", "medium", "dangerous", "forbidden"]
InteractionKind = Literal["tool_confirmation", "client_tool_call", "ask_user"]
InteractionOutcome = Literal[
    "approved",
    "rejected",
    "answered",
    "executed",
    "timeout",
    "cancelled",
    "disconnected",
    "failed",
]
RememberChoice = Literal["none", "session", "persistent"]

# ---------------------------------------------------------------------------
# Shared sub-objects
# ---------------------------------------------------------------------------


class WsContextBreakdown(BaseModel):
    """Per-category token breakdown within a ``context.usage`` frame."""

    model_config = ConfigDict(extra="forbid")

    system: int
    tools: int
    messages: int
    files: int
    tool_results: int
    other: int


class WsAskUserQuestion(BaseModel):
    """One question within an ``interaction.requested`` (``ask_user``) frame."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    type: Literal["radio", "checkbox"]
    options: list[str] = Field(default_factory=list)
    allow_free_text: bool = False


class WsAskUserAnswer(BaseModel):
    """One answer within an ``interaction.response`` (``ask_user``) frame."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    selected: list[str] = Field(default_factory=list)
    free_text: str | None = None

# ---------------------------------------------------------------------------
# Canonical v2 turn events (api/ws_schema/wire.py)
# ---------------------------------------------------------------------------


class WsTurnStarted(ChatServerFrame):
    """A new turn has started processing."""

    type: Literal["turn.started"]
    turn_id: str
    conversation_id: str
    source: Literal["chat", "voice", "headless"]


class WsTurnDelta(ChatServerFrame):
    """A turn output delta (text or thinking)."""

    type: Literal["turn.delta"]
    turn_id: str
    step: int
    kind: Literal["text", "thinking"]
    text: str


class WsTurnLlmStep(ChatServerFrame):
    """The engine began an LLM step."""

    type: Literal["turn.llm_step"]
    turn_id: str
    step: int


class WsTurnToolCall(ChatServerFrame):
    """The engine dispatched a tool call."""

    type: Literal["tool.call"]
    turn_id: str
    execution_id: str
    tool_name: str
    args: dict[str, Any]
    step: int


class WsToolStarted(ChatServerFrame):
    """A greenlit tool call has started server-side execution."""

    type: Literal["tool.started"]
    turn_id: str
    execution_id: str
    tool_name: str


class WsToolProgress(ChatServerFrame):
    """Incremental progress of a long-running tool (typed, nested payload)."""

    type: Literal["tool.progress"]
    turn_id: str
    execution_id: str
    tool_name: str
    progress: dict[str, Any]


class WsTurnToolResult(ChatServerFrame):
    """A tool returned its result to the engine.

    ``status`` is the engine outcome vocabulary
    (ok/error/parse_error/duplicate/unknown_tool/denied/rejected/timeout/
    cancelled/budget_exhausted); ``result`` is the COMPLETE tool-response body
    (including the synthetic prose of the refusal branches).
    """

    type: Literal["tool.result"]
    turn_id: str
    execution_id: str
    tool_name: str
    status: str
    result: str
    content_type: str | None = None
    artifact_id: str | None = None


class WsInteractionRequested(ChatServerFrame):
    """An interaction (confirmation / client tool / clarification) was requested."""

    type: Literal["interaction.requested"]
    turn_id: str
    interaction_id: str
    execution_id: str
    kind: InteractionKind
    tool_name: str | None = None
    args: dict[str, Any] | None = None
    risk_level: RiskLevel | None = None
    description: str | None = None
    reasoning: str | None = None
    allow_remember: bool | None = None
    questions: list[WsAskUserQuestion] | None = None


class WsInteractionResolved(ChatServerFrame):
    """An in-flight interaction completed (or was cancelled/timed-out)."""

    type: Literal["interaction.resolved"]
    turn_id: str
    interaction_id: str
    execution_id: str
    kind: InteractionKind
    outcome: InteractionOutcome


class WsContextUsage(ChatServerFrame):
    """Context-window utilisation (``percentage`` is a fraction in [0, 1])."""

    type: Literal["context.usage"]
    turn_id: str | None = None
    used: int
    available: int
    context_window: int
    percentage: float
    was_compressed: bool = False
    messages_summarized: int = 0
    is_estimated: bool = True
    breakdown: WsContextBreakdown | None = None


class WsContextCompaction(ChatServerFrame):
    """A context-compaction cycle (started/done/failed)."""

    type: Literal["context.compaction"]
    turn_id: str | None = None
    phase: Literal["started", "done", "failed"]
    messages_summarized: int | None = None
    summary_message_id: str | None = None
    tokens_before: int | None = None
    tokens_after: int | None = None
    error: str | None = None


class WsTurnWarning(ChatServerFrame):
    """A non-fatal turn warning."""

    type: Literal["turn.warning"]
    turn_id: str
    code: str
    message: str


class WsTurnError(ChatServerFrame):
    """A turn error; ``turn_id`` is absent for pre-turn errors (validation)."""

    type: Literal["turn.error"]
    turn_id: str | None = None
    code: str
    message: str


class WsTurnUsage(ChatServerFrame):
    """Per-step token/cost usage snapshot emitted by the engine."""

    type: Literal["turn.usage"]
    turn_id: str
    step: int
    input_tokens: int
    output_tokens: int
    cost: float
    tool_calls: int
    max_steps: int


class WsTurnFinished(ChatServerFrame):
    """The turn has finished; summary statistics follow.

    ``message_id`` is ``""`` when the turn saved no final assistant message.
    """

    type: Literal["turn.finished"]
    turn_id: str
    finish_reason: str
    conversation_id: str
    message_id: str
    user_message_id: str | None = None
    version_group_id: str | None = None
    version_index: int
    steps: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost: float

# ---------------------------------------------------------------------------
# Client→server frames
# ---------------------------------------------------------------------------


class WsUserMessage(ClientFrame):
    """A plain user message — the UNTAGGED chat frame.

    Deliberately NOT part of :data:`ChatClientMessage`: the wire format has
    no ``type`` key (the channel pump treats any unrecognized frame as a
    user message). Exported as a named component for the FE send payload.
    """

    content: str
    conversation_id: str | None = None
    attachments: list[str] | None = None
    edit_message_id: str | None = None
    source: Literal["text", "voice"] | None = None
    """Input modality; ``voice`` turns get a trimmed toolset (Fase 8)."""


class WsCancel(ClientFrame):
    """Cancel the current in-flight turn."""

    type: Literal["cancel"]


class WsInteractionResponse(ClientFrame):
    """Unified response to interactions (kind-discriminated payload)."""

    type: Literal["interaction.response"]
    interaction_id: str
    kind: InteractionKind
    # tool_confirmation
    approved: bool | None = None
    remember: RememberChoice = "none"
    # ask_user
    answers: list[WsAskUserAnswer] | None = None
    # client_tool_call
    success: bool | None = None
    result: str | list[Any] | dict[str, Any] | None = None
    error: str | None = None

# ---------------------------------------------------------------------------
# Channel unions
# ---------------------------------------------------------------------------

ChatServerMessage = Annotated[
    WsTurnStarted
    | WsTurnDelta
    | WsTurnLlmStep
    | WsTurnToolCall
    | WsToolStarted
    | WsToolProgress
    | WsTurnToolResult
    | WsInteractionRequested
    | WsInteractionResolved
    | WsContextUsage
    | WsContextCompaction
    | WsTurnWarning
    | WsTurnError
    | WsTurnUsage
    | WsTurnFinished,
    Field(discriminator="type"),
]

ChatClientMessage = Annotated[
    WsCancel | WsInteractionResponse,
    Field(discriminator="type"),
]
