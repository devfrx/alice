"""O.M.N.I.A. — Calendar plugin package.

Importing this module registers :class:`CalendarPlugin` in the
static ``PLUGIN_REGISTRY`` so the plugin manager can discover it.
"""

from backend.core.plugin_manager import PLUGIN_REGISTRY
from backend.plugins.calendar.plugin import CalendarPlugin  # noqa: F401

PLUGIN_REGISTRY["calendar"] = CalendarPlugin

