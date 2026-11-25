"""
Varied writing: the formats a stream may use, the weighted draw of a format and a logic per
draft, and the candidates a person can swap in.

- formats.json reads through memory.py; the shipped file has the eight formats, each with a
  structure and its channels; a stream without the file has the theme post alone; a file that
  does not read is an error, never a default
- the draw is deterministic for its seed, stays inside the 60/25/15 budget of proven,
  variation and experiment, weighs a format by how it scored, never draws a format that needs
  evidence for a held theme, and lands in planning.json per theme
- a prediction record carries the format and the logic, so the next draw can weigh them
- the draw and the alternatives live on the post note and read back; swapping an alternative
  in keeps what it replaced, clears the gate and is refused under a person's decision
"""
import collections
import copy
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ENGINE))
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import livetests  # noqa: E402
import memory  # noqa: E402
import plan_queries  # noqa: E402
import predictions  # noqa: E402
import repo  # noqa: E402

DAY = dt.date(2026, 11, 13)
NAME = fixture_memory.ROOT_NAME

with open(os.path.join(HERE, "fixtures.json"), encoding="utf-8") as f:
    BASE = json.load(f)["base"]


def scored(fmt, logic, band, n=2):
    return [{"id": f"{fmt}-{logic}-{band}-{i}", "stream": NAME, "format": fmt, "logic": logic, "actual": band} for i in range(n)]


class Formats(fixture_memory.FixtureMemoryCase):
    def shipped(self):
        return memory.load_formats(path=os.path.join(REPO, ".atelier", "memory", "formats.json"))

    def test_the_shipped_file_has_the_eight_formats(self):
        formats = self.shipped()
        self.assertEqual(list(formats), ["theme-post", "x-thread", "short-take", "quote-commentary", "question", "data-note",
                                         "motion-card", "case-story"])
        for key, f in formats.items():
            self.assertTrue(f["structure"] and f["channels"] and f["when"] and f["length"], key)
            self.assertLessEqual(set(f["channels"]), set(memory.FORMAT_CHANNELS))
        self.assertEqual(formats["x-thread"]["skill"], "salon:x-thread")
        self.assertEqual([k for k, f in formats.items() if f["needs_evidence"]], ["data-note", "case-story"])
        self.assertEqual(len(formats["theme-post"]["structure"]), 5, "the five-part structure is one format among them")

    def test_a_stream_without_the_file_writes_theme_posts_only(self):
        self.assertEqual(list(memory.load_formats()), ["theme-post"])
        self.assertEqual(list(memory.load_formats(fixture_memory.OTHER)), ["theme-post"])

    def test_a_file_that_does_not_read_is_an_error(self):
        path = self.fixture.path("formats.json")
        for bad in ("{ not json", {"formats": {}}, {"formats": {"x": {"structure": [], "channels": ["x"]}}},
                    {"formats": {"note": {"structure": ["a"], "channels": ["fax"]}}},
                    {"formats": {"note": {"structure": ["a"], "channels": ["x"], "weight": 0}}},
                    {"formats": {"Bad Key": {"structure": ["a"], "channels": ["x"]}}}):
            with open(path, "w", encoding="utf-8") as f:
                f.write(bad if isinstance(bad, str) else json.dumps(bad))
            with self.assertRaises(memory.SharedMemoryError, msg=str(bad)):
                memory.load_formats()


class Draw(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.formats = memory.load_formats(path=os.path.join(REPO, ".atelier", "memory", "formats.json"))

    def draw(self, records=(), seed="s", logics=("L1", "L2"), licence="full", formats=None):
        return plan_queries.draw(formats or self.formats, list(logics), list(records), NAME, seed, licence=licence)

    def many(self, n=600, **kw):
        return [self.draw(seed=f"seed-{i}", **kw) for i in range(n)]

    def test_the_same_seed_gives_the_same_draw(self):
        a, b = self.draw(seed="acme:#T:2026-11-13:1"), self.draw(seed="acme:#T:2026-11-13:1")
        self.assertEqual(a, b)
        self.assertEqual(set(a), {"format", "logic", "kind", "seed", "weight", "pool"})
        self.assertNotEqual({d["format"] for d in self.many(40)}, {a["format"]}, "another seed is another draw")
        self.assertEqual(plan_queries.draw_seed("acme", "#T", DAY, 2), "acme:#T:2026-11-13:2")

    def test_with_no_history_everything_is_an_experiment_and_every_format_can_come_up(self):
        draws = self.many()
        self.assertEqual({d["kind"] for d in draws}, {"experiment"})
        self.assertEqual({d["format"] for d in draws}, set(self.formats))
        count = collections.Counter(d["format"] for d in draws)
        self.assertGreater(count["theme-post"], count["case-story"], "the base weight still counts before any result")

    def test_the_kinds_follow_the_budget(self):
        records = scored("theme-post", "L1", "above") + scored("theme-post", "L2", "baseline") + scored("x-thread", "L1", "above")
        self.assertEqual(plan_queries.kind_of("theme-post", "L1", *plan_queries.past_scores(records, NAME)), "proven")
        self.assertEqual(plan_queries.kind_of("x-thread", "L2", *plan_queries.past_scores(records, NAME)), "variation")
        self.assertEqual(plan_queries.kind_of("question", "L1", *plan_queries.past_scores(records, NAME)), "experiment")
        draws = self.many(2000, records=records)
        share = {k: sum(1 for d in draws if d["kind"] == k) / len(draws) for k in livetests.KINDS}
        for kind, want in livetests.BUDGET.items():
            self.assertAlmostEqual(share[kind], want, delta=0.04, msg=f"{kind}: {share}")
        self.assertEqual(draws[0]["pool"], {"proven": 3, "variation": 1, "experiment": 12})

    def test_a_format_that_scored_below_is_not_proven_and_is_drawn_less(self):
        below = scored("short-take", "L1", "below") + scored("short-take", "L2", "below")
        above = scored("question", "L1", "above") + scored("question", "L2", "above")
        by_format, by_combo = plan_queries.past_scores(below, NAME)
        self.assertEqual(plan_queries.kind_of("short-take", "L1", by_format, by_combo), "experiment")
        only = {k: self.formats[k] for k in ("short-take", "question")}
        draws = self.many(800, records=below + above, formats={k: dict(v, weight=1.0) for k, v in only.items()})
        proven = [d for d in draws if d["kind"] == "proven"]
        self.assertTrue(proven and all(d["format"] == "question" for d in proven))
        self.assertLess(sum(1 for d in draws if d["format"] == "short-take"), sum(1 for d in draws if d["format"] == "question"))

    def test_a_held_theme_never_draws_a_format_that_needs_evidence(self):
        self.assertNotIn(True, [self.formats[d["format"]]["needs_evidence"] for d in self.many(licence="held")])
        self.assertIn(True, [self.formats[d["format"]]["needs_evidence"] for d in self.many(licence="full")])
        evidence_only = {"case-story": self.formats["case-story"]}
        with self.assertRaises(memory.SharedMemoryError):
            self.draw(formats=evidence_only, licence="held")

    def test_another_streams_scores_and_unscored_records_do_not_count(self):
        records = [dict(r, stream="Beta") for r in scored("question", "L1", "above")] + \
                  [{"id": "x", "stream": NAME, "format": "question", "logic": "L1", "actual": None}]
        self.assertEqual(plan_queries.past_scores(records, NAME), ({}, {}))
        legacy = [{"id": "o", "stream": NAME, "format": "Observation", "logic": "L1", "actual": "above"}]
        self.assertEqual(list(plan_queries.past_scores(legacy, NAME)[0]), ["theme-post"], "an old note's label is a theme post")

    def test_the_plan_carries_a_draw_per_theme_and_the_record_carries_what_was_drawn(self):
        state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, state, True)
        out = plan_queries.run(fixture_memory.ROOT, state=state, cal=os.path.join(state, "none"), today=DAY, signals={},
                               engagement={}, changes=[])
        for tag, row in out["themes"].items():
            d = row["draw"]
            self.assertEqual(d["format"], "theme-post", "the fixture stream has no formats.json: one format")
            self.assertEqual((d["seed"], d["at"]), (f"acme:{tag}:2026-11-13:1", "2026-11-13"))
            self.assertIn(d["kind"], livetests.KINDS)
        self.assertIn(out["themes"]["#ExampleTheme"]["draw"]["logic"], ("L1", "L2"), "the logic is one of the theme's own")
        self.assertIn("draw", plan_queries.table(out).splitlines()[0])
        again = plan_queries.draw_for(fixture_memory.ROOT, "#ExampleTheme", state=state, today=DAY, slot=2)
        self.assertEqual(again["seed"], "acme:#ExampleTheme:2026-11-13:2")
        with self.assertRaises(memory.SharedMemoryError):
            plan_queries.draw_for(fixture_memory.ROOT, "#NotATheme", state=state, today=DAY)
        item = dict(BASE, format="x-thread", logic="L2", slot={"platform": "X"})
        rec = predictions.record_for(item)
        self.assertEqual((rec["format"], rec["logic"]), ("x-thread", "L2"))


class Alternatives(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="formats-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (repo.CAL, repo.STATE)
        repo.CAL, repo.STATE = os.path.join(self.tmp, "Content", "Calendar"), self.tmp
        self.addCleanup(lambda: (setattr(repo, "CAL", saved[0]), setattr(repo, "STATE", saved[1])))
        self.item = dict(copy.deepcopy(BASE), id="Q-1", alpha_status="proposed", slot={"date": "2026-11-16"},
                         format="short-take", logic="L2",
                         draw={"seed": "acme:#ExampleTheme:2026-11-13:1", "kind": "variation", "at": "2026-11-13"},
                         gate={"verdict": "pass", "checks": []},
                         alternatives=[
                             {"variable": "hook form", "value": "a question", "rank": 2, "why": "sharper",
                              "title": "Which root does a company credential chain to?",
                              "teaser_x": "Which root does a company credential chain to?\n\nNobody has decided in public.\n\n#ExampleTheme\nhttps://www.example.com/insights/a-root-is-not-a-wallet"},
                             {"variable": "hook form", "value": "a scene", "rank": 3, "why": "slower"}])
        repo.write_item(self.item, "Idea")

    def read(self):
        return {i["id"]: i for i in repo.load_items()}["Q-1"]

    def test_the_draw_and_the_alternatives_are_on_the_post_note_and_read_back(self):
        item = self.read()
        self.assertEqual((item["format"], item["logic"]), ("short-take", "L2"))
        self.assertEqual(item["draw"], self.item["draw"])
        self.assertEqual(item["alternatives"], self.item["alternatives"])
        fm, _ = repo.parse_note(os.path.join(repo.CAL, repo.safe_title(self.item["title"]) + " - teasers.md"))
        self.assertNotIn("alternatives", fm, "the teasers note is the companion, not a second record")
        plain = dict(copy.deepcopy(BASE), id="Q-2", slot={"date": "2026-11-17"}, title="Another piece entirely. With its own hook.")
        repo.write_item(plain, "Idea")
        fm, _ = repo.parse_note(os.path.join(repo.CAL, repo.safe_title(plain["title"]) + ".md"))
        self.assertNotIn("draw", fm, "a note without a draw is written as it always was")
        self.assertNotIn("alternatives", fm)

    def test_swapping_one_in_keeps_what_it_replaced_and_sends_the_text_back_to_the_gate(self):
        before = self.read()
        repo.swap_alternative("Q-1", 1)
        after = self.read()
        self.assertEqual(after["title"], "Which root does a company credential chain to?")
        self.assertTrue(after["teaser_x"].startswith("Which root does a company credential chain to?"))
        self.assertEqual(after["post"], before["post"], "a field the alternative does not carry stays")
        self.assertEqual(after["teaser_linkedin"], before["teaser_linkedin"])
        self.assertEqual((after["gate"], after["alpha_status"]), ({}, "proposed"), "a new text: the gate reads it again")
        kept = after["alternatives"][0]
        self.assertEqual((kept["title"], kept["teaser_x"], kept["value"]), (before["title"], before["teaser_x"], "the draft this replaced"))
        self.assertNotEqual(repo.base_hash(after), repo.base_hash(before))
        repo.swap_alternative("Q-1", 1)
        back = self.read()
        self.assertEqual((back["title"], back["teaser_x"]), (before["title"], before["teaser_x"]), "a swap can be undone")

    def test_a_swap_is_refused_under_a_decision_and_for_an_alternative_that_is_not_there(self):
        for n in (0, 3, "1"):
            with self.assertRaises(KeyError):
                repo.swap_alternative("Q-1", n)
        with self.assertRaises(KeyError) as cm:
            repo.swap_alternative("Q-1", 2)
        self.assertIn("carries no text", str(cm.exception))
        with self.assertRaises(KeyError):
            repo.swap_alternative("Q-none", 1)
        repo.set_fields("Q-1", {"alpha_status": "approved"})
        with self.assertRaises(KeyError) as cm:
            repo.swap_alternative("Q-1", 1)
        self.assertIn("approved", str(cm.exception))
        self.assertEqual(self.read()["title"], self.item["title"])


class TheWriter(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(ENGINE, *parts), encoding="utf-8") as f:
            return " ".join(f.read().split())

    def test_the_writer_follows_the_draw_and_writes_three_candidates(self):
        agent = self.read("agents", "theme-writer.md")
        skill = self.read("skills", "theme-post", "SKILL.md")
        for text, name in ((agent, "theme-writer.md"), (skill, "theme-post/SKILL.md")):
            for must in ("formats.json", "`draw`", "three candidates" if text is agent else "Three candidates", "salon:post-audit",
                         "`alternatives`", "--swap"):
                self.assertIn(must.lower(), text.lower(), (name, must))
        self.assertIn("it is one format, not the only one", skill)
        self.assertIn("You never invent a seed", agent)
        self.assertIn("differ in the one variable", agent)


if __name__ == "__main__":
    unittest.main()
