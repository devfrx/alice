"""O.M.N.I.A. — System Info plugin package.

Importing this module registers :class:`SystemInfoPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.plugins.system_info.plugin import SystemInfoPlugin  # noqa: F401

