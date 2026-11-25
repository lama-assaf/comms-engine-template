"""
The supersession and decay check (plan v2, item A6).

1. **Downgrading a fixture claim raises exactly the notes that cite it**, and
   no other, with the change named.
2. **A superseded or uncorroborated cite flags the note now**, whatever the
   snapshot says: a stale snapshot delays a flag, never hides one.
3. **The first run bootstraps** the snapshot and raises nothing on time
   grounds; a change seen before the gate read the note does not flag it.
4. **Decay** flags a published piece past the age threshold whose index is
   below half its baseline, and only when a scoring record exists.
5. **Writes** `state/claims-review.json` with the action a person takes; a
   dry run writes nothing.

Everything runs on a temp state directory and in-memory items and registers;
`repo` and the real register are never touched.
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

import claims_check  # noqa: E402
import fixture_memory  # noqa: E402
import memory  # noqa: E402

T0 = dt.datetime(2026, 10, 1, 7, 0, tzinfo=dt.timezone.utc)
T1 = dt.datetime(2026, 10, 10, 22, 0, tzinfo=dt.timezone.utc)
T2 = dt.datetime(2026, 10, 20, 22, 0, tzinfo=dt.timezone.utc)


def reg(**over):
    base = {
        "C-f-1": {"id": "C-f-1", "grade": "evidenced", "corroboration": "primary", "superseded_by": ""},
        "C-f-2": {"id": "C-f-2", "grade": "evidenced", "corroboration": "primary", "superseded_by": ""},
        "C-f-3": {"id": "C-f-3", "grade": "asserted", "corroboration": "primary", "superseded_by": ""},
    }
    for cid, fields in over.items():
        base[cid] = {**base[cid], **fields}
    return base


def item(iid, cites, read_at=T0, published=None):
    return {"id": iid, "title": f"Note {iid}", "stream": "Acme", "cites": cites,
            "gate": {"verdict": "pass", "reviewed_at": read_at.isoformat(timespec="seconds")},
            **({"published_at": published.isoformat(timespec="seconds")} if published else {})}


class Check(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="claims-check-")
        self.items = [item("N-1", ["C-f-1"]), item("N-2", ["C-f-2"]), item("N-3", ["C-f-1", "C-f-3"])]

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def run_at(self, register, now, items=None, dry_run=False):
        return claims_check.run(state=self.state, items=items or self.items, register=register, now=now, dry_run=dry_run)

    def test_first_run_bootstraps_and_raises_nothing(self):
        out = self.run_at(reg(), T1)
        self.assertTrue(out["bootstrapped"])
        self.assertEqual(out["items"], [])
        self.assertTrue(os.path.exists(os.path.join(self.state, "claims-snapshot.json")))
        self.assertTrue(os.path.exists(os.path.join(self.state, "claims-review.json")))

    def test_downgrade_raises_exactly_the_citing_notes(self):
        self.run_at(reg(), T1)
        out = self.run_at(reg(**{"C-f-1": {"grade": "asserted"}}), T2)
        self.assertEqual([i["id"] for i in out["items"]], ["N-1", "N-3"])
        r = out["items"][0]["reasons"][0]
        self.assertEqual(r["claim"], "C-f-1")
        self.assertIn("grade changed after the gate read it", r["kind"])
        self.assertIn("evidenced -> asserted", r["detail"])
        self.assertEqual(out["items"][0]["action"], claims_check.ACTION)
        self.assertEqual(len(out["changes_seen_this_run"]), 1)

    def test_change_before_the_gate_read_does_not_flag(self):
        self.run_at(reg(), T0 - dt.timedelta(days=5))
        # the grade fell before T0; every note was gated at T0, after it
        out = self.run_at(reg(**{"C-f-3": {"grade": "intended"}}), T0 - dt.timedelta(days=1))
        self.assertEqual(out["items"], [])
        # ...but a note gated before that change is flagged on a later run
        early = [item("N-9", ["C-f-3"], read_at=T0 - dt.timedelta(days=10))]
        out = self.run_at(reg(**{"C-f-3": {"grade": "intended"}}), T1, items=early)
        self.assertEqual([i["id"] for i in out["items"]], ["N-9"])

    def test_superseded_cite_flags_now_whatever_the_snapshot_says(self):
        register = reg(**{"C-f-2": {"superseded_by": "C-f-9"}})
        out = self.run_at(register, T1)  # first run: no log, yet N-2 is flagged
        self.assertEqual([i["id"] for i in out["items"]], ["N-2"])
        self.assertEqual(out["items"][0]["reasons"][0]["kind"], "uncitable now")
        self.assertIn("superseded by C-f-9", out["items"][0]["reasons"][0]["detail"])

    def test_corroboration_falling_to_watching_flags(self):
        self.run_at(reg(), T1)
        out = self.run_at(reg(**{"C-f-1": {"corroboration": "watching"}}), T2)
        kinds = {r["kind"] for i in out["items"] for r in i["reasons"]}
        self.assertIn("uncitable now", kinds)
        self.assertIn("corroboration changed after the gate read it", kinds)
        self.assertEqual([i["id"] for i in out["items"]], ["N-1", "N-3"])

    def test_decay_needs_a_record_and_age(self):
        old = item("P-1", ["C-f-1"], published=T0)
        fresh = item("P-2", ["C-f-1"], published=T2 - dt.timedelta(days=2))
        with open(os.path.join(self.state, "engagement.json"), "w", encoding="utf-8") as f:
            json.dump({"stream": "Acme", "records": [
                {"id": "P-1", "stream": "Acme", "score": 2.0, "baseline": 10.0, "partial": True},
                {"id": "P-2", "stream": "Acme", "score": 1.0, "baseline": 10.0},
            ]}, f)
        out = self.run_at(reg(), T2, items=[old, fresh])
        self.assertEqual([i["id"] for i in out["items"]], ["P-1"])
        self.assertEqual(out["items"][0]["standing"], "published")
        self.assertEqual(out["items"][0]["reasons"][0]["kind"], "engagement decayed")
        self.assertIn("(partial)", out["items"][0]["reasons"][0]["detail"])
        # no record: nothing to judge
        os.remove(os.path.join(self.state, "engagement.json"))
        self.assertEqual(self.run_at(reg(), T2, items=[old])["items"], [])

    def test_dry_run_writes_nothing(self):
        out = self.run_at(reg(), T1, dry_run=True)
        self.assertTrue(out["bootstrapped"])
        self.assertEqual(os.listdir(self.state), [])


class FixtureState(fixture_memory.FixtureMemoryCase):
    """The fixture register against the fixture drafts: nothing is raised on
    current-state grounds, because every queued draft cites current rows (A5);
    the snapshot is only bootstrapped. Nothing here reads the checkout's own
    register, notes or state."""

    def test_register_and_drafts_check_cleanly_in_dry_run(self):
        state = tempfile.mkdtemp(prefix="claims-check-state-")
        self.addCleanup(shutil.rmtree, state, True)
        with open(fixture_memory.QUEUE_JSON, encoding="utf-8") as f:
            drafts = json.load(f)
        out = claims_check.run(state=state, items=drafts, dry_run=True)
        # `items` lists only what has a reason to be raised: nothing does
        self.assertEqual(out["items"], [])
        self.assertTrue(out["bootstrapped"])
        self.assertEqual(os.listdir(state), [], "a dry run writes nothing")
        # and a cite that moved is raised, so the clean result is not vacuous
        moved = {**memory.load_claims(), "C-acme-4": {**memory.load_claims()["C-acme-4"], "superseded_by": "C-acme-99"}}
        raised = claims_check.run(state=state, items=drafts, register=moved, dry_run=True)
        self.assertEqual([i["id"] for i in raised["items"]], ["Q-2026-10-01-exampletheme-1"])
        self.assertIn("uncitable now", [r["kind"] for r in raised["items"][0]["reasons"]])


if __name__ == "__main__":
    unittest.main()
