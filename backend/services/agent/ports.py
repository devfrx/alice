"""Porte del motore (Protocol) e tipi di supporto — Interfacce condivise §ports.py.

Ogni tipo è copiato verbatim dalla sezione "Interfacce condivise" dello spec
Fase 1. ``EngineDisconnected`` vive qui (non in ``engine.py``) per evitare un
import circolare: le porte interaction/event la sollevano su socket caduto,
``engine.py`` la importerà da qui.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from backend.services.agent.events import AgentEvent
from backend.services.agent.models import ToolInvocation, ToolMeta


class EngineDisconnected(Exception):  # noqa: N818 — nome mandato verbatim dallo spec
    """Segnale interno: client WS caduto durante un'interazione."""


# --- tipi di supporto -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LLMTextDelta:
    """Delta di testo generato dal modello."""

    text: str


@dataclass(frozen=True, slots=True)
class LLMThinkingDelta:
    """Delta di ragionamento (thinking) generato dal modello."""

    text: str


@dataclass(frozen=True, slots=True)
class LLMToolCallDelta:
    """Chunk raw di una tool call in streaming (solo diagnostica/parity)."""

    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Utilizzo token/costo riportato dal modello."""

    input_tokens: int
    output_tokens: int
    cost: float


@dataclass(frozen=True, slots=True)
class LLMStepDone:
    """Fine di uno step LLM: motivo e tool call normalizzate."""

    finish_reason: str
    tool_calls: tuple[ToolInvocation, ...]


@dataclass(frozen=True, slots=True)
class LLMFailure:
    """Fallimento dello step LLM."""

    message: str
    status_code: int | None
    retryable: bool


LLMEvent = (
    LLMTextDelta | LLMThinkingDelta | LLMToolCallDelta | LLMUsage | LLMStepDone | LLMFailure
)


class GateAction(StrEnum):
    """Azione decisa dal gate dei permessi."""

    EXECUTE = "execute"
    DENY = "deny"
    CONFIRM = "confirm"


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """Verdetto del gate dei permessi per una tool call."""

    action: GateAction
    outcome: str
    reason: str | None = None
    risk_level: str | None = None
    description: str | None = None


class InteractionOutcome(StrEnum):
    """Esito di un'interazione utente (conferma, tool client, ask_user)."""

    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True, slots=True)
class ToolExecutionOutput:
    """Risultato dell'esecuzione di un tool."""

    ok: bool
    content: str
    error: str | None = None
    images: tuple[dict[str, str], ...] = ()
    payload: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """Esito di una compattazione del contesto."""

    performed: bool
    summary_text: str | None
    tokens_before: int
    tokens_after: int
    error: str | None = None


# --- le 7 porte --------------------------------------------------------------


class LLMPort(Protocol):
    """Streaming di uno step LLM."""

    def stream_step(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None,
        cancel: asyncio.Event,
    ) -> AsyncIterator[LLMEvent]: ...


class PermissionPort(Protocol):
    """Gate dei permessi, risolto per-call (invariante §6.9)."""

    async def decide(
        self, call: ToolInvocation, *, conversation_id: str,
    ) -> GateVerdict: ...


class InteractionPort(Protocol):
    """Interazioni con l'utente: conferma, esecuzione client-side, ask_user."""

    async def confirm_tool(
        self, call: ToolInvocation, *, verdict: GateVerdict, timeout_s: float,
        cancel: asyncio.Event,
    ) -> InteractionOutcome: ...

    async def run_client_tool(
        self, call: ToolInvocation, *, timeout_s: float, cancel: asyncio.Event,
    ) -> ToolExecutionOutput: ...

    async def ask_user(
        self, call: ToolInvocation, *, timeout_s: float, cancel: asyncio.Event,
    ) -> ToolExecutionOutput: ...


class EventPort(Protocol):
    """Emissione eventi verso l'esterno; best-effort, mai solleva."""

    async def emit(self, event: AgentEvent) -> None: ...


class PersistencePort(Protocol):
    """Persistenza del turno: step assistant, risultati tool, audit, storia."""

    async def save_assistant_step(
        self, *, content: str, thinking: str,
        tool_calls: tuple[ToolInvocation, ...],
    ) -> str: ...

    async def save_tool_result(
        self, *, call: ToolInvocation, content: str, status: str,
    ) -> None: ...

    async def save_audit(
        self, *, call: ToolInvocation, verdict: GateVerdict,
        interaction: InteractionOutcome | None,
    ) -> None: ...

    async def register_artifacts(
        self, *, call: ToolInvocation, output: ToolExecutionOutput,
    ) -> str | None: ...

    async def checkpoint(self) -> None: ...

    async def load_history(self) -> list[dict[str, Any]]: ...

    async def archive_compacted(
        self, *, summary_text: str, upto_message_ids: list[str],
    ) -> None: ...


class ContextPort(Protocol):
    """Gestione della finestra di contesto: stima, decisione, compattazione."""

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int: ...

    def should_compact(self, *, tokens: int, context_window: int) -> bool: ...

    async def compact(
        self, *, messages: list[dict[str, Any]], context_window: int,
    ) -> CompactionResult: ...


class ExecutionPort(Protocol):
    """Esecuzione dei tool (server-side); timeout per-tool interno all'adapter."""

    def describe(self, name: str) -> ToolMeta: ...

    async def execute(
        self, call: ToolInvocation, *, client_ip: str | None,
        conversation_id: str,
    ) -> ToolExecutionOutput: ...
