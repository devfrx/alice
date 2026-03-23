"""AL\\CE — Weather plugin package.

Importing this module registers :class:`WeatherPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.weather.plugin import WeatherPlugin  # noqa: F401

PLUGIN_REGISTRY["weather"] = WeatherPlugin
