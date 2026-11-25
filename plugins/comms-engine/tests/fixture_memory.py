#!/usr/bin/env python3
"""
fixture_memory.py - point `scripts/memory.py` at a temp copy of the fixture memory,
and `scripts/config.py` at an engine.json that carries the placeholder brand.

The suite never reads `.atelier/memory/`, `state/` or `Content/Calendar/`.
Everything a test needs from shared memory comes from `tests/fixtures/memory/`
(the invented brand Acme, its second stream Beta, eight invented themes, a
denylist of invented terms), copied to a temp directory for the length of a
test so a test that writes into it harms nothing.

The brand is fixed the same way. The fixture registry's root is `acme`, so the
engine.json the scripts read while a fixture is installed must say `acme` too,
whatever brand the checkout has been stamped with by `engine.py init`:
`start()` writes a copy of the tracked engine.json with its `brand` replaced by
`config.DEFAULT_BRAND` (jobs and params as shipped, the `streams` key renamed)
and points `config.ENGINE_JSON` and `config.LOCAL_JSON` at the temp directory.
The scripts that derive a constant from the brand at import (memory's root
stream, the secrets service, the X stream's rule prefix, the console's labels,
the hook's marker, the gate's capability subject) are rebound for the length of
the fixture through `BRAND_BOUND`, so a module imported before the fixture
started answers for the fixture brand as well. A function default such as
`stream=memory.DEFAULT_STREAM` is fixed at definition time and is not rebound:
a test that relies on one passes `fixture_memory.ROOT` explicitly.

`memory.py` resolves the root stream through its module-level constants
(`MEMORY`, `THEMES_MD`, ...) and every other stream through `REPO` plus the
registry's `memory` column, so both are patched: the copy sits at
`<tmp>/.atelier/memory/` and `memory.REPO` becomes `<tmp>`, which keeps the
relative paths the gate quotes in its fixes (`.atelier/memory/streams/beta/...`)
the same as in a real checkout.

Three ways to use it:

    class MyTest(FixtureMemoryCase):          # setUp/tearDown do it
        ...

    class MyTest(FixtureMemoryCase):
        PRIVATE = False                       # the companion left out of the copy

    def setUpModule():                        # once per module
        fixture_memory.install()
    def tearDownModule():
        fixture_memory.uninstall()

`FIXTURES` is the fixture directory itself, for a test that wants a file by
path (`os.path.join(FIXTURES, "themes.json")`) rather than through memory.py.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import config  # noqa: E402
import memory  # noqa: E402

#: The tracked engine.json, captured before any fixture patches config.ENGINE_JSON.
LIVE_ENGINE_JSON = os.path.join(ENGINE, "engine.json")

FIXTURES = os.path.join(HERE, "fixtures")
MEMORY_FIXTURE = os.path.join(FIXTURES, "memory")
THEMES_JSON = os.path.join(FIXTURES, "themes.json")
ENGINE_STREAMS = os.path.join(FIXTURES, "streams")
QUEUE_JSON = os.path.join(FIXTURES, "queue.json")

#: The slugs and display names the fixture registry carries, so a test reads
#: them from one place rather than spelling them.
ROOT, ROOT_NAME = "acme", "Acme"
OTHER, OTHER_NAME = "beta", "Beta"
#: A name the registry does not list, for the tests that need an unknown stream.
UNKNOWN_NAME = "Umbra"


def fixture_engine_json(dst, live=LIVE_ENGINE_JSON):
    """Write `dst`: the tracked engine.json with the placeholder brand and its streams key.

    Jobs and params stay as shipped, so a test of the schedule or the console
    reads the real eight jobs; only the brand, and the registry key that is the
    brand's slug, are pinned to what the fixture memory says."""
    with open(live, encoding="utf-8") as f:
        doc = json.load(f)
    old = (doc.get("brand") or {}).get("slug") or ROOT
    doc["brand"] = dict(config.DEFAULT_BRAND)
    streams = doc.get("streams") or {}
    if old in streams and old != ROOT:
        doc["streams"] = {(ROOT if k == old else k): v for k, v in streams.items()}
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return dst


def _bound(b):
    """{module name: {attribute: value}} for every constant a script derives from the brand at import."""
    slug, name, prefix = b["slug"], b["name"], b["env_prefix"]
    label = lambda n: b["label_prefix"] + "." + n  # noqa: E731
    out = {
        "config": {"ENV_PREFIX": prefix},
        "memory": {"DEFAULT_STREAM": slug, "DEFAULT_STREAM_NAME": name},
        "secrets": {"KEYCHAIN_SERVICE": b["keychain_service"], "ROOT_STREAM": slug},
        "engine_secrets": {"KEYCHAIN_SERVICE": b["keychain_service"], "ROOT_STREAM": slug},
        "x_stream": {"PREFIX": slug + ":", "BRAND_NAME": name, "INTERVAL": {slug + ":mentions": 600}},
        "autopilot": {"STREAM": slug, "STREAM_NAME": name, "STREAM_NAMES": (name, "Both"), "X_APP": slug},
        "session_brief": {"BRAND_NAME": name},
    }
    gate_lint = sys.modules.get("gate_lint")
    if gate_lint is not None:
        out["gate_lint"] = {"BRAND_NAME": name, "CAPABILITY": gate_lint.capability_pattern(name)}
    engine = sys.modules.get("engine")
    if engine is not None:
        checks = engine.doctor_checks(slug)
        out["engine"] = {
            "SHORT": {alias: label(n) for alias, n in engine.JOB_NAMES.items()},
            "LAUNCHD_LOGS": config.log_dir(),
            "DOCTOR_CHECKS": checks,
            "INFO_CHECKS": engine.info_checks(checks),
        }
    return out


#: Documentation of what `_bound` rebinds, for a reader of the suite.
BRAND_BOUND = tuple(sorted(_bound(config.DEFAULT_BRAND)))


class FixtureMemory:
    """A temp copy of the fixture memory and a fixture engine.json, with memory.py and config.py pointed at them."""

    def __init__(self, private=True):
        self.private = private
        self.root = None
        self.dir = None
        self.engine_json = None
        self._patches = []

    def start(self):
        self.root = tempfile.mkdtemp(prefix="fixture-memory-")
        self.dir = os.path.join(self.root, ".atelier", "memory")
        shutil.copytree(MEMORY_FIXTURE, self.dir)
        if not self.private:
            os.remove(os.path.join(self.dir, "handles.private.md"))
        engine_dir = self.root  # instance-shaped: engine.json, brand.json and engine.local.json side by side
        self.engine_json = fixture_engine_json(os.path.join(engine_dir, "engine.json"))
        targets = {
            "REPO": self.root,
            "MEMORY": self.dir,
            "THEMES_MD": os.path.join(self.dir, "themes.md"),
            "HANDLES_MD": os.path.join(self.dir, "handles.md"),
            "HANDLES_PRIVATE_MD": os.path.join(self.dir, "handles.private.md"),
            "STREAMS_MD": os.path.join(self.dir, "streams.md"),
            "CLAIMS_MD": os.path.join(self.dir, "claims.md"),
        }
        # Plain setattr with the originals kept, not mock.patch: a test that
        # calls mock.patch.stopall() in its cleanup would otherwise stop the
        # fixture's patches too and leave the module reading the checkout.
        for k, v in targets.items():
            self._set(memory, k, v)
        self._set(config, "ENGINE_JSON", self.engine_json)
        self._set(config, "LOCAL_JSON", os.path.join(engine_dir, "engine.local.json"))
        # The brand-derived constants, for every script already imported; a
        # script imported later derives them from the patched config itself.
        for mod_name, attrs in _bound(config.brand()).items():
            mod = sys.modules.get(mod_name)
            if mod is None:
                continue
            for attr, value in attrs.items():
                if hasattr(mod, attr):
                    self._set(mod, attr, value)
        return self

    def _set(self, mod, attr, value):
        self._patches.append((mod, attr, getattr(mod, attr)))
        setattr(mod, attr, value)

    def stop(self):
        for mod, attr, original in reversed(self._patches):
            setattr(mod, attr, original)
        self._patches = []
        if self.root:
            shutil.rmtree(self.root, ignore_errors=True)
        self.root = self.dir = None

    def stream_dir(self, slug):
        """The copy's directory for a stream, through the registry like the engine."""
        return memory.stream_dir(slug)

    def path(self, *parts):
        return os.path.join(self.dir, *parts)


_module_fixture = None


def install(private=True):
    """Install once for a whole module (pair with `uninstall` in tearDownModule)."""
    global _module_fixture
    if _module_fixture is not None:
        raise RuntimeError("fixture memory already installed for this module")
    _module_fixture = FixtureMemory(private=private).start()
    return _module_fixture


def uninstall():
    global _module_fixture
    if _module_fixture is not None:
        _module_fixture.stop()
        _module_fixture = None


class FixtureMemoryCase(unittest.TestCase):
    """A TestCase whose every test runs against its own copy of the fixture memory."""

    PRIVATE = True

    def setUp(self):
        super().setUp()
        self.fixture = FixtureMemory(private=self.PRIVATE).start()
        self.addCleanup(self.fixture.stop)
