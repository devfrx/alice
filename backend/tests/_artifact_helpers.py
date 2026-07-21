"""AL\\CE — Shared fixtures/constants for artifact tests.

Kept out of ``conftest.py`` so test modules can import the constants
explicitly (same pattern as ``tests/agent/doubles.py``).
"""

from __future__ import annotations

import base64

PNG_1X1_B64: str = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
"""1x1 transparent PNG (real, decodable) for IMAGE-artifact tests."""

PNG_1X1_BYTES: bytes = base64.b64decode(PNG_1X1_B64)
"""Decoded bytes of :data:`PNG_1X1_B64`."""
