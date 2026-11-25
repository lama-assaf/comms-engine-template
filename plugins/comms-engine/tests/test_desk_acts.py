#!/usr/bin/env python3
"""
The desk's rows as acts: `desk_acts.py`, reached through `desk_sync.pull`.

What is asserted:

1. A pulled approval reaches `scheduled` in the lifecycle (gated -> decided -> scheduled
   for the note's date), with the act applied and the guard asked for that date.
2. An act is made once: pulling again records nothing and moves nothing.
3. Conflicts skip: a post already past `gated`, or whose text changed after the gate,
   ends `skipped: moved`; an edit whose base is stale ends `skipped: moved`.
4. A refusal ends `refused: <reason>` and leaves the lifecycle where it was (a failing
   gate, a guardrails refusal).
5. Held, rejected and rewrite decisions, argument lines and reviews are recorded and
   applied, and move nothing; `by` is a role, never a name.
6. A dry run records nothing on disk; decisions.json, edits.json and arguments.json are
   written exactly as before.

Fakes only: a temp vault, state directory and database, and a fake guard. Nothing is sent.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import acts  # noqa: E402
import channels  # noqa: E402
import desk_acts  # noqa: E402
import desk_sync  # noqa: E402
import lifecycle  # noqa: E402
import repo  # noqa: E402
import standing_rules  # noqa: E402

NOTE = """---
title: {title}
date: '{date}'
status: Idea
stream: Testco
type: Reactive
pillar: Thesis
platform: Blog
format: X-vs-Y
owner: EV
slug: {eid}
excerpt: The claim.
engine_id: {eid}
theme: '#Theme'
gate_verdict: {verdict}
gate:
  verdict: {verdict}
alpha_status: proposed
cta: https://example.com/{eid}
partner_tags: []
drafted_by: theme-writer
---

{body}
"""


def ok_guard(item, date):
    ok_guard.calls.append((item["id"], date))
    return True, ""


ok_guard.calls = []


def no_guard(item, date):
    return False, "quiet hours"


class DeskActsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="desk-acts-")
        self.cal = os.path.join(self.tmp, "Content", "Calendar")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.cal)
        os.makedirs(self.state)
        self.db_path = os.path.join(self.state, "desk.db")
        self._saved = (repo.CAL, repo.STATE, desk_sync.STATE, desk_sync.REVIEWS_MD, desk_sync.DB_PATH)
        repo.CAL, repo.STATE = self.cal, self.state
        desk_sync.STATE, desk_sync.REVIEWS_MD = self.state, os.path.join(self.tmp, "reviews.md")
        desk_sync.DB_PATH = self.db_path
        ok_guard.calls = []
        self.note("Q-1", "First post", "2026-09-09", "pass", "Body one.")
        self.con = desk_sync.connect(self.db_path)
        desk_sync.ensure_schema(self.con)
        self.apath = os.path.join(self.state, "acts.jsonl")
        self.lpath = os.path.join(self.state, "lifecycle.jsonl")

    def tearDown(self):
        self.con.close()
        repo.CAL, repo.STATE, desk_sync.STATE, desk_sync.REVIEWS_MD, desk_sync.DB_PATH = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def note(self, eid, title, date, verdict, body):
        with open(os.path.join(self.cal, f"{title}.md"), "w", encoding="utf-8") as f:
            f.write(NOTE.format(eid=eid, title=title, date=date, verdict=verdict, body=body))

    def teasers(self, eid, title, linkedin, x):
        """The companion teasers note, the way repo.write_item writes it."""
        body = repo.teaser_body(linkedin, x, "#Theme", f"https://example.com/{eid}")
        with open(os.path.join(self.cal, f"{title} - teasers.md"), "w", encoding="utf-8") as f:
            f.write(f"---\ntitle: {title} - teasers\nplatform: LinkedIn\nstream: Testco\nengine_id: {eid}\n"
                    f"theme: '#Theme'\ncta: https://example.com/{eid}\n---\n\n{body}")

    def decide(self, eid, status, by="Alpha", at="2026-09-08T10:00:00+00:00", kind="post"):
        self.con.execute("INSERT INTO decisions (id, kind, status, note, by, at) VALUES (?, ?, ?, '', ?, ?)",
                         (eid, kind, status, by, at))
        self.con.commit()

    def confirm(self, eid, hook):
        """The argument line confirmed against the hook now on the card, as the desk or the dashboard does."""
        self.con.execute("INSERT INTO argument_lines (item_id, act, hook, claim, by, at) "
                         "VALUES (?, 'confirmed', ?, 'The claim.', 'alpha', '2026-09-08T10:00:00.000Z')", (eid, hook))
        self.con.commit()

    def pull(self, guard=ok_guard, dry_run=False):
        return desk_sync.pull(self.con, dry_run=dry_run, verbose=False, guard=guard)

    def outcomes(self):
        return {a["id"]: a["outcome"] for a in acts.list_acts(path=self.apath)}

    def test_approval_reaches_scheduled(self):
        self.decide("Q-1", "approved")
        made = self.pull()["acts"]
        self.assertEqual([m["outcome"] for m in made], ["applied"])
        row = lifecycle.current("Q-1", self.lpath)
        self.assertEqual((row["to"], row["date"]), ("scheduled", "2026-09-09"))
        self.assertEqual(row["stream"], "Testco")
        self.assertIn(("Q-1", "2026-09-09"), ok_guard.calls)
        (act,) = acts.list_acts(path=self.apath)
        self.assertEqual((act["kind"], act["by"], act["outcome"]), ("decision", "alpha", "applied"))
        self.assertEqual(act["payload"]["decision"], "approve")
        decided = [r for r in lifecycle.lines("Q-1", self.lpath) if r["to"] == "decided"]
        self.assertEqual(decided[0]["allowed_by"]["decision_act"], act["id"])
        decisions = json.load(open(os.path.join(self.state, "decisions.json")))
        self.assertEqual(decisions["Q-1"]["status"], "approved")

    def test_pulling_again_makes_nothing(self):
        self.decide("Q-1", "approved")
        self.pull()
        before = (open(self.apath).read(), open(self.lpath).read())
        self.assertEqual(self.pull()["acts"], [])
        self.assertEqual(before, (open(self.apath).read(), open(self.lpath).read()))

    def test_a_post_already_moved_is_skipped(self):
        self.decide("Q-1", "approved")
        self.pull()
        self.decide("Q-1", "approved", at="2026-09-08T11:00:00+00:00") if False else None
        self.con.execute("DELETE FROM decisions")
        self.decide("Q-1", "approved", at="2026-09-08T12:00:00+00:00")
        made = self.pull()["acts"]
        self.assertEqual([m["outcome"] for m in made], ["skipped: moved"])
        self.assertEqual(lifecycle.state("Q-1", self.lpath), "scheduled")

    def test_text_changed_after_the_gate_is_skipped(self):
        item = repo.load_items()[0]
        lifecycle.gate("Q-1", "an-older-hash", "v", stream="Testco", path=self.lpath)
        self.decide("Q-1", "approved")
        made = self.pull()["acts"]
        self.assertEqual([m["outcome"] for m in made], ["skipped: moved"])
        self.assertEqual(lifecycle.state("Q-1", self.lpath), "gated")
        self.assertTrue(item)

    def test_failing_gate_is_refused(self):
        self.note("Q-1", "First post", "2026-09-09", "block", "Body one.")
        self.decide("Q-1", "approved")
        (m,) = self.pull()["acts"]
        self.assertTrue(m["outcome"].startswith("refused: the gate verdict is"), m)
        self.assertEqual(lifecycle.state("Q-1", self.lpath), "draft")
        self.assertTrue(self.outcomes()[m["id"]].startswith("refused: "))

    def test_pass_with_edits_is_allowed_like_channels_send(self):
        self.note("Q-1", "First post", "2026-09-09", "pass-with-edits", "Body one.")
        self.decide("Q-1", "approved")
        (m,) = self.pull()["acts"]
        self.assertEqual(m["outcome"], "applied")
        self.assertEqual(lifecycle.state("Q-1", self.lpath), "scheduled")
        self.assertIsNone(lifecycle.gate_refusal("pass-with-edits"))
        self.assertIsNone(lifecycle.gate_refusal("pass"))
        self.assertIn("not pass or pass-with-edits", lifecycle.gate_refusal("block"))
        self.assertIn("missing", lifecycle.gate_refusal(""))

    def test_dashboard_approve_uses_the_same_applier_and_never_sends(self):
        self.confirm("Q-1", "First post")
        items = {i["id"]: i for i in repo.load_items()}
        got = desk_acts.approve_post("Q-1", "Alpha", items, self.state, guard=ok_guard, reason="the claim is on the register")
        self.assertEqual((got["outcome"], got["state"], got["date"]), ("applied", "scheduled", "2026-09-09"))
        (act, review) = acts.list_acts(path=self.apath)
        self.assertEqual((act["kind"], act["by"], act["outcome"], act["payload"]["source"]),
                         ("decision", "alpha", "applied", "dashboard"))
        self.assertEqual((review["kind"], review["payload"]["scope"], review["payload"]["rationale"]),
                         ("review", "item", "the claim is on the register"))
        self.assertFalse(os.path.exists(os.path.join(self.state, "sends.jsonl")))
        # a second approve records its own act and is skipped: the post has moved
        again = desk_acts.approve_post("Q-1", "alpha", items, self.state, guard=ok_guard, reason="again")
        self.assertEqual(again["outcome"], "skipped: moved")
        self.assertEqual(lifecycle.state("Q-1", self.lpath), "scheduled")

    def test_dashboard_approve_refusals_end_the_act_with_a_reason(self):
        self.confirm("Q-1", "First post")
        items = {i["id"]: i for i in repo.load_items()}
        got = desk_acts.approve_post("Q-1", "someone@example.com", items, self.state, guard=no_guard, reason="r")
        self.assertEqual(got["outcome"], "refused: guardrails: quiet hours")
        self.assertEqual(lifecycle.state("Q-1", self.lpath), "draft")
        (act,) = acts.list_acts(path=self.apath)
        self.assertEqual((act["by"], act["outcome"]), ("alpha", "refused: guardrails: quiet hours"))
        self.note("Q-2", "Second post", "2026-09-10", "block", "Body two.")
        self.confirm("Q-2", "Second post")
        items = {i["id"]: i for i in repo.load_items()}
        got = desk_acts.approve_post("Q-2", "alpha", items, self.state, guard=ok_guard, reason="r")
        self.assertEqual(got["outcome"], "refused: " + standing_rules.BLOCKED)
        got = desk_acts.approve_post("Q-9", "alpha", items, self.state, guard=ok_guard, reason="r")
        self.assertEqual(got["outcome"], "refused: no note carries this id")

    def test_guardrails_refusal_leaves_the_lifecycle_alone(self):
        self.decide("Q-1", "approved")
        (m,) = self.pull(guard=no_guard)["acts"]
        self.assertEqual(m["outcome"], "refused: guardrails: quiet hours")
        self.assertEqual(lifecycle.state("Q-1", self.lpath), "draft")
        self.assertFalse(os.path.exists(self.lpath))

    def test_other_decisions_and_rows_are_recorded_and_move_nothing(self):
        self.decide("Q-1", "held", by="Some Person")
        self.con.execute("INSERT INTO argument_lines (item_id, act, hook, claim, by, at) "
                         "VALUES ('Q-1', 'confirmed', 'h', 'c', 'Alpha', '2026-09-08T10:00:00+00:00')")
        self.con.execute("INSERT INTO reviews (item_id, kind, theme, title, verdict, rationale, scope, by, at) "
                         "VALUES ('Q-1', 'post', '#Theme', 't', 'held', 'why', 'item', 'Alpha', '2026-09-08T10:00:00+00:00')")
        self.con.commit()
        made = self.pull()["acts"]
        self.assertEqual(sorted(m["kind"] for m in made), ["argument_line", "decision", "review"])
        self.assertEqual({m["outcome"] for m in made}, {"applied"})
        self.assertEqual({a["by"] for a in acts.list_acts(path=self.apath)}, {"alpha"})
        self.assertFalse(os.path.exists(self.lpath))

    def test_edit_applied_or_skipped_by_its_base(self):
        item = repo.load_items()[0]
        row = ("Q-1", "T", "new post", "", "", repo.base_hash(item), "Alpha", "2026-09-08T10:00:00+00:00")
        self.con.execute("INSERT INTO edits (item_id, title, post, teaser_linkedin, teaser_x, base_hash, by, at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
        self.con.execute("INSERT INTO edits (item_id, title, post, teaser_linkedin, teaser_x, base_hash, by, at) "
                         "VALUES ('Q-2', 'T', 'x', '', '', 'stale', 'Alpha', '2026-09-08T10:00:00+00:00')")
        self.con.commit()
        self.note("Q-2", "Second post", "2026-09-10", "pass", "Other body.")
        outcomes = {m["target"]: m["outcome"] for m in self.pull()["acts"]}
        self.assertEqual(outcomes, {"Q-1": "applied", "Q-2": "skipped: moved"})

    def test_dry_run_writes_nothing(self):
        self.decide("Q-1", "approved")
        made = self.pull(dry_run=True)["acts"]
        self.assertEqual([m["outcome"] for m in made], ["applied"])
        self.assertFalse(os.path.exists(self.apath))
        self.assertFalse(os.path.exists(self.lpath))
        self.assertFalse(os.path.exists(os.path.join(self.state, "decisions.json")))

    def test_approval_schedules_each_channel_on_its_own_act(self):
        self.teasers("Q-1", "First post", "The LinkedIn cut.", "The X cut.")
        self.decide("Q-1", "approved")
        (m,) = self.pull()["acts"]
        self.assertEqual(m["outcome"], "applied")
        for key, text in (("linkedin", "The LinkedIn cut."), ("x", "The X cut.")):
            cid = f"Q-1:{key}"
            row = lifecycle.current(cid, self.lpath)
            self.assertEqual((row["to"], row["date"], row["text_hash"]),
                             ("scheduled", "2026-09-09", channels.text_hash(key, text)))
            decided = [r for r in lifecycle.lines(cid, self.lpath) if r["to"] == "decided"][0]
            (own,) = [a for a in acts.list_acts(path=self.apath) if a["target"] == cid]
            self.assertEqual(decided["allowed_by"]["decision_act"], own["id"])
            self.assertEqual((own["outcome"], own["base"], own["payload"]["approval"], own["by"]),
                             ("applied", channels.text_hash(key, text), m["id"], "alpha"))
        self.assertEqual(lifecycle.state("Q-1", self.lpath), "scheduled")
        self.assertIn(("Q-1", "2026-09-09"), ok_guard.calls)

    def test_a_channel_with_no_teaser_is_not_scheduled(self):
        self.teasers("Q-1", "First post", "The LinkedIn cut.", "")
        self.decide("Q-1", "approved")
        self.pull()
        self.assertEqual(lifecycle.state("Q-1:linkedin", self.lpath), "scheduled")
        self.assertEqual(lifecycle.state("Q-1:x", self.lpath), "draft")

    def test_a_channel_the_guardrails_refuse_refuses_the_whole_approval(self):
        self.teasers("Q-1", "First post", "The LinkedIn cut.", "The X cut.")

        def x_closed(item, date):
            return (False, "drafts only") if item["slot"]["platform"] == "X" else (True, "")

        self.decide("Q-1", "approved")
        (m,) = self.pull(guard=x_closed)["acts"]
        self.assertEqual(m["outcome"], "refused: guardrails: X: drafts only")
        self.assertFalse(os.path.exists(self.lpath))

    def test_reschedule_moves_every_id_until_one_is_sent(self):
        self.teasers("Q-1", "First post", "The LinkedIn cut.", "The X cut.")
        self.decide("Q-1", "approved")
        self.pull()
        item = {i["id"]: i for i in repo.load_items()}["Q-1"]
        moved = desk_acts.reschedule(item, "2026-09-12", self.state, guard=ok_guard)
        self.assertEqual(sorted(moved), ["Q-1", "Q-1:linkedin", "Q-1:x"])
        self.assertEqual({lifecycle.current(i, self.lpath)["date"] for i in moved}, {"2026-09-12"})
        with self.assertRaises(lifecycle.LifecycleError):
            desk_acts.reschedule(item, "2026-09-13", self.state, guard=no_guard)
        lifecycle.sent("Q-1:x", {"id": "Q-1:x", "sent_at": "2026-09-12T09:00:00Z"}, path=self.lpath)
        with self.assertRaises(lifecycle.LifecycleError) as cm:
            desk_acts.reschedule(item, "2026-09-14", self.state, guard=ok_guard)
        self.assertIn("already sent", str(cm.exception))
        self.assertEqual(lifecycle.current("Q-1:linkedin", self.lpath)["date"], "2026-09-12")

    def test_blog_live_is_one_act_with_the_site_url_and_the_webhook(self):
        self.decide("Q-1", "approved")
        self.pull()
        items = {i["id"]: i for i in repo.load_items()}
        calls = []
        got = desk_acts.blog_live("Q-1", "Some Person", items, self.state, webhook=lambda: calls.append(1) or "sent 200")
        self.assertEqual((got["outcome"], got["url"], got["webhook"]), ("applied", repo.post_url("Q-1"), "sent 200"))
        act = [a for a in acts.list_acts(path=self.apath) if a["kind"] == "blog-live"][0]
        self.assertEqual((act["target"], act["by"], act["payload"]["url"]), ("Q-1", "alpha", repo.post_url("Q-1")))
        self.assertEqual(desk_acts.live_url(items["Q-1"], self.state), repo.post_url("Q-1"))
        again = desk_acts.blog_live("Q-1", "alpha", items, self.state, webhook=lambda: calls.append(1) or "sent 200")
        self.assertEqual((again["outcome"], again["webhook"]), ("skipped: moved", None))
        self.assertEqual([1], calls, "the webhook fires once, on the applied act")

    def test_blog_live_refusals_and_a_failing_webhook(self):
        items = {i["id"]: i for i in repo.load_items()}
        got = desk_acts.blog_live("Q-1", "alpha", items, self.state, webhook=lambda: "sent")
        self.assertEqual(got["outcome"], "refused: the item is not approved; approve it before its article goes live")
        self.assertIsNone(desk_acts.live_url(items["Q-1"], self.state))
        self.assertEqual(desk_acts.blog_live("Q-9", "alpha", items, self.state)["outcome"],
                         "refused: no note carries this id")
        self.note("Q-2", "Second post", "2026-09-10", "pass", "")
        items = {i["id"]: dict(i, alpha_status="approved") for i in repo.load_items()}
        self.assertEqual(desk_acts.blog_live("Q-2", "alpha", items, self.state)["outcome"],
                         "refused: the item has no article")

        def broken():
            raise OSError("the site is down")
        got = desk_acts.blog_live("Q-1", "alpha", items, self.state, webhook=broken)
        self.assertEqual(("applied", "failed: the site is down"), (got["outcome"], got["webhook"]))
        self.assertIsNotNone(desk_acts.live_act("Q-1", self.state), "a failed webhook never undoes the act")


if __name__ == "__main__":
    unittest.main()
