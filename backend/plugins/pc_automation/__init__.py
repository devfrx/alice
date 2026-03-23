"""AL\\CE — PC Automation plugin package."""

from backend.plugins.pc_automation.plugin import PcAutomationPlugin  # noqa: F401
from backend.core.plugin_manager import PLUGIN_REGISTRY

PLUGIN_REGISTRY["pc_automation"] = PcAutomationPlugin

