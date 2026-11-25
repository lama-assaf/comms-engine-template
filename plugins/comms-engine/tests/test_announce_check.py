"""announce_check: cleared wording passes, an operating claim flags once a brand has written its rule, and
`write` turns a checked plan into one calendar item."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import announce_check as ac  # noqa: E402
import fixture_memory  # noqa: E402
import repo  # noqa: E402


def flagged(sentence):
    rules = ac.rules()
    if rules["cleared_re"].search(sentence):
        return []
    return [why for pat, why in rules["status_flags"] if re.search(pat, sentence, re.I)]


RULE = [{"pattern": r"\bnetwork[^.]*\b(is live|went live|is running)\b", "why": "status.md: the network has no go-live evidence."}]
CLEARED = ["is in the process of going live"]


class Rules(fixture_memory.FixtureMemoryCase):
    """The announcement rules are read from the brand's gate-rules.json, never from code."""

    def write_rules(self, **announce):
        with open(self.fixture.path("gate-rules.json"), "w", encoding="utf-8") as f:
            json.dump({"announce": announce}, f)


class ClearedWording(Rules):
    """A phrase an approved release carried is cleared and never flagged, even where a rule would match."""

    def test_cleared_phrases_pass(self):
        self.write_rules(status_flags=RULE, cleared_phrases=CLEARED)
        for s in [
            "The partners plan to run a node on the network.",
            "The network is in the process of going live, the partners said.",
        ]:
            self.assertEqual(flagged(s), [], s)
        self.assertTrue(flagged("The network is live today."), "the rule is in force outside the cleared wording")


class OperatingClaims(Rules):
    """The rules ship empty (a brand writes them from its status.md); with one written, an operating claim flags."""

    def test_shipped_rules_are_empty_and_flag_nothing(self):
        with open(Path(__file__).resolve().parents[3] / ".atelier" / "memory" / "gate-rules.json", encoding="utf-8") as f:
            shipped = json.load(f)["announce"]
        self.assertEqual(shipped, {"status_flags": [], "cleared_phrases": [], "voice_flags": []})
        rules = ac.rules()
        self.assertEqual((rules["status_flags"], rules["voice_flags"]), ([], []))
        self.assertIsNone(rules["cleared_re"].search("anything at all"))
        self.assertEqual(flagged("The network is live today."), [])
        self.assertFalse(hasattr(ac, "STATUS_FLAGS"), "no rule lives in the code")

    def test_a_written_rule_flags_an_operating_claim(self):
        self.write_rules(status_flags=RULE)
        self.assertTrue(flagged("The network is live today."))
        self.assertEqual(flagged("The network is being built."), [])

    def test_rules_that_do_not_read_stop_the_check(self):
        with open(self.fixture.path("gate-rules.json"), "w", encoding="utf-8") as f:
            f.write("{ not json")
        with self.assertRaises(SystemExit) as ctx:
            ac.rules()
        self.assertIn("does not parse as JSON", str(ctx.exception))


class Helpers(unittest.TestCase):
    def test_name_spelled_two_ways(self):
        text = {"blog": "said Firstname Lastnane, CEO. Contact Firstname Lastname."}
        with mock.patch.object(ac, "known_names", lambda: "nobody here"):
            out = ac.name_clashes(text)
        self.assertEqual(len(out), 1)
        # memory knows neither spelling: a note, and the user is asked
        self.assertEqual(out[0]["severity"], "note")
        self.assertIn("spelled two ways", out[0]["why"])
        # memory spells the surname one way, so the fix is named
        with mock.patch.object(ac, "known_names", lambda: "The CEO is Firstname Lastname."):
            out = ac.name_clashes(text)
        self.assertEqual(out[0]["severity"], "fill")
        self.assertIn("Firstname Lastname", out[0]["why"])

    def test_slugify_stops_at_a_word(self):
        self.assertEqual(ac.slugify("Partner Network joins Acme"), "partner-network-joins-acme")
        self.assertLessEqual(len(ac.slugify("word " * 40)), 60)



class WriteNotes(fixture_memory.FixtureMemoryCase):
    """`write`: a checked plan becomes one calendar item through repo.py, with the fills made."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="announce-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (repo.CAL, repo.STATE)
        repo.CAL, repo.STATE = os.path.join(self.tmp, "Content", "Calendar"), self.tmp
        self.addCleanup(lambda: (setattr(repo, "CAL", saved[0]), setattr(repo, "STATE", saved[1])))
        self.plan = {"title": "Partner joins Acme", "slug": "partner-joins-acme", "theme": "#ExampleTheme",
                     "date": "2026-11-20", "gate_verdict": "pass", "findings": [],
                     "blog": "Partner joins Acme on [Date]. More follows.", "linkedin": "Partner joins. [website link]",
                     "x": "Partner joins Acme."}
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)

    def run_write(self, *extra, plan=None):
        with open(os.path.join(self.out, "plan.json"), "w") as f:
            json.dump(plan or self.plan, f)
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            return ac.main(["write", self.out, *extra])

    def test_hand_posting_writes_the_article_alone_with_the_fills(self):
        self.assertEqual(self.run_write("--approved", "copy approved by the owner"), 0)
        [item] = repo.load_items()
        self.assertEqual(item["id"], "A-2026-11-20-partner-joins-acme")
        self.assertEqual(item["post"], "Partner joins Acme on 2026-11-20. More follows.")
        # nothing for an approval to schedule: X and LinkedIn go out by hand
        self.assertEqual((item["teaser_x"], item["teaser_linkedin"]), ("", ""))
        self.assertEqual((item["drafted_by"], item["alpha_status"], item["anchor"]),
                         (repo.TEAM_BY, "proposed", "copy approved by the owner"))

    def test_engine_posting_carries_the_x_post_and_a_rerun_rewrites_the_same_item(self):
        self.assertEqual(self.run_write("--approved", "ok", "--post", "engine"), 0)
        self.assertEqual(self.run_write("--approved", "ok", "--post", "engine",
                                        plan=dict(self.plan, x="Partner joins Acme today.")), 0)
        [item] = repo.load_items()
        self.assertEqual(item["teaser_x"], "Partner joins Acme today.")
        self.assertEqual(item["teaser_linkedin"], "")

    def test_refusals_write_nothing(self):
        cases = [((), self.plan),  # no approval
                 (("--approved", "ok"), dict(self.plan, findings=[{"check": "clearance", "severity": "block", "line": "x"}])),
                 (("--approved", "ok"), dict(self.plan, date="")),
                 (("--approved", "ok"), dict(self.plan, blog="Quote from [Name] here."))]
        for extra, plan in cases:
            self.assertEqual(self.run_write(*extra, plan=plan), 2, plan)
        self.assertEqual(repo.load_items(), [])

    def test_a_decided_announcement_is_not_rewritten(self):
        self.run_write("--approved", "ok")
        repo.set_fields("A-2026-11-20-partner-joins-acme", {"alpha_status": "approved"})
        self.assertEqual(self.run_write("--approved", "ok", plan=dict(self.plan, blog="Other words.")), 2)
        self.assertIn("More follows.", repo.load_items()[0]["post"])


if __name__ == "__main__":
    unittest.main()
