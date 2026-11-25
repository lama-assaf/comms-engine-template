"""
A fake Composio API key for tests that fake the Composio HTTP layer.

The engine resolves a stream's key through `secrets.get_secret("COMPOSIO_API_KEY", stream=...)`
before it makes a request. A test that fakes the HTTP layer must fake that resolution too, so
nothing reads the environment or the keychain of the machine it runs on:

    fake_composio_key.install(self)            # every stream has KEY
    fake_composio_key.install(self, {})        # no stream has one
    fake_composio_key.install(self, {"alpha": "k"})   # only these streams

Other secret names go to the real chain, as they did before.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import secrets as secrets_mod  # noqa: E402

KEY = "test-composio-key-not-a-secret"


def install(case, keys=None, default=KEY):
    """Patch `secrets.get_secret` for the case; returns the list of `(name, stream)` it was asked."""
    asked = []
    real = secrets_mod.get_secret

    def fake(name, required=True, stream=None):
        if name != "COMPOSIO_API_KEY":
            return real(name, required=required, stream=stream)
        asked.append((name, stream))
        value = default if keys is None else keys.get((stream or "").lower())
        if value or not required:
            return value or None
        raise secrets_mod.SecretNotFound(f"{name} not found")

    p = mock.patch.object(secrets_mod, "get_secret", fake)
    p.start()
    case.addCleanup(p.stop)
    return asked
