"""AL\\CE — Backend entry point with clean shutdown on Windows.

Usage:
    python -m backend                  (defaults: host=0.0.0.0, port=8000)
    python -m backend --port 9000
    python -m backend --reload         (dev mode)
"""

from __future__ import annotations

import signal
import sys

import uvicorn


def main() -> None:
    """Launch uvicorn with graceful signal handling for Windows."""
    import argparse

    parser = argparse.ArgumentParser(description="AL\\CE backend server")
    parser.add_argument("--host", default="0.0.0.0")
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
        kwargs["reload"] = True
        kwargs["reload_dirs"] = [args.reload_dir]

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
