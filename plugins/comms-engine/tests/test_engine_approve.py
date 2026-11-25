"""
The approval with no person in it (`desk_acts.engine_approve`, `autopilot.py approve`).

With the post mode on `review`, the default, nothing changes: the engine approves nothing and
`channels.send()` still refuses a post no person approved. Where a person switched the mode to
`auto` on a stream whose autopilot is `by switch`:

- a gated draft whose verdict is `pass`, stamped by review.py for its present text on two
  reviewers who agreed, is approved by one `decision` act with `by: engine` that names the
  switch act that allowed it, then scheduled by the same applier
- a verdict that is not `pass`, a blocked gate, a channel still on review, a paused stream or
  a person's hold or rejection leaves the item in the queue, and records no act
- the argument line is not asked of the engine and is still asked of everyone else, and the
  dashboard can never make an act `by: engine`
- what the engine approved is sent only while the mode is still `auto`: switching back to
  `review` stops the next send
- the hold for review passes without a release only while the `hold` mode is `auto`

A temp vault and state directory on the fixture memory; every driver is a fake.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import acts  # noqa: E402
import autopilot as ap  # noqa: E402
import channels  # noqa: E402
import desk_acts  # noqa: E402
import lifecycle  # noqa: E402
import memory  # noqa: E402
import repo  # noqa: E402
import review  # noqa: E402
import standing_rules  # noqa: E402
import switches  # noqa: E402
from test_autopilot import LI_TEXT, TODAY, X_TEXT, Post, ok_guard  # noqa: E402
from test_switches import OLD_RULE  # noqa: E402


class Engine(Post):
    def setUp(self):
        super().setUp()
        ap.DRY = False
        self.root = ap.STREAM

    def by_switch(self, value="by switch"):
        with open(memory.STREAMS_MD, encoding="utf-8") as f:
            text = f.read()
        with open(memory.STREAMS_MD, "w", encoding="utf-8") as f:
            f.write(text.replace(OLD_RULE, value))

    def auto(self, kind="post", channels_=("x", "linkedin")):
        for key in channels_:
            got = switches.set_mode(self.root, key, kind, "auto", confirm=True, state=self.tmp)
            self.assertEqual(got["outcome"], "applied", got)

    def items(self):
        return {i["id"]: i for i in repo.load_items()}

    def approve(self, eid, **kw):
        return desk_acts.engine_approve(eid, self.items(), self.tmp, guard=ok_guard, **kw)

    def item(self, eid, title, *a, stamp=True, **kw):
        """An item as the Post fixture writes it, with the stamp review.py leaves on a passing review
        by two reviewers (unless `stamp=False`, or the verdict asked for is not a pass)."""
        item = super().item(eid, title, *a, **kw)
        if stamp and kw.get("verdict", "pass") == "pass":
            now = self.items()[eid]
            repo.set_fields(eid, {"gate": {"verdict": "pass", "reviewed_by": review.REVIEWER, "reviewed_at": "2026-11-05T07:00:00+00:00",
                                           "review": {"text_hash": review.text_key(now), "verdict": "pass",
                                                      "reviewers": ["gatekeeper", "gate-second.md"]}}})
        return item

    def decisions(self, by=None):
        return [a for a in acts.list_acts(path=self.apath) if a["kind"] == "decision" and (by is None or a["by"] == by)]


class ReviewIsTheDefault(Engine):
    def test_the_engine_approves_nothing_and_an_unapproved_post_is_not_sent(self):
        self.item("Q-1", "A draft nobody read", approve=False)
        got = self.approve("Q-1")
        self.assertTrue(got["outcome"].startswith("refused: "), got)
        self.assertIn("wait for a person", got["outcome"])
        self.assertEqual(self.decisions(), [], "a refusal before the act records nothing")
        self.assertEqual(ap.step_approve(), 0)
        n, _ = self.run_post()
        self.assertEqual((n, self.sent), (0, []))
        with self.assertRaises(channels.SendRefused) as cm:
            channels.send(self.root, "x", "post", X_TEXT, {"id": "Q-1:x", "text_gate": True}, driver=lambda r: {"url": "u"},
                          state=self.tmp, at=ap.NOW_DT)
        self.assertEqual(cm.exception.check, "kind rule")
        self.assertIn("must be scheduled", cm.exception.reason)

    def test_by_switch_alone_changes_nothing_until_a_person_switches_the_mode(self):
        self.by_switch()
        self.item("Q-1", "A draft nobody read", approve=False)
        self.assertTrue(self.approve("Q-1")["outcome"].startswith("refused: "))
        self.assertEqual(ap.step_approve(), 0)

    def test_a_rule_that_is_not_by_switch_cannot_be_switched_to_auto_for_posts(self):
        got = switches.set_mode(self.root, "x", "post", "auto", confirm=True, state=self.tmp)
        self.assertTrue(got["outcome"].startswith("refused: "))
        self.item("Q-1", "A draft nobody read", approve=False)
        self.assertTrue(self.approve("Q-1")["outcome"].startswith("refused: "))


class Auto(Engine):
    def setUp(self):
        super().setUp()
        self.by_switch()
        self.auto()

    def test_a_passing_draft_is_approved_by_the_engine_and_scheduled_by_the_same_applier(self):
        self.item("Q-1", "A clean draft", approve=False)
        got = self.approve("Q-1")
        self.assertEqual((got["outcome"], got["state"], got["date"], got["by"]), ("applied", "scheduled", TODAY.isoformat(), "engine"))
        own = [a for a in self.decisions("engine") if a["target"] == "Q-1"]
        self.assertEqual(len(own), 1)
        act = own[0]
        self.assertEqual((act["outcome"], act["payload"]["source"], act["payload"]["decision"]), ("applied", "engine", "approve"))
        switch_ids = {a["id"] for a in acts.list_acts(path=self.apath) if a["kind"] == "switch"}
        self.assertEqual(set(act["payload"]["allowed_by"]), {"x", "linkedin"})
        self.assertLessEqual(set(act["payload"]["allowed_by"].values()), switch_ids, "it names the switch acts that allowed it")
        for cid in ("Q-1:x", "Q-1:linkedin"):
            self.assertEqual(lifecycle.state(cid, self.lpath), "scheduled")
        self.assertEqual({a["by"] for a in self.decisions()}, {"engine"}, "each channel's own act is the engine's too")
        self.assertEqual(self.approve("Q-1")["outcome"], "skipped: moved", "a second pass decides nothing twice")

    def test_the_autopilot_step_approves_then_the_sender_sends_what_is_due(self):
        self.item("Q-1", "A clean draft", approve=False)
        self.item("Q-2", "A draft with edits pending", approve=False, verdict="pass-with-edits",
                  x="Another clean line about the standard.", linkedin="Another LinkedIn line about the standard.")
        self.assertEqual(ap.step_approve(), 1)
        self.assertEqual(lifecycle.state("Q-2", self.lpath), "draft", "anything short of pass stays in the queue")
        n, _ = self.run_post()
        self.assertEqual(n, 2)
        self.assertEqual(sorted(s[0] for s in self.sent), ["LinkedIn", "X"])
        self.assertEqual({s[1] for s in self.sent}, {X_TEXT, LI_TEXT})

    def test_a_dry_run_says_what_it_would_approve_and_records_nothing(self):
        self.item("Q-1", "A clean draft", approve=False)
        got = self.approve("Q-1", dry=True)
        self.assertEqual(got["outcome"], "would approve")
        self.assertEqual(self.decisions(), [])
        self.assertEqual(lifecycle.state("Q-1", self.lpath), "draft")

    def test_what_fails_stays_in_the_queue_and_records_no_act(self):
        self.item("Q-1", "Blocked by the gate", approve=False, verdict="block")
        self.item("Q-2", "Never gated", approve=False, verdict="")
        for eid, why in (("Q-1", "block"), ("Q-2", "missing")):
            got = self.approve(eid)
            self.assertTrue(got["outcome"].startswith("refused: "), got)
            self.assertIn(why, got["outcome"])
        self.assertEqual(self.approve("Q-none")["outcome"], "refused: no note carries this id")
        self.assertEqual(self.decisions(), [])

    def test_a_pass_that_review_py_did_not_stamp_for_this_text_is_not_enough(self):
        self.item("Q-1", "A verdict typed in", approve=False, stamp=False)
        got = self.approve("Q-1")
        self.assertIn("no review stamp", got["outcome"])
        self.item("Q-2", "Read by one reviewer", approve=False, x="A second clean line.", linkedin="A second LinkedIn line.")
        gate = self.items()["Q-2"]["gate"]
        repo.set_fields("Q-2", {"gate": dict(gate, review=dict(gate["review"], reviewers=["gatekeeper"]))})
        self.assertIn("two who agree", self.approve("Q-2")["outcome"])
        self.item("Q-3", "Edited after the review", approve=False, x="A third clean line.", linkedin="A third LinkedIn line.")
        repo.set_fields("Q-3", {"teaser_x": "A third clean line, edited since."})
        self.assertIn("no review stamp", self.approve("Q-3")["outcome"])
        self.assertEqual(self.decisions(), [])

    def test_one_channel_on_review_keeps_the_whole_item_for_a_person(self):
        switches.set_mode(self.root, "linkedin", "post", "review", state=self.tmp)
        self.item("Q-1", "A clean draft", approve=False)
        got = self.approve("Q-1")
        self.assertIn("LinkedIn wait for a person", got["outcome"])
        self.assertEqual(lifecycle.state("Q-1:x", self.lpath), "draft")

    def test_a_persons_hold_or_rejection_stands(self):
        self.item("Q-1", "Held by a person", approve=False)
        item = self.items()["Q-1"]
        held = acts.record("decision", item["stream"], "Q-1", {"decision": "hold", "note": "not this week"},
                           base=repo.base_hash(item), by="alpha", path=self.apath)
        acts.applied(held["id"], path=self.apath)
        got = self.approve("Q-1")
        self.assertIn("a person's decision stands", got["outcome"])
        self.assertEqual(self.decisions("engine"), [])
        repo.set_fields("Q-1", {"alpha_status": "rejected"})
        self.assertIn("a person's decision stands", self.approve("Q-1")["outcome"])

    def test_a_paused_stream_approves_nothing_and_sends_nothing(self):
        self.item("Q-1", "A clean draft", approve=False)
        self.approve("Q-1")
        switches.set_pause(self.root, True, state=self.tmp)
        self.item("Q-2", "Another clean draft", approve=False, x="A second clean line.", linkedin="A second LinkedIn line.")
        self.assertIn("paused", self.approve("Q-2")["outcome"])
        n, _ = self.run_post()
        self.assertEqual((n, self.sent), (0, []), "the pause stops what was already scheduled too")

    def test_switching_back_to_review_stops_the_next_send_of_what_the_engine_approved(self):
        self.item("Q-1", "A clean draft", approve=False)
        self.approve("Q-1")
        switches.set_mode(self.root, "x", "post", "review", state=self.tmp)
        n, _ = self.run_post()
        self.assertEqual([s[0] for s in self.sent], ["LinkedIn"], "X waits for a person; LinkedIn is still on auto")
        refused = [ln for ln in channels.sends(self.tmp) if ln["outcome"] == "refused"]
        self.assertEqual([(ln["check"], ln["id"]) for ln in refused], [("kind rule", "Q-1:x")])
        self.assertIn("approved by the engine", refused[0]["reason"])

    def test_a_persons_approval_is_sent_whatever_the_mode(self):
        switches.set_mode(self.root, "x", "post", "review", state=self.tmp)
        switches.set_mode(self.root, "linkedin", "post", "review", state=self.tmp)
        self.item("Q-1", "Approved by a person")
        n, _ = self.run_post()
        self.assertEqual(n, 2)


class TheArgumentLineAndTheRole(Engine):
    def test_the_engine_role_skips_the_argument_line_and_nothing_else(self):
        self.assertIsNone(standing_rules.refusal("approved", None, "post", False, False, role="engine"))
        self.assertEqual(standing_rules.refusal("approved", None, "post", False, True, role="engine"), standing_rules.BLOCKED)
        self.assertEqual(standing_rules.refusal("held", None, "post", True, False, role="engine"), standing_rules.REASON)
        for role in (None, "alpha", "beta", "team", "Engine", "engine "):
            self.assertEqual(standing_rules.refusal("approved", None, "post", False, False, role=role), standing_rules.ARGUMENT, role)

    def test_the_dashboard_can_never_claim_to_be_the_engine(self):
        self.assertEqual(desk_acts.role_of("engine"), "alpha")
        self.assertNotIn("engine", desk_acts.ROLES)
        self.by_switch()
        self.auto()
        self.item("Q-1", "A clean draft", approve=False)
        got = desk_acts.approve_post("Q-1", "engine", self.items(), self.tmp, guard=ok_guard)
        self.assertEqual(got["outcome"], f"refused: {standing_rules.ARGUMENT}",
                         "a caller that names itself the engine is still asked for the argument line")
        self.assertEqual(self.decisions(), [])


class Hold(Engine):
    """Standing rule 4 as a switch: the hold waits for a release on `review` and passes on `auto`."""

    HELD = "Adoption grew 40% across the standard's registries."

    def send(self):
        return channels.send(self.root, "x", "post", self.HELD, {"id": "Q-1:x", "text_gate": True}, driver=lambda r: {"url": "u"},
                             state=self.tmp, at=ap.NOW_DT)

    def test_review_holds_and_auto_passes_and_every_other_check_still_runs(self):
        self.by_switch()
        self.item("Q-1", "A post with a statistic", x=self.HELD)
        with self.assertRaises(channels.SendRefused) as cm:
            self.send()
        self.assertEqual(cm.exception.check, "hold")
        self.auto("hold", ("x",))
        self.assertEqual(channels.mode(self.root, "x", "hold", self.tmp), "auto")
        self.assertEqual(self.send()["url"], "u")
        self.assertEqual(channels.hold_reasons(self.root, self.HELD), ["a statistic with no cited claim"],
                         "the text is still in a hold class; the mode is what let it through")

    def test_the_hold_mode_does_not_reach_another_channel_or_another_check(self):
        self.by_switch()
        self.auto("hold", ("linkedin",))
        self.item("Q-1", "A post with a statistic", x=self.HELD)
        with self.assertRaises(channels.SendRefused) as cm:
            self.send()
        self.assertEqual(cm.exception.check, "hold", "x is still on review")
        self.auto("hold", ("x",))
        stealth = memory.denylist(self.root)[0]
        with self.assertRaises(channels.SendRefused) as cm:
            channels.send(self.root, "x", "post", f"{self.HELD} {stealth} agrees.", {"id": "Q-1:x", "text_gate": True},
                          driver=lambda r: {"url": "u"}, state=self.tmp, at=ap.NOW_DT)
        self.assertIn(cm.exception.check, ("gate", "stealth"))


if __name__ == "__main__":
    import unittest
    unittest.main()
