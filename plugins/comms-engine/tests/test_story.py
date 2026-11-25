#!/usr/bin/env python3
"""
`scripts/story.py`, the story deck of each run, and `scripts/genome.py`, the
brand genome every visual reads.

1. **The check.** A deck of 5 to 9 slides, a cover first, a state slide, at
   most three questions, short headlines, every number one the facts carry,
   nothing on the denylist. An invented number, a long headline, a missing
   cover, too many questions or an unknown slide kind stop it.
2. **Publishing and answers.** Publishing gives each question an id and keeps
   it open in the questions file; the same open question asked again keeps its
   id; an answer is recorded once, refused when the file moved or the answer
   is empty, and an answered question reads back as answered.
3. **The genome.** Missing values come from the defaults, a bad colour falls
   back, and a logo that could run script is dropped.

Every file is a temp file and the gate's text checks are stubbed.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import gate_lint  # noqa: E402
import genome  # noqa: E402
import story  # noqa: E402

FACTS = {"run_id": "20261106T190000Z", "date": "2026-11-06", "stream": "Acme",
         "posts": {"next_14_days": 4, "planned": 8, "waiting_for_ok": 8, "stopped_by_check": 0},
         "listening": {"findings": [{"id": "F1", "theme": "#ExampleTheme", "finding": "Banks moved first."}]},
         "questions": {"open": [], "answered_since_last_story": []}}

GOOD = {"slides": [
    {"kind": "cover", "title": "Four posts are ready and the banks moved first", "subtitle": "What changed this week."},
    {"kind": "state", "title": "Eight posts wait for your OK", "figure": {"value": "4", "label": "posts in two weeks"},
     "points": ["Nothing was stopped by the check.", "Eight posts are waiting for you."]},
    {"kind": "discoveries", "title": "What we found", "items": [{"text": "Banks moved first.", "source": "F1"}]},
    {"kind": "question", "question": "Should the example theme stay not yet allowed?", "why": "It decides what posts may say.",
     "options": ["Keep it", "Upgrade it"]},
    {"kind": "next", "title": "What happens next", "points": ["The posts go to the desk."]}]}


def fake_check(name):
    def run(item, slug=None):
        if "Umbra Capital" in item["post"]:
            return gate_lint.check(name, "block", "Umbra Capital", "on the denylist")
        return gate_lint.check(name)
    return run


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        for p in (mock.patch.object(story, "STORY", self.dir),
                  mock.patch.object(gate_lint, "check_stealth", fake_check("stealth")),
                  mock.patch.object(gate_lint, "check_status_words", fake_check("status words")),
                  mock.patch.object(gate_lint, "resolve_slug", lambda item: None)):
            p.start()
            self.addCleanup(p.stop)

    def deck(self, **changes):
        d = copy.deepcopy(GOOD)
        for i, slide in changes.items():
            d["slides"][int(i)] = slide
        return d


class Check(Base):
    def assertRefused(self, d, fragment):
        problems = story.check(d, FACTS)
        self.assertTrue(any(fragment in p for p in problems), f"expected {fragment!r} in {problems}")

    def test_a_good_deck_passes(self):
        self.assertEqual(story.check(GOOD, FACTS), [])

    def test_an_invented_number_is_refused(self):
        d = self.deck(**{"1": dict(GOOD["slides"][1], points=["37 banks joined this week."])})
        self.assertRefused(d, "the number 37 is not in this run's facts")

    def test_small_counts_and_numbers_in_the_facts_pass(self):
        d = self.deck(**{"1": dict(GOOD["slides"][1], points=["8 posts wait; 3 days to go."])})
        self.assertEqual(story.check(d, FACTS), [])

    def test_shape_rules(self):
        self.assertRefused({"slides": GOOD["slides"][:3]}, "5 to 9 slides")
        moved = copy.deepcopy(GOOD)
        moved["slides"].insert(0, moved["slides"].pop(1))
        self.assertRefused(moved, "slide 1 is the cover")
        no_state = copy.deepcopy(GOOD)
        no_state["slides"][1] = {"kind": "explore", "title": "Worth a look", "items": [{"text": "x", "why": "y"}]}
        self.assertRefused(no_state, "a `state` slide")
        many = copy.deepcopy(GOOD)
        many["slides"][2:2] = [dict(GOOD["slides"][3], question=f"Question {n}?") for n in range(3)]
        self.assertRefused(many, "at most 3 question slides")
        self.assertRefused(self.deck(**{"2": {"kind": "chart", "title": "x"}}), "kind is one of")
        self.assertRefused(self.deck(**{"4": {"kind": "add", "title": "Add", "items": [{"text": "x", "kind": "wish"}]}}), "an `add` item's kind")

    def test_big_and_short(self):
        long = " ".join(["word"] * 13)
        self.assertRefused(self.deck(**{"0": dict(GOOD["slides"][0], title=long)}), "the title has 13 words")
        four = dict(GOOD["slides"][1], points=["a", "b", "c", "d"])
        self.assertRefused(self.deck(**{"1": four}), "at most 3 points")

    def test_the_denylist_applies(self):
        d = self.deck(**{"2": {"kind": "discoveries", "title": "Found", "items": [{"text": "We met Umbra Capital."}]}})
        self.assertRefused(d, "stealth")


class PublishAndAnswer(Base):
    def test_questions_get_ids_and_answers_are_kept(self):
        s = story.publish(copy.deepcopy(GOOD), FACTS)
        qid = next(x["id"] for x in s["slides"] if x["kind"] == "question")
        self.assertEqual(qid, "Q-2026-11-06-1")
        latest = json.load(open(os.path.join(self.dir, "latest.json"), encoding="utf-8"))
        self.assertEqual(latest["run_id"], FACTS["run_id"])
        q = story.load_questions()["questions"]
        self.assertEqual((q[0]["id"], q[0]["status"]), (qid, "open"))
        again = story.publish(copy.deepcopy(GOOD), dict(FACTS, run_id="20261107T190000Z", date="2026-11-07"))
        self.assertEqual(next(x["id"] for x in again["slides"] if x["kind"] == "question"), qid, "an open question keeps its id")
        self.assertEqual(len(story.load_questions()["questions"]), 1)
        path = os.path.join(self.dir, "questions.json")
        with self.assertRaises(story.control.Conflict):
            story.answer(qid, "Keep it", "stale")
        with self.assertRaises(story.control.Refused):
            story.answer(qid, "  ", story.control.digest(path))
        story.answer(qid, "Keep it", story.control.digest(path))
        q = story.load_questions()["questions"][0]
        self.assertEqual((q["status"], q["answer"]), ("answered", "Keep it"))
        with self.assertRaises(story.control.Refused):
            story.answer("Q-none", "x", story.control.digest(path))

    def test_a_deck_that_fails_its_check_is_not_published(self):
        bad = copy.deepcopy(GOOD)
        bad["slides"][1]["points"] = ["99 banks joined."]
        with self.assertRaises(story.StoryError):
            story.publish(bad, FACTS)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "latest.json")))


class Responses(Base):
    def setUp(self):
        super().setUp()
        self.story = story.publish(copy.deepcopy(GOOD), FACTS)

    def base(self, name):
        return story.control.digest(os.path.join(self.dir, name))

    def test_any_slide_takes_an_action_a_note_or_both(self):
        story.respond(FACTS["run_id"], 1, "Looks right", "", self.base("responses.json"))
        story.respond(FACTS["run_id"], 2, "", "Say more about the banks.", self.base("responses.json"))
        story.respond(FACTS["run_id"], 1, "Something is off", "Eight is too many.", self.base("responses.json"))
        rows = story.load_responses()["responses"]
        self.assertEqual(len(rows), 2, "a second response to the same slide replaces the first")
        mine = {r["slide"]: r for r in rows}
        self.assertEqual((mine[1]["action"], mine[1]["text"], mine[1]["kind"]), ("Something is off", "Eight is too many.", "state"))
        self.assertEqual(mine[2]["about"], "What we found")

    def test_refusals(self):
        b = self.base("responses.json")
        for args, why in (((FACTS["run_id"], 1, "", "", b), "pick an action"), (("old-run", 1, "x", "", b), "not the latest"),
                          ((FACTS["run_id"], 42, "x", "", b), "no such slide")):
            with self.subTest(why=why), self.assertRaises(story.control.Refused) as e:
                story.respond(*args)
            self.assertIn(why, str(e.exception))
        with self.assertRaises(story.control.Refused):
            story.respond(FACTS["run_id"], 2, "Add it", "", b, item=5)
        with self.assertRaises(story.control.Conflict):
            story.respond(FACTS["run_id"], 1, "x", "", "stale")

    def test_the_closing_frame_feeds_the_next_story_and_every_session(self):
        story.give_feedback(FACTS["run_id"], "too long", "More on the banks.", "Never lead with accounts.", self.base("feedback.json"))
        with self.assertRaises(story.control.Refused):
            story.give_feedback(FACTS["run_id"], "brilliant", "", "", self.base("feedback.json"))
        with self.assertRaises(story.control.Refused):
            story.give_feedback(FACTS["run_id"], "", "", "", self.base("feedback.json"))
        notes = story.remember_notes()
        self.assertEqual(notes[0]["note"], "Never lead with accounts.")
        import session_brief
        lines = session_brief.story_lines(self._state())
        self.assertIn("the owner rated it: too long", lines)
        self.assertTrue(any("always remember" in l and "Never lead with accounts." in l for l in lines))

    def _state(self):
        # session_brief reads <state>/story/: give it this test's story directory as that.
        state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, state, True)
        shutil.copytree(self.dir, os.path.join(state, "story"))
        return state

    def test_handles_on_add_items_must_be_suggested_accounts(self):
        f = dict(FACTS, accounts={"top_suggestions": [{"handle": "@realbank"}]})
        d = copy.deepcopy(GOOD)
        d["slides"][4] = {"kind": "add", "title": "Worth adding", "items": [{"text": "Watch it", "kind": "account", "handle": "@madeup"}]}
        self.assertTrue(any("not one of this run's suggested accounts" in p for p in story.check(d, f)))
        d["slides"][4]["items"][0]["handle"] = "@realbank"
        self.assertEqual(story.check(d, f), [])
        d["slides"][4]["actions"] = ["a", "b", "c", "d"]
        self.assertTrue(any("at most 3 actions" in p for p in story.check(d, f)))


class Genome(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.file = os.path.join(self.dir, "brand-genome.json")

    def write(self, data):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return genome.load(file=self.file)

    def test_defaults_fill_what_the_file_leaves_out(self):
        g = self.write({"name": "Acme", "colors": {"primary": "#123456"}})
        self.assertEqual(g["colors"]["primary"], "#123456")
        self.assertEqual(g["colors"]["accent"], genome.DEFAULT["colors"]["accent"])
        self.assertEqual(g["name"], "Acme")

    def test_bad_values_fall_back(self):
        g = self.write({"colors": {"primary": "navy", "accent": "#12345"}, "shape": {"radius": "round"}})
        self.assertEqual(g["colors"]["primary"], genome.DEFAULT["colors"]["primary"])
        self.assertEqual(g["colors"]["accent"], genome.DEFAULT["colors"]["accent"])
        self.assertEqual(g["shape"]["radius"], genome.DEFAULT["shape"]["radius"])

    def test_a_logo_that_could_run_is_dropped(self):
        g = self.write({"logo": {"on_dark": '<svg onload="x()"></svg>', "on_light": "<svg><script>x()</script></svg>"}})
        self.assertEqual(g["logo"], {"on_light": "", "on_dark": ""})
        g = self.write({"logo": {"on_dark": '<svg viewBox="0 0 1 1"><rect/></svg>'}})
        self.assertTrue(g["logo"]["on_dark"].startswith("<svg"))

    def test_the_palette_is_checked_and_its_roles_resolve(self):
        g = self.write({"palette": {"colors": [{"name": "Sea", "hex": "#43aa8b"}, {"name": "Bad", "hex": "teal"}, "f94144"],
                                    "roles": {"good": "Sea", "critical": "#f94144", "nonsense": "Sea"}}})
        self.assertEqual([c["hex"] for c in g["palette"]["colors"]], ["#43aa8b", "#f94144"], "a colour that is not hex is dropped; a bare hex gets its #")
        self.assertEqual(g["palette"]["roles"]["good"], "#43aa8b")
        self.assertEqual(g["palette"]["roles"]["critical"], "#f94144", "a role may name a colour by its hex")
        self.assertNotIn("nonsense", g["palette"]["roles"], "only the known roles")
        self.assertEqual(set(g["palette"]["roles"]), {"critical", "warning", "good", "action", "info"}, "a role the file leaves out keeps its default")
        self.assertEqual(g["palette"]["style"], "pastel", "pastel unless the file says solid")
        self.assertEqual(self.write({"palette": {"style": "solid"}})["palette"]["style"], "solid")
        self.assertEqual(self.write({"palette": {"style": "neon"}})["palette"]["style"], "pastel")
        self.assertEqual(self.write({"palette": {"roles": {"good": "12a150"}}})["palette"]["roles"]["good"], "#12a150")
        g = self.write({"palette": {"colors": ["nothing"]}})
        self.assertEqual(g["palette"]["colors"], genome.DEFAULT["palette"]["colors"], "no colour that reads: the default palette")

    def test_the_control_page_radius_is_its_own_and_clamped(self):
        g = self.write({"shape": {"radius": 0, "ui_radius": 99}})
        self.assertEqual((g["shape"]["radius"], g["shape"]["ui_radius"]), (0, 32))
        self.assertEqual(self.write({})["shape"]["ui_radius"], genome.DEFAULT["shape"]["ui_radius"])

    def test_a_missing_file_is_the_defaults(self):
        g = genome.load(file=os.path.join(self.dir, "none.json"))
        self.assertEqual(g["colors"], genome.DEFAULT["colors"])
        self.assertIn("--brand-primary:", genome.css(g))


if __name__ == "__main__":
    unittest.main()
