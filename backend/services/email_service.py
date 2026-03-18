"""O.M.N.I.A. — Async email service (IMAP read + SMTP send)."""

from __future__ import annotations

import asyncio
import email
import email.header
import email.utils
import html
import re
import time
import uuid
from email.message import Message
from email.mime.text import MIMEText
from typing import Any

import aioimaplib
import aiosmtplib
from aioimaplib.aioimaplib import Abort as ImapAbort
from aioimaplib.aioimaplib import CommandTimeout as ImapTimeout
from bs4 import BeautifulSoup
from loguru import logger

from backend.core.config import EmailConfig
from backend.core.event_bus import EventBus, OmniaEvent

_TRUNCATION_SUFFIX = "\n[…troncato]"


class _LRUCache:
    """Minimal async-safe TTL cache (LRU eviction at max_size)."""

    def __init__(self, max_size: int = 200, ttl_s: int = 300) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._max_size = max_size
        self._ttl = ttl_s

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, ts = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if key not in self._store and len(self._store) >= self._max_size:
            oldest = min(self._store, key=lambda k: self._store[k][1])
            del self._store[oldest]
        self._store[key] = (value, time.monotonic())

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class EmailService:
    """Async IMAP/SMTP service for reading and sending emails locally.

    Credentials are never stored in plaintext; they are retrieved from
    the OS keyring (``use_keyring=True``, default) or from the
    ``OMNIA_EMAIL__PASSWORD`` environment variable (``use_keyring=False``).

    The service owns:
    - A persistent ``aioimaplib`` client for inbox operations
    - An ``aiosmtplib`` connection created per-send (stateless)
    - An in-memory TTL cache for recently fetched headers and bodies
    - An ``asyncio.Task`` for IMAP IDLE when ``imap_idle_enabled=True``
    """

    def __init__(self, config: EmailConfig, event_bus: EventBus) -> None:
        self._config = config
        self._bus = event_bus
        self._imap: aioimaplib.IMAP4_SSL | aioimaplib.IMAP4 | None = None
        self._password_resolved: str = ""
        self._cache = _LRUCache(max_size=200, ttl_s=config.cache_ttl_s)
        self._idle_task: asyncio.Task | None = None
        self._send_log: list[float] = []
        self._imap_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Resolve credentials, connect IMAP, start IDLE watcher."""
        if not self._config.imap_host:
            raise RuntimeError(
                "email.imap_host is required — configure it in default.yaml"
            )

        self._password_resolved = await self._resolve_password()

        self._imap = await self._connect_imap()
        logger.info(
            "EmailService connected to {}:{} as {}",
            self._config.imap_host, self._config.imap_port,
            self._config.username,
        )

        if self._config.imap_idle_enabled:
            self._idle_task = asyncio.create_task(
                self._idle_watcher(), name="email-idle-watcher",
            )

    async def close(self) -> None:
        """Cancel IDLE task and close IMAP connection."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass
        async with self._imap_lock:
            if self._imap:
                try:
                    await self._imap.logout()
                except Exception:
                    pass
                self._imap = None
            self._cache.clear()
        logger.info("EmailService closed")

    # ------------------------------------------------------------------
    # IMAP operations
    # ------------------------------------------------------------------

    async def fetch_inbox(
        self,
        *,
        folder: str = "INBOX",
        limit: int = 20,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch and return email headers from the specified folder."""
        limit = min(limit, self._config.max_fetch)
        cache_key = f"inbox:{folder}:{limit}:{unread_only}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        async with self._imap_lock:
            imap = await self._get_imap()
            sel = await imap.select(self._quote_folder(folder))
            if sel.result != "OK":
                raise ValueError(
                    f"Cannot select folder '{folder}': {sel.result}"
                )
            criteria = "UNSEEN" if unread_only else "ALL"
            response = await imap.uid_search(criteria)
            uids = (
                response.lines[0].split()
                if response.result == "OK"
                and response.lines
                and response.lines[0]
                else []
            )
            uids = uids[-limit:][::-1]

            headers = []
            for uid_bytes in uids:
                uid = (
                    uid_bytes.decode()
                    if isinstance(uid_bytes, bytes)
                    else uid_bytes
                )
                hdr = await self._fetch_header(uid, folder)
                if hdr:
                    headers.append(hdr)
                elif self._imap is None:
                    break  # connection died, stop fetching

        self._cache.set(cache_key, headers)
        return headers

    async def fetch_email(
        self, uid: str, *, folder: str = "INBOX",
    ) -> dict[str, Any] | None:
        """Fetch the full email (headers + plain-text body)."""
        cache_key = f"email:{folder}:{uid}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        uid = str(uid)
        async with self._imap_lock:
            imap = await self._get_imap()
            sel = await imap.select(self._quote_folder(folder))
            if sel.result != "OK":
                raise ValueError(
                    f"Cannot select folder '{folder}': {sel.result}"
                )
            try:
                result, data = await imap.uid(
                    "FETCH", uid, "(FLAGS RFC822)",
                )
            except (ImapTimeout, ImapAbort, OSError) as exc:
                logger.warning(
                    "IMAP timeout fetching email {}: {}", uid, exc,
                )
                self._imap = None
                raise ConnectionError(
                    f"IMAP timeout retrieving email {uid}",
                ) from exc
            if result != "OK" or not data or data[0] is None:
                return None

            raw = data[1] if len(data) > 1 else data[0]
            if isinstance(raw, (list, tuple)):
                raw = b"".join(
                    chunk for chunk in raw
                    if isinstance(chunk, (bytes, bytearray))
                )

        parsed = self._parse_email(
            uid, bytes(raw) if isinstance(raw, bytearray) else raw,
        )
        if parsed:
            flags_raw = (
                data[0].decode()
                if isinstance(data[0], (bytes, bytearray))
                else str(data[0])
            )
            parsed["is_read"] = "\\Seen" in flags_raw
            self._cache.set(cache_key, parsed)
        return parsed

    async def search(
        self,
        query: str,
        *,
        folder: str = "INBOX",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search emails using IMAP SEARCH criteria."""
        limit = min(limit, self._config.max_fetch)

        # Safety: strip characters that could inject extra IMAP commands
        safe_query = re.sub(r"[^\w \"@.:\-]", "", query)

        async with self._imap_lock:
            imap = await self._get_imap()
            sel = await imap.select(self._quote_folder(folder))
            if sel.result != "OK":
                raise ValueError(
                    f"Cannot select folder '{folder}': {sel.result}"
                )

            response = await imap.uid_search(safe_query)
            uids = (
                response.lines[0].split()
                if response.result == "OK"
                and response.lines
                and response.lines[0]
                else []
            )
            uids = uids[-limit:][::-1]

            headers = []
            for uid_bytes in uids:
                uid = (
                    uid_bytes.decode()
                    if isinstance(uid_bytes, bytes)
                    else uid_bytes
                )
                hdr = await self._fetch_header(uid, folder)
                if hdr:
                    headers.append(hdr)
                elif self._imap is None:
                    break  # connection died, stop fetching
        return headers

    async def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        *,
        reply_to_uid: str | None = None,
        folder: str = "INBOX",
    ) -> dict[str, Any]:
        """Send an email via SMTP with STARTTLS.

        Checks rate limit and allowed_recipients whitelist before sending.
        """
        # Rate limit check
        now = time.monotonic()
        self._send_log = [t for t in self._send_log if now - t < 3600]
        if len(self._send_log) >= self._config.rate_limit_send_per_hour:
            raise ValueError(
                f"Limite invii orari raggiunto "
                f"({self._config.rate_limit_send_per_hour}/ora). "
                "Riprova tra qualche minuto."
            )

        # Whitelist check
        if self._config.allowed_recipients:
            blocked = [
                r for r in to
                if r not in self._config.allowed_recipients
            ]
            if blocked:
                raise ValueError(
                    f"Destinatari non nella whitelist: "
                    f"{', '.join(blocked)}. "
                    "Modifica email.allowed_recipients in "
                    "default.yaml per abilitarli."
                )

        # Build message
        in_reply_to: str | None = None
        if reply_to_uid:
            original = await self.fetch_email(
                reply_to_uid, folder=folder,
            )
            if original:
                in_reply_to = original.get("message_id")

        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self._config.username
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        message_id = (
            f"<omnia-{uuid.uuid4()}@{self._config.smtp_host}>"
        )
        msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        try:
            smtp_kwargs: dict[str, Any] = dict(
                hostname=self._config.smtp_host,
                port=self._config.smtp_port,
                username=self._config.username,
                password=self._password_resolved,
                timeout=self._config.connection_timeout_s,
                use_tls=self._config.smtp_ssl,
                start_tls=not self._config.smtp_ssl,
            )
            await aiosmtplib.send(msg, **smtp_kwargs)
        except Exception as exc:
            raise RuntimeError(f"SMTP error: {exc}") from exc

        self._send_log.append(now)
        logger.info("Email inviata a {} — subject: {}", to, subject)
        await self._bus.emit(
            OmniaEvent.EMAIL_SENT,
            to=to,
            subject=subject,
            message_id=message_id,
        )
        return {"success": True, "message_id": message_id}

    async def mark_read(
        self, uid: str, *, folder: str = "INBOX", read: bool = True,
    ) -> bool:
        """Set or clear the \\Seen flag."""
        uid = str(uid)
        async with self._imap_lock:
            imap = await self._get_imap()
            sel = await imap.select(self._quote_folder(folder))
            if sel.result != "OK":
                raise ValueError(
                    f"Cannot select folder '{folder}': {sel.result}"
                )
            flag_cmd = "+FLAGS" if read else "-FLAGS"
            try:
                result, _ = await imap.uid(
                    "STORE", uid, flag_cmd, "\\Seen",
                )
            except (ImapTimeout, ImapAbort, OSError) as exc:
                logger.warning(
                    "IMAP timeout marking uid={}: {}", uid, exc,
                )
                self._imap = None
                raise ConnectionError(
                    f"IMAP timeout marking email {uid}",
                ) from exc
            self._cache.clear()
        return result == "OK"

    async def archive(
        self, uid: str, *, from_folder: str = "INBOX",
    ) -> bool:
        """Archive an email.

        Gmail: removing from the source folder is sufficient because
        every message already lives in All Mail.
        Other providers: COPY to the configured archive folder first,
        then delete from the source.
        """
        uid = str(uid)
        async with self._imap_lock:
            imap = await self._get_imap()
            sel = await imap.select(self._quote_folder(from_folder))
            if sel.result != "OK":
                raise ValueError(
                    f"Cannot select folder '{from_folder}': "
                    f"{sel.result}"
                )
            try:
                if not self._is_gmail:
                    dest = self._quote_folder(
                        self._config.archive_folder,
                    )
                    result, _ = await imap.uid("COPY", uid, dest)
                    if result != "OK":
                        return False
                await imap.uid(
                    "STORE", uid, "+FLAGS", "\\Deleted",
                )
                await imap.expunge()
            except (ImapTimeout, ImapAbort, OSError) as exc:
                logger.warning(
                    "IMAP timeout archiving uid={}: {}", uid, exc,
                )
                self._imap = None
                raise ConnectionError(
                    f"IMAP timeout archiving email {uid}",
                ) from exc
            self._cache.clear()
        return True

    async def list_folders(self) -> list[str]:
        """Return list of selectable IMAP folder names."""
        async with self._imap_lock:
            imap = await self._get_imap()
            try:
                _, data = await imap.list('""', '*')
            except (ImapTimeout, ImapAbort, OSError) as exc:
                logger.warning(
                    "IMAP timeout listing folders: {}", exc,
                )
                self._imap = None
                raise ConnectionError(
                    "IMAP timeout listing folders",
                ) from exc
        folders = []
        # Pattern: (flags) "delimiter" "folder_name"
        line_re = re.compile(r'\(([^)]*)\)\s+"/"\s+"(.+)"')
        for line in data:
            if isinstance(line, (bytes, bytearray)):
                line = line.decode("utf-8", errors="replace")
            match = line_re.search(line)
            if not match:
                continue
            flags_str, folder_name = match.group(1), match.group(2)
            if "\\Noselect" in flags_str:
                continue
            folders.append(folder_name)
        return folders

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _resolve_password(self) -> str:
        """Retrieve password from keyring or config field."""
        if self._config.use_keyring:
            try:
                import keyring

                pwd = await asyncio.to_thread(
                    keyring.get_password,
                    "omnia",
                    self._config.username,
                )
                if pwd:
                    return pwd
                logger.warning(
                    "Password non trovata nel keyring per '{}'. "
                    "Esegui: keyring set omnia {}",
                    self._config.username,
                    self._config.username,
                )
            except ImportError:
                logger.warning(
                    "Libreria 'keyring' non installata — "
                    "fallback a email.password dal config",
                )
        return self._config.password.get_secret_value()

    async def _connect_imap(
        self,
    ) -> aioimaplib.IMAP4_SSL | aioimaplib.IMAP4:
        """Open and authenticate an IMAP connection."""
        if self._config.imap_ssl:
            imap = aioimaplib.IMAP4_SSL(
                host=self._config.imap_host,
                port=self._config.imap_port,
                timeout=self._config.connection_timeout_s,
            )
        else:
            imap = aioimaplib.IMAP4(
                host=self._config.imap_host,
                port=self._config.imap_port,
                timeout=self._config.connection_timeout_s,
            )
        await imap.wait_hello_from_server()
        if not self._config.imap_ssl and hasattr(imap, "starttls"):
            await imap.starttls()
        response = await imap.login(self._config.username, self._password_resolved)
        if response.result != "OK":
            raise RuntimeError(
                f"IMAP LOGIN failed for {self._config.username}: {response.result} "
                f"{' '.join(response.lines)}"
            )
        return imap

    async def _get_imap(
        self,
    ) -> aioimaplib.IMAP4_SSL | aioimaplib.IMAP4:
        """Return the active IMAP connection, reconnecting if needed."""
        if self._imap is not None:
            try:
                await self._imap.noop()
            except Exception:
                logger.debug("IMAP connection stale, reconnecting")
                self._imap = None
        if self._imap is None:
            self._imap = await self._connect_imap()
        return self._imap

    async def _fetch_header(
        self, uid: str, folder: str,
    ) -> dict[str, Any] | None:
        """Fetch envelope headers for one UID."""
        cache_key = f"hdr:{folder}:{uid}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        imap = await self._get_imap()
        try:
            result, data = await imap.uid(
                "FETCH", uid, "(FLAGS RFC822.HEADER)",
            )
        except (ImapTimeout, ImapAbort, OSError) as exc:
            logger.warning(
                "IMAP timeout fetching header uid={}: {}", uid, exc,
            )
            self._imap = None
            return None
        if result != "OK" or not data or data[0] is None:
            return None

        raw = data[1] if len(data) > 1 else data[0]
        if isinstance(raw, (list, tuple)):
            raw = b"".join(
                chunk for chunk in raw
                if isinstance(chunk, (bytes, bytearray))
            )

        msg = email.message_from_bytes(
            bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw.encode(),
        )
        flags_raw = (
            data[0].decode()
            if isinstance(data[0], (bytes, bytearray))
            else str(data[0])
        )
        is_read = "\\Seen" in flags_raw

        hdr = {
            "uid": uid,
            "subject": self._decode_header(msg.get("Subject", "")),
            "from": self._decode_header(msg.get("From", "")),
            "to": self._decode_header(msg.get("To", "")),
            "date": msg.get("Date", ""),
            "message_id": msg.get("Message-ID", ""),
            "is_read": is_read,
            "has_attachments": False,
        }
        self._cache.set(cache_key, hdr)
        return hdr

    def _parse_email(
        self, uid: str, raw: bytes | bytearray,
    ) -> dict[str, Any]:
        """Parse a raw RFC822 email into a structured dict."""
        msg = email.message_from_bytes(raw)
        body = ""
        has_attachments = False

        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                disp = str(part.get("Content-Disposition", ""))
                if "attachment" in disp:
                    has_attachments = True
                    continue
                if ct == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(
                        charset, errors="replace",
                    )
                    break
                if ct == "text/html" and not body:
                    charset = part.get_content_charset() or "utf-8"
                    html_body = part.get_payload(decode=True).decode(
                        charset, errors="replace",
                    )
                    body = BeautifulSoup(
                        html_body, "html.parser",
                    ).get_text(separator=" ")
        else:
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                ct = msg.get_content_type()
                raw_body = payload.decode(charset, errors="replace")
                if ct == "text/html":
                    body = BeautifulSoup(
                        raw_body, "html.parser",
                    ).get_text(separator=" ")
                else:
                    body = raw_body

        # Truncate and sanitize
        body = html.unescape(body).strip()
        if len(body) > self._config.max_email_body_chars:
            body = (
                body[: self._config.max_email_body_chars]
                + _TRUNCATION_SUFFIX
            )

        return {
            "uid": uid,
            "subject": self._decode_header(msg.get("Subject", "")),
            "from": self._decode_header(msg.get("From", "")),
            "to": self._decode_header(msg.get("To", "")),
            "cc": self._decode_header(msg.get("Cc", "")),
            "date": msg.get("Date", ""),
            "message_id": msg.get("Message-ID", ""),
            "body": body,
            "has_attachments": has_attachments,
        }

    @staticmethod
    def _decode_header(raw: str) -> str:
        """Decode RFC2047-encoded email header."""
        parts = email.header.decode_header(raw)
        decoded = []
        for part, enc in parts:
            if isinstance(part, bytes):
                decoded.append(
                    part.decode(enc or "utf-8", errors="replace"),
                )
            else:
                decoded.append(part)
        return " ".join(decoded)

    @staticmethod
    def _quote_folder(folder: str) -> str:
        """Quote IMAP mailbox name for safe use in commands.

        aioimaplib does NOT auto-quote folder arguments, so names
        containing spaces or special characters (e.g.
        ``[Gmail]/Tutti i messaggi``) must be wrapped in double-quotes
        per RFC 3501.  INBOX is a protocol-level atom and never quoted.
        """
        if folder.upper() == "INBOX":
            return "INBOX"
        # Already quoted — pass through
        if folder.startswith('"') and folder.endswith('"'):
            return folder
        escaped = folder.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'

    @property
    def _is_gmail(self) -> bool:
        """True when the IMAP host belongs to Gmail."""
        return "gmail" in self._config.imap_host.lower()

    async def _idle_watcher(self) -> None:
        """Background task: IMAP IDLE for real-time new-mail events.

        Uses a dedicated IMAP connection (separate from the shared one
        used by fetch/search/mark operations) because IDLE locks the
        connection and prevents concurrent commands.
        """
        idle_imap = None
        while True:
            try:
                if idle_imap is None:
                    idle_imap = await self._connect_imap()
                await idle_imap.select("INBOX")
                idle_future = await idle_imap.idle_start(timeout=28 * 60)
                new_mail = False
                try:
                    await asyncio.wait_for(
                        idle_imap.wait_server_push(), timeout=29 * 60,
                    )
                    new_mail = True
                except asyncio.TimeoutError:
                    pass  # Normal keepalive cycle
                finally:
                    idle_imap.idle_done()
                    await asyncio.wait_for(idle_future, timeout=10)

                if new_mail:
                    logger.debug(
                        "EMAIL_RECEIVED notification from IMAP IDLE",
                    )
                    await self._bus.emit(
                        OmniaEvent.EMAIL_RECEIVED,
                        folder="INBOX",
                    )
                    async with self._imap_lock:
                        self._cache.clear()
            except asyncio.CancelledError:
                if idle_imap:
                    try:
                        await idle_imap.logout()
                    except Exception:
                        pass
                return
            except Exception as exc:
                logger.warning(
                    "IMAP IDLE error (retrying in 60s): {}", exc,
                )
                if idle_imap:
                    try:
                        await idle_imap.logout()
                    except Exception:
                        pass
                    idle_imap = None
                await asyncio.sleep(60)
