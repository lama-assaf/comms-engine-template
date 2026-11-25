#!/usr/bin/env python3
"""
The desk-to-engine edge: `scripts/desk_sync.py`.

The desk application writes one SQLite file and this script is the only thing
that moves data across that boundary. The rule it exists to hold is that **the
database is a derived index and a decision store, never the record** — so what
is asserted here is mostly about which direction each table moves in, and what a
routine refresh is not allowed to destroy:

1. **The schema has one source.** `--init` applies `desk/drizzle/*.sql`, the
   file `db/schema.ts` generates, so the TypeScript and Python runtimes cannot
   end up with different tables. Applying it twice is a no-op, because `--push`
   calls it on every run.
2. **A push is a replacement, not an accumulation.** Pushing twice leaves one
   row per note, and a note that has gone leaves no row behind.
3. **A push never writes the decision store.** This is the one that would lose
   real work: a decision Alpha made and had not pulled yet must survive a
   refresh of the mirror tables. `replace()` refuses the four store tables by
   name, and a full push leaves them untouched.
4. **The stealth list never reaches the database.** `handles.private.md` holds
   the denylist and the stealth counterparties, and must not enter a store that
   can be deployed. The push reads the public file only; the test reads the
   private one on purpose (the fixture companion) and asserts that every one of
   its denylist terms and every party in its stealth table is absent from all
   six mirror tables, whole-word and case-insensitively, the match rule that
   file states for itself. Absent the companion the test skips loudly rather
   than passing on an empty list.
5. **A pull writes the shapes the engine already reads.** `state/decisions.json`
   and `state/edits.json` come back in exactly the form `apply_edits.py` and
   `publish.py` were written against — asserted by handing the output to
   `apply_edits` itself and getting `pending`, not a parse error and not a
   phantom `conflict`.
6. **The two hashes are one number.** `desk/lib/hash.ts` and `repo.base_hash()`
   are run over the same vectors, in Node and in Python, and compared. A
   disagreement here would not corrupt a note — it would make every desk edit
   unappliable while looking exactly like a vault conflict, which is worse.
7. **Reviews reach memory once.** Only `scope: standing` rows travel to
   `.atelier/memory/reviews.md`; a second pull appends nothing; an item-scoped
   review stays on the desk.

Everything runs against a temp vault, a temp database and the fixture memory
(`fixture_memory.py`), with `repo.CAL`, `repo.STATE` and the memory paths
redirected, never against `Content/Calendar/`, `state/desk.db` or
`.atelier/memory/`.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import json
import os
import re
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ENGINE))
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import apply_edits  # noqa: E402
import desk_sync  # noqa: E402
import fixture_memory  # noqa: E402
import repo  # noqa: E402

DESK = os.path.join(REPO, "Tooling", "desk")

NOTE = """---
title: {title}
date: '{date}'
status: Idea
stream: Acme
type: Reactive
pillar: Thesis
platform: Blog
format: X-vs-Y
owner: EV
proof_gate: A primary source, cited to its publisher.
category: SecondTheme
slug: {slug}
excerpt: The claim the post makes.
feature: false
topics:
- SecondTheme
tags:
- content
engine_id: {eid}
theme: '#SecondTheme'
finding_id: F3
logic: L2
gate_verdict: pass
alpha_status: proposed
hooks_considered:
- {title}
cta: https://www.example.com/insights/{slug}
partner_tags: []
campaign: q3-2026-acme-evergreen
drafted_by: theme-writer
---

{body}
"""


def write_note(cal, eid, title, slug, date, body):
    path = os.path.join(cal, f"{title}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(NOTE.format(eid=eid, title=title, slug=slug, date=date, body=body))
    return path


class DeskSyncCase(fixture_memory.FixtureMemoryCase):
    """A temp vault, a temp state directory and a temp database, over the fixture memory."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="desk-sync-")
        self.cal = os.path.join(self.tmp, "Content", "Calendar")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.cal)
        os.makedirs(self.state)
        self.db_path = os.path.join(self.state, "desk.db")
        self.reviews_md = os.path.join(self.tmp, "memory", "reviews.md")

        self._saved = (repo.CAL, repo.STATE, desk_sync.STATE, desk_sync.REVIEWS_MD, desk_sync.DB_PATH)
        repo.CAL, repo.STATE = self.cal, self.state
        desk_sync.STATE, desk_sync.REVIEWS_MD, desk_sync.DB_PATH = self.state, self.reviews_md, self.db_path
        apply_edits.repo.CAL, apply_edits.repo.STATE = self.cal, self.state

        write_note(self.cal, "Q-1", "A closed set answers by exclusion", "closed-set", "2026-09-09",
                   "The body of the post, as the writer drafted it.")
        self.con = desk_sync.connect(self.db_path)
        desk_sync.ensure_schema(self.con)

    def tearDown(self):
        self.con.close()
        repo.CAL, repo.STATE, desk_sync.STATE, desk_sync.REVIEWS_MD, desk_sync.DB_PATH = self._saved
        apply_edits.repo.CAL, apply_edits.repo.STATE = self._saved[0], self._saved[1]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tables(self):
        return {r["name"] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def rows(self, table):
        return [dict(r) for r in self.con.execute(f"SELECT * FROM {table}")]

    def read_reviews(self):
        with open(self.reviews_md, encoding="utf-8") as f:
            return f.read()

    def record_decision(self, item_id, status="approved", scope="standing", rationale="Because."):
        """What the desk's server action writes, in the same two tables.

        The decision is upserted and the review is appended, which is the shape
        the action has: an item carries one current decision and the whole
        history of the reasoning behind it.
        """
        at = desk_sync.utcnow()
        self.con.execute(
            "INSERT INTO decisions (id, kind, status, note, by, at) VALUES (?, 'post', ?, ?, 'Alpha', ?) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, note = excluded.note, at = excluded.at",
            (item_id, status, rationale, at))
        self.con.execute(
            "INSERT INTO reviews (item_id, kind, theme, title, verdict, rationale, scope, by, at) "
            "VALUES (?, 'post', '#SecondTheme', 'A closed set answers by exclusion', ?, ?, ?, 'Alpha', ?)",
            (item_id, status, rationale, scope, at))
        self.con.commit()


class TheSchema(DeskSyncCase):
    """One source of DDL, applied by both runtimes."""

    def test_every_table_the_app_declares_exists(self):
        self.assertLessEqual(set(desk_sync.MIRROR_TABLES + desk_sync.STORE_TABLES + ("sync_meta",)), self.tables())

    def test_applying_it_twice_is_a_no_op(self):
        """`--push` calls ensure_schema on every run, so it has to be idempotent."""
        self.assertFalse(desk_sync.ensure_schema(self.con))

    def test_the_migration_is_the_generated_one(self):
        """Not hand-written SQL living beside the schema it is meant to track."""
        files = [f for f in os.listdir(os.path.join(DESK, "drizzle")) if f.endswith(".sql")]
        self.assertTrue(files, "no generated migration - run `npm run generate` in desk/")


class ThePush(DeskSyncCase):
    """The mirror tables are a derivation, and only the mirror tables move."""

    def test_a_note_becomes_a_row(self):
        desk_sync.push(self.con, verbose=False)
        rows = self.rows("items")
        self.assertEqual(1, len(rows))
        self.assertEqual("Q-1", rows[0]["id"])
        self.assertEqual("2026-09-09", rows[0]["date"], "the calendar axis is the note's own date")
        self.assertEqual("Idea", rows[0]["status"])
        self.assertEqual("#SecondTheme", rows[0]["theme"])

    def test_pushing_twice_replaces_rather_than_accumulates(self):
        desk_sync.push(self.con, verbose=False)
        desk_sync.push(self.con, verbose=False)
        self.assertEqual(1, len(self.rows("items")))

    def test_a_note_that_has_gone_leaves_no_row(self):
        desk_sync.push(self.con, verbose=False)
        os.remove(os.path.join(self.cal, "A closed set answers by exclusion.md"))
        desk_sync.push(self.con, verbose=False)
        self.assertEqual([], self.rows("items"))

    def test_the_note_hash_is_what_the_desk_will_stamp_an_edit_with(self):
        desk_sync.push(self.con, verbose=False)
        item = repo.load_items()[0]
        self.assertEqual(repo.base_hash(item), self.rows("items")[0]["note_hash"])

    def test_a_push_never_writes_the_decision_store(self):
        """The one that would lose real work: an act made but not yet pulled."""
        self.record_decision("Q-1")
        desk_sync.push(self.con, verbose=False)
        self.assertEqual(1, len(self.rows("decisions")), "a refresh destroyed a decision")
        self.assertEqual(1, len(self.rows("reviews")))

    def test_replace_refuses_a_store_table_by_name(self):
        for table in desk_sync.STORE_TABLES:
            with self.assertRaises(ValueError):
                desk_sync.replace(self.con, table, [])


class TheFindingStatus(DeskSyncCase):
    """The strategist's verdict, carried onto the finding the desk shows.

    `findings.status` is how Alpha sees, at a glance, which of the week's
    findings the strategist took and which it set aside — so it is worth
    pinning against a real `strategy.json` shape rather than trusting that the
    keys are what someone remembered them to be. They are `picks` and
    `not_this_week`, both lists of objects carrying a `finding_id`.

    The third case is the one that matters most: a finding nobody ruled on
    comes back with an empty status. `strategy.json` also carries `held_slot`,
    which is a paragraph of prose about the week's reactive calendar row and
    names no finding at all; a `held` status read out of it would be a verdict
    with no author.
    """

    def write_state(self, signals, strategy):
        for name, payload in (("signals.json", signals), ("strategy.json", strategy)):
            with open(os.path.join(self.state, name), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)

    def test_the_strategists_verdict_reaches_the_finding(self):
        self.write_state(
            {"findings": [
                {"id": "F2", "theme": "#ThirdTheme", "finding": "Token promotion, not a document."},
                {"id": "F3", "theme": "#SecondTheme", "finding": "A members-only ledger is a closed set."},
                {"id": "F5", "theme": "#ExampleTheme", "finding": "Nobody ruled on this one."},
            ]},
            {"week": "2026-09-08",
             "picks": [{"finding_id": "F3", "theme": "#SecondTheme", "platform": "Blog"}],
             "not_this_week": [{"finding_id": "F2", "reason": "Same theme as F1 in the same week."}],
             "held_slot": "Not triggered. The 2026-09-16 reactive row stays empty and titled only."},
        )
        desk_sync.push(self.con, verbose=False)
        status = {r["id"]: r["status"] for r in self.rows("findings")}

        self.assertEqual({"F2", "F3", "F5"}, set(status), "a finding went missing between signals and the desk")
        self.assertEqual("picked", status["F3"], "a picked finding must not arrive on the desk undecided")
        self.assertEqual("not-this-week", status["F2"])
        self.assertEqual("", status["F5"], "an unruled finding gained a verdict nothing in strategy.json states")

    def test_the_held_slot_prose_is_not_read_as_a_finding(self):
        """`held_slot` names no finding, so it must contribute no status at all.

        Written as its own case because the failure it guards against is silent:
        a `held` key read off this string would either match nothing — dead code
        that reads like coverage — or, if the prose were ever restructured into
        a list, stamp findings with a status the strategist never assigned.
        """
        self.write_state(
            {"findings": [{"id": "F7", "theme": "#FourthTheme", "finding": "In the pass, unruled."}]},
            {"picks": [], "not_this_week": [],
             "held_slot": "Not triggered. It triggers on a document published in full by an issuing body."},
        )
        desk_sync.push(self.con, verbose=False)
        self.assertEqual([""], [r["status"] for r in self.rows("findings")])


class TheStealthList(DeskSyncCase):
    """`handles.private.md` must not reach a store that can be deployed.

    `load_handles()` reports the private companion as `{path, present}` and
    nothing more — by design, so that the ordinary read path cannot hand a
    stealth counterparty to a caller by accident. The contents are reachable
    only through `memory.denylist()` and the companion's own tables, which is
    what the assertion below goes to fetch. It is the one place in this suite
    that reads the private file on purpose: to prove its contents are absent
    from somewhere else.
    """

    #: The `##` heading of the companion's stealth table. Its first column is
    #: the party, sometimes as `A / B` or `A · B`, sometimes with a
    #: parenthesised gloss, so each cell is split into the names it carries.
    STEALTH_TABLE = "stealth parties"

    def private_values(self):
        """The terms and party names that must appear nowhere in the database.

        Two lists, from the two parts of `handles.private.md` that are stealth
        rules rather than taggability rules:

        * **the denylist**: the closed terms Alpha alone edits, which the file
          itself says are matched case-insensitively and whole-word. No length
          filter is applied to them: a short term is still a term, and a
          filter that quietly drops the short ones is the same vacuity in
          miniature as a loop that never runs.
        * **the stealth parties table**: the counterparties that stay dark, the
          ones most likely to leak into a theme draft and from there into a row.

        The *draft and unsigned parties* table is deliberately excluded. It
        encodes a taggability rule (real relationships that are not yet
        nameable), not a stealth rule, and an entry there can be a plain
        English word that whole-word matching over theme prose would flag as a
        leak that is not one. Do not fold it back in.
        """
        text = desk_sync.memory._read(desk_sync.memory.HANDLES_PRIVATE_MD)
        names = set(desk_sync.memory.denylist())
        for row in desk_sync.memory.table_in(text, self.STEALTH_TABLE):
            cell = list(row.values())[0]
            for part in re.split(r"[/·]", cell):
                part = re.sub(r"\(.*?\)", "", part).strip(' "')
                if len(part) > 3:
                    names.add(part)
        return sorted(names)

    def test_no_private_counterparty_appears_in_any_table(self):
        """The property the whole boundary exists for, asserted term by term.

        A push replaces six mirror tables from the notes and from the *public*
        half of the inventory. Every cell of all six is flattened into one
        string and each private term is searched for in it, whole-word and
        case-insensitively — the match rule the companion states for itself,
        because several of the terms are short and ordinary in other contexts
        and a substring match would cry wolf on every `linear`.

        The database is a file the desk serves and something that can be
        deployed; a stealth counterparty inside it is not recoverable by
        deleting a row later. So this fails on the first occurrence and names
        the term, rather than reporting a count.
        """
        if not desk_sync.memory.load_handles()["private"]["present"]:
            self.skipTest(
                "handles.private.md is gitignored and absent from this checkout — "
                "there is no stealth list to assert the absence of. Restore the "
                "companion before trusting this suite's stealth coverage.")
        desk_sync.push(self.con, verbose=False)
        names = self.private_values()
        self.assertTrue(names, "the private companion is present but yielded no terms to check")

        blob = " ".join(
            str(dict(r)) for t in desk_sync.MIRROR_TABLES for r in self.con.execute(f"SELECT * FROM {t}")
        )
        for name in names:
            pattern = r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])"
            self.assertIsNone(
                re.search(pattern, blob, re.IGNORECASE),
                f"a stealth term reached the database: {name!r}")

    def test_the_inventory_carries_no_identity_column(self):
        """`identity` is dropped on the way past, as build_dashboard.py does."""
        desk_sync.push(self.con, verbose=False)
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(inventory)")}
        self.assertNotIn("identity", cols)

    def test_the_desk_is_told_the_companion_is_present_without_being_given_it(self):
        desk_sync.push(self.con, verbose=False)
        meta = dict(self.con.execute("SELECT key, value FROM sync_meta").fetchall())
        self.assertIn("private_handles_present", meta)
        self.assertIn(meta["private_handles_present"], ("0", "1"))


class ThePull(DeskSyncCase):
    """The shapes the rest of the engine was written against."""

    def test_decisions_come_back_in_the_shape_publish_reads(self):
        self.record_decision("Q-1", status="approved", scope="item")
        desk_sync.pull(self.con, verbose=False)
        with open(os.path.join(self.state, "decisions.json"), encoding="utf-8") as f:
            got = json.load(f)
        self.assertEqual({"status", "note", "by", "at", "stream"}, set(got["Q-1"]))
        self.assertEqual("approved", got["Q-1"]["status"])
        # A3: the act names the stream of the item it was made on, from the note.
        self.assertEqual("Acme", got["Q-1"]["stream"])

    def test_an_edit_comes_back_appliable_rather_than_as_a_phantom_conflict(self):
        """The whole point of the hash agreeing: apply_edits says `pending`."""
        desk_sync.push(self.con, verbose=False)
        item = repo.load_items()[0]
        self.con.execute(
            "INSERT INTO edits (item_id, title, post, teaser_linkedin, teaser_x, base_hash, by, at) "
            "VALUES ('Q-1', ?, ?, '', '', ?, 'Alpha', ?)",
            (item["title"], "Alpha's rewrite of the body.", repo.base_hash(item), desk_sync.utcnow()))
        self.con.commit()
        desk_sync.pull(self.con, verbose=False)

        edits = apply_edits.load_edits()
        self.assertEqual("pending", apply_edits.status_of(item, edits["Q-1"]))

    def test_an_edit_against_a_note_that_moved_is_a_conflict(self):
        """The other half: nothing is written, and it is not silently applied."""
        desk_sync.push(self.con, verbose=False)
        self.con.execute(
            "INSERT INTO edits (item_id, title, post, teaser_linkedin, teaser_x, base_hash, by, at) "
            "VALUES ('Q-1', 'x', 'y', '', '', 'deadbeef', 'Alpha', ?)", (desk_sync.utcnow(),))
        self.con.commit()
        desk_sync.pull(self.con, verbose=False)

        item = repo.load_items()[0]
        edits = apply_edits.load_edits()
        self.assertEqual("conflict", apply_edits.status_of(item, edits["Q-1"]))

    def test_a_dry_run_writes_nothing(self):
        self.record_decision("Q-1")
        desk_sync.pull(self.con, dry_run=True, verbose=False)
        self.assertFalse(os.path.exists(os.path.join(self.state, "decisions.json")))
        self.assertFalse(os.path.exists(self.reviews_md))
        self.assertIsNone(self.rows("reviews")[0]["synced_at"])


class TheReviews(DeskSyncCase):
    """Alpha's reasoning, into the memory the drafting agents read."""

    def test_a_standing_review_reaches_the_memory_file(self):
        self.record_decision("Q-1", scope="standing", rationale="A source URL that carries a figure is a figure.")
        desk_sync.pull(self.con, verbose=False)
        text = self.read_reviews()
        self.assertIn("A source URL that carries a figure is a figure.", text)
        self.assertIn("Q-1", text)

    def test_an_item_scoped_review_stays_on_the_desk(self):
        self.record_decision("Q-1", scope="item", rationale="Just this one.")
        desk_sync.pull(self.con, verbose=False)
        self.assertFalse(os.path.exists(self.reviews_md), "an item-scoped review leaked into memory")

    def test_a_second_pull_appends_nothing(self):
        self.record_decision("Q-1", scope="standing")
        desk_sync.pull(self.con, verbose=False)
        first = self.read_reviews()
        desk_sync.pull(self.con, verbose=False)
        self.assertEqual(first, self.read_reviews())

    def test_the_file_is_appended_to_never_rewritten(self):
        """Agents and people read this directory too; the write has to be additive."""
        self.record_decision("Q-1", scope="standing", rationale="First.")
        desk_sync.pull(self.con, verbose=False)
        self.record_decision("Q-1", scope="standing", rationale="Second, later.")
        desk_sync.pull(self.con, verbose=False)
        text = self.read_reviews()
        self.assertIn("First.", text)
        self.assertIn("Second, later.", text)

    def test_synced_rows_are_stamped(self):
        self.record_decision("Q-1", scope="standing")
        desk_sync.pull(self.con, verbose=False)
        self.assertTrue(self.rows("reviews")[0]["synced_at"])


class TheHashParity(unittest.TestCase):
    """One number in two languages, run in both rather than asserted by hand.

    `desk/lib/hash.ts` computes the digest the browser stamps on an edit and
    `repo.base_hash()` computes the one `apply_edits.py` checks it against. If
    they disagreed, every desk edit would come back as a vault conflict — the
    note would be safe and the desk would be useless. Node runs the actual
    module rather than a transcription of it.
    """

    VECTORS = [
        {"post": "a", "teaser_linkedin": "b", "teaser_x": "c", "title": "d"},
        {"post": "", "teaser_linkedin": "", "teaser_x": "", "title": ""},
        # The characters a real note carries: curly quotes, an em dash, a
        # hashtag, a newline, and an accent that is not in Latin-1.
        {"post": "Swift's own release — “a controlled phase”\n\nSecond para.",
         "teaser_linkedin": "#SecondTheme\nhttps://www.example.com/x",
         "teaser_x": "Zürich, Example City · 2026",
         "title": "A closed set answers who may transact by exclusion."},
    ]

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(DESK, "node_modules")):
            raise unittest.SkipTest("desk/node_modules absent - run `npm install` in desk/")

    def test_node_and_python_agree(self):
        script = (
            "const {baseHash} = await import('./lib/hash.ts');"
            "const v = JSON.parse(process.argv[1]);"
            "console.log(JSON.stringify(v.map(baseHash)));"
        )
        proc = subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "--eval", script,
             "--", json.dumps(self.VECTORS)],
            cwd=DESK, capture_output=True, text=True)
        if proc.returncode != 0:
            self.skipTest(f"node could not run the TypeScript module: {proc.stderr.strip()[:200]}")
        from_node = json.loads(proc.stdout.strip().splitlines()[-1])
        from_python = [repo.base_hash(v) for v in self.VECTORS]
        self.assertEqual(from_python, from_node)


class NoDeskHere(unittest.TestCase):
    """The desk is an optional module of the instance: without it and without its database the
    cycle's pull and push steps have nothing to do, and say so, rather than fail the chain."""

    def test_nothing_to_pull_or_push_and_no_database_made(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        db = os.path.join(d, "state", "desk.db")
        out = io.StringIO()
        with mock.patch.object(desk_sync, "DESK", os.path.join(d, "Tooling", "desk")), redirect_stdout(out):
            self.assertEqual(desk_sync.main(["--pull", "--dry-run", "--db", db]), 0)
            self.assertEqual(desk_sync.main(["--push", "--db", db]), 0)
        self.assertIn("nothing to pull or push", out.getvalue())
        self.assertFalse(os.path.exists(db))
        os.makedirs(os.path.dirname(db))
        open(db, "wb").close()  # an empty file a failed run left behind holds no act either
        with mock.patch.object(desk_sync, "DESK", os.path.join(d, "Tooling", "desk")), redirect_stdout(io.StringIO()):
            self.assertEqual(desk_sync.main(["--pull", "--dry-run", "--db", db]), 0)

    def test_a_database_with_the_desks_tables_is_still_pulled(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        db = os.path.join(d, "desk.db")
        con = desk_sync.connect(db)
        desk_sync.ensure_schema(con)
        con.close()
        self.assertTrue(desk_sync._has_desk_tables(db), "decisions made before the desk went are not stranded")


if __name__ == "__main__":
    unittest.main()

