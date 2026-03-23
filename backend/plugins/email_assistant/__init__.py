"""AL\\CE — Email Assistant plugin package.

Importing this module registers :class:`EmailPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.email_assistant.plugin import EmailPlugin  # noqa: F401

PLUGIN_REGISTRY["email_assistant"] = EmailPlugin

__all__ = ["EmailPlugin"]
