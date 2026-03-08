"""O.M.N.I.A. — File Search plugin package.

Importing this module registers :class:`FileSearchPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.file_search.plugin import FileSearchPlugin  # noqa: F401

PLUGIN_REGISTRY["file_search"] = FileSearchPlugin
