"""AL\\CE — Continuum plugin package.

Importing this module registers :class:`ContinuumPlugin` in the static
``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.continuum.plugin import ContinuumPlugin  # noqa: F401

PLUGIN_REGISTRY["continuum"] = ContinuumPlugin
