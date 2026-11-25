"""
Scoring at 72 hours and 7 days (plan v2, item A9).

1. **A scored fixture item shows weights, negatives, baseline and no handle.**
   The weighted score follows the intent ladder; negatives are counted apart;
   the baseline is absent (and the record partial) until three earlier
   records exist on the same platform and format; nothing in the record
   names an author.
2. **`actual` lands beside `predicted`** in `predictions.json` once the
   7-day window closes, as a band from the index.
3. **Windows close on time**: before 72 h nothing is written; between 72 h
   and 7 d only the first window; a full window is never rewritten.
4. **Listening alone** counts replies and quotes, marked partial.
5. **Demand per theme** is written into `signals.json` as counts.
6. **The autopilot's ledgers** are read: a publish-log entry becomes a
   published item keyed by the autopilot's queue id when the title matches.
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
import predictions  # noqa: E402
import score  # noqa: E402

PUB = dt.datetime(2026, 10, 1, 8, 0, tzinfo=dt.timezone.utc)


def item(iid, platform="X", fmt="Observation", theme="#ExampleTheme", url="https://x.com/acme_hq/status/111"):
    return {"id": iid, "stream": "Acme", "theme": theme, "title": f"Title {iid}", "format": fmt,
            "slot": {"platform": platform}, "published_at": PUB.isoformat(timespec="seconds"), "cta": url,
            "query": "gaps", "hypothesis": "h", "predicted": "above", "test_id": "none"}


class Scoring(fixture_memory.FixtureMemoryCase):
    """The registry row and the theme roster come from the fixture memory."""

    def setUp(self):
        super().setUp()
        self.state = tempfile.mkdtemp(prefix="score-")
        os.makedirs(os.path.join(self.state, "metrics-input"))

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def read(self, iid, at, **counts):
        p = os.path.join(self.state, "metrics-input", f"{iid}.json")
        data = {"reads": []}
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        data["reads"].append({"at": at.isoformat(timespec="seconds"), "platform": "X", **counts})
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def run_at(self, now, items, dry_run=False):
        return score.score_all("acme", self.state, now=now, items=items, publish_log={"entries": []},
                               ledger={"sends": {}}, queue=[], dry_run=dry_run)

    def test_weights_negatives_baseline_and_no_handle(self):
        it = item("Q-1")
        predictions.append_for([it], self.state)
        self.read("Q-1", PUB + dt.timedelta(days=6), impressions=1000, likes=10, reposts=2, quotes=1,
                  replies=4, substantive_replies=2, saves=1, link_clicks=3, profile_clicks=1,
                  negatives={"unfollows": 1, "hides": 0, "corrections": 2}, author="@someone")
        records, done = self.run_at(PUB + dt.timedelta(days=8), [it])
        self.assertEqual(done, ["Q-1"])
        r = records[0]
        # 3*(1+1+2+3+1) + 2*2 + 1*10 = 24 + 4 + 10
        self.assertEqual(r["score"], 38)
        self.assertEqual(r["negatives_total"], 3)
        self.assertEqual(r["at_7d"]["negatives"]["corrections"], 2)
        self.assertEqual(r["at_7d"]["impressions"], 1000)
        self.assertIsNone(r["baseline"])
        self.assertTrue(r["partial"])
        self.assertNotIn("author", json.dumps(r))
        self.assertNotIn("someone", json.dumps(r))
        self.assertEqual(r["at_7d"]["source"], ["platform read"])
        # actual beside predicted: no baseline yet, so the band is None but score lands
        p = predictions.load(self.state)[0]
        self.assertEqual(p["predicted"], "above")
        self.assertEqual(p["score"], 38)
        self.assertIsNone(p["actual"])
        self.assertTrue(p["partial"])

    def test_baseline_after_three_records_and_the_band(self):
        items = [item(f"Q-{i}", url=f"https://x.com/acme_hq/status/{i}") for i in range(1, 5)]
        predictions.append_for(items, self.state)
        for i, likes in ((1, 10), (2, 20), (3, 30)):
            self.read(f"Q-{i}", PUB + dt.timedelta(days=6), likes=likes)
        self.read("Q-4", PUB + dt.timedelta(days=6), likes=60)
        records, _ = self.run_at(PUB + dt.timedelta(days=8), items)
        by = {r["id"]: r for r in records}
        self.assertEqual(by["Q-4"]["baseline"], 20)   # median of 10, 20, 30
        self.assertEqual(by["Q-4"]["index"], 3.0)
        self.assertFalse(by["Q-4"]["partial"])
        p = {r["id"]: r for r in predictions.load(self.state)}["Q-4"]
        self.assertEqual(p["actual"], "above")
        self.assertEqual(score.band(0.5), "below")
        self.assertEqual(score.band(1.0), "baseline")

    def test_windows_close_on_time_and_never_rewrite_a_full_window(self):
        it = item("Q-1")
        self.read("Q-1", PUB + dt.timedelta(days=2), likes=5)
        records, done = self.run_at(PUB + dt.timedelta(hours=48), [it])
        self.assertEqual(records[0].get("at_72h"), None)
        records, _ = self.run_at(PUB + dt.timedelta(hours=80), [it])
        self.assertEqual(records[0]["at_72h"]["likes"], 5)
        self.assertNotIn("at_7d", records[0])
        # a later read does not rewrite the closed, full 72 h window
        self.read("Q-1", PUB + dt.timedelta(days=2, hours=12), likes=50)
        records, _ = self.run_at(PUB + dt.timedelta(days=8), [it])
        self.assertEqual(records[0]["at_72h"]["likes"], 5)
        self.assertEqual(records[0]["at_7d"]["likes"], 50)

    def test_listening_alone_is_partial(self):
        it = item("Q-1", url="https://x.com/acme_hq/status/777")
        os.makedirs(os.path.join(self.state, "x-stream"))
        with open(os.path.join(self.state, "x-stream", "2026-10-02.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "1", "inReplyToId": "777", "createdAt": "2026-10-02T09:00:00+00:00", "author": {"userName": "someone"}}) + "\n")
            f.write(json.dumps({"id": "2", "quoted_tweet": {"id": "777"}, "createdAt": "2026-10-03T09:00:00+00:00"}) + "\n")
            f.write(json.dumps({"id": "3", "inReplyToId": "777", "createdAt": "2026-10-20T09:00:00+00:00"}) + "\n")
        with open(os.path.join(self.state, "listening-20261003T000000Z.json"), "w", encoding="utf-8") as f:
            json.dump({"items": [{"text": "see https://x.com/acme_hq/status/777", "created_at": "Fri Oct 02 10:00:00 +0000 2026"}]}, f)
        records, _ = self.run_at(PUB + dt.timedelta(days=8), [it])
        w = records[0]["at_7d"]
        self.assertEqual((w["replies"], w["quotes"]), (1, 2))
        self.assertEqual(w["source"], ["listening"])
        self.assertTrue(w["partial"])
        self.assertNotIn("someone", json.dumps(records))

    def test_demand_per_theme(self):
        with open(os.path.join(self.state, "signals.json"), "w", encoding="utf-8") as f:
            json.dump({"per_theme": {"#ExampleTheme": {"count": 1}},
                       "findings": [{"theme": "#ExampleTheme", "conversation": {"target": "t"}},
                                    {"theme": "#ExampleTheme", "conversation": "None"}]}, f)
        with open(os.path.join(self.state, "engagement.json"), "w", encoding="utf-8") as f:
            json.dump({"records": [{"id": "Q-1", "theme": "#ExampleTheme", "at_7d": {"substantive_replies": 2, "quotes": 1}}]}, f)
        d = score.demand("acme", self.state)
        self.assertEqual(d["#ExampleTheme"], 4)
        with open(os.path.join(self.state, "signals.json"), encoding="utf-8") as f:
            sig = json.load(f)
        self.assertEqual(sig["per_theme"]["#ExampleTheme"]["demand"], 4)
        self.assertEqual(sig["per_theme"]["#FourthTheme"]["demand"], 0)

    def test_only_publications_count_and_join_by_id_then_title(self):
        log = {"entries": [
            {"id": "P9", "target": "calendar:blog", "page_id": "pg0", "state": "Idea", "url": "https://www.example.com/cal/x",
             "published_at": "2026-10-05T05:00:00+00:00"},
            {"id": "P9", "target": "calendar:x", "page_id": "pgx", "state": "Ready", "url": "https://www.example.com/cal/y",
             "published_at": "2026-10-05T05:00:00+00:00"},
            {"id": "P9", "target": "calendar:blog", "page_id": "pg0", "state": "Published", "url": "https://www.example.com/cal/x",
             "published_at": "2026-10-07T05:00:00+00:00"},
            {"target": "linkedin", "page_id": "pg1", "title": "Sovereign compute starts here",
             "url": "https://www.linkedin.com/feed/update/urn:li:share:1", "published_at": "2026-10-08T05:00:00+00:00"},
            {"id": "P2", "target": "calendar:blog", "page_id": "pg5", "state": "Idea", "published_at": "2026-10-01T05:00:00+00:00"}]}
        queue = [{"id": "P9", "title": "Sovereign compute starts here", "theme": "#FifthTheme", "stream": "Acme",
                  "cta": "https://www.example.com/insights/sc"},
                 {"id": "P2", "title": "Never published", "theme": "#ExampleTheme", "stream": "Acme"}]
        ledger = {"sends": {"pg2": {"page_id": "pg2", "platform": "X", "title": "Sovereign compute starts here",
                                    "state": "sent", "url": "https://x.com/acme_hq/status/999", "at": "2026-10-08T06:00:00+00:00"},
                            "pg3": {"page_id": "pg3", "platform": "X", "title": "Sovereign compute starts here", "state": "queued"}}}
        pub = score.published_items("Acme", items=[], publish_log=log, ledger=ledger, queue=queue)
        self.assertEqual([p["id"] for p in pub], ["P9"])
        self.assertEqual(pub[0]["theme"], "#FifthTheme")
        self.assertEqual(pub[0]["published_at"], "2026-10-07T05:00:00+00:00")
        self.assertEqual(set(pub[0]["urls"]), {"https://www.example.com/insights/sc", "https://www.linkedin.com/feed/update/urn:li:share:1",
                                               "https://x.com/acme_hq/status/999"})
        self.assertEqual(score.x_ids(pub[0]["urls"]), {"999"})


class RealState(fixture_memory.FixtureMemoryCase):
    def test_dry_run_on_the_real_ledgers(self):
        records, done = score.score_all(fixture_memory.ROOT, dry_run=True)
        for r in records:
            self.assertNotIn("author", json.dumps(r))
            self.assertIn(r.get("stream"), (fixture_memory.ROOT_NAME,))


if __name__ == "__main__":
    unittest.main()
