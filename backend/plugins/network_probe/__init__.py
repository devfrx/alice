"""AL\\CE — Network probe plugin package.

Importing this module registers :class:`NetworkProbePlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.network_probe.plugin import NetworkProbePlugin  # noqa: F401

PLUGIN_REGISTRY["network_probe"] = NetworkProbePlugin
