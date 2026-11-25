"""
The monthly readout (plan v2, item A12).

- the readout carries the correlation, the stage, the promoted and decayed
  lessons, the variables that predicted nothing and the platform events
- a correlation that fell against the previous readout freezes the scorer,
  and the flag lands in metrics.json
- a kept-pattern lesson past 90 days gets one decay note, once
- a dry run writes nothing
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import readout  # noqa: E402

TODAY = dt.date(2026, 11, 2)


def preds(pairs):
    return [{"id": f"P{i}", "predicted": p, "actual": a, "hypothesis": h} for i, (p, a, h) in enumerate(pairs)]


class Readout(fixture_memory.FixtureMemoryCase):
    """The registry row the readout names is the fixture's."""

    def setUp(self):
        super().setUp()
        self.state = tempfile.mkdtemp(prefix="readout-")
        self.lessons = os.path.join(self.state, "lessons.md")
        with open(self.lessons, "w", encoding="utf-8") as f:
            f.write("# lessons\n\n## 2026-07-01 — kept pattern: hook form (T-acme-0)\n\ncontext: x\n\nlesson: y\n\nevidence: A, B\nconfidence: medium\nsince: 2026-07-01\n\n---\n")
        self.items = [{"id": "i1", "stream": "Acme", "slot": {"date": "2026-10-03"}, "query": "depth", "format": "F", "logic": "L", "title": "A b"},
                      {"id": "i2", "stream": "Acme", "slot": {"date": "2026-10-10"}, "query": "depth", "format": "F", "logic": "L", "title": "C d"},
                      {"id": "i3", "stream": "Acme", "slot": {"date": "2026-10-20"}, "query": "gaps", "format": "F", "logic": "L", "title": "E f"}]

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def _write(self, name, data):
        with open(os.path.join(self.state, name), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_shape_stage_and_decay(self):
        self._write("predictions.json", preds([("above", "above", "hook form: a"), ("below", "below", "hook form: b"),
                                               ("baseline", "baseline", "hook form: c"), ("above", "below", "length: a"),
                                               ("above", "below", "length: b"), ("below", "above", "length: c")]))
        self._write("platform-events.json", [{"at": "2026-10-14", "platform": "X", "event": "link reach halved"}, {"at": "2026-09-01", "event": "old"}])
        out = readout.run("acme", self.state, today=TODAY, lessons_path=self.lessons, items=self.items)
        self.assertEqual(out["month"], "2026-10")
        self.assertEqual(out["stage"]["stage"], "deepen")
        self.assertEqual(out["stage"]["pieces"], 3)
        self.assertEqual([v["variable"] for v in out["predicted_nothing"]], ["length"])
        self.assertEqual(len(out["platform_events"]), 1)
        self.assertEqual(out["lessons"]["decayed"], ["2026-07-01 — kept pattern: hook form (T-acme-0)"])
        self.assertFalse(out["scorer_frozen"])
        self.assertTrue(os.path.exists(os.path.join(self.state, "readout-2026-10.json")))
        with open(self.lessons, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text.count("decayed:"), 1)
        # a second run adds no second decay note
        readout.run("acme", self.state, today=TODAY, lessons_path=self.lessons, items=self.items)
        with open(self.lessons, encoding="utf-8") as f:
            self.assertEqual(f.read().count("decayed:"), 1)

    def test_falling_correlation_freezes_the_scorer(self):
        self._write("readout-2026-09.json", {"stream": "Acme", "month": "2026-09", "correlation": {"value": 0.9}})
        self._write("predictions.json", preds([("above", "below", "h: a"), ("below", "above", "h: b"), ("above", "below", "h: c"),
                                               ("baseline", "baseline", "h: d"), ("below", "above", "h: e")]))
        out = readout.run("acme", self.state, today=TODAY, lessons_path=self.lessons, items=self.items)
        self.assertEqual(out["correlation"]["previous"], 0.9)
        self.assertTrue(out["scorer_frozen"])
        with open(os.path.join(self.state, "metrics.json"), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["scorer_frozen"])

    def test_dry_run_writes_nothing(self):
        out = readout.run("acme", self.state, today=TODAY, dry_run=True, lessons_path=self.lessons, items=self.items)
        self.assertEqual(out["lessons"]["decayed"], ["2026-07-01 — kept pattern: hook form (T-acme-0)"])
        self.assertEqual(sorted(os.listdir(self.state)), ["lessons.md"])


if __name__ == "__main__":
    unittest.main()
