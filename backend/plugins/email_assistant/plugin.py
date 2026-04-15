"""AL\\CE Email Assistant plugin - expose email tools to the LLM."""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext

_READ_EMAILS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "folder": {
            "type": "string",
            "default": "INBOX",
            "description": (
                "IMAP folder name (default: INBOX). "
                "For Gmail use exact IMAP paths: "
                "\"[Gmail]/Sent Mail\", \"[Gmail]/Drafts\", "
                "\"[Gmail]/Trash\", \"[Gmail]/Spam\", "
                "\"[Gmail]/All Mail\". "
                "Use list_folders to discover available names."
            ),
        },
        "limit": {
            "type": "integer",
            "default": 20,
            "minimum": 1,
            "maximum": 50,
            "description": "Number of emails to fetch (max 50).",
        },
        "unread_only": {
            "type": "boolean",
            "default": False,
            "description": "If true, return only unread emails.",
        },
    },
    "required": [],
}

_GET_EMAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "uid": {
            "type": "string",
            "description": (
                "UID of the email to read (from read_emails list)."
            ),
        },
        "folder": {
            "type": "string",
            "default": "INBOX",
            "description": "IMAP folder containing the email.",
        },
    },
    "required": ["uid"],
}

_SEARCH_EMAILS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "IMAP SEARCH expression using standard keywords: "
                "FROM, TO, SUBJECT, TEXT, SINCE, BEFORE, UNSEEN, SEEN. "
                "Example: 'SUBJECT \"fattura\" FROM \"amazon.it\"'. "
                "Use only alphanumeric characters and IMAP keywords."
            ),
        },
        "folder": {"type": "string", "default": "INBOX"},
        "limit": {
            "type": "integer",
            "default": 20,
            "minimum": 1,
            "maximum": 50,
        },
    },
    "required": ["query"],
}

_SEND_EMAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of recipient email addresses.",
        },
        "subject": {
            "type": "string",
            "description": "Email subject line.",
        },
        "body": {
            "type": "string",
            "description": "Plain-text email body (no HTML).",
        },
        "reply_to_uid": {
            "type": "string",
            "description": (
                "UID of the email being replied to (optional). "
                "Sets In-Reply-To and References headers."
            ),
        },
        "folder": {
            "type": "string",
            "default": "INBOX",
            "description": (
                "Folder containing the email being replied to."
            ),
        },
    },
    "required": ["to", "subject", "body"],
}

_MARK_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "uid": {
            "type": "string",
            "description": "Email UID to mark.",
        },
        "folder": {"type": "string", "default": "INBOX"},
        "read": {
            "type": "boolean",
            "default": True,
            "description": (
                "True = mark as read, False = mark as unread."
            ),
        },
    },
    "required": ["uid"],
}

_ARCHIVE_EMAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "uid": {
            "type": "string",
            "description": "Email UID to archive.",
        },
        "from_folder": {"type": "string", "default": "INBOX"},
    },
    "required": ["uid"],
}

_LIST_FOLDERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}


class EmailPlugin(BasePlugin):
    """Plugin email — expose 7 LLM tools for email management.

    Delegates all I/O to ``ctx.email_service``.
    """

    plugin_name: str = "email_assistant"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Leggi, cerca e invia email via IMAP/SMTP locale."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 30

    def get_tools(self) -> list[ToolDefinition]:
        if self._ctx is None or not self._ctx.config.email.enabled:
            return []
        return [
            ToolDefinition(
                name="read_emails",
                description=(
                    "Elenca le email più recenti nella cartella "
                    "specificata. Restituisce una lista di intestazioni: "
                    "uid, subject, from, to, date, is_read. "
                    "Usa uid per leggere il corpo completo con get_email."
                ),
                parameters=_READ_EMAILS_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=50_000,
            ),
            ToolDefinition(
                name="get_email",
                description=(
                    "Legge il corpo completo di una email dato l'uid. "
                    "Il corpo HTML viene convertito automaticamente in testo "
                    "plain. Usa read_emails o search_emails per ottenere "
                    "gli uid."
                ),
                parameters=_GET_EMAIL_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=50_000,
            ),
            ToolDefinition(
                name="search_emails",
                description=(
                    "Cerca email usando criteri IMAP standard (FROM, TO, "
                    "SUBJECT, TEXT, SINCE, BEFORE, UNSEEN, SEEN). "
                    "Restituisce le intestazioni delle email "
                    "corrispondenti."
                ),
                parameters=_SEARCH_EMAILS_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=50_000,
            ),
            ToolDefinition(
                name="send_email",
                description=(
                    "Invia una email via SMTP. "
                    "Usa reply_to_uid per rispondere a una email "
                    "esistente. ATTENZIONE: operazione irreversibile — "
                    "richiede conferma esplicita."
                ),
                parameters=_SEND_EMAIL_SCHEMA,
                risk_level="dangerous",
                requires_confirmation=True,
                timeout_ms=50_000,
            ),
            ToolDefinition(
                name="mark_as_read",
                description=(
                    "Segna una email come letta o non letta. "
                    "Usa read=false per marcarla come non letta."
                ),
                parameters=_MARK_READ_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=50_000,
            ),
            ToolDefinition(
                name="archive_email",
                description=(
                    "Sposta una email nella cartella di archivio "
                    "configurata. L'operazione rimuove l'email dalla "
                    "cartella di origine. Richiede conferma prima "
                    "dell'esecuzione."
                ),
                parameters=_ARCHIVE_EMAIL_SCHEMA,
                risk_level="medium",
                requires_confirmation=True,
                timeout_ms=50_000,
            ),
            ToolDefinition(
                name="list_folders",
                description=(
                    "Elenca le cartelle IMAP disponibili. "
                    "Utile per scoprire i nomi esatti delle cartelle "
                    "(es. \"[Gmail]/Sent Mail\", \"[Gmail]/Drafts\"). "
                    "Chiama questo tool PRIMA di leggere cartelle "
                    "diverse da INBOX."
                ),
                parameters=_LIST_FOLDERS_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=50_000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the appropriate handler method."""
        if not self.ctx.config.email.enabled:
            return ToolResult.error(
                "Plugin email_assistant non abilitato.",
            )

        svc = self.ctx.email_service
        if svc is None:
            return ToolResult.error(
                "Email service non disponibile. "
                "Controlla la configurazione IMAP."
            )

        handlers = {
            "read_emails": self._read_emails,
            "get_email": self._get_email,
            "search_emails": self._search_emails,
            "send_email": self._send_email,
            "mark_as_read": self._mark_as_read,
            "archive_email": self._archive_email,
            "list_folders": self._list_folders,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return ToolResult.error(f"Tool sconosciuto: {tool_name}")
        return await handler(args)

    # ------------------------------------------------------------------
    # Dependency / health
    # ------------------------------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Report missing dependencies."""
        if self._ctx is None or self._ctx.email_service is None:
            return ["email_service"]
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED if email service is available."""
        if self._ctx is None:
            return ConnectionStatus.DISCONNECTED
        if not self._ctx.config.email.enabled:
            return ConnectionStatus.DISCONNECTED
        if self._ctx.email_service is not None:
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.ERROR

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _read_emails(
        self, args: dict[str, Any],
    ) -> ToolResult:
        svc = self.ctx.email_service
        cfg = self.ctx.config.email
        try:
            emails = await svc.fetch_inbox(
                folder=args.get("folder", "INBOX"),
                limit=int(args.get("limit", cfg.fetch_last_n)),
                unread_only=bool(args.get("unread_only", False)),
            )
        except ValueError as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:
            self.logger.error("read_emails failed: {}", exc)
            return ToolResult.error(f"Errore IMAP: {exc}")
        return ToolResult.ok(
            json.dumps(emails, ensure_ascii=False, default=str),
        )

    async def _get_email(
        self, args: dict[str, Any],
    ) -> ToolResult:
        uid = (args.get("uid") or "").strip()
        if not uid:
            return ToolResult.error("Missing required parameter: uid")
        svc = self.ctx.email_service
        try:
            mail = await svc.fetch_email(
                uid, folder=args.get("folder", "INBOX"),
            )
        except ValueError as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:
            self.logger.error("get_email failed: {}", exc)
            return ToolResult.error(f"Errore IMAP: {exc}")
        if mail is None:
            return ToolResult.error(
                f"Email non trovata: {uid}",
            )
        return ToolResult.ok(
            json.dumps(mail, ensure_ascii=False, default=str),
        )

    async def _search_emails(
        self, args: dict[str, Any],
    ) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult.error("Missing required parameter: query")
        svc = self.ctx.email_service
        cfg = self.ctx.config.email
        try:
            results = await svc.search(
                query,
                folder=args.get("folder", "INBOX"),
                limit=int(args.get("limit", cfg.fetch_last_n)),
            )
        except ValueError as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:
            self.logger.error("search_emails failed: {}", exc)
            return ToolResult.error(f"Errore IMAP: {exc}")
        return ToolResult.ok(
            json.dumps(results, ensure_ascii=False, default=str),
        )

    async def _send_email(
        self, args: dict[str, Any],
    ) -> ToolResult:
        to = args.get("to")
        if not to or not isinstance(to, list):
            return ToolResult.error("Missing required parameter: to")
        subject = args.get("subject", "")
        if not subject:
            return ToolResult.error("Missing required parameter: subject")
        body = args.get("body", "")
        if not body:
            return ToolResult.error("Missing required parameter: body")
        svc = self.ctx.email_service
        try:
            result = await svc.send(
                to=to,
                subject=subject,
                body=body,
                reply_to_uid=args.get("reply_to_uid"),
                folder=args.get("folder", "INBOX"),
            )
            return ToolResult.ok(
                json.dumps(result, ensure_ascii=False),
            )
        except ValueError as exc:
            return ToolResult.error(str(exc))
        except RuntimeError as exc:
            self.logger.error("SMTP send failed: {}", exc)
            return ToolResult.error(f"Errore SMTP: {exc}")

    async def _mark_as_read(
        self, args: dict[str, Any],
    ) -> ToolResult:
        uid = (args.get("uid") or "").strip()
        if not uid:
            return ToolResult.error("Missing required parameter: uid")
        svc = self.ctx.email_service
        try:
            ok = await svc.mark_read(
                uid,
                folder=args.get("folder", "INBOX"),
                read=bool(args.get("read", True)),
            )
        except ValueError as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:
            self.logger.error("mark_as_read failed: {}", exc)
            return ToolResult.error(f"Errore IMAP: {exc}")
        status = "letta" if args.get("read", True) else "non letta"
        if ok:
            return ToolResult.ok(
                f"Email {uid} marcata come {status}.",
            )
        return ToolResult.error(
            f"Impossibile aggiornare email {uid}.",
        )

    async def _archive_email(
        self, args: dict[str, Any],
    ) -> ToolResult:
        uid = (args.get("uid") or "").strip()
        if not uid:
            return ToolResult.error("Missing required parameter: uid")
        svc = self.ctx.email_service
        try:
            ok = await svc.archive(
                uid,
                from_folder=args.get("from_folder", "INBOX"),
            )
        except ValueError as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:
            self.logger.error("archive_email failed: {}", exc)
            return ToolResult.error(f"Errore IMAP: {exc}")
        if ok:
            return ToolResult.ok(
                f"Email {uid} archiviata.",
            )
        return ToolResult.error(
            f"Impossibile archiviare email {uid}.",
        )

    async def _list_folders(
        self, args: dict[str, Any],
    ) -> ToolResult:
        svc = self.ctx.email_service
        try:
            folders = await svc.list_folders()
        except Exception as exc:
            self.logger.error("list_folders failed: {}", exc)
            return ToolResult.error(f"Errore IMAP: {exc}")
        return ToolResult.ok(
            json.dumps(folders, ensure_ascii=False),
        )
