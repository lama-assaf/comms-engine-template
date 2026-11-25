"""
The desk per stream (plan v2, item A14).

- the mirror tables gain a `stream` column, once, on an old or a new database
- a push writes the stream on findings, proposals, runs and themes rows
- `--pull --dry-run` names the target `reviews.md` per standing review: the
  root file for a root-stream item, `streams/<slug>/reviews.md` for another
- a real pull appends to the stream's own file and stamps `synced_at`
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
sys.path.insert(0, HERE)

import apply_edits  # noqa: E402
import desk_sync  # noqa: E402
import fixture_memory  # noqa: E402
import memory  # noqa: E402
import repo  # noqa: E402

NOTE = """---
title: {title}
date: '2026-10-20'
status: Idea
stream: {stream}
type: Reactive
pillar: Thesis
platform: Blog
format: X-vs-Y
owner: EV
proof_gate: A primary source.
category: SecondTheme
slug: {slug}
engine_id: {eid}
theme: '#SecondTheme'
finding_id: F1
logic: L1
gate_verdict: pass
alpha_status: proposed
hooks_considered: []
cta: https://www.example.com/insights/{slug}
---
The body.
"""


class DeskStream(fixture_memory.FixtureMemoryCase):
    """Over the fixture memory: the other stream's reviews.md is the temp copy's."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="desk-stream-")
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
        for eid, title, stream in (("Q-L", "An Acme item", "Acme"), ("Q-Z", "A Beta item", "Beta")):
            with open(os.path.join(self.cal, f"{title}.md"), "w", encoding="utf-8") as f:
                f.write(NOTE.format(title=title, stream=stream, slug=eid.lower(), eid=eid))
        with open(os.path.join(self.state, "signals.json"), "w", encoding="utf-8") as f:
            json.dump({"stream": "Acme", "findings": [{"id": "F1", "theme": "#SecondTheme", "finding": "x", "evidence": [{}]}]}, f)
        with open(os.path.join(self.state, "runs.json"), "w", encoding="utf-8") as f:
            json.dump([{"run_id": "r", "step": "gate", "at": "2026-10-20T07:00:00+00:00", "stream": "Acme", "detail": "d"}], f)
        self.con = desk_sync.connect(self.db_path)
        desk_sync.ensure_schema(self.con)

    def tearDown(self):
        self.con.close()
        repo.CAL, repo.STATE, desk_sync.STATE, desk_sync.REVIEWS_MD, desk_sync.DB_PATH = self._saved
        apply_edits.repo.CAL, apply_edits.repo.STATE = self._saved[0], self._saved[1]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cols(self, table):
        return {r["name"] for r in self.con.execute(f"PRAGMA table_info({table})")}

    def test_stream_columns_added_once(self):
        for t in desk_sync.STREAM_COLUMN_TABLES:
            self.assertIn("stream", self.cols(t), t)
        self.assertEqual(desk_sync.ensure_stream_columns(self.con), [])
        self.assertFalse(desk_sync.ensure_schema(self.con))

    def test_push_writes_stream_on_mirror_rows(self):
        desk_sync.push(self.con, verbose=False)
        self.assertEqual({r["stream"] for r in self.con.execute("SELECT stream FROM findings")}, {"Acme"})
        self.assertEqual({r["stream"] for r in self.con.execute("SELECT stream FROM runs")}, {"Acme"})
        self.assertEqual({r["stream"] for r in self.con.execute("SELECT stream FROM themes")}, {"Acme"})
        self.assertEqual({r["id"]: r["stream"] for r in self.con.execute("SELECT id, stream FROM items")}, {"Q-L": "Acme", "Q-Z": "Beta"})

    def record(self, item_id, title):
        self.con.execute(
            "INSERT INTO reviews (item_id, kind, theme, title, verdict, rationale, scope, by, at) VALUES (?, 'post', '#SecondTheme', ?, 'held', 'because', 'standing', 'Alpha', '2026-10-21T08:00:00+00:00')",
            (item_id, title))
        self.con.commit()

    def test_dry_run_names_the_target_per_review(self):
        desk_sync.push(self.con, verbose=False)
        self.record("Q-L", "An Acme item")
        self.record("Q-Z", "A Beta item")
        out = desk_sync.pull(self.con, dry_run=True, verbose=False)["reviews"]
        targets = {r["item_id"]: r["target"] for r in out}
        self.assertEqual(targets["Q-L"], self.reviews_md)
        self.assertEqual(targets["Q-Z"], os.path.join(memory.stream_dir("beta"), "reviews.md"))
        self.assertFalse(os.path.exists(self.reviews_md))

    def test_real_pull_appends_to_the_streams_file(self):
        desk_sync.push(self.con, verbose=False)
        self.record("Q-L", "An Acme item")
        other_target = os.path.join(memory.stream_dir("beta"), "reviews.md")
        self.assertTrue(other_target.startswith(self.fixture.root), "the temp copy, never the checkout")
        self.record("Q-Z", "A Beta item")
        desk_sync.pull(self.con, verbose=False)
        self.assertIn("Q-L", open(self.reviews_md, encoding="utf-8").read())
        self.assertNotIn("Q-Z", open(self.reviews_md, encoding="utf-8").read())
        self.assertIn("Q-Z", open(other_target, encoding="utf-8").read())
        left = list(self.con.execute("SELECT * FROM reviews WHERE synced_at IS NULL OR synced_at = ''"))
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
