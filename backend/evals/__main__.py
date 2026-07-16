"""Entry point: ``python -m backend.evals``."""

from __future__ import annotations

import sys

from backend.evals.cli import main

if __name__ == "__main__":
    sys.exit(main())
