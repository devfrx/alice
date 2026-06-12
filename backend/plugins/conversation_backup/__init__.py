"""AL\\CE — Conversation backup plugin package.

Importing this module registers :class:`ConversationBackupPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.conversation_backup.plugin import ConversationBackupPlugin  # noqa: F401

PLUGIN_REGISTRY["conversation_backup"] = ConversationBackupPlugin
