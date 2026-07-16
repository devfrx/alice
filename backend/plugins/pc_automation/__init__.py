"""AL\\CE — PC Automation plugin package."""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.pc_automation.plugin import PcAutomationPlugin  # noqa: F401

PLUGIN_REGISTRY["pc_automation"] = PcAutomationPlugin

