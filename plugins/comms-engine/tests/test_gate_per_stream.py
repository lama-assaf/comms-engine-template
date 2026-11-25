"""
The gate per stream (plan v2, item A7).

An item is gated against the memory of its own stream and nothing else. The
acceptance case: an Acme item carried with `stream: Beta` blocks, because
beta's `themes.md` has no such theme, its `handles.private.md` is absent,
and its claims register has no such rows. The same item as Acme passes the
linter. A missing, `Both` or unknown stream blocks on its own.

Both streams come from the fixture memory (`fixture_memory.py`), so the
checkout's own `.atelier/memory/` is never read.
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import gate_lint  # noqa: E402

with open(os.path.join(HERE, "fixtures.json"), encoding="utf-8") as f:
    BASE = json.load(f)["base"]


def named(result):
    return {c["check"]: c for c in result["checks"]}


class PerStream(fixture_memory.FixtureMemoryCase):
    def test_acme_item_passes_against_acme(self):
        r = gate_lint.lint(copy.deepcopy(BASE))
        self.assertEqual(r["verdict"], "pass", [c for c in r["checks"] if c["result"] != "pass"])
        self.assertIn("acme memory", named(r)["lint: stream"]["fix"])

    def test_acme_item_against_beta_blocks_with_reasons_named(self):
        item = copy.deepcopy(BASE)
        item["stream"] = fixture_memory.OTHER_NAME
        r = gate_lint.lint(item)
        self.assertEqual(r["verdict"], "block")
        n = named(r)
        self.assertEqual(n["lint: stream"]["result"], "block")
        self.assertIn("not a theme of the beta stream", n["lint: stream"]["fix"])
        self.assertEqual(n["lint: stealth"]["result"], "block")
        self.assertIn("streams/beta/handles.private.md", n["lint: stealth"]["fix"])
        self.assertEqual(n["lint: cites"]["result"], "block")
        self.assertIn("no such claim", n["lint: cites"]["fix"])

    def test_missing_and_both_block(self):
        for value in ("", "Both", fixture_memory.UNKNOWN_NAME):
            item = copy.deepcopy(BASE)
            item["stream"] = value
            r = gate_lint.lint(item)
            self.assertEqual(r["verdict"], "block", value)
            self.assertEqual(named(r)["lint: stream"]["result"], "block", value)

    def test_slug_resolution(self):
        self.assertEqual(gate_lint.resolve_slug({"stream": "Acme"}), "acme")
        self.assertEqual(gate_lint.resolve_slug({"stream": "beta"}), "beta")
        self.assertIsNone(gate_lint.resolve_slug({"stream": "Both"}))
        self.assertIsNone(gate_lint.resolve_slug({}))


if __name__ == "__main__":
    unittest.main()
