"""AL\\CE — CAD Generator plugin package.

Importing this module registers :class:`CadGeneratorPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.cad_generator.plugin import CadGeneratorPlugin  # noqa: F401

PLUGIN_REGISTRY["cad_generator"] = CadGeneratorPlugin
