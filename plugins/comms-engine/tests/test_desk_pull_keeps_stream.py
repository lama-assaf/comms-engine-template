"""A pulled act keeps its recorded stream when its item has left the indexes.

2026-11-05: a scheduled cycle's desk pull rewrote two older comment decisions
with stream '' because their proposals were no longer in engagement.json after
the day's engagement pass; state_check then failed. The stream on the record
is kept, the notes win where they still know the item.
"""
import os
import sqlite3
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import desk_sync  # noqa: E402

ROOT_NAME, OTHER_NAME = "Acme", "Beta"


def con_with_decisions(rows):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE decisions (id TEXT PRIMARY KEY, status TEXT, note TEXT, by TEXT, at TEXT, stream TEXT NOT NULL DEFAULT '')")
    con.executemany("INSERT INTO decisions (id, status, note, by, at) VALUES (?,?,?,?,?)", rows)
    return con


class PullKeepsStream(unittest.TestCase):
    def test_recorded_stream_survives_a_missing_item(self):
        con = con_with_decisions([("C-F2-X", "approved", "", "Alpha", "2026-09-08T07:41Z"),
                                  ("Q-2026-09-09-x-1", "approved", "", "Alpha", "2026-09-08T05:50Z")])
        recorded = {"C-F2-X": {"status": "approved", "stream": ROOT_NAME}}
        with mock.patch.object(desk_sync, "load_json", lambda name, default: recorded if name == "decisions.json" else default):
            out = desk_sync.pull_decisions(con, streams={"Q-2026-09-09-x-1": ROOT_NAME})
        self.assertEqual(out["C-F2-X"]["stream"], ROOT_NAME, "kept from the file")
        self.assertEqual(out["Q-2026-09-09-x-1"]["stream"], ROOT_NAME, "from the notes")

    def test_the_notes_win_over_the_record(self):
        con = con_with_decisions([("Q-1", "approved", "", "Alpha", "2026-09-08T05:50Z")])
        recorded = {"Q-1": {"status": "approved", "stream": ROOT_NAME}}
        with mock.patch.object(desk_sync, "load_json", lambda name, default: recorded if name == "decisions.json" else default):
            out = desk_sync.pull_decisions(con, streams={"Q-1": OTHER_NAME})
        self.assertEqual(out["Q-1"]["stream"], OTHER_NAME)

    def test_nothing_recorded_stays_empty(self):
        con = con_with_decisions([("Q-9", "approved", "", "Alpha", "2026-09-08T05:50Z")])
        with mock.patch.object(desk_sync, "load_json", lambda name, default: default):
            out = desk_sync.pull_decisions(con, streams={})
        self.assertEqual(out["Q-9"]["stream"], "")


if __name__ == "__main__":
    unittest.main()
