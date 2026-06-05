"""AL\\CE — Agent plugin package.

Importing this module registers :class:`AgentPlugin` in the static
``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.agent.plugin import AgentPlugin  # noqa: F401

PLUGIN_REGISTRY["agent"] = AgentPlugin
