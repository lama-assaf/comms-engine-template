#!/usr/bin/env python3
"""
The fixture set for `scripts/inventory.py`.

The claim this script makes is a claim about money: one threshold governs both
the staleness flag and the paid profile call, so the inventory stays current at
roughly one actor run per handle per month. Nothing about that is visible from
reading the code, so it is asserted here with a counting stub in place of the
actor. No test makes a network call.

Five things:

1. **The window is the budget.** A first run checks exactly the rows the
   recorded dates call stale, writes today's date onto the ones it confirmed,
   and a second run inside the window makes *no* call at all, while the desk
   still renders every row of the inventory.
2. **An edited handle is due whatever its date says.** `last_verified` records
   when a status was established; a handle changed after that date has a date
   that refers to something else, and the ledger is what notices.
3. **LinkedIn is never called, forced or not,** and `--force-all` sweeps every
   recorded X handle.
4. **The write-back is surgical.** Two cells change on the rows that were
   confirmed; the row count, the column count and every other byte of
   `handles.md` stand. An inconclusive check writes nothing, and a status is
   never downgraded.
5. **The desk reads the same threshold.** `inventory_rows` flags exactly the
   rows `plan` calls due, so the page cannot say current where the refresh says
   due.

Every case runs against a temp copy of `fixtures/memory/handles.md`, the
inventory of the invented brand frozen as it stood on 2026-09-08, and never
against `.atelier/memory/handles.md`. The dates are the assertion here, and a
live file's dates move the moment the refresh does its job: read it, and the
suite that proves the window works would fail *because* it worked.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import datetime as dt
import io
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
import inventory  # noqa: E402
import memory  # noqa: E402

FIXTURE = os.path.join(fixture_memory.MEMORY_FIXTURE, "handles.md")

# The fixture's rows, named once: the brand's own X handle (recorded, never
# verified), the two verified partners (fresh on the pinned day) and the
# standards body (recorded, never verified).
OWN, OWN_X = "Acme", "@acme_hq"
PARTNER_X = "betalabs"
STANDARDS, STANDARDS_X = "Example Standards Body", "examplestandards"


class Actor:
    """A stub for the paid profile lookup (twitterapi.io user/info, decision
    2026-10-26) that counts what it was asked. It is only ever given an X
    handle: a LinkedIn slug reaching it would be a LinkedIn call."""

    def __init__(self, known=(OWN_X[1:], PARTNER_X, "deltaco", STANDARDS_X), empty=(), suspended=()):
        self.known = {k.lower() for k in known}
        self.empty = {k.lower() for k in empty}
        self.suspended = {k.lower() for k in suspended}
        self.calls = []

    def __call__(self, name):
        assert "/" not in name and "linkedin" not in name.lower(), f"a LinkedIn value was looked up: {name}"
        self.calls.append(name)
        if name.lower() in self.suspended:
            return "unavailable", "Suspended"
        if name.lower() in self.empty or name.lower() not in self.known:
            return "not found", "user not found"
        return "found", {"userName": name, "followers": 10}


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="inventory-")
        self.handles = os.path.join(self.tmp, "handles.md")
        shutil.copy(FIXTURE, self.handles)
        self.ledger = os.path.join(self.tmp, "inventory-ledger.json")
        self.today = dt.date(2026, 9, 8)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_once(self, actor, today=None, **kw):
        buf = io.StringIO()
        report = inventory.run(handles_path=self.handles, ledger_path=self.ledger,
                               call=actor, today=today or self.today, log=False,
                               out=lambda s: buf.write(s + "\n"), **kw)
        report["_out"] = buf.getvalue()
        return report

    def cells(self, party, column, heading=None):
        """One cell of one row of the temp handles.md, read back off disk."""
        text = memory._read(self.handles)
        for spec in inventory.TABLES:
            if heading and spec["heading"] != heading:
                continue
            for row in memory.table_in(text, spec["heading"], prefix=True):
                if row.get(spec["party"]) == party:
                    return row.get(column)
        return None

    # 1 --------------------------------------------------------------------

    def test_second_run_inside_the_window_makes_no_paid_call(self):
        actor = Actor()
        first = self.run_once(actor)
        self.assertGreater(first["calls"], 0, "a first run should check the stale rows")
        self.assertEqual(first["confirmed"], len(first["due"]))
        # Every due row was one the recorded date called stale.
        frozen = inventory.inventory_rows(FIXTURE, today=self.today)
        for t in first["due"]:
            self.assertTrue(inventory.is_stale(
                next(r["last_verified"] for r in frozen if r["party"] == t["party"]),
                self.today))

        before = len(actor.calls)
        second = self.run_once(Actor(), today=self.today + dt.timedelta(days=1))
        self.assertEqual(second["calls"], 0,
                         "a second run inside the window must not call the paid actor")
        self.assertEqual(len(actor.calls), before)

        # ...and the desk still shows every row.
        rows = inventory.inventory_rows(self.handles, today=self.today + dt.timedelta(days=1))
        self.assertEqual(len(rows), len(frozen))
        self.assertEqual(len(rows), second["rows"])
        for r in rows:
            self.assertTrue(r["party"], "every row keeps its party name")

    def test_the_window_reopens_when_it_expires(self):
        actor = Actor()
        self.run_once(actor)
        n = len(actor.calls)
        later = self.run_once(actor, today=self.today + dt.timedelta(days=31))
        self.assertGreater(later["calls"], 0, "past 30 days the rows are due again")
        self.assertGreater(len(actor.calls), n)

    # 2 --------------------------------------------------------------------

    def test_an_edited_handle_is_due_inside_the_window(self):
        self.run_once(Actor())
        text = memory._read(self.handles).replace(OWN_X, "@acme_official")
        with open(self.handles, "w", encoding="utf-8") as f:
            f.write(text)
        actor = Actor(known=("acme_official",))
        report = self.run_once(actor, today=self.today + dt.timedelta(days=1))
        self.assertIn("acme_official", actor.calls)
        self.assertTrue(any(t["why"] == "handle added or edited since the last run"
                            for t in report["due"]))

    def test_a_first_run_does_not_treat_an_empty_ledger_as_a_change(self):
        """No previous run means the recorded date is the only authority."""
        rows = inventory.inventory_rows(self.handles, today=self.today)
        due, fresh, _ = inventory.plan(rows, {"rows": {}}, today=self.today)
        self.assertTrue(fresh, "the rows verified yesterday are fresh, not due")
        for t in due:
            self.assertTrue(t["row"]["stale"])

    # 3 --------------------------------------------------------------------

    def test_linkedin_is_never_called_and_is_reported_for_a_person(self):
        actor = Actor()
        report = self.run_once(actor, force_all=True)
        for name in actor.calls:
            self.assertNotIn("linkedin", name.lower())
        linkedin = [m for m in report["manual"] if m["platform"].lower() == "linkedin"]
        self.assertTrue(linkedin, "LinkedIn rows go to a person, not to an actor")
        self.assertTrue(any("blank" in m["reason"] or "manual" in m["reason"]
                            for m in report["manual"]))

    def test_force_all_sweeps_every_recorded_x_handle(self):
        rows = inventory.inventory_rows(self.handles, today=self.today)
        recorded = {h["handle"].lstrip("@").lower()
                    for r in rows for h in r["handles"]
                    if h["platform"].lower() == "x" and not inventory._blank(h["handle"])}
        actor = Actor()
        report = self.run_once(actor, force_all=True)
        self.assertEqual(set(actor.calls), recorded)
        self.assertEqual(report["calls"], len(recorded),
                         "one handle, one call - a handle on two rows is not paid for twice")

    def test_the_blank_linkedin_slug_is_routed_to_alpha(self):
        report = self.run_once(Actor())
        blanks = [m for m in report["manual"]
                  if m["party"] == OWN and m["platform"] == "LinkedIn"]
        self.assertEqual(len(blanks), 1)
        self.assertIn("does not guess", blanks[0]["reason"])
        self.assertEqual(self.cells(OWN, "handle"), OWN_X)

    # 4 --------------------------------------------------------------------

    def test_the_write_back_is_surgical(self):
        before = memory._read(self.handles).split("\n")
        report = self.run_once(Actor())
        after = memory._read(self.handles).split("\n")
        self.assertEqual(len(before), len(after), "no line added or removed")
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(changed), len(report["written"]),
                         "exactly the confirmed rows are rewritten")
        for i in changed:
            self.assertEqual(before[i].count("|"), after[i].count("|"),
                             "the column count of a rewritten row stands")
        self.assertEqual(self.cells(OWN, "last_verified"), str(self.today))
        self.assertEqual(self.cells(OWN, "status"), "verified")
        self.assertEqual(self.cells(STANDARDS, "last_verified"), str(self.today))

    def test_an_inconclusive_check_writes_nothing(self):
        report = self.run_once(Actor(known=(), empty=(OWN_X[1:], STANDARDS_X)))
        self.assertGreater(report["calls"], 0)
        self.assertEqual(report["confirmed"], 0)
        self.assertEqual(report["written"], [])
        self.assertEqual(self.cells(OWN, "last_verified"), "—")
        self.assertEqual(self.cells(OWN, "status"), "collect")

    def test_a_status_is_never_downgraded(self):
        row = {"status": "verified",
               "handles": [{"platform": "X", "handle": "@x"},
                           {"platform": "LinkedIn", "handle": "company/x"}]}
        self.assertEqual(inventory.status_after(row, set()), "verified")

    def test_a_manual_linkedin_slug_holds_the_status_at_collect(self):
        row = {"status": "collect",
               "handles": [{"platform": "X", "handle": "@x"},
                           {"platform": "LinkedIn", "handle": "company/x"}]}
        self.assertEqual(inventory.status_after(row, {"X"}), "collect")
        row["handles"][1]["handle"] = "collect"
        self.assertEqual(inventory.status_after(row, {"X"}), "verified")

    def test_no_row_is_added_or_removed(self):
        before = inventory.inventory_rows(self.handles, today=self.today)
        self.run_once(Actor(), force_all=True)
        after = inventory.inventory_rows(self.handles, today=self.today)
        self.assertEqual([r["party"] for r in before], [r["party"] for r in after])
        self.assertEqual([[h["handle"] for h in r["handles"]] for r in before],
                         [[h["handle"] for h in r["handles"]] for r in after],
                         "handles are read, never written")

    # 5 --------------------------------------------------------------------

    def test_the_desk_flag_and_the_paid_call_share_one_threshold(self):
        rows = inventory.inventory_rows(self.handles, today=self.today)
        due, fresh, _ = inventory.plan(rows, inventory.load_ledger(self.ledger),
                                       today=self.today)
        self.assertTrue(all(t["row"]["stale"] for t in due))
        self.assertTrue(all(not t["row"]["stale"] for t in fresh))
        # And after a run the flag clears with the call.
        self.run_once(Actor())
        rows = inventory.inventory_rows(self.handles, today=self.today)
        self.assertFalse(next(r for r in rows if r["party"] == STANDARDS)["stale"])

    def test_a_row_never_verified_is_always_stale(self):
        self.assertTrue(inventory.is_stale("—", self.today))
        self.assertTrue(inventory.is_stale("", self.today))
        self.assertTrue(inventory.is_stale("not a date", self.today))
        self.assertFalse(inventory.is_stale("2026-09-07", self.today))
        self.assertFalse(inventory.is_stale("2026-08-09", self.today))
        self.assertTrue(inventory.is_stale("2026-08-08", self.today))

    def test_a_dry_run_calls_nothing_and_writes_nothing(self):
        before = memory._read(self.handles)
        actor = Actor()
        report = self.run_once(actor, dry_run=True, force_all=True)
        self.assertEqual(actor.calls, [])
        self.assertEqual(report["calls"], 0)
        self.assertEqual(memory._read(self.handles), before)
        self.assertFalse(os.path.exists(self.ledger), "a dry run leaves no ledger behind")


if __name__ == "__main__":
    unittest.main()
