"""AL\\CE — Chart Generator plugin package.

Importing this module registers ChartGeneratorPlugin in the static PLUGIN_REGISTRY
so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.chart_generator.plugin import ChartGeneratorPlugin  # noqa: F401

PLUGIN_REGISTRY["chart_generator"] = ChartGeneratorPlugin
