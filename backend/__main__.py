"""AL\\CE — Backend entry point with clean shutdown on Windows.

Usage:
    python -m backend                  (defaults: host=0.0.0.0, port=8000)
    python -m backend --port 9000
    python -m backend --reload         (dev mode)
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

import uvicorn


class _SuppressLifespanCancelledError(logging.Filter):
    """Suppress spurious CancelledError tracebacks on clean Ctrl+C shutdown.

    On Python 3.13+, after a graceful shutdown completes, uvicorn's
    ``capture_signals()`` calls ``signal.raise_signal(SIGINT)`` to propagate
    the signal to the parent process.  This re-triggers asyncio's internal
    ``_on_sigint`` handler which calls ``loop.stop()`` and raises
    ``KeyboardInterrupt``.  Any still-queued async tasks (such as uvicorn's
    background lifespan task waiting on ``receive_queue.get()``) receive a
    ``CancelledError``.  ``LifespanOn.main()`` catches ``BaseException`` and
    logs it as an error — but the shutdown already completed successfully, so
    the log is spurious noise, not a real failure.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if record.exc_info:
            exc_type = record.exc_info[0]
            if exc_type is not None and issubclass(exc_type, asyncio.CancelledError):
                return False
        return True


def _run_mcp_fetch_primp() -> None:
    """Dispatch to the bundled mcp-fetch-primp stdio server.

    The MCP client launches this entry point as a subprocess (configured via
    the ``{builtin:fetch_primp}`` placeholder in ``default.yaml``).  In a
    PyInstaller --onedir build ``sys.executable`` is ``backend.exe`` and the
    standalone ``backend/tools/mcp_fetch_primp.py`` script can no longer be
    invoked directly, so we re-export the same server through this CLI flag.
    """
    if sys.platform == "win32":
        # Match the standalone script's UTF-8 stdio setup so the MCP
        # framing protocol is not corrupted by Windows code-page encoders.
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    from backend.tools.mcp_fetch_primp import _main as _fetch_primp_main

    asyncio.run(_fetch_primp_main())


def main() -> None:
    """Launch uvicorn with graceful signal handling for Windows."""
    import argparse

    # Builtin MCP server dispatch — must be checked before argparse so the
    # flag works even when invoked as ``backend.exe --mcp-fetch-primp`` with
    # no other arguments (argparse would otherwise treat it as unknown).
    if "--mcp-fetch-primp" in sys.argv[1:]:
        _run_mcp_fetch_primp()
        return

    parser = argparse.ArgumentParser(description="AL\\CE backend server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--reload-dir", default="backend")
    args = parser.parse_args()

    kwargs: dict = {
        "factory": True,
        "host": args.host,
        "port": args.port,
    }
    if args.reload:
        # Resolve reload directory to absolute path for reliable
        # directory exclusion matching on Windows.
        from pathlib import Path

        reload_dir = Path(args.reload_dir).resolve()
        kwargs["reload"] = True
        kwargs["reload_dirs"] = [str(reload_dir)]
        kwargs["reload_excludes"] = [
            str(reload_dir / ".venv"),
            str(reload_dir / "__pycache__"),
            str(reload_dir / "tests"),
            "*.pyc",
        ]

    # Suppress the benign CancelledError that uvicorn logs as ERROR on
    # Python 3.13+ when Ctrl+C re-triggers asyncio's internal signal handler
    # after a graceful shutdown has already completed successfully.
    logging.getLogger("uvicorn.error").addFilter(_SuppressLifespanCancelledError())

    # On Windows, uvicorn's default signal handler raises KeyboardInterrupt
    # via signal.raise_signal(), which causes CancelledError tracebacks in
    # Starlette's lifespan.  By suppressing the KeyboardInterrupt at this
    # level the shutdown still completes cleanly (uvicorn handles SIGINT
    # internally) but the ugly traceback is eliminated.
    try:
        uvicorn.run("backend.core.app:create_app", **kwargs)
    except KeyboardInterrupt:
        pass
    finally:
        # Restore default signal handler to prevent double-handling.
        signal.signal(signal.SIGINT, signal.SIG_DFL)


if __name__ == "__main__":
    main()
