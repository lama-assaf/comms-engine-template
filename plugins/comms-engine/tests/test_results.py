"""results.py: what each job produced since a moment, from fixture state only."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import results  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 6, 8, 0, tzinfo=UTC)
SINCE = NOW - dt.timedelta(hours=24)


def write(d, name, obj):
    os.makedirs(os.path.dirname(os.path.join(d, name)), exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        os.makedirs(self.state)
        write(self.state, "runs.json", [
            {"run_id": "old", "step": "gate", "at": "2026-10-01T07:00:00+00:00", "stream": "Acme", "detail": "old gate"},
            {"run_id": "r1", "step": "listen", "at": "2026-11-05T19:00:00+00:00", "stream": "Acme", "items": 76, "terms": 9, "elapsed_s": 40},
            {"run_id": "r1", "step": "distribute", "at": "2026-11-05T20:40:00+00:00", "stream": "Acme", "item": "Q-2026-11-06-exampletheme-1", "published_to": []},
            {"run_id": "r2", "step": "engage", "at": "2026-11-05T19:55:00+00:00", "stream": "Acme", "detail": "2 comment drafts"},
            {"run_id": "r3", "step": "score", "at": "2026-11-05T21:00:00+00:00", "stream": "Acme", "detail": "0 scored, 17 partial"},
            {"run_id": "r4", "step": "claims-check", "at": "2026-11-05T21:15:00+00:00", "stream": "Acme", "detail": "0 notes for review"},
        ])
        write(self.state, "signals.json", {"run_id": "20261105T190000Z", "window": {"from": "2026-10-29T00:00:00Z", "to": "2026-11-05T19:00:00Z"},
                                           "findings": [{"id": "F1"}, {"id": "F2"}],
                                           "per_theme": {"#ExampleTheme": {"relevance": 3.1, "count": 12}, "#Other": {"relevance": 1.0, "count": 2}},
                                           "handed_on": {"hold for review": ["F2 a statistic"]}})
        write(self.state, "engagement.json", {"pass_at": "2026-11-05T19:55:00+00:00", "stream": "Acme",
                                              "proposals": [{"platform": "X", "theme": "#ExampleTheme", "shape": "sharper follow-up question"}],
                                              "skipped": [{"id": "F3"}, {"id": "F4"}],
                                              "inbound": {"posts_in_last_three_days": 0}})
        write(self.state, "metrics.json", {"computed_at": "2026-11-05T21:00:00+00:00", "rows": [{"row": "a", "status": "live"}, {"row": "b", "status": "partial"}]})
        write(self.state, "claims-review.json", {"checked_at": "2026-11-05T21:15:00+00:00", "items": []})
        write(self.state, "corpus-cycle.log", "2026-10-01T06:30 nothing pending; no Claude run\n2026-11-05T20:17 pending work found, running /corpus-cycle\n2026-11-05T20:17 /corpus-cycle exit 0\n")
        write(self.state, "autopilot.log", "2026-11-05T20:13:14 refused: quiet hours\n2026-11-05T20:13:14 stale LinkedIn 2026-10-08 x: more than 2 days late, not posted\n2026-11-05T20:13:14 posted 0 row(s)\n2026-11-05T20:13:23 link replies added 0\n")
        write(self.state, "send-ledger.json", {"sends": {"p1": {"platform": "X", "state": "sent", "at": "2026-09-22T13:20:56+00:00"}}})
        self.engine_json = os.path.join(self.tmp.name, "engine.json")
        write(self.tmp.name, "engine.json", {"jobs": [
            {"label": "com.acme.social-engine", "what": "the cycle", "calendar": [{"Weekday": d, "Hour": 7, "Minute": 15} for d in range(1, 6)]},
            {"label": "com.acme.corpus-cycle", "what": "corpus", "calendar": [{"Weekday": 5, "Hour": 6, "Minute": 30}]},
            {"label": "com.acme.autopilot", "what": "sender", "calendar": [{"Hour": 9, "Minute": 5}, {"Hour": 13, "Minute": 35}]},
            {"label": "com.acme.nosleep", "what": "caffeinate", "keep_alive": True},
        ]})
        self.items = [
            {"id": "Q-2026-11-06-exampletheme-1", "title": "An example", "drafted_at": "2026-11-05T20:40:00+00:00", "theme": "#ExampleTheme",
             "gate": {"verdict": "pass-with-edits"}, "alpha_status": "proposed", "slot": {"date": "2026-11-06"}},
            {"id": "Q-2026-09-09-old-1", "title": "Old", "drafted_at": "2026-09-07T20:15:00+00:00", "gate": {"verdict": "pass"}, "slot": {"date": "2026-09-09"}},
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def digest(self, since=SINCE):
        results.LOCAL = BERLIN
        return results.digest(since=since, now=NOW, state_dir=self.state, items=self.items, repo=self.tmp.name,
                              marker_path=os.path.join(self.tmp.name, "none.json"), engine_json=self.engine_json)

    def test_every_job_reports_its_window(self):
        d = self.digest()
        by = {j["short"]: j for j in d["jobs"]}
        self.assertIn("1 draft written or rewritten (1 pass-with-edits)", by["cycle"]["lines"][0]["text"])
        self.assertIn("Q-2026-11-06-exampletheme-1", by["cycle"]["lines"][1]["text"])
        self.assertTrue(any("listening pass 20261105T190000Z: 2 findings" in l["text"] and "1 held for a person" in l["text"] for l in by["cycle"]["lines"]))
        self.assertIn("1 comment draft waiting for Alpha, 2 skipped", by["engagement"]["lines"][0]["text"])
        self.assertIn("0 own posts in the three-day window", by["engagement"]["lines"][1]["text"])
        self.assertIn("scorecard recomputed: 2 rows", by["score"]["lines"][0]["text"])
        self.assertIn("0 notes whose cited claim moved", by["claims-check"]["lines"][0]["text"])
        self.assertIn("1 Claude run on the corpus", by["corpus"]["lines"][0]["text"])
        self.assertIn("1 run: posted 0, link replies 0, 1 refused by guardrails, 1 stale row not posted", by["autopilot"]["lines"][0]["text"])
        self.assertEqual(by["x-stream"]["lines"], [])

    def test_old_records_fall_outside_the_window(self):
        d = self.digest(since=NOW - dt.timedelta(hours=1))
        self.assertTrue(all(not j["lines"] for j in d["jobs"]), d["jobs"])
        self.assertIn("nothing produced", results.lines(d)[-1])

    def test_labels_come_from_engine_json(self):
        by = {j["short"]: j["label"] for j in self.digest()["jobs"]}
        self.assertEqual(by["cycle"], "com.acme.social-engine")
        self.assertEqual(by["corpus"], "com.acme.corpus-cycle")
        self.assertEqual(by["engagement"], "")

    def test_schedule_next_fire_and_keep_alive(self):
        with open(self.engine_json) as f:
            jobs = json.load(f)["jobs"]
        sched = {s["label"]: s for s in results.schedule(jobs, NOW, BERLIN)}
        # NOW is Friday 2026-11-06 08:00 UTC = 09:00 Berlin; the cycle fired at 07:15 so next is Monday
        self.assertEqual(sched["com.acme.social-engine"]["next"], "2026-11-09T06:15+00:00")
        self.assertEqual(sched["com.acme.corpus-cycle"]["next"], "2026-11-13T05:30+00:00")
        self.assertEqual(sched["com.acme.autopilot"]["next"], "2026-11-06T08:05+00:00")
        self.assertIsNone(sched["com.acme.nosleep"]["next"])
        self.assertTrue(sched["com.acme.nosleep"]["keep_alive"])

    def test_no_handle_in_any_line(self):
        for j in self.digest()["jobs"]:
            for l in j["lines"]:
                self.assertNotRegex(l["text"], r"@[A-Za-z0-9_]{3,}")


class Since(unittest.TestCase):
    def test_relative_iso_and_marker(self):
        now = NOW
        self.assertEqual(results.since_from("36h", now), now - dt.timedelta(hours=36))
        self.assertEqual(results.since_from("7d", now), now - dt.timedelta(days=7))
        self.assertEqual(results.since_from("2026-11-05T20:11:00+00:00", now), dt.datetime(2026, 11, 5, 20, 11, tzinfo=UTC))
        with self.assertRaises(ValueError):
            results.since_from("yesterday", now)
        with tempfile.TemporaryDirectory() as d:
            mk = os.path.join(d, "m.json")
            with open(mk, "w") as f:
                json.dump({"last_session": "2026-11-05T18:17:00+00:00"}, f)
            self.assertEqual(results.since_from(None, now, mk), dt.datetime(2026, 11, 5, 18, 17, tzinfo=UTC))
            self.assertEqual(results.since_from(None, now, os.path.join(d, "absent.json")), now - results.DEFAULT_WINDOW)

    def test_local_stamps_are_read_in_the_given_zone(self):
        t = results.parse_ts("2026-11-05T20:13:14", assume=BERLIN)
        self.assertEqual(t, dt.datetime(2026, 11, 5, 19, 13, 14, tzinfo=UTC))
        self.assertEqual(results.parse_ts("2026-11-05T20:13:14", assume=UTC), dt.datetime(2026, 11, 5, 20, 13, 14, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
