"""
Engagement acts in the loop (plan v2, item A17).

- a recorded act carries shape, tier and (later) outcome; a handle is refused
  as a target; `due` lists acts past 72 h with no outcome; the ledger counts
  what earns a reply per tier and shape
- the golden-hour checklist exists for a published item and not otherwise
- partner reposts are counted by `score.py` as a high-intent signal, with
  no handle stored
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

import engage  # noqa: E402
import fixture_memory  # noqa: E402
import score  # noqa: E402

T0 = dt.datetime(2026, 10, 27, 9, tzinfo=dt.timezone.utc)


class Acts(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="engage-")

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def test_record_outcome_due_and_ledger(self):
        a = engage.record("Q-1", "#ExampleTheme", "X", "2103", "institution", "sharper question", "2104", state=self.state, now=T0)
        self.assertEqual(a["id"], "A-2026-10-27-1")
        self.assertIsNone(a["outcome"])
        self.assertEqual(engage.due(self.state, now=T0 + dt.timedelta(hours=10)), [])
        self.assertEqual([d["id"] for d in engage.due(self.state, now=T0 + dt.timedelta(hours=73))], ["A-2026-10-27-1"])
        engage.outcome("A-2026-10-27-1", "author replied", state=self.state, now=T0 + dt.timedelta(hours=73))
        self.assertEqual(engage.due(self.state, now=T0 + dt.timedelta(days=5)), [])
        engage.record("Q-1", "#ExampleTheme", "X", "2105", "institution", "sharper question", state=self.state, now=T0)
        led = engage.ledger(self.state)
        self.assertEqual(led["institution / sharper question"]["placed"], 2)
        self.assertEqual(led["institution / sharper question"]["author replied"], 1)
        self.assertEqual(led["institution / sharper question"]["open"], 1)
        with open(engage.path(self.state), encoding="utf-8") as f:
            self.assertNotIn("@", json.dumps(json.load(f)["acts"]))

    def test_handle_as_target_is_refused(self):
        with self.assertRaises(ValueError):
            engage.record("Q-1", "#ExampleTheme", "X", "@examplestandards", "institution", "sharper question", state=self.state)
        with self.assertRaises(ValueError):
            engage.record("Q-1", "#ExampleTheme", "X", "2103", "vip", "sharper question", state=self.state)

    def test_golden_hour_checklist_only_after_publish(self):
        self.assertEqual(engage.checklist({"id": "Q-1"}), [])
        cl = engage.checklist({"id": "Q-1", "published_at": "2026-10-27T09:00:00+00:00"})
        self.assertEqual(len(cl), 5)
        self.assertEqual(cl[0]["when"], "T+0")


class PartnerReposts(fixture_memory.FixtureMemoryCase):
    """The cleared partners come from the fixture handles.md, never the checkout's."""

    def test_counted_without_a_handle(self):
        state = tempfile.mkdtemp(prefix="score-partners-")
        try:
            os.makedirs(os.path.join(state, "x-stream"))
            with open(os.path.join(state, "x-stream", "2026-10-02.jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps({"id": "1", "retweeted_tweet": {"id": "777"}, "createdAt": "2026-10-02T09:00:00+00:00", "author": {"userName": "betalabs"}}) + "\n")
                f.write(json.dumps({"id": "2", "quoted_tweet": {"id": "777"}, "createdAt": "2026-10-02T09:00:00+00:00", "author": {"userName": "deltaco"}}) + "\n")
                f.write(json.dumps({"id": "3", "quoted_tweet": {"id": "777"}, "createdAt": "2026-10-02T09:00:00+00:00", "author": {"userName": "someone"}}) + "\n")
            partners = score.partner_handles(fixture_memory.ROOT)  # the default stream is fixed at import
            self.assertEqual(partners, {"betalabs", "deltaco"})
            until = dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc)
            seen = score.stream_reactions({"777"}, [], state, until, partners)
            self.assertEqual(seen["partner_reposts"], 2)
            self.assertEqual(seen["quotes"], 2)
            self.assertNotIn("author", json.dumps(seen))
        finally:
            shutil.rmtree(state, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
