"""
Keep a test off the checkout's real channel settings.

`install(case)` makes `config.cfg` answer the caller's default for the keys that choose a driver
or record a price sign-off (`channels.write_driver.*`, `channels.x_read.*`, `channels.x_own.*`,
`listen.x_price_signoff`, `listen.x_own_price_signoff`), so a test that asserts the shipped
defaults, or sets its own value on top, does not depend on what this checkout's engine.json (or
engine.local.json) has switched on. Install it before any patch that wraps `config.cfg`.
"""
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import config  # noqa: E402

PREFIXES = ("channels.write_driver.", "channels.x_read.", "channels.x_own.")
EXACT = ("listen.x_price_signoff", "listen.x_own_price_signoff")


def install(case):
    real = config.cfg

    def fake(path, default=None, **kw):
        if path in EXACT or str(path).startswith(PREFIXES):
            return default
        return real(path, default, **kw)
    p = mock.patch.object(config, "cfg", fake)
    p.start()
    case.addCleanup(p.stop)
