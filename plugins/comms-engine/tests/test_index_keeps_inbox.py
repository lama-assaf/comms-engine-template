"""
`repo.write_index()` keeps the drafting inbox.

The 2026-11-05 cycle lost three drafts: the theme-writer had appended them to
state/queue.json, the distributor ran apply_edits.py, and its index rebuild
wrote queue.json from the notes alone, before `repo.py --all` had ingested the
drafts into notes. The index is derived from the vault, but an item that has
no note yet exists only in the index, so a rebuild must carry it over.

- an item in queue.json with no note survives a rebuild, marked as inbox
- an item that has a note is read from the note (the note wins)
- a rebuild on an empty or missing queue.json still works
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import repo  # noqa: E402


class IndexKeepsInbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._state, self._cal = repo.STATE, repo.CAL
        repo.STATE = os.path.join(self.tmp, "state")
        repo.CAL = os.path.join(self.tmp, "Content", "Calendar")
        os.makedirs(repo.STATE)
        os.makedirs(repo.CAL)

    def tearDown(self):
        repo.STATE, repo.CAL = self._state, self._cal
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_inbox_item_survives_rebuild(self):
        draft = {"id": "Q-2026-11-05-exampletheme-1", "stream": "Acme", "theme": "#ExampleTheme",
                 "title": "A draft with no note yet", "alpha_status": "proposed"}
        with open(os.path.join(repo.STATE, "queue.json"), "w", encoding="utf-8") as f:
            json.dump([draft], f)
        repo.write_index()
        with open(os.path.join(repo.STATE, "queue.json"), encoding="utf-8") as f:
            items = json.load(f)
        ids = [i["id"] for i in items]
        self.assertIn("Q-2026-11-05-exampletheme-1", ids)
        kept = next(i for i in items if i["id"] == draft["id"])
        self.assertEqual(kept["title"], draft["title"])

    def test_missing_queue_is_fine(self):
        repo.write_index()
        with open(os.path.join(repo.STATE, "queue.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), [])


if __name__ == "__main__":
    unittest.main()
