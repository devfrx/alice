"""O.M.N.I.A. — File Search plugin.

Exposes five tools for searching, reading and writing files on the
local filesystem with path access control.  All paths are validated
against allowed/forbidden root directories before any operation.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import string
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.file_search.readers import (
    _DOCX_AVAILABLE,
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
                timeout_ms=3_000,
            ),
            ToolDefinition(
                name="read_text_file",
                description=(
                    "Read the text content of a file. Supports plain text "
                    "formats (.txt, .md, .py, .json, etc.), PDF and DOCX. "
                    "Content may be truncated for large files."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file.",
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
                timeout_ms=5_000,
            ),
            ToolDefinition(
                name="write_text_file",
                description=(
                    "Create or overwrite a text file with the given "
                    "content. The path must be inside an allowed "
                    "directory. Executable extensions are blocked."
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
                timeout_ms=10_000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested tool.

        Args:
            tool_name: One of the four file-search tool names.
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
        }

        handler = handlers.get(tool_name)
        if handler is None:
            return ToolResult.error(f"Unknown tool: {tool_name}")

        try:
            result = await handler(args)
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

    async def _exec_search_files(self, args: dict) -> list[dict]:
        """Execute the search_files tool.

        Args:
            args: Must contain "query"; optionally "path", "extensions",
                  "max_results".

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

    async def _exec_get_file_info(self, args: dict) -> dict:
        """Execute the get_file_info tool.

        Args:
            args: Must contain "path".

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

        def _gather_metadata() -> dict:
            if not resolved.exists():
                raise ValueError(f"File not found: {resolved}")

            stat = resolved.stat()
            mime_type, _ = mimetypes.guess_type(str(resolved))
            created_dt = datetime.fromtimestamp(
                stat.st_ctime, tz=timezone.utc,
            )
            modified_dt = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc,
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

    async def _exec_read_text_file(self, args: dict) -> dict | ToolResult:
        """Execute the read_text_file tool.

        Args:
            args: Must contain "path"; optionally "max_chars".

        Returns:
            A dict with file content or a ToolResult error.
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
        if file_size > cfg.max_file_size_read_bytes:
            return ToolResult.error(
                f"File too large ({file_size:,} bytes). "
                f"Maximum is {cfg.max_file_size_read_bytes:,} bytes."
            )

        max_chars: int = min(
            int(args.get("max_chars", cfg.max_content_chars)),
            cfg.max_content_chars,
        )

        return await read_text_file(
            path=resolved,
            max_bytes=cfg.max_file_size_read_bytes,
            max_chars=max_chars,
        )

    async def _exec_open_file(self, args: dict) -> str:
        """Execute the open_file tool.

        Args:
            args: Must contain "path".

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
            os.startfile(resolved)  # type: ignore[attr-defined]  # Windows-only

        await asyncio.to_thread(_open_with_system)
        return f"Opened file: {resolved.name}"

    async def _exec_write_text_file(self, args: dict) -> str:
        """Execute the write_text_file tool.

        Creates or overwrites a text file at the given path with the
        supplied content.  Executable extensions are blocked and path
        validation applies the same allowed/forbidden rules as read.

        Args:
            args: Must contain "path" and "content".

        Returns:
            A success message string.
        """
        raw_path: str = args.get("path", "")
        if not raw_path:
            raise ValueError("'path' parameter is required")

        content: str = args.get("content", "")
        if not content:
            raise ValueError("'content' parameter is required")

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

        def _write() -> None:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_bytes(encoded)

        await asyncio.to_thread(_write)
        logger.info("file_search: wrote {} bytes to {}", len(encoded), resolved)
        return f"File written: {resolved.name} ({len(encoded):,} bytes)"
