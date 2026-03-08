"""O.M.N.I.A. — Clipboard plugin package.

Importing this module registers :class:`ClipboardPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.clipboard.plugin import ClipboardPlugin  # noqa: F401

PLUGIN_REGISTRY["clipboard"] = ClipboardPlugin
