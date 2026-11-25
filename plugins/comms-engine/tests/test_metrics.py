"""
The scorecard rows (plan v2, item A10).

- rows render "partial" where the source is listening only; the correlation
  is blank, not zero, before five pairs; reach is context unless the registry
  row opts in; the variety row counts distinct formats, logics and openers
- the Spearman rank correlation is right on known pairs
- the twelve key results from Principles s6 travel with the rows
"""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import metrics  # noqa: E402

NOW = dt.datetime(2026, 10, 26, 12, tzinfo=dt.timezone.utc)


def rec(iid, index, partial=False, negatives=1, impressions=100, published="2026-10-20T08:00:00+00:00"):
    return {"id": iid, "stream": "Acme", "index": index, "partial": partial, "negatives_total": negatives,
            "published_at": published, "at_7d": {"impressions": impressions}}


def item(iid, fmt, logic, title, date="2026-10-01"):
    return {"id": iid, "stream": "Acme", "format": fmt, "logic": logic, "title": title, "slot": {"date": date}}


class Rows(fixture_memory.FixtureMemoryCase):
    """The registry row that decides whether reach is context or an objective is the fixture's."""

    def rows(self, **kw):
        kw.setdefault("items", [])
        kw.setdefault("engagement", {"records": []})
        kw.setdefault("predictions", [])
        return {r["row"]: r for r in metrics.rows("acme", state="/nonexistent", now=NOW, **kw)["rows"]}

    def test_empty_state_is_blank_and_partial(self):
        r = self.rows()
        self.assertIsNone(r["engagement index"]["value"])
        self.assertEqual(r["engagement index"]["status"], "partial")
        self.assertIsNone(r["correlation"]["value"])
        self.assertEqual(r["correlation"]["status"], "blank")
        self.assertEqual(r["reach"]["status"], "context")
        self.assertIsNone(r["variety"]["value"])

    def test_partial_while_any_record_is_listening_only(self):
        full = {"records": [rec("a", 1.0), rec("b", 1.2)]}
        self.assertEqual(self.rows(engagement=full)["engagement index"]["status"], "full")
        self.assertEqual(self.rows(engagement=full)["engagement index"]["value"], 1.1)
        mixed = {"records": [rec("a", 1.0), rec("b", 1.2, partial=True)]}
        self.assertEqual(self.rows(engagement=mixed)["engagement index"]["status"], "partial")

    def test_negatives_and_reach_over_the_window(self):
        eng = {"records": [rec("a", 1.0, negatives=2, impressions=300), rec("b", 1.0, negatives=0, impressions=200),
                           rec("old", 1.0, negatives=9, impressions=999, published="2026-08-01T08:00:00+00:00")]}
        r = self.rows(engagement=eng)
        self.assertEqual(r["negatives guardrail"]["value"], 1.0)
        self.assertEqual(r["reach"]["value"], 500)

    def test_correlation_blank_before_five_pairs_then_live(self):
        four = [{"predicted": "above", "actual": "above"}] * 4
        self.assertIsNone(self.rows(predictions=four)["correlation"]["value"])
        five = [{"predicted": p, "actual": a} for p, a in
                (("below", "below"), ("baseline", "baseline"), ("above", "above"), ("below", "baseline"), ("above", "baseline"))]
        r = self.rows(predictions=five)["correlation"]
        self.assertEqual(r["status"], "live")
        self.assertGreater(r["value"], 0.5)
        self.assertEqual(metrics.spearman([(0, 0), (1, 1), (2, 2)]), 1.0)
        self.assertEqual(metrics.spearman([(0, 2), (1, 1), (2, 0)]), -1.0)

    def test_variety(self):
        same = [item(f"i{n}", "Observation", "L1", "The root is not a wallet.") for n in range(12)]
        self.assertEqual(self.rows(items=same)["variety"]["value"], round(3 / 36, 2))
        varied = [item(f"i{n}", f"F{n}", f"L{n}", f"Word{n} and more.") for n in range(12)]
        self.assertEqual(self.rows(items=varied)["variety"]["value"], 1.0)

    def test_key_results_travel(self):
        out = metrics.rows("acme", state="/nonexistent", now=NOW, items=[], engagement={}, predictions=[])
        self.assertEqual(len(out["key_results"]), 12)
        self.assertIn("Zero claims of live or deployed capability ahead of delivery", [k["key_result"] for k in out["key_results"]])


if __name__ == "__main__":
    unittest.main()
