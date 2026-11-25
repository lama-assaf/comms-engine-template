#!/usr/bin/env python3
"""
The desk's two standing rules, kept by the dashboard as the desk keeps them (`standing_rules.py`).

What is asserted:

1. The check (owner decision 2026-11-11): a hold, a rejection and a rewrite are refused without a
   reason; an approval, of a post or a reaction, is not; approving a post still needs a current
   argument line and an unblocked gate.
2. The desk's TypeScript copy (`desk/lib/rules.ts`) and `standing_rules.refusal()` give the same
   answer over the same vectors, run in both rather than asserted by hand.
3. The dashboard's approve is refused without a confirmed, current argument line, with no act and no
   lifecycle move; allowed with it, with or without a reason.
4. Confirming the argument line writes the desk's `argument_lines` row and its act; rewriting the
   hook reopens it.
5. A reason typed with an approval is a desk `reviews` row; with none there is no row and no review act.
   The reason is a desk `reviews` row: an item-scope one never reaches `reviews.md`; a standing one
   reaches it through `desk_sync.pull_reviews` alone, once, and the dashboard never writes the file.
   A later pull records no second act for the rows the dashboard already made.

Fakes only: a temp vault, state directory and desk database. Nothing is sent.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import acts  # noqa: E402
import control  # noqa: E402
import desk_acts  # noqa: E402
import desk_sync  # noqa: E402
import repo  # noqa: E402
import standing_rules as rules  # noqa: E402
from test_desk_acts import NOTE, ok_guard  # noqa: E402

DESK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "Tooling", "desk")
STATUSES = ("approved", "held", "rejected", "rewrite")


class TheCheck(unittest.TestCase):
    def test_no_reason_is_refused_for_a_hold_a_rejection_and_a_rewrite_only(self):
        for status in STATUSES:
            for kind in ("post", "reaction"):
                for blank in (None, "", "  \n"):
                    want = None if status == "approved" else rules.REASON
                    self.assertEqual(rules.refusal(status, blank, kind, True, False), want, (status, kind, blank))

    def test_an_approval_without_a_reason_still_needs_the_argument_line_and_the_gate(self):
        self.assertEqual(rules.refusal("approved", "", "post", False, False), rules.ARGUMENT)
        self.assertEqual(rules.refusal("approved", None, "post", True, True), rules.BLOCKED)
        self.assertIsNone(rules.refusal("approved", "", "post", True, False))
        self.assertIsNone(rules.refusal("approved", "", "reaction", False, True))

    def test_approving_a_post_needs_a_current_argument_line_and_an_unblocked_gate(self):
        self.assertEqual(rules.refusal("approved", "why", "post", False, False), rules.ARGUMENT)
        self.assertEqual(rules.refusal("approved", "why", "post", True, True), rules.BLOCKED)
        self.assertEqual(rules.refusal("approved", "why", "post", False, True), rules.ARGUMENT, "the argument line comes first")
        self.assertIsNone(rules.refusal("approved", "why", "post", True, False))

    def test_a_hold_a_rejection_and_a_reaction_need_the_reason_only(self):
        for status in ("held", "rejected", "rewrite"):
            self.assertIsNone(rules.refusal(status, "why", "post", False, True))
        self.assertIsNone(rules.refusal("approved", "why", "reaction", False, True))

    def test_scope_is_item_or_standing(self):
        self.assertEqual([rules.norm_scope(v) for v in (None, "", "item", "Standing")], ["item", "item", "item", "standing"])
        with self.assertRaises(ValueError):
            rules.norm_scope("forever")


class TheDeskAgrees(unittest.TestCase):
    """`desk/lib/rules.ts` run by node against `standing_rules.refusal()` over every combination."""

    def test_node_and_python_agree(self):
        if not os.path.isdir(os.path.join(DESK, "node_modules")) and not os.path.isfile(os.path.join(DESK, "lib", "rules.ts")):
            self.skipTest("desk/lib/rules.ts absent")
        vectors = [{"status": s, "kind": k, "rationale": r, "argCurrent": a, "blocked": b}
                   for s in STATUSES for k in ("post", "reaction") for r in ("", "  ", "because") for a in (True, False)
                   for b in (True, False)]
        script = ("const {refusal} = await import('./lib/rules.ts');"
                  "const v = JSON.parse(process.argv[1]);"
                  "console.log(JSON.stringify(v.map(refusal)));")
        proc = subprocess.run(["node", "--experimental-strip-types", "--input-type=module", "--eval", script, "--",
                               json.dumps(vectors)], cwd=DESK, capture_output=True, text=True)
        if proc.returncode != 0:
            self.skipTest(f"node could not run the TypeScript module: {proc.stderr.strip()[:200]}")
        from_node = json.loads(proc.stdout.strip().splitlines()[-1])
        from_python = [rules.refusal(v["status"], v["rationale"], v["kind"], v["argCurrent"], v["blocked"]) for v in vectors]
        self.assertEqual(from_python, from_node)
        self.assertEqual(len(from_node), len(vectors))


class TheDashboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="standing-rules-")
        self.cal = os.path.join(self.tmp, "Content", "Calendar")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.cal)
        os.makedirs(self.state)
        self.db = os.path.join(self.state, "desk.db")
        self.reviews_md = os.path.join(self.tmp, "reviews.md")
        self._saved = (repo.CAL, repo.STATE, desk_sync.STATE, desk_sync.REVIEWS_MD, desk_sync.DB_PATH, os.environ.get("DESK_DB"))
        repo.CAL, repo.STATE = self.cal, self.state
        desk_sync.STATE, desk_sync.REVIEWS_MD, desk_sync.DB_PATH = self.state, self.reviews_md, self.db
        os.environ.pop("DESK_DB", None)
        self.note("Q-1", "First post", "pass")
        self.apath = os.path.join(self.state, "acts.jsonl")
        self.lpath = os.path.join(self.state, "lifecycle.jsonl")

    def tearDown(self):
        repo.CAL, repo.STATE, desk_sync.STATE, desk_sync.REVIEWS_MD, desk_sync.DB_PATH, env = self._saved
        if env is not None:
            os.environ["DESK_DB"] = env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def note(self, eid, title, verdict):
        with open(os.path.join(self.cal, f"{title}.md"), "w", encoding="utf-8") as f:
            f.write(NOTE.format(eid=eid, title=title, date="2026-09-09", verdict=verdict, body="Body."))

    def items(self):
        return {i["id"]: i for i in repo.load_items()}

    def approve(self, reason="the claim is on the register", scope="item", eid="Q-1"):
        return desk_acts.approve_post(eid, "alpha", self.items(), self.state, guard=ok_guard, reason=reason, scope=scope)

    def rows(self, table):
        con = desk_sync.connect(self.db)
        try:
            return [dict(r) for r in con.execute(f"SELECT * FROM {table}")]
        finally:
            con.close()

    def untouched(self):
        self.assertFalse(os.path.exists(self.apath), "a refusal records no act")
        self.assertFalse(os.path.exists(self.lpath), "and moves nothing")

    def test_refused_without_a_confirmed_argument_line(self):
        got = self.approve()
        self.assertEqual(got["outcome"], "refused: " + rules.ARGUMENT)
        self.untouched()

    def test_allowed_without_a_reason_and_it_records_no_review_and_no_review_act(self):
        rules.confirm_argument(self.items()["Q-1"], "alpha", self.state)
        got = self.approve(reason="   ", scope="standing")
        self.assertEqual((got["outcome"], got["state"]), ("applied", "scheduled"))
        self.assertEqual(self.rows("reviews"), [], "nothing typed, nothing kept")
        self.assertEqual(sorted(a["kind"] for a in acts.list_acts(path=self.apath)), ["argument_line", "decision"])
        decision = [a for a in acts.list_acts(path=self.apath) if a["kind"] == "decision"][0]
        self.assertEqual(decision["payload"]["note"], "")
        self.assertFalse(os.path.exists(self.reviews_md))

    def test_still_refused_without_the_argument_line_when_there_is_no_reason(self):
        self.assertEqual(self.approve(reason="")["outcome"], "refused: " + rules.ARGUMENT)
        self.untouched()

    def test_a_hold_a_rejection_and_a_rewrite_still_need_a_reason_through_the_desk_database(self):
        # the dashboard has no hold route; the shared check is what today.py and the desk call
        for status in ("held", "rejected", "rewrite"):
            self.assertEqual(rules.refusal(status, " ", "post", True, False), rules.REASON)

    def test_allowed_with_both_and_the_reason_is_the_acts_note(self):
        rules.confirm_argument(self.items()["Q-1"], "alpha", self.state)
        got = self.approve()
        self.assertEqual((got["outcome"], got["state"], got["date"]), ("applied", "scheduled", "2026-09-09"))
        decision = [a for a in acts.list_acts(path=self.apath) if a["kind"] == "decision"][0]
        self.assertEqual((decision["payload"]["note"], decision["payload"]["source"]), ("the claim is on the register", "dashboard"))

    def test_confirming_writes_the_desks_row_and_its_act_and_a_rewritten_hook_reopens_it(self):
        got = rules.confirm_argument(self.items()["Q-1"], "Some Person", self.state)
        self.assertEqual((got["hook"], got["claim"], got["by"]), ("First post", "The claim.", "alpha"))
        (row,) = self.rows("argument_lines")
        self.assertEqual((row["item_id"], row["act"], row["hook"], row["claim"], row["by"]),
                         ("Q-1", "confirmed", "First post", "The claim.", "alpha"))
        self.assertTrue(rules.post_facts(self.items()["Q-1"], self.db)["argument_current"])
        # a saved desk edit that rewrites the hook: the confirmation no longer names the hook on the card
        con = desk_sync.connect(self.db)
        con.execute("INSERT INTO edits (item_id, title, post, teaser_linkedin, teaser_x, base_hash, by, at) "
                    "VALUES ('Q-1', 'A new hook', 'p', 'l', 'x', 'h', 'alpha', '2026-09-08T10:00:00.000Z')")
        con.commit()
        con.close()
        facts = rules.post_facts(self.items()["Q-1"], self.db)
        self.assertEqual((facts["hook"], facts["argument_current"]), ("A new hook", False))
        self.assertEqual(self.approve()["outcome"], "refused: " + rules.ARGUMENT)

    def test_a_blocked_post_is_refused_by_the_rule_before_any_act(self):
        self.note("Q-2", "Second post", "block")
        rules.confirm_argument(self.items()["Q-2"], "alpha", self.state)
        self.assertEqual(self.approve(eid="Q-2")["outcome"], "refused: " + rules.BLOCKED)
        self.assertEqual([a["kind"] for a in acts.list_acts(path=self.apath)], ["argument_line"])

    def test_an_item_reason_stays_on_the_desk_and_a_standing_one_reaches_reviews_through_the_pull_alone(self):
        rules.confirm_argument(self.items()["Q-1"], "alpha", self.state)
        self.assertEqual(self.approve(reason="Only claims on the register.", scope="standing")["outcome"], "applied")
        (review,) = self.rows("reviews")
        self.assertEqual((review["item_id"], review["kind"], review["verdict"], review["rationale"], review["scope"], review["by"]),
                         ("Q-1", "post", "approved", "Only claims on the register.", "standing", "alpha"))
        self.assertEqual(review["theme"], "#Theme")
        self.assertFalse(os.path.exists(self.reviews_md), "the dashboard never writes reviews.md")
        con = desk_sync.connect(self.db)
        try:
            pulled = desk_sync.pull_reviews(con, streams={"Q-1": "Testco"})
        finally:
            con.close()
        self.assertEqual(len(pulled), 1)
        text = open(self.reviews_md, encoding="utf-8").read()
        self.assertIn("Only claims on the register.", text)
        self.assertIn("item: `Q-1`", text)
        self.assertTrue(self.rows("reviews")[0]["synced_at"])
        con = desk_sync.connect(self.db)
        try:
            self.assertEqual(desk_sync.pull_reviews(con, streams={"Q-1": "Testco"}), [], "a second pull writes nothing")
        finally:
            con.close()
        self.assertEqual(open(self.reviews_md, encoding="utf-8").read().count("Only claims on the register."), 1)

    def test_an_item_scope_reason_never_reaches_reviews_md(self):
        rules.confirm_argument(self.items()["Q-1"], "alpha", self.state)
        self.approve(reason="Just this one.", scope="item")
        con = desk_sync.connect(self.db)
        try:
            self.assertEqual(desk_sync.pull_reviews(con, streams={"Q-1": "Testco"}), [])
        finally:
            con.close()
        self.assertFalse(os.path.exists(self.reviews_md))

    def test_the_pull_makes_no_second_act_for_what_the_dashboard_recorded(self):
        rules.confirm_argument(self.items()["Q-1"], "alpha", self.state)
        self.approve(reason="why", scope="standing")
        before = sorted(a["id"] for a in acts.list_acts(path=self.apath))
        self.assertEqual(sorted(a["kind"] for a in acts.list_acts(path=self.apath)), ["argument_line", "decision", "review"])
        con = desk_sync.connect(self.db)
        try:
            made = desk_sync.pull(con, verbose=False, guard=ok_guard)["acts"]
        finally:
            con.close()
        self.assertEqual(made, [], "the argument line and the review were already acts with the pull's own ids")
        self.assertEqual(sorted(a["id"] for a in acts.list_acts(path=self.apath)), before)

    def test_control_refuses_a_bad_scope_and_names_the_hook_and_claim(self):
        from unittest import mock
        with mock.patch("gate_lint.items_by_id", lambda: self.items()), mock.patch.object(control, "STATE", self.state):
            got = control.confirm_argument("Q-1", "alpha")
            self.assertEqual((got["hook"], got["claim"]), ("First post", "The claim."))
            with self.assertRaises(control.Refused):
                control.approve_post("Q-1", "alpha", scope="forever", reason="x")
            with self.assertRaises(control.Refused):
                control.confirm_argument("nope", "alpha")


if __name__ == "__main__":
    unittest.main()
