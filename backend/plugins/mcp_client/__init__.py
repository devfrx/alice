"""AL\\CE — MCP Client plugin package.

Importing this module registers McpClientPlugin in the static PLUGIN_REGISTRY.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.mcp_client.plugin import McpClientPlugin  # noqa: F401

PLUGIN_REGISTRY["mcp_client"] = McpClientPlugin
