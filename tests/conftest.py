"""Lets the plugin import on any machine, without InkyPi or a display.

``daily_quote.py`` imports ``plugins.base_plugin.base_plugin.BasePlugin``
from InkyPi; a minimal stand-in is registered here instead.
"""

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _StubBasePlugin:
    def __init__(self, config, **dependencies):
        self.config = config

    def generate_settings_template(self):
        return {"settings_template": "daily_quote/settings.html"}


if "plugins.base_plugin.base_plugin" not in sys.modules:
    for name in ("plugins", "plugins.base_plugin", "plugins.base_plugin.base_plugin"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["plugins.base_plugin.base_plugin"].BasePlugin = _StubBasePlugin
