"""AL\\CE — News/briefing plugin package.

Importing this module registers :class:`NewsPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.news.plugin import NewsPlugin  # noqa: F401

PLUGIN_REGISTRY["news"] = NewsPlugin
