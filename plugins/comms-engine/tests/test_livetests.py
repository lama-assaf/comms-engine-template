"""
Live tests and outcomes (plan v2, item A11).

- a fixture test with two wins in separate periods closes as `keep` and
  writes a lesson with evidence, confidence and since; one win writes
  `trending` and no lesson
- a losing variant is `discard`; inside the margin is `inconclusive`; an
  unmatured slot or a short sample keeps the test open
- the budget names what is over 60/25/15 and a channel with too many open tests
- a third open test on one channel is refused
- with the scorer frozen a second win stays `trending`
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import livetests  # noqa: E402

W1 = dt.datetime(2026, 10, 12, 22, tzinfo=dt.timezone.utc)   # 2026-W42
W2 = dt.datetime(2026, 10, 26, 22, tzinfo=dt.timezone.utc)   # 2026-W44


def rec(iid, score, published="2026-10-01T08:00:00+00:00"):
    return {"id": iid, "score": score, "published_at": published}


class Tests(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="livetests-")
        self.lessons = os.path.join(self.state, "lessons.md")
        self._saved = livetests.LESSONS
        livetests.LESSONS = self.lessons
        with open(self.lessons, "w", encoding="utf-8") as f:
            f.write("# lessons\n")
        livetests.new("T-acme-1", "hook form", "a contrast hook beats a declarative", "X", "variation", state=self.state, now=W1)
        livetests.assign("T-acme-1", variant=["V1", "V2"], control=["C1", "C2"], state=self.state)

    def tearDown(self):
        livetests.LESSONS = self._saved
        shutil.rmtree(self.state, ignore_errors=True)

    def records(self, v1, v2, c1, c2):
        return {"V1": rec("V1", v1), "V2": rec("V2", v2), "C1": rec("C1", c1), "C2": rec("C2", c2)}

    def test_one_win_is_trending_two_wins_keep_and_write_a_lesson(self):
        closed = livetests.close(self.state, now=W1, records=self.records(30, 32, 20, 22))
        self.assertEqual(closed[0][1], "trending")
        with open(self.lessons, encoding="utf-8") as f:
            self.assertNotIn("kept pattern", f.read())
        closed = livetests.close(self.state, now=W2, records=self.records(40, 42, 20, 22))
        self.assertEqual(closed[0][1], "keep")
        t = livetests.load(self.state)[0]
        self.assertEqual(t["wins"], ["2026-W42", "2026-W44"])
        self.assertEqual(t["lesson"]["confidence"], "medium")
        with open(self.lessons, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("kept pattern: hook form (T-acme-1)", text)
        self.assertIn("evidence: V1, V2, C1, C2", text)
        self.assertIn("since: 2026-10-26", text)

    def test_second_win_in_the_same_period_does_not_keep(self):
        livetests.close(self.state, now=W1, records=self.records(30, 32, 20, 22))
        closed = livetests.close(self.state, now=W1 + dt.timedelta(days=1), records=self.records(30, 32, 20, 22))
        self.assertEqual(closed[0][1], "trending")

    def test_discard_and_inconclusive(self):
        self.assertEqual(livetests.close(self.state, now=W1, records=self.records(10, 12, 20, 22))[0][1], "discard")
        livetests.new("T-acme-2", "length", "shorter wins", "LinkedIn", "experiment", state=self.state, now=W1)
        livetests.assign("T-acme-2", variant=["V1", "V2"], control=["C1", "C2"], state=self.state)
        out = {c[0]: c[1] for c in livetests.close(self.state, now=W1, records=self.records(21, 21, 20, 20))}
        self.assertEqual(out["T-acme-2"], "inconclusive")

    def test_open_until_matured_and_sampled(self):
        recs = self.records(30, 32, 20, 22)
        recs["V2"]["published_at"] = "2026-10-11T08:00:00+00:00"  # the day before W1: not matured
        self.assertEqual(livetests.close(self.state, now=W1, records=recs), [])
        recs = {"V1": rec("V1", 30), "C1": rec("C1", 20)}
        self.assertEqual(livetests.close(self.state, now=W1, records=recs), [])

    def test_budget_and_channel_collisions(self):
        livetests.new("T-acme-3", "angle", "x", "X", "experiment", state=self.state, now=W1)
        with self.assertRaises(ValueError) as cm:
            livetests.new("T-acme-4", "angle", "y", "X", "experiment", state=self.state, now=W1)
        self.assertIn("One or two per channel", str(cm.exception))
        slots = [{"id": f"S{i}", "channel": "X", "kind": "experiment"} for i in range(5)] + [{"id": "S9", "channel": "X", "kind": "proven"}]
        b = livetests.budget(slots, self.state)
        self.assertIn("experiment", b["over"])
        self.assertIn("proven", b["under"])
        self.assertTrue(any("experiment" in h for h in b["holds"]))
        self.assertEqual(b["open_per_channel"], {"X": 2})

    def test_frozen_scorer_never_keeps(self):
        livetests.close(self.state, now=W1, records=self.records(30, 32, 20, 22))
        closed = livetests.close(self.state, now=W2, records=self.records(40, 42, 20, 22), frozen=True)
        self.assertEqual(closed[0][1], "trending")


if __name__ == "__main__":
    unittest.main()
