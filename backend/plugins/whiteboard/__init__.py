"""AL\\CE — Whiteboard plugin package.

Importing this module registers :class:`WhiteboardPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.whiteboard.plugin import WhiteboardPlugin  # noqa: F401

PLUGIN_REGISTRY["whiteboard"] = WhiteboardPlugin
