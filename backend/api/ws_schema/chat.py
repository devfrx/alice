"""AL\\CE — Typed schema of the chat WebSocket channel (``/api/ws/chat``).

One Pydantic model per frame. Field shapes audited from the emit sites on
2026-06-11: LLM stream forwarding (``services/turn/direct_executor.py`` —
``usage`` and the LLM-level ``done`` are consumed internally and never
reach the client), tool loop (``tool_loop.py``/``pipeline.py``), turn
persistence (``api/routes/chat/_persist.py`` builds the final ``done``),
canonical turn events (``services/turn/events.py``), interaction frames
(``services/turn/channel.py`` ``_REQUEST_SPECS``), reflective executor.
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
# Legacy streaming
# ---------------------------------------------------------------------------


class WsToken(ChatServerFrame):
    """A single streamed token from the LLM."""

    type: Literal["token"]
    content: str


class WsThinking(ChatServerFrame):
    """A reasoning/thinking token from the LLM (extended thinking mode)."""

    type: Literal["thinking"]
    content: str


class WsToolCallFunction(BaseModel):
    """The function sub-object of a raw LLM tool-call stream forward."""

    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: str


class WsToolCallStream(ChatServerFrame):
    """LLM requested a tool (raw stream forward, pre-execution)."""

    type: Literal["tool_call"]
    id: str
    function: WsToolCallFunction


class WsError(ChatServerFrame):
    """A hard error that terminated the turn."""

    type: Literal["error"]
    content: str


class WsDone(ChatServerFrame):
    """Final turn frame (built in chat ``_persist`` after the DB commit)."""

    type: Literal["done"]
    conversation_id: str
    message_id: str
    user_message_id: str
    finish_reason: str
    version_group_id: str | None = None
    version_index: int

# ---------------------------------------------------------------------------
# Tool loop
# ---------------------------------------------------------------------------


class WsToolExecutionStart(ChatServerFrame):
    """The tool executor began running a tool."""

    type: Literal["tool_execution_start"]
    tool_name: str
    execution_id: str


class WsToolExecutionDone(ChatServerFrame):
    """The tool executor finished running a tool."""

    type: Literal["tool_execution_done"]
    tool_name: str
    result: str
    execution_id: str
    success: bool
    content_type: str | None = None
    artifact_id: str | None = None


class WsToolProgress(ChatServerFrame):
    """Incremental progress; tools merge arbitrary extra keys (extra=allow)."""

    model_config = ConfigDict(extra="allow")

    type: Literal["tool_progress"]
    tool_name: str
    execution_id: str
    phase: str | None = None
    label: str | None = None
    step: int | None = None
    total: int | None = None
    percent: float | None = None
    elapsed_s: float | None = None


class WsContextBreakdown(BaseModel):
    """Per-category token breakdown within a ``context_info`` frame."""

    model_config = ConfigDict(extra="forbid")

    system: int
    tools: int
    messages: int
    files: int
    tool_results: int
    other: int


class WsContextInfo(ChatServerFrame):
    """Current context-window utilisation snapshot."""

    type: Literal["context_info"]
    used: int
    available: int
    context_window: int
    percentage: float
    was_compressed: bool
    messages_summarized: int
    is_estimated: bool = False
    breakdown: WsContextBreakdown | None = None


class WsContextCompressionStart(ChatServerFrame):
    """Context compression is about to begin."""

    type: Literal["context_compression_start"]


class WsContextCompressionDone(ChatServerFrame):
    """Context compression completed successfully."""

    type: Literal["context_compression_done"]
    messages_summarized: int
    summary_message_id: str | None = None


class WsContextCompressionFailed(ChatServerFrame):
    """Context compression failed; the turn continues uncompressed."""

    type: Literal["context_compression_failed"]


class WsLlmRequery(ChatServerFrame):
    """The tool loop is making another LLM call after tool execution."""

    type: Literal["llm_requery"]
    iteration: int


class WsWarning(ChatServerFrame):
    """A non-fatal warning from the turn executor."""

    type: Literal["warning"]
    content: str

# ---------------------------------------------------------------------------
# Interaction requests (round-trips driven by services/turn/channel.py)
# ---------------------------------------------------------------------------


class WsToolConfirmationRequired(ChatServerFrame):
    """The turn executor needs the user to approve a risky tool call."""

    type: Literal["tool_confirmation_required"]
    execution_id: str
    tool_name: str
    args: dict[str, Any]
    risk_level: RiskLevel
    description: str
    reasoning: str | None = None
    allow_remember: bool = True


class WsClientToolCall(ChatServerFrame):
    """Delegate a UI-side tool execution to the connected client."""

    type: Literal["client_tool_call"]
    execution_id: str
    tool_name: str
    args: dict[str, Any]


class WsAskUserQuestion(BaseModel):
    """One question within an ``ask_user_required`` frame."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    type: Literal["radio", "checkbox"]
    options: list[str] = Field(default_factory=list)
    allow_free_text: bool = False


class WsAskUserRequired(ChatServerFrame):
    """The agent needs clarification from the user before proceeding."""

    type: Literal["ask_user_required"]
    execution_id: str
    questions: list[WsAskUserQuestion]

# ---------------------------------------------------------------------------
# Canonical turn events (services/turn/events.py)
# ---------------------------------------------------------------------------


class WsTurnStarted(ChatServerFrame):
    """A new turn has started processing."""

    type: Literal["turn.started"]
    turn_id: str
    conversation_id: str


class WsTurnLlmStep(ChatServerFrame):
    """The turn executor began an LLM step."""

    type: Literal["turn.llm_step"]
    turn_id: str
    step: int


class WsTurnToolCall(ChatServerFrame):
    """The turn executor dispatched a tool call."""

    type: Literal["tool.call"]
    turn_id: str
    execution_id: str
    tool_name: str
    args: dict[str, Any]


class WsTurnToolResult(ChatServerFrame):
    """A tool returned its result to the turn executor."""

    type: Literal["tool.result"]
    turn_id: str
    execution_id: str
    tool_name: str
    success: bool
    result: str
    content_type: str | None = None
    artifact_id: str | None = None


class WsInteractionRequested(ChatServerFrame):
    """An interaction (confirmation / client tool / clarification) was requested."""

    type: Literal["interaction.requested"]
    turn_id: str
    execution_id: str
    kind: InteractionKind
    tool_name: str | None = None


class WsInteractionResolved(ChatServerFrame):
    """An in-flight interaction completed (or was cancelled/timed-out)."""

    type: Literal["interaction.resolved"]
    turn_id: str
    execution_id: str
    kind: InteractionKind
    outcome: InteractionOutcome


class WsTurnUsage(ChatServerFrame):
    """Per-step token usage snapshot emitted by the turn executor."""

    type: Literal["turn.usage"]
    turn_id: str
    step: int
    input_tokens: int
    output_tokens: int
    tool_calls: int
    max_steps: int


class WsTurnFinished(ChatServerFrame):
    """The turn has finished; summary statistics follow."""

    type: Literal["turn.finished"]
    turn_id: str
    finish_reason: str | None = None
    input_tokens: int
    output_tokens: int
    steps: int
    cost: float | None = None

# ---------------------------------------------------------------------------
# Reflective executor
# ---------------------------------------------------------------------------


class WsAgentCriticInvoked(ChatServerFrame):
    """The reflective executor invoked the critic pass."""

    type: Literal["agent.critic_invoked"]
    run_id: str | None = None
    step_index: int = 0
    source: str


class WsAgentWarning(ChatServerFrame):
    """A structural warning from the agentic layer (e.g. degeneration)."""

    type: Literal["agent.warning"]
    run_id: str | None = None
    code: str
    message: str

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


class WsToolConfirmationResponse(ClientFrame):
    """User response to a ``tool_confirmation_required`` request."""

    type: Literal["tool_confirmation_response"]
    execution_id: str
    approved: bool
    remember: RememberChoice = "none"


class WsClientToolResult(ClientFrame):
    """Result of a UI-side tool execution requested by ``client_tool_call``."""

    type: Literal["client_tool_result"]
    execution_id: str
    success: bool = False
    result: str | list[Any] | dict[str, Any] | None = None
    error: str | None = None


class WsAskUserAnswer(BaseModel):
    """One answer within an ``ask_user_response`` frame."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    selected: list[str] = Field(default_factory=list)
    free_text: str | None = None


class WsAskUserResponse(ClientFrame):
    """User answers to an ``ask_user_required`` request."""

    type: Literal["ask_user_response"]
    execution_id: str
    answers: list[WsAskUserAnswer]

# ---------------------------------------------------------------------------
# Channel unions
# ---------------------------------------------------------------------------

ChatServerMessage = Annotated[
    WsToken
    | WsThinking
    | WsToolCallStream
    | WsError
    | WsDone
    | WsToolExecutionStart
    | WsToolExecutionDone
    | WsToolProgress
    | WsContextInfo
    | WsContextCompressionStart
    | WsContextCompressionDone
    | WsContextCompressionFailed
    | WsLlmRequery
    | WsWarning
    | WsToolConfirmationRequired
    | WsClientToolCall
    | WsAskUserRequired
    | WsTurnStarted
    | WsTurnLlmStep
    | WsTurnToolCall
    | WsTurnToolResult
    | WsInteractionRequested
    | WsInteractionResolved
    | WsTurnUsage
    | WsTurnFinished
    | WsAgentCriticInvoked
    | WsAgentWarning,
    Field(discriminator="type"),
]

ChatClientMessage = Annotated[
    WsCancel | WsToolConfirmationResponse | WsClientToolResult | WsAskUserResponse,
    Field(discriminator="type"),
]
