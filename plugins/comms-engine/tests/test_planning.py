"""
Planning queries and predictions (plan v2, item A8).

1. **The three queries run over the files** and say so (`queries: files`);
   each theme gets gaps, freshness and depth scores and the query it answers.
2. **Gaps** falls as pieces land on a theme; **freshness** counts register
   rows added or changed since the theme's last piece; **depth** counts
   conversation-shaped findings and substantive replies.
3. **A prediction is appended at ingest** for an item carrying the four A8
   fields, once, with no actual; an item missing any field gets no record.
4. **The actual lands beside the prediction** without touching anything else.

The register and the themes are the fixture memory's (`fixture_memory.py`);
the fixture register's dates are what the freshness assertions lean on.
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
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import memory  # noqa: E402
import plan_queries  # noqa: E402
import predictions  # noqa: E402
import repo  # noqa: E402

TODAY = dt.date(2026, 10, 26)


def note(cal, title, stream, date, theme="", category=""):
    with open(os.path.join(cal, f"{title}.md"), "w", encoding="utf-8") as f:
        f.write(f"---\ntitle: {title}\ndate: '{date}'\nstatus: Published\nstream: {stream}\nplatform: Blog\n"
                + (f"theme: '{theme}'\n" if theme else "") + (f"category: {category}\n" if category else "")
                + "---\nbody\n")


class Queries(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="planning-")
        self.cal = os.path.join(self.tmp, "Calendar")
        os.makedirs(self.cal)
        self.register = memory.load_claims()
        self.signals = {"per_theme": {"#ExampleTheme": {"count": 20, "relevance": 3.0},
                                      "#SecondTheme": {"count": 10, "relevance": 2.0, "demand": 7.5}},
                        "findings": [{"theme": "#ExampleTheme", "conversation": {"target": "x"}},
                                     {"theme": "#ExampleTheme", "conversation": "None"}]}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def run_q(self, engagement=None, changes=None):
        return plan_queries.run("acme", state=self.tmp, cal=self.cal, today=TODAY, register=self.register,
                                signals=self.signals, engagement=engagement or {}, changes=changes or [])

    def test_shape_and_files_flag(self):
        out = self.run_q()
        self.assertEqual(out["queries"], "files")
        self.assertEqual(set(out["themes"]), set(memory.theme_tags()))
        for t, x in out["themes"].items():
            for q in plan_queries.QUERIES:
                self.assertIn("score", x[q], (t, q))
            self.assertIn(x["answer"], plan_queries.QUERIES + ("none",))
        self.assertEqual(len(out["order"]), 8)

    def test_demand_source_and_gaps_fall_with_pieces(self):
        out = self.run_q()
        ir = out["themes"]["#ExampleTheme"]["gaps"]
        self.assertEqual(ir["demand_source"], "proxy")
        self.assertEqual(ir["demand"], 6.0)
        self.assertEqual(out["themes"]["#SecondTheme"]["gaps"]["demand_source"], "qualitative")
        self.assertEqual(out["themes"]["#SecondTheme"]["gaps"]["demand"], 7.5)
        before = ir["score"]
        note(self.cal, "One", "Acme", "2026-10-20", theme="#ExampleTheme")
        note(self.cal, "Two", "Acme", "2026-10-21", category="ExampleTheme")
        note(self.cal, "Other stream", "Beta", "2026-10-21", theme="#ExampleTheme")
        after = self.run_q()["themes"]["#ExampleTheme"]["gaps"]
        self.assertEqual(after["pieces_in_window"], 2)
        self.assertLess(after["score"], before)

    def test_freshness_counts_rows_since_the_last_piece(self):
        # no piece on #FourthTheme: the window applies; the register's rows on
        # it are all dated before the window, so nothing is new...
        out = self.run_q()
        self.assertEqual(out["themes"]["#FourthTheme"]["freshness"]["new"], [])
        # ...until a change to one of its rows is logged after the window start
        changes = [{"id": "C-acme-2", "field": "grade", "from": "evidenced", "to": "asserted", "seen_at": "2026-10-25T22:00:00+00:00"}]
        out = self.run_q(changes=changes)
        self.assertEqual(out["themes"]["#FourthTheme"]["freshness"]["changed"], ["C-acme-2"])
        self.assertEqual(out["themes"]["#FourthTheme"]["freshness"]["score"], 1)
        # a row dated inside the window on a theme with no piece counts as new
        self.assertIn("C-acme-10", out["themes"]["#FifthTheme"]["freshness"]["new"])

    def test_depth_counts_conversations_and_replies(self):
        out = self.run_q()
        self.assertEqual(out["themes"]["#ExampleTheme"]["depth"]["score"], 1)
        self.assertTrue(out["themes"]["#ExampleTheme"]["depth"]["partial"])
        eng = {"records": [{"id": "P", "theme": "#ExampleTheme", "at_7d": {"substantive_replies": 3}}]}
        out = self.run_q(engagement=eng)
        self.assertEqual(out["themes"]["#ExampleTheme"]["depth"]["score"], 4)
        self.assertFalse(out["themes"]["#ExampleTheme"]["depth"]["partial"])

    def test_table_renders(self):
        self.assertIn("queries: files", plan_queries.table(self.run_q()))


class Predictions(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.state = tempfile.mkdtemp(prefix="predictions-")

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)
        super().tearDown()

    def _item(self, iid, **over):
        it = {"id": iid, "stream": "Acme", "theme": "#ExampleTheme", "slot": {"platform": "Blog"}, "format": "Observation",
              "query": "gaps", "hypothesis": "hook form: contrast", "predicted": "above", "test_id": "none"}
        it.update(over)
        return it

    def test_append_once_with_no_actual(self):
        added = predictions.append_for([self._item("Q-1"), self._item("Q-2", hypothesis="")], self.state)
        self.assertEqual(added, ["Q-1"])
        recs = predictions.load(self.state)
        self.assertEqual(len(recs), 1)
        self.assertIsNone(recs[0]["actual"])
        self.assertEqual(recs[0]["predicted"], "above")
        self.assertEqual(predictions.append_for([self._item("Q-1")], self.state), [])
        self.assertEqual(len(predictions.load(self.state)), 1)

    def test_invalid_band_gets_no_record(self):
        self.assertEqual(predictions.append_for([self._item("Q-3", predicted="viral")], self.state), [])

    def test_actual_lands_beside_predicted(self):
        predictions.append_for([self._item("Q-1")], self.state)
        r = predictions.set_actual("Q-1", "baseline", score=12.0, index=1.1, partial=True, state=self.state)
        self.assertEqual((r["predicted"], r["actual"], r["partial"]), ("above", "baseline", True))
        self.assertIsNone(predictions.set_actual("Q-9", "below", state=self.state))

    def test_ingest_appends_a_prediction(self):
        saved = (repo.CAL, repo.STATE)
        repo.CAL = os.path.join(self.state, "Calendar"); repo.STATE = self.state
        os.makedirs(repo.CAL)
        try:
            item = self._item("Q-T-8", title="Eight", post="Body.", teaser_linkedin="a", teaser_x="b",
                              tags=["#ExampleTheme"], anchor="x", logic="L1", finding_id="F1", hooks_considered=[])
            repo.write_item(item, "Idea")
            got = repo.load_items()[0]
            self.assertEqual((got["query"], got["predicted"], got["test_id"]), ("gaps", "above", "none"))
            self.assertEqual(predictions.append_for(repo.load_items(), self.state), ["Q-T-8"])
        finally:
            repo.CAL, repo.STATE = saved


if __name__ == "__main__":
    unittest.main()
