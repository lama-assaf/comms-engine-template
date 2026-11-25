"""
lifecycle.py: the append-only transition log.

- each move records from, to, time and what allowed it
- each move is refused without what it needs (verdict, act, guardrails, ledger row)
- current state is the fold of the lines; no line is draft
- a torn last line is skipped and does not spoil the next append
- the calendar note carries no lifecycle key; only lifecycle.py writes the log
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import acts  # noqa: E402
import lifecycle as lc  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.path = os.path.join(d, "lifecycle.jsonl")
        self.acts = os.path.join(d, "acts.jsonl")

    def approve(self, target="p1", decision="approve", base="h1", outcome="applied", kind="decision"):
        a = acts.record(kind, "acme", target, {"decision": decision}, base=base, path=self.acts)
        if outcome == "applied":
            acts.applied(a["id"], path=self.acts)
        elif outcome:
            acts.refused(a["id"], "x", path=self.acts)
        return a["id"]

    def gated(self, id="p1"):
        return lc.gate(id, "h1", "v1", stream="acme", path=self.path)

    def decided(self, id="p1"):
        self.gated(id)
        return lc.decide(id, self.approve(id), acts_path=self.acts, path=self.path)

    def scheduled(self, id="p1"):
        self.decided(id)
        return lc.schedule(id, "2026-11-12", lambda: (True, ""), path=self.path)

    def refused(self, fn, *a, **k):
        with self.assertRaises(lc.LifecycleError) as cm:
            fn(*a, **k)
        return str(cm.exception)


class TestMoves(Base):
    def test_full_path_records_what_allowed_each_move(self):
        self.scheduled()
        row = lc.sent("p1", {"id": "p1", "sent_at": "2026-11-12T09:05:00Z"}, path=self.path)
        self.assertEqual(row["from"], "scheduled")
        lc.scored("p1", {"id": "p1", "sent_at": "2026-11-12T09:05:00Z"}, path=self.path)
        got = lc.lines("p1", self.path)
        self.assertEqual([r["to"] for r in got], ["gated", "decided", "scheduled", "sent", "scored"])
        self.assertEqual(got[0]["allowed_by"], {"gate_verdict": "v1"})
        self.assertIn("decision_act", got[1]["allowed_by"])
        self.assertEqual(got[2]["date"], "2026-11-12")
        self.assertEqual(got[4]["published_at"], "2026-11-12T09:05:00Z")
        self.assertTrue(all(r["at"] and r["stream"] == "acme" for r in got))

    def test_gate_refuses_failing_or_missing_verdict(self):
        self.assertIn("not pass", self.refused(lc.gate, "p1", "h1", "v1", verdict="fail", path=self.path))
        self.assertIn("verdict_hash", self.refused(lc.gate, "p1", "h1", "", path=self.path))
        self.assertIn("text_hash", self.refused(lc.gate, "p1", "", "v1", path=self.path))
        self.assertEqual(lc.state("p1", self.path), "draft")

    def test_decide_refusals(self):
        self.assertIn("cannot move", self.refused(lc.decide, "p1", "x", acts_path=self.acts, path=self.path))
        self.gated()
        self.assertIn("no act", self.refused(lc.decide, "p1", "nope", acts_path=self.acts, path=self.path))
        for kw, msg in (({"kind": "edit"}, "not a decision"), ({"target": "other"}, "decision on"),
                        ({"decision": "hold"}, "not an approval"), ({"outcome": None}, "pending"),
                        ({"outcome": "refused"}, "refused"), ({"base": "h2"}, "different text")):
            aid = self.approve(**kw)
            self.assertIn(msg, self.refused(lc.decide, "p1", aid, acts_path=self.acts, path=self.path), kw)
        self.assertEqual(lc.state("p1", self.path), "gated")

    def test_schedule_refusals(self):
        self.assertIn("cannot move", self.refused(lc.schedule, "p1", "2026-11-12", lambda: (True, ""), path=self.path))
        self.decided()
        self.assertIn("guardrails refuse: quiet", self.refused(lc.schedule, "p1", "2026-11-12",
                                                               lambda: (False, "quiet hours"), path=self.path))
        self.assertIn("not a date", self.refused(lc.schedule, "p1", "soon", lambda: (True, ""), path=self.path))
        self.assertIn("guardrails check", self.refused(lc.schedule, "p1", "2026-11-12", None, path=self.path))
        self.assertEqual(lc.state("p1", self.path), "decided")

    def test_sent_and_scored_refusals(self):
        self.assertIn("cannot move", self.refused(lc.sent, "p1", {"id": "p1", "sent_at": "t"}, path=self.path))
        self.scheduled()
        self.assertIn("no sent_at", self.refused(lc.sent, "p1", {"id": "p1"}, path=self.path))
        self.assertIn("ledger row is for", self.refused(lc.sent, "p1", {"id": "z", "sent_at": "t"}, path=self.path))
        self.assertIn("different text", self.refused(lc.sent, "p1", {"id": "p1", "sent_at": "t", "text_hash": "h9"}, path=self.path))
        lc.sent("p1", {"id": "p1", "sent_at": "T1"}, path=self.path)
        self.assertIn("sent time", self.refused(lc.scored, "p1", {"sent_at": "T2"}, path=self.path))
        self.assertIn("sent_at", self.refused(lc.scored, "p1", {}, path=self.path))

    def test_block_retire(self):
        self.gated()
        self.assertIn("reason", self.refused(lc.block, "p1", "", path=self.path))
        lc.block("p1", "stealth list", path=self.path)
        self.assertEqual(lc.state("p1", self.path), "blocked")
        self.assertIn("cannot block", self.refused(lc.block, "p1", "again", path=self.path))
        self.gated()  # a blocked post re-enters through the gate
        self.assertEqual(lc.state("p1", self.path), "gated")
        lc.retire("p1", "withdrawn", path=self.path)
        self.assertIn("cannot", self.refused(lc.retire, "p1", "x", path=self.path))
        self.assertIn("cannot move", self.refused(lc.gate, "p1", "h1", "v1", path=self.path))

    def test_sent_post_cannot_be_blocked_or_retired(self):
        self.scheduled()
        lc.sent("p1", {"id": "p1", "sent_at": "T"}, path=self.path)
        self.assertIn("sent post", self.refused(lc.block, "p1", "x", path=self.path))
        self.assertIn("sent post", self.refused(lc.retire, "p1", "x", path=self.path))

    def test_reschedule_moves_a_scheduled_post_and_refuses_once_sent(self):
        self.assertIn("cannot move", self.refused(lc.reschedule, "p1", "2026-11-14", lambda: (True, ""), path=self.path))
        self.scheduled()
        row = lc.reschedule("p1", "2026-11-14", lambda: (True, ""), path=self.path)
        self.assertEqual((row["from"], row["to"], row["date"], row["text_hash"]), ("scheduled", "scheduled", "2026-11-14", "h1"))
        self.assertEqual(row["allowed_by"]["rescheduled_from"], "2026-11-12")
        self.assertIn("guardrails refuse: cap", self.refused(lc.reschedule, "p1", "2026-11-15",
                                                             lambda: (False, "cap"), path=self.path))
        self.assertIn("not a date", self.refused(lc.reschedule, "p1", "later", lambda: (True, ""), path=self.path))
        self.assertEqual(lc.current("p1", self.path)["date"], "2026-11-14")
        lc.sent("p1", {"id": "p1", "sent_at": "T"}, path=self.path)
        self.assertIn("cannot move", self.refused(lc.reschedule, "p1", "2026-11-20", lambda: (True, ""), path=self.path))


class TestFold(Base):
    def test_fold_is_last_line_per_id(self):
        self.assertEqual(lc.state("p1", self.path), "draft")
        self.assertEqual(lc.fold(self.path), {})
        self.gated("p1")
        self.gated("p2")
        lc.decide("p2", self.approve("p2"), acts_path=self.acts, path=self.path)
        self.assertEqual({k: v["to"] for k, v in lc.fold(self.path).items()}, {"p1": "gated", "p2": "decided"})

    def test_torn_last_line_is_skipped_and_next_append_is_whole(self):
        self.gated("p1")
        with open(self.path, "a") as f:
            f.write('{"id": "p1", "from": "gated", "to": "deci')
        self.assertEqual(lc.state("p1", self.path), "gated")
        self.assertEqual(len(lc.lines("p1", self.path)), 1)
        lc.decide("p1", self.approve("p1"), acts_path=self.acts, path=self.path)
        self.assertEqual(lc.state("p1", self.path), "decided")
        good = [l for l in open(self.path).read().split("\n") if l.strip()]
        self.assertEqual(len(good), 3)
        json.loads(good[-1])

    def test_no_calendar_key_and_single_writer(self):
        src = open(os.path.join(os.path.dirname(HERE), "scripts", "lifecycle.py")).read()
        self.assertNotIn("Content/Calendar", src)
        self.assertNotIn("repo", src.replace("repository", ""))


if __name__ == "__main__":
    unittest.main()
