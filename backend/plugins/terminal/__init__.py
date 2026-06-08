"""AL\\CE — scoped terminal plugin package (security primitives in :mod:`.security`)."""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.terminal.plugin import TerminalPlugin

PLUGIN_REGISTRY["terminal"] = TerminalPlugin
