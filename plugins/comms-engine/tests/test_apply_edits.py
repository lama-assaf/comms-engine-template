#!/usr/bin/env python3
"""
The desk-to-vault edge: `scripts/apply_edits.py`.

The rule under test is the standing one: a desk edit and a vault-side change
to the same item are reconciled by **skipping, never clobbering**, so what is
asserted here is mostly what does *not* happen:

1. **The hash is one number in two languages.** `repo.base_hash` answers a
   known-answer vector for the canonical form the desk computes in JavaScript
   (the same four fields, the same U+001F separator, the same encoding), so an
   edit saved in the browser and an edit read by the distributor are talking
   about the same note.
2. **A clean apply.** The note still hashes to `base_hash`, so Alpha's four
   fields land on it and `desk_edit` records that they did. A second run is a
   no-op: the marker, not the text, is what says "already applied", because a
   gatekeeper fix or an Obsidian tweak may legitimately move the text after.
3. **The same item edited on both sides.** The run reports a skipped conflict,
   the note is byte-identical to the vault version, `state/edits.json` still
   holds Alpha's, and `runs.json` carries the flag. Neither version is lost.
4. **The overrides.** `--prefer desk` takes Alpha's text, `--prefer vault` keeps
   the note's and still records the edit as dropped (the desk record cannot be
   deleted from here, so the resolution has to live on the note). Both need an
   id; a bare `--prefer` is refused.
5. **The publish refusals.** `publish.py` refuses an approved item while its
   desk edit is in conflict, and refuses one whose edit landed until the
   gatekeeper stamps a `gate.reviewed_at` later than the resolution. Then it
   publishes.

Everything runs against a temp vault built from the gate fixture item
(`fixtures.json`), with `repo.CAL` and `repo.STATE` redirected and the
registry read from the fixture memory, never against `Content/Calendar/`.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import contextlib
import copy
import datetime as dt
import hashlib
import io
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

import apply_edits  # noqa: E402
import fixture_memory  # noqa: E402
import publish  # noqa: E402
import repo  # noqa: E402

with open(os.path.join(HERE, "fixtures.json"), encoding="utf-8") as f:
    BASE = json.load(f)["base"]

# A known-answer vector for the canonical form the desk and the engine share:
# sha256 over the four edited fields, U+001F-separated, UTF-8. This vector, not
# the prose of a note, is what pins the agreement: pinning a live item's text
# would turn the first desk edit the engine applies into a failing test.
VECTOR = {"post": "a", "teaser_linkedin": "b", "teaser_x": "c", "title": "d"}
VECTOR_SHA = hashlib.sha256("a\u001fb\u001fc\u001fd".encode("utf-8")).hexdigest()


def fixture_item():
    """The gate fixture item as a vault item: a slot on a weekday, a passing gate."""
    item = copy.deepcopy(BASE)
    item["slot"] = {"date": "2026-10-06", "platform": "Blog", "campaign": "q4"}
    item["gate"] = {"verdict": "pass", "checks": [], "note_for_alpha": ""}
    item["alpha_status"] = "proposed"
    return item


class TheHash(unittest.TestCase):
    """One canonical form, computed in the browser and in Python."""

    def test_the_canonical_form(self):
        """The order, the separator and the encoding, in one number."""
        self.assertEqual(VECTOR_SHA, repo.base_hash(VECTOR))
        self.assertEqual(("post", "teaser_linkedin", "teaser_x", "title"), repo.HASH_FIELDS)

    def test_a_fixture_item_hashes(self):
        """An item yields one 64-hex digest, the value the desk stores as
        base_hash and the distributor checks, the same for a copy of it."""
        h = repo.base_hash(BASE)
        self.assertRegex(h, r"^[0-9a-f]{64}$")
        self.assertEqual(h, repo.base_hash(dict(BASE)))

    def test_the_separator_is_load_bearing(self):
        """Fields are joined on U+001F, so moving a boundary changes the hash."""
        a = {"post": "ab", "teaser_linkedin": "", "teaser_x": "", "title": ""}
        b = {"post": "a", "teaser_linkedin": "b", "teaser_x": "", "title": ""}
        self.assertNotEqual(repo.base_hash(a), repo.base_hash(b))

    def test_a_missing_field_hashes_as_empty(self):
        """`String(item[f] ?? "")` in the page; the same here."""
        self.assertEqual(repo.base_hash({"post": "x"}),
                         repo.base_hash({"post": "x", "title": "", "teaser_x": "", "teaser_linkedin": ""}))


class Sandbox(fixture_memory.FixtureMemoryCase):
    """One fixture item's two notes in a temp vault, with the state directory beside it."""

    ITEM = BASE["id"]

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="apply-edits-")
        self.real = (repo.CAL, repo.STATE, publish.STATE, publish.SNAPSHOT)
        # No calendar snapshot: these cases test the edit refusals, not the
        # duplicate check, so nothing here counts as already published.
        publish.SNAPSHOT = os.path.join(self.tmp, "no-snapshot.json")
        cal = os.path.join(self.tmp, "Calendar")
        state = os.path.join(self.tmp, "state")
        os.makedirs(cal)
        os.makedirs(state)
        repo.CAL, repo.STATE, publish.STATE = cal, state, state
        repo.write_item(fixture_item(), "Idea")
        repo.write_index()
        self.item = self.now()

    def tearDown(self):
        repo.CAL, repo.STATE, publish.STATE, publish.SNAPSHOT = self.real
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    # ── the fixtures ────────────────────────────────────────────────
    def now(self, item_id=None):
        item_id = item_id or self.ITEM
        return next(i for i in repo.load_items() if i["id"] == item_id)

    def note_path(self):
        return repo.scan_notes()[self.ITEM]["Blog"][0]

    def note_bytes(self):
        with open(self.note_path(), "rb") as f:
            return f.read()

    def desk_edit_on(self, item=None, **over):
        """The record the page's "Save edit" writes, over the note as built."""
        item = item or self.item
        rec = {
            "by": "Alpha (dashboard)",
            "at": "2026-10-08T09:00:00.000Z",
            "title": item["title"],
            "post": item["post"],
            "teaser_linkedin": item["teaser_linkedin"],
            "teaser_x": item["teaser_x"],
            "base_hash": repo.base_hash(item),
        }
        rec.update(over)
        return rec

    def store_edit(self, rec, item_id=None):
        """`state/edits.json` as /social-cycle step 1 pulls it."""
        path = os.path.join(repo.STATE, "edits.json")
        data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        data[item_id or self.ITEM] = rec
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        return path

    def vault_side_change(self, text="\n\nA sentence added in Obsidian after Alpha was shown the card."):
        """Someone edits the note itself: Obsidian, a gate fix."""
        item = self.now()
        repo.set_fields(self.ITEM, {"post": item["post"] + text})

    def apply_run(self, **kw):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            result = apply_edits.run(**kw)
        result["out"] = buf.getvalue()
        return result

    def runs_log(self):
        p = os.path.join(repo.STATE, "runs.json")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return json.load(f)


class CleanApply(Sandbox):
    """Nothing moved: the edit lands, and lands once."""

    EDITED_TITLE = "A wallet holds a credential and the root is still a governance question"

    def test_it_applies_and_records_the_marker(self):
        rec = self.desk_edit_on(title=self.EDITED_TITLE, post=self.item["post"] + "\n\nAlpha's added line.")
        self.store_edit(rec)
        result = self.apply_run()
        self.assertEqual([self.ITEM], result["applied"])
        self.assertEqual([], result["conflicts"])

        after = self.now()
        self.assertEqual(self.EDITED_TITLE, after["title"])
        self.assertTrue(after["post"].endswith("Alpha's added line."))
        self.assertEqual({"edited_at": rec["at"], "by": rec["by"], "base_hash": rec["base_hash"],
                          "resolution": "applied"},
                         {k: v for k, v in after["desk_edit"].items() if k != "at"})
        # The note moved to the new title; there is one post note, not two.
        blog = [n for n in os.listdir(repo.CAL) if not n.endswith(" - teasers.md")]
        self.assertEqual([repo.safe_title(self.EDITED_TITLE) + ".md"], blog)
        # And the index followed the note.
        self.assertEqual(self.EDITED_TITLE,
                         next(i for i in repo.load_queue() if i["id"] == self.ITEM)["title"])

    def test_a_second_run_is_a_no_op(self):
        self.store_edit(self.desk_edit_on(title=self.EDITED_TITLE))
        self.apply_run()
        before = self.note_bytes()
        result = self.apply_run()
        self.assertEqual([self.ITEM], result["unchanged"])
        self.assertEqual([], result["applied"])
        self.assertEqual(before, self.note_bytes())

    def test_a_later_vault_change_is_not_a_new_conflict(self):
        """The marker decides `resolved`, not text equality: a gatekeeper fix
        after the edit landed must not resurface as a conflict for ever."""
        self.store_edit(self.desk_edit_on(title=self.EDITED_TITLE))
        self.apply_run()
        self.vault_side_change("\n\nThe gatekeeper's mechanical fix, applied after the edit.")
        result = self.apply_run()
        self.assertEqual([], result["conflicts"])
        self.assertEqual([self.ITEM], result["unchanged"])

    def test_an_item_with_no_note_is_left_for_the_sweep(self):
        self.store_edit(self.desk_edit_on(), item_id="Q-2026-10-30-notyet-1")
        result = self.apply_run()
        self.assertIn("Q-2026-10-30-notyet-1", result["missing"])
        self.assertEqual([], result["conflicts"])


class Conflict(Sandbox):
    """Edited on both sides: nothing is written, nothing is lost."""

    ALPHA_TITLE = "A wallet holds a credential and the root is a governance question by design"

    def setUp(self):
        super().setUp()
        self.rec = self.desk_edit_on(title=self.ALPHA_TITLE,
                                     post=self.item["post"] + "\n\nAlpha's version of the ending.")
        self.edits_path = self.store_edit(self.rec)
        self.vault_side_change()                    # the other side moves
        self.vault = self.note_bytes()
        self.desk_edit_before = self.now().get("desk_edit", {})

    def test_the_run_reports_a_skipped_conflict(self):
        result = self.apply_run()
        self.assertEqual([], result["applied"])
        self.assertEqual([self.ITEM], [c["id"] for c in result["conflicts"]])
        self.assertIn("CONFLICT", result["out"])
        self.assertIn("--prefer desk|vault", result["out"])
        c = result["conflicts"][0]
        self.assertEqual(self.rec["base_hash"], c["base_hash"])
        self.assertEqual(repo.base_hash(self.now()), c["note_hash"])
        self.assertNotEqual(c["base_hash"], c["note_hash"])

    def test_neither_version_is_lost(self):
        self.apply_run()
        # The vault's version: the note is untouched, byte for byte.
        self.assertEqual(self.vault, self.note_bytes())
        self.assertNotEqual(self.ALPHA_TITLE, self.now()["title"])
        self.assertEqual(self.desk_edit_before, self.now()["desk_edit"])
        # Alpha's version: still in state/edits.json, unchanged.
        with open(self.edits_path, encoding="utf-8") as f:
            kept = json.load(f)
        self.assertEqual(self.rec, kept[self.ITEM])

    def test_the_item_is_flagged_in_the_run_log(self):
        self.apply_run()
        entry = self.runs_log()[-1]
        self.assertEqual("edits", entry["step"])
        self.assertEqual([self.ITEM], [c["id"] for c in entry["conflicts"]])
        self.assertEqual([], entry["applied"])
        self.assertIn("conflict skipped", entry["detail"])
        self.assertIn(self.ITEM, entry["detail"])

    def test_the_flag_stands_until_a_person_resolves_it(self):
        for _ in range(3):
            self.assertEqual([self.ITEM], [c["id"] for c in self.apply_run()["conflicts"]])
        self.assertEqual(self.vault, self.note_bytes())

    def test_the_cli_exits_nonzero_while_a_conflict_stands(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as e:
                apply_edits.main([])
        self.assertEqual(1, e.exception.code)

    def test_prefer_desk_takes_alphas_text(self):
        result = self.apply_run(only=self.ITEM, prefer="desk")
        self.assertEqual([{"id": self.ITEM, "prefer": "desk", "was": "conflict"}], result["resolved"])
        after = self.now()
        self.assertEqual(self.ALPHA_TITLE, after["title"])
        self.assertTrue(after["post"].endswith("Alpha's version of the ending."))
        self.assertEqual("desk", after["desk_edit"]["resolution"])
        self.assertEqual(self.rec["at"], after["desk_edit"]["edited_at"])
        self.assertEqual([], self.apply_run()["conflicts"])       # resolved for good

    def test_prefer_vault_keeps_the_note_and_still_records_the_edit(self):
        result = self.apply_run(only=self.ITEM, prefer="vault")
        self.assertEqual([{"id": self.ITEM, "prefer": "vault", "was": "conflict"}], result["resolved"])
        after = self.now()
        self.assertNotEqual(self.ALPHA_TITLE, after["title"])
        self.assertTrue(after["post"].endswith("A sentence added in Obsidian after Alpha was shown the card."))
        self.assertEqual("vault", after["desk_edit"]["resolution"])
        self.assertEqual(self.rec["at"], after["desk_edit"]["edited_at"])
        # The desk record is untouched (this script has no reach into it), so
        # the note's marker is the only durable trace that it was dropped.
        with open(self.edits_path, encoding="utf-8") as f:
            self.assertEqual(self.rec, json.load(f)[self.ITEM])
        self.assertEqual([], self.apply_run()["conflicts"])

    def test_an_unverifiable_edit_is_a_conflict(self):
        """No base_hash, nothing to check against: refuse rather than assume."""
        rec = dict(self.rec)
        rec.pop("base_hash")
        self.store_edit(rec)
        self.assertEqual([self.ITEM], [c["id"] for c in self.apply_run()["conflicts"]])

    def test_prefer_needs_an_id(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                apply_edits.main(["--prefer", "desk"])

    def test_dry_run_writes_nothing(self):
        self.apply_run(only=self.ITEM, prefer="desk", dry_run=True)
        self.assertEqual(self.vault, self.note_bytes())


class PublishRefusals(Sandbox):
    """An edit is a new draft: publish.py says so, twice."""

    def approve(self):
        repo.set_fields(self.ITEM, {"alpha_status": "approved"})

    def publish(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            try:
                publish.main([self.ITEM, *argv])
                code = None
            except SystemExit as e:
                code = e.code
        return code, buf.getvalue()

    def stamp_gate(self, when):
        gate = dict(self.now()["gate"])
        gate["reviewed_at"] = when
        gate["reviewed_by"] = "gatekeeper"
        repo.set_fields(self.ITEM, {"gate": gate})

    def test_it_refuses_while_the_edit_is_in_conflict(self):
        self.approve()
        self.store_edit(self.desk_edit_on(title="Alpha's rewrite of the hook"))
        self.vault_side_change()
        before = self.note_bytes()
        code, _ = self.publish()
        self.assertIn("unresolved desk edit", str(code))
        self.assertEqual(before, self.note_bytes())

    def test_it_refuses_an_applied_edit_the_gate_has_not_re_read(self):
        self.approve()
        self.store_edit(self.desk_edit_on(title="Alpha's rewrite of the hook"))
        self.assertEqual([self.ITEM], self.apply_run()["applied"])
        before = self.note_bytes()
        code, _ = self.publish()
        self.assertIn("edited on the desk", str(code))
        self.assertIn("an edit is a new draft", str(code).lower())
        self.assertEqual(before, self.note_bytes())

    def test_it_publishes_once_the_gatekeeper_has_re_read_it(self):
        self.approve()
        self.store_edit(self.desk_edit_on(title="Alpha's rewrite of the hook"))
        self.apply_run()
        later = (apply_edits.parse_ts(self.now()["desk_edit"]["at"]) + dt.timedelta(minutes=5))
        self.stamp_gate(later.isoformat(timespec="seconds"))
        code, out = self.publish()
        self.assertEqual(None, code, out)
        after = self.now()
        self.assertEqual("Alpha's rewrite of the hook", after["title"])
        self.assertEqual(["vault"], after["published_to"])
        self.assertEqual("Ready", repo.scan_notes()[self.ITEM]["Blog"][1]["status"])
        self.assertEqual("publish", self.runs_log()[-1]["step"])

    def test_an_unedited_item_is_unaffected(self):
        """No desk edit, no new refusal: the path that worked still works."""
        self.approve()
        code, out = self.publish()
        self.assertEqual(None, code, out)

    def test_force_is_still_the_dry_run_bypass(self):
        self.store_edit(self.desk_edit_on(title="Alpha's rewrite"))
        self.vault_side_change()
        code, out = self.publish("--force")
        self.assertEqual(None, code, out)


if __name__ == "__main__":
    unittest.main()
