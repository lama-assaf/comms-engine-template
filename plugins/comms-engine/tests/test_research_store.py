"""
The research store (plan v2, item A16), in files mode.

- a fixture finding from the sweep becomes a `watching` candidate with its
  tier, and the gate cannot cite it (it is not a register row)
- a second independent source promotes the candidate to two-independent; a
  primary source makes it primary; the same source twice only extends `seen`
- the day's watch log is written; `promotable` lists what corpus-analyse may
  propose
- the topic map exists for all eight hashtags and carries the month's changed
  claims; writing it into a campaign file replaces the section, not the file
- with the store absent everything runs in files mode and the gate verdicts
  are unchanged (the suite as a whole is that check)

Shared memory is the fixture copy (`fixture_memory.py`); the findings are
invented.
"""
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
import memory  # noqa: E402
import research_store as rs  # noqa: E402

F1 = {"id": "F1", "theme": "#ExampleTheme", "finding": "The standards body published a revised checklist for its issuer qualification programme",
      "evidence": [{"title": "Standards body: issuer qualification programme update", "url": "https://standards.example.org/x"}], "sentiment": "neutral",
      "conversation": {"target": "x", "shape": "question"}}
F2 = {"id": "F2", "theme": "#FourthTheme", "finding": "A trade outlet reports a bank-run pilot of a rule-carrying currency rail",
      "evidence": [{"title": "Example Press: bank rail pilot", "url": "https://trade-a.example.org/y"}], "sentiment": "positive"}
F3 = {"id": "F3", "theme": "#FourthTheme", "finding": "A trade outlet reports a bank-run pilot of a rule-carrying currency rail",
      "evidence": [{"title": "Example Business Press: rail pilot", "url": "https://trade-b.example.org/z"}], "sentiment": "neutral"}
F0 = {"id": "F0", "theme": "#FourthTheme", "finding": "no evidence here", "evidence": []}


class FilesMode(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.state = tempfile.mkdtemp(prefix="rs-")
        self.log = os.path.join(self.state, "watch", "2026-10-26.md")

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)
        super().tearDown()

    def test_mode_is_files_without_the_store(self):
        self.assertEqual(rs.mode(), "files")

    def test_finding_becomes_a_watching_candidate_the_gate_cannot_cite(self):
        out = rs.watch([F1, F0], "acme", self.state, today="2026-10-26", log_path=self.log)
        self.assertEqual((out["mode"], out["new"], out["total"]), ("files", 1, 1))
        c = rs.load_candidates(self.state)[0]
        self.assertEqual((c["tier"], c["grade"], c["corroboration"]), ("primary", "asserted", "primary"))
        self.assertEqual(c["theme"], "#ExampleTheme")
        self.assertTrue(os.path.exists(self.log))
        self.assertFalse(memory.citable(c["candidate_id"])[0])

    def test_second_independent_source_promotes(self):
        rs.watch([F2], "acme", self.state, today="2026-10-26", log_path=self.log)
        c = rs.load_candidates(self.state)[0]
        self.assertEqual((c["tier"], c["corroboration"]), ("trade", "watching"))
        self.assertEqual(rs.promotable(self.state), [])
        rs.watch([F2], "acme", self.state, today="2026-10-27", log_path=self.log)
        c = rs.load_candidates(self.state)[0]
        self.assertEqual(c["corroboration"], "watching")
        self.assertEqual(c["seen"], ["2026-10-26", "2026-10-27"])
        rs.watch([F3], "acme", self.state, today="2026-10-28", log_path=self.log)
        cands = rs.load_candidates(self.state)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["corroboration"], "two-independent")
        self.assertEqual(cands[0]["also"][0]["source"], "Example Business Press: rail pilot")
        self.assertEqual([c["candidate_id"] for c in rs.promotable(self.state)], [cands[0]["candidate_id"]])
        self.assertEqual(rs.promotable(self.state, since="2026-10-28"), [])

    def test_topic_map_for_all_hashtags_and_section_replace(self):
        rs.watch([F2], "acme", self.state, today="2026-10-26", log_path=self.log)
        changes = [{"id": "C-acme-2", "field": "grade", "from": "evidenced", "to": "asserted", "seen_at": "2026-10-20T22:00:00+00:00"}]
        tm = rs.topic_map("acme", self.state, month="2026-10", signals={"findings": [F1, F2]}, items=[], changes=changes)
        self.assertEqual(set(tm["themes"]), set(memory.theme_tags()))
        self.assertEqual(tm["themes"]["#FourthTheme"]["claims_changed"], ["C-acme-2"])
        self.assertEqual(len(tm["themes"]["#ExampleTheme"]["open_questions"]), 1)
        self.assertEqual(len(tm["themes"]["#FourthTheme"]["candidates_watching"]), 1)
        camp = os.path.join(self.state, "campaign.md")
        with open(camp, "w", encoding="utf-8") as f:
            f.write("# campaign\n\n## brief\n\ntext\n\n## topic map — 2026-09 (mode: files)\n\nold\n\n## engager ledger\n\nrows\n")
        rs.write_topic_map(tm, camp)
        text = open(camp, encoding="utf-8").read()
        self.assertIn("## topic map — 2026-10", text)
        self.assertNotIn("2026-09", text)
        self.assertIn("## engager ledger", text)
        self.assertIn("## brief", text)
        self.assertEqual(text.count("## topic map"), 1)

    def test_episodes_shape_from_the_register(self):
        # the function's default stream is fixed at import; the fixture root is passed
        eps = rs.episodes_from_register(fixture_memory.ROOT)
        self.assertEqual(len(eps), len(memory.load_claims()))
        self.assertTrue(all(e["stream"] == fixture_memory.ROOT_NAME for e in eps))
        self.assertTrue(any("C-acme-2" in e["name"] for e in eps))
        self.assertEqual(rs.ingest("acme", self.state)["mode"], "files")


if __name__ == "__main__":
    unittest.main()
