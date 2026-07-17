"""Adapter ``PersistencePort`` -> SQLModel/``AsyncSession`` (piattaforma).

Consuma ``backend/db/models.py`` (``Message``, ``ToolConfirmationAudit``) e,
opzionalmente, ``ArtifactRegistry.register_from_tool_result``
(``backend/services/artifacts/registry.py``). Nessun import da
``backend/services/turn/`` (principio pilastro — legacy solo come checklist
di invarianti, mai come sorgente di comportamento copiato).

Unit-of-work esplicita (invariante §6.15): ``save_assistant_step`` e
``save_tool_result`` fanno solo ``session.flush()`` (serve l'id subito per
correlare assistant/tool via ``tool_call_id``, ma NIENTE commit). L'unico
punto che fa ``session.commit()`` è :meth:`SqlModelPersistence.checkpoint`.
Motivazione: la connessione SQLite di scrittura è condivisa con i plugin
(ognuno apre la propria sessione/connessione verso lo stesso file), quindi
tenere una transazione aperta più a lungo del necessario rischia
``database is locked``; il motore chiama ``checkpoint()`` ai confini di step
espliciti dove è sicuro rilasciare il write-lock.

Divergenze dal brief (documentate, non "corrette" silenziosamente):

- **Nessuna risoluzione di bare tool name.** Il brief chiede di delegare a
  ``register_from_tool_result`` "con la risoluzione del bare tool name come
  fa il registry stesso" — ma ``ArtifactRegistry.register_from_tool_result``
  / ``parse_tool_payload`` (``backend/services/artifacts/registry.py:129``,
  ``backend/services/artifacts/parsers.py:79``) fanno un lookup ESATTO nel
  dizionario ``_PARSERS`` per ``tool_name``, senza alcuna risoluzione di
  suffisso: la piattaforma non "risolve" nulla a questo livello, è il
  chiamante (nel path legacy, ``services/turn/tool_loop.py`` — non letto,
  vietato dal principio pilastro) a passare già il nome risolto. Questo
  adapter non ha un ``ToolRegistry`` iniettato (solo ``artifact_registry``,
  come da firma del costruttore nel brief) e ``ToolInvocation`` (``models.py``)
  porta un solo campo ``name`` — nessun "bare" vs "namespaced" distinti.
  Si passa quindi ``call.name`` verbatim: se il modello invoca un tool con un
  nome bare che non coincide con la chiave registrata nei parser (es.
  ``"cad_generate"``), l'artifact non verrà riconosciuto — comportamento
  onesto e documentato, non silenziosamente "corretto" inventando una
  euristica di risoluzione qui.
- **Nessuna persistenza immagini su disco.** Il Task 12 (vedi
  ``.superpowers/sdd/task-12-report.md``) ha stabilito che
  ``ToolExecutionOutput.images`` è SEMPRE ``()`` — la piattaforma
  (``ToolResult``, ``backend/core/plugin_models.py:169``) non ha un campo
  immagini separato, e ``ArtifactRegistry.register_from_tool_result`` non
  accetta né consuma immagini: consuma solo ``payload`` (il dict originale
  del risultato tool) + ``content_type``. I file (incluse eventuali immagini
  generate, es. CAD/3D) sono già scritti su disco dal tool stesso PRIMA che
  il risultato arrivi qui (``ArtifactRegistry`` "non possiede altro: gli
  strumenti sottostanti restano responsabili di *produrre* il file su disco;
  il registry si limita a registrarne l'esistenza" —
  ``backend/services/artifacts/registry.py:76-82``). Non c'è quindi nulla da
  implementare per "immagini persistite su disco prima della registrazione":
  il payload (``output.payload``) è già la struttura pronta che i parser si
  aspettano (es. ``file_path``), e la si passa così com'è.
- **``message_id`` per l'artifact.** ``save_tool_result`` ritorna ``None``
  per contratto di Port, quindi ``register_artifacts`` non riceve l'id della
  riga ``tool`` appena creata. Questo adapter tiene una mappa interna
  ``call_id -> message_id`` popolata da ``save_tool_result`` e la consulta in
  ``register_artifacts`` (best-effort: ``None`` se ``save_tool_result`` non è
  mai stato chiamato per quel ``call_id``, es. in test che chiamano
  ``register_artifacts`` isolatamente).
- **``ToolConfirmationAudit`` non ha campi 1:1 con ``save_audit``.** La
  tabella reale (``backend/db/models.py:197``) traccia
  ``execution_id``/``tool_name``/``args_json``/``risk_level``/
  ``user_approved``/``rejection_reason``/``thinking_content`` — non
  "verdict"/"interaction" come oggetti. Mapping adottato:
    * ``execution_id`` = ``call.call_id`` (già un ID univoco per-call, stesso
      ruolo che l'audit vuole "per correlazione con il tool loop").
    * ``risk_level`` = ``verdict.risk_level`` se presente, altrimenti
      ``"safe"`` (fallback necessario: la colonna ha un CHECK constraint
      NOT NULL su un vocabolario fisso e ``GateVerdict.risk_level`` è
      opzionale — Task 12 nota che è "``None`` se il tool non è risolvibile
      nel registry").
    * ``user_approved``/``rejection_reason``: se ``interaction`` è fornito,
      ``True`` solo per ``InteractionOutcome.APPROVED``, altrimenti
      ``rejection_reason = interaction.value``. Se ``interaction`` è
      ``None`` (nessuna interazione utente necessaria: la call non
      richiedeva conferma), si deriva da ``verdict.action``: ``DENY`` ->
      non approvato (``rejection_reason = verdict.reason or "denied"``),
      altrimenti approvato implicitamente (execute diretto).
    * ``thinking_content`` resta ``None``: la Port ``save_audit`` non porta
      il testo di ragionamento (lo fa ``save_assistant_step`` separatamente).
- **``version_index`` di default.** ``Message.version_index`` non è
  nullable (default ``0``); quando il costruttore riceve ``version_index=None``
  si applica ``0`` esplicitamente (stesso default del modello).
- **Marcatore del messaggio di riassunto.** ``archive_compacted`` marca
  ``role="assistant"``, ``is_context_summary=True`` e prefissa il contenuto
  con ``"[Context summary of N earlier messages]:\n..."`` — lo stesso
  marcatore usato oggi dalla piattaforma (verificato in
  ``backend/api/routes/chat/_assembly.py:707-717`` e
  ``backend/api/routes/chat/_persist.py:390-399``, entrambi fuori da
  ``services/turn/``), così un summary scritto da questo motore resta
  indistinguibile da uno scritto dal path legacy per qualunque consumer a
  valle (UI, export, backfill).
- **Shape di ``tool_calls`` in formato OpenAI.** Non esiste un helper di
  piattaforma "fair game" (fuori da ``services/turn/``) che costruisca la
  colonna JSON ``Message.tool_calls`` a partire da tool call normalizzate:
  ``backend/api/routes/chat/_assembly.py:387`` la legge (``m.tool_calls``)
  già pronta e la passa così com'è nel dict OpenAI-shape, senza mai
  costruirla. Questo adapter la costruisce nel formato OpenAI standard
  (``[{"id", "type": "function", "function": {"name", "arguments"}}]``,
  ``arguments`` = ``call.raw_args`` grezzo) — lo stesso formato che
  ``load_history`` deve poi restituire per il round-trip col modello.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from backend.db.models import Message, ToolConfirmationAudit
from backend.services.agent.models import ToolInvocation
from backend.services.agent.ports import (
    GateAction,
    GateVerdict,
    InteractionOutcome,
    ToolExecutionOutput,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from backend.services.artifacts.registry import ArtifactRegistry


def _to_uuid(value: str | uuid.UUID) -> uuid.UUID:
    """Return *value* as a :class:`uuid.UUID`, accepting either type."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class SqlModelPersistence:
    """Implementa ``PersistencePort`` sopra una ``AsyncSession`` SQLModel."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        conversation_id: str,
        artifact_registry: ArtifactRegistry | None,
        version_group_id: str | None,
        version_index: int | None,
    ) -> None:
        """Inizializza l'adapter per UNA conversazione/turno.

        Args:
            session: Sessione async SQLModel condivisa per l'intero turno
                (unit-of-work: ``flush()`` nei ``save_*``, ``commit()`` solo
                in :meth:`checkpoint`).
            conversation_id: ID della conversazione (str o UUID già valido).
            artifact_registry: Registry di piattaforma per gli artifact, o
                ``None`` per disabilitare :meth:`register_artifacts` (no-op).
            version_group_id: Applicato alla riga ``Message`` assistant, se
                fornito (``Message.version_group_id``).
            version_index: Applicato alla riga ``Message`` assistant; ``None``
                mappa al default del modello (``0``).
        """
        self._session = session
        self._conversation_id = _to_uuid(conversation_id)
        self._artifact_registry = artifact_registry
        self._version_group_id = (
            _to_uuid(version_group_id) if version_group_id else None
        )
        self._version_index = version_index
        # call_id -> id della riga "tool" appena salvata (per register_artifacts).
        self._tool_message_ids: dict[str, uuid.UUID] = {}

    async def save_assistant_step(
        self, *, content: str, thinking: str,
        tool_calls: tuple[ToolInvocation, ...],
    ) -> str:
        """Persiste lo step assistant (flush, NIENTE commit — vedi §6.15).

        L'ID torna subito disponibile (via ``flush()``) perché il chiamante
        ne ha bisogno per correlare eventuali riferimenti successivi, anche
        se la correlazione assistant/tool avviene tramite ``call_id`` (non
        tramite l'ID della riga) — invariante §6.1.
        """
        tool_calls_json: list[dict[str, Any]] | None = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.raw_args},
            }
            for call in tool_calls
        ] or None
        message = Message(
            conversation_id=self._conversation_id,
            role="assistant",
            content=content,
            thinking_content=thinking or None,
            tool_calls=tool_calls_json,
            version_group_id=self._version_group_id,
            version_index=(
                self._version_index if self._version_index is not None else 0
            ),
        )
        self._session.add(message)
        await self._session.flush()
        return str(message.id)

    async def save_tool_result(
        self, *, call: ToolInvocation, content: str, status: str,
    ) -> None:
        """Persiste il risultato tool, correlato via ``tool_call_id`` (§6.1).

        ``status`` non ha una colonna dedicata su ``Message`` — la
        piattaforma non distingue ok/errore a livello di riga (l'errore
        finisce nel ``content`` stesso, come fa ``ToolRegistryAdapter``
        (Task 12) serializzando ``ToolResult`` in stringa). Non introduciamo
        una colonna qui: fuori scope per la Port (che non lo chiede) e per
        questo task (schema fisso, nessuna migrazione).
        """
        message = Message(
            conversation_id=self._conversation_id,
            role="tool",
            content=content,
            tool_call_id=call.call_id,
        )
        self._session.add(message)
        await self._session.flush()
        self._tool_message_ids[call.call_id] = message.id

    async def save_audit(
        self, *, call: ToolInvocation, verdict: GateVerdict,
        interaction: InteractionOutcome | None,
    ) -> None:
        """Riga di audit — mapping verso lo schema reale (vedi docstring modulo)."""
        if interaction is not None:
            approved = interaction is InteractionOutcome.APPROVED
            rejection_reason = None if approved else interaction.value
        else:
            approved = verdict.action is not GateAction.DENY
            rejection_reason = None if approved else (verdict.reason or "denied")

        audit = ToolConfirmationAudit(
            conversation_id=self._conversation_id,
            execution_id=call.call_id,
            tool_name=call.name,
            args_json=json.dumps(call.args, ensure_ascii=False),
            risk_level=verdict.risk_level or "safe",
            user_approved=approved,
            rejection_reason=rejection_reason,
        )
        self._session.add(audit)
        await self._session.flush()

    async def register_artifacts(
        self, *, call: ToolInvocation, output: ToolExecutionOutput,
    ) -> str | None:
        """Delega ad ``ArtifactRegistry.register_from_tool_result`` (§6.4.11).

        No-op (``None``) se: nessun registry iniettato, il tool ha fallito
        (``output.ok is False``), o il risultato non porta un ``payload``
        strutturato (i parser lavorano su dict, non su stringhe grezze — vedi
        docstring di modulo per il perché non serve gestione immagini qui).
        """
        if self._artifact_registry is None or not output.ok or output.payload is None:
            return None
        message_id = self._tool_message_ids.get(call.call_id)
        artifact = await self._artifact_registry.register_from_tool_result(
            conversation_id=self._conversation_id,
            message_id=message_id,
            tool_call_id=call.call_id,
            tool_name=call.name,
            payload=output.payload,
            content_type=None,
        )
        return str(artifact.id) if artifact is not None else None

    async def checkpoint(self) -> None:
        """Unico punto di ``commit()`` del turno (invariante §6.15).

        I ``save_*`` fanno solo ``flush()`` per tenere la transazione
        scrivibile aperta il minimo indispensabile: la connessione SQLite di
        scrittura è condivisa con i plugin (ognuno apre la propria sessione
        verso lo stesso file DB), quindi una transazione aperta a lungo
        rischia ``database is locked`` quando un plugin prova a scrivere in
        parallelo. ``checkpoint()`` rilascia esplicitamente il write-lock ai
        confini di step scelti dal motore (mai implicitamente).
        """
        await self._session.commit()

    async def load_history(self) -> list[dict[str, Any]]:
        """Storia della conversazione in formato OpenAI dict (§6.4.11).

        Esclude le righe ``context_excluded=True`` (archiviate da
        :meth:`archive_compacted`); il filtro è fatto in Python dopo il
        fetch (non con un ``WHERE context_excluded = false`` SQL) per
        evitare le insidie di confronto booleano SQLite/SQLAlchemy — a
        questa scala (una conversazione) il costo è trascurabile.
        """
        stmt = (
            select(Message)
            .where(Message.conversation_id == self._conversation_id)
            .order_by(col(Message.created_at))
        )
        rows = (await self._session.exec(stmt)).all()
        history: list[dict[str, Any]] = []
        for message in rows:
            if message.context_excluded:
                continue
            entry: dict[str, Any] = {
                "role": message.role,
                "content": message.content,
            }
            if message.tool_calls:
                entry["tool_calls"] = message.tool_calls
            if message.tool_call_id:
                entry["tool_call_id"] = message.tool_call_id
            history.append(entry)
        return history

    async def archive_compacted(
        self, *, summary_text: str, upto_message_ids: list[str],
    ) -> None:
        """UPDATE ``context_excluded=True`` sugli ID + INSERT del summary.

        Il messaggio di riassunto usa lo stesso marcatore della piattaforma
        (``role="assistant"``, ``is_context_summary=True``, prefisso
        ``"[Context summary of N earlier messages]:"``) — vedi docstring di
        modulo per le citazioni file:riga.
        """
        ids = [_to_uuid(mid) for mid in upto_message_ids]
        if ids:
            stmt = select(Message).where(col(Message.id).in_(ids))
            rows = (await self._session.exec(stmt)).all()
            for message in rows:
                message.context_excluded = True
                self._session.add(message)

        summary_message = Message(
            conversation_id=self._conversation_id,
            role="assistant",
            content=(
                f"[Context summary of {len(upto_message_ids)} earlier "
                f"messages]:\n{summary_text}"
            ),
            is_context_summary=True,
        )
        self._session.add(summary_message)
        await self._session.flush()
