"""O.M.N.I.A. — Web Search plugin package.

Importing this module registers :class:`WebSearchPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.web_search.plugin import WebSearchPlugin  # noqa: F401

PLUGIN_REGISTRY["web_search"] = WebSearchPlugin
