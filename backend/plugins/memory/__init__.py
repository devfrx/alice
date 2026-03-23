"""AL\\CE — Memory plugin package.

Importing this module registers :class:`MemoryPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.memory.plugin import MemoryPlugin  # noqa: F401

PLUGIN_REGISTRY["memory"] = MemoryPlugin
