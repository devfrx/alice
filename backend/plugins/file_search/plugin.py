"""AL\\CE — File Search plugin.

Exposes six tools for searching, reading, writing and editing files on
the local filesystem with path access control.  All paths are validated
against allowed/forbidden root directories before any operation.
"""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import os
import string
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.file_search.read_tracker import ReadState, ReadTracker
from backend.plugins.file_search.readers import (
    _DOCX_AVAILABLE,
    _IMAGE_CONTENT_TYPES,
    _PDF_AVAILABLE,
    read_text_file,
)
from backend.plugins.file_search.searcher import (
    _validate_path,
    search_files,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext

_EXECUTABLE_EXTENSIONS: set[str] = {
    ".exe", ".bat", ".cmd", ".ps1", ".msi",
    ".vbs", ".scr", ".com", ".pif",
}


class FileSearchPlugin(BasePlugin):
    """Search and read files on the local filesystem with access control."""

    plugin_name: str = "file_search"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Search, read and write files on the local filesystem "
        "with path access control."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 25

    def __init__(self) -> None:
        super().__init__()
        self._allowed_paths: list[Path] = []
        self._forbidden_paths: list[Path] = []
        self._read_tracker = ReadTracker()

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Initialize the plugin and compute allowed/forbidden paths.

        If no allowed paths are configured, defaults to the user's home,
        Desktop, Documents and Downloads directories.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)

        cfg = ctx.config.file_search

        # Compute allowed paths
        if cfg.allowed_paths:
            self._allowed_paths = [Path(p) for p in cfg.allowed_paths]
        else:
            # Default: all available drive roots on Windows,
            # or the user home on other platforms.
            if sys.platform == "win32":
                drives = [
                    Path(f"{letter}:\\")
                    for letter in string.ascii_uppercase
                    if Path(f"{letter}:\\").exists()
                ]
                self._allowed_paths = drives if drives else [Path.home()]
            else:
                self._allowed_paths = [Path.home()]

        # Compute forbidden paths
        self._forbidden_paths = [Path(p) for p in cfg.forbidden_paths]

        logger.info(
            "file_search: allowed_paths={}, forbidden_paths={}",
            [str(p) for p in self._allowed_paths],
            [str(p) for p in self._forbidden_paths],
        )

    # -- Tools -------------------------------------------------------------

    # Maximum bytes for a single write operation
    _MAX_WRITE_BYTES: int = 1_048_576  # 1 MiB

    def get_tools(self) -> list[ToolDefinition]:
        """Return the five file-search tool definitions.

        Returns:
            A list of ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="search_files",
                description=(
                    "Search for files by name on the local filesystem. "
                    "Returns matching file paths, sizes and dates. "
                    "Optionally filter by directory and file extensions."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Substring to match in file names "
                                "(case-insensitive)."
                            ),
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "Optional root directory to restrict "
                                "the search to."
                            ),
                        },
                        "extensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional list of file extensions to "
                                "filter by (e.g. ['.txt', '.pdf'])."
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": (
                                "Maximum number of results. "
                                "Defaults to configured max_results."
                            ),
                            "minimum": 1,
                            "maximum": 200,
                        },
                    },
                    "required": ["query"],
                },
                result_type="json",
                risk_level="safe",
                capabilities=("fs_read",),
                path_args=("path",),
                timeout_ms=60_000,
            ),
            ToolDefinition(
                name="get_file_info",
                description=(
                    "Get metadata about a file: name, size, dates, "
                    "MIME type. Does not read file content."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file.",
                        },
                    },
                    "required": ["path"],
                },
                result_type="json",
                risk_level="safe",
                capabilities=("fs_read",),
                path_args=("path",),
                timeout_ms=3_000,
            ),
            ToolDefinition(
                name="read_text_file",
                description=(
                    "Read the content of a file. Supports plain text "
                    "formats (.txt, .md, .py, .json, etc.), PDF, DOCX and "
                    "images (.png, .jpg, .jpeg, .gif, .webp — returned as "
                    "base64, subject to a size cap). Text files are "
                    "returned with cat -n style line numbers; use 'offset' "
                    "and 'limit' to read a window of lines and, when the "
                    "result is truncated, continue from the returned "
                    "'next_offset'. Line numbering and offset/limit apply "
                    "to text files only — PDF and DOCX return plain "
                    "extracted text. Content may be truncated for large "
                    "files."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file.",
                        },
                        "offset": {
                            "type": "integer",
                            "description": (
                                "1-based line number to start reading "
                                "from (text files only). Defaults to 1."
                            ),
                            "minimum": 1,
                            "default": 1,
                        },
                        "limit": {
                            "type": "integer",
                            "description": (
                                "Maximum number of lines to read (text "
                                "files only). Default 2000."
                            ),
                            "minimum": 1,
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": (
                                "Maximum characters to return. "
                                "Defaults to configured max_content_chars."
                            ),
                            "minimum": 100,
                            "maximum": 50_000,
                        },
                    },
                    "required": ["path"],
                },
                result_type="json",
                risk_level="medium",
                requires_confirmation=True,
                capabilities=("fs_read",),
                path_args=("path",),
                timeout_ms=15_000,
            ),
            ToolDefinition(
                name="open_file",
                description=(
                    "Open a file with the system's default application "
                    "(e.g. open a PDF in the default PDF viewer)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file.",
                        },
                    },
                    "required": ["path"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
                capabilities=("fs_read",),
                path_args=("path",),
                timeout_ms=5_000,
            ),
            ToolDefinition(
                name="write_text_file",
                description=(
                    "Create a new text file, or overwrite an existing "
                    "one, with the given content. The path must be "
                    "inside an allowed directory. Overwriting an "
                    "existing file requires having read it earlier in "
                    "this conversation with read_text_file (re-read if "
                    "it changed on disk since); for a small, targeted "
                    "change prefer edit_text_file instead. Executable "
                    "extensions are blocked."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "Absolute path for the file to create "
                                "or overwrite."
                            ),
                        },
                        "content": {
                            "type": "string",
                            "description": (
                                "Text content to write into the file."
                            ),
                        },
                    },
                    "required": ["path", "content"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
                capabilities=("fs_write",),
                path_args=("path",),
                timeout_ms=10_000,
            ),
            ToolDefinition(
                name="edit_text_file",
                description=(
                    "Perform an exact-string replacement in a text file. "
                    "'old_string' is raw file content WITHOUT the "
                    "'     N\\t' line-number prefix shown by "
                    "read_text_file. It must match exactly one occurrence "
                    "in the file (extend the surrounding context to make "
                    "it unique) unless replace_all=true, which replaces "
                    "every occurrence. The file must have been read with "
                    "read_text_file earlier in this conversation, and "
                    "re-read if it changed on disk since."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file.",
                        },
                        "old_string": {
                            "type": "string",
                            "description": (
                                "Exact text to replace, without line-number "
                                "prefixes. Must be unique in the file unless "
                                "replace_all=true."
                            ),
                        },
                        "new_string": {
                            "type": "string",
                            "description": (
                                "Replacement text (may be empty to delete "
                                "old_string)."
                            ),
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": (
                                "Replace every occurrence of old_string "
                                "instead of requiring uniqueness."
                            ),
                            "default": False,
                        },
                    },
                    "required": ["path", "old_string", "new_string"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
                capabilities=("fs_write",),
                path_args=("path",),
                timeout_ms=10_000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested tool.

        Args:
            tool_name: One of the six file-search tool names.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the JSON payload or an error message.
        """
        start = time.perf_counter()

        handlers = {
            "search_files": self._exec_search_files,
            "get_file_info": self._exec_get_file_info,
            "read_text_file": self._exec_read_text_file,
            "open_file": self._exec_open_file,
            "write_text_file": self._exec_write_text_file,
            "edit_text_file": self._exec_edit_text_file,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            return ToolResult.error(f"Unknown tool: {tool_name}")

        try:
            result = await handler(args, context)
        except ValueError as exc:
            return ToolResult.error(str(exc))
        except Exception as exc:
            logger.error("file_search tool '{}' failed: {}", tool_name, exc)
            return ToolResult.error(f"Internal error: {exc}")

        elapsed_ms = (time.perf_counter() - start) * 1000

        if isinstance(result, ToolResult):
            result.execution_time_ms = elapsed_ms
            return result

        return ToolResult.ok(
            content=result,
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    # -- Dependency / health -----------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Report missing optional dependencies.

        Returns:
            A list of missing package names (pdfplumber, python-docx).
        """
        missing: list[str] = []
        if not _PDF_AVAILABLE:
            missing.append("pdfplumber")
        if not _DOCX_AVAILABLE:
            missing.append("python-docx")
        return missing

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED — filesystem is always local.

        Returns:
            ``ConnectionStatus.CONNECTED``.
        """
        return ConnectionStatus.CONNECTED

    # -- Private tool handlers ---------------------------------------------

    async def _exec_search_files(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> list[dict[str, Any]]:
        """Execute the search_files tool.

        Args:
            args: Must contain "query"; optionally "path", "extensions",
                  "max_results".
            context: Execution metadata (unused).

        Returns:
            A list of file-info dicts.
        """
        query: str = args.get("query", "")
        if not query:
            raise ValueError("'query' parameter is required")

        cfg = self.ctx.config.file_search
        max_results: int = min(
            int(args.get("max_results", cfg.max_results)),
            cfg.max_results,
        )

        # Determine search roots
        if "path" in args and args["path"]:
            validated = _validate_path(
                args["path"],
                self._allowed_paths,
                self._forbidden_paths,
                cfg.follow_symlinks,
            )
            roots = [validated]
        else:
            roots = self._allowed_paths

        extensions: list[str] | None = args.get("extensions")

        return await search_files(
            query=query,
            roots=roots,
            extensions=extensions,
            max_results=max_results,
            forbidden=self._forbidden_paths,
            follow_symlinks=cfg.follow_symlinks,
        )

    async def _exec_get_file_info(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Execute the get_file_info tool.

        Args:
            args: Must contain "path".
            context: Execution metadata (unused).

        Returns:
            A dict with file metadata.
        """
        raw_path: str = args.get("path", "")
        if not raw_path:
            raise ValueError("'path' parameter is required")

        cfg = self.ctx.config.file_search
        resolved = _validate_path(
            raw_path,
            self._allowed_paths,
            self._forbidden_paths,
            cfg.follow_symlinks,
        )

        def _gather_metadata() -> dict[str, Any]:
            if not resolved.exists():
                raise ValueError(f"File not found: {resolved}")

            stat = resolved.stat()
            mime_type, _ = mimetypes.guess_type(str(resolved))
            created_dt = datetime.fromtimestamp(
                stat.st_ctime, tz=UTC,
            )
            modified_dt = datetime.fromtimestamp(
                stat.st_mtime, tz=UTC,
            )

            return {
                "path": str(resolved),
                "name": resolved.name,
                "size_bytes": stat.st_size,
                "created_iso": created_dt.isoformat(),
                "modified_iso": modified_dt.isoformat(),
                "extension": resolved.suffix,
                "mime_type": mime_type or "application/octet-stream",
                "is_file": resolved.is_file(),
                "is_dir": resolved.is_dir(),
            }

        return await asyncio.to_thread(_gather_metadata)

    async def _exec_read_text_file(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any] | ToolResult:
        """Execute the read_text_file tool.

        Every successful read (text, PDF/DOCX and images alike) is
        registered in the per-conversation ``ReadTracker`` so that a
        later ``edit_text_file``/overwrite on the same path passes the
        read-before-write guard.

        Args:
            args: Must contain "path"; optionally "offset", "limit"
                and "max_chars".
            context: Execution metadata (conversation id for read
                tracking).

        Returns:
            A dict with file content, a ``ToolResult.ok`` with base64
            content for images, or a ``ToolResult`` error.
        """
        raw_path: str = args.get("path", "")
        if not raw_path:
            raise ValueError("'path' parameter is required")

        cfg = self.ctx.config.file_search
        resolved = _validate_path(
            raw_path,
            self._allowed_paths,
            self._forbidden_paths,
            cfg.follow_symlinks,
        )

        def _pre_check() -> int:
            if not resolved.is_file():
                raise ValueError(f"Not a file or not found: {resolved}")
            return resolved.stat().st_size

        file_size = await asyncio.to_thread(_pre_check)
        is_image = resolved.suffix.lower() in _IMAGE_CONTENT_TYPES
        if not is_image and file_size > cfg.max_file_size_read_bytes:
            # Images are exempt from the text byte-cap: only
            # max_image_bytes applies (checked in the reader).
            return ToolResult.error(
                f"File too large ({file_size:,} bytes). "
                f"Maximum is {cfg.max_file_size_read_bytes:,} bytes."
            )

        max_chars: int = min(
            int(args.get("max_chars", cfg.max_content_chars)),
            cfg.max_content_chars,
        )
        offset: int = max(int(args.get("offset", 1)), 1)
        limit: int = max(
            min(int(args.get("limit", cfg.max_read_lines)), cfg.max_read_lines),
            1,
        )

        result = await read_text_file(
            path=resolved,
            max_bytes=cfg.max_file_size_read_bytes,
            max_chars=max_chars,
            offset=offset,
            limit=limit,
            max_line_chars=cfg.max_line_chars,
            max_image_bytes=cfg.max_image_bytes,
        )

        read_ok = isinstance(result, dict) or result.success
        if read_ok:
            self._read_tracker.record(context.conversation_id, resolved)

        return result

    async def _exec_open_file(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> str:
        """Execute the open_file tool.

        Args:
            args: Must contain "path".
            context: Execution metadata (unused).

        Returns:
            A success message string.
        """
        raw_path: str = args.get("path", "")
        if not raw_path:
            raise ValueError("'path' parameter is required")

        cfg = self.ctx.config.file_search
        resolved = _validate_path(
            raw_path,
            self._allowed_paths,
            self._forbidden_paths,
            cfg.follow_symlinks,
        )

        if resolved.suffix.lower() in _EXECUTABLE_EXTENSIONS:
            raise ValueError(
                f"Cannot open executable files ({resolved.suffix}): "
                f"{resolved.name}"
            )

        def _open_with_system() -> None:
            if not resolved.exists():
                raise ValueError(f"File not found: {resolved}")
            # ``os.startfile`` exists only on Windows.  On other
            # platforms we surface a clear error rather than letting
            # an ``AttributeError`` bubble up from the worker thread.
            if sys.platform != "win32":
                raise ValueError(
                    "open_file is only supported on Windows "
                    f"(current platform: {sys.platform})"
                )
            os.startfile(resolved)  # type: ignore[attr-defined]  # Windows-only

        await asyncio.to_thread(_open_with_system)
        return f"Opened file: {resolved.name}"

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        """Write ``data`` to ``path`` atomically.

        Creates the parent directory if needed, writes to a tmp file in
        the same directory (same volume) and ``os.replace``s it onto the
        target: a crash mid-write never leaves a half-written file. The
        tmp file is removed if anything goes wrong before the replace.

        Args:
            path: Destination file path (need not exist yet).
            data: Raw bytes to write.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp_name, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    async def _exec_write_text_file(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> str:
        """Execute the write_text_file tool.

        Creating a new file is always free. Overwriting an existing file
        requires a prior successful ``read_text_file`` on the same path
        in this conversation (same ``ReadTracker`` guard as
        ``edit_text_file``): UNREAD/STALE fail with an actionable
        message. Executable extensions are blocked and path validation
        applies the same allowed/forbidden rules as read. The write
        itself is atomic (tmp file + ``os.replace``), and a successful
        write (new or overwrite) is recorded in the tracker so a
        follow-up write/edit in the same conversation does not need a
        re-read.

        Args:
            args: Must contain "path" and a non-empty string "content".
            context: Execution metadata (conversation id for the
                read-tracking guard).

        Returns:
            A success message string.

        Raises:
            ValueError: If "path" or "content" is missing/empty, "content" is
                not a string, the target is an executable, the target exists
                and was never read (or was read but is now stale), or
                content exceeds the maximum write size.
        """
        raw_path: str = args.get("path", "")
        if not raw_path:
            raise ValueError("'path' parameter is required")

        content = args.get("content")
        if content is None:
            raise ValueError("'content' parameter is required")
        if not isinstance(content, str):
            raise ValueError("'content' must be a string")
        if not content:
            raise ValueError("'content' parameter must not be empty")

        cfg = self.ctx.config.file_search
        resolved = _validate_path(
            raw_path,
            self._allowed_paths,
            self._forbidden_paths,
            cfg.follow_symlinks,
        )

        if resolved.suffix.lower() in _EXECUTABLE_EXTENSIONS:
            raise ValueError(
                f"Cannot write executable files ({resolved.suffix}): "
                f"{resolved.name}"
            )

        encoded = content.encode("utf-8")
        if len(encoded) > self._MAX_WRITE_BYTES:
            raise ValueError(
                f"Content too large ({len(encoded):,} bytes). "
                f"Maximum is {self._MAX_WRITE_BYTES:,} bytes."
            )

        if await asyncio.to_thread(resolved.exists):
            state = self._read_tracker.verify(context.conversation_id, resolved)
            if state is ReadState.UNREAD:
                raise ValueError(
                    "File esistente mai letto in questa conversazione: "
                    "leggi il file con read_text_file prima di "
                    "sovrascriverlo (o usa edit_text_file per modifiche "
                    "puntuali)."
                )
            if state is ReadState.STALE:
                raise ValueError(
                    "Il file è stato modificato dopo l'ultima lettura: "
                    "rileggilo con read_text_file e riprova."
                )

        await asyncio.to_thread(self._atomic_write_bytes, resolved, encoded)
        self._read_tracker.record(context.conversation_id, resolved)
        logger.info("file_search: wrote {} bytes to {}", len(encoded), resolved)
        return f"File written: {resolved.name} ({len(encoded):,} bytes)"

    async def _exec_edit_text_file(
        self,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> str:
        """Execute the edit_text_file tool (exact-string replacement).

        Guards: same path validation as write, executable extensions
        blocked, and a read-before-edit check against the conversation's
        ``ReadTracker`` (UNREAD/STALE fail with an actionable message).
        Matching happens in a normalized space (BOM stripped, CRLF
        folded to LF on both file content and arguments) and the result
        is written back atomically (tmp file + ``os.replace``) in the
        file's native convention when it is uniform (all-CRLF or all-LF,
        BOM preserved).  Files with MIXED line endings are rejected
        fail-closed: rewriting them would silently normalize lines the
        edit never touched.

        Args:
            args: Must contain "path", "old_string" and "new_string";
                optionally "replace_all" (default false).
            context: Execution metadata (conversation id for the
                read-tracking guard).

        Returns:
            A success message with the number of replacements.

        Raises:
            ValueError: On missing/invalid parameters, guard failures,
                non-UTF-8 content, mixed line endings, zero or
                non-unique occurrences, or a result exceeding the
                maximum write size.
        """
        raw_path: str = args.get("path", "")
        if not raw_path:
            raise ValueError("'path' parameter is required")

        old_string = args.get("old_string")
        if not isinstance(old_string, str):
            raise ValueError("'old_string' parameter is required")
        if not old_string:
            raise ValueError("old_string non può essere vuota")

        new_string = args.get("new_string")
        if not isinstance(new_string, str):
            raise ValueError("'new_string' parameter is required")

        replace_all = bool(args.get("replace_all", False))

        cfg = self.ctx.config.file_search
        resolved = _validate_path(
            raw_path,
            self._allowed_paths,
            self._forbidden_paths,
            cfg.follow_symlinks,
        )

        if resolved.suffix.lower() in _EXECUTABLE_EXTENSIONS:
            raise ValueError(
                f"Cannot edit executable files ({resolved.suffix}): "
                f"{resolved.name}"
            )

        state = self._read_tracker.verify(context.conversation_id, resolved)
        if state is ReadState.UNREAD:
            raise ValueError(
                "File mai letto in questa conversazione: leggi il file "
                "con read_text_file prima di modificarlo."
            )
        if state is ReadState.STALE:
            raise ValueError(
                "Il file è stato modificato dopo l'ultima lettura: "
                "rileggilo con read_text_file e riprova."
            )

        def _read_bytes() -> bytes:
            if not resolved.is_file():
                raise ValueError(f"Not a file or not found: {resolved}")
            if resolved.stat().st_size > self._MAX_WRITE_BYTES:
                raise ValueError(
                    f"File troppo grande per edit_text_file "
                    f"(massimo {self._MAX_WRITE_BYTES:,} bytes)."
                )
            return resolved.read_bytes()

        raw = await asyncio.to_thread(_read_bytes)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "Il file non è testo UTF-8: edit_text_file non è "
                "supportato su questo file."
            ) from exc

        # Match in normalized space (BOM stripped, LF-only) so that the
        # model can quote content in either EOL convention; write back in
        # the file's native convention afterwards.
        bom = "\ufeff"
        had_bom = text.startswith(bom)
        if had_bom:
            text = text.removeprefix(bom)
        is_crlf = "\r\n" in text
        if is_crlf and "\n" in text.replace("\r\n", ""):
            # Lone \n alongside \r\n: the round-trip would silently
            # rewrite every line to CRLF, including untouched ones.
            raise ValueError(
                "Il file ha EOL misti (CRLF e LF): edit non applicato "
                "per non riscrivere righe non toccate; normalizza prima "
                "gli EOL del file."
            )
        text = text.replace("\r\n", "\n")
        # Strip a leading BOM from the arguments too: read_text_file
        # renders the file's BOM invisibly on line 1, so the model may
        # copy it into old_string (or omit it) either way.
        old = old_string.replace("\r\n", "\n").removeprefix(bom)
        new = new_string.replace("\r\n", "\n").removeprefix(bom)

        if old == new:
            raise ValueError(
                "old_string e new_string sono identiche: "
                "nessuna modifica da applicare."
            )

        count = text.count(old)
        if count == 0:
            raise ValueError(
                "old_string non trovata nel file (0 occorrenze). Nota: "
                "old_string è contenuto del file SENZA il prefisso di "
                "numerazione righe mostrato da read_text_file; se il "
                "contenuto sembra cambiato, rileggi il file con "
                "read_text_file."
            )
        if count > 1 and not replace_all:
            raise ValueError(
                f"old_string non è unica ({count} occorrenze): estendi "
                "il contesto per renderla unica oppure usa "
                "replace_all=true."
            )

        replaced = count if replace_all else 1
        new_text = (
            text.replace(old, new)
            if replace_all
            else text.replace(old, new, 1)
        )

        if is_crlf:
            new_text = new_text.replace("\n", "\r\n")
        if had_bom:
            new_text = bom + new_text
        encoded = new_text.encode("utf-8")
        if len(encoded) > self._MAX_WRITE_BYTES:
            raise ValueError(
                f"Contenuto risultante troppo grande "
                f"({len(encoded):,} bytes). "
                f"Massimo {self._MAX_WRITE_BYTES:,} bytes."
            )

        await asyncio.to_thread(self._atomic_write_bytes, resolved, encoded)
        self._read_tracker.record(context.conversation_id, resolved)
        logger.info(
            "file_search: edited {} ({} replacement(s))", resolved, replaced,
        )
        label = "sostituzione" if replaced == 1 else "sostituzioni"
        return f"File modificato: {resolved.name} ({replaced} {label})"
