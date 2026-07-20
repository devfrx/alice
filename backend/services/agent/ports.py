"""Porte del motore (Protocol) e tipi di supporto — Interfacce condivise §ports.py.

Ogni tipo è copiato verbatim dalla sezione "Interfacce condivise" dello spec
Fase 1. ``EngineDisconnected`` vive qui (non in ``engine.py``) per evitare un
import circolare: le porte interaction/event la sollevano su socket caduto,
``engine.py`` la importerà da qui.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
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
    LLMTextDelta | LLMThinkingDelta | LLMUsage | LLMStepDone | LLMFailure
)


class GateAction(StrEnum):
    """Azione decisa dal gate dei permessi."""

    EXECUTE = "execute"
    DENY = "deny"
    CONFIRM = "confirm"


@dataclass(frozen=True, slots=True)
class ToolMetaInfo:
    """Provenienza del tool per il dialogo di conferma (wire ``tool_meta``).

    Origin ``"native"`` per i tool di piattaforma (tutti gli altri campi
    ``None``); ``"mcp"`` per i tool MCP, con i campi copiati dalla
    ``McpToolMeta`` della ``ToolDefinition``. È provenienza informativa:
    l'autorità operativa resta nei campi gate del verdetto.
    """

    origin: str  # "native" | "mcp"
    server: str | None = None
    annotated: bool | None = None
    read_only: bool | None = None
    destructive: bool | None = None
    trusted: bool | None = None

    def as_payload(self) -> dict[str, Any]:
        """Forma dict per il payload evento (chiavi = contratto wire)."""
        return {
            "origin": self.origin,
            "server": self.server,
            "annotated": self.annotated,
            "read_only": self.read_only,
            "destructive": self.destructive,
            "trusted": self.trusted,
        }


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """Verdetto del gate dei permessi per una tool call."""

    action: GateAction
    outcome: str
    reason: str | None = None
    risk_level: str | None = None
    description: str | None = None
    tool_meta: ToolMetaInfo | None = None


class InteractionOutcome(StrEnum):
    """Esito di un'interazione utente (conferma, tool client, ask_user)."""

    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DISCONNECTED = "disconnected"


class RememberScope(StrEnum):
    """Portata della scelta "ricorda la decisione" di una conferma approvata.

    Valori allineati al vocabolario wire ``RememberChoice``
    (``api/ws_schema/chat.py``): ``conversation`` crea una regola allow
    per-conversazione, ``persistent`` una regola allow globale.
    """

    NONE = "none"
    CONVERSATION = "conversation"
    PERSISTENT = "persistent"


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    """Esito completo di una conferma tool: outcome + scelta remember.

    ``remember`` è significativo SOLO con outcome ``APPROVED``: la porta lo
    normalizza a ``NONE`` in ogni altro caso (una call declinata non va mai
    ricordata).
    """

    outcome: InteractionOutcome
    remember: RememberScope = RememberScope.NONE


@dataclass(frozen=True, slots=True)
class ToolExecutionOutput:
    """Risultato dell'esecuzione di un tool.

    ``content_type`` è il MIME della tool response quando la piattaforma lo
    espone (``ToolResult.content_type``); ``None`` se non disponibile.
    """

    ok: bool
    content: str
    error: str | None = None
    images: tuple[dict[str, str], ...] = ()
    payload: dict[str, Any] | None = None
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """Esito di una compattazione del contesto."""

    performed: bool
    summary_text: str | None
    tokens_before: int
    tokens_after: int
    error: str | None = None
    kept_messages: tuple[dict[str, Any], ...] = ()
    archived_message_ids: tuple[str, ...] = ()


#: Callback di progresso tool: riceve il payload parziale del tool
#: (senza type/tool_name/execution_id, che aggiunge chi emette il frame).
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


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

    async def remember_approval(
        self, call: ToolInvocation, *, conversation_id: str,
        scope: RememberScope,
    ) -> None:
        """Persiste la scelta "ricorda" di una conferma APPROVATA.

        Best-effort: non solleva mai (un errore di persistenza della
        preferenza non deve far fallire la call appena approvata).
        ``scope=NONE`` è un no-op.
        """
        ...


class InteractionPort(Protocol):
    """Interazioni con l'utente: conferma, esecuzione client-side, ask_user.

    ``interaction_id`` è la chiave di correlazione wire della richiesta: il
    motore la genera, la emette nell'evento ``interaction.requested`` e la
    passa alla porta, che DEVE usarla per correlare la risposta del client.
    """

    async def confirm_tool(
        self, call: ToolInvocation, *, interaction_id: str, verdict: GateVerdict,
        timeout_s: float, cancel: asyncio.Event,
    ) -> ConfirmationResult: ...

    async def run_client_tool(
        self, call: ToolInvocation, *, interaction_id: str, timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput: ...

    async def ask_user(
        self, call: ToolInvocation, *, interaction_id: str, timeout_s: float,
        cancel: asyncio.Event,
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

    async def save_final_message(
        self, *, content: str, thinking: str,
        input_tokens: int, output_tokens: int, cost: float,
    ) -> str: ...

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
        on_progress: ProgressCallback | None = None,
    ) -> ToolExecutionOutput: ...
