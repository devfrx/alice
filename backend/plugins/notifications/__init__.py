"""AL\\CE — Notifications plugin package.

Importing this module registers :class:`NotificationsPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.notifications.plugin import NotificationsPlugin  # noqa: F401

PLUGIN_REGISTRY["notifications"] = NotificationsPlugin
