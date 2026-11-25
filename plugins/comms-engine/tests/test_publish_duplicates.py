"""
Never republish what the calendar already shows as Published.

A desk approval can stand in the engine for a piece the autopilot has already
sent, or that a person released by hand. `publish.py` must refuse it, by title
or by slug, and must not refuse an item that is not out. The snapshot and the
vault are temp copies built from the gate fixture item; nothing here reads
`state/` or `Content/Calendar/`.
"""
import contextlib
import copy
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

import fixture_memory  # noqa: E402
import publish  # noqa: E402
import repo  # noqa: E402

with open(os.path.join(HERE, "fixtures.json"), encoding="utf-8") as f:
    BASE = json.load(f)["base"]

PUBLISHED_TITLE = "A closed set answers who may transact by exclusion. Identity answers it by proof."


class Duplicates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dup-")
        self.snap = os.path.join(self.tmp, "calendar-snapshot.json")
        with open(self.snap, "w", encoding="utf-8") as f:
            json.dump({"rows": [
                {"title": PUBLISHED_TITLE, "platform": "Blog", "status": "Published", "date": "2026-09-24",
                 "slug": "a-closed-set-answers-who-may-transact-by-exclusion-identity-answers-it-by-proof"},
                {"title": "Something else", "platform": "X", "status": "Published", "slug": "sovereignty-as-infrastructure-x"},
                {"title": "Parked", "platform": "Blog", "status": "Idea", "slug": "parked"},
            ]}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_by_title(self):
        item = {"title": PUBLISHED_TITLE, "slug": "closed-set-answers-by-exclusion"}
        self.assertEqual(publish.already_published(item, self.snap)["date"], "2026-09-24")

    def test_by_slug_with_a_platform_suffix(self):
        item = {"title": "Sovereignty, as infrastructure", "slug": "sovereignty-as-infrastructure"}
        self.assertIsNotNone(publish.already_published(item, self.snap))

    def test_not_published_is_not_refused(self):
        self.assertIsNone(publish.already_published({"title": "Parked", "slug": "parked"}, self.snap))
        self.assertIsNone(publish.already_published({"title": "New piece", "slug": "new-piece"}, self.snap))

    def test_no_snapshot_refuses_nothing(self):
        self.assertIsNone(publish.already_published({"title": PUBLISHED_TITLE}, os.path.join(self.tmp, "none.json")))


class StandingApproval(fixture_memory.FixtureMemoryCase):
    """An approved item the calendar already shows as Published is refused before anything is written."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="dup-vault-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.real = (repo.CAL, repo.STATE, publish.STATE, publish.SNAPSHOT)
        self.addCleanup(self.restore)
        repo.CAL = os.path.join(self.tmp, "Calendar")
        repo.STATE = publish.STATE = os.path.join(self.tmp, "state")
        os.makedirs(repo.CAL)
        os.makedirs(repo.STATE)
        item = copy.deepcopy(BASE)
        item["slot"] = {"date": "2026-10-06", "platform": "Blog", "campaign": ""}
        item["gate"] = {"verdict": "pass", "checks": []}
        item["alpha_status"] = "approved"
        repo.write_item(item, "Idea")
        repo.write_index()
        self.item = repo.load_items()[0]
        publish.SNAPSHOT = os.path.join(self.tmp, "calendar-snapshot.json")
        with open(publish.SNAPSHOT, "w", encoding="utf-8") as f:
            json.dump({"rows": [{"title": self.item["title"], "platform": "Blog", "status": "Published",
                                 "date": "2026-10-06", "slug": self.item["slug"]}]}, f)

    def restore(self):
        repo.CAL, repo.STATE, publish.STATE, publish.SNAPSHOT = self.real

    def test_the_standing_approval_is_caught(self):
        self.assertIsNotNone(publish.already_published(self.item))

    def test_cli_refuses_before_writing(self):
        path = repo.scan_notes()[self.item["id"]]["Blog"][0]
        with open(path, "rb") as f:
            before = f.read()
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                publish.main([self.item["id"]])
        self.assertIn("Nothing written", str(cm.exception))
        with open(path, "rb") as f:
            self.assertEqual(before, f.read())
        self.assertNotIn("published_to", repo.load_items()[0])


if __name__ == "__main__":
    unittest.main()
