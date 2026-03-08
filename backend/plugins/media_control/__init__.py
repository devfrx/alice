"""O.M.N.I.A. — Media Control plugin package.

Importing this module registers :class:`MediaControlPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.media_control.plugin import MediaControlPlugin  # noqa: F401

PLUGIN_REGISTRY["media_control"] = MediaControlPlugin
